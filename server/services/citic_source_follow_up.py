"""Read-only Operations projection for reviewed incomplete CITIC sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from account_truth.citic_source_intake import (
    CiticSourceIntake,
    CiticSourceIntakeReadRejected,
    CiticSourceIntakeRepository,
)
from account_truth.citic_source_query_window_review import (
    CiticSourceQueryWindowReview,
    CiticSourceQueryWindowReviewReadRejected,
    CiticSourceQueryWindowReviewRepository,
)
from account_truth.citic_source_scope_review import (
    CiticSourceScopeReview,
    CiticSourceScopeReviewReadRejected,
    CiticSourceScopeReviewRepository,
)
from server.services.citic_source_query_window_review import (
    project_citic_query_window_batch_assessment,
)
from server.services.citic_source_scope_review import (
    active_citic_source_scope_review,
    project_citic_source_scope_batch_assessment,
)

CITIC_SOURCE_FOLLOW_UP_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_source_follow_up.v1"
)
_CITIC_SOURCE_FOLLOW_UP_SCAN_LIMIT = 200
_QUERY_WINDOW_INTEGRITY_BLOCKERS = frozenset(
    {
        "citic_query_window_batch_review_invalid",
        "citic_query_window_batch_review_count_exceeds_sources",
        "citic_query_window_batch_sources_unreviewed",
        "citic_query_window_batch_calendar_gap",
        "citic_query_window_batch_calendar_overlap",
    }
)
_SOURCE_SCOPE_INTEGRITY_BLOCKERS = frozenset(
    {
        "citic_source_scope_batch_source_count_invalid",
        "citic_source_scope_batch_query_window_review_invalid",
        "citic_source_scope_batch_review_invalid",
        "citic_source_scope_batch_sources_unreviewed",
        "citic_source_scope_batch_account_binding_conflict",
        "citic_source_scope_batch_declared_scope_conflict",
        "citic_source_scope_batch_review_count_exceeds_sources",
    }
)


def build_citic_source_follow_up(db_path: str | Path | None) -> dict[str, object]:
    """Project sanitized persisted reviews without initializing or repairing storage."""

    if db_path is None:
        return _follow_up_projection(
            status="not_configured",
            subsystem_status="skipped",
            pending_sources=[],
            query_window_reviews={},
            next_manual_action="none",
            limitations=[
                "CITIC source follow-up storage is not configured for this runtime."
            ],
        )

    try:
        intakes = CiticSourceIntakeRepository(db_path).list_intakes(
            limit=_CITIC_SOURCE_FOLLOW_UP_SCAN_LIMIT
        )
    except CiticSourceIntakeReadRejected as exc:
        return _follow_up_projection(
            status=exc.code,
            subsystem_status="blocked",
            pending_sources=[],
            query_window_reviews={},
            next_manual_action="repair_citic_source_intake_metadata_store",
            limitations=[
                "Persisted CITIC source intake metadata could not be read safely; no repair was attempted."
            ],
            count_complete=False,
        )

    pending = sorted(
        (item for item in intakes if item.review_status == "follow_up_required"),
        key=lambda item: (
            item.source_preview_fingerprint,
            item.review_id,
        ),
    )
    intake_scan_truncated = len(intakes) >= _CITIC_SOURCE_FOLLOW_UP_SCAN_LIMIT
    if intake_scan_truncated:
        return _follow_up_projection(
            status="citic_source_intake_scan_truncated",
            subsystem_status="blocked",
            pending_sources=pending,
            query_window_reviews={},
            next_manual_action="review_citic_source_intake_scan_limit",
            limitations=[
                "The bounded CITIC source scan reached its safety limit, so older source-review state may be omitted and the count is not complete."
            ],
            count_complete=False,
            scanned_source_count=len(intakes),
            intake_scan_truncated=True,
        )

    try:
        review_repository = CiticSourceQueryWindowReviewRepository(db_path)
        query_window_reviews = {
            intake.intake_id: review
            for intake in intakes
            if (review := review_repository.get_latest_review(intake.intake_id))
            is not None
        }
    except CiticSourceQueryWindowReviewReadRejected as exc:
        return _follow_up_projection(
            status=exc.code,
            subsystem_status="blocked",
            pending_sources=pending,
            query_window_reviews={},
            next_manual_action="repair_citic_source_query_window_review_store",
            limitations=[
                "Persisted CITIC source query-window review metadata could not be read safely; no repair was attempted."
            ],
            count_complete=False,
            scanned_source_count=len(intakes),
        )

    try:
        scope_review_repository = CiticSourceScopeReviewRepository(db_path)
        source_scope_reviews = {
            intake.intake_id: review
            for intake in intakes
            if (review := scope_review_repository.get_latest_review(intake.intake_id))
            is not None
        }
    except CiticSourceScopeReviewReadRejected as exc:
        return _follow_up_projection(
            status=exc.code,
            subsystem_status="blocked",
            pending_sources=pending,
            query_window_reviews=query_window_reviews,
            next_manual_action="repair_citic_source_scope_review_store",
            limitations=[
                "Persisted CITIC source-scope review metadata could not be read safely; no repair was attempted."
            ],
            count_complete=False,
            scanned_source_count=len(intakes),
        )

    if not pending:
        return _follow_up_projection(
            status="no_follow_up_required",
            subsystem_status="skipped",
            pending_sources=[],
            query_window_reviews=query_window_reviews,
            source_scope_reviews=source_scope_reviews,
            next_manual_action="none",
            limitations=[
                "No persisted CITIC source review currently requires follow-up."
            ],
            scanned_source_count=len(intakes),
        )
    missing_query_window_count = sum(
        not _active_query_window_review(source, query_window_reviews)
        for source in pending
    )
    query_window_batch_assessment = _query_window_batch_assessment(
        pending,
        query_window_reviews,
    )
    source_scope_batch_assessment = _source_scope_batch_assessment(
        pending,
        query_window_reviews,
        source_scope_reviews,
    )
    return _follow_up_projection(
        status="follow_up_required",
        subsystem_status="manual_action_required",
        pending_sources=pending,
        query_window_reviews=query_window_reviews,
        source_scope_reviews=source_scope_reviews,
        next_manual_action=(
            "review_citic_source_query_windows"
            if missing_query_window_count
            or query_window_batch_assessment["integrity_status"] != "clear"
            else (
                "review_citic_source_scopes"
                if source_scope_batch_assessment["integrity_status"] != "clear"
                else "provide_citic_account_truth_evidence_or_reject_source"
            )
        ),
        limitations=[
            "CITIC History Trades remain incomplete, non-authoritative source material.",
            "Completing or rejecting source follow-up does not itself create Account Truth evidence, reconcile the account, or grant trading authority.",
        ],
        scanned_source_count=len(intakes),
        query_window_batch_assessment=query_window_batch_assessment,
        source_scope_batch_assessment=source_scope_batch_assessment,
    )


def _projection(
    *,
    status: str,
    subsystem_status: str,
    pending_sources: list[CiticSourceIntake],
    query_window_reviews: dict[str, CiticSourceQueryWindowReview],
    source_scope_reviews: dict[str, CiticSourceScopeReview] | None = None,
    next_manual_action: str,
    limitations: list[str],
    count_complete: bool = True,
) -> dict[str, object]:
    effective_source_scope_reviews = source_scope_reviews or {}
    active_query_window_reviews = {
        source.intake_id: review
        for source in pending_sources
        if (
            review := _active_query_window_review(
                source,
                query_window_reviews,
            )
        )
        is not None
    }
    unreviewed_query_window_source_count = len(pending_sources) - len(
        active_query_window_reviews
    )
    active_source_scope_reviews = {
        source.intake_id: review
        for source in pending_sources
        if (
            review := active_citic_source_scope_review(
                source=source,
                query_window_review=active_query_window_reviews.get(source.intake_id),
                source_scope_review=effective_source_scope_reviews.get(
                    source.intake_id
                ),
            )
        )
        is not None
    }
    unreviewed_source_scope_count = len(pending_sources) - len(
        active_source_scope_reviews
    )
    required_evidence_set = {
        evidence for source in pending_sources for evidence in source.required_evidence
    }
    if unreviewed_query_window_source_count:
        required_evidence_set.add("reviewed_query_window_for_source")
    if unreviewed_source_scope_count:
        required_evidence_set.add("reviewed_source_scope_for_source")
    required_evidence = sorted(required_evidence_set)
    error_codes = sorted(
        {code for source in pending_sources for code in source.error_codes}
    )
    latest_reviewed_at = max(
        (
            *[source.reviewed_at for source in pending_sources],
            *[review.created_at for review in active_query_window_reviews.values()],
            *[review.created_at for review in active_source_scope_reviews.values()],
        ),
        default=None,
    )
    fingerprint_payload = {
        "schema_version": CITIC_SOURCE_FOLLOW_UP_SCHEMA_VERSION,
        "status": status,
        "count_complete": count_complete,
        "sources": [
            {
                "source_preview_fingerprint": source.source_preview_fingerprint,
                "review_id": source.review_id,
                "review_status": source.review_status,
                "reviewed_at": source.reviewed_at,
                "required_evidence": sorted(source.required_evidence),
                "error_codes": sorted(source.error_codes),
                "query_window_review": (
                    {
                        "review_id": review.review_id,
                        "review_fingerprint": review.review_fingerprint,
                        "query_start_date": review.query_start_date,
                        "query_end_date": review.query_end_date,
                    }
                    if (review := active_query_window_reviews.get(source.intake_id))
                    else None
                ),
                "source_scope_review": (
                    {
                        "review_id": review.review_id,
                        "review_fingerprint": review.review_fingerprint,
                        "query_window_review_fingerprint": (
                            review.query_window_review_fingerprint
                        ),
                        "account_reference_hash": review.account_reference_hash,
                        "account_type": review.account_type,
                        "market_scopes": list(review.market_scopes),
                        "asset_classes": list(review.asset_classes),
                        "business_types": list(review.business_types),
                        "no_other_filters_attested": (review.no_other_filters_attested),
                        "complete_returned_results_attested": (
                            review.complete_returned_results_attested
                        ),
                    }
                    if (review := active_source_scope_reviews.get(source.intake_id))
                    else None
                ),
            }
            for source in pending_sources
        ],
    }
    encoded = json.dumps(
        fingerprint_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema_version": CITIC_SOURCE_FOLLOW_UP_SCHEMA_VERSION,
        "status": status,
        "subsystem_status": subsystem_status,
        "pending_source_count": len(pending_sources),
        "count_complete": count_complete,
        "required_evidence": required_evidence,
        "reviewed_query_window_source_count": len(active_query_window_reviews),
        "unreviewed_query_window_source_count": (unreviewed_query_window_source_count),
        "query_window_reviews_complete": (unreviewed_query_window_source_count == 0),
        "reviewed_source_scope_source_count": len(active_source_scope_reviews),
        "unreviewed_source_scope_source_count": unreviewed_source_scope_count,
        "source_scope_reviews_complete": unreviewed_source_scope_count == 0,
        "error_codes": error_codes,
        "latest_reviewed_at": latest_reviewed_at,
        "evidence_fingerprint": f"sha256:{hashlib.sha256(encoded).hexdigest()}",
        "next_manual_action": next_manual_action,
        "limitations": limitations,
        "persisted_facts_only": True,
        "source_paths_included": False,
        "source_names_included": False,
        "transaction_details_included": False,
        "provider_contacted": False,
        "database_writes_performed": False,
        "eligible_for_account_truth": False,
        "eligible_for_reconciliation": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }


def _follow_up_projection(
    *,
    status: str,
    subsystem_status: str,
    pending_sources: list[CiticSourceIntake],
    query_window_reviews: dict[str, CiticSourceQueryWindowReview],
    source_scope_reviews: dict[str, CiticSourceScopeReview] | None = None,
    next_manual_action: str,
    limitations: list[str],
    count_complete: bool = True,
    scanned_source_count: int = 0,
    intake_scan_truncated: bool = False,
    query_window_batch_assessment: dict[str, object] | None = None,
    source_scope_batch_assessment: dict[str, object] | None = None,
) -> dict[str, object]:
    """Bind persisted source counts to one sanitized window-integrity projection."""

    projection = _projection(
        status=status,
        subsystem_status=subsystem_status,
        pending_sources=pending_sources,
        query_window_reviews=query_window_reviews,
        source_scope_reviews=source_scope_reviews,
        next_manual_action=next_manual_action,
        limitations=limitations,
        count_complete=count_complete,
    )
    assessment = query_window_batch_assessment or _query_window_batch_assessment(
        pending_sources,
        query_window_reviews,
    )
    scope_assessment = source_scope_batch_assessment or _source_scope_batch_assessment(
        pending_sources,
        query_window_reviews,
        source_scope_reviews or {},
    )
    assessment_blockers = [
        blocker
        for blocker in assessment.get("blockers", [])
        if blocker in _QUERY_WINDOW_INTEGRITY_BLOCKERS
    ]
    scope_assessment_blockers = [
        blocker
        for blocker in scope_assessment.get("blockers", [])
        if blocker in _SOURCE_SCOPE_INTEGRITY_BLOCKERS
    ]
    blockers = [*assessment_blockers, *scope_assessment_blockers]
    required_evidence = list(projection["required_evidence"])
    if intake_scan_truncated:
        blockers.insert(0, "citic_source_intake_scan_truncated")
        required_evidence.append("complete_citic_source_intake_scan")
    if any(
        blocker
        in {
            "citic_query_window_batch_review_invalid",
            "citic_query_window_batch_review_count_exceeds_sources",
            "citic_query_window_batch_calendar_gap",
            "citic_query_window_batch_calendar_overlap",
        }
        for blocker in assessment_blockers
    ):
        required_evidence.append("contiguous_non_overlapping_reviewed_query_windows")
    if scope_assessment_blockers:
        required_evidence.append("consistent_reviewed_source_scope_for_each_source")
    required_evidence = list(dict.fromkeys(required_evidence))
    projection.update(
        {
            "scanned_source_count": scanned_source_count,
            "intake_scan_truncated": intake_scan_truncated,
            "blockers": list(dict.fromkeys(blockers)),
            "required_evidence": required_evidence,
            "query_window_batch_integrity_status": assessment.get("integrity_status"),
            "query_window_batch_assessment_fingerprint": assessment.get(
                "assessment_fingerprint"
            ),
            "query_window_gap_calendar_day_count": assessment.get(
                "gap_calendar_day_count"
            ),
            "query_window_overlap_calendar_day_count": assessment.get(
                "overlap_calendar_day_count"
            ),
            "query_window_integrity_clear": (
                assessment.get("integrity_status") == "clear"
            ),
            "source_scope_batch_integrity_status": scope_assessment.get(
                "integrity_status"
            ),
            "source_scope_batch_assessment_fingerprint": scope_assessment.get(
                "assessment_fingerprint"
            ),
            "source_scope_integrity_clear": (
                scope_assessment.get("integrity_status") == "clear"
            ),
            "source_scope_account_binding_consistent": scope_assessment.get(
                "account_binding_consistent"
            ),
            "source_scope_declared_scope_consistent": scope_assessment.get(
                "declared_scope_consistent"
            ),
            "source_scope_complete_returned_results_attested": (
                scope_assessment.get("complete_returned_results_attested")
            ),
        }
    )
    fingerprint_payload = {
        "base_evidence_fingerprint": projection["evidence_fingerprint"],
        "scanned_source_count": scanned_source_count,
        "intake_scan_truncated": intake_scan_truncated,
        "blockers": projection["blockers"],
        "required_evidence": required_evidence,
        "next_manual_action": projection["next_manual_action"],
        "query_window_batch_integrity_status": projection[
            "query_window_batch_integrity_status"
        ],
        "query_window_batch_assessment_fingerprint": projection[
            "query_window_batch_assessment_fingerprint"
        ],
        "source_scope_batch_integrity_status": projection[
            "source_scope_batch_integrity_status"
        ],
        "source_scope_batch_assessment_fingerprint": projection[
            "source_scope_batch_assessment_fingerprint"
        ],
    }
    projection["evidence_fingerprint"] = _fingerprint(fingerprint_payload)
    return projection


def _query_window_batch_assessment(
    pending_sources: list[CiticSourceIntake],
    query_window_reviews: dict[str, CiticSourceQueryWindowReview],
) -> dict[str, object]:
    active_reviews = [
        review
        for source in pending_sources
        if (
            review := _active_query_window_review(
                source,
                query_window_reviews,
            )
        )
        is not None
    ]
    return project_citic_query_window_batch_assessment(
        source_count=len(pending_sources),
        active_reviews=active_reviews,
    )


def _source_scope_batch_assessment(
    pending_sources: list[CiticSourceIntake],
    query_window_reviews: dict[str, CiticSourceQueryWindowReview],
    source_scope_reviews: dict[str, CiticSourceScopeReview],
) -> dict[str, object]:
    active_query_reviews: list[CiticSourceQueryWindowReview] = []
    active_scope_reviews: list[CiticSourceScopeReview] = []
    for source in pending_sources:
        query_review = _active_query_window_review(source, query_window_reviews)
        if query_review is None:
            continue
        active_query_reviews.append(query_review)
        scope_review = active_citic_source_scope_review(
            source=source,
            query_window_review=query_review,
            source_scope_review=source_scope_reviews.get(source.intake_id),
        )
        if scope_review is not None:
            active_scope_reviews.append(scope_review)
    return project_citic_source_scope_batch_assessment(
        source_count=len(pending_sources),
        active_query_window_reviews=active_query_reviews,
        active_scope_reviews=active_scope_reviews,
    )


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _active_query_window_review(
    source: CiticSourceIntake,
    reviews: dict[str, CiticSourceQueryWindowReview],
) -> CiticSourceQueryWindowReview | None:
    review = reviews.get(source.intake_id)
    if (
        review is None
        or review.decision != "accepted"
        or review.file_fingerprint != source.file_fingerprint
        or review.source_preview_fingerprint != source.source_preview_fingerprint
    ):
        return None
    return review
