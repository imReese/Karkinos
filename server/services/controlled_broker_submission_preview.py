"""Fail-closed preview for one exact controlled broker submission."""

from __future__ import annotations

from typing import Any

from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_SUBMISSION_SCHEMA_VERSION,
)
from server.services.controlled_broker_submission_gateway import (
    capabilities as _capabilities,
)
from server.services.controlled_broker_submission_gateway import dry_run as _dry_run
from server.services.controlled_broker_submission_gateway import health as _health
from server.services.controlled_broker_submission_values import (
    FINGERPRINT_PATTERN as _FINGERPRINT_PATTERN,
)
from server.services.controlled_broker_submission_values import (
    ID_PATTERN as _ID_PATTERN,
)
from server.services.controlled_broker_submission_values import aware_utc as _aware_utc
from server.services.controlled_broker_submission_values import (
    client_order_id as _client_order_id,
)
from server.services.controlled_broker_submission_values import (
    fingerprint as _fingerprint,
)
from server.services.controlled_broker_submission_values import (
    json_object as _json_object,
)
from server.services.controlled_broker_submission_values import mapping as _mapping
from server.services.controlled_broker_submission_values import (
    safety_flags as _safety_flags,
)


class ControlledBrokerSubmissionPreviewMixin:
    def preview(
        self,
        *,
        order_id: str,
        confirmation_id: str,
        release_evidence_id: str,
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        normalized_order_id = str(order_id or "").strip()
        normalized_confirmation_id = str(confirmation_id or "").strip().lower()
        normalized_release_id = str(release_evidence_id or "").strip().lower()
        blockers: list[str] = []
        if not _ID_PATTERN.fullmatch(normalized_order_id):
            blockers.append("controlled_broker_submit_order_id_invalid")
        if not _FINGERPRINT_PATTERN.fullmatch(normalized_confirmation_id):
            blockers.append("controlled_broker_submit_confirmation_id_invalid")
        if not _FINGERPRINT_PATTERN.fullmatch(normalized_release_id):
            blockers.append("controlled_broker_submit_release_evidence_id_invalid")

        interlock = self._submission_interlock(exclude_order_id=normalized_order_id)
        if interlock["blocked"]:
            blockers.append("controlled_broker_submit_unreconciled_intent_exists")

        order = self._db.get_oms_order_sync(normalized_order_id) or {}
        if not order:
            blockers.append("controlled_broker_submit_order_not_found")
        elif str(order.get("status") or "") != "manually_confirmed":
            blockers.append("controlled_broker_submit_order_not_manually_confirmed")
        order_payload = _json_object(order.get("payload_json"))
        if str(order_payload.get("execution_mode") or "").lower() == "paper_shadow":
            blockers.append("controlled_broker_submit_simulated_order_forbidden")
        order_fingerprint = self._build_order_fingerprint(order) if order else ""
        order_contract = self._build_execution_gateway_order_contract(order)

        confirmation = self._resolve_confirmation_evidence(
            confirmation_id=normalized_confirmation_id,
            expected_order_id=normalized_order_id,
            expected_order_fingerprint=order_fingerprint,
        )
        blockers.extend(confirmation["blockers"])
        dossier = _mapping(confirmation.get("current_dossier"))
        gateway_verification = _mapping(dossier.get("execution_gateway_verification"))
        capital = _mapping(dossier.get("capital_evaluation"))
        scope = _mapping(capital.get("scope"))
        gateway_id = str(gateway_verification.get("gateway_id") or "")
        account_alias = str(scope.get("account_alias") or "")
        gateway_verification_fingerprint = str(
            gateway_verification.get("verification_fingerprint") or ""
        )
        if gateway_verification.get("status") != "pass":
            blockers.append("controlled_broker_submit_gateway_verification_not_clear")
        if gateway_verification.get("runtime_gateway_verified") is not True:
            blockers.append("controlled_broker_submit_gateway_not_verified")

        release = self._resolve_release(
            normalized_release_id,
            expected_gateway_id=gateway_id,
            expected_account_alias=account_alias,
            now=now,
        )
        blockers.extend(release["blockers"])
        gateway, gateway_blockers = self._gateway(gateway_id)
        blockers.extend(gateway_blockers)
        capabilities, capability_blockers = _capabilities(gateway)
        blockers.extend(capability_blockers)
        health, health_blockers = _health(gateway, now=now)
        blockers.extend(health_blockers)
        kill_switch = self._kill_switch()
        if kill_switch["enabled"] is not False:
            blockers.append("controlled_broker_submit_kill_switch_enabled")

        client_order_id = _client_order_id(
            order_id=normalized_order_id,
            order_fingerprint=order_fingerprint,
            confirmation_id=normalized_confirmation_id,
            release_evidence_fingerprint=release["evidence_fingerprint"],
        )
        gateway_order = {
            **order_contract,
            "order_id": normalized_order_id,
            "order_fingerprint": order_fingerprint,
            "client_order_id": client_order_id,
        }
        dry_run, dry_run_blockers = _dry_run(gateway, gateway_order)
        blockers.extend(dry_run_blockers)
        submission_core = {
            "schema_version": CONTROLLED_BROKER_SUBMISSION_SCHEMA_VERSION,
            "action": "submit_confirmed_broker_order",
            "order_id": normalized_order_id,
            "order_fingerprint": order_fingerprint,
            "order_contract": order_contract,
            "confirmation_id": normalized_confirmation_id,
            "dossier_fingerprint": str(confirmation.get("dossier_fingerprint") or ""),
            "gateway_id": gateway_id,
            "gateway_verification_fingerprint": (gateway_verification_fingerprint),
            "gateway_health_source_fingerprint": health["source_fingerprint"],
            "dry_run_payload_fingerprint": dry_run["payload_fingerprint"],
            "release_evidence_id": normalized_release_id,
            "release_evidence_fingerprint": release["evidence_fingerprint"],
            "client_order_id": client_order_id,
            "operator_id": str(confirmation.get("operator_id") or ""),
            "account_alias": account_alias,
        }
        submit_fingerprint = _fingerprint(submission_core)
        submit_intent_id = _fingerprint(
            {
                "domain": "karkinos.controlled_broker.submit_intent_id.v1",
                "submit_fingerprint": submit_fingerprint,
            }
        )
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            **submission_core,
            "submit_intent_id": submit_intent_id,
            "submit_fingerprint": submit_fingerprint,
            "generated_at": now.isoformat(),
            "status": "ready_for_final_signature" if not unique_blockers else "blocked",
            "ready": not unique_blockers,
            "blockers": unique_blockers,
            "gateway_capabilities": capabilities,
            "gateway_health": health,
            "dry_run": dry_run,
            "release_evidence": release,
            "kill_switch": kill_switch,
            "submission_interlock": interlock,
            "required_operator_approval": {
                "action": "submit_confirmed_broker_order",
                "artifact_type": "controlled_broker_submission",
                "artifact_fingerprint": submit_fingerprint,
            },
            "submitted_to_broker": False,
            "default_broker_submission_enabled": False,
            "automatic_submission_enabled": False,
            "strategy_direct_submission_enabled": False,
            "production_ledger_mutated": False,
            "safety": _safety_flags(),
        }
