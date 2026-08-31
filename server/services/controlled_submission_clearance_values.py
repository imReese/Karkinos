"""Pure normalization, identity, and response values for clearance."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


def clearance_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = json_object(row.get("payload_json"))
    terminal_status = str(
        row.get("terminal_status") or payload.get("terminal_status") or "filled"
    )
    fill_count = int(row.get("fill_count") or 0)
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "clearance_id": str(row.get("clearance_id") or ""),
        "clearance_fingerprint": str(row.get("clearance_fingerprint") or ""),
        "submit_intent_id": str(row.get("submit_intent_id") or ""),
        "order_id": str(row.get("order_id") or ""),
        "status": str(row.get("status") or "cleared"),
        "terminal_status": terminal_status,
        "cancelled_quantity": str(
            row.get("cancelled_quantity") or payload.get("cancelled_quantity") or "0"
        ),
        "fill_count": fill_count,
        "fill_quantity": str(row.get("fill_quantity") or "0"),
        "cleared_at": str(row.get("cleared_at") or ""),
        "persisted": bool(row),
        "reused": reused,
        "interlock_released": True,
        "oms_terminal_status": terminal_status,
        "real_fills_recorded": fill_count > 0,
        "terminal_outcome_recorded": True,
        "production_ledger_mutated": False,
        "automatic_submission_enabled": False,
        "strategy_direct_submission_enabled": False,
        "safety": safety_flags(),
    }


def decimal_value(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def decimal_string(value: Decimal) -> str:
    return format(value.normalize(), "f")


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


def mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def parse_timestamp(value: Any) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def safety_flags() -> dict[str, bool]:
    return {
        "manual_final_signature_required": True,
        "exact_latest_reconciliation_required": True,
        "exact_broker_and_client_order_identity_required": True,
        "fresh_account_truth_required": True,
        "exact_terminal_outcome_required": True,
        "open_partial_fill_clearance_disabled": True,
        "partial_cancel_records_actual_fills_only": True,
        "atomic_fill_oms_clearance": True,
        "automatic_ledger_mutation_disabled": True,
        "automatic_submission_disabled": True,
        "strategy_direct_submission_disabled": True,
        "broker_cancel_disabled": True,
        "automatic_capital_expansion_disabled": True,
    }
