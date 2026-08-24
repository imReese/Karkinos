"""Command workflows for one-shot cancellation and query-only recovery."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from server.contracts.controlled_broker_cancellation import (
    CONTROLLED_BROKER_CANCELLATION_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_CANCELLATION_RECOVERY_ACKNOWLEDGEMENT,
    ControlledBrokerCancellationRejected,
    cancellation_aware_utc,
)
from server.projections.controlled_broker_cancellation import (
    controlled_broker_cancellation_command_response,
    controlled_broker_cancellation_safety_flags,
)
from server.services.controlled_broker_cancellation_policy import (
    classify_controlled_broker_cancel_result,
    sanitize_controlled_broker_cancel_result,
    sanitize_controlled_broker_query_result,
)
from server.services.operator_approval import (
    resolve_operator_approval,
    resolve_operator_approval_with_proof,
)

PreviewBuilder = Callable[..., dict[str, Any]]
GatewayResolver = Callable[[str], tuple[Any | None, list[str]]]
RejectionRecorder = Callable[..., dict[str, Any]]
TrustedIdentitiesProvider = Callable[[], list[Any] | tuple[Any, ...]]


def execute_controlled_broker_cancellation(
    *,
    db: Any,
    store: Any | None,
    trusted_operator_identities_provider: TrustedIdentitiesProvider,
    clock: Callable[[], datetime],
    preview_builder: PreviewBuilder,
    gateway_resolver: GatewayResolver,
    rejection_recorder: RejectionRecorder,
    submit_intent_id: str,
    cancel_fingerprint: str,
    operator_approval_id: str,
    operator_proof_signature_base64: str,
    acknowledgement: str,
) -> dict[str, Any]:
    """Persist one permanent cancel claim before its sole external call."""

    normalized = str(submit_intent_id or "").strip().lower()
    if store is not None:
        existing = store.get_for_intent(normalized)
        if existing is not None:
            if existing["cancel_fingerprint"] == str(cancel_fingerprint or ""):
                return controlled_broker_cancellation_command_response(
                    existing,
                    reused=True,
                    external_call_performed=False,
                )
            raise ControlledBrokerCancellationRejected(
                "controlled broker cancellation conflicts with persisted command",
                evidence={
                    "status": "rejected",
                    "submit_intent_id": normalized,
                    "cancel_command_id": existing["cancel_command_id"],
                    "blockers": ["controlled_broker_cancel_retry_conflict"],
                    "broker_cancel_performed": False,
                    "cancellation_proven": False,
                    "safety": controlled_broker_cancellation_safety_flags(),
                },
            )

    preview = preview_builder(submit_intent_id=normalized)
    rejection_reasons: list[str] = []
    if str(cancel_fingerprint or "") != preview["cancel_fingerprint"]:
        rejection_reasons.append("controlled_broker_cancel_fingerprint_mismatch")
    if acknowledgement != CONTROLLED_BROKER_CANCELLATION_ACKNOWLEDGEMENT:
        rejection_reasons.append("controlled_broker_cancel_acknowledgement_mismatch")
    if preview["blockers"]:
        rejection_reasons.append("controlled_broker_cancel_review_blocked")
    approval, approval_blockers = resolve_operator_approval_with_proof(
        db=db,
        trusted_identities=trusted_operator_identities_provider(),
        approval_id=operator_approval_id,
        proof_signature_base64=operator_proof_signature_base64,
        expected_action="cancel_exact_controlled_broker_order",
        expected_artifact_type="controlled_broker_cancellation",
        expected_artifact_fingerprint=preview["cancel_fingerprint"],
        clock=clock,
    )
    if approval_blockers:
        rejection_reasons.append("controlled_broker_cancel_operator_approval_blocked")
    elif str(approval.get("operator_id") or "") != preview["operator_id"]:
        rejection_reasons.append("controlled_broker_cancel_operator_mismatch")
    if rejection_reasons:
        evidence = rejection_recorder(
            preview=preview,
            submitted_fingerprint=str(cancel_fingerprint or ""),
            operator_approval_id=operator_approval_id,
            rejection_reasons=rejection_reasons,
            transaction_blockers=[],
            recovery=False,
        )
        raise ControlledBrokerCancellationRejected(
            "controlled broker cancellation rejected",
            evidence=evidence,
        )
    if store is None:
        raise ControlledBrokerCancellationRejected(
            "controlled broker cancellation audit store unavailable",
            evidence={
                "status": "rejected",
                "blockers": ["controlled_broker_cancel_audit_store_unavailable"],
                "safety": controlled_broker_cancellation_safety_flags(),
            },
        )

    now = cancellation_aware_utc(clock())
    transaction = store.prepare(
        preview=preview,
        operator_approval_id=operator_approval_id,
        prepared_at_epoch_ms=int(now.timestamp() * 1000),
        prepared_at=now.isoformat(),
    )
    if transaction["status"] == "rejected":
        evidence = rejection_recorder(
            preview=preview,
            submitted_fingerprint=str(cancel_fingerprint or ""),
            operator_approval_id=operator_approval_id,
            rejection_reasons=["controlled_broker_cancel_prepare_rejected"],
            transaction_blockers=transaction["blockers"],
            recovery=False,
        )
        raise ControlledBrokerCancellationRejected(
            "controlled broker cancellation claim rejected",
            evidence=evidence,
        )
    if not transaction["external_call_permitted"]:
        return controlled_broker_cancellation_command_response(
            transaction["command"],
            reused=True,
            external_call_performed=False,
        )

    fresh = preview_builder(submit_intent_id=normalized)
    pre_call_blockers = list(fresh["blockers"])
    if fresh["cancel_fingerprint"] != preview["cancel_fingerprint"]:
        pre_call_blockers.append("controlled_broker_cancel_evidence_changed")
    approval, approval_blockers = resolve_operator_approval(
        db=db,
        trusted_identities=trusted_operator_identities_provider(),
        approval_id=operator_approval_id,
        expected_action="cancel_exact_controlled_broker_order",
        expected_artifact_type="controlled_broker_cancellation",
        expected_artifact_fingerprint=preview["cancel_fingerprint"],
        clock=clock,
    )
    if approval_blockers:
        pre_call_blockers.append("controlled_broker_cancel_operator_approval_changed")
        pre_call_blockers.extend(
            f"operator_approval:{item}" for item in approval_blockers
        )
    elif str(approval.get("operator_id") or "") != preview["operator_id"]:
        pre_call_blockers.extend(
            (
                "controlled_broker_cancel_operator_approval_changed",
                "operator_approval:operator_mismatch",
            )
        )
    if pre_call_blockers:
        result = {
            "status": "rejected_before_gateway_call",
            "blockers": list(dict.fromkeys(pre_call_blockers)),
            "cancel_requested": False,
        }
        finalized = store.finalize(
            cancel_command_id=preview["cancel_command_id"],
            status="cancel_rejected",
            result=result,
            finalized_at_epoch_ms=int(now.timestamp() * 1000),
            finalized_at=now.isoformat(),
        )
        return controlled_broker_cancellation_command_response(
            finalized["command"],
            reused=False,
            external_call_performed=False,
        )

    gateway, gateway_blockers = gateway_resolver(
        str(preview["identity"].get("gateway_id") or "")
    )
    canceller = getattr(gateway, "cancel_order", None) if not gateway_blockers else None
    external_call_performed = callable(canceller)
    try:
        raw_result = (
            canceller(
                client_order_id=preview["identity"]["client_order_id"],
                cancel_command_id=preview["cancel_command_id"],
                command_fingerprint=preview["cancel_fingerprint"],
            )
            if callable(canceller)
            else {
                "status": "gateway_unavailable_after_prepare",
                "cancel_requested": None,
            }
        )
        raw_result = raw_result if isinstance(raw_result, dict) else {}
    except Exception as exc:
        raw_result = {
            "status": "gateway_cancel_exception",
            "error_type": type(exc).__name__,
            "cancel_requested": None,
        }
    sanitized = sanitize_controlled_broker_cancel_result(raw_result)
    classification = classify_controlled_broker_cancel_result(
        sanitized,
        expected=preview,
    )
    finalized_at = cancellation_aware_utc(clock())
    finalized = store.finalize(
        cancel_command_id=preview["cancel_command_id"],
        status=classification,
        result=sanitized,
        finalized_at_epoch_ms=int(finalized_at.timestamp() * 1000),
        finalized_at=finalized_at.isoformat(),
    )
    if finalized["status"] == "rejected":
        raise ControlledBrokerCancellationRejected(
            "controlled broker cancellation result persistence rejected",
            evidence=finalized,
        )
    return controlled_broker_cancellation_command_response(
        finalized["command"],
        reused=False,
        external_call_performed=external_call_performed,
    )


def execute_controlled_broker_cancellation_recovery(
    *,
    db: Any,
    store: Any | None,
    trusted_operator_identities_provider: TrustedIdentitiesProvider,
    clock: Callable[[], datetime],
    preview_builder: PreviewBuilder,
    gateway_resolver: GatewayResolver,
    rejection_recorder: RejectionRecorder,
    cancel_command_id: str,
    recovery_fingerprint: str,
    operator_approval_id: str,
    operator_proof_signature_base64: str,
    acknowledgement: str,
) -> dict[str, Any]:
    """Claim and perform one signed query without issuing another cancellation."""

    if store is not None:
        existing = store.find_recovery(
            recovery_fingerprint=str(recovery_fingerprint or ""),
            operator_approval_id=str(operator_approval_id or ""),
        )
        if existing is not None:
            return {
                **controlled_broker_cancellation_command_response(
                    existing["command"],
                    reused=True,
                    external_call_performed=False,
                ),
                "recovery_claim_id": existing["recovery_claim_id"],
                "recovery_fingerprint": str(recovery_fingerprint or ""),
                "recovery_operator_approval_id": str(operator_approval_id or ""),
                "recovery_query_performed": False,
                "recovery_status": str(
                    existing["result"].get("status") or existing["status"]
                ),
                "query_result": existing["result"],
                "query_result_authoritative": False,
                "query_only": True,
                "recancel_enabled": False,
            }
    preview = preview_builder(cancel_command_id=cancel_command_id)
    rejection_reasons: list[str] = []
    if str(recovery_fingerprint or "") != preview["recovery_fingerprint"]:
        rejection_reasons.append(
            "controlled_broker_cancel_recovery_fingerprint_mismatch"
        )
    if acknowledgement != CONTROLLED_BROKER_CANCELLATION_RECOVERY_ACKNOWLEDGEMENT:
        rejection_reasons.append(
            "controlled_broker_cancel_recovery_acknowledgement_mismatch"
        )
    if preview["blockers"]:
        rejection_reasons.append("controlled_broker_cancel_recovery_blocked")
    approval, approval_blockers = resolve_operator_approval_with_proof(
        db=db,
        trusted_identities=trusted_operator_identities_provider(),
        approval_id=operator_approval_id,
        proof_signature_base64=operator_proof_signature_base64,
        expected_action="query_exact_broker_cancellation_outcome",
        expected_artifact_type="controlled_broker_cancellation_recovery",
        expected_artifact_fingerprint=preview["recovery_fingerprint"],
        clock=clock,
    )
    if approval_blockers:
        rejection_reasons.append(
            "controlled_broker_cancel_recovery_operator_approval_blocked"
        )
    elif str(approval.get("operator_id") or "") != preview["operator_id"]:
        rejection_reasons.append("controlled_broker_cancel_recovery_operator_mismatch")
    if rejection_reasons:
        evidence = rejection_recorder(
            preview=preview,
            submitted_fingerprint=str(recovery_fingerprint or ""),
            operator_approval_id=operator_approval_id,
            rejection_reasons=rejection_reasons,
            transaction_blockers=[],
            recovery=True,
        )
        raise ControlledBrokerCancellationRejected(
            "controlled broker cancellation recovery rejected",
            evidence=evidence,
        )
    if store is None:
        raise ControlledBrokerCancellationRejected(
            "controlled broker cancellation recovery store unavailable",
            evidence={
                "status": "rejected",
                "blockers": ["controlled_broker_cancel_audit_store_unavailable"],
                "safety": controlled_broker_cancellation_safety_flags(),
            },
        )

    now = cancellation_aware_utc(clock())
    transaction = store.claim_recovery(
        preview=preview,
        operator_approval_id=operator_approval_id,
        claimed_at_epoch_ms=int(now.timestamp() * 1000),
        claimed_at=now.isoformat(),
    )
    if transaction["status"] == "rejected":
        evidence = rejection_recorder(
            preview=preview,
            submitted_fingerprint=str(recovery_fingerprint or ""),
            operator_approval_id=operator_approval_id,
            rejection_reasons=["controlled_broker_cancel_recovery_claim_rejected"],
            transaction_blockers=transaction["blockers"],
            recovery=True,
        )
        raise ControlledBrokerCancellationRejected(
            "controlled broker cancellation recovery claim rejected",
            evidence=evidence,
        )
    if not transaction["external_call_permitted"]:
        return {
            **controlled_broker_cancellation_command_response(
                transaction["command"],
                reused=True,
                external_call_performed=False,
            ),
            "recovery_claim_id": transaction["recovery_claim_id"],
            "recovery_query_performed": False,
            "query_only": True,
            "recancel_enabled": False,
        }

    command = transaction["command"]
    approval, approval_blockers = resolve_operator_approval(
        db=db,
        trusted_identities=trusted_operator_identities_provider(),
        approval_id=operator_approval_id,
        expected_action="query_exact_broker_cancellation_outcome",
        expected_artifact_type="controlled_broker_cancellation_recovery",
        expected_artifact_fingerprint=preview["recovery_fingerprint"],
        clock=clock,
    )
    pre_query_blockers: list[str] = []
    if approval_blockers:
        pre_query_blockers.append(
            "controlled_broker_cancel_recovery_operator_approval_changed"
        )
        pre_query_blockers.extend(
            f"operator_approval:{item}" for item in approval_blockers
        )
    elif str(approval.get("operator_id") or "") != preview["operator_id"]:
        pre_query_blockers.extend(
            (
                "controlled_broker_cancel_recovery_operator_approval_changed",
                "operator_approval:operator_mismatch",
            )
        )
    if pre_query_blockers:
        evidence = rejection_recorder(
            preview=preview,
            submitted_fingerprint=str(recovery_fingerprint or ""),
            operator_approval_id=operator_approval_id,
            rejection_reasons=[
                "controlled_broker_cancel_recovery_operator_approval_changed"
            ],
            transaction_blockers=pre_query_blockers,
            recovery=True,
        )
        sanitized = sanitize_controlled_broker_query_result(
            {
                "status": "rejected_before_gateway_query",
                "definitive": False,
                "reason": "operator_approval_changed_before_gateway_query",
            }
        )
        completed_at = cancellation_aware_utc(clock())
        finalized = store.finalize_recovery(
            recovery_claim_id=transaction["recovery_claim_id"],
            result=sanitized,
            completed_at_epoch_ms=int(completed_at.timestamp() * 1000),
            completed_at=completed_at.isoformat(),
        )
        if finalized["status"] == "rejected":
            raise ControlledBrokerCancellationRejected(
                "controlled broker cancellation recovery rejection persistence failed",
                evidence=finalized,
            )
        return {
            **controlled_broker_cancellation_command_response(
                finalized["command"],
                reused=False,
                external_call_performed=False,
            ),
            "recovery_status": "rejected_before_gateway_query",
            "recovery_claim_id": transaction["recovery_claim_id"],
            "recovery_fingerprint": preview["recovery_fingerprint"],
            "recovery_operator_approval_id": operator_approval_id,
            "recovery_rejection_event_id": int(evidence["event_id"]),
            "recovery_blockers": list(dict.fromkeys(pre_query_blockers)),
            "recovery_query_performed": False,
            "query_result": sanitized,
            "query_result_authoritative": False,
            "query_only": True,
            "recancel_enabled": False,
        }
    gateway, gateway_blockers = gateway_resolver(command["gateway_id"])
    query = getattr(gateway, "query_order", None) if not gateway_blockers else None
    external_call_performed = callable(query)
    try:
        raw_result = (
            query(command["client_order_id"])
            if callable(query)
            else {
                "status": "gateway_unavailable_after_claim",
                "definitive": False,
            }
        )
        raw_result = raw_result if isinstance(raw_result, dict) else {}
    except Exception as exc:
        raw_result = {
            "status": "gateway_query_exception",
            "error_type": type(exc).__name__,
            "definitive": False,
        }
    sanitized = sanitize_controlled_broker_query_result(raw_result)
    completed_at = cancellation_aware_utc(clock())
    finalized = store.finalize_recovery(
        recovery_claim_id=transaction["recovery_claim_id"],
        result=sanitized,
        completed_at_epoch_ms=int(completed_at.timestamp() * 1000),
        completed_at=completed_at.isoformat(),
    )
    if finalized["status"] == "rejected":
        raise ControlledBrokerCancellationRejected(
            "controlled broker cancellation recovery persistence rejected",
            evidence=finalized,
        )
    return {
        **controlled_broker_cancellation_command_response(
            finalized["command"],
            reused=False,
            external_call_performed=False,
        ),
        "recovery_claim_id": transaction["recovery_claim_id"],
        "recovery_fingerprint": preview["recovery_fingerprint"],
        "recovery_operator_approval_id": operator_approval_id,
        "recovery_query_performed": external_call_performed,
        "query_result": sanitized,
        "query_result_authoritative": False,
        "query_only": True,
        "recancel_enabled": False,
    }
