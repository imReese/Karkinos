"""Account Truth review routes — /api/account-truth/*"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from account_truth.broker_evidence import (
    BrokerEvidenceReadRejected,
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
from account_truth.citic_broker_soak_candidate import (
    build_citic_broker_soak_candidate,
)
from account_truth.citic_history_xls import (
    CITIC_HISTORY_XLS_MAX_BYTES,
    parse_citic_history_xls,
    recognized_non_financial_activity_count,
)
from account_truth.citic_history_xls_directory import (
    CiticHistoryXlsBatchAssessment,
    CiticHistoryXlsDirectoryRejected,
    CiticHistoryXlsDirectoryScan,
    find_citic_history_xls_directory_preview,
    scan_citic_history_xls_directory,
)
from account_truth.citic_source_canonical_resolution import (
    CiticSourceCanonicalResolutionReadRejected,
    CiticSourceCanonicalResolutionRejected,
)
from account_truth.citic_source_intake import (
    CiticSourceIntake,
    CiticSourceIntakeReadRejected,
    CiticSourceIntakeRejected,
    CiticSourceIntakeRepository,
    citic_preview_is_recordable_for_follow_up,
    citic_source_preview_fingerprint,
    required_evidence_for_citic_preview,
)
from account_truth.citic_source_query_window_review import (
    CiticSourceQueryWindowReview,
    CiticSourceQueryWindowReviewReadRejected,
    CiticSourceQueryWindowReviewRejected,
)
from account_truth.citic_source_scope_review import (
    CiticSourceScopeReview,
    CiticSourceScopeReviewReadRejected,
    CiticSourceScopeReviewRejected,
)
from account_truth.evidence_scope_review import (
    EvidenceScopeReviewReadRejected,
    EvidenceScopeReviewRejected,
)
from account_truth.manual_review import (
    ManualReviewDecision,
    ManualReviewReadRejected,
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
from server.config import CiticHistoryXlsDirectoryConfig
from server.services.account_truth_evidence_readiness import (
    build_account_truth_evidence_readiness,
)
from server.services.account_truth_evidence_scope_review import (
    record_account_truth_evidence_scope_review,
    revoke_account_truth_evidence_scope_review,
)
from server.services.citic_history_canonical_lineage import (
    build_citic_history_canonical_lineage_assessment,
)
from server.services.citic_source_canonical_resolution import (
    record_citic_source_canonical_resolution,
    revoke_citic_source_canonical_resolution,
)
from server.services.citic_source_query_window_review import (
    citic_source_query_window_review_response,
    latest_citic_query_window_reviews_by_intake,
    project_citic_query_window_batch_assessment,
    record_citic_source_query_window_review,
    revoke_citic_source_query_window_review,
)
from server.services.citic_source_scope_review import (
    active_citic_source_scope_review,
    citic_source_scope_review_response,
    latest_citic_source_scope_reviews_by_intake,
    project_citic_source_scope_batch_assessment,
    record_citic_source_scope_review,
    revoke_citic_source_scope_review,
)
from server.services.reviewed_fee_schedule import (
    REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
    ReviewedFeeScheduleReadRejected,
    ReviewedFeeScheduleRejected,
    ReviewedFeeScheduleReviewRepository,
    build_reviewed_fee_schedule_preview,
    build_reviewed_fee_schedule_review_status,
)

CITIC_HISTORY_XLS_MAX_BASE64_CHARS = ((CITIC_HISTORY_XLS_MAX_BYTES + 2) // 3) * 4


class ReviewDecisionCreate(BaseModel):
    category: str
    review_status: ManualReviewStatus
    symbol: str = ""
    note: str = ""
    reviewer: str = "local"


class BrokerStatementPreviewCreate(BaseModel):
    content: str
    source_name: str = "local-broker-statement.csv"


class CiticHistoryXlsPreviewCreate(BaseModel):
    content_base64: str


class CiticHistoryXlsIntakeCreate(BaseModel):
    content_base64: str
    expected_file_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_status: Literal["follow_up_required", "rejected"]


class CiticHistoryXlsDirectoryIntakeCreate(BaseModel):
    expected_file_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_status: Literal["follow_up_required", "rejected"]


class CiticHistoryXlsQueryWindowReviewCreate(BaseModel):
    content_base64: str
    expected_file_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_source_preview_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    query_end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    query_window_attested: Literal[True]
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class CiticHistoryXlsDirectoryQueryWindowReviewCreate(BaseModel):
    expected_file_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_source_preview_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    query_end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    query_window_attested: Literal[True]
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class CiticHistoryXlsQueryWindowReviewRevoke(BaseModel):
    intake_id: str = Field(min_length=1, max_length=128)
    expected_active_review_id: str = Field(min_length=1, max_length=128)
    expected_active_review_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class CiticHistoryXlsSourceScopeReviewCreate(BaseModel):
    intake_id: str = Field(min_length=1, max_length=128)
    expected_file_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_source_preview_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_query_window_review_id: str = Field(min_length=1, max_length=128)
    expected_query_window_review_fingerprint: str = Field(
        pattern=r"^sha256:[0-9a-f]{64}$"
    )
    account_alias: str = Field(min_length=1, max_length=128)
    account_reference_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    account_type: str = Field(pattern=r"^[a-z][a-z0-9_:-]{0,63}$")
    market_scopes: list[str] = Field(min_length=1, max_length=32)
    asset_classes: list[str] = Field(min_length=1, max_length=32)
    account_value_band: str = Field(pattern=r"^[a-z][a-z0-9_:-]{0,63}$")
    business_types: list[str] = Field(min_length=1, max_length=32)
    no_other_filters_attested: Literal[True]
    complete_returned_results_attested: Literal[True]
    source_scope_attested: Literal[True]
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class CiticHistoryXlsSourceScopeReviewRevoke(BaseModel):
    intake_id: str = Field(min_length=1, max_length=128)
    expected_active_review_id: str = Field(min_length=1, max_length=128)
    expected_active_review_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class EvidenceScopeReviewCreate(BaseModel):
    import_run_id: str = Field(min_length=1, max_length=128)
    expected_observed_scope_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    provider: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._:-]{0,63}$")
    account_alias: str = Field(min_length=1, max_length=128)
    account_reference_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    coverage_start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    coverage_end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    asset_classes: list[str] = Field(min_length=1, max_length=16)
    full_account_scope_attested: Literal[True]
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class EvidenceScopeReviewRevoke(BaseModel):
    import_run_id: str = Field(min_length=1, max_length=128)
    expected_observed_scope_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class CiticSourceCanonicalResolutionCreate(BaseModel):
    expected_source_set_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_scope_review_id: str = Field(min_length=1, max_length=128)
    expected_scope_review_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    canonical_statement_covers_sources_attested: Literal[True]
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class CiticSourceCanonicalResolutionRevoke(BaseModel):
    expected_resolution_id: str = Field(min_length=1, max_length=128)
    expected_resolution_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class ReviewedFeeSchedulePreviewCreate(BaseModel):
    effective_start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    effective_end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reviewed_asset_classes: list[Literal["stock"]] = Field(
        default_factory=lambda: ["stock"],
        min_length=1,
        max_length=1,
    )


class ReviewedFeeScheduleReviewCreate(ReviewedFeeSchedulePreviewCreate):
    expected_preview_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)
    confirmation: str


class ReviewedFeeScheduleReviewRevoke(BaseModel):
    expected_review_id: str = Field(min_length=1, max_length=128)
    expected_review_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)
    confirmation: str


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/account-truth", tags=["account-truth"])

    @r.post("/broker-statement/preview")
    async def preview_broker_statement(
        body: BrokerStatementPreviewCreate,
    ) -> dict[str, object]:
        preview = parse_broker_statement_csv(body.content)
        return _preview_response(preview, source_name=body.source_name)

    @r.post("/citic-history-xls/preview")
    async def preview_citic_history_xls(
        body: CiticHistoryXlsPreviewCreate,
    ) -> dict[str, object]:
        return _citic_history_xls_preview_response(
            _parse_citic_history_xls_transport(body.content_base64)
        )

    @r.post("/citic-history-xls/intakes")
    async def record_citic_history_xls_intake(
        body: CiticHistoryXlsIntakeCreate,
    ) -> dict[str, object]:
        from server.app import get_app_state

        preview = _parse_citic_history_xls_transport(body.content_base64)
        return _record_citic_source_intake(
            state=get_app_state(),
            preview=preview,
            expected_file_fingerprint=body.expected_file_fingerprint,
            review_status=body.review_status,
        )

    @r.get("/citic-history-xls/directory")
    async def get_citic_history_xls_directory_status() -> dict[str, object]:
        from server.app import get_app_state

        config = _citic_history_xls_directory_config_for_state(get_app_state())
        return _citic_history_xls_directory_status_response(config)

    @r.post("/citic-history-xls/directory/scan")
    async def scan_configured_citic_history_xls_directory() -> dict[str, object]:
        from server.app import get_app_state

        state = get_app_state()
        config = _citic_history_xls_directory_config_for_state(state)
        scan = scan_citic_history_xls_directory(
            path=config.path,
            enabled=config.enabled,
            max_files=config.max_files,
            max_file_bytes=config.max_file_bytes,
            max_total_bytes=config.max_total_bytes,
        )
        intakes, reviews, scope_reviews = _citic_source_reviews_for_state(
            state,
            limit=config.max_files,
        )
        canonical_lineage_assessment = build_citic_history_canonical_lineage_assessment(
            state,
            scan=scan,
        )
        return _citic_history_xls_directory_scan_response(
            scan,
            config=config,
            intakes=intakes,
            query_window_reviews=reviews,
            source_scope_reviews=scope_reviews,
            canonical_lineage_assessment=canonical_lineage_assessment,
        )

    @r.post("/citic-history-xls/directory/intakes")
    async def record_configured_citic_history_xls_directory_intake(
        body: CiticHistoryXlsDirectoryIntakeCreate,
    ) -> dict[str, object]:
        from server.app import get_app_state

        state = get_app_state()
        config = _citic_history_xls_directory_config_for_state(state)
        try:
            preview = find_citic_history_xls_directory_preview(
                expected_file_fingerprint=body.expected_file_fingerprint,
                path=config.path,
                enabled=config.enabled,
                max_files=config.max_files,
                max_file_bytes=config.max_file_bytes,
                max_total_bytes=config.max_total_bytes,
            )
        except CiticHistoryXlsDirectoryRejected as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": exc.code,
                    "message": "Configured CITIC source could not be re-verified.",
                },
            ) from exc
        return _record_citic_source_intake(
            state=state,
            preview=preview,
            expected_file_fingerprint=body.expected_file_fingerprint,
            review_status=body.review_status,
        )

    @r.post("/citic-history-xls/query-window-reviews")
    async def record_citic_history_xls_query_window_review(
        body: CiticHistoryXlsQueryWindowReviewCreate,
    ) -> dict[str, object]:
        from server.app import get_app_state

        preview = _parse_citic_history_xls_transport(body.content_base64)
        try:
            return record_citic_source_query_window_review(
                get_app_state(),
                preview=preview,
                **body.model_dump(exclude={"content_base64"}),
            )
        except CiticSourceQueryWindowReviewRejected as exc:
            raise _citic_query_window_review_http_exception(exc) from exc
        except CiticSourceQueryWindowReviewReadRejected as exc:
            raise _citic_query_window_review_read_http_exception(exc) from exc

    @r.post("/citic-history-xls/directory/query-window-reviews")
    async def record_configured_citic_history_xls_query_window_review(
        body: CiticHistoryXlsDirectoryQueryWindowReviewCreate,
    ) -> dict[str, object]:
        from server.app import get_app_state

        state = get_app_state()
        config = _citic_history_xls_directory_config_for_state(state)
        try:
            preview = find_citic_history_xls_directory_preview(
                expected_file_fingerprint=body.expected_file_fingerprint,
                path=config.path,
                enabled=config.enabled,
                max_files=config.max_files,
                max_file_bytes=config.max_file_bytes,
                max_total_bytes=config.max_total_bytes,
            )
            return record_citic_source_query_window_review(
                state,
                preview=preview,
                **body.model_dump(),
            )
        except CiticHistoryXlsDirectoryRejected as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": exc.code,
                    "message": "Configured CITIC source could not be re-verified.",
                },
            ) from exc
        except CiticSourceQueryWindowReviewRejected as exc:
            raise _citic_query_window_review_http_exception(exc) from exc
        except CiticSourceQueryWindowReviewReadRejected as exc:
            raise _citic_query_window_review_read_http_exception(exc) from exc

    @r.post("/citic-history-xls/query-window-reviews/revoke")
    async def revoke_citic_history_xls_query_window_review(
        body: CiticHistoryXlsQueryWindowReviewRevoke,
    ) -> dict[str, object]:
        from server.app import get_app_state

        try:
            return revoke_citic_source_query_window_review(
                get_app_state(),
                **body.model_dump(),
            )
        except CiticSourceQueryWindowReviewRejected as exc:
            raise _citic_query_window_review_http_exception(exc) from exc
        except CiticSourceQueryWindowReviewReadRejected as exc:
            raise _citic_query_window_review_read_http_exception(exc) from exc

    @r.post("/citic-history-xls/source-scope-reviews")
    async def record_citic_history_xls_source_scope_review(
        body: CiticHistoryXlsSourceScopeReviewCreate,
    ) -> dict[str, object]:
        from server.app import get_app_state

        try:
            return record_citic_source_scope_review(
                get_app_state(),
                **body.model_dump(),
            )
        except CiticSourceScopeReviewRejected as exc:
            raise _citic_source_scope_review_http_exception(exc) from exc
        except CiticSourceScopeReviewReadRejected as exc:
            raise _citic_source_scope_review_read_http_exception(exc) from exc

    @r.post("/citic-history-xls/source-scope-reviews/revoke")
    async def revoke_citic_history_xls_source_scope_review(
        body: CiticHistoryXlsSourceScopeReviewRevoke,
    ) -> dict[str, object]:
        from server.app import get_app_state

        try:
            return revoke_citic_source_scope_review(
                get_app_state(),
                **body.model_dump(),
            )
        except CiticSourceScopeReviewRejected as exc:
            raise _citic_source_scope_review_http_exception(exc) from exc
        except CiticSourceScopeReviewReadRejected as exc:
            raise _citic_source_scope_review_read_http_exception(exc) from exc

    @r.get("/citic-history-xls/intakes")
    async def list_citic_history_xls_intakes(
        limit: int = 50,
    ) -> list[dict[str, object]]:
        from server.app import get_app_state

        intakes, reviews, scope_reviews = _citic_source_reviews_for_state(
            get_app_state(),
            limit=limit,
        )
        return [
            _citic_source_intake_response(
                intake,
                query_window_review=reviews.get(intake.intake_id),
                source_scope_review=scope_reviews.get(intake.intake_id),
            )
            for intake in intakes
        ]

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
        from server.app import get_app_state

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
        from server.app import get_app_state

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
        from server.app import get_app_state

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
        from server.app import get_app_state

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
        from server.app import get_app_state

        try:
            return build_account_truth_evidence_readiness(get_app_state())
        except (
            BrokerEvidenceReadRejected,
            ManualReviewReadRejected,
            EvidenceScopeReviewReadRejected,
        ) as exc:
            raise _account_truth_read_http_exception(exc) from exc

    @r.post("/fee-schedule/preview")
    async def preview_reviewed_fee_schedule(
        body: ReviewedFeeSchedulePreviewCreate,
    ) -> dict[str, object]:
        from server.app import get_app_state

        try:
            return build_reviewed_fee_schedule_preview(
                get_app_state(), **body.model_dump()
            )
        except ReviewedFeeScheduleRejected as exc:
            raise _reviewed_fee_schedule_http_exception(exc) from exc
        except (
            BrokerEvidenceReadRejected,
            ManualReviewReadRejected,
            EvidenceScopeReviewReadRejected,
        ) as exc:
            raise _account_truth_read_http_exception(exc) from exc

    @r.get("/fee-schedule/review")
    async def get_reviewed_fee_schedule_review() -> dict[str, object]:
        from server.app import get_app_state

        try:
            return build_reviewed_fee_schedule_review_status(get_app_state())
        except ReviewedFeeScheduleReadRejected as exc:
            raise _reviewed_fee_schedule_read_http_exception(exc) from exc
        except (
            BrokerEvidenceReadRejected,
            ManualReviewReadRejected,
            EvidenceScopeReviewReadRejected,
        ) as exc:
            raise _account_truth_read_http_exception(exc) from exc

    @r.post("/fee-schedule/reviews")
    async def record_reviewed_fee_schedule_review(
        body: ReviewedFeeScheduleReviewCreate,
    ) -> dict[str, object]:
        from server.app import get_app_state

        state = get_app_state()
        try:
            preview = build_reviewed_fee_schedule_preview(
                state,
                effective_start_date=body.effective_start_date,
                effective_end_date=body.effective_end_date,
                reviewed_asset_classes=body.reviewed_asset_classes,
            )
            review = _reviewed_fee_schedule_repository_for_state(state).record_review(
                preview=preview,
                expected_preview_fingerprint=body.expected_preview_fingerprint,
                reviewer=body.reviewer,
                confirmation=body.confirmation,
            )
        except ReviewedFeeScheduleRejected as exc:
            raise _reviewed_fee_schedule_http_exception(exc) from exc
        except ReviewedFeeScheduleReadRejected as exc:
            raise _reviewed_fee_schedule_read_http_exception(exc) from exc
        except (
            BrokerEvidenceReadRejected,
            ManualReviewReadRejected,
            EvidenceScopeReviewReadRejected,
        ) as exc:
            raise _account_truth_read_http_exception(exc) from exc
        return {
            "status": "accepted",
            "review": review.to_json_dict(),
            "approval_confirmation": REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        }

    @r.post("/fee-schedule/reviews/revoke")
    async def revoke_reviewed_fee_schedule_review(
        body: ReviewedFeeScheduleReviewRevoke,
    ) -> dict[str, object]:
        from server.app import get_app_state

        try:
            review = _reviewed_fee_schedule_repository_for_state(
                get_app_state()
            ).revoke_latest(**body.model_dump())
        except ReviewedFeeScheduleRejected as exc:
            raise _reviewed_fee_schedule_http_exception(exc) from exc
        except ReviewedFeeScheduleReadRejected as exc:
            raise _reviewed_fee_schedule_read_http_exception(exc) from exc
        return {
            "status": "revoked",
            "review": review.to_json_dict(),
            "revocation_confirmation": REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        }

    @r.post("/evidence-scope/reviews")
    async def record_evidence_scope_review(
        body: EvidenceScopeReviewCreate,
    ) -> dict[str, object]:
        from server.app import get_app_state

        try:
            return record_account_truth_evidence_scope_review(
                get_app_state(),
                **body.model_dump(),
            )
        except EvidenceScopeReviewRejected as exc:
            raise _evidence_scope_review_http_exception(exc) from exc
        except (
            BrokerEvidenceReadRejected,
            ManualReviewReadRejected,
            EvidenceScopeReviewReadRejected,
        ) as exc:
            raise _account_truth_read_http_exception(exc) from exc

    @r.post("/evidence-scope/reviews/revoke")
    async def revoke_evidence_scope_review(
        body: EvidenceScopeReviewRevoke,
    ) -> dict[str, object]:
        from server.app import get_app_state

        try:
            return revoke_account_truth_evidence_scope_review(
                get_app_state(),
                **body.model_dump(),
            )
        except EvidenceScopeReviewRejected as exc:
            raise _evidence_scope_review_http_exception(exc) from exc
        except (
            BrokerEvidenceReadRejected,
            ManualReviewReadRejected,
            EvidenceScopeReviewReadRejected,
        ) as exc:
            raise _account_truth_read_http_exception(exc) from exc

    @r.post("/citic-history-xls/canonical-resolutions")
    async def record_citic_canonical_resolution(
        body: CiticSourceCanonicalResolutionCreate,
    ) -> dict[str, object]:
        from server.app import get_app_state

        try:
            return record_citic_source_canonical_resolution(
                get_app_state(),
                **body.model_dump(),
            )
        except CiticSourceCanonicalResolutionRejected as exc:
            raise _citic_canonical_resolution_http_exception(exc) from exc
        except CiticSourceCanonicalResolutionReadRejected as exc:
            raise _citic_canonical_resolution_read_http_exception(exc) from exc

    @r.post("/citic-history-xls/canonical-resolutions/revoke")
    async def revoke_citic_canonical_resolution(
        body: CiticSourceCanonicalResolutionRevoke,
    ) -> dict[str, object]:
        from server.app import get_app_state

        try:
            return revoke_citic_source_canonical_resolution(
                get_app_state(),
                **body.model_dump(),
            )
        except CiticSourceCanonicalResolutionRejected as exc:
            raise _citic_canonical_resolution_http_exception(exc) from exc
        except CiticSourceCanonicalResolutionReadRejected as exc:
            raise _citic_canonical_resolution_read_http_exception(exc) from exc

    @r.get("/reconciliation-reports/{import_run_id}")
    async def get_reconciliation_report(import_run_id: str) -> dict[str, object]:
        from server.app import get_app_state

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
        from server.app import get_app_state

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


def _repository_for_state(state) -> BrokerEvidenceRepository:
    db_path = getattr(getattr(state, "db", None), "_path", None)
    if db_path is None:
        raise HTTPException(
            status_code=503, detail="Account Truth database unavailable"
        )
    return BrokerEvidenceRepository(Path(db_path))


def _reviewed_fee_schedule_repository_for_state(
    state,
) -> ReviewedFeeScheduleReviewRepository:
    db_path = getattr(getattr(state, "db", None), "_path", None)
    if db_path is None:
        raise HTTPException(
            status_code=503, detail="Account Truth database unavailable"
        )
    return ReviewedFeeScheduleReviewRepository(Path(db_path))


def _reviewed_fee_schedule_http_exception(
    exc: ReviewedFeeScheduleRejected,
) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": exc.code,
            "message": "Reviewed fee schedule remains in no-action state.",
        },
    )


def _reviewed_fee_schedule_read_http_exception(
    exc: ReviewedFeeScheduleReadRejected,
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": exc.code,
            "message": "Persisted reviewed fee schedule is unavailable.",
        },
    )


def _account_truth_read_http_exception(
    exc: (
        BrokerEvidenceReadRejected
        | ManualReviewReadRejected
        | EvidenceScopeReviewReadRejected
    ),
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": exc.code,
            "message": "Persisted Account Truth evidence is unavailable.",
        },
    )


def _evidence_scope_review_http_exception(
    exc: EvidenceScopeReviewRejected,
) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": exc.code,
            "message": "Account Truth evidence scope could not be recorded safely.",
        },
    )


def _citic_canonical_resolution_http_exception(
    exc: CiticSourceCanonicalResolutionRejected,
) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": exc.code,
            "message": "CITIC source canonical coverage could not be recorded safely.",
        },
    )


def _citic_canonical_resolution_read_http_exception(
    exc: CiticSourceCanonicalResolutionReadRejected,
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": exc.code,
            "message": "Persisted CITIC source canonical coverage is unavailable.",
        },
    )


def _citic_query_window_review_http_exception(
    exc: CiticSourceQueryWindowReviewRejected,
) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": exc.code,
            "message": "CITIC source query-window review could not be recorded safely.",
        },
    )


def _citic_query_window_review_read_http_exception(
    exc: CiticSourceQueryWindowReviewReadRejected,
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": exc.code,
            "message": "Persisted CITIC source query-window reviews are unavailable.",
        },
    )


def _citic_source_scope_review_http_exception(
    exc: CiticSourceScopeReviewRejected,
) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": exc.code,
            "message": "CITIC source-scope review could not be recorded safely.",
        },
    )


def _citic_source_scope_review_read_http_exception(
    exc: CiticSourceScopeReviewReadRejected,
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": exc.code,
            "message": "Persisted CITIC source-scope reviews are unavailable.",
        },
    )


def _manual_review_repository_for_state(state) -> ManualReviewRepository:
    db_path = getattr(getattr(state, "db", None), "_path", None)
    if db_path is None:
        raise HTTPException(
            status_code=503, detail="Account Truth database unavailable"
        )
    return ManualReviewRepository(Path(db_path))


def _citic_intake_repository_for_state(state) -> CiticSourceIntakeRepository:
    db_path = getattr(getattr(state, "db", None), "_path", None)
    if db_path is None:
        raise HTTPException(
            status_code=503, detail="Account Truth database unavailable"
        )
    return CiticSourceIntakeRepository(Path(db_path))


def _citic_source_reviews_for_state(
    state: object,
    *,
    limit: int,
) -> tuple[
    list[CiticSourceIntake],
    dict[str, CiticSourceQueryWindowReview],
    dict[str, CiticSourceScopeReview],
]:
    repository = _citic_intake_repository_for_state(state)
    db_path = Path(getattr(getattr(state, "db", None), "_path"))
    try:
        intakes = repository.list_intakes(limit=limit)
        reviews = latest_citic_query_window_reviews_by_intake(
            db_path,
            intakes=intakes,
        )
        scope_reviews = latest_citic_source_scope_reviews_by_intake(
            db_path,
            intakes=intakes,
        )
    except CiticSourceIntakeReadRejected as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": exc.code,
                "message": "CITIC source intake metadata is unavailable.",
            },
        ) from exc
    except CiticSourceQueryWindowReviewReadRejected as exc:
        raise _citic_query_window_review_read_http_exception(exc) from exc
    except CiticSourceScopeReviewReadRejected as exc:
        raise _citic_source_scope_review_read_http_exception(exc) from exc
    return intakes, reviews, scope_reviews


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


def _citic_history_xls_preview_response(
    preview: BrokerStatementPreview,
) -> dict[str, object]:
    return {
        "schema_version": preview.schema_version,
        "source_type": preview.source_type,
        "generated_at": preview.generated_at,
        "file_fingerprint": preview.file_fingerprint,
        "row_count": preview.row_count,
        "valid_row_count": preview.valid_row_count,
        "invalid_row_count": preview.invalid_row_count,
        "recognized_non_financial_activity_count": (
            recognized_non_financial_activity_count(preview)
        ),
        "duplicate_row_count": preview.duplicate_row_count,
        "validation_status": preview.validation_status,
        "limitations": list(preview.limitations),
        "errors": [_preview_error_response(error) for error in preview.errors],
        "total_event_count": len(preview.events),
        "source_preview_fingerprint": citic_source_preview_fingerprint(preview),
        "recordable_for_follow_up": (
            citic_preview_is_recordable_for_follow_up(preview)
        ),
        "required_evidence": required_evidence_for_citic_preview(preview),
        "broker_soak_candidate": build_citic_broker_soak_candidate(preview),
        "events_included": False,
        "evidence_persisted": False,
        "does_not_mutate_production_ledger": True,
        "does_not_contact_provider": True,
        "does_not_enable_broker_submission": True,
        "does_not_change_capital_authority": True,
    }


def _parse_citic_history_xls_transport(content_base64: str) -> BrokerStatementPreview:
    if not content_base64:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "citic_history_xls_empty_transport",
                "message": "CITIC XLS preview content is empty.",
            },
        )
    if len(content_base64) > CITIC_HISTORY_XLS_MAX_BASE64_CHARS:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "citic_history_xls_transport_too_large",
                "message": "CITIC XLS preview content exceeds the size limit.",
            },
        )
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "citic_history_xls_invalid_transport",
                "message": "CITIC XLS preview content is not valid base64.",
            },
        ) from exc
    return parse_citic_history_xls(content)


def _citic_source_intake_response(
    intake: CiticSourceIntake,
    *,
    query_window_review: CiticSourceQueryWindowReview | None = None,
    source_scope_review: CiticSourceScopeReview | None = None,
) -> dict[str, object]:
    return {
        "intake_id": intake.intake_id,
        "schema_version": intake.schema_version,
        "source_type": intake.source_type,
        "file_fingerprint": intake.file_fingerprint,
        "source_preview_fingerprint": intake.source_preview_fingerprint,
        "validation_status": intake.validation_status,
        "row_count": intake.row_count,
        "valid_row_count": intake.valid_row_count,
        "invalid_row_count": intake.invalid_row_count,
        "duplicate_row_count": intake.duplicate_row_count,
        "recognized_event_count": intake.recognized_event_count,
        "recognized_non_financial_activity_count": max(
            0,
            intake.row_count - intake.valid_row_count - intake.invalid_row_count,
        ),
        "error_codes": list(intake.error_codes),
        "required_evidence": list(intake.required_evidence),
        "limitations": list(intake.limitations),
        "recordable_for_follow_up": intake.recordable_for_follow_up,
        "review_id": intake.review_id,
        "review_status": intake.review_status,
        "reviewer": intake.reviewer,
        "created_at": intake.created_at,
        "reviewed_at": intake.reviewed_at,
        "reused": intake.reused,
        "query_window_review": (
            citic_source_query_window_review_response(
                query_window_review,
                source_review_status=intake.review_status,
            )
            if query_window_review is not None
            else None
        ),
        "source_scope_review": (
            citic_source_scope_review_response(
                source_scope_review,
                source_review_status=intake.review_status,
                query_window_review=query_window_review,
            )
            if source_scope_review is not None
            else None
        ),
        "source_intake_persisted": True,
        "events_persisted": False,
        "eligible_for_account_truth": False,
        "eligible_for_reconciliation": False,
        "does_not_mutate_production_ledger": True,
        "does_not_contact_provider": True,
        "does_not_enable_broker_submission": True,
        "does_not_change_capital_authority": True,
    }


def _record_citic_source_intake(
    *,
    state: object,
    preview: BrokerStatementPreview,
    expected_file_fingerprint: str,
    review_status: Literal["follow_up_required", "rejected"],
) -> dict[str, object]:
    repository = _citic_intake_repository_for_state(state)
    try:
        intake = repository.record_review(
            preview,
            expected_file_fingerprint=expected_file_fingerprint,
            review_status=review_status,
            reviewer="local",
        )
    except CiticSourceIntakeRejected as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": exc.code,
                "message": "CITIC source intake review was rejected.",
            },
        ) from exc
    return _citic_source_intake_response(intake)


def _citic_history_xls_directory_config_for_state(
    state: object,
) -> CiticHistoryXlsDirectoryConfig:
    config = getattr(state, "config", None)
    configured_directory = getattr(config, "citic_history_xls_directory", None)
    if isinstance(configured_directory, CiticHistoryXlsDirectoryConfig):
        return configured_directory
    return CiticHistoryXlsDirectoryConfig()


def _citic_history_xls_directory_status_response(
    config: CiticHistoryXlsDirectoryConfig,
) -> dict[str, object]:
    return {
        "schema_version": ("karkinos.account_truth.citic_history_xls_directory.v1"),
        "enabled": config.enabled,
        "state": "configured" if config.enabled else "disabled",
        "max_files": config.max_files,
        "max_file_bytes": config.max_file_bytes,
        "max_total_bytes": config.max_total_bytes,
        "configured_path_included": False,
        "source_names_included": False,
        "scan_requires_explicit_command": True,
        "scan_persisted": False,
        "events_persisted": False,
        "eligible_for_account_truth": False,
        "eligible_for_reconciliation": False,
        "does_not_mutate_production_ledger": True,
        "does_not_contact_provider": True,
        "does_not_enable_broker_submission": True,
        "does_not_change_capital_authority": True,
    }


def _citic_history_xls_directory_scan_response(
    scan: CiticHistoryXlsDirectoryScan,
    *,
    config: CiticHistoryXlsDirectoryConfig,
    intakes: list[CiticSourceIntake] | None = None,
    query_window_reviews: dict[str, CiticSourceQueryWindowReview] | None = None,
    source_scope_reviews: dict[str, CiticSourceScopeReview] | None = None,
    canonical_lineage_assessment: dict[str, object] | None = None,
) -> dict[str, object]:
    intake_by_file = {intake.file_fingerprint: intake for intake in (intakes or [])}
    review_by_intake = query_window_reviews or {}
    scope_review_by_intake = source_scope_reviews or {}
    month_hint_by_file = dict(scan.local_name_month_hints)
    active_query_window_reviews = []
    active_source_scope_reviews = []
    for preview in scan.previews:
        intake = intake_by_file.get(preview.file_fingerprint)
        if intake is not None and _citic_query_window_review_is_active(
            intake,
            review_by_intake,
            source_preview_fingerprint=citic_source_preview_fingerprint(preview),
        ):
            query_review = review_by_intake[intake.intake_id]
            active_query_window_reviews.append(query_review)
            scope_review = active_citic_source_scope_review(
                source=intake,
                query_window_review=query_review,
                source_scope_review=scope_review_by_intake.get(intake.intake_id),
            )
            if scope_review is not None:
                active_source_scope_reviews.append(scope_review)
    query_window_batch_assessment = project_citic_query_window_batch_assessment(
        source_count=scan.preview_count,
        active_reviews=active_query_window_reviews,
    )
    source_scope_batch_assessment = project_citic_source_scope_batch_assessment(
        source_count=scan.preview_count,
        active_query_window_reviews=active_query_window_reviews,
        active_scope_reviews=active_source_scope_reviews,
    )
    return {
        "schema_version": scan.schema_version,
        "enabled": scan.enabled,
        "state": scan.state,
        "candidate_file_count": scan.candidate_file_count,
        "preview_count": scan.preview_count,
        "duplicate_file_count": scan.duplicate_file_count,
        "unreadable_file_count": scan.unreadable_file_count,
        "recognized_event_count": scan.recognized_event_count,
        "valid_row_count": scan.valid_row_count,
        "invalid_row_count": scan.invalid_row_count,
        "scan_fingerprint": scan.scan_fingerprint,
        "error_codes": list(scan.error_codes),
        "batch_assessment": _citic_history_xls_batch_assessment_response(
            scan.batch_assessment
        ),
        "canonical_lineage_assessment": canonical_lineage_assessment,
        "query_window_review_summary": {
            "reviewed_source_count": query_window_batch_assessment[
                "reviewed_source_count"
            ],
            "unreviewed_source_count": query_window_batch_assessment[
                "unreviewed_source_count"
            ],
            "all_current_sources_reviewed": query_window_batch_assessment[
                "all_current_sources_reviewed"
            ],
            "complete_coverage_proven": False,
            "eligible_for_account_truth": False,
            "eligible_for_reconciliation": False,
        },
        "query_window_batch_assessment": query_window_batch_assessment,
        "source_scope_review_summary": {
            "reviewed_source_count": source_scope_batch_assessment[
                "reviewed_source_count"
            ],
            "unreviewed_source_count": source_scope_batch_assessment[
                "unreviewed_source_count"
            ],
            "all_current_sources_reviewed": source_scope_batch_assessment[
                "all_current_sources_reviewed"
            ],
            "same_account_binding_proven": source_scope_batch_assessment[
                "account_scope_bound"
            ],
            "declared_scope_consistent": source_scope_batch_assessment[
                "declared_scope_consistent"
            ],
            "complete_account_coverage_proven": False,
            "eligible_for_account_truth": False,
            "eligible_for_reconciliation": False,
        },
        "source_scope_batch_assessment": source_scope_batch_assessment,
        "items": [
            {
                **_citic_history_xls_preview_response(preview),
                "local_name_month_hint": month_hint_by_file.get(
                    preview.file_fingerprint
                ),
                "local_name_month_hint_is_evidence": False,
                "query_window_inferred": False,
                "source_intake": (
                    _citic_source_intake_response(
                        intake,
                        query_window_review=review_by_intake.get(intake.intake_id),
                        source_scope_review=scope_review_by_intake.get(
                            intake.intake_id
                        ),
                    )
                    if (intake := intake_by_file.get(preview.file_fingerprint))
                    else None
                ),
            }
            for preview in scan.previews
        ],
        "max_files": config.max_files,
        "max_file_bytes": config.max_file_bytes,
        "max_total_bytes": config.max_total_bytes,
        "configured_path_included": scan.configured_path_included,
        "source_names_included": scan.source_names_included,
        "source_name_month_hints_included": bool(scan.local_name_month_hints),
        "source_name_month_hints_are_evidence": False,
        "scan_persisted": scan.scan_persisted,
        "events_persisted": scan.events_persisted,
        "eligible_for_account_truth": scan.eligible_for_account_truth,
        "eligible_for_reconciliation": scan.eligible_for_reconciliation,
        "does_not_mutate_production_ledger": (scan.does_not_mutate_production_ledger),
        "does_not_contact_provider": scan.does_not_contact_provider,
        "does_not_enable_broker_submission": (scan.does_not_enable_broker_submission),
        "does_not_change_capital_authority": (scan.does_not_change_capital_authority),
    }


def _citic_query_window_review_is_active(
    intake: CiticSourceIntake | None,
    reviews: dict[str, CiticSourceQueryWindowReview],
    *,
    source_preview_fingerprint: str,
) -> bool:
    if intake is None or intake.review_status != "follow_up_required":
        return False
    review = reviews.get(intake.intake_id)
    return bool(
        review is not None
        and review.decision == "accepted"
        and review.file_fingerprint == intake.file_fingerprint
        and review.source_preview_fingerprint == intake.source_preview_fingerprint
        and review.source_preview_fingerprint == source_preview_fingerprint
    )


def _citic_history_xls_batch_assessment_response(
    assessment: CiticHistoryXlsBatchAssessment,
) -> dict[str, object]:
    return {
        "schema_version": assessment.schema_version,
        "status": assessment.status,
        "integrity_status": assessment.integrity_status,
        "source_count": assessment.source_count,
        "structurally_recordable_source_count": (
            assessment.structurally_recordable_source_count
        ),
        "source_with_financial_events_count": (
            assessment.source_with_financial_events_count
        ),
        "source_without_financial_events_count": (
            assessment.source_without_financial_events_count
        ),
        "observed_event_count": assessment.observed_event_count,
        "unique_event_count": assessment.unique_event_count,
        "within_file_duplicate_row_count": (assessment.within_file_duplicate_row_count),
        "cross_file_duplicate_event_count": (
            assessment.cross_file_duplicate_event_count
        ),
        "conflicting_event_identity_count": (
            assessment.conflicting_event_identity_count
        ),
        "invalid_row_count": assessment.invalid_row_count,
        "invalid_event_time_count": assessment.invalid_event_time_count,
        "recognized_non_financial_activity_count": (
            assessment.recognized_non_financial_activity_count
        ),
        "observed_event_months": list(assessment.observed_event_months),
        "observed_event_month_counts": [
            {"month": month, "event_count": event_count}
            for month, event_count in assessment.observed_event_month_counts
        ],
        "batch_fingerprint": assessment.batch_fingerprint,
        "blockers": list(assessment.blockers),
        "required_evidence": list(assessment.required_evidence),
        "limitations": list(assessment.limitations),
        "query_windows_reviewed": assessment.query_windows_reviewed,
        "complete_coverage_proven": assessment.complete_coverage_proven,
        "settlement_components_complete": (assessment.settlement_components_complete),
        "current_account_snapshots_present": (
            assessment.current_account_snapshots_present
        ),
        "account_scope_bound": assessment.account_scope_bound,
        "events_included": assessment.events_included,
        "private_fields_included": assessment.private_fields_included,
        "source_names_included": assessment.source_names_included,
        "paths_included": assessment.paths_included,
        "evidence_persisted": assessment.evidence_persisted,
        "eligible_for_account_truth": assessment.eligible_for_account_truth,
        "eligible_for_reconciliation": assessment.eligible_for_reconciliation,
        "does_not_mutate_production_ledger": (
            assessment.does_not_mutate_production_ledger
        ),
        "does_not_contact_provider": assessment.does_not_contact_provider,
        "does_not_enable_broker_submission": (
            assessment.does_not_enable_broker_submission
        ),
        "does_not_change_capital_authority": (
            assessment.does_not_change_capital_authority
        ),
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
