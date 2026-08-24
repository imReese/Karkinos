"""Pure normalization and fingerprint helpers for execution reconciliation."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any


def fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def decimal_value(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def event_payload(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("payload")
    if isinstance(raw, dict):
        return raw
    payload_json = event.get("payload_json")
    if not isinstance(payload_json, str) or not payload_json.strip():
        return {}
    try:
        parsed = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def object_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def sum_event_decimal(events: list[Any], field: str) -> Decimal:
    total = Decimal("0")
    for event in events:
        total += decimal_value(getattr(event, field, None)) or Decimal("0")
    return total


def order_payload(order: dict[str, Any]) -> dict[str, Any]:
    value = order.get("payload")
    if isinstance(value, dict):
        return value
    raw = order.get("payload_json")
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def evidence_identifier(value: Any, *, expected_kind: str) -> str | None:
    kind, separator, identifier = str(value or "").strip().partition(":")
    if separator != ":" or kind != expected_kind or not identifier.strip():
        return None
    return identifier.strip()


def decision_action_ref(value: Any) -> str | None:
    identifier = evidence_identifier(value, expected_kind="decision_action")
    return f"action:{identifier}" if identifier is not None else None


def decision_action_side(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"buy", "increase", "add", "overweight"}:
        return "buy"
    if normalized in {"sell", "decrease", "reduce", "underweight"}:
        return "sell"
    return ""


def reference_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def valid_strategy_advancement_refs(value: Any) -> bool:
    refs = reference_list(value)
    return (
        len(refs) == 1
        and re.fullmatch(r"strategy_advancement:[a-f0-9]{64}", refs[0].lower())
        is not None
    )


def asset_class_equivalent(left: Any, right: Any) -> bool:
    return normalized_asset_class(left) == normalized_asset_class(right) != ""


def normalized_asset_class(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"fund", "etf"}:
        return "fund"
    return normalized
