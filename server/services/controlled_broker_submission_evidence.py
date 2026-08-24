"""Persisted source resolution, interlock, and audit evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_RECOVERY_REJECTION_ENTITY_TYPE,
    CONTROLLED_BROKER_RECOVERY_REJECTION_EVENT_TYPE,
    CONTROLLED_BROKER_RECOVERY_SCHEMA_VERSION,
    CONTROLLED_BROKER_SUBMISSION_EVENT_SOURCE,
    CONTROLLED_BROKER_SUBMISSION_REJECTION_ENTITY_TYPE,
    CONTROLLED_BROKER_SUBMISSION_REJECTION_EVENT_TYPE,
    CONTROLLED_BROKER_SUBMISSION_SCHEMA_VERSION,
    REQUIRED_RELEASE_ASSERTIONS,
)
from server.services.controlled_broker_submission_values import (
    FINGERPRINT_PATTERN as _FINGERPRINT_PATTERN,
)
from server.services.controlled_broker_submission_values import aware_utc as _aware_utc
from server.services.controlled_broker_submission_values import (
    fingerprint as _fingerprint,
)
from server.services.controlled_broker_submission_values import mapping as _mapping
from server.services.controlled_broker_submission_values import (
    parse_timestamp as _parse_timestamp,
)


class ControlledBrokerSubmissionEvidenceMixin:
    def _resolve_confirmation_evidence(
        self,
        *,
        confirmation_id: str,
        expected_order_id: str,
        expected_order_fingerprint: str,
    ) -> dict[str, Any]:
        blockers: list[str] = []
        confirmation = self._resolve_provider(
            self._confirmation_provider,
            confirmation_id,
            unavailable="controlled_broker_submit_confirmation_provider_unavailable",
            failed="controlled_broker_submit_confirmation_provider_failed",
            blockers=blockers,
        )
        if confirmation.get("status") != (
            "current_verified_non_authorizing_confirmation"
        ):
            blockers.append("controlled_broker_submit_confirmation_not_current")
            blockers.extend(
                f"confirmation:{item}" for item in confirmation.get("blockers") or []
            )
        resolved_confirmation_id = str(confirmation.get("confirmation_id") or "")
        if resolved_confirmation_id != confirmation_id:
            blockers.append("controlled_broker_submit_confirmation_identity_mismatch")
        resolved_order_id = str(confirmation.get("order_id") or "")
        if resolved_order_id != expected_order_id:
            blockers.append("controlled_broker_submit_confirmation_order_mismatch")
        dossier = _mapping(confirmation.get("current_dossier"))
        order_fingerprint = str(dossier.get("order_fingerprint") or "")
        if order_fingerprint != expected_order_fingerprint:
            blockers.append("controlled_broker_submit_order_fingerprint_changed")
        gateway_verification = _mapping(dossier.get("execution_gateway_verification"))
        capital = _mapping(dossier.get("capital_evaluation"))
        scope = _mapping(capital.get("scope"))
        return {
            "confirmation_id": resolved_confirmation_id,
            "order_id": resolved_order_id,
            "order_fingerprint": order_fingerprint,
            "dossier_fingerprint": str(confirmation.get("dossier_fingerprint") or ""),
            "gateway_id": str(gateway_verification.get("gateway_id") or ""),
            "gateway_verification_fingerprint": str(
                gateway_verification.get("verification_fingerprint") or ""
            ),
            "operator_id": str(confirmation.get("operator_id") or ""),
            "account_alias": str(scope.get("account_alias") or ""),
            "current_dossier": dossier,
            "blockers": list(dict.fromkeys(blockers)),
        }

    def _resolve_provider(
        self,
        provider: Callable[[str], dict[str, Any]] | None,
        identifier: str,
        *,
        unavailable: str,
        failed: str,
        blockers: list[str],
    ) -> dict[str, Any]:
        if not callable(provider):
            blockers.append(unavailable)
            return {}
        try:
            value = provider(identifier) or {}
        except Exception:
            blockers.append(failed)
            return {}
        return value if isinstance(value, dict) else {}

    def _submission_interlock(
        self,
        *,
        exclude_order_id: str = "",
    ) -> dict[str, Any]:
        try:
            rows = self._db.list_unreconciled_controlled_broker_submit_intents_sync(
                limit=500
            )
        except Exception:
            return {
                "status": "blocked_source_unavailable",
                "blocked": True,
                "unresolved_count": 0,
                "unresolved_intents": [],
                "clearing_operation_available": False,
            }
        unresolved = [
            {
                "submit_intent_id": str(row.get("submit_intent_id") or ""),
                "order_id": str(row.get("order_id") or ""),
                "status": str(row.get("status") or "unknown"),
                "interlock_reason": str(
                    row.get("interlock_reason") or "unreconciled_submission"
                ),
                "lifecycle_blocker": str(row.get("lifecycle_blocker") or ""),
            }
            for row in rows
            if str(row.get("order_id") or "") != exclude_order_id
        ]
        return {
            "status": "blocked_unreconciled_submission" if unresolved else "clear",
            "blocked": bool(unresolved),
            "unresolved_count": len(unresolved),
            "unresolved_intents": unresolved[:20],
            "clearing_operation_available": False,
        }

    def _resolve_release(
        self,
        release_evidence_id: str,
        *,
        expected_gateway_id: str,
        expected_account_alias: str,
        now: datetime,
    ) -> dict[str, Any]:
        blockers: list[str] = []
        raw = self._resolve_provider(
            self._release_evidence_provider,
            release_evidence_id,
            unavailable="controlled_broker_submit_release_provider_unavailable",
            failed="controlled_broker_submit_release_provider_failed",
            blockers=blockers,
        )
        evidence_fingerprint = str(raw.get("evidence_fingerprint") or "")
        if raw.get("status") != "current_clear_signed_release":
            blockers.append("controlled_broker_submit_release_not_current")
        if str(raw.get("release_evidence_id") or "") != release_evidence_id:
            blockers.append("controlled_broker_submit_release_identity_mismatch")
        if not _FINGERPRINT_PATTERN.fullmatch(evidence_fingerprint):
            blockers.append("controlled_broker_submit_release_fingerprint_invalid")
        if str(raw.get("gateway_id") or "") != expected_gateway_id:
            blockers.append("controlled_broker_submit_release_gateway_mismatch")
        if str(raw.get("account_alias") or "") != expected_account_alias:
            blockers.append("controlled_broker_submit_release_account_mismatch")
        if raw.get("operator_identity_verified") is not True:
            blockers.append("controlled_broker_submit_release_operator_unverified")
        if raw.get("execution_mode") != "manual_each_order":
            blockers.append("controlled_broker_submit_release_mode_invalid")
        if raw.get("automatic_execution_allowed") is not False:
            blockers.append("controlled_broker_submit_release_automatic_mode_invalid")
        if raw.get("strategy_direct_submission_allowed") is not False:
            blockers.append("controlled_broker_submit_release_strategy_path_invalid")
        for field in REQUIRED_RELEASE_ASSERTIONS:
            if raw.get(field) is not True:
                blockers.append(f"controlled_broker_submit_release_{field}_missing")
        effective_at = _parse_timestamp(raw.get("effective_at"))
        expires_at = _parse_timestamp(raw.get("expires_at"))
        if effective_at is None or expires_at is None or expires_at <= effective_at:
            blockers.append("controlled_broker_submit_release_window_invalid")
        elif now < effective_at or now >= expires_at:
            blockers.append("controlled_broker_submit_release_not_effective")
        return {
            "status": "clear" if not blockers else "blocked",
            "release_evidence_id": release_evidence_id,
            "evidence_fingerprint": evidence_fingerprint,
            "gateway_id": str(raw.get("gateway_id") or ""),
            "account_alias": str(raw.get("account_alias") or ""),
            "effective_at": str(raw.get("effective_at") or ""),
            "expires_at": str(raw.get("expires_at") or ""),
            "review_assertions": {
                field: raw.get(field) is True for field in REQUIRED_RELEASE_ASSERTIONS
            },
            "blockers": list(dict.fromkeys(blockers)),
        }

    def _gateway(self, gateway_id: str) -> tuple[Any | None, list[str]]:
        matches = [
            item
            for item in self._gateways
            if str(getattr(item, "gateway_id", "") or "") == gateway_id
        ]
        if not matches:
            return None, ["controlled_broker_submit_gateway_not_registered"]
        if len(matches) > 1:
            return None, ["controlled_broker_submit_gateway_id_duplicated"]
        return matches[0], []

    def _kill_switch(self) -> dict[str, Any]:
        getter = getattr(self._trading_controls, "snapshot", None)
        if not callable(getter):
            return {"enabled": None, "reason_present": False, "updated_at": ""}
        try:
            value = getter()
        except Exception:
            return {"enabled": None, "reason_present": False, "updated_at": ""}
        return {
            "enabled": bool(getattr(value, "kill_switch_enabled", False)),
            "reason_present": bool(str(getattr(value, "reason", "") or "")),
            "updated_at": str(getattr(value, "updated_at", "") or ""),
        }

    def _finalize(
        self,
        *,
        submit_intent_id: str,
        classification: str,
        result: dict[str, Any],
        recovered: bool,
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        broker_order_id = str(result.get("broker_order_id") or "")
        broker_status = str(result.get("status") or "")
        transaction = self._db.finalize_controlled_broker_submit_intent_sync(
            submit_intent_id=submit_intent_id,
            status=classification,
            broker_order_id=broker_order_id,
            broker_status=broker_status,
            result=result,
            actor="controlled-broker-submission",
            finalized_at_epoch_ms=int(now.timestamp() * 1000),
            finalized_at=now.isoformat(),
            recovered=recovered,
        )
        if transaction.get("status") == "rejected" and transaction.get("blockers"):
            raise self._submission_rejection(
                "controlled broker submission result persistence rejected",
                evidence=transaction,
            )
        return transaction

    def _record_rejection(
        self,
        *,
        preview: dict[str, Any],
        submitted_fingerprint: str,
        operator_approval_id: str,
        rejection_reasons: list[str],
        transaction_blockers: list[str],
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        payload = {
            "schema_version": CONTROLLED_BROKER_SUBMISSION_SCHEMA_VERSION,
            "status": "rejected",
            "order_id": str(preview.get("order_id") or ""),
            "submit_intent_id": str(preview.get("submit_intent_id") or ""),
            "expected_fingerprint": str(preview.get("submit_fingerprint") or ""),
            "submitted_fingerprint": str(submitted_fingerprint or ""),
            "operator_approval_id": str(operator_approval_id or ""),
            "review_blockers": [str(item) for item in preview.get("blockers") or []],
            "rejection_reasons": list(dict.fromkeys(rejection_reasons)),
            "transaction_blockers": list(dict.fromkeys(transaction_blockers)),
            "submitted_to_broker": False,
            "production_ledger_mutated": False,
            "automatic_submission_enabled": False,
            "strategy_direct_submission_enabled": False,
        }
        attempt_id = _fingerprint({**payload, "attempted_at": now.isoformat()})
        event_id = self._db.append_event_sync(
            event_type=CONTROLLED_BROKER_SUBMISSION_REJECTION_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type=CONTROLLED_BROKER_SUBMISSION_REJECTION_ENTITY_TYPE,
            entity_id=attempt_id,
            source=CONTROLLED_BROKER_SUBMISSION_EVENT_SOURCE,
            source_ref=payload["expected_fingerprint"],
            payload={"attempt_id": attempt_id, **payload},
        )
        return {
            "event_id": event_id,
            "attempt_id": attempt_id,
            "recorded_at": now.isoformat(),
            "persisted": True,
            **payload,
        }

    def _record_recovery_rejection(
        self,
        *,
        preview: dict[str, Any],
        submitted_fingerprint: str,
        operator_approval_id: str,
        rejection_reasons: list[str],
        transaction_blockers: list[str],
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        payload = {
            "schema_version": CONTROLLED_BROKER_RECOVERY_SCHEMA_VERSION,
            "status": "rejected",
            "submit_intent_id": str(preview.get("submit_intent_id") or ""),
            "order_id": str(preview.get("order_id") or ""),
            "expected_fingerprint": str(preview.get("recovery_fingerprint") or ""),
            "submitted_fingerprint": str(submitted_fingerprint or ""),
            "operator_approval_id": str(operator_approval_id or ""),
            "review_blockers": [str(item) for item in preview.get("blockers") or []],
            "rejection_reasons": list(dict.fromkeys(rejection_reasons)),
            "transaction_blockers": list(dict.fromkeys(transaction_blockers)),
            "query_only": True,
            "broker_query_performed": False,
            "broker_submission_performed": False,
            "broker_cancel_performed": False,
            "production_ledger_mutated": False,
            "authority_changed": False,
        }
        attempt_id = _fingerprint({**payload, "attempted_at": now.isoformat()})
        event_id = self._db.append_event_sync(
            event_type=CONTROLLED_BROKER_RECOVERY_REJECTION_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type=CONTROLLED_BROKER_RECOVERY_REJECTION_ENTITY_TYPE,
            entity_id=attempt_id,
            source=CONTROLLED_BROKER_SUBMISSION_EVENT_SOURCE,
            source_ref=payload["expected_fingerprint"],
            payload={"attempt_id": attempt_id, **payload},
        )
        return {
            "event_id": event_id,
            "attempt_id": attempt_id,
            "recorded_at": now.isoformat(),
            "persisted": True,
            **payload,
        }
