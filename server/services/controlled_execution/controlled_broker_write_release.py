"""Fail-closed boundary for disabled controlled broker write releases."""

from __future__ import annotations

from typing import Any

from server.contracts.controlled_broker_write_release import (
    CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_WRITE_RELEASE_STATUS_SCHEMA_VERSION,
    ControlledBrokerWriteReleaseRejected,
)


class ControlledBrokerWriteReleaseService:
    """Fail-closed service rejecting all automated write release attempts."""

    def __init__(
        self,
        *,
        db: Any = None,
        trusted_operator_identities: Any = None,
        soak_promotion_provider: Any = None,
        clock: Any = None,
        **kwargs: Any,
    ) -> None:
        self._db = db

    def get_status(self) -> dict[str, Any]:
        return {
            "schema_version": CONTROLLED_BROKER_WRITE_RELEASE_STATUS_SCHEMA_VERSION,
            "contract_status": "disabled",
            "registered_releases": [],
            "active_releases": [],
            "active_release_count": 0,
            "revoked_releases": [],
            "expired_releases": [],
            "trusted_operator_identities_configured": False,
            "default_broker_submission_enabled": False,
            "automatic_submission_enabled": False,
            "limitations": [
                "Automated broker write release is permanently disabled in Karkinos."
            ],
        }

    def preview_dossier(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ControlledBrokerWriteReleaseRejected(
            "automated broker write release is permanently disabled",
            {"status": "disabled", "reason": "write_release_disabled"},
        )

    def record_release(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ControlledBrokerWriteReleaseRejected(
            "automated broker write release is permanently disabled",
            {"status": "disabled", "reason": "write_release_disabled"},
        )

    def list_releases(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return []

    def get_release(self, release_evidence_id: str) -> dict[str, Any] | None:
        return None

    def preview_revocation(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ControlledBrokerWriteReleaseRejected(
            "automated broker write release revocation is permanently disabled",
            {"status": "disabled", "reason": "write_release_disabled"},
        )

    def revoke_release(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ControlledBrokerWriteReleaseRejected(
            "automated broker write release revocation is permanently disabled",
            {"status": "disabled", "reason": "write_release_disabled"},
        )

    def resolve(self, release_evidence_id: str) -> dict[str, Any]:
        return {}


__all__ = [
    "CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT",
    "CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_ACKNOWLEDGEMENT",
    "ControlledBrokerWriteReleaseRejected",
    "ControlledBrokerWriteReleaseService",
]
