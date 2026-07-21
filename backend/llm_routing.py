"""LLM path ordering and Claude / non-Claude fallback strategy."""

from __future__ import annotations

from typing import Any, Callable, Iterable, TypeVar

T = TypeVar("T")


def is_claude_thinking_model(model_id: str) -> bool:
    return "thinking" in (model_id or "").lower()


def is_claude_fable_model(model_id: str) -> bool:
    """Fable 系列：代理1走 Prime → Max（不用 Base）。"""
    return "fable" in (model_id or "").lower()


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


def _proxy1_tiers_from_settings(settings: Any) -> dict[str, dict[str, Any]]:
    """代理1 Base/Prime/Max；旧字段 claude_proxy_key 作为 Base 回退。"""
    base_url = getattr(settings, "claude_proxy_base_url", None)
    if not base_url:
        return {}
    key_base = getattr(settings, "claude_proxy_key_base", None) or getattr(
        settings, "claude_proxy_key", None
    )
    key_prime = getattr(settings, "claude_proxy_key_prime", None)
    key_max = getattr(settings, "claude_proxy_key_max", None)
    tiers: dict[str, dict[str, Any]] = {}
    if key_base:
        tiers["base"] = {
            "name": "Proxy1 Base",
            "api_key": key_base,
            "base_url": base_url,
        }
    if key_prime:
        tiers["prime"] = {
            "name": "Proxy1 Prime",
            "api_key": key_prime,
            "base_url": base_url,
        }
    if key_max:
        tiers["max"] = {
            "name": "Proxy1 Max",
            "api_key": key_max,
            "base_url": base_url,
        }
    return tiers


def build_claude_proxy_configs(settings: Any, model_id: str | None = None) -> list[dict[str, Any]]:
    """
    Claude 代理列表。
    - model_id 给定时按模型排序：Fable=Prime→Max；其它=Base→Prime→Max；再 Proxy2
    - 未给 model_id 时（Gemini/Grok 等复用）：每端点一档（优先 Base）
    """
    tiers = _proxy1_tiers_from_settings(settings)
    proxies: list[dict[str, Any]] = []

    if model_id is not None:
        order = ("prime", "max") if is_claude_fable_model(model_id) else ("base", "prime", "max")
        for tier in order:
            conf = tiers.get(tier)
            if conf:
                proxies.append(conf)
    else:
        for tier in ("base", "prime", "max"):
            if tier in tiers:
                proxies.append(
                    {
                        "name": "Proxy1",
                        "api_key": tiers[tier]["api_key"],
                        "base_url": tiers[tier]["base_url"],
                    }
                )
                break

    key2 = getattr(settings, "claude_proxy_key_2", None)
    url2 = getattr(settings, "claude_proxy_base_url_2", None)
    if key2 and url2:
        proxies.append(
            {
                "name": "Proxy2",
                "api_key": key2,
                "base_url": url2,
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
