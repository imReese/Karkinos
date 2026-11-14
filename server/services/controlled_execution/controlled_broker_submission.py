"""Fail-closed boundary for disabled controlled broker submissions."""

from __future__ import annotations

from typing import Any

from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_RECOVERY_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_SUBMISSION_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_SUBMISSION_STATUS_SCHEMA_VERSION,
)


class ControlledBrokerSubmissionRejected(Exception):
    def __init__(self, message: str, evidence: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.evidence = evidence or {}


class ControlledBrokerSubmissionService:
    """Fail-closed service rejecting all automated broker submission attempts."""

    def __init__(
        self,
        *,
        db: Any = None,
        gateways: list[Any] | None = None,
        confirmation_provider: Any = None,
        release_evidence_provider: Any = None,
        trusted_operator_identities: Any = None,
        trading_controls: Any = None,
        **kwargs: Any,
    ) -> None:
        self._db = db

    def get_status(self) -> dict[str, Any]:
        unresolved: list[dict[str, Any]] = []
        if self._db and hasattr(
            self._db, "list_unreconciled_controlled_broker_submit_intents_sync"
        ):
            try:
                rows = self._db.list_unreconciled_controlled_broker_submit_intents_sync(
                    limit=500
                )
                unresolved = [
                    {
                        "submit_intent_id": str(r.get("submit_intent_id") or ""),
                        "order_id": str(r.get("order_id") or ""),
                        "status": str(r.get("status") or "unknown"),
                        "interlock_reason": str(
                            r.get("interlock_reason") or "unreconciled_submission"
                        ),
                        "lifecycle_blocker": str(r.get("lifecycle_blocker") or ""),
                    }
                    for r in rows
                ]
            except Exception:
                pass

        return {
            "schema_version": CONTROLLED_BROKER_SUBMISSION_STATUS_SCHEMA_VERSION,
            "contract_status": (
                "disabled_waiting_for_explicit_write_gateway_and_release_evidence"
                if not unresolved
                else "blocked_by_unreconciled_controlled_submission"
            ),
            "registered_gateway_ids": [],
            "duplicate_gateway_ids": [],
            "confirmation_provider_configured": False,
            "release_evidence_provider_configured": False,
            "trusted_operator_signature_configured": False,
            "kill_switch_provider_configured": True,
            "default_broker_submission_enabled": False,
            "automatic_submission_enabled": False,
            "submission_interlock": {
                "schema_version": "karkinos.controlled_broker_submission_interlock.v1",
                "blocked": bool(unresolved),
                "unresolved_count": len(unresolved),
                "unresolved_intents": unresolved[:20],
            },
            "limitations": [
                "Automated broker submission is permanently disabled in Karkinos.",
                "Use ManualTradingService for copyable manual broker tickets.",
            ],
        }

    def preview(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ControlledBrokerSubmissionRejected(
            "automated broker submission is permanently disabled",
            {"status": "disabled", "reason": "automated_submission_disabled"},
        )

    def submit(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ControlledBrokerSubmissionRejected(
            "automated broker submission is permanently disabled",
            {"status": "disabled", "reason": "automated_submission_disabled"},
        )

    def preview_recovery(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ControlledBrokerSubmissionRejected(
            "automated broker submission recovery is permanently disabled",
            {"status": "disabled", "reason": "automated_recovery_disabled"},
        )

    def recover(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ControlledBrokerSubmissionRejected(
            "automated broker submission recovery is permanently disabled",
            {"status": "disabled", "reason": "automated_recovery_disabled"},
        )


__all__ = [
    "CONTROLLED_BROKER_RECOVERY_ACKNOWLEDGEMENT",
    "CONTROLLED_BROKER_SUBMISSION_ACKNOWLEDGEMENT",
    "ControlledBrokerSubmissionRejected",
    "ControlledBrokerSubmissionService",
]
