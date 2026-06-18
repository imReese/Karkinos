"""Account Truth review routes — /api/account-truth/*"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from account_truth.broker_evidence import (
    BrokerEvidenceRepository,
    BrokerImportRun,
    StoredBrokerEvidenceEvent,
)
from account_truth.manual_review import (
    ManualReviewDecision,
    ManualReviewRepository,
    ManualReviewStatus,
)
from account_truth.reconciliation import (
    KarkinosLedgerFact,
    KarkinosPositionFact,
    ReconciliationItem,
    ReconciliationReport,
    ReconciliationStatus,
    build_reconciliation_report,
)
from account_truth.score import AccountTruthScore, build_account_truth_score
from server.ledger.models import LedgerEntry
from server.projections.service import build_portfolio_projection_from_db


class ReviewDecisionCreate(BaseModel):
    category: str
    review_status: ManualReviewStatus
    symbol: str = ""
    note: str = ""
    reviewer: str = "local"


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/account-truth", tags=["account-truth"])

    @r.get("/import-runs")
    async def list_import_runs(limit: int = 50) -> list[dict[str, object]]:
        from server.app import get_app_state

        repository = _repository_for_state(get_app_state())
        return [
            _import_run_response(import_run)
            for import_run in repository.list_import_runs(limit=limit)
        ]

    @r.get("/reconciliation-reports")
    async def list_reconciliation_reports(
        status: ReconciliationStatus | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        from server.app import get_app_state

        state = get_app_state()
        repository = _repository_for_state(state)
        responses = []
        for import_run in repository.list_import_runs(limit=limit):
            report = _build_report_for_import_run(state, repository, import_run)
            if status is not None and report.status != status:
                continue
            responses.append(_report_summary_response(import_run, report))
        return responses

    @r.get("/score")
    async def get_account_truth_score() -> dict[str, object]:
        from server.app import get_app_state

        state = get_app_state()
        repository = _repository_for_state(state)
        import_run = _latest_reconcilable_import_run(repository)
        if import_run is None:
            return _missing_score_response()
        report = _build_report_for_import_run(state, repository, import_run)
        review_decisions = _manual_review_repository_for_state(state).list_decisions(
            import_run.import_run_id
        )
        score = build_account_truth_score(
            report=report,
            review_decisions=review_decisions,
            data_freshness_status="fresh",
        )
        return _score_response(import_run, score)

    @r.get("/reconciliation-reports/{import_run_id}")
    async def get_reconciliation_report(import_run_id: str) -> dict[str, object]:
        from server.app import get_app_state

        state = get_app_state()
        repository = _repository_for_state(state)
        import_run = repository.get_import_run(import_run_id)
        if import_run is None:
            raise HTTPException(status_code=404, detail="Import run not found")
        report = _build_report_for_import_run(state, repository, import_run)
        return _report_detail_response(import_run, report, repository, state)

    @r.post("/reconciliation-reports/{import_run_id}/items/{item_key}/review")
    async def record_review_decision(
        import_run_id: str,
        item_key: str,
        body: ReviewDecisionCreate,
    ) -> dict[str, object]:
        from server.app import get_app_state

        state = get_app_state()
        repository = _repository_for_state(state)
        if repository.get_import_run(import_run_id) is None:
            raise HTTPException(status_code=404, detail="Import run not found")
        review_repository = _manual_review_repository_for_state(state)
        decision = review_repository.record_decision(
            import_run_id=import_run_id,
            item_key=item_key,
            category=body.category,
            symbol=body.symbol,
            review_status=body.review_status,
            note=body.note,
            reviewer=body.reviewer,
        )
        return _decision_response(decision)

    return r


def _repository_for_state(state) -> BrokerEvidenceRepository:
    db_path = getattr(getattr(state, "db", None), "_path", None)
    if db_path is None:
        raise HTTPException(
            status_code=503, detail="Account Truth database unavailable"
        )
    return BrokerEvidenceRepository(Path(db_path))


def _manual_review_repository_for_state(state) -> ManualReviewRepository:
    db_path = getattr(getattr(state, "db", None), "_path", None)
    if db_path is None:
        raise HTTPException(
            status_code=503, detail="Account Truth database unavailable"
        )
    return ManualReviewRepository(Path(db_path))


def _build_report_for_import_run(
    state,
    repository: BrokerEvidenceRepository,
    import_run: BrokerImportRun,
) -> ReconciliationReport:
    broker_events = repository.list_events(import_run.import_run_id)
    facts = _karkinos_account_facts(state)
    return build_reconciliation_report(
        import_run_id=import_run.import_run_id,
        broker_events=broker_events,
        ledger_facts=facts["ledger_facts"],
        cash_balance=facts["cash_balance"],
        positions=facts["positions"],
    )


def _latest_reconcilable_import_run(
    repository: BrokerEvidenceRepository,
) -> BrokerImportRun | None:
    for import_run in repository.list_import_runs(limit=100):
        if import_run.duplicate_of_import_run_id:
            continue
        if import_run.valid_row_count <= 0:
            continue
        return import_run
    return None


def _karkinos_account_facts(state) -> dict[str, object]:
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
            cost_basis=position.avg_cost,
        )
        for position in projection.positions.values()
        if position.quantity != Decimal("0")
    ]
    return {
        "ledger_facts": ledger_facts,
        "cash_balance": projection.cash,
        "positions": positions,
    }


def _latest_quotes_by_symbol(db) -> dict[str, dict[str, object]]:
    if db is None or not hasattr(db, "get_latest_quotes_sync"):
        return {}
    return {
        str(row.get("symbol")): row
        for row in db.get_latest_quotes_sync()
        if row.get("symbol")
    }


def _ledger_fact_from_entry(entry: LedgerEntry) -> KarkinosLedgerFact:
    return KarkinosLedgerFact(
        event_type=entry.entry_type,
        symbol=str(entry.symbol or ""),
        quantity=_decimal_or_zero(entry.quantity),
        price=_decimal_or_zero(entry.price),
        fee=_decimal_or_zero(entry.commission),
        tax=Decimal("0"),
        net_amount=_decimal_or_zero(entry.amount),
    )


def _import_run_response(import_run: BrokerImportRun) -> dict[str, object]:
    return {
        "import_run_id": import_run.import_run_id,
        "schema_version": import_run.schema_version,
        "source_type": import_run.source_type,
        "source_name": import_run.source_name,
        "file_fingerprint": import_run.file_fingerprint,
        "row_count": import_run.row_count,
        "valid_row_count": import_run.valid_row_count,
        "invalid_row_count": import_run.invalid_row_count,
        "row_duplicate_count": import_run.row_duplicate_count,
        "file_duplicate_count": import_run.file_duplicate_count,
        "validation_status": import_run.validation_status,
        "limitations": list(import_run.limitations),
        "duplicate_of_import_run_id": import_run.duplicate_of_import_run_id,
        "created_at": import_run.created_at,
    }


def _report_summary_response(
    import_run: BrokerImportRun,
    report: ReconciliationReport,
) -> dict[str, object]:
    return {
        "import_run_id": report.import_run_id,
        "schema_version": report.schema_version,
        "status": report.status,
        "row_count": import_run.row_count,
        "validation_status": import_run.validation_status,
        "source_type": import_run.source_type,
        "source_name": import_run.source_name,
        "created_at": import_run.created_at,
        "unresolved_count": report.unresolved_count,
        "cash_difference": str(report.cash_difference),
        "fee_difference": str(report.fee_difference),
        "tax_difference": str(report.tax_difference),
        "suggested_review_actions": list(report.suggested_review_actions),
        "limitations": list(import_run.limitations),
    }


def _report_detail_response(
    import_run: BrokerImportRun,
    report: ReconciliationReport,
    repository: BrokerEvidenceRepository,
    state,
) -> dict[str, object]:
    events = repository.list_events(import_run.import_run_id)
    review_decisions = _manual_review_repository_for_state(state).list_decisions(
        import_run.import_run_id
    )
    review_by_item = {decision.item_key: decision for decision in review_decisions}
    return {
        **_report_summary_response(import_run, report),
        "items": [
            _item_response(item, events, review_by_item.get(_item_key(item)))
            for item in report.items
        ],
    }


def _item_response(
    item: ReconciliationItem,
    events: list[StoredBrokerEvidenceEvent],
    latest_review: ManualReviewDecision | None = None,
) -> dict[str, object]:
    return {
        "item_key": _item_key(item),
        "category": item.category,
        "status": item.status,
        "severity": item.status,
        "symbol": item.symbol,
        "broker_value": item.broker_value,
        "karkinos_value": item.karkinos_value,
        "difference": item.difference,
        "suggested_review_action": item.suggested_review_action,
        "detail": item.detail,
        "evidence_references": _evidence_references(item, events),
        "latest_review": (
            _decision_response(latest_review) if latest_review is not None else None
        ),
    }


def _evidence_references(
    item: ReconciliationItem,
    events: list[StoredBrokerEvidenceEvent],
) -> list[str]:
    if item.category == "position" and item.symbol:
        return [
            f"broker_event:{event.import_run_id}:{event.symbol}:{event.event_type}"
            for event in events
            if event.symbol == item.symbol and event.event_type == "position_snapshot"
        ]
    if item.category == "cash":
        return [
            f"broker_event:{event.import_run_id}:cash:{event.event_type}"
            for event in events
            if event.event_type == "cash_snapshot"
        ]
    if item.category in {"fee", "tax", "cost_basis"}:
        return [
            f"broker_event:{event.import_run_id}:{event.symbol or item.category}:{event.event_type}"
            for event in events
            if event.event_type in {item.category, "position_snapshot"}
        ]
    return []


def _item_key(item: ReconciliationItem) -> str:
    if item.symbol:
        return f"{item.category}:{item.symbol}"
    return item.category


def _decision_response(decision: ManualReviewDecision) -> dict[str, object]:
    return {
        "id": decision.id,
        "import_run_id": decision.import_run_id,
        "item_key": decision.item_key,
        "category": decision.category,
        "symbol": decision.symbol,
        "review_status": decision.review_status,
        "note": decision.note,
        "reviewer": decision.reviewer,
        "schema_version": decision.schema_version,
        "created_at": decision.created_at,
        "updated_at": decision.updated_at,
        "does_not_mutate_production_ledger": True,
    }


def _score_response(
    import_run: BrokerImportRun,
    score: AccountTruthScore,
) -> dict[str, object]:
    return {
        **score.to_json_dict(),
        "status": "available",
        "import_run_id": import_run.import_run_id,
        "source_type": import_run.source_type,
        "source_name": import_run.source_name,
        "created_at": import_run.created_at,
    }


def _missing_score_response() -> dict[str, object]:
    return {
        "schema_version": "karkinos.account_truth.score.v1",
        "status": "missing",
        "import_run_id": None,
        "score": None,
        "gate_status": "blocked",
        "cash_status": "missing",
        "position_status": "missing",
        "fee_status": "missing",
        "cost_basis_status": "missing",
        "data_freshness_status": "missing",
        "unresolved_mismatch_count": None,
        "resolved_review_count": 0,
        "required_actions": ["import_and_reconcile_broker_evidence"],
        "blocking_reasons": ["account_truth_score_unavailable"],
        "limitations": [
            "Account Truth review requires staged broker evidence before trusted use."
        ],
    }


def _decimal_or_zero(value: object | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))
