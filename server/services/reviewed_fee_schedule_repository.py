"""Append-only reviewed fee schedule repository facade."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any, Mapping

from server.contracts.reviewed_fee_schedule import (
    REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    REVIEWED_FEE_SCHEDULE_REVIEW_SCHEMA_VERSION,
    REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
    ReviewedFeeScheduleRejected,
    ReviewedFeeScheduleReview,
)
from server.persistence.reviewed_fee_schedule_reviews import (
    ReviewedFeeScheduleReviewStore,
)
from server.services.reviewed_fee_schedule_policy import (
    SAFE_ID_PATTERN,
    fingerprint_payload,
    review_from_row,
    validated_preview,
)


class ReviewedFeeScheduleReviewRepository:
    """Append-only runtime reviews; all reads are SQLite query-only."""

    def __init__(self, db_path: str | Path) -> None:
        self._store = ReviewedFeeScheduleReviewStore(db_path)

    def record_review(
        self,
        *,
        preview: Mapping[str, Any],
        expected_preview_fingerprint: str,
        reviewer: str,
        confirmation: str,
    ) -> ReviewedFeeScheduleReview:
        if confirmation != REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION:
            raise ReviewedFeeScheduleRejected(
                "reviewed_fee_schedule_approval_confirmation_invalid"
            )
        normalized_reviewer = str(reviewer or "").strip()
        if not SAFE_ID_PATTERN.fullmatch(normalized_reviewer):
            raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_reviewer_invalid")
        normalized = validated_preview(preview)
        if normalized["status"] != "ready":
            raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_preview_blocked")
        if expected_preview_fingerprint != normalized["preview_fingerprint"]:
            raise ReviewedFeeScheduleRejected(
                "reviewed_fee_schedule_preview_fingerprint_mismatch"
            )
        return self._append(
            decision="accepted",
            preview=normalized,
            reviewer=normalized_reviewer,
        )

    def revoke_latest(
        self,
        *,
        expected_review_id: str,
        expected_review_fingerprint: str,
        reviewer: str,
        confirmation: str,
    ) -> ReviewedFeeScheduleReview:
        if confirmation != REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION:
            raise ReviewedFeeScheduleRejected(
                "reviewed_fee_schedule_revocation_confirmation_invalid"
            )
        latest = self.get_latest_review()
        if latest is None:
            raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_review_missing")
        if (
            latest.review_id != expected_review_id
            or latest.review_fingerprint != expected_review_fingerprint
        ):
            raise ReviewedFeeScheduleRejected(
                "reviewed_fee_schedule_review_fingerprint_mismatch"
            )
        if latest.decision == "revoked":
            return _with_reused(latest)
        normalized_reviewer = str(reviewer or "").strip()
        if not SAFE_ID_PATTERN.fullmatch(normalized_reviewer):
            raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_reviewer_invalid")
        return self._append(
            decision="revoked",
            preview=latest.preview,
            reviewer=normalized_reviewer,
        )

    def get_latest_review(self) -> ReviewedFeeScheduleReview | None:
        row = self._store.get_latest_review()
        return review_from_row(row) if row is not None else None

    def get_review(self, review_id: str) -> ReviewedFeeScheduleReview | None:
        row = self._store.get_review(review_id)
        return review_from_row(row) if row is not None else None

    def _append(
        self,
        *,
        decision: str,
        preview: Mapping[str, Any],
        reviewer: str,
    ) -> ReviewedFeeScheduleReview:
        core = {
            "schema_version": REVIEWED_FEE_SCHEDULE_REVIEW_SCHEMA_VERSION,
            "decision": decision,
            "schedule_fingerprint": preview["schedule_fingerprint"],
            "preview_fingerprint": preview["preview_fingerprint"],
            "account_truth_import_run_id": preview["account_truth_import_run_id"],
            "account_truth_source_fingerprint": preview[
                "account_truth_source_fingerprint"
            ],
            "account_truth_scope_fingerprint": preview[
                "account_truth_scope_fingerprint"
            ],
            "account_reference_hash": preview["account_reference_hash"],
            "effective_start_date": preview["effective_start_date"],
            "effective_end_date": preview["effective_end_date"],
            "reviewer": reviewer,
        }
        row, reused = self._store.append(
            decision=decision,
            preview=preview,
            reviewer=reviewer,
            review_fingerprint=fingerprint_payload(core),
        )
        review = review_from_row(row)
        return _with_reused(review) if reused else review


def _with_reused(review: ReviewedFeeScheduleReview) -> ReviewedFeeScheduleReview:
    return ReviewedFeeScheduleReview(
        **{
            field.name: getattr(review, field.name)
            for field in fields(ReviewedFeeScheduleReview)
            if field.name != "reused"
        },
        reused=True,
    )


__all__ = ["ReviewedFeeScheduleReviewRepository"]
