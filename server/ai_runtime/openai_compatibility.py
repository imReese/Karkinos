"""Small canonical helpers for reviewed OpenAI-compatible provider edges."""

from __future__ import annotations

from .contracts import JsonObject
from .provider_connectivity_contracts import ProviderConnectivitySettings


def edge_request_options(settings: ProviderConnectivitySettings) -> JsonObject:
    """Preserve configured reasoning while avoiding unsupported sampling knobs."""
    provider = settings.provider_id.strip().lower()
    if provider == "deepseek" or settings.endpoint_origin.endswith("deepseek.com"):
        return {
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
        }
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


__all__ = ["edge_request_options", "message_text", "safe_usage"]
