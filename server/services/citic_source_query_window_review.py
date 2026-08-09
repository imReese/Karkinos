"""Application commands for reviewed CITIC export query windows."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Sequence

from account_truth.broker_statement import BrokerStatementPreview
from account_truth.citic_source_intake import CiticSourceIntake
from account_truth.citic_source_query_window_review import (
    CiticSourceQueryWindowReview,
    CiticSourceQueryWindowReviewRejected,
    CiticSourceQueryWindowReviewRepository,
)

CITIC_SOURCE_QUERY_WINDOW_REVIEW_COMMAND_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_source_query_window_review_command.v1"
)
CITIC_QUERY_WINDOW_BATCH_ASSESSMENT_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_query_window_batch_assessment.v1"
)


def project_citic_query_window_batch_assessment(
    *,
    source_count: int,
    active_reviews: Sequence[CiticSourceQueryWindowReview],
) -> dict[str, object]:
    """Project declared-window integrity without claiming complete coverage."""

    source_count_valid = (
        isinstance(source_count, int)
        and not isinstance(source_count, bool)
        and source_count >= 0
    )
    effective_source_count = source_count if source_count_valid else 0
    invalid_review_count = 0
    seen_intake_ids: set[str] = set()
    day_counts: Counter[date] = Counter()
    identity_rows: list[dict[str, str]] = []

    for review in active_reviews:
        intake_id = str(getattr(review, "intake_id", ""))
        review_fingerprint = str(getattr(review, "review_fingerprint", ""))
        start_text = str(getattr(review, "query_start_date", ""))
        end_text = str(getattr(review, "query_end_date", ""))
        try:
            start = date.fromisoformat(start_text)
            end = date.fromisoformat(end_text)
        except ValueError:
            invalid_review_count += 1
            continue
        day_count = (end - start).days + 1
        if (
            getattr(review, "decision", None) != "accepted"
            or getattr(review, "query_window_attested", None) is not True
            or not intake_id.startswith("citic_intake_")
            or intake_id in seen_intake_ids
            or start.isoformat() != start_text
            or end.isoformat() != end_text
            or day_count < 1
            or day_count > 31
            or not _sha256_fingerprint_is_valid(review_fingerprint)
        ):
            invalid_review_count += 1
            continue
        seen_intake_ids.add(intake_id)
        identity_rows.append(
            {
                "intake_id": intake_id,
                "review_fingerprint": review_fingerprint,
                "query_start_date": start_text,
                "query_end_date": end_text,
            }
        )
        for offset in range(day_count):
            day_counts[start + timedelta(days=offset)] += 1

    reviewed_source_count = len(identity_rows)
    unreviewed_source_count = max(
        0,
        effective_source_count - reviewed_source_count,
    )
    all_current_sources_reviewed = bool(
        source_count_valid
        and effective_source_count > 0
        and invalid_review_count == 0
        and reviewed_source_count == effective_source_count
        and len(active_reviews) == effective_source_count
    )
    declared_window_start = min(day_counts, default=None)
    declared_window_end = max(day_counts, default=None)
    covered_calendar_day_count = len(day_counts)
    declared_span_day_count = (
        (declared_window_end - declared_window_start).days + 1
        if declared_window_start is not None and declared_window_end is not None
        else 0
    )
    gap_calendar_day_count = max(
        0,
        declared_span_day_count - covered_calendar_day_count,
    )
    overlap_calendar_day_count = sum(
        coverage_count > 1 for coverage_count in day_counts.values()
    )
    declared_windows_contiguous = bool(day_counts) and gap_calendar_day_count == 0
    declared_windows_non_overlapping = (
        bool(day_counts) and overlap_calendar_day_count == 0
    )

    blockers = ["citic_query_window_batch_complete_account_coverage_unproven"]
    if not source_count_valid:
        blockers.append("citic_query_window_batch_source_count_invalid")
    if effective_source_count == 0:
        blockers.append("citic_query_window_batch_sources_missing")
    if invalid_review_count:
        blockers.append("citic_query_window_batch_review_invalid")
    if reviewed_source_count > effective_source_count:
        blockers.append("citic_query_window_batch_review_count_exceeds_sources")
    if unreviewed_source_count:
        blockers.append("citic_query_window_batch_sources_unreviewed")
    if gap_calendar_day_count:
        blockers.append("citic_query_window_batch_calendar_gap")
    if overlap_calendar_day_count:
        blockers.append("citic_query_window_batch_calendar_overlap")

    if (
        not source_count_valid
        or invalid_review_count
        or reviewed_source_count > effective_source_count
        or gap_calendar_day_count
        or overlap_calendar_day_count
    ):
        integrity_status = "blocked"
    elif effective_source_count == 0 or not day_counts:
        integrity_status = "not_available"
    elif not all_current_sources_reviewed:
        integrity_status = "partial"
    else:
        integrity_status = "clear"

    core: dict[str, object] = {
        "schema_version": CITIC_QUERY_WINDOW_BATCH_ASSESSMENT_SCHEMA_VERSION,
        "status": "blocked",
        "integrity_status": integrity_status,
        "source_count": effective_source_count,
        "reviewed_source_count": reviewed_source_count,
        "unreviewed_source_count": unreviewed_source_count,
        "invalid_review_count": invalid_review_count,
        "all_current_sources_reviewed": all_current_sources_reviewed,
        "declared_window_start_date": (
            declared_window_start.isoformat()
            if declared_window_start is not None
            else None
        ),
        "declared_window_end_date": (
            declared_window_end.isoformat() if declared_window_end is not None else None
        ),
        "covered_calendar_day_count": covered_calendar_day_count,
        "gap_calendar_day_count": gap_calendar_day_count,
        "overlap_calendar_day_count": overlap_calendar_day_count,
        "declared_windows_contiguous": declared_windows_contiguous,
        "declared_windows_non_overlapping": declared_windows_non_overlapping,
        "blockers": list(dict.fromkeys(blockers)),
        "required_evidence": [
            "explicit_query_window_review_for_each_current_source",
            "contiguous_non_overlapping_declared_query_windows",
            "separate_complete_account_scope_review",
            "itemized_settlement_components_and_current_account_snapshots",
        ],
        "complete_account_coverage_proven": False,
        "account_scope_bound": False,
        "settlement_components_complete": False,
        "current_account_snapshots_present": False,
        "reviewed_query_windows_included": bool(day_counts),
        "events_included": False,
        "transaction_details_included": False,
        "private_fields_included": False,
        "source_names_included": False,
        "paths_included": False,
        "assessment_persisted": False,
        "database_writes_performed": False,
        "provider_contacted": False,
        "eligible_for_account_truth": False,
        "eligible_for_reconciliation": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "limitations": [
            "This assessment checks only the continuity and overlap of explicitly reviewed export query windows.",
            "Continuous declared windows do not prove that the selected sources cover the full account, all asset classes, settlement components, or current account state.",
        ],
    }
    fingerprint_payload = {
        **{key: value for key, value in core.items() if key != "limitations"},
        "review_identities": sorted(
            identity_rows,
            key=lambda row: (
                row["query_start_date"],
                row["query_end_date"],
                row["intake_id"],
                row["review_fingerprint"],
            ),
        ),
    }
    core["assessment_fingerprint"] = _fingerprint(fingerprint_payload)
    return core


def record_citic_source_query_window_review(
    state: Any,
    *,
    preview: BrokerStatementPreview,
    expected_file_fingerprint: str,
    expected_source_preview_fingerprint: str,
    query_start_date: str,
    query_end_date: str,
    query_window_attested: bool,
    reviewer: str = "local_owner",
) -> dict[str, object]:
    repository = CiticSourceQueryWindowReviewRepository(_required_db_path(state))
    review = repository.record_review(
        preview,
        expected_file_fingerprint=expected_file_fingerprint,
        expected_source_preview_fingerprint=expected_source_preview_fingerprint,
        query_start_date=query_start_date,
        query_end_date=query_end_date,
        query_window_attested=query_window_attested,
        reviewer=reviewer,
    )
    return _command_response(review=review)


def revoke_citic_source_query_window_review(
    state: Any,
    *,
    intake_id: str,
    expected_active_review_id: str,
    expected_active_review_fingerprint: str,
    reviewer: str = "local_owner",
) -> dict[str, object]:
    repository = CiticSourceQueryWindowReviewRepository(_required_db_path(state))
    review = repository.revoke_latest(
        intake_id=intake_id,
        expected_active_review_id=expected_active_review_id,
        expected_active_review_fingerprint=expected_active_review_fingerprint,
        reviewer=reviewer,
    )
    return _command_response(review=review)


def latest_citic_query_window_reviews_by_intake(
    db_path: str | Path,
    *,
    intakes: Sequence[CiticSourceIntake],
) -> dict[str, CiticSourceQueryWindowReview]:
    repository = CiticSourceQueryWindowReviewRepository(db_path)
    return {
        intake.intake_id: review
        for intake in intakes
        if (review := repository.get_latest_review(intake.intake_id)) is not None
    }


def citic_source_query_window_review_response(
    review: CiticSourceQueryWindowReview,
    *,
    source_review_status: str = "follow_up_required",
) -> dict[str, object]:
    effective_status = (
        "active"
        if review.decision == "accepted"
        and source_review_status == "follow_up_required"
        else "revoked" if review.decision == "revoked" else "source_closed"
    )
    return {
        "review_id": review.review_id,
        "schema_version": review.schema_version,
        "intake_id": review.intake_id,
        "file_fingerprint": review.file_fingerprint,
        "source_preview_fingerprint": review.source_preview_fingerprint,
        "query_start_date": review.query_start_date,
        "query_end_date": review.query_end_date,
        "query_window_attested": review.query_window_attested,
        "decision": review.decision,
        "effective_status": effective_status,
        "supersedes_review_id": review.supersedes_review_id,
        "reviewer": review.reviewer,
        "review_fingerprint": review.review_fingerprint,
        "created_at": review.created_at,
        "reused": review.reused,
        "review_persisted": True,
        "events_included": False,
        "transaction_details_included": False,
        "source_name_included": False,
        "source_path_included": False,
        "eligible_for_account_truth": False,
        "eligible_for_reconciliation": False,
        "does_not_mutate_broker_evidence": True,
        "does_not_mutate_production_ledger": True,
        "does_not_contact_provider": True,
        "does_not_enable_broker_submission": True,
        "does_not_change_capital_authority": True,
    }


def _command_response(
    *,
    review: CiticSourceQueryWindowReview,
) -> dict[str, object]:
    return {
        "schema_version": (CITIC_SOURCE_QUERY_WINDOW_REVIEW_COMMAND_SCHEMA_VERSION),
        "status": "recorded" if review.decision == "accepted" else "revoked",
        "review": citic_source_query_window_review_response(review),
        "query_window_review_write_performed": not review.reused,
        "writes_only_query_window_review_store": True,
        "events_persisted": False,
        "does_not_mutate_source_intake": True,
        "does_not_mutate_broker_evidence": True,
        "does_not_mutate_production_ledger": True,
        "does_not_reconcile_account": True,
        "does_not_contact_provider": True,
        "does_not_enable_broker_submission": True,
        "does_not_change_capital_authority": True,
    }


def _required_db_path(state: Any) -> Path:
    db_path = getattr(getattr(state, "db", None), "_path", None)
    if db_path is None:
        raise CiticSourceQueryWindowReviewRejected(
            "citic_source_query_window_store_not_configured"
        )
    return Path(db_path)


def _sha256_fingerprint_is_valid(value: str) -> bool:
    prefix, separator, digest = value.partition(":")
    return bool(
        prefix == "sha256"
        and separator
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
