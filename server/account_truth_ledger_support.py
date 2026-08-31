"""Canonical ledger snapshots and Account Truth coverage projections."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from account_truth.broker_evidence import (
    BrokerEvidenceRepository,
    BrokerImportRun,
    StoredBrokerEvidenceEvent,
)
from account_truth.reconciliation import KarkinosPositionFact
from server.account_truth_gate_values import (
    broker_events_for_import_run,
    db_path_for_state,
    ledger_fact_from_entry,
    parse_aware_timestamp,
    parse_fact_timestamp,
    same_shanghai_date,
)
from server.ledger.models import LedgerEntry
from server.projections.legacy_fund_trade_duplicate_correction import (
    resolve_legacy_fund_trade_duplicate_exclusions,
)
from server.projections.service import build_portfolio_projection


def _mapping_rows(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise RuntimeError("Canonical repository returned an invalid row collection")
    if not all(isinstance(item, Mapping) for item in value):
        raise RuntimeError("Canonical repository returned an invalid row collection")
    return [dict(item) for item in value]


def _entry_id(row: Mapping[str, Any]) -> int:
    value = row.get("id")
    if value is None or value == "":
        return 0
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def load_canonical_ledger_rows(
    db: Any,
    *,
    batch_size: int = 500,
) -> list[dict[str, Any]]:
    """Read one shared ledger snapshot for all consumers in an evaluation."""

    snapshot_reader = getattr(db, "get_all_ledger_entries_sync", None)
    if callable(snapshot_reader):
        rows = _mapping_rows(snapshot_reader())
        _assert_unique_ledger_ids(rows)
        return rows
    reader = getattr(db, "get_ledger_entries_sync", None)
    if not callable(reader):
        return []
    batch = _mapping_rows(reader(limit=batch_size, offset=0))
    if len(batch) >= batch_size:
        raise RuntimeError(
            "A single-statement canonical ledger snapshot reader is required"
        )
    rows = [dict(row) for row in batch]
    _assert_unique_ledger_ids(rows)
    return rows


def _assert_unique_ledger_ids(rows: Sequence[dict[str, Any]]) -> None:
    ids: list[int] = []
    for row in rows:
        try:
            entry_id = _entry_id(row)
        except (TypeError, ValueError):
            raise RuntimeError(
                "Canonical ledger snapshot identity is invalid"
            ) from None
        if entry_id <= 0:
            raise RuntimeError("Canonical ledger snapshot identity is invalid")
        ids.append(entry_id)
    if len(ids) != len(set(ids)):
        raise RuntimeError("Canonical ledger snapshot contains duplicate identities")


def legacy_fund_duplicate_roll_forward_guardrail(
    ledger_entries: Sequence[dict[str, Any]],
) -> tuple[frozenset[int], str | None]:
    """Resolve server-owned correction evidence for the pure roll-forward writer."""

    rows = [dict(row) for row in ledger_entries]
    resolution = resolve_legacy_fund_trade_duplicate_exclusions(rows)
    if not resolution.valid:
        return (
            frozenset(),
            "daily_snapshot_roll_forward_legacy_fund_correction_invalid",
        )
    if not resolution.correction_entry_ids:
        return frozenset(), None
    try:
        build_portfolio_projection([LedgerEntry.from_row(row) for row in rows])
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return (
            frozenset(),
            "daily_snapshot_roll_forward_legacy_fund_correction_projection_invalid",
        )
    return frozenset(resolution.correction_entry_ids), None


def karkinos_account_facts(
    state: Any,
    *,
    ledger_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project account facts only from canonical ledger and persisted quotes."""

    db = getattr(state, "db", None)
    rows = load_canonical_ledger_rows(db) if ledger_rows is None else ledger_rows
    correction_resolution = resolve_legacy_fund_trade_duplicate_exclusions(rows)
    if not correction_resolution.valid:
        raise RuntimeError(
            "Account Truth legacy fund correction evidence is invalid: "
            + ",".join(correction_resolution.blockers)
        )
    latest_quotes = latest_quotes_by_symbol(db)
    projection = build_portfolio_projection(
        [LedgerEntry.from_row(row) for row in rows],
        initial_cash=Decimal("0"),
        latest_quotes=latest_quotes,
    )
    asset_classes_by_symbol: dict[str, str] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol or symbol in asset_classes_by_symbol:
            continue
        asset_classes_by_symbol[symbol] = (
            str(row.get("asset_class") or "stock").strip().lower() or "stock"
        )
    ledger_facts = [
        ledger_fact_from_entry(LedgerEntry.from_row(row))
        for row in rows
        if _entry_id(row) not in correction_resolution.excluded_manual_entry_ids
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
    *,
    ledger_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Prove whether staged broker evidence covers the current ledger."""

    db = getattr(state, "db", None)
    reader = getattr(db, "get_ledger_entries_sync", None)
    snapshot_reader = getattr(db, "get_all_ledger_entries_sync", None)
    import_timestamp = parse_aware_timestamp(import_run.created_at)
    if not callable(reader) and not callable(snapshot_reader):
        return {
            "status": "unknown",
            "reasons": ["ledger_reader_unavailable"],
            "import_created_at": import_run.created_at,
            "latest_ledger_created_at": None,
        }
    rows = (
        load_canonical_ledger_rows(db)
        if ledger_rows is None
        else [dict(row) for row in ledger_rows]
    )
    correction_resolution = resolve_legacy_fund_trade_duplicate_exclusions(rows)
    posting_covered_entry_ids = posting_covered_ledger_entry_ids(
        db,
        import_run_id=import_run.import_run_id,
        ledger_rows=rows,
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
    if correction_resolution.valid:
        covered_entry_ids.update(correction_resolution.correction_entry_ids)
    stale_reasons: list[str] = []
    if not correction_resolution.valid:
        stale_reasons.extend(correction_resolution.blockers)
    uncovered_created_after_import = any(
        (created_at := parse_fact_timestamp(row.get("created_at"))) is not None
        and import_timestamp is not None
        and created_at > import_timestamp
        and _entry_id(row) not in covered_entry_ids
        for row in rows
        if isinstance(row, dict)
    )
    if uncovered_created_after_import:
        stale_reasons.append("ledger_was_revised_after_broker_import")
    uncovered_event_after_evidence = any(
        (event_at := parse_fact_timestamp(row.get("timestamp"))) is not None
        and broker_evidence_as_of is not None
        and event_at > broker_evidence_as_of
        and _entry_id(row) not in covered_entry_ids
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
        "legacy_fund_duplicate_correction_entry_count": len(
            correction_resolution.correction_entry_ids
        ),
    }


def broker_evidence_covered_ledger_entry_ids(
    rows: list[dict[str, Any]],
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
        rows,
        key=lambda row: _entry_id(row),
    ):
        entry_id = _entry_id(row)
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
    ledger_rows: list[dict[str, Any]] | None = None,
) -> set[int]:
    """Return immutable ledger rows proven to originate from one broker import."""

    reader = getattr(db, "list_controlled_submission_ledger_postings_sync", None)
    if not callable(reader):
        return set()
    covered: set[int] = set()
    for posting in _mapping_rows(reader(limit=1000)):
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
            entry_id
            for entry_id in entry_ids
            if isinstance(entry_id, int) and entry_id > 0
        )
    rows = load_canonical_ledger_rows(db) if ledger_rows is None else ledger_rows
    return {
        _entry_id(row)
        for row in rows
        if isinstance(row, dict)
        and _entry_id(row) in covered
        and str(row.get("source") or "") == "controlled_submission_ledger_posting"
    }


def freshness_with_ledger_coverage(
    freshness_status: str,
    ledger_coverage: dict[str, object],
) -> str:
    if freshness_status == "fresh" and ledger_coverage.get("status") != "covered":
        return "stale"
    return freshness_status
