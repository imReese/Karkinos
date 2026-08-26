"""Stable scalar and JSON serialization for SQLite repository boundaries."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


def normalize_timestamp(value: str) -> str:
    """Normalize timestamps to stable UTC ISO-8601 text for ordering."""

    normalized_value = value.strip().replace("Z", "+00:00")
    timestamp = datetime.fromisoformat(normalized_value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)
    return timestamp.isoformat(timespec="seconds")


def serialize_metadata_json(value: dict[str, Any] | str | None) -> str | None:
    """Serialize optional metadata to stable JSON text."""

    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def metadata_payload_value(value: dict[str, Any] | str | None) -> Any:
    """Return metadata as a structured event payload value when possible."""

    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def decimal_values_equal(left: Any, right: Any) -> bool:
    """Compare persisted decimal values without float coercion."""

    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (ArithmeticError, TypeError, ValueError):
        return False


__all__ = [
    "decimal_values_equal",
    "metadata_payload_value",
    "normalize_timestamp",
    "serialize_metadata_json",
]
