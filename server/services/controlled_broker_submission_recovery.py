"""Signed query-only recovery for unknown controlled submissions."""

from __future__ import annotations

from typing import Any

from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_RECOVERY_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_RECOVERY_MINIMUM_WAIT_SECONDS,
    CONTROLLED_BROKER_RECOVERY_SCHEMA_VERSION,
)
from server.services.controlled_broker_submission_policy import (
    classify_gateway_result as _classify_gateway_result,
)
from server.services.controlled_broker_submission_policy import (
    sanitize_gateway_result as _sanitize_gateway_result,
)
from server.services.controlled_broker_submission_values import (
    FINGERPRINT_PATTERN as _FINGERPRINT_PATTERN,
)
from server.services.controlled_broker_submission_values import aware_utc as _aware_utc
from server.services.controlled_broker_submission_values import (
    fingerprint as _fingerprint,
)
from server.services.controlled_broker_submission_values import (
    intent_response as _intent_response,
)
from server.services.controlled_broker_submission_values import (
    json_object as _json_object,
)
from server.services.controlled_broker_submission_values import (
    safety_flags as _safety_flags,
)


class ControlledBrokerSubmissionRecoveryMixin:
    def preview_recovery(self, *, submit_intent_id: str) -> dict[str, Any]:
        """Build a persisted-evidence-bound preview without contacting a gateway."""
        normalized = str(submit_intent_id or "").strip().lower()
        now = _aware_utc(self._clock())
        blockers: list[str] = []
        if not _FINGERPRINT_PATTERN.fullmatch(normalized):
            blockers.append("controlled_broker_submit_intent_id_invalid")
        row = self._db.get_controlled_broker_submit_intent_sync(normalized) or {}
        if not row:
            blockers.append("controlled_broker_submit_intent_not_found")
        source_status = str(row.get("status") or "not_found")
        if row and source_status not in {"prepared", "submission_unknown"}:
            blockers.append("controlled_broker_recovery_query_not_required")
        previous_attempt_epoch_ms = max(
            int(row.get("prepared_at_epoch_ms") or 0),
            int(row.get("last_recovery_at_epoch_ms") or 0),
        )
        elapsed_seconds = max(
            0,
            int(now.timestamp()) - previous_attempt_epoch_ms // 1000,
        )
        recovery_wait_remaining_seconds = max(
            0,
            CONTROLLED_BROKER_RECOVERY_MINIMUM_WAIT_SECONDS - elapsed_seconds,
        )
        if row and recovery_wait_remaining_seconds:
            blockers.append("controlled_broker_recovery_query_wait_required")
        gateway, gateway_blockers = self._gateway(str(row.get("gateway_id") or ""))
        blockers.extend(gateway_blockers)
        raw_capabilities = (
            getattr(gateway, "capabilities", {}) if gateway is not None else {}
        )
        can_query_orders = bool(
            raw_capabilities.get("can_query_orders")
            if isinstance(raw_capabilities, dict)
            else getattr(raw_capabilities, "can_query_orders", False)
        )
        if gateway is not None and not can_query_orders:
            blockers.append("controlled_broker_recovery_query_capability_missing")
        if gateway is not None and not callable(getattr(gateway, "query_order", None)):
            blockers.append("controlled_broker_recovery_query_method_unavailable")
        persisted_gateway_result = _sanitize_gateway_result(
            _json_object(row.get("result_json"))
        )
        recovery_contract = {
            "schema_version": CONTROLLED_BROKER_RECOVERY_SCHEMA_VERSION,
            "action": "query_unknown_controlled_broker_submission",
            "submit_intent_id": normalized,
            "submit_fingerprint": str(row.get("submit_fingerprint") or ""),
            "order_id": str(row.get("order_id") or ""),
            "order_fingerprint": str(row.get("order_fingerprint") or ""),
            "gateway_id": str(row.get("gateway_id") or ""),
            "client_order_id": str(row.get("client_order_id") or ""),
            "operator_id": str(row.get("operator_id") or ""),
            "source_status": source_status,
            "source_result_fingerprint": _fingerprint(persisted_gateway_result),
            "prepared_at": str(row.get("prepared_at") or ""),
            "last_recovery_at": str(row.get("last_recovery_at") or ""),
            "last_recovery_at_epoch_ms": int(row.get("last_recovery_at_epoch_ms") or 0),
            "query_contract": "query_order_by_exact_client_order_id",
            "resubmission_allowed": False,
        }
        recovery_fingerprint = _fingerprint(recovery_contract)
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            **recovery_contract,
            "recovery_fingerprint": recovery_fingerprint,
            "generated_at": now.isoformat(),
            "review_status": (
                "ready_for_final_signature" if not unique_blockers else "blocked"
            ),
            "review_ready": not unique_blockers,
            "blockers": unique_blockers,
            "recovery_wait_remaining_seconds": recovery_wait_remaining_seconds,
            "gateway_query_capability": can_query_orders,
            "persisted_gateway_result": persisted_gateway_result,
            "required_operator_approval": {
                "action": "query_unknown_controlled_broker_submission",
                "artifact_type": "controlled_broker_submission_recovery",
                "artifact_fingerprint": recovery_fingerprint,
            },
            "reads_persisted_facts_only": True,
            "provider_contact_performed": False,
            "broker_query_performed": False,
            "broker_submission_performed": False,
            "broker_cancel_performed": False,
            "production_ledger_mutated": False,
            "authority_changed": False,
            "safety": _safety_flags(),
        }

    def recover(
        self,
        *,
        submit_intent_id: str,
        recovery_fingerprint: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        """Run one signed query-only recovery attempt; never call submit or cancel."""
        normalized = str(submit_intent_id or "").strip().lower()
        submitted_fingerprint = str(recovery_fingerprint or "").strip().lower()
        preview = self.preview_recovery(submit_intent_id=normalized)
        rejection_reasons: list[str] = []
        if submitted_fingerprint != preview["recovery_fingerprint"]:
            rejection_reasons.append(
                "controlled_broker_recovery_query_fingerprint_mismatch"
            )
        if acknowledgement != CONTROLLED_BROKER_RECOVERY_ACKNOWLEDGEMENT:
            rejection_reasons.append(
                "controlled_broker_recovery_query_acknowledgement_mismatch"
            )
        if preview["blockers"]:
            rejection_reasons.append("controlled_broker_recovery_query_review_blocked")
        approval, approval_blockers = self._resolve_operator_approval_with_proof(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            proof_signature_base64=operator_proof_signature_base64,
            expected_action="query_unknown_controlled_broker_submission",
            expected_artifact_type="controlled_broker_submission_recovery",
            expected_artifact_fingerprint=preview["recovery_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            rejection_reasons.append(
                "controlled_broker_recovery_query_operator_approval_blocked"
            )
        elif str(approval.get("operator_id") or "") != preview["operator_id"]:
            rejection_reasons.append(
                "controlled_broker_recovery_query_operator_mismatch"
            )
        if rejection_reasons:
            evidence = self._record_recovery_rejection(
                preview=preview,
                submitted_fingerprint=submitted_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=rejection_reasons,
                transaction_blockers=[],
            )
            raise self._submission_rejection(
                "controlled broker recovery query rejected",
                evidence=evidence,
            )

        now = _aware_utc(self._clock())
        transaction = self._db.claim_controlled_broker_recovery_query_sync(
            submit_intent_id=normalized,
            recovery_fingerprint=preview["recovery_fingerprint"],
            operator_approval_id=operator_approval_id,
            claimed_at_epoch_ms=int(now.timestamp() * 1000),
            claimed_at=now.isoformat(),
            minimum_wait_seconds=CONTROLLED_BROKER_RECOVERY_MINIMUM_WAIT_SECONDS,
        )
        if transaction.get("status") == "rejected":
            evidence = self._record_recovery_rejection(
                preview=preview,
                submitted_fingerprint=submitted_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=["controlled_broker_recovery_query_claim_rejected"],
                transaction_blockers=[
                    str(item) for item in transaction.get("blockers") or []
                ],
            )
            raise self._submission_rejection(
                "controlled broker recovery query claim rejected",
                evidence=evidence,
            )
        if not transaction.get("external_call_permitted"):
            row = transaction.get("intent") or {}
            return {
                **_intent_response(
                    row,
                    reused=True,
                    external_call_performed=False,
                ),
                "status": str(transaction.get("status") or row.get("status") or ""),
                "recovery_fingerprint": preview["recovery_fingerprint"],
                "recovery_operator_approval_id": operator_approval_id,
                "recovery_query_performed": False,
                "recovery_wait_remaining_seconds": int(
                    transaction.get("recovery_wait_remaining_seconds") or 0
                ),
            }

        claimed = transaction.get("intent") or {}
        approval, approval_blockers = self._resolve_operator_approval(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            expected_action="query_unknown_controlled_broker_submission",
            expected_artifact_type="controlled_broker_submission_recovery",
            expected_artifact_fingerprint=preview["recovery_fingerprint"],
            clock=self._clock,
        )
        pre_query_blockers: list[str] = []
        if approval_blockers:
            pre_query_blockers.append(
                "controlled_broker_recovery_query_operator_approval_changed"
            )
            pre_query_blockers.extend(
                f"operator_approval:{item}" for item in approval_blockers
            )
        elif str(approval.get("operator_id") or "") != preview["operator_id"]:
            pre_query_blockers.extend(
                (
                    "controlled_broker_recovery_query_operator_approval_changed",
                    "operator_approval:operator_mismatch",
                )
            )
        if pre_query_blockers:
            evidence = self._record_recovery_rejection(
                preview=preview,
                submitted_fingerprint=submitted_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=[
                    "controlled_broker_recovery_query_operator_approval_changed"
                ],
                transaction_blockers=pre_query_blockers,
            )
            return {
                **_intent_response(
                    claimed,
                    reused=False,
                    external_call_performed=False,
                ),
                "recovery_status": "rejected_before_gateway_query",
                "recovery_fingerprint": preview["recovery_fingerprint"],
                "recovery_operator_approval_id": operator_approval_id,
                "recovery_claim_id": str(transaction.get("claim_id") or ""),
                "recovery_rejection_event_id": int(evidence["event_id"]),
                "recovery_blockers": list(dict.fromkeys(pre_query_blockers)),
                "recovery_query_performed": False,
            }
        gateway, gateway_blockers = self._gateway(str(claimed.get("gateway_id") or ""))
        query = getattr(gateway, "query_order", None) if not gateway_blockers else None
        external_call_performed = callable(query)
        try:
            raw_result = (
                query(str(claimed.get("client_order_id") or ""))
                if callable(query)
                else {}
            )
            raw_result = raw_result if isinstance(raw_result, dict) else {}
        except Exception as exc:
            raw_result = {
                "status": "gateway_query_exception",
                "error_type": type(exc).__name__,
                "submitted": None,
            }
        classification = _classify_gateway_result(
            raw_result,
            client_order_id=str(claimed.get("client_order_id") or ""),
            order_fingerprint=str(claimed.get("order_fingerprint") or ""),
            allow_definitive_not_found=True,
        )
        finalized = self._finalize(
            submit_intent_id=normalized,
            classification=classification,
            result=_sanitize_gateway_result(raw_result),
            recovered=True,
        )
        return {
            **_intent_response(
                finalized.get("intent") or {},
                reused=False,
                external_call_performed=external_call_performed,
            ),
            "recovery_fingerprint": preview["recovery_fingerprint"],
            "recovery_operator_approval_id": operator_approval_id,
            "recovery_claim_id": str(transaction.get("claim_id") or ""),
            "recovery_query_performed": external_call_performed,
        }
