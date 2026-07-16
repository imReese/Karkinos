"""Shared Account Truth gate construction for routes and review surfaces."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from account_truth.broker_evidence import (
    BrokerEvidenceRepository,
    BrokerImportRun,
    StoredBrokerEvidenceEvent,
)
from account_truth.manual_review import ManualReviewRepository
from account_truth.reconciliation import (
    KarkinosLedgerFact,
    KarkinosPositionFact,
    ReconciliationReport,
    build_reconciliation_report,
)
from account_truth.score import AccountTruthScore, build_account_truth_score
from server.ledger.models import LedgerEntry
from server.projections.service import build_portfolio_projection_from_db

ACCOUNT_TRUTH_PROMOTION_EVIDENCE_SCHEMA_VERSION = (
    "karkinos.account_truth.promotion_evidence.v1"
)
ACCOUNT_TRUTH_PROMOTION_MAX_AGE_SECONDS = 86400
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def build_latest_account_truth_score_payload(
    state: Any,
    *,
    data_freshness_status: str = "fresh",
) -> dict[str, object]:
    """Build the latest Account Truth score from staged broker evidence."""

    db_path = _db_path_for_state(state)
    if db_path is None:
        return {}

    repository = BrokerEvidenceRepository(db_path)
    import_run = _latest_reconcilable_import_run(repository)
    if import_run is None:
        return {}

    ledger_coverage = _ledger_coverage_for_import(state, import_run)
    effective_freshness = _freshness_with_ledger_coverage(
        data_freshness_status,
        ledger_coverage,
    )
    score = build_account_truth_score_for_import_run(
        state,
        repository=repository,
        import_run=import_run,
        data_freshness_status=effective_freshness,
    )
    payload = {
        **score.to_json_dict(),
        "status": "available",
        "import_run_id": import_run.import_run_id,
        "source_type": import_run.source_type,
        "source_name": import_run.source_name,
        "created_at": import_run.created_at,
        "ledger_coverage": ledger_coverage,
    }
    if ledger_coverage["status"] == "stale":
        payload["gate_status"] = "blocked"
        payload["blocking_reasons"] = list(
            dict.fromkeys(
                [
                    *list(payload.get("blocking_reasons") or []),
                    "account_truth_evidence_predates_latest_ledger",
                ]
            )
        )
        payload["required_actions"] = list(
            dict.fromkeys(
                [
                    *list(payload.get("required_actions") or []),
                    "reimport_broker_statement_after_latest_ledger_fact",
                ]
            )
        )
        payload["limitations"] = list(
            dict.fromkeys(
                [
                    *list(payload.get("limitations") or []),
                    "The latest broker evidence does not cover the latest local ledger fact.",
                ]
            )
        )
    return payload


def build_latest_account_truth_promotion_evidence(
    state: Any,
    *,
    clock: Callable[[], datetime] | None = None,
    max_age_seconds: int = ACCOUNT_TRUTH_PROMOTION_MAX_AGE_SECONDS,
) -> dict[str, object]:
    """Build sanitized, source-sensitive Account Truth promotion evidence."""

    db_path = _db_path_for_state(state)
    if db_path is None:
        return _missing_account_truth_promotion_evidence(
            ["account_truth_database_unavailable"]
        )
    repository = BrokerEvidenceRepository(db_path)
    import_run = _latest_reconcilable_import_run(repository)
    if import_run is None:
        return _missing_account_truth_promotion_evidence(
            ["account_truth_import_run_missing"]
        )

    now = _aware_utc((clock or (lambda: datetime.now(timezone.utc)))())
    captured_at = _parse_aware_timestamp(import_run.created_at)
    effective_max_age = max(60, min(int(max_age_seconds), 604800))
    blockers: list[str] = []
    age_seconds: int | None = None
    freshness_status = "missing"
    if captured_at is None:
        blockers.append("account_truth_import_timestamp_invalid")
    else:
        age = (now - captured_at).total_seconds()
        age_seconds = int(max(0, age))
        if age < -300:
            blockers.append("account_truth_import_timestamp_in_future")
        elif age > effective_max_age:
            blockers.append("account_truth_import_stale")
            freshness_status = "stale"
        else:
            freshness_status = "fresh"

    ledger_coverage = _ledger_coverage_for_import(state, import_run)
    freshness_status = _freshness_with_ledger_coverage(
        freshness_status,
        ledger_coverage,
    )
    if ledger_coverage["status"] == "stale":
        blockers.append("account_truth_evidence_predates_latest_ledger")

    report = build_reconciliation_report_for_import_run(
        state,
        repository=repository,
        import_run=import_run,
    )
    review_decisions = ManualReviewRepository(db_path).list_decisions(
        import_run.import_run_id
    )
    score = build_account_truth_score(
        report=report,
        review_decisions=review_decisions,
        data_freshness_status=freshness_status,
    )
    if import_run.validation_status == "blocked":
        blockers.append("account_truth_import_validation_blocked")
    if report.status == "blocked":
        blockers.append("account_truth_reconciliation_blocked")
    if score.gate_status != "pass":
        blockers.append(f"account_truth_gate_not_pass:{score.gate_status}")
    if score.unresolved_mismatch_count:
        blockers.append("account_truth_unresolved_mismatches")

    review_by_item = {decision.item_key: decision for decision in review_decisions}
    report_items = sorted(
        (
            {
                "item_key": _account_truth_item_key(item.category, item.symbol),
                "category": item.category,
                "symbol": item.symbol,
                "status": item.status,
                "broker_value": item.broker_value,
                "karkinos_value": item.karkinos_value,
                "difference": item.difference,
                "detail_code": item.detail_code,
                "review_status": str(
                    getattr(
                        review_by_item.get(
                            _account_truth_item_key(item.category, item.symbol)
                        ),
                        "review_status",
                        "",
                    )
                    or ""
                ),
            }
            for item in report.items
        ),
        key=lambda item: (item["category"], item["symbol"], item["item_key"]),
    )
    source_core = {
        "schema_version": ACCOUNT_TRUTH_PROMOTION_EVIDENCE_SCHEMA_VERSION,
        "import_run": {
            "import_run_id": import_run.import_run_id,
            "schema_version": import_run.schema_version,
            "source_type": import_run.source_type,
            "file_fingerprint": import_run.file_fingerprint,
            "row_count": import_run.row_count,
            "valid_row_count": import_run.valid_row_count,
            "invalid_row_count": import_run.invalid_row_count,
            "row_duplicate_count": import_run.row_duplicate_count,
            "validation_status": import_run.validation_status,
            "created_at": import_run.created_at,
        },
        "reconciliation": {
            "schema_version": report.schema_version,
            "status": report.status,
            "unresolved_count": report.unresolved_count,
            "items": report_items,
        },
        "score": score.to_json_dict(),
        "freshness": {
            "status": freshness_status,
            "max_age_seconds": effective_max_age,
            "ledger_coverage": ledger_coverage,
        },
    }
    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": ACCOUNT_TRUTH_PROMOTION_EVIDENCE_SCHEMA_VERSION,
        "status": "clear" if not unique_blockers else "blocked",
        "source_fingerprint": _fingerprint_json(source_core),
        "import_run_id": import_run.import_run_id,
        "file_fingerprint": import_run.file_fingerprint,
        "source_type": import_run.source_type,
        "captured_at": import_run.created_at,
        "import_validation_status": import_run.validation_status,
        "import_valid_row_count": import_run.valid_row_count,
        "current_age_seconds": age_seconds,
        "max_age_seconds": effective_max_age,
        "data_freshness_status": freshness_status,
        "ledger_coverage": ledger_coverage,
        "reconciliation_status": report.status,
        "score": score.score,
        "gate_status": score.gate_status,
        "cash_status": score.cash_status,
        "position_status": score.position_status,
        "fee_status": score.fee_status,
        "cost_basis_status": score.cost_basis_status,
        "unresolved_mismatch_count": score.unresolved_mismatch_count,
        "resolved_review_count": score.resolved_review_count,
        "reconciliation_items": report_items,
        "blockers": unique_blockers,
        "does_not_mutate_production_ledger": True,
        "does_not_issue_execution_authority": True,
        "broker_submission_enabled": False,
    }


def build_account_truth_score_for_import_run(
    state: Any,
    *,
    repository: BrokerEvidenceRepository,
    import_run: BrokerImportRun,
    data_freshness_status: str = "fresh",
) -> AccountTruthScore:
    """Reconcile one import run and build its account-truth score."""

    report = build_reconciliation_report_for_import_run(
        state,
        repository=repository,
        import_run=import_run,
    )
    db_path = _db_path_for_state(state)
    review_decisions = (
        ManualReviewRepository(db_path).list_decisions(import_run.import_run_id)
        if db_path is not None
        else []
    )
    effective_freshness = _freshness_with_ledger_coverage(
        data_freshness_status,
        _ledger_coverage_for_import(state, import_run),
    )
    return build_account_truth_score(
        report=report,
        review_decisions=review_decisions,
        data_freshness_status=effective_freshness,
    )


def build_reconciliation_report_for_import_run(
    state: Any,
    *,
    repository: BrokerEvidenceRepository,
    import_run: BrokerImportRun,
) -> ReconciliationReport:
    """Build a reconciliation report for one staged broker evidence run."""

    return build_reconciliation_report(
        import_run_id=import_run.import_run_id,
        broker_events=broker_events_for_import_run(repository, import_run),
        **_karkinos_account_facts(state),
    )


def broker_events_for_import_run(
    repository: BrokerEvidenceRepository,
    import_run: BrokerImportRun,
) -> list[StoredBrokerEvidenceEvent]:
    evidence_import_run_id = (
        import_run.duplicate_of_import_run_id or import_run.import_run_id
    )
    return repository.list_events(evidence_import_run_id)


def _latest_reconcilable_import_run(
    repository: BrokerEvidenceRepository,
) -> BrokerImportRun | None:
    for import_run in repository.list_import_runs(limit=100):
        if import_run.valid_row_count <= 0:
            continue
        if import_run.validation_status == "blocked":
            continue
        return import_run
    return None


def _karkinos_account_facts(state: Any) -> dict[str, object]:
    db = getattr(state, "db", None)
    config = getattr(state, "config", None)
    initial_cash = Decimal(str(getattr(config, "initial_cash", "0")))
    latest_quotes = _latest_quotes_by_symbol(db)
    projection = build_portfolio_projection_from_db(
        db,
        initial_cash=initial_cash,
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
        _ledger_fact_from_entry(LedgerEntry.from_row(row)) for row in ledger_rows
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


def _latest_quotes_by_symbol(db: Any) -> dict[str, dict[str, object]]:
    if db is None or not hasattr(db, "get_latest_quotes_sync"):
        return {}
    return {
        str(row.get("symbol")): row
        for row in db.get_latest_quotes_sync()
        if row.get("symbol")
    }


def _ledger_coverage_for_import(
    state: Any,
    import_run: BrokerImportRun,
) -> dict[str, object]:
    db = getattr(state, "db", None)
    reader = getattr(db, "get_ledger_entries_sync", None)
    import_timestamp = _parse_aware_timestamp(import_run.created_at)
    if not callable(reader):
        return {
            "status": "unknown",
            "import_created_at": import_run.created_at,
            "latest_ledger_created_at": None,
        }
    rows = list(reader(limit=1000, offset=0) or [])
    posting_covered_entry_ids = _posting_covered_ledger_entry_ids(
        db,
        import_run_id=import_run.import_run_id,
    )
    ledger_created_timestamps = [
        _parse_fact_timestamp(row.get("created_at"))
        for row in rows
        if isinstance(row, dict) and row.get("created_at")
    ]
    ledger_event_timestamps = [
        _parse_fact_timestamp(row.get("timestamp"))
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
    db_path = _db_path_for_state(state)
    if db_path is not None:
        repository = BrokerEvidenceRepository(db_path)
        broker_timestamps = [
            _parse_fact_timestamp(event.occurred_at)
            for event in broker_events_for_import_run(repository, import_run)
        ]
        broker_evidence_as_of = max(
            (value for value in broker_timestamps if value is not None),
            default=None,
        )
    stale_reasons: list[str] = []
    uncovered_created_after_import = any(
        (created_at := _parse_fact_timestamp(row.get("created_at"))) is not None
        and import_timestamp is not None
        and created_at > import_timestamp
        and int(row.get("id") or 0) not in posting_covered_entry_ids
        for row in rows
        if isinstance(row, dict)
    )
    if uncovered_created_after_import:
        stale_reasons.append("ledger_was_revised_after_broker_import")
    uncovered_event_after_evidence = any(
        (event_at := _parse_fact_timestamp(row.get("timestamp"))) is not None
        and broker_evidence_as_of is not None
        and event_at > broker_evidence_as_of
        and int(row.get("id") or 0) not in posting_covered_entry_ids
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
    }


def _posting_covered_ledger_entry_ids(
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
    return {
        int(row.get("id") or 0)
        for row in (getattr(db, "get_ledger_entries_sync")(limit=1000, offset=0) or [])
        if isinstance(row, dict)
        and int(row.get("id") or 0) in covered
        and str(row.get("source") or "") == "controlled_submission_ledger_posting"
    }


def _freshness_with_ledger_coverage(
    freshness_status: str,
    ledger_coverage: dict[str, object],
) -> str:
    if freshness_status == "fresh" and ledger_coverage.get("status") == "stale":
        return "stale"
    return freshness_status


def _parse_fact_timestamp(value: object) -> datetime | None:
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


def _ledger_fact_from_entry(entry: LedgerEntry) -> KarkinosLedgerFact:
    quantity = _decimal_or_zero(entry.quantity)
    price = _decimal_or_zero(entry.price)
    gross_amount = _optional_decimal(entry.gross_amount) or quantity * price
    fee = _ledger_fee_component(entry)
    tax = _ledger_tax_component(entry)
    transfer_fee = _ledger_transfer_fee_component(entry)
    return KarkinosLedgerFact(
        event_type=entry.entry_type,
        symbol=str(entry.symbol or ""),
        quantity=quantity,
        price=price,
        gross_amount=gross_amount,
        fee=fee,
        tax=tax,
        transfer_fee=transfer_fee,
        net_amount=_ledger_net_cash_impact(
            entry,
            gross_amount=gross_amount,
            fee=fee,
            tax=tax,
            transfer_fee=transfer_fee,
        ),
    )


def _db_path_for_state(state: Any) -> Path | None:
    raw_path = getattr(getattr(state, "db", None), "_path", None)
    return Path(raw_path) if raw_path is not None else None


def _missing_account_truth_promotion_evidence(
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


def _account_truth_item_key(category: str, symbol: str) -> str:
    return f"{category}:{symbol}" if symbol else category


def _parse_aware_timestamp(value: object) -> datetime | None:
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


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fingerprint_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _decimal_or_zero(value: object | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _optional_decimal(value: object | None) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _ledger_fee_component(entry: LedgerEntry) -> Decimal:
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
        (_breakdown_decimal(breakdown, key) or Decimal("0")) for key in fee_keys
    )
    if total != Decimal("0"):
        return abs(total)
    return abs(_decimal_or_zero(entry.commission))


def _ledger_tax_component(entry: LedgerEntry) -> Decimal:
    return abs(
        _breakdown_decimal(entry.fee_breakdown or {}, "stamp_tax", "tax")
        or Decimal("0")
    )


def _ledger_transfer_fee_component(entry: LedgerEntry) -> Decimal:
    return abs(
        _breakdown_decimal(entry.fee_breakdown or {}, "transfer_fee") or Decimal("0")
    )


def _breakdown_decimal(
    breakdown: dict[str, object],
    *keys: str,
) -> Decimal | None:
    for key in keys:
        value = breakdown.get(key)
        if value is not None and value != "":
            return Decimal(str(value))
    return None


def _ledger_net_cash_impact(
    entry: LedgerEntry,
    *,
    gross_amount: Decimal,
    fee: Decimal,
    tax: Decimal,
    transfer_fee: Decimal,
) -> Decimal:
    if entry.net_cash_impact is not None:
        return _decimal_or_zero(entry.net_cash_impact)

    entry_type = entry.entry_type
    total_cost = fee + tax + transfer_fee
    if entry_type == "trade_buy":
        return -(gross_amount + total_cost)
    if entry_type == "trade_sell":
        return gross_amount - total_cost
    if entry_type in {"cash_withdraw", "cash_withdrawal", "withdraw", "fee"}:
        return -abs(_decimal_or_zero(entry.amount))
    return _decimal_or_zero(entry.amount)
