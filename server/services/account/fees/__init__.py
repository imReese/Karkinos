"""Account fees domain package.

Owns fee schedules, commission calculation, policy validation, reconciliation,
and lifecycle workflows.
"""

from __future__ import annotations

from server.contracts.reviewed_fee_schedule import (
    REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    REVIEWED_FEE_SCHEDULE_REVIEW_SCHEMA_VERSION,
    REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
    ReviewedFeeScheduleReadRejected,
    ReviewedFeeScheduleRejected,
    ReviewedFeeScheduleReview,
)
from server.services.account.fees.commission import (
    CommissionCalculator,
    ReviewedFeeScheduleResolution,
    build_commission_calculator,
    is_reviewed_cost_model_reference,
    reviewed_cost_model_reference,
    validated_notional_envelope,
)
from server.services.account.fees.policy import (
    NOTIONAL_ENVELOPE_SCHEMA_VERSION,
    REVIEWED_COST_MODEL_PREFIX,
    REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION,
    REVIEWED_FEE_SCHEDULE_RESOLUTION_SCHEMA_VERSION,
    SUPPORTED_ASSET_CLASSES,
    SUPPORTED_REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSIONS,
    TRADE_EVENT_TYPES,
)
from server.services.account.fees.reconciliation import (
    active_review_matches_fee_evidence,
    compare_schedule_to_events,
    component_reconciliation_extends_reviewed,
)
from server.services.account.fees.repository import (
    ReviewedFeeScheduleReviewRepository,
)
from server.services.account.fees.workflows import (
    build_reviewed_fee_schedule_preview_workflow,
    build_reviewed_fee_schedule_review_status_workflow,
    freeze_deployment_fee_schedule,
    resolve_frozen_deployment_fee_schedule,
    resolve_reviewed_fee_schedule_workflow,
)

# Canonical domain aliases
FeeScheduleResolution = ReviewedFeeScheduleResolution
FeeScheduleReviewRepository = ReviewedFeeScheduleReviewRepository

__all__ = [
    "CommissionCalculator",
    "FeeScheduleResolution",
    "FeeScheduleReviewRepository",
    "NOTIONAL_ENVELOPE_SCHEMA_VERSION",
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
    "SUPPORTED_ASSET_CLASSES",
    "SUPPORTED_REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSIONS",
    "TRADE_EVENT_TYPES",
    "active_review_matches_fee_evidence",
    "build_commission_calculator",
    "build_reviewed_fee_schedule_preview_workflow",
    "build_reviewed_fee_schedule_review_status_workflow",
    "compare_schedule_to_events",
    "component_reconciliation_extends_reviewed",
    "freeze_deployment_fee_schedule",
    "is_reviewed_cost_model_reference",
    "resolve_frozen_deployment_fee_schedule",
    "resolve_reviewed_fee_schedule_workflow",
    "reviewed_cost_model_reference",
    "validated_notional_envelope",
]
