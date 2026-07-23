import json
from collections.abc import Iterator
from typing import Any, Callable

import numpy as np
from anthropic import Anthropic
from google import genai
from google.genai import types
from openai import OpenAI
from openai import APIStatusError, APIConnectionError, APITimeoutError

from backend.claude_compat import (
    build_claude_request_kwargs,
    claude_messages_create,
    downgrade_claude_request_kwargs,
    should_skip_claude_client,
)
from backend.llm_routing import (
    build_claude_proxy_configs,
    build_gemini_paths_from_settings,
    build_grok_paths_from_settings,
    build_openrouter_paths_from_settings,
    run_grok_slot_path_first,
    run_path_first,
)
from backend.tools import fetch_url_tool_entry, read_file_tool, web_search_tool


def tool_result_as_content(result_obj: Any) -> str:
    if isinstance(result_obj, str):
        return result_obj
    return json.dumps(result_obj, ensure_ascii=False)


def make_tool_exec(project_root_abs: str) -> dict[str, Callable[[dict[str, Any]], Any]]:
    def exec_web_search(args: dict[str, Any]) -> Any:
        return web_search_tool(
            args.get("query", ""),
            max_results=int(args.get("max_results") or 5),
        )

    def exec_read_file(args: dict[str, Any]) -> Any:
        return read_file_tool(
            project_root_abs=project_root_abs,
            relative_path=args.get("path", ""),
        )

    def exec_fetch_url(args: dict[str, Any]) -> Any:
        return fetch_url_tool_entry(
            args.get("url", ""),
            output_format=args.get("output_format") or args.get("format") or "auto",
            max_chars=args.get("max_chars"),
        )

    return {
        "web_search": exec_web_search,
        "read_file": exec_read_file,
        "fetch_url": exec_fetch_url,
    }


def openai_tools_schema(*, max_search_results: int) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the public web (no site restrictions). Prefer TAVILY; fall back to DuckDuckGo.",
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
                "description": "Read a file inside the Calling project root. Use '__TREE__' to get a project tree.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path under Calling root, or '__TREE__'."},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_url",
                "description": (
                    "Fetch an HTTP(S) URL and return html/md/txt/json as text. "
                    "Rate-limited for CI; GitHub URLs use GITHUB_TOKEN when set."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "HTTP or HTTPS URL."},
                        "output_format": {
                            "type": "string",
                            "enum": ["auto", "html", "md", "txt", "json"],
                            "description": "Output format (default auto).",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "Max characters to return.",
                            "minimum": 500,
                            "maximum": 50000,
                        },
                    },
                    "required": ["url"],
                },
            },
        },
    ]


def claude_tools_schema(*, max_search_results: int) -> list[dict[str, Any]]:
    # Keep keys identical to Tenshi's CLAUDE_TOOLS style
    return [
        {
            "name": "web_search",
            "description": "Search the public web (no site restrictions). Prefer TAVILY; fall back to DuckDuckGo.",
            "input_schema": {
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
        {
            "name": "read_file",
            "description": "Read a file inside the Calling project root. Use '__TREE__' to get a project tree.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path under Calling root, or '__TREE__'."},
                },
                "required": ["path"],
            },
        },
        {
            "name": "fetch_url",
            "description": "Fetch HTTP(S) URL content as text (html/md/txt/json). GitHub auth via GITHUB_TOKEN.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTP or HTTPS URL."},
                    "output_format": {
                        "type": "string",
                        "enum": ["auto", "html", "md", "txt", "json"],
                    },
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": 50000},
                },
                "required": ["url"],
            },
        },
    ]


def gemini_tools_wrappers(*, project_root_abs: str):
    # google-genai can register python callables as tools via introspection.
    def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
        return web_search_tool(query, max_results=max_results)

    def read_file(path: str) -> dict[str, Any]:
        return read_file_tool(project_root_abs=project_root_abs, relative_path=path)

    def fetch_url(url: str, output_format: str = "auto", max_chars: int = 28000) -> dict[str, Any]:
        return fetch_url_tool_entry(url, output_format=output_format, max_chars=max_chars)

    web_search.__doc__ = "Search the public web. Prefer TAVILY; fall back to DuckDuckGo."
    read_file.__doc__ = "Read a file inside the Calling project root. Use '__TREE__' to get a project tree."
    fetch_url.__doc__ = "Fetch HTTP(S) URL as text (html/md/txt/json)."

    web_search.__name__ = "web_search"
    read_file.__name__ = "read_file"
    fetch_url.__name__ = "fetch_url"

    return [web_search, read_file, fetch_url]


def _build_provider_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages or []:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content") or ""
        out.append({"role": role, "content": content})
    return out


def _is_grok_slot_model(model: str, settings: Any) -> bool:
    mid = (model or "").strip().lower()
    if mid.startswith("grok-"):
        return True
    or_model = (getattr(settings, "openrouter_model", "") or "").strip().lower()
    return "/" in mid or (or_model and mid == or_model)


def _grok_slot_invoke(
    settings: Any,
    *,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tool_exec: dict[str, Callable[[dict[str, Any]], Any]],
    force_web_search: bool,
):
    def _invoke(mid: str, path: dict[str, Any]) -> dict[str, Any]:
        return call_grok_with_tools(
            settings=settings,
            model=mid,
            system_prompt=system_prompt,
            messages=messages,
            tool_exec=tool_exec,
            force_web_search=force_web_search,
            llm_path=path,
        )

    openrouter_model = getattr(settings, "openrouter_model", "") or "deepseek/deepseek-r1-distill-llama-70b"
    grok_models = [model] if model.startswith("grok-") else ["grok-4.3"]
    return run_grok_slot_path_first(
        openrouter_model,
        grok_models,
        settings,
        _invoke,
    )


def call_grok_with_tools(
    *,
    settings: Any,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tool_exec: dict[str, Callable[[dict[str, Any]], Any]],
    force_web_search: bool,
    max_tool_rounds: int = 8,
    llm_path: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = llm_path or {
        "name": "Official",
        "api_key": settings.grok_api_key,
        "base_url": getattr(settings, "grok_base_url", "https://api.x.ai/v1"),
    }
    client = OpenAI(api_key=path["api_key"], base_url=path.get("base_url") or "https://api.x.ai/v1")

    model_messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for m in _build_provider_messages(messages):
        model_messages.append({"role": m["role"], "content": m["content"]})

    tools = openai_tools_schema(max_search_results=settings.web_search_max_results)
    used_web_search = False

    for _ in range(max_tool_rounds):
        resp = client.chat.completions.create(
            model=model,
            messages=model_messages,
            tools=tools,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        if tool_calls:
            # append assistant tool-calling message
            tool_call_payloads = []
            for tc in tool_calls:
                fn = tc.function
                args_str = fn.arguments or "{}"
                tool_call_payloads.append(
                    {"id": tc.id, "type": "function", "function": {"name": fn.name, "arguments": args_str}}
                )
                used_web_search = used_web_search or (fn.name == "web_search")
            model_messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": tool_call_payloads})

            for tc in tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                result = tool_exec.get(name, lambda _a: {"error": f"tool {name} not found"}) (args)
                model_messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": tool_result_as_content(result)}
                )
            continue

        # final answer candidate
        return {
            "answer": msg.content or "",
            "used_web_search": used_web_search,
            "thinking": (getattr(msg, "reasoning_content", None) or ""),
        }

    return {
        "answer": "I couldn't produce a final answer within the tool loop.",
        "used_web_search": used_web_search,
        "thinking": "",
    }


def call_openai_compat_with_tools(
    *,
    settings: Any,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tool_exec: dict[str, Callable[[dict[str, Any]], Any]],
    force_web_search: bool,
    max_tool_rounds: int = 8,
) -> dict[str, Any]:
    """
    OpenAI-compatible gateway for models like GLM via providers such as OpenRouter/Glama.
    Requires OPENAI_COMPAT_API_KEY and OPENAI_COMPAT_BASE_URL.
    """
    if not getattr(settings, "openai_compat_api_key", None) or not getattr(settings, "openai_compat_base_url", None):
        raise RuntimeError("OPENAI_COMPAT_API_KEY / OPENAI_COMPAT_BASE_URL is not configured.")

    client = OpenAI(api_key=settings.openai_compat_api_key, base_url=settings.openai_compat_base_url)

    model_messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for m in _build_provider_messages(messages):
        model_messages.append({"role": m["role"], "content": m["content"]})

    tools = openai_tools_schema(max_search_results=settings.web_search_max_results)
    used_web_search = False

    for _ in range(max_tool_rounds):
        # Some OpenAI-compatible providers (or specific models, e.g. GLM behind gateways)
        # do not fully support tool/function calling and may return 5xx.
        # Try with tools first, then gracefully fall back to plain chat.
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=model_messages,
                tools=tools,
                tool_choice="auto",
            )
        except APIStatusError as e:
            status = getattr(e, "status_code", None)
            if status and int(status) >= 500:
                resp = client.chat.completions.create(
                    model=model,
                    messages=model_messages,
                )
            else:
                raise
        except (APIConnectionError, APITimeoutError):
            # Network-layer issues: don't silently change behavior; bubble up.
            raise
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        if tool_calls:
            tool_call_payloads = []
            for tc in tool_calls:
                fn = tc.function
                args_str = fn.arguments or "{}"
                tool_call_payloads.append(
                    {"id": tc.id, "type": "function", "function": {"name": fn.name, "arguments": args_str}}
                )
                used_web_search = used_web_search or (fn.name == "web_search")
            model_messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": tool_call_payloads})

            for tc in tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                result = tool_exec.get(name, lambda _a: {"error": f"tool {name} not found"})(args)
                model_messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_result_as_content(result)})
            continue

        return {
            "answer": msg.content or "",
            "used_web_search": used_web_search,
            "thinking": (getattr(msg, "reasoning_content", None) or ""),
        }

    return {
        "answer": "I couldn't produce a final answer within the tool loop.",
        "used_web_search": used_web_search,
        "thinking": "",
    }

def _build_claude_clients(settings: Any, model: str) -> list[tuple[Anthropic, str]]:
    """Claude：按模型选代理1档位，再 Proxy2，官方最后。"""
    clients: list[tuple[Anthropic, str]] = []
    for proxy in build_claude_proxy_configs(settings, model_id=model):
        clients.append(
            (Anthropic(api_key=proxy["api_key"], base_url=proxy["base_url"]), proxy["name"])
        )
    if settings.claude_api_key:
        clients.append((Anthropic(api_key=settings.claude_api_key), "Official"))
    return clients


def call_claude_with_tools(
    *,
    settings: Any,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tool_exec: dict[str, Callable[[dict[str, Any]], Any]],
    force_web_search: bool,
    max_tool_rounds: int = 8,
) -> dict[str, Any]:
    clients = _build_claude_clients(settings, model)

    if not clients:
        raise RuntimeError("No Claude API client configured (CLAUDE_API_KEY and/or CLAUDE_PROXY_* missing).")

    claude_messages_base: list[dict[str, Any]] = []
    for m in _build_provider_messages(messages):
        content_blocks = [{"type": "text", "text": m["content"]}]
        claude_messages_base.append({"role": m["role"], "content": content_blocks})

    tools = claude_tools_schema(max_search_results=settings.web_search_max_results)

    last_err: Exception | None = None
    for client, client_name in clients:
        if should_skip_claude_client(model, client_name):
            continue
        try:
            used_web_search = False
            claude_messages = json.loads(json.dumps(claude_messages_base, ensure_ascii=False))
            kwargs = build_claude_request_kwargs(
                model,
                system=system_prompt,
                messages=claude_messages,
                tools=tools,
            )
            tool_rounds = 0

            try:
                response = claude_messages_create(client, kwargs)
            except Exception as e:
                if "max_tokens" in str(e) and int(kwargs.get("max_tokens", 0)) > 8192:
                    downgrade_claude_request_kwargs(kwargs)
                    response = claude_messages_create(client, kwargs)
                else:
                    raise
            tool_rounds += 1

            while getattr(response, "stop_reason", None) == "tool_use" and tool_rounds <= max_tool_rounds:
                tool_rounds += 1

                # Append assistant tool_use message to history (without thinking blocks)
                assistant_content_blocks: list[dict[str, Any]] = []
                for block in response.content:
                    if getattr(block, "type", None) == "thinking":
                        continue
                    if hasattr(block, "model_dump"):
                        assistant_content_blocks.append(block.model_dump())
                    elif hasattr(block, "dict"):
                        assistant_content_blocks.append(block.dict())
                    else:
                        assistant_content_blocks.append(block)  # pragma: no cover
                claude_messages.append({"role": "assistant", "content": assistant_content_blocks})

                tool_results: list[dict[str, Any]] = []
                for block in response.content:
                    if getattr(block, "type", None) == "tool_use":
                        name = getattr(block, "name", None)
                        block_input = getattr(block, "input", {}) or {}
                        if name == "web_search":
                            used_web_search = True
                        result = tool_exec.get(name, lambda _a: {"error": f"tool {name} not found"})(block_input)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": getattr(block, "id", None),
                                "content": tool_result_as_content(result),
                            }
                        )

                claude_messages.append({"role": "user", "content": tool_results})
                kwargs["messages"] = claude_messages
                response = claude_messages_create(client, kwargs)

            # Final response
            answer = ""
            thinking = ""
            for block in getattr(response, "content", []) or []:
                if getattr(block, "type", None) == "text":
                    answer += getattr(block, "text", "") or ""
                elif getattr(block, "type", None) == "thinking":
                    thinking += getattr(block, "thinking", "") or getattr(block, "text", "") or ""
            return {"answer": answer, "used_web_search": used_web_search, "thinking": thinking}
        except Exception as e:
            last_err = e
            continue

    raise last_err or RuntimeError("Claude call failed.")


def call_gemini_with_tools(
    *,
    settings: Any,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tool_exec: dict[str, Callable[[dict[str, Any]], Any]],
    force_web_search: bool,
    project_root_abs: str,
    max_tool_rounds: int = 8,
    llm_path: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = llm_path or {"name": "Official", "api_key": settings.gemini_api_key, "base_url": None}
    if not path.get("api_key"):
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    http_options = None
    if path.get("base_url"):
        http_options = types.HttpOptions(base_url=path["base_url"])
    client = genai.Client(api_key=path["api_key"], http_options=http_options)
    tools = gemini_tools_wrappers(project_root_abs=project_root_abs)

    msgs = _build_provider_messages(messages)
    if not msgs:
        return {"answer": "", "used_web_search": False}
    if len(msgs) == 1:
        chat_history = []
        current_parts = [types.Part.from_text(text=msgs[-1]["content"])]
    else:
        chat_history = []
        for m in msgs[:-1]:
            role = "user" if m["role"] == "user" else "model"
            chat_history.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
        current_parts = [types.Part.from_text(text=msgs[-1]["content"])]

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    chat = client.chats.create(model=model, config=config, history=chat_history)
    response = chat.send_message(current_parts)
    used_web_search = False

    tool_rounds = 0
    while tool_rounds < max_tool_rounds:
        tool_calls = []
        parts = []
        try:
            parts = response.candidates[0].content.parts or []
        except Exception:
            parts = []

        for part in parts:
            if getattr(part, "function_call", None):
                tool_calls.append(part.function_call)

        if not tool_calls:
            break

        tool_rounds += 1
        tool_outputs: list[types.Part] = []
        for fc in tool_calls:
            name = fc.name
            args = fc.args or {}
            if name == "web_search":
                used_web_search = True
            result = tool_exec.get(name, lambda _a: {"error": f"tool {name} not found"})(args)
            tool_outputs.append(
                types.Part.from_function_response(
                    name=name,
                    response={"result": tool_result_as_content(result)},
                )
            )

        response = chat.send_message(tool_outputs)

    # Final text
    answer = ""
    try:
        parts = response.candidates[0].content.parts or []
        for part in parts:
            if getattr(part, "text", None):
                answer += part.text
    except Exception:
        pass

    return {"answer": answer, "used_web_search": used_web_search, "thinking": ""}


def route_and_chat(
    *,
    settings: Any,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tool_exec: dict[str, Callable[[dict[str, Any]], Any]],
    force_web_search: bool,
    project_root_abs: str,
    max_force_retries: int = 3,
) -> dict[str, Any]:
    provider = None
    if model.startswith("claude-"):
        provider = "claude"
    elif model.startswith("gemini-"):
        provider = "gemini"
    elif model.startswith("grok-") or _is_grok_slot_model(model, settings):
        provider = "grok"
    elif model.startswith("glm-"):
        provider = "openai_compat"
    else:
        # Fall back to OpenAI-compatible gateway when configured, otherwise Grok.
        provider = "openai_compat" if getattr(settings, "openai_compat_base_url", None) else "grok"

    msgs = _build_provider_messages(messages)
    used_web_search_total = False
    answer = ""
    thinking = ""

    for attempt in range(max_force_retries + 1):
        if attempt > 0 and force_web_search:
            msgs = msgs + [
                {
                    "role": "user",
                    "content": "Requirement: You must call `web_search` at least once before answering. Call it now, then provide the final answer.",
                }
            ]

        if provider == "grok":
            if not getattr(settings, "openrouter_api_key", None) and not getattr(settings, "grok_api_key", None):
                raise RuntimeError("OPENROUTER_API_KEY / GROK_API_KEY is not configured.")
            r = _grok_slot_invoke(
                settings,
                model=model,
                system_prompt=system_prompt,
                messages=msgs,
                tool_exec=tool_exec,
                force_web_search=force_web_search,
            )
        elif provider == "openai_compat":
            r = call_openai_compat_with_tools(
                settings=settings,
                model=model,
                system_prompt=system_prompt,
                messages=msgs,
                tool_exec=tool_exec,
                force_web_search=force_web_search,
                max_tool_rounds=8,
            )
        elif provider == "claude":
            r = call_claude_with_tools(
                settings=settings,
                model=model,
                system_prompt=system_prompt,
                messages=msgs,
                tool_exec=tool_exec,
                force_web_search=force_web_search,
                max_tool_rounds=8,
            )
        else:
            paths = build_gemini_paths_from_settings(settings)
            if not paths:
                raise RuntimeError("GEMINI_API_KEY is not configured.")
            r = run_path_first(
                [model],
                paths,
                lambda mid, p: call_gemini_with_tools(
                    settings=settings,
                    model=mid,
                    system_prompt=system_prompt,
                    messages=msgs,
                    tool_exec=tool_exec,
                    force_web_search=force_web_search,
                    project_root_abs=project_root_abs,
                    max_tool_rounds=8,
                    llm_path=p,
                ),
            )

        answer = r.get("answer") or ""
        used_web_search_total = bool(r.get("used_web_search"))
        thinking = (r.get("thinking") or "").strip()

        if not force_web_search or used_web_search_total:
            return {"answer": answer, "used_web_search": used_web_search_total, "thinking": thinking}

    # Force-search enabled but model never triggered web_search.
    if force_web_search and not used_web_search_total:
        return {
            "answer": "Error: `force_web_search` is enabled, but the model did not call `web_search` before answering. Try again or choose a different model.",
            "used_web_search": False,
            "thinking": thinking,
        }

    return {"answer": answer, "used_web_search": used_web_search_total, "thinking": thinking}


def _emit_answer_chunks(text: str, *, chunk_size: int = 80) -> Iterator[dict[str, Any]]:
    for i in range(0, len(text), chunk_size):
        yield {"event": "answer_delta", "text": text[i : i + chunk_size]}


def _emit_thinking_chunks(text: str, *, chunk_size: int = 120) -> Iterator[dict[str, Any]]:
    for i in range(0, len(text), chunk_size):
        yield {"event": "thinking_delta", "text": text[i : i + chunk_size], "transient": False}


def _stream_openai_completion(
    client: OpenAI,
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = "auto",
) -> Iterator[dict[str, Any]]:
    kwargs: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
    if tools is not None:
        kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
    stream = client.chat.completions.create(**kwargs)
    answer_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls_acc: dict[int, dict[str, Any]] = {}
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        content = getattr(delta, "content", None) or ""
        if content:
            answer_parts.append(content)
            yield {"event": "answer_delta", "text": content}
        reasoning = getattr(delta, "reasoning_content", None) or ""
        if reasoning:
            thinking_parts.append(reasoning)
            yield {"event": "thinking_delta", "text": reasoning, "transient": False}
        for tc in getattr(delta, "tool_calls", None) or []:
            idx = int(getattr(tc, "index", 0) or 0)
            slot = tool_calls_acc.setdefault(
                idx,
                {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
            )
            if getattr(tc, "id", None):
                slot["id"] = tc.id
            fn = getattr(tc, "function", None)
            if fn is not None:
                if getattr(fn, "name", None):
                    slot["function"]["name"] = fn.name
                if getattr(fn, "arguments", None):
                    slot["function"]["arguments"] += fn.arguments or ""
    tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc.keys())]
    yield {
        "event": "_complete",
        "answer": "".join(answer_parts),
        "thinking": "".join(thinking_parts),
        "tool_calls": tool_calls,
    }


def _stream_openai_with_tools(
    *,
    client: OpenAI,
    model: str,
    model_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_exec: dict[str, Callable[[dict[str, Any]], Any]],
    max_tool_rounds: int,
) -> Iterator[dict[str, Any]]:
    used_web_search = False
    for _ in range(max_tool_rounds):
        answer = ""
        thinking = ""
        tool_calls: list[Any] = []
        try:
            stream_iter = _stream_openai_completion(
                client,
                model=model,
                messages=model_messages,
                tools=tools,
                tool_choice="auto",
            )
        except APIStatusError as e:
            status = getattr(e, "status_code", None)
            if status and int(status) >= 500:
                stream_iter = _stream_openai_completion(
                    client,
                    model=model,
                    messages=model_messages,
                    tools=None,
                    tool_choice=None,
                )
            else:
                raise

        for evt in stream_iter:
            if evt.get("event") == "_complete":
                answer = evt.get("answer") or ""
                thinking = evt.get("thinking") or ""
                tool_calls = evt.get("tool_calls") or []
                continue
            yield evt

        if tool_calls:
            model_messages.append(
                {"role": "assistant", "content": answer or "", "tool_calls": tool_calls}
            )
            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                if name == "web_search":
                    used_web_search = True
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                result = tool_exec.get(name, lambda _a: {"error": f"tool {name} not found"})(args)
                model_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": tool_result_as_content(result),
                    }
                )
            yield {"event": "status", "message": "Running tools, preparing answer..."}
            continue

        yield {
            "event": "_final",
            "answer": answer,
            "thinking": thinking,
            "used_web_search": used_web_search,
        }
        return

    yield {
        "event": "_final",
        "answer": "I couldn't produce a final answer within the tool loop.",
        "thinking": "",
        "used_web_search": used_web_search,
    }


def route_and_chat_stream(
    *,
    settings: Any,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tool_exec: dict[str, Callable[[dict[str, Any]], Any]],
    force_web_search: bool,
    project_root_abs: str,
    max_force_retries: int = 3,
) -> Iterator[dict[str, Any]]:
    if model.startswith("claude-"):
        provider = "claude"
    elif model.startswith("gemini-"):
        provider = "gemini"
    elif model.startswith("grok-") or _is_grok_slot_model(model, settings):
        provider = "grok"
    elif model.startswith("glm-"):
        provider = "openai_compat"
    else:
        provider = "openai_compat" if getattr(settings, "openai_compat_base_url", None) else "grok"

    msgs = _build_provider_messages(messages)
    used_web_search_total = False
    answer = ""
    thinking = ""

    for attempt in range(max_force_retries + 1):
        if attempt > 0 and force_web_search:
            msgs = msgs + [
                {
                    "role": "user",
                    "content": "Requirement: You must call `web_search` at least once before answering. Call it now, then provide the final answer.",
                }
            ]

        if provider in ("grok", "openai_compat"):
            if provider == "grok":
                grok_model = model if model.startswith("grok-") else "grok-4.3"
                slot_attempts: list[tuple[dict[str, Any], str]] = []
                for path in build_openrouter_paths_from_settings(settings):
                    slot_attempts.append((path, getattr(settings, "openrouter_model", model)))
                for path in build_grok_paths_from_settings(settings):
                    slot_attempts.append((path, grok_model))
                if not slot_attempts:
                    raise RuntimeError("OPENROUTER_API_KEY / GROK_API_KEY is not configured.")
                streamed = False
                for path, slot_model in slot_attempts:
                    client = OpenAI(
                        api_key=path["api_key"],
                        base_url=path.get("base_url") or "https://api.x.ai/v1",
                    )
                    model_messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
                    for m in msgs:
                        model_messages.append({"role": m["role"], "content": m["content"]})
                    tools = openai_tools_schema(max_search_results=settings.web_search_max_results)
                    try:
                        for evt in _stream_openai_with_tools(
                            client=client,
                            model=slot_model,
                            model_messages=model_messages,
                            tools=tools,
                            tool_exec=tool_exec,
                            max_tool_rounds=8,
                        ):
                            if evt.get("event") == "_final":
                                answer = evt.get("answer") or ""
                                thinking = (evt.get("thinking") or "").strip()
                                used_web_search_total = bool(evt.get("used_web_search"))
                                if not force_web_search or used_web_search_total:
                                    yield evt
                                    return
                                break
                            yield evt
                        streamed = True
                        break
                    except Exception:
                        continue
                if streamed:
                    continue
            elif provider == "openai_compat":
                if not getattr(settings, "openai_compat_api_key", None) or not getattr(
                    settings, "openai_compat_base_url", None
                ):
                    raise RuntimeError("OPENAI_COMPAT_API_KEY / OPENAI_COMPAT_BASE_URL is not configured.")
                client = OpenAI(
                    api_key=settings.openai_compat_api_key,
                    base_url=settings.openai_compat_base_url,
                )
                model_messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
                for m in msgs:
                    model_messages.append({"role": m["role"], "content": m["content"]})
                tools = openai_tools_schema(max_search_results=settings.web_search_max_results)
                for evt in _stream_openai_with_tools(
                    client=client,
                    model=model,
                    model_messages=model_messages,
                    tools=tools,
                    tool_exec=tool_exec,
                    max_tool_rounds=8,
                ):
                    if evt.get("event") == "_final":
                        answer = evt.get("answer") or ""
                        thinking = (evt.get("thinking") or "").strip()
                        used_web_search_total = bool(evt.get("used_web_search"))
                        if not force_web_search or used_web_search_total:
                            yield evt
                            return
                        break
                    yield evt

        elif provider == "claude":
            result = call_claude_with_tools(
                settings=settings,
                model=model,
                system_prompt=system_prompt,
                messages=msgs,
                tool_exec=tool_exec,
                force_web_search=force_web_search,
                max_tool_rounds=8,
            )
            answer = result.get("answer") or ""
            thinking = (result.get("thinking") or "").strip()
            used_web_search_total = bool(result.get("used_web_search"))
            if thinking:
                yield from _emit_thinking_chunks(thinking)
            if answer:
                yield from _emit_answer_chunks(answer)

        else:
            paths = build_gemini_paths_from_settings(settings)
            if not paths:
                raise RuntimeError("GEMINI_API_KEY is not configured.")
            result = run_path_first(
                [model],
                paths,
                lambda mid, p: call_gemini_with_tools(
                    settings=settings,
                    model=mid,
                    system_prompt=system_prompt,
                    messages=msgs,
                    tool_exec=tool_exec,
                    force_web_search=force_web_search,
                    project_root_abs=project_root_abs,
                    max_tool_rounds=8,
                    llm_path=p,
                ),
            )
            answer = result.get("answer") or ""
            thinking = (result.get("thinking") or "").strip()
            used_web_search_total = bool(result.get("used_web_search"))
            if thinking:
                yield from _emit_thinking_chunks(thinking)
            if answer:
                yield from _emit_answer_chunks(answer)

        if not force_web_search or used_web_search_total:
            yield {
                "event": "_final",
                "answer": answer,
                "thinking": thinking,
                "used_web_search": used_web_search_total,
            }
            return

    if force_web_search and not used_web_search_total:
        answer = (
            "Error: `force_web_search` is enabled, but the model did not call `web_search` "
            "before answering. Try again or choose a different model."
        )
    yield {
        "event": "_final",
        "answer": answer,
        "thinking": thinking,
        "used_web_search": used_web_search_total,
    }

