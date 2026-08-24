"""Stable contracts for reviewed account-bound fee schedules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

REVIEWED_FEE_SCHEDULE_REVIEW_SCHEMA_VERSION = (
    "karkinos.account_truth.reviewed_fee_schedule_review.v1"
)
REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION = (
    "approve_reconciled_account_fee_schedule_for_research_only_without_execution_"
    "or_capital_authority"
)
REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION = (
    "revoke_reconciled_account_fee_schedule_without_execution_or_capital_authority"
)


class ReviewedFeeScheduleRejected(ValueError):
    """A stable fail-closed rejection for review or resolution."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ReviewedFeeScheduleReadRejected(RuntimeError):
    """Persisted review state could not be read without guessing."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ReviewedFeeScheduleReview:
    review_id: str
    schema_version: str
    decision: str
    schedule: dict[str, Any]
    schedule_fingerprint: str
    preview: dict[str, Any]
    preview_fingerprint: str
    account_truth_import_run_id: str
    account_truth_source_fingerprint: str
    account_truth_scope_fingerprint: str
    account_reference_hash: str
    effective_start_date: str
    effective_end_date: str
    reviewer: str
    review_fingerprint: str
    created_at: str
    reused: bool = False

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schedule"] = dict(self.schedule)
        payload["preview"] = dict(self.preview)
        return payload


__all__ = [
    "REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION",
    "REVIEWED_FEE_SCHEDULE_REVIEW_SCHEMA_VERSION",
    "REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION",
    "ReviewedFeeScheduleReadRejected",
    "ReviewedFeeScheduleRejected",
    "ReviewedFeeScheduleReview",
]
