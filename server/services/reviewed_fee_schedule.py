"""Stable public facade for reviewed, account-bound fee schedules.

The implementation is partitioned by policy, persistence, reconciliation, and
application workflow ownership. This module intentionally keeps the original
import surface and dependency-injection seam used by deterministic tests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from server.account_truth_gate import build_latest_account_truth_promotion_evidence
from server.contracts.reviewed_fee_schedule import (
    REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    REVIEWED_FEE_SCHEDULE_REVIEW_SCHEMA_VERSION,
    REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
    ReviewedFeeScheduleReadRejected,
    ReviewedFeeScheduleRejected,
    ReviewedFeeScheduleReview,
)
from server.services.account_truth_evidence_readiness import (
    build_account_truth_evidence_readiness,
)
from server.services.reviewed_fee_schedule_commission import (
    ReviewedFeeScheduleResolution,
    is_reviewed_cost_model_reference,
    reviewed_cost_model_reference,
)
from server.services.reviewed_fee_schedule_policy import (
    REVIEWED_COST_MODEL_PREFIX,
    REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION,
    REVIEWED_FEE_SCHEDULE_RESOLUTION_SCHEMA_VERSION,
)
from server.services.reviewed_fee_schedule_reconciliation import (
    active_review_matches_fee_evidence,
)
from server.services.reviewed_fee_schedule_repository import (
    ReviewedFeeScheduleReviewRepository,
)
from server.services.reviewed_fee_schedule_workflows import (
    build_reviewed_fee_schedule_preview_workflow,
    build_reviewed_fee_schedule_review_status_workflow,
    resolve_reviewed_fee_schedule_workflow,
)


def build_reviewed_fee_schedule_preview(
    state: Any,
    *,
    effective_start_date: str,
    effective_end_date: str,
    reviewed_asset_classes: Sequence[str] | None = None,
    schedule_override: Mapping[str, Any] | None = None,
    account_truth_as_of: datetime | None = None,
) -> dict[str, Any]:
    """Build a deterministic preview using the facade's injectable dependencies."""

    return build_reviewed_fee_schedule_preview_workflow(
        state,
        effective_start_date=effective_start_date,
        effective_end_date=effective_end_date,
        reviewed_asset_classes=reviewed_asset_classes,
        schedule_override=schedule_override,
        account_truth_as_of=account_truth_as_of,
        evidence_readiness_builder=build_account_truth_evidence_readiness,
        promotion_evidence_builder=build_latest_account_truth_promotion_evidence,
    )


def build_reviewed_fee_schedule_review_status(
    state: Any,
    *,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Project the current persisted review without contacting a provider."""

    return build_reviewed_fee_schedule_review_status_workflow(
        state,
        as_of_date=as_of_date,
        preview_builder=build_reviewed_fee_schedule_preview,
        evidence_readiness_builder=build_account_truth_evidence_readiness,
        promotion_evidence_builder=build_latest_account_truth_promotion_evidence,
    )


def resolve_reviewed_fee_schedule(
    state: Any,
    *,
    start_date: str,
    end_date: str,
    universe: Sequence[str],
    asset_classes: Sequence[str],
    expected_cost_model_reference: str | None = None,
    account_truth_as_of: datetime | None = None,
) -> ReviewedFeeScheduleResolution:
    """Resolve an active review with all current fail-closed evidence checks."""

    return resolve_reviewed_fee_schedule_workflow(
        state,
        start_date=start_date,
        end_date=end_date,
        universe=universe,
        asset_classes=asset_classes,
        expected_cost_model_reference=expected_cost_model_reference,
        account_truth_as_of=account_truth_as_of,
        preview_builder=build_reviewed_fee_schedule_preview,
        evidence_readiness_builder=build_account_truth_evidence_readiness,
        promotion_evidence_builder=build_latest_account_truth_promotion_evidence,
    )


__all__ = [
    "REVIEWED_COST_MODEL_PREFIX",
    "REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION",
    "REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION",
    "REVIEWED_FEE_SCHEDULE_RESOLUTION_SCHEMA_VERSION",
    "REVIEWED_FEE_SCHEDULE_REVIEW_SCHEMA_VERSION",
    "REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION",
    "ReviewedFeeScheduleReadRejected",
    "ReviewedFeeScheduleRejected",
    "ReviewedFeeScheduleResolution",
    "ReviewedFeeScheduleReview",
    "ReviewedFeeScheduleReviewRepository",
    "active_review_matches_fee_evidence",
    "build_reviewed_fee_schedule_preview",
    "build_reviewed_fee_schedule_review_status",
    "is_reviewed_cost_model_reference",
    "resolve_reviewed_fee_schedule",
    "reviewed_cost_model_reference",
]
