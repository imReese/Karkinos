"""Canonical account_truth intake projections."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import HTTPException

from account_truth.broker_evidence import (
    BrokerEvidenceRepository,
    BrokerImportRun,
)
from account_truth.broker_statement import (
    BrokerStatementPreview,
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
    CiticHistoryXlsDirectoryScan,
)
from account_truth.citic_source_intake import (
    CiticSourceIntake,
    CiticSourceIntakeReadRejected,
    CiticSourceIntakeRejected,
    citic_preview_is_recordable_for_follow_up,
    citic_source_preview_fingerprint,
    required_evidence_for_citic_preview,
)
from account_truth.citic_source_query_window_review import (
    CiticSourceQueryWindowReview,
    CiticSourceQueryWindowReviewReadRejected,
)
from account_truth.citic_source_scope_review import (
    CiticSourceScopeReview,
    CiticSourceScopeReviewReadRejected,
)
from account_truth.reconciliation import (
    ReconciliationReport,
)
from server.account_truth_gate import (
    build_reconciliation_report_for_import_run,
)
from server.config import CiticHistoryXlsDirectoryConfig
from server.services.account_truth_views.assessments import (
    citic_history_xls_batch_assessment_response,
    citic_query_window_review_is_active,
)
from server.services.account_truth_views.reports import (
    preview_error_response,
    preview_event_response,
)
from server.services.account_truth_views.repositories import (
    citic_intake_repository_for_state,
    citic_query_window_review_read_http_exception,
    citic_source_scope_review_read_http_exception,
)
from server.services.citic_source_query_window_review import (
    citic_source_query_window_review_response,
    latest_citic_query_window_reviews_by_intake,
    project_citic_query_window_batch_assessment,
)
from server.services.citic_source_scope_review import (
    active_citic_source_scope_review,
    citic_source_scope_review_response,
    latest_citic_source_scope_reviews_by_intake,
    project_citic_source_scope_batch_assessment,
)

CITIC_HISTORY_XLS_MAX_BASE64_CHARS = ((CITIC_HISTORY_XLS_MAX_BYTES + 2) // 3) * 4


def citic_source_reviews_for_state(
    state: object,
    *,
    limit: int,
) -> tuple[
    list[CiticSourceIntake],
    dict[str, CiticSourceQueryWindowReview],
    dict[str, CiticSourceScopeReview],
]:
    repository = citic_intake_repository_for_state(state)
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
        raise citic_query_window_review_read_http_exception(exc) from exc
    except CiticSourceScopeReviewReadRejected as exc:
        raise citic_source_scope_review_read_http_exception(exc) from exc
    return intakes, reviews, scope_reviews


def latest_import_runs_by_fingerprint(
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


def build_report_for_import_run(
    state,
    repository: BrokerEvidenceRepository,
    import_run: BrokerImportRun,
) -> ReconciliationReport:
    return build_reconciliation_report_for_import_run(
        state,
        repository=repository,
        import_run=import_run,
    )


def import_run_response(import_run: BrokerImportRun) -> dict[str, object]:
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


def preview_response(
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
        "errors": [preview_error_response(error) for error in preview.errors],
        "events_preview": [
            preview_event_response(event) for event in preview.events[:20]
        ],
        "preview_event_count": min(len(preview.events), 20),
        "total_event_count": len(preview.events),
        "does_not_mutate_production_ledger": True,
    }


def citic_history_xls_preview_response(
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
        "errors": [preview_error_response(error) for error in preview.errors],
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


def parse_citic_history_xls_transport(
    content_base64: str,
    *,
    parser: Callable[[bytes], BrokerStatementPreview] = parse_citic_history_xls,
) -> BrokerStatementPreview:
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
    return parser(content)


def citic_source_intake_response(
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


def record_citic_source_intake(
    *,
    state: object,
    preview: BrokerStatementPreview,
    expected_file_fingerprint: str,
    review_status: Literal["follow_up_required", "rejected"],
) -> dict[str, object]:
    repository = citic_intake_repository_for_state(state)
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
    return citic_source_intake_response(intake)


def citic_history_xls_directory_config_for_state(
    state: object,
) -> CiticHistoryXlsDirectoryConfig:
    config = getattr(state, "config", None)
    configured_directory = getattr(config, "citic_history_xls_directory", None)
    if isinstance(configured_directory, CiticHistoryXlsDirectoryConfig):
        return configured_directory
    return CiticHistoryXlsDirectoryConfig()


def citic_history_xls_directory_status_response(
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


def citic_history_xls_directory_scan_response(
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
        if intake is not None and citic_query_window_review_is_active(
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
        "batch_assessment": citic_history_xls_batch_assessment_response(
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
                **citic_history_xls_preview_response(preview),
                "local_name_month_hint": month_hint_by_file.get(
                    preview.file_fingerprint
                ),
                "local_name_month_hint_is_evidence": False,
                "query_window_inferred": False,
                "source_intake": (
                    citic_source_intake_response(
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


__all__ = (
    "build_report_for_import_run",
    "citic_history_xls_directory_config_for_state",
    "citic_history_xls_directory_scan_response",
    "citic_history_xls_directory_status_response",
    "citic_history_xls_preview_response",
    "citic_source_intake_response",
    "citic_source_reviews_for_state",
    "import_run_response",
    "latest_import_runs_by_fingerprint",
    "parse_citic_history_xls_transport",
    "preview_response",
    "record_citic_source_intake",
)
