"""Stable contracts for the controlled broker write-edge release."""

from __future__ import annotations

import re
from typing import Any

CONTROLLED_BROKER_WRITE_RELEASE_DOSSIER_SCHEMA_VERSION = (
    "karkinos.controlled_broker_write_release_dossier.v1"
)
CONTROLLED_BROKER_WRITE_RELEASE_SCHEMA_VERSION = (
    "karkinos.controlled_broker_write_release.v1"
)
CONTROLLED_BROKER_WRITE_RELEASE_STATUS_SCHEMA_VERSION = (
    "karkinos.controlled_broker_write_release_status.v1"
)
CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_SCHEMA_VERSION = (
    "karkinos.controlled_broker_write_release_revocation.v1"
)
CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT = "issue_exact_expiring_manual_each_order_write_release_without_order_or_capital_authority"
CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_ACKNOWLEDGEMENT = (
    "revoke_exact_broker_write_release_without_resume_or_broker_action"
)
CONTROLLED_BROKER_WRITE_RELEASE_MAX_SECONDS = 12 * 60 * 60
CONTROLLED_BROKER_WRITE_RELEASE_ISSUE_CLOCK_SKEW_SECONDS = 5 * 60

CONTROLLED_BROKER_WRITE_RELEASE_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$"
)
CONTROLLED_BROKER_WRITE_RELEASE_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
CONTROLLED_BROKER_WRITE_RELEASE_OWNER_REVIEW_REF_FIELDS = (
    "broker_agreement_review",
    "account_permissions_review",
    "program_trading_reporting_review",
    "provider_acceptance_test_report",
    "deployment_authorization",
    "risk_controls_review",
    "rollback_drill_review",
)
CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_REASONS = frozenset(
    {
        "adapter_or_deployment_changed",
        "incident_or_anomaly",
        "owner_disabled",
        "provider_scope_changed",
        "regulatory_or_permission_change",
        "scheduled_expiry_superseded",
    }
)


class ControlledBrokerWriteReleaseRejected(ValueError):
    """Raised when an issue or revocation attempt fails closed."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


__all__ = [
    "CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT",
    "CONTROLLED_BROKER_WRITE_RELEASE_DOSSIER_SCHEMA_VERSION",
    "CONTROLLED_BROKER_WRITE_RELEASE_FINGERPRINT_PATTERN",
    "CONTROLLED_BROKER_WRITE_RELEASE_ID_PATTERN",
    "CONTROLLED_BROKER_WRITE_RELEASE_ISSUE_CLOCK_SKEW_SECONDS",
    "CONTROLLED_BROKER_WRITE_RELEASE_MAX_SECONDS",
    "CONTROLLED_BROKER_WRITE_RELEASE_OWNER_REVIEW_REF_FIELDS",
    "CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_ACKNOWLEDGEMENT",
    "CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_REASONS",
    "CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_SCHEMA_VERSION",
    "CONTROLLED_BROKER_WRITE_RELEASE_SCHEMA_VERSION",
    "CONTROLLED_BROKER_WRITE_RELEASE_STATUS_SCHEMA_VERSION",
    "ControlledBrokerWriteReleaseRejected",
]
