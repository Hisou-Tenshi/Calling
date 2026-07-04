"""LLM path ordering and Claude / non-Claude fallback strategy."""

from __future__ import annotations

from typing import Any, Callable, Iterable, TypeVar

T = TypeVar("T")


def is_claude_thinking_model(model_id: str) -> bool:
    return "thinking" in (model_id or "").lower()


def should_skip_claude_client(model_id: str, client_name: str) -> bool:
    if client_name == "Official" and is_claude_thinking_model(model_id):
        return True
    return False


def build_llm_paths(
    official_key: str | None,
    official_base_url: str | None,
    proxy_configs: Iterable[dict[str, Any]] | None,
    *,
    official_name: str = "Official",
) -> list[dict[str, Any]]:
    paths: list[dict[str, Any]] = []
    if official_key:
        paths.append(
            {
                "name": official_name,
                "api_key": official_key,
                "base_url": official_base_url or None,
                "is_official": True,
            }
        )
    for proxy in proxy_configs or []:
        api_key = proxy.get("api_key")
        base_url = proxy.get("base_url")
        if not api_key or not base_url:
            continue
        paths.append(
            {
                "name": proxy.get("name") or "Proxy",
                "api_key": api_key,
                "base_url": base_url,
                "is_official": False,
            }
        )
    return paths


def build_claude_proxy_configs(settings: Any) -> list[dict[str, Any]]:
    proxies: list[dict[str, Any]] = []
    if settings.claude_proxy_key and settings.claude_proxy_base_url:
        proxies.append(
            {
                "name": "Proxy1",
                "api_key": settings.claude_proxy_key,
                "base_url": settings.claude_proxy_base_url,
            }
        )
    if settings.claude_proxy_key_2 and settings.claude_proxy_base_url_2:
        proxies.append(
            {
                "name": "Proxy2",
                "api_key": settings.claude_proxy_key_2,
                "base_url": settings.claude_proxy_base_url_2,
            }
        )
    return proxies


def build_gemini_paths_from_settings(settings: Any) -> list[dict[str, Any]]:
    return build_llm_paths(settings.gemini_api_key, None, build_claude_proxy_configs(settings))


def build_grok_paths_from_settings(settings: Any) -> list[dict[str, Any]]:
    base_url = getattr(settings, "grok_base_url", "https://api.x.ai/v1")
    return build_llm_paths(settings.grok_api_key, base_url, build_claude_proxy_configs(settings))


def build_openrouter_paths_from_settings(settings: Any) -> list[dict[str, Any]]:
    return build_llm_paths(
        getattr(settings, "openrouter_api_key", None),
        getattr(settings, "openrouter_base_url", "https://openrouter.ai/api/v1"),
        None,
        official_name="OpenRouter",
    )


def run_grok_slot_path_first(
    openrouter_model: str,
    grok_model_ids: list[str],
    settings: Any,
    invoke: Callable[[str, dict[str, Any]], T],
    *,
    max_attempts: int = 1,
) -> T:
    """OpenRouter 主路 + Grok 容灾。"""
    last_err: Exception | None = None
    or_paths = build_openrouter_paths_from_settings(settings)
    if or_paths and openrouter_model:
        try:
            return run_path_first([openrouter_model], or_paths, invoke, max_attempts=max_attempts)
        except Exception as e:
            last_err = e

    grok_paths = build_grok_paths_from_settings(settings)
    if grok_paths and grok_model_ids:
        try:
            return run_path_first(grok_model_ids, grok_paths, invoke, max_attempts=max_attempts)
        except Exception as e:
            last_err = e

    raise last_err or RuntimeError("OpenRouter/Grok slot failed")


def run_path_first(
    model_ids: list[str],
    paths: list[dict[str, Any]],
    invoke: Callable[[str, dict[str, Any]], T],
    *,
    max_attempts: int = 1,
) -> T:
    last_err: Exception | None = None
    for path in paths:
        for model_id in model_ids:
            for attempt in range(1, max_attempts + 1):
                try:
                    return invoke(model_id, path)
                except Exception as e:
                    last_err = e
    raise last_err or RuntimeError("All paths/models failed")
