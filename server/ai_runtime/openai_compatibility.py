"""Small canonical helpers for reviewed OpenAI-compatible provider edges."""

from __future__ import annotations

from .contracts import JsonObject
from .provider_call_window import (
    is_deepseek_provider_endpoint,
    is_gemini_provider_endpoint,
)
from .provider_connectivity_contracts import ProviderConnectivitySettings


def is_thinking_provider_settings(settings: ProviderConnectivitySettings) -> bool:
    """Classify providers/models that support maximum reasoning / thinking mode."""
    if is_deepseek_provider_endpoint(settings.provider_id, settings.endpoint_origin):
        return True
    if is_gemini_provider_endpoint(settings.provider_id, settings.endpoint_origin):
        return True
    model = (getattr(settings, "model_name", None) or "").strip().casefold()
    return "deepseek" in model or "gemini" in model


def edge_request_options(settings: ProviderConnectivitySettings) -> JsonObject:
    """Preserve configured reasoning per provider while avoiding unsupported knobs."""
    if is_deepseek_provider_endpoint(settings.provider_id, settings.endpoint_origin):
        return {
            "thinking": {"type": "enabled"},
            "reasoning_effort": "max",
        }
    if is_gemini_provider_endpoint(settings.provider_id, settings.endpoint_origin):
        return {"reasoning_effort": "high"}

    model = (getattr(settings, "model_name", None) or "").strip().casefold()
    if "deepseek" in model:
        return {
            "thinking": {"type": "enabled"},
            "reasoning_effort": "max",
        }
    if "gemini" in model:
        return {"reasoning_effort": "high"}
    if "gpt-" in model or "o1" in model or "o3" in model or "sol" in model:
        return {"reasoning_effort": "max"}
    if "kimi" in model or "moonshot" in model:
        return {"reasoning_effort": "high"}

    return {"temperature": 0}


def message_text(value: object) -> str | None:
    """Normalize text content without accepting provider-side tool output."""
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return None
    parts: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        part_type = item.get("type")
        text = item.get("text")
        if part_type not in (None, "text", "output_text") or not isinstance(text, str):
            return None
        parts.append(text)
    return "".join(parts)


def safe_usage(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        raw = value.get(key)
        if isinstance(raw, int) and raw >= 0:
            result[key] = raw
    return result


__all__ = [
    "edge_request_options",
    "is_thinking_provider_settings",
    "message_text",
    "safe_usage",
]
