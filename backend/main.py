import json
import logging
import os
import shutil
import sys
import time
import uuid
from collections import deque
from queue import Empty, Queue
from threading import Thread
from typing import Any
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

from backend.config import load_settings
from backend.agent import make_tool_exec, route_and_chat
from backend.ingest import ingest_file_for_rag
from backend.embeddings import make_gemini_embedding_fn
from backend.rag_store import RagStore
from backend.util import chunk_text, ensure_dir
from backend.conversation_store import ConversationStore
from backend.translate import translate_document, SEPARATOR_PRESETS
from backend.auth import (
    github_oauth_callback,
    github_oauth_start,
    logout_response,
    password_login,
    authenticate_request,
    require_auth,
)
from backend.rate_limit import InMemorySlidingWindow, UpstashFixedWindow
from backend.security import get_request_ip


class _BroadcastHandler(logging.Handler):
    """Keeps a ring-buffer of recent log records and notifies SSE subscribers."""
    def __init__(self, maxlen: int = 500):
        super().__init__()
        self._buf: deque[str] = deque(maxlen=maxlen)
        self._queues: list[deque] = []
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            self._buf.append(line)
            for q in self._queues:
                q.append(line)
        except Exception:
            pass

    def subscribe(self) -> deque:
        q: deque = deque()
        # replay recent history
        q.extend(self._buf)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: deque) -> None:
        try:
            self._queues.remove(q)
        except ValueError:
            pass


_broadcast_handler = _BroadcastHandler(maxlen=500)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), _broadcast_handler],
)
logger = logging.getLogger("calling.main")

try:
    from fastapi.staticfiles import StaticFiles
except Exception:  # pragma: no cover
    StaticFiles = None  # type: ignore


def _trim_conversation(messages: list[dict[str, Any]], max_user_turns: int = 20) -> list[dict[str, Any]]:
    # Keep last N user messages and all assistant messages following them.
    user_msgs = [m for m in messages if m.get("role") == "user"]
    if len(user_msgs) <= max_user_turns:
        return messages

    # Find the index of the user message that will become the oldest in window.
    target_user_count = max_user_turns
    seen = 0
    start_idx = 0
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            seen += 1
            if seen > target_user_count:
                start_idx = i + 1
                break
    return messages[start_idx:]


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return (m.get("content") or "").strip()
    return ""


def build_system_prompt(*, force_web_search: bool, rag_enabled: bool) -> str:
    lines = [
        "You are a helpful assistant.",
        "Use tools when needed.",
        "If you use web_search, incorporate the retrieved facts into your answer.",
        "If you use read_file, cite relevant content from it when it helps.",
    ]
    if force_web_search:
        lines.append("Requirement: you MUST call the `web_search` tool at least once before giving a final answer.")
    if rag_enabled:
        lines.append("If RAG context is provided, use it when answering.")
    return "\n".join(lines)


def make_tools(*, max_read_chars: int = 20000, max_search_results: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the public web (no site restrictions). Return relevant snippets and links.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query."},
                        "max_results": {
                            "type": "integer",
                            "description": f"Max results to return (1..10). Default {max_search_results}.",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file from the Calling project directory (relative paths only). Use '__TREE__' to get a project tree.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path under the Calling project root, or '__TREE__'.",
                        }
                    },
                    "required": ["path"],
                },
            },
        },
    ]


def _tool_defs_impl(project_root_abs: str):
    # returns closures used for tool execution
    def exec_web_search(args: dict[str, Any]):
        return web_search_tool(
            args.get("query", ""),
            max_results=args.get("max_results") or 5,
        )

    def exec_read_file(args: dict[str, Any]):
        return read_file_tool(
            project_root_abs=project_root_abs,
            relative_path=args.get("path", ""),
        )

    return {"web_search": exec_web_search, "read_file": exec_read_file}


def create_app() -> FastAPI:
    settings = load_settings()
    ensure_dir(settings.uploads_dir)

    project_root = settings.project_root
    uploads_dir = settings.uploads_dir

    rag_store = RagStore(settings.rag_db_path)
    conversation_store = ConversationStore(os.path.join(settings.data_dir, "conversations.json"))
    embedding_fn = None
    if settings.gemini_api_key:
        embedding_fn = make_gemini_embedding_fn(gemini_api_key=settings.gemini_api_key)

    app = FastAPI(title="Calling - Minimal Agent")

    # ----------------------------
    # Auth + Rate limit guard (protect /api/*)
    # ----------------------------
    mem_rl = InMemorySlidingWindow()
    upstash_rl = None
    if settings.upstash_redis_rest_url and settings.upstash_redis_rest_token:
        upstash_rl = UpstashFixedWindow(
            rest_url=settings.upstash_redis_rest_url,
            rest_token=settings.upstash_redis_rest_token,
        )

    def _rl_allow(key: str, limit: int, window_seconds: int = 60):
        if upstash_rl is not None:
            return upstash_rl.allow(key, limit=limit, window_seconds=window_seconds)
        return mem_rl.allow(key, limit=limit, window_seconds=window_seconds)

    @app.middleware("http")
    async def _auth_and_rate_limit(request: Request, call_next):
        path = request.url.path or ""
        if not path.startswith("/api/"):
            return await call_next(request)

        # allow CORS preflight
        if request.method == "OPTIONS":
            return await call_next(request)

        # public endpoints
        if path in ("/api/health",):
            return await call_next(request)
        if path.startswith("/api/auth/"):
            # basic IP limiter for auth endpoints
            ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or "unknown"
            d = _rl_allow(f"rl:auth:ip:{ip}", limit=max(10, settings.rate_limit_per_ip_per_min // 3))
            if not d.allowed:
                return JSONResponse(
                    {"detail": "Too many auth attempts. Please wait."},
                    status_code=429,
                    headers={"Retry-After": str(d.reset_in_seconds or 60)},
                )
            return await call_next(request)

        # Trial endpoints: allow unauthenticated access with strict limits
        trial_paths = ("/api/models", "/api/chat", "/api/chat/stream")
        auth_mode = (settings.auth_mode or "none").strip().lower()
        ip = get_request_ip(dict(request.headers), fallback="unknown")

        ar = authenticate_request(request, settings=settings)
        authed = bool(ar.ok)
        request.state.authed = authed
        request.state.trial = False

        if auth_mode != "none" and (not authed) and path in trial_paths:
            request.state.trial = True
            # very strict per-ip limiter for trial
            d_trial = _rl_allow(f"rl:trial:ip:{ip}", limit=max(3, int(settings.rate_limit_per_ip_per_min // 6)))
            if not d_trial.allowed:
                return JSONResponse(
                    {"detail": "Rate limited (trial)."},
                    status_code=429,
                    headers={"Retry-After": str(d_trial.reset_in_seconds or 60)},
                )
            # global quota: shared across everyone (best with Upstash; otherwise per-instance)
            # Count only chat requests (models endpoint should not consume quota).
            if path in ("/api/chat", "/api/chat/stream"):
                d_global = _rl_allow("rl:trial:global", limit=max(1, int(settings.trial_global_per_hour)), window_seconds=3600)
                if not d_global.allowed:
                    return JSONResponse(
                        {"detail": "Trial quota exhausted. Please login or try again later."},
                        status_code=429,
                        headers={"Retry-After": str(d_global.reset_in_seconds or 3600)},
                    )
            return await call_next(request)

        # everything else under /api requires auth (when auth enabled)
        if auth_mode != "none":
            try:
                ar = require_auth(request, settings=settings)
            except HTTPException as e:
                return JSONResponse({"detail": e.detail}, status_code=e.status_code)

        uid = (ar.user_id or "user") if authed else "anon"

        d_ip = _rl_allow(f"rl:ip:{ip}", limit=max(5, int(settings.rate_limit_per_ip_per_min)))
        if not d_ip.allowed:
            return JSONResponse(
                {"detail": "Rate limited (ip)."},
                status_code=429,
                headers={"Retry-After": str(d_ip.reset_in_seconds or 60)},
            )

        d_u = _rl_allow(f"rl:user:{uid}", limit=max(5, int(settings.rate_limit_per_user_per_min)))
        if not d_u.allowed:
            return JSONResponse(
                {"detail": "Rate limited (user)."},
                status_code=429,
                headers={"Retry-After": str(d_u.reset_in_seconds or 60)},
            )

        return await call_next(request)

    # Static GUI (serve / as index.html; serve /static/* for assets)
    if StaticFiles is not None:
        frontend_dir = os.path.join(project_root, "frontend")
        static_dir = os.path.join(frontend_dir, "static")
        if os.path.exists(frontend_dir):
            index_path = os.path.join(frontend_dir, "index.html")
            if os.path.exists(index_path):
                @app.get("/", include_in_schema=False)
                async def api_index(request: Request):
                    # Always serve the same UI; auth/trial rules are enforced on /api/*.
                    return FileResponse(index_path)

            if os.path.exists(static_dir):
                app.mount("/static", StaticFiles(directory=static_dir), name="static")

    tool_exec = make_tool_exec(project_root)

    @app.get("/api/health")
    def api_health():
        return {"ok": True}

    # ----------------------------
    # Auth endpoints (cookie sessions)
    # ----------------------------
    @app.get("/api/auth/me")
    def api_auth_me(request: Request):
        ar = require_auth(request, settings=settings)
        return {"ok": True, "user_id": ar.user_id, "login": ar.user_login, "method": ar.method}

    @app.get("/api/auth/logout")
    def api_auth_logout(request: Request):
        return logout_response(request)

    @app.post("/api/auth/password")
    async def api_auth_password(request: Request, payload: dict[str, Any] | None = None):
        if payload is None:
            payload = {}
        pw = (payload.get("password") or "").strip()
        device = (request.headers.get("x-calling-device") or "").strip() or None
        return password_login(request, settings=settings, password=pw, device=device)

    @app.get("/api/auth/github/start")
    def api_auth_github_start(request: Request):
        return github_oauth_start(request, settings=settings)

    @app.get("/api/auth/github/callback")
    def api_auth_github_callback(request: Request):
        return github_oauth_callback(request, settings=settings)

    def _run_chat(payload: dict[str, Any]) -> dict[str, Any]:
        model = payload.get("model") or settings.default_chat_model
        conversation_id = payload.get("conversation_id") or "default"
        messages = payload.get("messages") or []
        rag_enabled = bool(payload.get("rag_enabled"))
        force_web_search = bool(payload.get("force_web_search"))
        uploaded_files = payload.get("uploaded_files") or []
        continue_from = (payload.get("continue_from") or "").strip()
        user_system_prompt = (payload.get("system_prompt") or "").strip()

        if not isinstance(messages, list) or not messages:
            raise HTTPException(status_code=400, detail="messages must be a non-empty list")
        if rag_enabled and uploaded_files and not isinstance(uploaded_files, list):
            raise HTTPException(status_code=400, detail="uploaded_files must be a list")

        work_messages = list(messages)
        if continue_from:
            work_messages.append({"role": "user", "content": continue_from})

        trimmed = _trim_conversation(work_messages, max_user_turns=20)
        latest_user = _latest_user_text(trimmed)
        if not latest_user and any(m.get("role") == "user" for m in trimmed) is False:
            raise HTTPException(status_code=400, detail="No user content found")

        rag_context = ""
        retrieved: list[dict[str, Any]] = []

        if rag_enabled:
            if uploaded_files:
                if embedding_fn is None:
                    raise HTTPException(status_code=400, detail="RAG enabled but GEMINI_API_KEY (embedding) missing.")

                for rel_path in uploaded_files:
                    if not rag_store.file_has_chunks(rel_path):
                        abs_path = os.path.join(project_root, rel_path)
                        if os.path.exists(abs_path):
                            with open(abs_path, "rb") as fp:
                                raw = fp.read()
                            ingest_file_for_rag(
                                rag_store=rag_store,
                                relative_file_path=rel_path,
                                mime_type=None,
                                file_bytes=raw,
                                embedding_fn=embedding_fn,
                                chunk_size=settings.rag_chunk_size,
                                chunk_overlap=settings.rag_chunk_overlap,
                            )

                q_emb = embedding_fn(latest_user[:4000])
                hits = rag_store.search(
                    query_embedding=q_emb,
                    file_paths=uploaded_files,
                    top_k=settings.rag_top_k,
                    threshold=None,
                )
                parts: list[str] = []
                for chunk, score in hits:
                    snippet = chunk.text
                    if len(snippet) > 2000:
                        snippet = snippet[:2000]
                    parts.append(
                        f"[{chunk.file_path} :: chunk#{chunk.chunk_index} :: sim={score:.4f}]\n{snippet}"
                    )
                    retrieved.append(
                        {
                            "file_path": chunk.file_path,
                            "chunk_index": chunk.chunk_index,
                            "score": score,
                            "chars": len(snippet),
                        }
                    )
                rag_context = "\n\n".join(parts)

        system_prompt = build_system_prompt(force_web_search=force_web_search, rag_enabled=rag_enabled)
        if user_system_prompt:
            system_prompt += f"\n\n{user_system_prompt}"
        if rag_enabled and rag_context.strip():
            system_prompt += f"\n\nRAG_CONTEXT:\n{rag_context}"

        r = route_and_chat(
            settings=settings,
            model=model,
            system_prompt=system_prompt,
            messages=trimmed,
            tool_exec=tool_exec,
            force_web_search=force_web_search,
            project_root_abs=project_root,
        )

        content = r.get("answer") or ""
        thinking = r.get("thinking") or ""
        used_web_search = bool(r.get("used_web_search"))
        if force_web_search and not used_web_search:
            raise HTTPException(status_code=400, detail="force_web_search enabled but web_search was not called.")

        full_messages = (work_messages or []) + [
            {"role": "assistant", "content": content, "model": model, "thinking": thinking}
        ]
        conversation_store.upsert_messages(conversation_id, full_messages)
        conversation_store.set_uploaded_files(conversation_id, uploaded_files)

        return {
            "conversation_id": conversation_id,
            "assistant": content,
            "thinking": thinking,
            "rag_enabled": rag_enabled,
            "rag_used": bool(rag_context.strip()),
            "retrieved_chunks": retrieved,
            "web_search_called": used_web_search,
            "model": model,
        }

    @app.get("/api/models")
    def api_models(request: Request):
        # Trial mode: expose ONLY the free model
        if getattr(request.state, "trial", False):
            return {"default": settings.trial_model, "options": [settings.trial_model], "trial_only": True}

        claude_models = [
            "claude-opus-4-6-thinking",
            "claude-opus-4-6",
            "claude-3-5-sonnet-20241022",
            "claude-3-opus-20240229",
        ]
        gemini_models = [
            "gemini-3.1-pro-preview",
            "gemini-2.5-pro",
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
        ]
        grok_models = [
            "grok-4-1-fast-non-reasoning",
            "grok-4-1-fast-reasoning",
        ]
        # Keep it flat for UI: one selector can accept any supported model id.
        options = sorted(set([settings.trial_model] + claude_models + gemini_models + grok_models + [settings.default_chat_model]))
        # Default model: always trial model (safety against accidental paid calls)
        return {"default": settings.trial_model, "options": options, "trial_only": False}

    @app.post("/api/conversations/new")
    def api_new_conversation():
        conv = conversation_store.create_new()
        return {"conversation_id": conv.conversation_id}

    @app.get("/api/conversations")
    def api_list_conversations():
        return {"conversations": conversation_store.list_conversations()}

    @app.get("/api/conversations/{conversation_id}")
    def api_get_conversation(conversation_id: str):
        try:
            conv = conversation_store.get(conversation_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="conversation not found")
        return {
            "conversation_id": conv.conversation_id,
            "title": conv.title,
            "messages": conv.messages,
            "uploaded_files": conv.uploaded_files,
        }

    @app.delete("/api/conversations/{conversation_id}")
    def api_delete_conversation(conversation_id: str):
        ok = conversation_store.delete_conversation(conversation_id)
        if not ok:
            raise HTTPException(status_code=404, detail="conversation not found")
        return {"deleted": True, "conversation_id": conversation_id}

    @app.post("/api/conversations/fork")
    def api_fork_conversation(payload: dict[str, Any]):
        source_conversation_id = (payload.get("conversation_id") or "").strip()
        fork_messages = payload.get("messages")
        uploaded = payload.get("uploaded_files") or []
        if not source_conversation_id:
            raise HTTPException(status_code=400, detail="conversation_id is required")
        if not isinstance(fork_messages, list):
            raise HTTPException(status_code=400, detail="messages must be a list")
        try:
            src = conversation_store.get(source_conversation_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="source conversation not found")

        new_conv = conversation_store.create_new()
        conversation_store.upsert_messages(new_conv.conversation_id, fork_messages)
        conversation_store.set_uploaded_files(new_conv.conversation_id, uploaded or list(src.uploaded_files or []))
        return {"conversation_id": new_conv.conversation_id}

    @app.post("/api/upload")
    async def api_upload(
        request: Request,
        files: list[UploadFile] = File(...),
        rag_enable: str = Form("false"),
        conversation_id: str = Form(""),
    ):
        conversation_id = (conversation_id or "").strip()
        if not conversation_id:
            conversation_id = "default"

        rag_enable_bool = rag_enable.lower() in ("1", "true", "yes", "on")
        uploaded: list[dict[str, Any]] = []
        # Keep conversation uploaded list in sync
        try:
            conv = conversation_store.get(conversation_id)
            current_uploaded = list(conv.uploaded_files or [])
        except KeyError:
            current_uploaded = []

        embedding_for_upload = embedding_fn if (rag_enable_bool and embedding_fn is not None) else None
        for f in files:
            orig_name = os.path.basename(f.filename or "upload")
            upload_id = uuid.uuid4().hex[:12]
            safe_name = orig_name.replace("\\", "_").replace("/", "_")
            relative_path = os.path.join("data", "uploads", f"{upload_id}_{safe_name}").replace("\\", "/")
            abs_path = os.path.join(project_root, relative_path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)

            raw = await f.read()
            with open(abs_path, "wb") as out:
                out.write(raw)

            embedded = False
            embedded_info: dict[str, Any] | None = None
            if rag_enable_bool and embedding_for_upload:
                embedded_info = ingest_file_for_rag(
                    rag_store=rag_store,
                    relative_file_path=relative_path,
                    mime_type=f.content_type,
                    file_bytes=raw,
                    embedding_fn=embedding_for_upload,
                    chunk_size=settings.rag_chunk_size,
                    chunk_overlap=settings.rag_chunk_overlap,
                )
                embedded = bool(embedded_info.get("embedded"))
            elif rag_enable_bool and embedding_for_upload is None:
                embedded_info = {"embedded": False, "reason": "embedding model missing"}

            current_uploaded.append(relative_path)
            uploaded.append(
                {
                    "file_path": relative_path,
                    "file_name": orig_name,
                    "mime_type": f.content_type,
                    "embedded": embedded,
                    "ingest": embedded_info,
                }
            )

        conversation_store.set_uploaded_files(conversation_id, current_uploaded)
        return {"uploaded": uploaded}

    @app.post("/api/chat")
    async def api_chat(request: Request, payload: dict[str, Any]):
        try:
            if getattr(request.state, "trial", False):
                payload = dict(payload or {})
                payload["model"] = settings.trial_model
                payload["rag_enabled"] = False
                payload["force_web_search"] = False
                payload["uploaded_files"] = []
                payload["conversation_id"] = f"trial:{get_request_ip(dict(request.headers), fallback='unknown')}"
            return JSONResponse(_run_chat(payload))
        except HTTPException as e:
            return JSONResponse({"detail": e.detail}, status_code=e.status_code)
        except Exception as e:
            return JSONResponse({"detail": str(e)}, status_code=500)

    @app.post("/api/chat/stream")
    async def api_chat_stream(request: Request, payload: dict[str, Any]):
        import asyncio

        if getattr(request.state, "trial", False):
            payload = dict(payload or {})
            payload["model"] = settings.trial_model
            payload["rag_enabled"] = False
            payload["force_web_search"] = False
            payload["uploaded_files"] = []
            payload["conversation_id"] = f"trial:{get_request_ip(dict(request.headers), fallback='unknown')}"

        def _sse(event: str, data: Any) -> str:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        async def event_stream():
            q: Queue = Queue()

            def _worker():
                try:
                    q.put(("result", _run_chat(payload)))
                except HTTPException as e:
                    q.put(("http_error", {"detail": e.detail, "status_code": e.status_code}))
                except Exception as e:
                    q.put(("error", {"detail": str(e)}))

            started_at = time.time()
            Thread(target=_worker, daemon=True).start()
            yield _sse("status", {"stage": "started", "message": "Assistant is thinking..."})

            while True:
                try:
                    kind, data = q.get_nowait()
                except Empty:
                    elapsed = int((time.time() - started_at) * 1000)
                    yield _sse(
                        "thinking_delta",
                        {"text": f"思考中... {elapsed / 1000:.1f}s", "transient": True, "elapsed_ms": elapsed},
                    )
                    await asyncio.sleep(0.35)
                    continue

                if kind == "http_error":
                    yield _sse("error", {"detail": data.get("detail"), "status_code": data.get("status_code", 400)})
                    return
                if kind == "error":
                    yield _sse("error", {"detail": data.get("detail"), "status_code": 500})
                    return

                thinking = (data.get("thinking") or "").strip()
                assistant = data.get("assistant") or ""
                if thinking:
                    for i in range(0, len(thinking), 120):
                        yield _sse("thinking_delta", {"text": thinking[i : i + 120], "transient": False})
                        await asyncio.sleep(0.01)

                for i in range(0, len(assistant), 120):
                    yield _sse("answer_delta", {"text": assistant[i : i + 120]})
                    await asyncio.sleep(0.01)

                yield _sse("done", data)
                return

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


    @app.post("/api/convert/tex")
    async def api_convert_tex(
        payload: dict = None,
    ):
        """Convert Markdown text to LaTeX. Body: {md: str, title?: str, author?: str}"""
        try:
            from backend.md2latex import md_to_latex
            if payload is None:
                payload = {}
            md = payload.get("md") or ""
            title = payload.get("title") or ""
            author = payload.get("author") or ""
            if not md.strip():
                return JSONResponse({"error": "md field is empty"}, status_code=400)
            latex = md_to_latex(md, title=title, author=author)
            logger.info("[api/convert/tex] converted %d chars MD -> %d chars LaTeX", len(md), len(latex))
            return JSONResponse({"latex": latex})
        except Exception as e:
            logger.exception("[api/convert/tex] error: %s", e)
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.post("/api/convert/pdf")
    async def api_convert_pdf(
        payload: dict = None,
    ):
        """Convert Markdown text to PDF. Body: {md: str, title?: str, author?: str}"""
        try:
            from backend.md2latex import md_to_latex, compile_latex_to_pdf
            from fastapi.responses import Response
            if payload is None:
                payload = {}
            md = payload.get("md") or ""
            title = payload.get("title") or ""
            author = payload.get("author") or ""
            if not md.strip():
                return JSONResponse({"error": "md field is empty"}, status_code=400)
            latex = md_to_latex(md, title=title, author=author)
            logger.info("[api/convert/pdf] compiling PDF for %d chars LaTeX", len(latex))
            pdf_bytes = compile_latex_to_pdf(latex)
            logger.info("[api/convert/pdf] PDF size=%d bytes", len(pdf_bytes))
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": "attachment; filename=translated.pdf"},
            )
        except Exception as e:
            logger.exception("[api/convert/pdf] error: %s", e)
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/api/logs")
    async def api_logs(request: Request):
        """SSE stream of server log lines. Replays last 500 lines on connect."""
        import asyncio

        q = _broadcast_handler.subscribe()

        async def event_stream():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    if q:
                        line = q.popleft()
                        level = "INFO"
                        for lvl in ("ERROR", "WARNING", "DEBUG", "CRITICAL"):
                            if f"[{lvl}]" in line:
                                level = lvl
                                break
                        payload = json.dumps({"line": line, "level": level}, ensure_ascii=False)
                        yield f"data: {payload}\n\n"
                    else:
                        await asyncio.sleep(0.15)
            finally:
                _broadcast_handler.unsubscribe(q)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/server/shutdown")
    def api_server_shutdown():
        """Gracefully shut down the uvicorn server process."""
        import threading
        logger.info("[api/server/shutdown] shutdown requested via UI")
        def _do_shutdown():
            import time, os, signal
            time.sleep(0.5)
            os.kill(os.getpid(), signal.SIGTERM)
        threading.Thread(target=_do_shutdown, daemon=True).start()
        return JSONResponse({"shutdown": True, "message": "Server is shutting down."})

    @app.get("/api/translate/languages")
    def api_translate_languages():
        languages = [
            "Chinese (Simplified)", "Chinese (Traditional)", "English", "Japanese",
            "Korean", "French", "German", "Spanish", "Portuguese", "Italian",
            "Russian", "Arabic", "Hindi", "Dutch", "Polish", "Turkish",
            "Vietnamese", "Thai", "Indonesian", "Swedish", "Norwegian",
            "Danish", "Finnish", "Czech", "Romanian", "Hungarian",
        ]
        return {"languages": languages, "separator_presets": list(SEPARATOR_PRESETS.keys()) + ["custom"]}

    @app.post("/api/translate")
    async def api_translate(
        file: UploadFile = File(...),
        model: str = Form(""),
        target_lang: str = Form("English"),
        source_lang: str = Form(""),
        split_mode: str = Form("separator"),
        separator_preset: str = Form("paragraph"),
        custom_separators: str = Form(""),
        parent_max_chars: int = Form(3000),
        child_max_chars: int = Form(800),
        llm_split_model: str = Form(""),
    ):
        try:
            _model = (model or "").strip() or settings.default_chat_model
            _target = (target_lang or "").strip() or "English"
            _source = (source_lang or "").strip() or None
            _split_mode = (split_mode or "separator").strip()
            _sep_preset = (separator_preset or "paragraph").strip()
            _custom_seps = [s for s in (custom_separators or "").split("|") if s]
            _llm_split_model = (llm_split_model or "").strip() or None
            _parent_max = max(500, min(int(parent_max_chars), 12000))
            _child_max = max(200, min(int(child_max_chars), 6000))

            raw = await file.read()
            filename = os.path.basename(file.filename or "upload.txt")
            logger.info("[api/translate] file=%s model=%s target=%s", filename, _model, _target)

            result = translate_document(
                raw=raw,
                filename=filename,
                settings=settings,
                model=_model,
                target_lang=_target,
                source_lang=_source,
                split_mode=_split_mode,
                separator_preset=_sep_preset,
                custom_separators=_custom_seps if _custom_seps else None,
                parent_max_chars=_parent_max,
                child_max_chars=_child_max,
                llm_split_model=_llm_split_model,
            )

            return JSONResponse(result)
        except Exception as e:
            logger.exception("[api/translate] error: %s", e)
            return JSONResponse({"error": str(e)}, status_code=500)

    # Active translation jobs: job_id -> {"abort": bool}
    _translate_jobs: dict[str, dict] = {}

    @app.post("/api/translate/stream")
    async def api_translate_stream(
        file: UploadFile = File(...),
        model: str = Form(""),
        target_lang: str = Form("English"),
        source_lang: str = Form(""),
        split_mode: str = Form("separator"),
        separator_preset: str = Form("paragraph"),
        custom_separators: str = Form(""),
        parent_max_chars: int = Form(2000),
        child_max_chars: int = Form(2000),
        llm_split_model: str = Form(""),
        job_id: str = Form(""),
    ):
        _model = (model or "").strip() or settings.default_chat_model
        _target = (target_lang or "").strip() or "English"
        _source = (source_lang or "").strip() or None
        _split_mode = (split_mode or "separator").strip()
        _sep_preset = (separator_preset or "paragraph").strip()
        _custom_seps = [s for s in (custom_separators or "").split("|") if s]
        _llm_split_model = (llm_split_model or "").strip() or None
        _chunk_max = max(500, min(max(int(parent_max_chars), int(child_max_chars)), 12000))
        _job_id = (job_id or "").strip() or uuid.uuid4().hex[:12]

        raw = await file.read()
        filename = os.path.basename(file.filename or "upload.txt")
        logger.info("[stream] job=%s file=%s model=%s target=%s chunk_max=%d",
                    _job_id, filename, _model, _target, _chunk_max)

        job_state = {"abort": False}
        _translate_jobs[_job_id] = job_state

        def _sse(event: str, data: Any) -> str:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        def run_translation():
            from backend.translate import (
                file_to_markdown, _split_markdown, llm_split_text,
                translate_chunk, verify_chunks,
                SEPARATOR_PRESETS, DEFAULT_CHUNK_MAX_CHARS,
            )

            yield _sse("start", {"job_id": _job_id, "filename": filename})

            # Step 1: Convert to Markdown
            try:
                md_text = file_to_markdown(raw, filename)
            except Exception as e:
                logger.error("[stream] extract error: %s", e)
                yield _sse("error", {"message": f"Extraction failed: {e}"})
                return

            if not md_text.strip():
                yield _sse("error", {"message": "Could not extract text from file."})
                return

            yield _sse("progress", {"stage": "extracted", "chars": len(md_text)})
            logger.info("[stream] job=%s extracted %d chars", _job_id, len(md_text))

            # Step 2: Split
            try:
                if _split_mode == "llm":
                    split_model = _llm_split_model or _model
                    def _call_llm(prompt):
                        return translate_chunk(prompt, settings, split_model,
                                              target_lang="English", source_lang=None)
                    chunks, integrity = llm_split_text(
                        md_text, call_llm=_call_llm, max_chars=_chunk_max)
                else:
                    chunks = _split_markdown(md_text, _chunk_max)
                    integrity = verify_chunks(md_text, chunks)
            except Exception as e:
                logger.error("[stream] split error: %s", e)
                yield _sse("error", {"message": f"Splitting failed: {e}"})
                return

            total = len(chunks)
            yield _sse("progress", {
                "stage": "split", "total": total,
                "integrity": integrity,
                "integrity_ok": integrity.get("ok", True),
            })
            logger.info("[stream] job=%s split=%d integrity=%s", _job_id, total, integrity)

            if not integrity.get("ok", True):
                logger.warning("[stream] job=%s low coverage=%.2f",
                               _job_id, integrity.get("coverage", 0))

            # Step 3: Translate each chunk (skip reference section onwards)
            from backend.translate import detect_reference_section
            translated_parts = []
            in_references = False
            for i, chunk in enumerate(chunks):
                if job_state.get("abort"):
                    logger.info("[stream] job=%s aborted at chunk %d/%d", _job_id, i+1, total)
                    yield _sse("aborted", {"done": i, "total": total})
                    return

                # Detect reference section
                if not in_references:
                    if detect_reference_section(chunk, settings, _model):
                        in_references = True
                        logger.info("[stream] job=%s ref section at chunk %d/%d", _job_id, i+1, total)

                is_ref = in_references
                yield _sse("chunk_start", {
                    "index": i, "total": total,
                    "chars": len(chunk),
                    "sub_count": 1,
                    "preview": chunk[:60],
                    "skipped": is_ref,
                })
                logger.info("[stream] job=%s chunk %d/%d chars=%d skipped=%s",
                            _job_id, i+1, total, len(chunk), is_ref)

                if is_ref:
                    t = chunk  # pass through verbatim
                else:
                    try:
                        t = translate_chunk(chunk, settings, _model,
                                           target_lang=_target, source_lang=_source)
                    except Exception as e:
                        logger.error("[stream] job=%s chunk %d error: %s", _job_id, i+1, e)
                        yield _sse("error", {"message": f"Chunk {i+1}/{total} failed: {e}"})
                        return

                translated_parts.append(t)
                yield _sse("chunk_done", {
                    "index": i, "total": total,
                    "text": t,
                    "percent": round((i + 1) / total * 100),
                    "skipped": is_ref,
                })

            result_text = "\n\n".join(translated_parts)
            logger.info("[stream] job=%s complete output=%d chars", _job_id, len(result_text))
            yield _sse("done", {
                "translated_text": result_text,
                "chunks_total": total,
                "filename": filename,
                "integrity": integrity,
            })
            _translate_jobs.pop(_job_id, None)

        return StreamingResponse(
            run_translation(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/translate/abort/{job_id}")
    def api_translate_abort(job_id: str):
        job = _translate_jobs.get(job_id)
        if job is None:
            return JSONResponse({"aborted": False, "reason": "job not found"}, status_code=404)
        job["abort"] = True
        logger.info("[api/translate/abort] job=%s abort requested", job_id)
        return JSONResponse({"aborted": True, "job_id": job_id})

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    settings = load_settings()
    uvicorn.run(app, host=settings.host, port=settings.port)

