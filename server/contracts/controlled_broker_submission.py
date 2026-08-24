"""Canonical contracts for one-shot controlled broker submission."""

from __future__ import annotations

CONTROLLED_BROKER_SUBMISSION_SCHEMA_VERSION = "karkinos.controlled_broker_submission.v1"
CONTROLLED_BROKER_SUBMISSION_STATUS_SCHEMA_VERSION = (
    "karkinos.controlled_broker_submission_status.v1"
)
CONTROLLED_BROKER_SUBMISSION_ACKNOWLEDGEMENT = (
    "submit_one_exact_manually_confirmed_order_once"
)
CONTROLLED_BROKER_RECOVERY_SCHEMA_VERSION = (
    "karkinos.controlled_broker_submission_recovery.v1"
)
CONTROLLED_BROKER_RECOVERY_ACKNOWLEDGEMENT = (
    "query_exact_unknown_submission_once_without_resubmit"
)
CONTROLLED_BROKER_RECOVERY_REJECTION_EVENT_TYPE = (
    "controlled_broker.recovery_query_rejected"
)
CONTROLLED_BROKER_RECOVERY_REJECTION_ENTITY_TYPE = (
    "controlled_broker_submission_recovery_rejection"
)
CONTROLLED_BROKER_SUBMISSION_REJECTION_EVENT_TYPE = (
    "controlled_broker.submission_rejected"
)
CONTROLLED_BROKER_SUBMISSION_REJECTION_ENTITY_TYPE = (
    "controlled_broker_submission_rejection"
)
CONTROLLED_BROKER_SUBMISSION_EVENT_SOURCE = "controlled_broker_submission"
CONTROLLED_BROKER_RECOVERY_MINIMUM_WAIT_SECONDS = 30
CONTROLLED_BROKER_GATEWAY_HEALTH_MAX_AGE_SECONDS = 60

REQUIRED_CAPABILITIES = (
    "can_cancel_orders",
    "can_dry_run_orders",
    "can_query_orders",
    "can_submit_orders",
    "supports_idempotent_client_order_id",
)
REQUIRED_RELEASE_ASSERTIONS = (
    "broker_agreement_reviewed",
    "connector_tested",
    "program_trading_reporting_reviewed",
    "risk_controls_reviewed",
)
GATEWAY_RESULT_STATUSES = frozenset(
    {
        "accepted",
        "submitted",
        "open",
        "partially_filled",
        "filled",
        "rejected",
        "not_found",
        "gateway_unavailable_after_prepare",
        "gateway_submit_exception",
        "gateway_query_exception",
    }
)
