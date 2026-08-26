"""Pure value, snapshot, and ledger helpers for the Account Truth gate."""

from __future__ import annotations

import hashlib
import json
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
from account_truth.reconciliation import KarkinosLedgerFact, KarkinosPositionFact
from server.ledger.models import LedgerEntry
from server.projections.service import build_portfolio_projection_from_db

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


def broker_events_for_import_run(
    repository: BrokerEvidenceRepository,
    import_run: BrokerImportRun,
) -> list[StoredBrokerEvidenceEvent]:
    evidence_import_run_id = (
        import_run.duplicate_of_import_run_id or import_run.import_run_id
    )
    return repository.list_events(evidence_import_run_id)


def latest_reconcilable_import_run(
    repository: BrokerEvidenceRepository,
) -> BrokerImportRun | None:
    for import_run in repository.list_import_runs(limit=100):
        if import_run.valid_row_count <= 0:
            continue
        if import_run.validation_status == "blocked":
            continue
        return import_run
    return None


def karkinos_account_facts(state: Any) -> dict[str, object]:
    """Project account facts only from canonical ledger and persisted quotes."""

    db = getattr(state, "db", None)
    latest_quotes = latest_quotes_by_symbol(db)
    projection = build_portfolio_projection_from_db(
        db,
        initial_cash=Decimal("0"),
        latest_quotes=latest_quotes,
    )
    ledger_rows = db.get_ledger_entries_sync(limit=1000, offset=0)
    asset_classes_by_symbol: dict[str, str] = {}
    for row in ledger_rows:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol or symbol in asset_classes_by_symbol:
            continue
        asset_classes_by_symbol[symbol] = (
            str(row.get("asset_class") or "stock").strip().lower() or "stock"
        )
    ledger_facts = [
        ledger_fact_from_entry(LedgerEntry.from_row(row)) for row in ledger_rows
    ]
    positions = [
        KarkinosPositionFact(
            symbol=position.symbol,
            quantity=position.quantity,
            cost_basis=(
                position.broker_displayed_unit_cost
                if position.broker_displayed_unit_cost != Decimal("0")
                else position.avg_cost
            ),
            cost_basis_method=(
                position.broker_cost_basis_method or "moving_average_buy_cost"
            ),
            asset_class=asset_classes_by_symbol.get(position.symbol, ""),
        )
        for position in projection.positions.values()
        if position.quantity != Decimal("0")
    ]
    return {
        "ledger_facts": ledger_facts,
        "cash_balance": projection.cash,
        "positions": positions,
    }


def latest_quotes_by_symbol(db: Any) -> dict[str, dict[str, object]]:
    if db is None or not hasattr(db, "get_latest_quotes_sync"):
        return {}
    return {
        str(row.get("symbol")): row
        for row in db.get_latest_quotes_sync()
        if row.get("symbol")
    }


def ledger_coverage_for_import(
    state: Any,
    import_run: BrokerImportRun,
) -> dict[str, object]:
    """Prove whether staged broker evidence covers the current ledger."""

    db = getattr(state, "db", None)
    reader = getattr(db, "get_ledger_entries_sync", None)
    import_timestamp = parse_aware_timestamp(import_run.created_at)
    if not callable(reader):
        return {
            "status": "unknown",
            "import_created_at": import_run.created_at,
            "latest_ledger_created_at": None,
        }
    rows = list(reader(limit=1000, offset=0) or [])
    posting_covered_entry_ids = posting_covered_ledger_entry_ids(
        db,
        import_run_id=import_run.import_run_id,
    )
    ledger_created_timestamps = [
        parse_fact_timestamp(row.get("created_at"))
        for row in rows
        if isinstance(row, dict) and row.get("created_at")
    ]
    ledger_event_timestamps = [
        parse_fact_timestamp(row.get("timestamp"))
        for row in rows
        if isinstance(row, dict) and row.get("timestamp")
    ]
    latest_ledger_created = max(
        (value for value in ledger_created_timestamps if value is not None),
        default=None,
    )
    latest_ledger_event = max(
        (value for value in ledger_event_timestamps if value is not None),
        default=None,
    )
    broker_evidence_as_of: datetime | None = None
    broker_events: list[StoredBrokerEvidenceEvent] = []
    db_path = db_path_for_state(state)
    if db_path is not None:
        repository = BrokerEvidenceRepository(db_path)
        broker_events = broker_events_for_import_run(repository, import_run)
        broker_timestamps = [
            parse_fact_timestamp(event.occurred_at) for event in broker_events
        ]
        broker_evidence_as_of = max(
            (value for value in broker_timestamps if value is not None),
            default=None,
        )
    broker_evidence_covered_entry_ids = broker_evidence_covered_ledger_entry_ids(
        rows,
        broker_events,
    )
    covered_entry_ids = posting_covered_entry_ids | broker_evidence_covered_entry_ids
    stale_reasons: list[str] = []
    uncovered_created_after_import = any(
        (created_at := parse_fact_timestamp(row.get("created_at"))) is not None
        and import_timestamp is not None
        and created_at > import_timestamp
        and int(row.get("id") or 0) not in covered_entry_ids
        for row in rows
        if isinstance(row, dict)
    )
    if uncovered_created_after_import:
        stale_reasons.append("ledger_was_revised_after_broker_import")
    uncovered_event_after_evidence = any(
        (event_at := parse_fact_timestamp(row.get("timestamp"))) is not None
        and broker_evidence_as_of is not None
        and event_at > broker_evidence_as_of
        and int(row.get("id") or 0) not in covered_entry_ids
        for row in rows
        if isinstance(row, dict)
    )
    if uncovered_event_after_evidence:
        stale_reasons.append("broker_evidence_does_not_cover_latest_ledger_event")
    if stale_reasons:
        status = "stale"
    elif rows and (import_timestamp is None or broker_evidence_as_of is None):
        status = "unknown"
    else:
        status = "covered"
    return {
        "status": status,
        "reasons": stale_reasons,
        "import_created_at": import_run.created_at,
        "latest_ledger_created_at": (
            latest_ledger_created.isoformat()
            if latest_ledger_created is not None
            else None
        ),
        "latest_ledger_event_at": (
            latest_ledger_event.isoformat() if latest_ledger_event is not None else None
        ),
        "broker_evidence_as_of": (
            broker_evidence_as_of.isoformat()
            if broker_evidence_as_of is not None
            else None
        ),
        "controlled_posting_lineage_entry_count": len(posting_covered_entry_ids),
        "broker_evidence_lineage_entry_count": len(broker_evidence_covered_entry_ids),
    }


def broker_evidence_covered_ledger_entry_ids(
    rows: list[object],
    broker_events: list[StoredBrokerEvidenceEvent],
) -> set[int]:
    """Match later local dividend capture to exact earlier broker evidence."""

    available_dividends = sorted(
        (
            event
            for event in broker_events
            if event.event_type == "dividend" and not event.is_row_duplicate
        ),
        key=lambda event: (event.occurred_at, event.row_number),
    )
    cash_snapshot_times = [
        timestamp
        for event in broker_events
        if event.event_type == "cash_snapshot" and not event.is_row_duplicate
        if (timestamp := parse_fact_timestamp(event.occurred_at)) is not None
    ]
    covered: set[int] = set()
    for row in sorted(
        (row for row in rows if isinstance(row, dict)),
        key=lambda row: int(row.get("id") or 0),
    ):
        entry_id = int(row.get("id") or 0)
        if entry_id <= 0 or str(row.get("entry_type") or "") != "dividend":
            continue
        ledger_at = parse_fact_timestamp(row.get("timestamp"))
        if ledger_at is None:
            continue
        ledger_fact = ledger_fact_from_entry(LedgerEntry.from_row(row))
        for index, event in enumerate(available_dividends):
            broker_at = parse_fact_timestamp(event.occurred_at)
            if broker_at is None or broker_at > ledger_at:
                continue
            if not same_shanghai_date(broker_at, ledger_at):
                continue
            if str(event.symbol or "").strip() != ledger_fact.symbol.strip():
                continue
            if Decimal(event.net_amount) != ledger_fact.net_amount:
                continue
            if not any(snapshot_at >= broker_at for snapshot_at in cash_snapshot_times):
                continue
            covered.add(entry_id)
            del available_dividends[index]
            break
    return covered


def posting_covered_ledger_entry_ids(
    db: Any,
    *,
    import_run_id: str,
) -> set[int]:
    """Return immutable ledger rows proven to originate from one broker import."""

    reader = getattr(db, "list_controlled_submission_ledger_postings_sync", None)
    if not callable(reader):
        return set()
    covered: set[int] = set()
    for posting in reader(limit=1000) or []:
        if (
            not isinstance(posting, dict)
            or posting.get("status") != "applied"
            or str(posting.get("account_truth_import_run_id") or "") != import_run_id
        ):
            continue
        try:
            entry_ids = json.loads(posting.get("ledger_entry_ids_json") or "[]")
        except (TypeError, ValueError):
            continue
        if not isinstance(entry_ids, list):
            continue
        covered.update(
            int(entry_id)
            for entry_id in entry_ids
            if isinstance(entry_id, int) and entry_id > 0
        )
    ledger_reader = getattr(db, "get_ledger_entries_sync")
    return {
        int(row.get("id") or 0)
        for row in (ledger_reader(limit=1000, offset=0) or [])
        if isinstance(row, dict)
        and int(row.get("id") or 0) in covered
        and str(row.get("source") or "") == "controlled_submission_ledger_posting"
    }


def freshness_with_ledger_coverage(
    freshness_status: str,
    ledger_coverage: dict[str, object],
) -> str:
    if freshness_status == "fresh" and ledger_coverage.get("status") == "stale":
        return "stale"
    return freshness_status
