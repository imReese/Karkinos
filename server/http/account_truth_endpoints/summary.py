"""Account-truth summary HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def create_router(facade: Any) -> APIRouter:
    r = APIRouter(prefix="/api/account-truth", tags=["account-truth"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    BrokerEvidenceReadRejected = dependency("BrokerEvidenceReadRejected")
    BrokerStatementPreviewCreate = dependency("BrokerStatementPreviewCreate")
    EvidenceScopeReviewReadRejected = dependency("EvidenceScopeReviewReadRejected")
    HTTPException = dependency("HTTPException")
    ManualReviewReadRejected = dependency("ManualReviewReadRejected")
    ReconciliationStatus = dependency("ReconciliationStatus")
    _account_truth_read_http_exception = dependency(
        "_account_truth_read_http_exception"
    )
    _build_report_for_import_run = dependency("_build_report_for_import_run")
    _import_run_response = dependency("_import_run_response")
    _latest_import_runs_by_fingerprint = dependency(
        "_latest_import_runs_by_fingerprint"
    )
    _missing_score_response = dependency("_missing_score_response")
    _preview_response = dependency("_preview_response")
    _report_summary_response = dependency("_report_summary_response")
    _repository_for_state = dependency("_repository_for_state")
    build_account_truth_evidence_readiness = dependency(
        "build_account_truth_evidence_readiness"
    )
    build_latest_account_truth_score_payload = dependency(
        "build_latest_account_truth_score_payload"
    )
    parse_broker_statement_csv = dependency("parse_broker_statement_csv")

    @r.post("/broker-statement/import")
    async def import_broker_statement(
        body: BrokerStatementPreviewCreate,
    ) -> dict[str, object]:
        from server.dependencies import get_app_state

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
        try:
            import_run = repository.save_preview(
                preview,
                source_name=body.source_name.strip() or "local-broker-statement.csv",
            )
            report = _build_report_for_import_run(state, repository, import_run)
        except BrokerEvidenceReadRejected as exc:
            raise _account_truth_read_http_exception(exc) from exc
        return {
            "import_run": _import_run_response(import_run),
            "preview": _preview_response(preview, source_name=body.source_name),
            "report": _report_summary_response(import_run, report),
            "does_not_mutate_production_ledger": True,
        }

    @r.get("/broker-statement/collector")
    async def get_broker_statement_collector_status() -> dict[str, object]:
        from server.dependencies import get_app_state

        collector = getattr(get_app_state(), "broker_statement_collector", None)
        if collector is None:
            return {
                "schema_version": (
                    "karkinos.account_truth.local_broker_statement_collector.v1"
                ),
                "enabled": False,
                "state": "disabled",
                "configured_path": "",
                "source_name": "",
                "file_present": False,
                "poll_interval_seconds": 0,
                "stability_delay_seconds": 0,
                "max_file_bytes": 0,
                "last_observed_at": None,
                "last_processed_at": None,
                "last_success_at": None,
                "file_fingerprint": None,
                "import_run_id": None,
                "validation_status": None,
                "row_count": None,
                "valid_row_count": None,
                "invalid_row_count": None,
                "duplicate_row_count": None,
                "error_code": "collector_not_initialized",
                "message": "Local broker-statement collector is not initialized.",
                "source_kind": "local_file_readonly",
                "does_not_mutate_production_ledger": True,
                "does_not_contact_provider": True,
                "does_not_change_execution_authority": True,
            }
        return collector.status().to_dict()

    @r.get("/import-runs")
    async def list_import_runs(limit: int = 50) -> list[dict[str, object]]:
        from server.dependencies import get_app_state

        repository = _repository_for_state(get_app_state())
        try:
            return [
                _import_run_response(import_run)
                for import_run in _latest_import_runs_by_fingerprint(
                    repository.list_import_runs(limit=limit)
                )
            ]
        except BrokerEvidenceReadRejected as exc:
            raise _account_truth_read_http_exception(exc) from exc

    @r.get("/reconciliation-reports")
    async def list_reconciliation_reports(
        status: ReconciliationStatus | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        from server.dependencies import get_app_state

        state = get_app_state()
        repository = _repository_for_state(state)
        try:
            responses = []
            for import_run in _latest_import_runs_by_fingerprint(
                repository.list_import_runs(limit=limit)
            ):
                report = _build_report_for_import_run(state, repository, import_run)
                if status is not None and report.status != status:
                    continue
                responses.append(_report_summary_response(import_run, report))
            return responses
        except BrokerEvidenceReadRejected as exc:
            raise _account_truth_read_http_exception(exc) from exc

    @r.get("/score")
    async def get_account_truth_score() -> dict[str, object]:
        from server.dependencies import get_app_state

        state = get_app_state()
        try:
            return (
                build_latest_account_truth_score_payload(state)
                or _missing_score_response()
            )
        except (BrokerEvidenceReadRejected, ManualReviewReadRejected) as exc:
            raise _account_truth_read_http_exception(exc) from exc

    @r.get("/evidence-readiness")
    async def get_account_truth_evidence_readiness() -> dict[str, object]:
        from server.dependencies import get_app_state

        try:
            return build_account_truth_evidence_readiness(get_app_state())
        except (
            BrokerEvidenceReadRejected,
            ManualReviewReadRejected,
            EvidenceScopeReviewReadRejected,
        ) as exc:
            raise _account_truth_read_http_exception(exc) from exc

    return r
