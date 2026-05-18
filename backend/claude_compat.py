"""Claude API request shaping for Opus 4.7 and legacy model fallbacks."""

from __future__ import annotations

from typing import Any


def build_claude_request_kwargs(
    model: str,
    *,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    thinking_config: dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None
    max_tokens = 8192

    if model == "claude-opus-4-7":
        thinking_config = {"type": "adaptive", "display": "summarized"}
        output_config = {"effort": "xhigh"}
        max_tokens = 64000
    elif model in ("claude-opus-4-6", "claude-opus-4-6-thinking"):
        thinking_config = {"type": "adaptive"}
        max_tokens = 64000

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
    if thinking_config:
        kwargs["thinking"] = thinking_config
    if output_config:
        kwargs["output_config"] = output_config
    return kwargs


def downgrade_claude_request_kwargs(kwargs: dict[str, Any]) -> None:
    """Fallback when a provider rejects large max_tokens or thinking/output_config."""
    kwargs["max_tokens"] = 8192
    kwargs.pop("thinking", None)
    kwargs.pop("output_config", None)


def should_skip_claude_client(model: str, client_name: str) -> bool:
    """Legacy alias is proxy-only in this project."""
    return model == "claude-opus-4-6-thinking" and client_name == "Official"


def claude_messages_create(client: Any, kwargs: dict[str, Any]) -> Any:
    """
    Create a Claude message response. Extended-thinking models must use streaming
    to avoid long-operation limits on non-streaming create().
    """
    if kwargs.get("thinking"):
        with client.messages.stream(**kwargs) as stream:
            for _ in stream.text_stream:
                pass
            return stream.get_final_message()
    return client.messages.create(**kwargs)
