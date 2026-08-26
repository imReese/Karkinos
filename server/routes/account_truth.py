"""Account Truth review routes — /api/account-truth/*"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path

from fastapi import APIRouter, HTTPException

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
from server.contracts.http.account_truth import (
    BrokerStatementPreviewCreate,
    CiticHistoryXlsDirectoryIntakeCreate,
    CiticHistoryXlsDirectoryQueryWindowReviewCreate,
    CiticHistoryXlsIntakeCreate,
    CiticHistoryXlsPreviewCreate,
    CiticHistoryXlsQueryWindowReviewCreate,
    CiticHistoryXlsQueryWindowReviewRevoke,
    CiticHistoryXlsSourceScopeReviewCreate,
    CiticHistoryXlsSourceScopeReviewRevoke,
    CiticSourceCanonicalResolutionCreate,
    CiticSourceCanonicalResolutionRevoke,
    EvidenceScopeReviewCreate,
    EvidenceScopeReviewRevoke,
    ReviewDecisionCreate,
    ReviewedFeeSchedulePreviewCreate,
    ReviewedFeeScheduleReviewCreate,
    ReviewedFeeScheduleReviewRevoke,
)
from server.http.account_truth_endpoints.dependencies import (
    IntakeEndpointDependencies,
    ReportDetailEndpointDependencies,
    ReviewEndpointDependencies,
    SummaryEndpointDependencies,
)
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


def create_router() -> APIRouter:
    router = APIRouter()
    router.routes.extend(
        _create_intake_router(
            IntakeEndpointDependencies(
                citic_history_xls_directory_config_for_state=(
                    lambda *args, **kwargs: (
                        _citic_history_xls_directory_config_for_state(*args, **kwargs)
                    )
                ),
                citic_history_xls_directory_scan_response=(
                    lambda *args, **kwargs: _citic_history_xls_directory_scan_response(
                        *args, **kwargs
                    )
                ),
                citic_history_xls_directory_status_response=(
                    lambda *args, **kwargs: (
                        _citic_history_xls_directory_status_response(*args, **kwargs)
                    )
                ),
                citic_history_xls_preview_response=lambda *args, **kwargs: (
                    _citic_history_xls_preview_response(*args, **kwargs)
                ),
                citic_query_window_review_http_exception=(
                    lambda *args, **kwargs: _citic_query_window_review_http_exception(
                        *args, **kwargs
                    )
                ),
                citic_query_window_review_read_http_exception=(
                    lambda *args, **kwargs: (
                        _citic_query_window_review_read_http_exception(*args, **kwargs)
                    )
                ),
                citic_source_intake_response=lambda *args, **kwargs: (
                    _citic_source_intake_response(*args, **kwargs)
                ),
                citic_source_reviews_for_state=lambda *args, **kwargs: (
                    _citic_source_reviews_for_state(*args, **kwargs)
                ),
                citic_source_scope_review_http_exception=(
                    lambda *args, **kwargs: _citic_source_scope_review_http_exception(
                        *args, **kwargs
                    )
                ),
                citic_source_scope_review_read_http_exception=(
                    lambda *args, **kwargs: (
                        _citic_source_scope_review_read_http_exception(*args, **kwargs)
                    )
                ),
                parse_citic_history_xls_transport=lambda *args, **kwargs: (
                    _parse_citic_history_xls_transport(*args, **kwargs)
                ),
                preview_response=lambda *args, **kwargs: _preview_response(
                    *args, **kwargs
                ),
                record_citic_source_intake=lambda *args, **kwargs: (
                    _record_citic_source_intake(*args, **kwargs)
                ),
                build_citic_history_canonical_lineage_assessment=(
                    lambda *args, **kwargs: (
                        build_citic_history_canonical_lineage_assessment(
                            *args, **kwargs
                        )
                    )
                ),
                find_citic_history_xls_directory_preview=(
                    lambda *args, **kwargs: find_citic_history_xls_directory_preview(
                        *args, **kwargs
                    )
                ),
                parse_broker_statement_csv=lambda *args, **kwargs: (
                    parse_broker_statement_csv(*args, **kwargs)
                ),
                parse_citic_history_xls=lambda *args, **kwargs: parse_citic_history_xls(
                    *args, **kwargs
                ),
                record_citic_source_query_window_review=(
                    lambda *args, **kwargs: record_citic_source_query_window_review(
                        *args, **kwargs
                    )
                ),
                record_citic_source_scope_review=lambda *args, **kwargs: (
                    record_citic_source_scope_review(*args, **kwargs)
                ),
                revoke_citic_source_query_window_review=(
                    lambda *args, **kwargs: revoke_citic_source_query_window_review(
                        *args, **kwargs
                    )
                ),
                revoke_citic_source_scope_review=lambda *args, **kwargs: (
                    revoke_citic_source_scope_review(*args, **kwargs)
                ),
                scan_citic_history_xls_directory=lambda *args, **kwargs: (
                    scan_citic_history_xls_directory(*args, **kwargs)
                ),
            )
        ).routes
    )
    router.routes.extend(
        _create_summary_router(
            SummaryEndpointDependencies(
                account_truth_read_http_exception=lambda *args, **kwargs: (
                    _account_truth_read_http_exception(*args, **kwargs)
                ),
                build_report_for_import_run=lambda *args, **kwargs: (
                    _build_report_for_import_run(*args, **kwargs)
                ),
                import_run_response=lambda *args, **kwargs: _import_run_response(
                    *args, **kwargs
                ),
                latest_import_runs_by_fingerprint=lambda *args, **kwargs: (
                    _latest_import_runs_by_fingerprint(*args, **kwargs)
                ),
                missing_score_response=lambda *args, **kwargs: _missing_score_response(
                    *args, **kwargs
                ),
                preview_response=lambda *args, **kwargs: _preview_response(
                    *args, **kwargs
                ),
                report_summary_response=lambda *args, **kwargs: (
                    _report_summary_response(*args, **kwargs)
                ),
                repository_for_state=lambda *args, **kwargs: _repository_for_state(
                    *args, **kwargs
                ),
                build_account_truth_evidence_readiness=lambda *args, **kwargs: (
                    build_account_truth_evidence_readiness(*args, **kwargs)
                ),
                build_latest_account_truth_score_payload=lambda *args, **kwargs: (
                    build_latest_account_truth_score_payload(*args, **kwargs)
                ),
                parse_broker_statement_csv=lambda *args, **kwargs: (
                    parse_broker_statement_csv(*args, **kwargs)
                ),
            )
        ).routes
    )
    router.routes.extend(
        _create_reviews_router(
            ReviewEndpointDependencies(
                account_truth_read_http_exception=lambda *args, **kwargs: (
                    _account_truth_read_http_exception(*args, **kwargs)
                ),
                citic_canonical_resolution_http_exception=(
                    lambda *args, **kwargs: _citic_canonical_resolution_http_exception(
                        *args, **kwargs
                    )
                ),
                citic_canonical_resolution_read_http_exception=(
                    lambda *args, **kwargs: (
                        _citic_canonical_resolution_read_http_exception(*args, **kwargs)
                    )
                ),
                evidence_scope_review_http_exception=lambda *args, **kwargs: (
                    _evidence_scope_review_http_exception(*args, **kwargs)
                ),
                reviewed_fee_schedule_http_exception=lambda *args, **kwargs: (
                    _reviewed_fee_schedule_http_exception(*args, **kwargs)
                ),
                reviewed_fee_schedule_read_http_exception=(
                    lambda *args, **kwargs: _reviewed_fee_schedule_read_http_exception(
                        *args, **kwargs
                    )
                ),
                reviewed_fee_schedule_repository_for_state=(
                    lambda *args, **kwargs: _reviewed_fee_schedule_repository_for_state(
                        *args, **kwargs
                    )
                ),
                build_reviewed_fee_schedule_preview=lambda *args, **kwargs: (
                    build_reviewed_fee_schedule_preview(*args, **kwargs)
                ),
                build_reviewed_fee_schedule_review_status=(
                    lambda *args, **kwargs: build_reviewed_fee_schedule_review_status(
                        *args, **kwargs
                    )
                ),
                record_account_truth_evidence_scope_review=(
                    lambda *args, **kwargs: record_account_truth_evidence_scope_review(
                        *args, **kwargs
                    )
                ),
                record_citic_source_canonical_resolution=(
                    lambda *args, **kwargs: record_citic_source_canonical_resolution(
                        *args, **kwargs
                    )
                ),
                revoke_account_truth_evidence_scope_review=(
                    lambda *args, **kwargs: revoke_account_truth_evidence_scope_review(
                        *args, **kwargs
                    )
                ),
                revoke_citic_source_canonical_resolution=(
                    lambda *args, **kwargs: revoke_citic_source_canonical_resolution(
                        *args, **kwargs
                    )
                ),
            )
        ).routes
    )
    router.routes.extend(
        _create_report_detail_router(
            ReportDetailEndpointDependencies(
                account_truth_read_http_exception=lambda *args, **kwargs: (
                    _account_truth_read_http_exception(*args, **kwargs)
                ),
                build_report_for_import_run=lambda *args, **kwargs: (
                    _build_report_for_import_run(*args, **kwargs)
                ),
                decision_response=lambda *args, **kwargs: _decision_response(
                    *args, **kwargs
                ),
                item_key=lambda *args, **kwargs: _item_key(*args, **kwargs),
                manual_review_repository_for_state=lambda *args, **kwargs: (
                    _manual_review_repository_for_state(*args, **kwargs)
                ),
                report_detail_response=lambda *args, **kwargs: _report_detail_response(
                    *args, **kwargs
                ),
                repository_for_state=lambda *args, **kwargs: _repository_for_state(
                    *args, **kwargs
                ),
                reconciliation_item_fingerprint=lambda *args, **kwargs: (
                    reconciliation_item_fingerprint(*args, **kwargs)
                ),
            )
        ).routes
    )
    return router
