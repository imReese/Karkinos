"""Canonical account_truth assessments projections."""

from __future__ import annotations

from account_truth.citic_history_xls_directory import (
    CiticHistoryXlsBatchAssessment,
)
from account_truth.citic_source_intake import (
    CiticSourceIntake,
)
from account_truth.citic_source_query_window_review import (
    CiticSourceQueryWindowReview,
)


def citic_query_window_review_is_active(
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


def citic_history_xls_batch_assessment_response(
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


__all__ = (
    "citic_history_xls_batch_assessment_response",
    "citic_query_window_review_is_active",
)
