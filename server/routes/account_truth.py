"""Account Truth review routes — /api/account-truth/*"""

from __future__ import annotations

import base64
import binascii
import sys
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
from server.account_truth_gate import (
    missing_account_truth_score_payload as _missing_score_response,
)
from server.config import CiticHistoryXlsDirectoryConfig
from server.http.account_truth_endpoints.intake import (
    create_router as _create_intake_router,
)
from server.http.account_truth_endpoints.report_detail import (
    create_router as _create_report_detail_router,
)
from server.http.account_truth_endpoints.reviews import (
    create_router as _create_reviews_router,
)
from server.http.account_truth_endpoints.summary import (
    create_router as _create_summary_router,
)
from server.services.account_truth_evidence_readiness import (
    build_account_truth_evidence_readiness,
)
from server.services.account_truth_evidence_scope_review import (
    record_account_truth_evidence_scope_review,
    revoke_account_truth_evidence_scope_review,
)
from server.services.account_truth_views.assessments import (
    citic_history_xls_batch_assessment_response as _citic_history_xls_batch_assessment_response,
)
from server.services.account_truth_views.assessments import (
    citic_query_window_review_is_active as _citic_query_window_review_is_active,
)
from server.services.account_truth_views.intake import (
    build_report_for_import_run as _build_report_for_import_run,
)
from server.services.account_truth_views.intake import (
    citic_history_xls_directory_config_for_state as _citic_history_xls_directory_config_for_state,
)
from server.services.account_truth_views.intake import (
    citic_history_xls_directory_scan_response as _citic_history_xls_directory_scan_response,
)
from server.services.account_truth_views.intake import (
    citic_history_xls_directory_status_response as _citic_history_xls_directory_status_response,
)
from server.services.account_truth_views.intake import (
    citic_history_xls_preview_response as _citic_history_xls_preview_response,
)
from server.services.account_truth_views.intake import (
    citic_source_intake_response as _citic_source_intake_response,
)
from server.services.account_truth_views.intake import (
    citic_source_reviews_for_state as _citic_source_reviews_for_state,
)
from server.services.account_truth_views.intake import (
    import_run_response as _import_run_response,
)
from server.services.account_truth_views.intake import (
    latest_import_runs_by_fingerprint as _latest_import_runs_by_fingerprint,
)
from server.services.account_truth_views.intake import (
    parse_citic_history_xls_transport as _parse_citic_history_xls_transport,
)
from server.services.account_truth_views.intake import (
    preview_response as _preview_response,
)
from server.services.account_truth_views.intake import (
    record_citic_source_intake as _record_citic_source_intake,
)
from server.services.account_truth_views.reports import (
    decision_response as _decision_response,
)
from server.services.account_truth_views.reports import (
    display_name_for_item as _display_name_for_item,
)
from server.services.account_truth_views.reports import (
    evidence_references as _evidence_references,
)
from server.services.account_truth_views.reports import item_key as _item_key
from server.services.account_truth_views.reports import item_response as _item_response
from server.services.account_truth_views.reports import (
    preview_error_response as _preview_error_response,
)
from server.services.account_truth_views.reports import (
    preview_event_response as _preview_event_response,
)
from server.services.account_truth_views.reports import (
    report_detail_response as _report_detail_response,
)
from server.services.account_truth_views.reports import (
    report_summary_response as _report_summary_response,
)
from server.services.account_truth_views.repositories import (
    account_truth_read_http_exception as _account_truth_read_http_exception,
)
from server.services.account_truth_views.repositories import (
    citic_canonical_resolution_http_exception as _citic_canonical_resolution_http_exception,
)
from server.services.account_truth_views.repositories import (
    citic_canonical_resolution_read_http_exception as _citic_canonical_resolution_read_http_exception,
)
from server.services.account_truth_views.repositories import (
    citic_intake_repository_for_state as _citic_intake_repository_for_state,
)
from server.services.account_truth_views.repositories import (
    citic_query_window_review_http_exception as _citic_query_window_review_http_exception,
)
from server.services.account_truth_views.repositories import (
    citic_query_window_review_read_http_exception as _citic_query_window_review_read_http_exception,
)
from server.services.account_truth_views.repositories import (
    citic_source_scope_review_http_exception as _citic_source_scope_review_http_exception,
)
from server.services.account_truth_views.repositories import (
    citic_source_scope_review_read_http_exception as _citic_source_scope_review_read_http_exception,
)
from server.services.account_truth_views.repositories import (
    evidence_scope_review_http_exception as _evidence_scope_review_http_exception,
)
from server.services.account_truth_views.repositories import (
    manual_review_repository_for_state as _manual_review_repository_for_state,
)
from server.services.account_truth_views.repositories import (
    repository_for_state as _repository_for_state,
)
from server.services.account_truth_views.repositories import (
    reviewed_fee_schedule_http_exception as _reviewed_fee_schedule_http_exception,
)
from server.services.account_truth_views.repositories import (
    reviewed_fee_schedule_read_http_exception as _reviewed_fee_schedule_read_http_exception,
)
from server.services.account_truth_views.repositories import (
    reviewed_fee_schedule_repository_for_state as _reviewed_fee_schedule_repository_for_state,
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
    facade = sys.modules[__name__]
    router = APIRouter()
    router.routes.extend(_create_intake_router(facade).routes)
    router.routes.extend(_create_summary_router(facade).routes)
    router.routes.extend(_create_reviews_router(facade).routes)
    router.routes.extend(_create_report_detail_router(facade).routes)
    return router
