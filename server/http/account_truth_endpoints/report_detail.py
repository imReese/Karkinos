"""Account-truth report detail HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from account_truth.broker_evidence import BrokerEvidenceReadRejected
from account_truth.manual_review import ManualReviewReadRejected
from server.contracts.http.account_truth import ReviewDecisionCreate


def create_router(facade: Any) -> APIRouter:
    r = APIRouter(prefix="/api/account-truth", tags=["account-truth"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    _account_truth_read_http_exception = dependency(
        "_account_truth_read_http_exception"
    )
    _build_report_for_import_run = dependency("_build_report_for_import_run")
    _decision_response = dependency("_decision_response")
    _item_key = dependency("_item_key")
    _manual_review_repository_for_state = dependency(
        "_manual_review_repository_for_state"
    )
    _report_detail_response = dependency("_report_detail_response")
    _repository_for_state = dependency("_repository_for_state")
    reconciliation_item_fingerprint = dependency("reconciliation_item_fingerprint")

    @r.get("/reconciliation-reports/{import_run_id}")
    async def get_reconciliation_report(import_run_id: str) -> dict[str, object]:
        from server.dependencies import get_app_state

        state = get_app_state()
        repository = _repository_for_state(state)
        try:
            import_run = repository.get_import_run(import_run_id)
            if import_run is None:
                raise HTTPException(status_code=404, detail="Import run not found")
            report = _build_report_for_import_run(state, repository, import_run)
            return _report_detail_response(import_run, report, repository, state)
        except (BrokerEvidenceReadRejected, ManualReviewReadRejected) as exc:
            raise _account_truth_read_http_exception(exc) from exc

    @r.post("/reconciliation-reports/{import_run_id}/items/{item_key}/review")
    async def record_review_decision(
        import_run_id: str,
        item_key: str,
        body: ReviewDecisionCreate,
    ) -> dict[str, object]:
        from server.dependencies import get_app_state

        state = get_app_state()
        repository = _repository_for_state(state)
        try:
            import_run = repository.get_import_run(import_run_id)
            if import_run is None:
                raise HTTPException(status_code=404, detail="Import run not found")
            report = _build_report_for_import_run(state, repository, import_run)
            current_item = next(
                (item for item in report.items if _item_key(item) == item_key),
                None,
            )
        except BrokerEvidenceReadRejected as exc:
            raise _account_truth_read_http_exception(exc) from exc
        if current_item is None:
            raise HTTPException(status_code=404, detail="Reconciliation item not found")
        if body.category != current_item.category or body.symbol != current_item.symbol:
            raise HTTPException(
                status_code=409,
                detail="Review identity does not match the current reconciliation item",
            )
        review_repository = _manual_review_repository_for_state(state)
        try:
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
        except ManualReviewReadRejected as exc:
            raise _account_truth_read_http_exception(exc) from exc
        return _decision_response(decision)

    return r
