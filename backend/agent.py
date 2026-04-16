import json
from typing import Any, Callable

import numpy as np
from anthropic import Anthropic
from google import genai
from google.genai import types
from openai import OpenAI

from backend.tools import read_file_tool, web_search_tool


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

    return {"web_search": exec_web_search, "read_file": exec_read_file}


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
    ]


def gemini_tools_wrappers(*, project_root_abs: str):
    # google-genai can register python callables as tools via introspection.
    def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
        return web_search_tool(query, max_results=max_results)

    def read_file(path: str) -> dict[str, Any]:
        return read_file_tool(project_root_abs=project_root_abs, relative_path=path)

    # Docstrings help the tool declaration
    web_search.__doc__ = "Search the public web. Prefer TAVILY; fall back to DuckDuckGo."
    read_file.__doc__ = "Read a file inside the Calling project root. Use '__TREE__' to get a project tree."

    web_search.__name__ = "web_search"
    read_file.__name__ = "read_file"

    return [web_search, read_file]


def _build_provider_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages or []:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content") or ""
        out.append({"role": role, "content": content})
    return out


def call_grok_with_tools(
    *,
    settings: Any,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tool_exec: dict[str, Callable[[dict[str, Any]], Any]],
    force_web_search: bool,
    max_tool_rounds: int = 8,
) -> dict[str, Any]:
    client = OpenAI(api_key=settings.grok_api_key, base_url=getattr(settings, "grok_base_url", "https://api.x.ai/v1"))

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
        resp = client.chat.completions.create(
            model=model,
            messages=model_messages,
            tools=tools,
            tool_choice="auto",
        )
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
    clients: list[tuple[Anthropic, str]] = []

    # Optional proxies (same var names as Tenshi)
    if settings.claude_proxy_key and settings.claude_proxy_base_url:
        clients.append(
            (Anthropic(api_key=settings.claude_proxy_key, base_url=settings.claude_proxy_base_url), "Proxy1")
        )
    if settings.claude_proxy_key_2 and settings.claude_proxy_base_url_2:
        clients.append(
            (Anthropic(api_key=settings.claude_proxy_key_2, base_url=settings.claude_proxy_base_url_2), "Proxy2")
        )
    if settings.claude_api_key:
        clients.append((Anthropic(api_key=settings.claude_api_key), "Official"))

    if not clients:
        raise RuntimeError("No Claude API client configured (CLAUDE_API_KEY and/or CLAUDE_PROXY_* missing).")

    claude_messages_base: list[dict[str, Any]] = []
    for m in _build_provider_messages(messages):
        content_blocks = [{"type": "text", "text": m["content"]}]
        claude_messages_base.append({"role": m["role"], "content": content_blocks})

    tools = claude_tools_schema(max_search_results=settings.web_search_max_results)

    last_err: Exception | None = None
    for client, _name in clients:
        try:
            used_web_search = False
            claude_messages = json.loads(json.dumps(claude_messages_base, ensure_ascii=False))
            kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": 8192,
                "system": system_prompt,
                "messages": claude_messages,
                "tools": tools,
            }
            tool_rounds = 0

            response = client.messages.create(**kwargs)
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
                response = client.messages.create(**kwargs)

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
) -> dict[str, Any]:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    client = genai.Client(api_key=settings.gemini_api_key)
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
    elif model.startswith("grok-"):
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
            r = call_grok_with_tools(
                settings=settings,
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
            r = call_gemini_with_tools(
                settings=settings,
                model=model,
                system_prompt=system_prompt,
                messages=msgs,
                tool_exec=tool_exec,
                force_web_search=force_web_search,
                project_root_abs=project_root_abs,
                max_tool_rounds=8,
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

