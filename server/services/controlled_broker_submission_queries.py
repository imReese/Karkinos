"""Read-only status and persisted-intent queries for broker submission."""

from __future__ import annotations

from typing import Any

from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_RECOVERY_MINIMUM_WAIT_SECONDS,
    CONTROLLED_BROKER_SUBMISSION_STATUS_SCHEMA_VERSION,
)
from server.services.controlled_broker_submission_values import (
    intent_response as _intent_response,
)
from server.services.controlled_broker_submission_values import (
    safety_flags as _safety_flags,
)


class ControlledBrokerSubmissionQueryMixin:
    def get_status(self) -> dict[str, Any]:
        gateway_ids = [
            str(getattr(gateway, "gateway_id", "") or "")
            for gateway in self._gateways
            if str(getattr(gateway, "gateway_id", "") or "")
        ]
        duplicates = sorted(
            item for item in set(gateway_ids) if gateway_ids.count(item) > 1
        )
        dependencies_ready = bool(
            gateway_ids
            and not duplicates
            and callable(self._confirmation_provider)
            and callable(self._release_evidence_provider)
            and self._trusted_operator_identities
            and self._trading_controls is not None
        )
        interlock = self._submission_interlock()
        return {
            "schema_version": CONTROLLED_BROKER_SUBMISSION_STATUS_SCHEMA_VERSION,
            "contract_status": (
                "disabled_waiting_for_explicit_write_gateway_and_release_evidence"
                if not dependencies_ready
                else (
                    "blocked_by_unreconciled_controlled_submission"
                    if interlock["blocked"]
                    else "one_shot_manual_submission_available"
                )
            ),
            "registered_gateway_ids": sorted(set(gateway_ids)),
            "duplicate_gateway_ids": duplicates,
            "confirmation_provider_configured": callable(self._confirmation_provider),
            "release_evidence_provider_configured": callable(
                self._release_evidence_provider
            ),
            "trusted_operator_signature_configured": bool(
                self._trusted_operator_identities
            ),
            "kill_switch_provider_configured": self._trading_controls is not None,
            "default_broker_submission_enabled": False,
            "automatic_submission_enabled": False,
            "strategy_direct_submission_enabled": False,
            "recovery_resubmission_enabled": False,
            "recovery_minimum_wait_seconds": (
                CONTROLLED_BROKER_RECOVERY_MINIMUM_WAIT_SECONDS
            ),
            "submission_interlock": interlock,
            "safety": _safety_flags(),
        }

    def list_intents(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_controlled_broker_submit_intents_sync(
            limit=max(1, min(int(limit), 500))
        )
        return [
            _intent_response(row, reused=False, external_call_performed=False)
            for row in rows
        ]

    def get_intent(self, submit_intent_id: str) -> dict[str, Any]:
        row = self._db.get_controlled_broker_submit_intent_sync(submit_intent_id)
        if row is None:
            return {
                "status": "not_found",
                "submit_intent_id": submit_intent_id,
                "default_broker_submission_enabled": False,
            }
        return _intent_response(row, reused=False, external_call_performed=False)
