"""One-shot signed submit command with one permanent external claim."""

from __future__ import annotations

from typing import Any

from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_SUBMISSION_ACKNOWLEDGEMENT,
)
from server.services.controlled_broker_submission_gateway import (
    capabilities as _capabilities,
)
from server.services.controlled_broker_submission_gateway import health as _health
from server.services.controlled_broker_submission_policy import (
    classify_gateway_result as _classify_gateway_result,
)
from server.services.controlled_broker_submission_policy import (
    sanitize_gateway_result as _sanitize_gateway_result,
)
from server.services.controlled_broker_submission_values import aware_utc as _aware_utc
from server.services.controlled_broker_submission_values import (
    intent_response as _intent_response,
)


class ControlledBrokerSubmissionCommandMixin:
    def submit(
        self,
        *,
        order_id: str,
        confirmation_id: str,
        release_evidence_id: str,
        submit_fingerprint: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        existing = self._db.get_controlled_broker_submit_intent_for_order_sync(order_id)
        if existing is not None:
            if (
                str(existing.get("submit_fingerprint") or "") == submit_fingerprint
                and str(existing.get("confirmation_id") or "") == confirmation_id
                and str(existing.get("release_evidence_id") or "")
                == release_evidence_id
            ):
                return _intent_response(
                    existing,
                    reused=True,
                    external_call_performed=False,
                )
            raise self._submission_rejection(
                "controlled broker submission retry conflicts with persisted intent",
                evidence={
                    "status": "rejected",
                    "order_id": order_id,
                    "submit_intent_id": str(existing.get("submit_intent_id") or ""),
                    "blockers": ["controlled_broker_submit_retry_conflict"],
                    "submitted_to_broker": False,
                    "production_ledger_mutated": False,
                },
            )
        preview = self.preview(
            order_id=order_id,
            confirmation_id=confirmation_id,
            release_evidence_id=release_evidence_id,
        )
        rejection_reasons: list[str] = []
        if submit_fingerprint != preview["submit_fingerprint"]:
            rejection_reasons.append("controlled_broker_submit_fingerprint_mismatch")
        if acknowledgement != CONTROLLED_BROKER_SUBMISSION_ACKNOWLEDGEMENT:
            rejection_reasons.append(
                "controlled_broker_submit_acknowledgement_mismatch"
            )
        if preview["blockers"]:
            rejection_reasons.append("controlled_broker_submit_review_blocked")
        approval, approval_blockers = self._resolve_operator_approval_with_proof(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            proof_signature_base64=operator_proof_signature_base64,
            expected_action="submit_confirmed_broker_order",
            expected_artifact_type="controlled_broker_submission",
            expected_artifact_fingerprint=preview["submit_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            rejection_reasons.append(
                "controlled_broker_submit_operator_approval_blocked"
            )
        elif str(approval.get("operator_id") or "") != preview["operator_id"]:
            rejection_reasons.append("controlled_broker_submit_operator_mismatch")
        if rejection_reasons:
            evidence = self._record_rejection(
                preview=preview,
                submitted_fingerprint=submit_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=rejection_reasons,
                transaction_blockers=[],
            )
            raise self._submission_rejection(
                "controlled broker submission rejected",
                evidence=evidence,
            )

        confirmation_recheck = self._resolve_confirmation_evidence(
            confirmation_id=preview["confirmation_id"],
            expected_order_id=preview["order_id"],
            expected_order_fingerprint=preview["order_fingerprint"],
        )
        confirmation_recheck_blockers = list(confirmation_recheck["blockers"])
        for field in (
            "confirmation_id",
            "order_id",
            "order_fingerprint",
            "dossier_fingerprint",
            "gateway_id",
            "gateway_verification_fingerprint",
            "operator_id",
            "account_alias",
        ):
            if str(confirmation_recheck.get(field) or "") != str(
                preview.get(field) or ""
            ):
                confirmation_recheck_blockers.append(
                    f"controlled_broker_submit_confirmation_recheck_mismatch:{field}"
                )
        confirmation_recheck_blockers = list(
            dict.fromkeys(confirmation_recheck_blockers)
        )
        if confirmation_recheck_blockers:
            evidence = self._record_rejection(
                preview=preview,
                submitted_fingerprint=submit_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=[
                    "controlled_broker_submit_confirmation_changed_before_prepare"
                ],
                transaction_blockers=[
                    f"confirmation_recheck:{item}"
                    for item in confirmation_recheck_blockers
                ],
            )
            raise self._submission_rejection(
                "controlled broker submission confirmation changed before prepare",
                evidence=evidence,
            )

        now = _aware_utc(self._clock())
        order = self._db.get_oms_order_sync(preview["order_id"]) or {}
        payload = {
            **{
                key: preview[key]
                for key in (
                    "schema_version",
                    "submit_intent_id",
                    "submit_fingerprint",
                    "order_id",
                    "order_fingerprint",
                    "order_contract",
                    "confirmation_id",
                    "dossier_fingerprint",
                    "gateway_id",
                    "gateway_verification_fingerprint",
                    "release_evidence_id",
                    "release_evidence_fingerprint",
                    "client_order_id",
                    "operator_id",
                    "account_alias",
                )
            },
            "operator_approval_id": operator_approval_id,
            "status": "prepared",
            "external_call_count": 0,
            "automatic_submission_enabled": False,
            "strategy_direct_submission_enabled": False,
            "production_ledger_mutated": False,
        }
        transaction = self._db.prepare_controlled_broker_submit_intent_sync(
            intent={
                **{
                    key: payload[key]
                    for key in (
                        "submit_intent_id",
                        "submit_fingerprint",
                        "order_id",
                        "order_fingerprint",
                        "confirmation_id",
                        "dossier_fingerprint",
                        "gateway_id",
                        "gateway_verification_fingerprint",
                        "release_evidence_id",
                        "release_evidence_fingerprint",
                        "client_order_id",
                        "operator_id",
                        "operator_approval_id",
                    )
                },
                "order_snapshot": {
                    key: order.get(key)
                    for key in (
                        "symbol",
                        "side",
                        "asset_class",
                        "quantity",
                        "order_type",
                        "limit_price",
                    )
                },
                "prepared_at_epoch_ms": int(now.timestamp() * 1000),
                "prepared_at": now.isoformat(),
                "payload": payload,
                "created_at": now.isoformat(),
            }
        )
        if transaction.get("status") == "rejected":
            evidence = self._record_rejection(
                preview=preview,
                submitted_fingerprint=submit_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=["controlled_broker_submit_prepare_rejected"],
                transaction_blockers=[
                    str(item) for item in transaction.get("blockers") or []
                ],
            )
            raise self._submission_rejection(
                "controlled broker submit intent rejected",
                evidence=evidence,
            )
        if not transaction.get("external_call_permitted"):
            return _intent_response(
                transaction.get("intent") or {},
                reused=True,
                external_call_performed=False,
            )

        pre_call_blockers = self._pre_call_blockers(
            preview,
            operator_approval_id=operator_approval_id,
        )
        if pre_call_blockers:
            finalized = self._finalize(
                submit_intent_id=preview["submit_intent_id"],
                classification="rejected",
                result={
                    "status": "rejected_before_gateway_call",
                    "blockers": pre_call_blockers,
                    "submitted": False,
                },
                recovered=False,
            )
            return _intent_response(
                finalized.get("intent") or {},
                reused=False,
                external_call_performed=False,
            )

        gateway, gateway_blockers = self._gateway(preview["gateway_id"])
        if gateway_blockers:
            classification = "submission_unknown"
            raw_result = {
                "status": "gateway_unavailable_after_prepare",
                "submitted": None,
            }
            external_call_performed = False
        else:
            submitter = getattr(gateway, "submit_order", None)
            external_call_performed = callable(submitter)
            try:
                raw_result = (
                    submitter(
                        {
                            **preview["order_contract"],
                            "order_id": preview["order_id"],
                            "order_fingerprint": preview["order_fingerprint"],
                            "client_order_id": preview["client_order_id"],
                            "submit_intent_id": preview["submit_intent_id"],
                        }
                    )
                    if callable(submitter)
                    else {}
                )
                raw_result = raw_result if isinstance(raw_result, dict) else {}
                classification = _classify_gateway_result(
                    raw_result,
                    client_order_id=preview["client_order_id"],
                    order_fingerprint=preview["order_fingerprint"],
                    allow_definitive_not_found=False,
                )
            except Exception as exc:
                classification = "submission_unknown"
                raw_result = {
                    "status": "gateway_submit_exception",
                    "error_type": type(exc).__name__,
                    "submitted": None,
                }
        finalized = self._finalize(
            submit_intent_id=preview["submit_intent_id"],
            classification=classification,
            result=_sanitize_gateway_result(raw_result),
            recovered=False,
        )
        return _intent_response(
            finalized.get("intent") or {},
            reused=False,
            external_call_performed=external_call_performed,
        )

    def _pre_call_blockers(
        self,
        preview: dict[str, Any],
        *,
        operator_approval_id: str,
    ) -> list[str]:
        blockers: list[str] = []
        approval, approval_blockers = self._resolve_operator_approval(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            expected_action="submit_confirmed_broker_order",
            expected_artifact_type="controlled_broker_submission",
            expected_artifact_fingerprint=preview["submit_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            blockers.append("controlled_broker_submit_operator_approval_changed")
            blockers.extend(f"operator_approval:{item}" for item in approval_blockers)
        elif str(approval.get("operator_id") or "") != preview["operator_id"]:
            blockers.extend(
                (
                    "controlled_broker_submit_operator_approval_changed",
                    "operator_approval:operator_mismatch",
                )
            )
        if self._kill_switch().get("enabled") is not False:
            blockers.append("controlled_broker_submit_kill_switch_changed")
        release = self._resolve_release(
            preview["release_evidence_id"],
            expected_gateway_id=preview["gateway_id"],
            expected_account_alias=preview["account_alias"],
            now=_aware_utc(self._clock()),
        )
        if release["evidence_fingerprint"] != preview["release_evidence_fingerprint"]:
            blockers.append("controlled_broker_submit_release_changed")
        blockers.extend(release["blockers"])
        gateway, gateway_blockers = self._gateway(preview["gateway_id"])
        blockers.extend(gateway_blockers)
        _, capability_blockers = _capabilities(gateway)
        blockers.extend(capability_blockers)
        _, health_blockers = _health(gateway, now=_aware_utc(self._clock()))
        blockers.extend(health_blockers)
        return list(dict.fromkeys(blockers))
