"""Pure shared values for Account Truth gate and ledger projections."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from account_truth.broker_evidence import (
    BrokerEvidenceRepository,
    BrokerImportRun,
    StoredBrokerEvidenceEvent,
)
from account_truth.reconciliation import KarkinosLedgerFact
from server.ledger.models import LedgerEntry

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
        asset_class=str(entry.asset_class or ""),
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
    total = sum(
        (breakdown_decimal(breakdown, key) or Decimal("0") for key in fee_keys),
        start=Decimal("0"),
    )
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

    total_cost = fee + tax + transfer_fee
    if entry.entry_type == "trade_buy":
        return -(gross_amount + total_cost)
    if entry.entry_type == "trade_sell":
        return gross_amount - total_cost
    if entry.entry_type in {"cash_withdraw", "cash_withdrawal", "withdraw", "fee"}:
        return -abs(decimal_or_zero(entry.amount))
    return decimal_or_zero(entry.amount)


def broker_events_for_import_run(
    repository: BrokerEvidenceRepository,
    import_run: BrokerImportRun,
) -> list[StoredBrokerEvidenceEvent]:
    evidence_import_run_id = (
        import_run.duplicate_of_import_run_id or import_run.import_run_id
    )
    return repository.list_events(evidence_import_run_id)


__all__ = [
    "breakdown_decimal",
    "broker_events_for_import_run",
    "db_path_for_state",
    "decimal_or_zero",
    "ledger_fact_from_entry",
    "ledger_fee_component",
    "ledger_net_cash_impact",
    "ledger_tax_component",
    "ledger_transfer_fee_component",
    "optional_decimal",
    "parse_aware_timestamp",
    "parse_fact_timestamp",
    "same_shanghai_date",
]
