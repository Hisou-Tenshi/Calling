import os
import shutil
import uuid
from typing import Any
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from backend.config import load_settings
from backend.agent import make_tool_exec, route_and_chat
from backend.ingest import ingest_file_for_rag
from backend.embeddings import make_gemini_embedding_fn
from backend.rag_store import RagStore
from backend.util import chunk_text, ensure_dir
from backend.conversation_store import ConversationStore

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

    # Static GUI (serve / as index.html; serve /static/* for assets)
    if StaticFiles is not None:
        frontend_dir = os.path.join(project_root, "frontend")
        static_dir = os.path.join(frontend_dir, "static")
        if os.path.exists(frontend_dir):
            index_path = os.path.join(frontend_dir, "index.html")
            if os.path.exists(index_path):
                @app.get("/")
                def api_index():
                    return FileResponse(index_path)

            if os.path.exists(static_dir):
                app.mount("/static", StaticFiles(directory=static_dir), name="static")

    tool_exec = make_tool_exec(project_root)

    @app.get("/api/models")
    def api_models():
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
        options = sorted(set(claude_models + gemini_models + grok_models + [settings.default_chat_model]))
        return {"default": settings.default_chat_model, "options": options}

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
    async def api_chat(payload: dict[str, Any]):
        try:
            model = payload.get("model") or settings.default_chat_model
            conversation_id = payload.get("conversation_id") or "default"
            messages = payload.get("messages") or []
            rag_enabled = bool(payload.get("rag_enabled"))
            force_web_search = bool(payload.get("force_web_search"))
            uploaded_files = payload.get("uploaded_files") or []

            if not isinstance(messages, list) or not messages:
                raise HTTPException(status_code=400, detail="messages must be a non-empty list")
            if rag_enabled and uploaded_files and not isinstance(uploaded_files, list):
                raise HTTPException(status_code=400, detail="uploaded_files must be a list")

            trimmed = _trim_conversation(messages, max_user_turns=20)
            latest_user = _latest_user_text(trimmed)
            if not latest_user and any(m.get("role") == "user" for m in trimmed) is False:
                raise HTTPException(status_code=400, detail="No user content found")

            rag_context = ""
            retrieved: list[dict[str, Any]] = []

            if rag_enabled:
                if not uploaded_files:
                    rag_context = ""
                else:
                    if embedding_fn is None:
                        raise HTTPException(status_code=400, detail="RAG enabled but GEMINI_API_KEY (embedding) missing.")

                    # Ensure requested files have embeddings. If not, ingest on-demand.
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
                            else:
                                # Keep going; retrieval will just be empty for that file.
                                pass

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
            used_web_search = bool(r.get("used_web_search"))
            if force_web_search and not used_web_search:
                raise HTTPException(status_code=400, detail="force_web_search enabled but web_search was not called.")

            full_messages = (messages or []) + [{"role": "assistant", "content": content, "model": model}]
            conversation_store.upsert_messages(conversation_id, full_messages)
            conversation_store.set_uploaded_files(conversation_id, uploaded_files)

            return JSONResponse(
                {
                    "conversation_id": conversation_id,
                    "assistant": content,
                    "rag_enabled": rag_enabled,
                    "rag_used": bool(rag_context.strip()),
                    "retrieved_chunks": retrieved,
                    "web_search_called": used_web_search,
                }
            )
        except HTTPException as e:
            return JSONResponse({"detail": e.detail}, status_code=e.status_code)
        except Exception as e:
            return JSONResponse({"detail": str(e)}, status_code=500)

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    settings = load_settings()
    uvicorn.run(app, host=settings.host, port=settings.port)

