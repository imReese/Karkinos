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
from account_truth.broker_statement import (
    BrokerEvidenceEvent,
    BrokerStatementPreview,
    BrokerStatementValidationError,
    parse_broker_statement_csv,
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
from account_truth.score import reconciliation_item_fingerprint
from server.account_truth_gate import (
    broker_events_for_import_run,
    build_latest_account_truth_score_payload,
    build_reconciliation_report_for_import_run,
)


class ReviewDecisionCreate(BaseModel):
    category: str
    review_status: ManualReviewStatus
    symbol: str = ""
    note: str = ""
    reviewer: str = "local"


class BrokerStatementPreviewCreate(BaseModel):
    content: str
    source_name: str = "local-broker-statement.csv"


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/account-truth", tags=["account-truth"])

    @r.post("/broker-statement/preview")
    async def preview_broker_statement(
        body: BrokerStatementPreviewCreate,
    ) -> dict[str, object]:
        preview = parse_broker_statement_csv(body.content)
        return _preview_response(preview, source_name=body.source_name)

    @r.post("/broker-statement/import")
    async def import_broker_statement(
        body: BrokerStatementPreviewCreate,
    ) -> dict[str, object]:
        from server.app import get_app_state

        state = get_app_state()
        repository = _repository_for_state(state)
        preview = parse_broker_statement_csv(body.content)
        if preview.validation_status == "blocked":
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Broker statement preview is blocked.",
                    "preview": _preview_response(preview, source_name=body.source_name),
                },
            )
        import_run = repository.save_preview(
            preview,
            source_name=body.source_name.strip() or "local-broker-statement.csv",
        )
        report = _build_report_for_import_run(state, repository, import_run)
        return {
            "import_run": _import_run_response(import_run),
            "preview": _preview_response(preview, source_name=body.source_name),
            "report": _report_summary_response(import_run, report),
            "does_not_mutate_production_ledger": True,
        }

    @r.get("/import-runs")
    async def list_import_runs(limit: int = 50) -> list[dict[str, object]]:
        from server.app import get_app_state

        repository = _repository_for_state(get_app_state())
        return [
            _import_run_response(import_run)
            for import_run in _latest_import_runs_by_fingerprint(
                repository.list_import_runs(limit=limit)
            )
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
        for import_run in _latest_import_runs_by_fingerprint(
            repository.list_import_runs(limit=limit)
        ):
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
        import_run = repository.get_import_run(import_run_id)
        if import_run is None:
            raise HTTPException(status_code=404, detail="Import run not found")
        report = _build_report_for_import_run(state, repository, import_run)
        current_item = next(
            (item for item in report.items if _item_key(item) == item_key),
            None,
        )
        if current_item is None:
            raise HTTPException(status_code=404, detail="Reconciliation item not found")
        if body.category != current_item.category or body.symbol != current_item.symbol:
            raise HTTPException(
                status_code=409,
                detail="Review identity does not match the current reconciliation item",
            )
        review_repository = _manual_review_repository_for_state(state)
        decision = review_repository.record_decision(
            import_run_id=import_run_id,
            item_key=item_key,
            category=body.category,
            symbol=body.symbol,
            review_status=body.review_status,
            note=body.note,
            reviewer=body.reviewer,
            evidence_fingerprint=reconciliation_item_fingerprint(current_item),
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


def _latest_import_runs_by_fingerprint(
    import_runs: list[BrokerImportRun],
) -> list[BrokerImportRun]:
    latest: list[BrokerImportRun] = []
    seen_fingerprints: set[str] = set()
    for import_run in import_runs:
        fingerprint = import_run.file_fingerprint or import_run.import_run_id
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        latest.append(import_run)
    return latest


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


def _preview_response(
    preview: BrokerStatementPreview,
    *,
    source_name: str,
) -> dict[str, object]:
    return {
        "schema_version": preview.schema_version,
        "source_type": preview.source_type,
        "source_name": source_name,
        "generated_at": preview.generated_at,
        "file_fingerprint": preview.file_fingerprint,
        "normalized_columns": list(preview.normalized_columns),
        "row_count": preview.row_count,
        "valid_row_count": preview.valid_row_count,
        "invalid_row_count": preview.invalid_row_count,
        "duplicate_row_count": preview.duplicate_row_count,
        "validation_status": preview.validation_status,
        "limitations": list(preview.limitations),
        "errors": [_preview_error_response(error) for error in preview.errors],
        "events_preview": [
            _preview_event_response(event) for event in preview.events[:20]
        ],
        "preview_event_count": min(len(preview.events), 20),
        "total_event_count": len(preview.events),
        "does_not_mutate_production_ledger": True,
    }


def _preview_error_response(
    error: BrokerStatementValidationError,
) -> dict[str, object]:
    return {
        "row_number": error.row_number,
        "code": error.code,
        "message": error.message,
    }


def _preview_event_response(event: BrokerEvidenceEvent) -> dict[str, object]:
    return {
        "row_number": event.row_number,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "occurred_at": event.occurred_at,
        "settled_at": event.settled_at,
        "symbol": event.symbol,
        "instrument_name": event.instrument_name,
        "asset_class": event.asset_class,
        "currency": event.currency,
        "quantity": str(event.quantity),
        "price": str(event.price),
        "gross_amount": str(event.gross_amount),
        "fee": str(event.fee),
        "tax": str(event.tax),
        "net_amount": str(event.net_amount),
        "cash_balance": (
            str(event.cash_balance) if event.cash_balance is not None else None
        ),
        "position_quantity": (
            str(event.position_quantity)
            if event.position_quantity is not None
            else None
        ),
        "cost_basis": str(event.cost_basis) if event.cost_basis is not None else None,
        "is_duplicate": event.is_duplicate,
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
    events = broker_events_for_import_run(repository, import_run)
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
        "display_name": _display_name_for_item(item, events),
        "broker_value": item.broker_value,
        "karkinos_value": item.karkinos_value,
        "difference": item.difference,
        "suggested_review_action": item.suggested_review_action,
        "detail_code": item.detail_code,
        "detail": item.detail,
        "detail_context": dict(item.detail_context),
        "evidence_references": _evidence_references(item, events),
        "evidence_fingerprint": reconciliation_item_fingerprint(item),
        "latest_review": (
            {
                **_decision_response(latest_review),
                "is_current": latest_review.evidence_fingerprint
                == reconciliation_item_fingerprint(item),
            }
            if latest_review is not None
            else None
        ),
        "manual_review_does_not_override_mismatch": True,
    }


def _display_name_for_item(
    item: ReconciliationItem,
    events: list[StoredBrokerEvidenceEvent],
) -> str | None:
    if not item.symbol:
        return None
    for event in events:
        if event.symbol == item.symbol and event.instrument_name.strip():
            return event.instrument_name
    return None


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
    if item.category in {
        "trade_gross_amount",
        "net_cash_impact",
        "fee",
        "tax",
        "transfer_fee",
        "cost_basis",
    }:
        event_types = (
            {"trade_buy", "trade_sell"}
            if item.category
            in {"trade_gross_amount", "net_cash_impact", "transfer_fee"}
            else {item.category, "position_snapshot", "trade_buy", "trade_sell"}
        )
        return [
            f"broker_event:{event.import_run_id}:{event.symbol or item.category}:{event.event_type}"
            for event in events
            if event.event_type in event_types
            and (not item.symbol or event.symbol == item.symbol)
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
        "evidence_fingerprint": decision.evidence_fingerprint,
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
