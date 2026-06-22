"""Account Truth review routes — /api/account-truth/*"""

from __future__ import annotations

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
    ReconciliationItem,
    ReconciliationReport,
    ReconciliationStatus,
)
from server.account_truth_gate import (
    build_latest_account_truth_score_payload,
    build_reconciliation_report_for_import_run,
)


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
        return (
            build_latest_account_truth_score_payload(state) or _missing_score_response()
        )

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
    return build_reconciliation_report_for_import_run(
        state,
        repository=repository,
        import_run=import_run,
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
