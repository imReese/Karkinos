"""Canonical normalization and value helpers for broker lifecycle evidence."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from account_truth.broker_order_lifecycle_contracts import (
    BROKER_ORDER_LIFECYCLE_FILL_FIELDS as _FILL_FIELDS,
)
from account_truth.broker_order_lifecycle_contracts import (
    BROKER_ORDER_LIFECYCLE_ORDER_FIELDS as _ORDER_FIELDS,
)
from account_truth.broker_order_lifecycle_contracts import (
    BROKER_ORDER_LIFECYCLE_ORDER_STATUSES as _ORDER_STATUSES,
)
from account_truth.broker_order_lifecycle_contracts import (
    BROKER_ORDER_LIFECYCLE_SENSITIVE_KEY_PARTS as _SENSITIVE_KEY_PARTS,
)
from account_truth.broker_order_lifecycle_contracts import MAX_EXPORT_BYTES

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")


def broker_order_lifecycle_id_is_valid(value: str) -> bool:
    """Return whether a broker lifecycle scope identifier is canonical."""

    return _ID_PATTERN.fullmatch(value) is not None


def normalize_broker_order(
    data: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    reject_broker_order_unknown_fields(data, _ORDER_FIELDS, "order", blockers)
    order = {
        "broker_order_id": normalize_broker_order_id_field(
            data, "broker_order_id", "order", blockers
        ),
        "client_order_id": normalize_broker_order_id_field(
            data, "client_order_id", "order", blockers
        ),
        "symbol": str(data.get("symbol") or "").strip(),
        "side": str(data.get("side") or "").strip().lower(),
        "status": str(data.get("status") or "").strip().lower(),
        "order_quantity": normalize_broker_order_decimal_field(
            data, "order_quantity", "order", blockers
        ),
        "cumulative_filled_quantity": normalize_broker_order_decimal_field(
            data, "cumulative_filled_quantity", "order", blockers
        ),
        "cancelled_quantity": normalize_broker_order_decimal_field(
            data, "cancelled_quantity", "order", blockers
        ),
        "average_fill_price": normalize_broker_order_optional_decimal_field(
            data, "average_fill_price", "order", blockers
        ),
        "submitted_at": normalize_broker_order_timestamp(
            data.get("submitted_at"),
            blocker="broker_order_lifecycle_order_submitted_at_invalid",
            blockers=blockers,
        ),
        "updated_at": normalize_broker_order_timestamp(
            data.get("updated_at"),
            blocker="broker_order_lifecycle_order_updated_at_invalid",
            blockers=blockers,
        ),
    }
    if not _SYMBOL_PATTERN.fullmatch(order["symbol"]):
        blockers.append("broker_order_lifecycle_order_symbol_invalid")
    if order["side"] not in {"buy", "sell"}:
        blockers.append("broker_order_lifecycle_order_side_invalid")
    if order["status"] not in _ORDER_STATUSES:
        blockers.append("broker_order_lifecycle_order_status_invalid")
    return order


def normalize_broker_fill(
    data: dict[str, Any],
    *,
    index: int,
    blockers: list[str],
) -> dict[str, Any]:
    prefix = f"fill_{index}"
    reject_broker_order_unknown_fields(data, _FILL_FIELDS, prefix, blockers)
    fill = {
        "broker_trade_id": normalize_broker_order_id_field(
            data, "broker_trade_id", prefix, blockers
        ),
        "broker_order_id": normalize_broker_order_id_field(
            data, "broker_order_id", prefix, blockers
        ),
        "client_order_id": normalize_broker_order_id_field(
            data, "client_order_id", prefix, blockers
        ),
        "symbol": str(data.get("symbol") or "").strip(),
        "side": str(data.get("side") or "").strip().lower(),
        "quantity": normalize_broker_order_decimal_field(
            data, "quantity", prefix, blockers
        ),
        "price": normalize_broker_order_decimal_field(data, "price", prefix, blockers),
        "fee": normalize_broker_order_decimal_field(data, "fee", prefix, blockers),
        "tax": normalize_broker_order_decimal_field(data, "tax", prefix, blockers),
        "transfer_fee": normalize_broker_order_decimal_field(
            data, "transfer_fee", prefix, blockers
        ),
        "net_amount": normalize_broker_order_decimal_field(
            data,
            "net_amount",
            prefix,
            blockers,
            allow_negative=True,
        ),
        "filled_at": normalize_broker_order_timestamp(
            data.get("filled_at"),
            blocker=f"broker_order_lifecycle_{prefix}_filled_at_invalid",
            blockers=blockers,
        ),
    }
    if not _SYMBOL_PATTERN.fullmatch(fill["symbol"]):
        blockers.append(f"broker_order_lifecycle_{prefix}_symbol_invalid")
    if fill["side"] not in {"buy", "sell"}:
        blockers.append(f"broker_order_lifecycle_{prefix}_side_invalid")
    return fill


def validate_broker_order_and_fills(
    order: dict[str, Any],
    fills: list[dict[str, Any]],
    captured_at: str,
    blockers: list[str],
) -> None:
    quantity = broker_order_decimal(order.get("order_quantity"))
    filled_quantity = broker_order_decimal(order.get("cumulative_filled_quantity"))
    cancelled_quantity = broker_order_decimal(order.get("cancelled_quantity"))
    if quantity <= 0:
        blockers.append("broker_order_lifecycle_order_quantity_not_positive")
    if filled_quantity < 0 or cancelled_quantity < 0:
        blockers.append("broker_order_lifecycle_order_quantities_negative")
    if filled_quantity + cancelled_quantity > quantity:
        blockers.append("broker_order_lifecycle_order_quantity_components_exceed_total")

    status = str(order.get("status") or "")
    if status in {"submitted", "open", "rejected"} and (
        filled_quantity != 0 or cancelled_quantity != 0
    ):
        blockers.append("broker_order_lifecycle_nonfill_status_has_quantity")
    if status == "partially_filled" and not (
        0 < filled_quantity < quantity and cancelled_quantity == 0
    ):
        blockers.append("broker_order_lifecycle_partial_fill_quantities_invalid")
    if status == "filled" and not (
        filled_quantity == quantity and cancelled_quantity == 0
    ):
        blockers.append("broker_order_lifecycle_filled_quantities_invalid")
    if status == "cancelled" and not (
        cancelled_quantity > 0 and filled_quantity + cancelled_quantity == quantity
    ):
        blockers.append("broker_order_lifecycle_cancelled_quantities_invalid")

    submitted_at = str(order.get("submitted_at") or "")
    updated_at = str(order.get("updated_at") or "")
    if submitted_at and updated_at and submitted_at > updated_at:
        blockers.append("broker_order_lifecycle_order_time_regressed")
    if updated_at and captured_at and updated_at > captured_at:
        blockers.append("broker_order_lifecycle_order_updated_after_capture")

    seen_trade_ids: set[str] = set()
    fill_total = Decimal("0")
    weighted_total = Decimal("0")
    for fill in fills:
        trade_id = str(fill.get("broker_trade_id") or "")
        if trade_id in seen_trade_ids:
            blockers.append("broker_order_lifecycle_broker_trade_id_duplicate")
        seen_trade_ids.add(trade_id)
        for field in (
            "broker_order_id",
            "client_order_id",
            "symbol",
            "side",
        ):
            if str(fill.get(field) or "") != str(order.get(field) or ""):
                blockers.append(f"broker_order_lifecycle_fill_{field}_mismatch")
        fill_quantity = broker_order_decimal(fill.get("quantity"))
        fill_price = broker_order_decimal(fill.get("price"))
        if fill_quantity <= 0:
            blockers.append("broker_order_lifecycle_fill_quantity_not_positive")
        if fill_price <= 0:
            blockers.append("broker_order_lifecycle_fill_price_not_positive")
        if str(fill.get("filled_at") or "") < submitted_at:
            blockers.append("broker_order_lifecycle_fill_before_submission")
        if str(fill.get("filled_at") or "") > updated_at:
            blockers.append("broker_order_lifecycle_fill_after_order_update")
        fill_total += fill_quantity
        weighted_total += fill_quantity * fill_price
    if fill_total != filled_quantity:
        blockers.append("broker_order_lifecycle_fill_sum_mismatch")
    average = order.get("average_fill_price")
    if filled_quantity > 0:
        if average is None or broker_order_decimal(average) <= 0:
            blockers.append("broker_order_lifecycle_average_fill_price_missing")
        elif fill_total > 0:
            calculated_average = weighted_total / fill_total
            if abs(calculated_average - broker_order_decimal(average)) > Decimal(
                "0.0001"
            ):
                blockers.append("broker_order_lifecycle_average_fill_price_mismatch")
    elif average is not None:
        blockers.append("broker_order_lifecycle_average_fill_price_without_fill")


def decode_broker_order_content(content: str | bytes) -> tuple[bytes, str, list[str]]:
    raw = content if isinstance(content, bytes) else str(content).encode("utf-8")
    blockers: list[str] = []
    if len(raw) > MAX_EXPORT_BYTES:
        blockers.append("broker_order_lifecycle_export_too_large")
        return raw, "", blockers
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        blockers.append("broker_order_lifecycle_export_not_utf8")
        text = ""
    return raw, text, blockers


def broker_order_contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                return True
            if broker_order_contains_sensitive_key(nested):
                return True
    elif isinstance(value, list):
        return any(broker_order_contains_sensitive_key(item) for item in value)
    return False


def reject_broker_order_unknown_fields(
    data: dict[str, Any],
    allowed: frozenset[str],
    prefix: str,
    blockers: list[str],
) -> None:
    for key in sorted(set(data) - allowed):
        blockers.append(f"broker_order_lifecycle_{prefix}_field_unsupported:{key}")


def normalize_broker_order_id_field(
    data: dict[str, Any],
    field: str,
    prefix: str,
    blockers: list[str],
) -> str:
    value = str(data.get(field) or "").strip()
    if not _ID_PATTERN.fullmatch(value):
        blockers.append(f"broker_order_lifecycle_{prefix}_{field}_invalid")
    return value


def normalize_broker_order_decimal_field(
    data: dict[str, Any],
    field: str,
    prefix: str,
    blockers: list[str],
    *,
    allow_negative: bool = False,
) -> str:
    try:
        value = Decimal(str(data[field]))
    except (KeyError, InvalidOperation, TypeError, ValueError):
        blockers.append(f"broker_order_lifecycle_{prefix}_{field}_invalid")
        return "0"
    if not value.is_finite() or (value < 0 and not allow_negative):
        blockers.append(f"broker_order_lifecycle_{prefix}_{field}_invalid")
        return "0"
    return format_broker_order_decimal(value)


def normalize_broker_order_optional_decimal_field(
    data: dict[str, Any],
    field: str,
    prefix: str,
    blockers: list[str],
) -> str | None:
    if data.get(field) is None:
        return None
    return normalize_broker_order_decimal_field(data, field, prefix, blockers)


def normalize_broker_order_source_sequence(value: Any, blockers: list[str]) -> int:
    if isinstance(value, bool):
        blockers.append("broker_order_lifecycle_source_sequence_invalid")
        return 0
    try:
        sequence = int(value)
    except (TypeError, ValueError):
        blockers.append("broker_order_lifecycle_source_sequence_invalid")
        return 0
    if sequence < 0 or str(value).strip() != str(sequence):
        blockers.append("broker_order_lifecycle_source_sequence_invalid")
        return 0
    return sequence


def normalize_broker_order_timestamp(
    value: Any,
    *,
    blocker: str,
    blockers: list[str],
) -> str:
    raw = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        blockers.append(blocker)
        return ""
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        blockers.append(blocker)
        return ""
    return parsed.astimezone(UTC).isoformat()


def aware_broker_order_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def broker_order_lifecycle_account_ref_hash_value(
    account_id: str, *, provider: str
) -> str:
    return broker_order_lifecycle_account_ref_hash(account_id, provider=provider)


def broker_order_lifecycle_account_ref_hash(account_id: str, *, provider: str) -> str:
    """Build the canonical provider-scoped opaque account reference."""
    if not account_id:
        return ""
    return broker_order_lifecycle_fingerprint(
        {
            "domain": "karkinos.broker_order_lifecycle.account_ref.v1",
            "provider": provider,
            "account_id": account_id,
        }
    )


def broker_order_lifecycle_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def format_broker_order_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def sanitize_broker_order_source_name(value: Any) -> str:
    source_name = str(value or "").strip()
    if not source_name or "/" in source_name or "\\" in source_name:
        return "broker local exact-order lifecycle export"
    return source_name[:128]


def broker_order_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else "0"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def broker_order_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def broker_order_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def broker_order_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def broker_order_json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
