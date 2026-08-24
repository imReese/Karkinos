"""Pure value, snapshot, and ledger helpers for the Account Truth gate."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from account_truth.broker_evidence import StoredBrokerEvidenceEvent
from account_truth.reconciliation import KarkinosLedgerFact
from server.ledger.models import LedgerEntry

ACCOUNT_TRUTH_PROMOTION_EVIDENCE_SCHEMA_VERSION = (
    "karkinos.account_truth.promotion_evidence.v1"
)
ACCOUNT_TRUTH_PROMOTION_MAX_AGE_SECONDS = 86400
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def parse_fact_timestamp(value: object) -> datetime | None:
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
        parsed = parsed.replace(tzinfo=_SHANGHAI_TZ)
    return parsed.astimezone(timezone.utc)


def same_shanghai_date(left: datetime, right: datetime) -> bool:
    return left.astimezone(_SHANGHAI_TZ).date() == right.astimezone(_SHANGHAI_TZ).date()


def ledger_fact_from_entry(entry: LedgerEntry) -> KarkinosLedgerFact:
    quantity = decimal_or_zero(entry.quantity)
    price = decimal_or_zero(entry.price)
    gross_amount = optional_decimal(entry.gross_amount) or quantity * price
    fee = ledger_fee_component(entry)
    tax = ledger_tax_component(entry)
    transfer_fee = ledger_transfer_fee_component(entry)
    return KarkinosLedgerFact(
        event_type=entry.entry_type,
        symbol=str(entry.symbol or ""),
        quantity=quantity,
        price=price,
        gross_amount=gross_amount,
        fee=fee,
        tax=tax,
        transfer_fee=transfer_fee,
        net_amount=ledger_net_cash_impact(
            entry,
            gross_amount=gross_amount,
            fee=fee,
            tax=tax,
            transfer_fee=transfer_fee,
        ),
    )


def db_path_for_state(state: Any) -> Path | None:
    raw_path = getattr(getattr(state, "db", None), "_path", None)
    return Path(raw_path) if raw_path is not None else None


def missing_account_truth_promotion_evidence(
    blockers: list[str],
) -> dict[str, object]:
    return {
        "schema_version": ACCOUNT_TRUTH_PROMOTION_EVIDENCE_SCHEMA_VERSION,
        "status": "blocked",
        "source_fingerprint": "",
        "import_run_id": "",
        "file_fingerprint": "",
        "source_type": "",
        "captured_at": "",
        "imported_at": "",
        "snapshot_capture": {
            "status": "missing",
            "captured_at": "",
            "latest_cash_snapshot_at": "",
            "latest_position_snapshot_at": "",
            "latest_non_snapshot_event_at": "",
            "blockers": ["account_truth_snapshot_evidence_missing"],
        },
        "current_age_seconds": None,
        "max_age_seconds": ACCOUNT_TRUTH_PROMOTION_MAX_AGE_SECONDS,
        "data_freshness_status": "missing",
        "reconciliation_status": "missing",
        "score": 0,
        "gate_status": "blocked",
        "cash_status": "missing",
        "position_status": "missing",
        "fee_status": "missing",
        "cost_basis_status": "missing",
        "unresolved_mismatch_count": 0,
        "resolved_review_count": 0,
        "blockers": list(dict.fromkeys(blockers)),
        "does_not_mutate_production_ledger": True,
        "does_not_issue_execution_authority": True,
        "broker_submission_enabled": False,
    }


def account_truth_item_key(category: str, symbol: str) -> str:
    return f"{category}:{symbol}" if symbol else category


def account_truth_snapshot_capture(
    events: list[StoredBrokerEvidenceEvent],
) -> dict[str, object]:
    """Resolve the effective Account Truth capture from persisted snapshots."""

    unique_events = [event for event in events if not event.is_row_duplicate]
    cash_timestamps = [
        parsed
        for event in unique_events
        if event.event_type == "cash_snapshot"
        and (parsed := parse_aware_timestamp(event.occurred_at)) is not None
    ]
    position_timestamps = [
        parsed
        for event in unique_events
        if event.event_type == "position_snapshot"
        and (parsed := parse_aware_timestamp(event.occurred_at)) is not None
    ]
    non_snapshot_timestamps = [
        parsed
        for event in unique_events
        if event.event_type not in {"cash_snapshot", "position_snapshot"}
        and (parsed := parse_aware_timestamp(event.occurred_at)) is not None
    ]
    latest_cash = max(cash_timestamps, default=None)
    latest_position = max(position_timestamps, default=None)
    latest_non_snapshot = max(non_snapshot_timestamps, default=None)
    blockers: list[str] = []
    if latest_cash is None:
        blockers.append("account_truth_cash_snapshot_missing")
    if latest_position is None:
        blockers.append("account_truth_position_snapshot_missing")

    captured_at = (
        min(latest_cash, latest_position)
        if latest_cash is not None and latest_position is not None
        else None
    )
    if (
        latest_cash is not None
        and latest_position is not None
        and latest_cash.astimezone(_SHANGHAI_TZ).date()
        != latest_position.astimezone(_SHANGHAI_TZ).date()
    ):
        blockers.append("account_truth_snapshot_dates_mismatch")
    if (
        captured_at is not None
        and latest_non_snapshot is not None
        and latest_non_snapshot > captured_at
    ):
        blockers.append("account_truth_snapshot_predates_latest_event")

    return {
        "status": "clear" if not blockers else "blocked",
        "captured_at": captured_at.isoformat() if captured_at is not None else "",
        "latest_cash_snapshot_at": (
            latest_cash.isoformat() if latest_cash is not None else ""
        ),
        "latest_position_snapshot_at": (
            latest_position.isoformat() if latest_position is not None else ""
        ),
        "latest_non_snapshot_event_at": (
            latest_non_snapshot.isoformat() if latest_non_snapshot is not None else ""
        ),
        "blockers": blockers,
    }


def parse_aware_timestamp(value: object) -> datetime | None:
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


def fingerprint_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def decimal_or_zero(value: object | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def optional_decimal(value: object | None) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def ledger_fee_component(entry: LedgerEntry) -> Decimal:
    breakdown = entry.fee_breakdown or {}
    fee_keys = (
        "commission",
        "subscription_fee",
        "redemption_fee",
        "exchange_clearing_fee",
        "surcharge_fee",
        "other_fees",
    )
    total = sum((breakdown_decimal(breakdown, key) or Decimal("0")) for key in fee_keys)
    if total != Decimal("0"):
        return abs(total)
    return abs(decimal_or_zero(entry.commission))


def ledger_tax_component(entry: LedgerEntry) -> Decimal:
    return abs(
        breakdown_decimal(entry.fee_breakdown or {}, "stamp_tax", "tax") or Decimal("0")
    )


def ledger_transfer_fee_component(entry: LedgerEntry) -> Decimal:
    return abs(
        breakdown_decimal(entry.fee_breakdown or {}, "transfer_fee") or Decimal("0")
    )


def breakdown_decimal(
    breakdown: dict[str, object],
    *keys: str,
) -> Decimal | None:
    for key in keys:
        value = breakdown.get(key)
        if value is not None and value != "":
            return Decimal(str(value))
    return None


def ledger_net_cash_impact(
    entry: LedgerEntry,
    *,
    gross_amount: Decimal,
    fee: Decimal,
    tax: Decimal,
    transfer_fee: Decimal,
) -> Decimal:
    if entry.net_cash_impact is not None:
        return decimal_or_zero(entry.net_cash_impact)

    entry_type = entry.entry_type
    total_cost = fee + tax + transfer_fee
    if entry_type == "trade_buy":
        return -(gross_amount + total_cost)
    if entry_type == "trade_sell":
        return gross_amount - total_cost
    if entry_type in {"cash_withdraw", "cash_withdrawal", "withdraw", "fee"}:
        return -abs(decimal_or_zero(entry.amount))
    return decimal_or_zero(entry.amount)
