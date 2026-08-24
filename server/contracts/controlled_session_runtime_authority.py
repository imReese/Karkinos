"""Stable contracts for bounded controlled-session runtime authority."""

from __future__ import annotations

CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION = (
    "karkinos.controlled_session_runtime_authority.v1"
)
CONTROLLED_SESSION_RUNTIME_AUTHORITY_STATUS_SCHEMA_VERSION = (
    "karkinos.controlled_session_runtime_authority_status.v1"
)
CONTROLLED_SESSION_RUNTIME_AUTHORITY_REJECTION_EVENT_TYPE = (
    "controlled_session.runtime_authority_rejected"
)
CONTROLLED_SESSION_RUNTIME_AUTHORITY_ENTITY_TYPE = (
    "controlled_session_runtime_authority"
)
CONTROLLED_SESSION_RUNTIME_AUTHORITY_EVENT_SOURCE = (
    "controlled_session_runtime_authority"
)
CONTROLLED_SESSION_ISSUANCE_ACKNOWLEDGEMENT = (
    "issue_exact_expiring_non_broker_controlled_session"
)
CONTROLLED_SESSION_REVOCATION_ACKNOWLEDGEMENT = (
    "revoke_exact_controlled_session_no_auto_resume"
)
CONTROLLED_SESSION_REPLACEMENT_ACKNOWLEDGEMENT = (
    "replace_paused_session_with_equal_or_narrower_fresh_authority"
)
CONTROLLED_SESSION_REPLACEMENT_MINIMUM_STABILITY_SECONDS = 60
CONTROLLED_SESSION_REPLACEMENT_SNAPSHOT_MAX_AGE_SECONDS = 30
CONTROLLED_SESSION_REVOCATION_REASONS = frozenset(
    {
        "manual_operator_stop",
        "end_of_strategy_window",
        "operational_concern",
        "risk_review",
        "account_or_reconciliation_concern",
    }
)
