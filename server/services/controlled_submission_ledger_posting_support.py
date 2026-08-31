"""Pure value projection for controlled-submission ledger posting."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

_MONEY_TOLERANCE = Decimal("0.005")


def _ledger_entry_descriptor(
    *,
    fill: dict[str, Any],
    metadata: dict[str, Any],
    event: Any,
    intent: dict[str, Any],
    order: dict[str, Any],
    import_run_id: str,
) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    side = str(order.get("side") or "").lower()
    quantity = abs(_decimal(getattr(event, "quantity", "0")))
    price = abs(_decimal(getattr(event, "price", "0")))
    gross = abs(_decimal(getattr(event, "gross_amount", "0")))
    fee = abs(_decimal(getattr(event, "fee", "0")))
    tax = abs(_decimal(getattr(event, "tax", "0")))
    transfer_fee = abs(_decimal(getattr(event, "transfer_fee", "0")))
    net_amount = _decimal(getattr(event, "net_amount", "0"))
    total_fee = fee + tax + transfer_fee
    expected_net = -(gross + total_fee) if side == "buy" else gross - total_fee
    if side not in {"buy", "sell"}:
        blockers.append("controlled_ledger_posting_side_invalid")
    if quantity <= 0 or price <= 0 or gross <= 0:
        blockers.append("controlled_ledger_posting_trade_values_invalid")
    if abs(gross - quantity * price) > _MONEY_TOLERANCE:
        blockers.append("controlled_ledger_posting_gross_amount_mismatch")
    if abs(net_amount - expected_net) > _MONEY_TOLERANCE:
        blockers.append("controlled_ledger_posting_net_amount_mismatch")
    comparisons = {
        "symbol": (
            str(fill.get("symbol") or ""),
            str(getattr(event, "symbol", "") or ""),
        ),
        "asset_class": (
            str(fill.get("asset_class") or ""),
            str(getattr(event, "asset_class", "") or ""),
        ),
        "broker_order_id": (
            str(intent.get("broker_order_id") or ""),
            str(getattr(event, "broker_order_id", "") or ""),
        ),
        "client_order_id": (
            str(intent.get("client_order_id") or ""),
            str(getattr(event, "client_order_id", "") or ""),
        ),
    }
    for field, (expected, actual) in comparisons.items():
        if expected != actual:
            blockers.append(f"controlled_ledger_posting_{field}_mismatch")
    if abs(_decimal(fill.get("fill_quantity")) - quantity) > Decimal("0.00000001"):
        blockers.append("controlled_ledger_posting_fill_quantity_mismatch")
    if abs(_decimal(fill.get("fill_price")) - price) > _MONEY_TOLERANCE:
        blockers.append("controlled_ledger_posting_fill_price_mismatch")
    if abs(_decimal(fill.get("commission")) - fee) > _MONEY_TOLERANCE:
        blockers.append("controlled_ledger_posting_fill_fee_mismatch")
    event_id = str(getattr(event, "event_id", "") or "")
    row_fingerprint = str(getattr(event, "row_fingerprint", "") or "")
    if str(metadata.get("broker_event_id") or "") != event_id:
        blockers.append("controlled_ledger_posting_fill_event_mismatch")
    if str(metadata.get("broker_row_fingerprint") or "") != row_fingerprint:
        blockers.append("controlled_ledger_posting_fill_row_mismatch")
    fee_breakdown = {
        "commission": _decimal_string(fee),
        "stamp_tax": _decimal_string(tax),
        "transfer_fee": _decimal_string(transfer_fee),
        "other_fees": "0",
        "total_fee": _decimal_string(total_fee),
        "confirmation_source": "broker_statement",
    }
    descriptor = {
        "fill_id": str(fill.get("fill_id") or ""),
        "broker_event_id": event_id,
        "broker_row_fingerprint": row_fingerprint,
        "entry_type": f"trade_{side}",
        "timestamp": str(getattr(event, "occurred_at", "") or ""),
        "settled_at": str(
            getattr(event, "settled_at", "") or getattr(event, "occurred_at", "") or ""
        ),
        "symbol": str(getattr(event, "symbol", "") or ""),
        "direction": side,
        "quantity": _decimal_string(quantity),
        "price": _decimal_string(price),
        "amount": _decimal_string(gross),
        "commission": _decimal_string(fee),
        "gross_amount": _decimal_string(gross),
        "net_cash_impact": _decimal_string(net_amount),
        "fee_breakdown": fee_breakdown,
        "fee_rule_id": "broker_statement_exact",
        "fee_rule_version": "broker_statement_exact.v1",
        "cost_basis_method": "broker_remaining_cost",
        "asset_class": str(getattr(event, "asset_class", "") or "stock"),
        "note": "Controlled submission reconciled ledger posting.",
        "source": "controlled_submission_ledger_posting",
        "source_ref": str(fill.get("fill_id") or ""),
        "settlement_status": "confirmed",
        "settlement_source": "broker_statement",
        "settlement_source_ref": f"{import_run_id}:{event_id}",
        "settlement_note": "Exact broker evidence bound by signed clearance.",
        "account_truth_import_run_id": import_run_id,
    }
    return descriptor, blockers


def _posting_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = _json_object(row.get("payload_json"))
    try:
        ledger_entry_ids = json.loads(row.get("ledger_entry_ids_json") or "[]")
    except (TypeError, ValueError):
        ledger_entry_ids = []
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "posting_id": str(row.get("posting_id") or ""),
        "posting_fingerprint": str(row.get("posting_fingerprint") or ""),
        "clearance_id": str(row.get("clearance_id") or ""),
        "submit_intent_id": str(row.get("submit_intent_id") or ""),
        "order_id": str(row.get("order_id") or ""),
        "status": str(row.get("status") or "applied"),
        "ledger_entry_count": int(row.get("ledger_entry_count") or 0),
        "ledger_entry_ids": (
            ledger_entry_ids if isinstance(ledger_entry_ids, list) else []
        ),
        "pre_ledger_cutoff_id": int(row.get("pre_ledger_cutoff_id") or 0),
        "post_ledger_cutoff_id": int(row.get("post_ledger_cutoff_id") or 0),
        "applied_at": str(row.get("applied_at") or ""),
        "persisted": bool(row),
        "reused": reused,
        "production_ledger_mutated": int(row.get("ledger_entry_count") or 0) > 0,
        "automatic_posting_enabled": False,
        "broker_submission_enabled": False,
        "broker_cancel_enabled": False,
        "capital_authority_changed": False,
        "safety": _safety_flags(),
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "persisted_facts_only": True,
        "exact_terminal_clearance_required": True,
        "operator_signature_required": True,
        "pre_ledger_identity_rechecked_in_transaction": True,
        "all_ledger_entries_one_transaction": True,
        "exactly_once_posting": True,
        "partial_cancel_posts_actual_fills_only": True,
        "zero_fill_cancel_creates_no_trade_entry": True,
        "corrections_require_compensating_events": True,
        "ledger_history_deletion_disabled": True,
        "automatic_posting_disabled": True,
        "provider_contact_disabled": True,
        "broker_submit_disabled": True,
        "broker_cancel_disabled": True,
        "strategy_direct_broker_access_disabled": True,
        "ai_trade_authority_disabled": True,
        "capital_authority_change_disabled": True,
    }


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _decimal_string(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _parse_timestamp(value: Any) -> datetime | None:
    normalized = str(value or "").strip().replace("Z", "+00:00")
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return _aware_utc(parsed)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


ledger_entry_descriptor = _ledger_entry_descriptor
posting_response = _posting_response
safety_flags = _safety_flags
fingerprint = _fingerprint
json_object = _json_object
mapping = _mapping
decimal_value = _decimal
decimal_string = _decimal_string
parse_timestamp = _parse_timestamp
aware_utc = _aware_utc
