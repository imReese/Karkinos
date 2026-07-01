"""Shared Account Truth gate construction for routes and review surfaces."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

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

    score = build_account_truth_score_for_import_run(
        state,
        repository=repository,
        import_run=import_run,
        data_freshness_status=data_freshness_status,
    )
    return {
        **score.to_json_dict(),
        "status": "available",
        "import_run_id": import_run.import_run_id,
        "source_type": import_run.source_type,
        "source_name": import_run.source_name,
        "created_at": import_run.created_at,
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
    return build_account_truth_score(
        report=report,
        review_decisions=review_decisions,
        data_freshness_status=data_freshness_status,
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
