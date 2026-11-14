"""Fail-closed boundary for disabled controlled broker cancellations."""

from __future__ import annotations

from typing import Any

from server.contracts.controlled_broker_cancellation import (
    CONTROLLED_BROKER_CANCELLATION_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_CANCELLATION_RECOVERY_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_CANCELLATION_STATUS_SCHEMA_VERSION,
    ControlledBrokerCancellationRejected,
)


class ControlledBrokerCancellationService:
    """Fail-closed service rejecting all automated broker cancellation attempts."""

    def __init__(
        self,
        *,
        db: Any = None,
        gateways: list[Any] | tuple[Any, ...] = (),
        release_evidence_provider: Any = None,
        trusted_operator_identities: list[Any] | tuple[Any, ...] = (),
        clock: Any = None,
        **kwargs: Any,
    ) -> None:
        self._db = db

    def get_status(self) -> dict[str, Any]:
        return {
            "schema_version": CONTROLLED_BROKER_CANCELLATION_STATUS_SCHEMA_VERSION,
            "contract_status": "disabled_waiting_for_explicit_write_gateway_and_release_evidence",
            "registered_gateway_ids": [],
            "duplicate_gateway_ids": [],
            "release_evidence_provider_configured": False,
            "trusted_operator_signature_configured": False,
            "default_broker_cancellation_enabled": False,
            "automatic_cancellation_enabled": False,
            "store_configured": False,
            "ready": False,
            "limitations": [
                "Automated broker cancellation is permanently disabled in Karkinos.",
                "Use manual broker workflow for order cancellation.",
            ],
        }

    def preview(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ControlledBrokerCancellationRejected(
            "automated broker cancellation is permanently disabled",
            {"status": "disabled", "reason": "automated_cancellation_disabled"},
        )

    def cancel(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ControlledBrokerCancellationRejected(
            "automated broker cancellation is permanently disabled",
            {"status": "disabled", "reason": "automated_cancellation_disabled"},
        )

    def preview_recovery(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ControlledBrokerCancellationRejected(
            "automated broker cancellation recovery is permanently disabled",
            {"status": "disabled", "reason": "automated_recovery_disabled"},
        )

    def recover(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ControlledBrokerCancellationRejected(
            "automated broker cancellation recovery is permanently disabled",
            {"status": "disabled", "reason": "automated_recovery_disabled"},
        )

    def get_command(self, cancel_command_id: str) -> dict[str, Any]:
        return {
            "status": "not_found",
            "cancel_command_id": cancel_command_id,
            "default_broker_cancellation_enabled": False,
            "safety": {
                "default_off": True,
                "human_supervised": True,
                "automated_cancellation_disabled": True,
            },
        }

    def list_commands(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return []


__all__ = [
    "CONTROLLED_BROKER_CANCELLATION_ACKNOWLEDGEMENT",
    "CONTROLLED_BROKER_CANCELLATION_RECOVERY_ACKNOWLEDGEMENT",
    "ControlledBrokerCancellationRejected",
    "ControlledBrokerCancellationService",
]
