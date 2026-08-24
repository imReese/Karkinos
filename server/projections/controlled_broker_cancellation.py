"""Read-only projections for controlled broker cancellation evidence."""

from __future__ import annotations

from typing import Any

from server.contracts.controlled_broker_cancellation import (
    CONTROLLED_BROKER_CANCELLATION_SCHEMA_VERSION,
    cancellation_mapping,
)


def controlled_broker_cancellation_safety_flags() -> dict[str, bool]:
    """Expose the fixed non-authorizing cancellation safety contract."""

    return {
        "reads_persisted_financial_facts_only": True,
        "preview_contacts_provider": False,
        "default_broker_cancellation_enabled": False,
        "automatic_cancellation_enabled": False,
        "strategy_direct_cancellation_enabled": False,
        "ai_direct_cancellation_enabled": False,
        "cancellation_retry_enabled": False,
        "query_only_recovery": True,
        "cancellation_proven": False,
        "canonical_lifecycle_mutated": False,
        "oms_mutated": False,
        "production_ledger_mutated": False,
        "risk_state_mutated": False,
        "kill_switch_mutated": False,
        "capital_authority_changed": False,
        "releases_submission_interlock": False,
    }


def controlled_broker_cancellation_command_response(
    row: dict[str, Any],
    *,
    reused: bool,
    external_call_performed: bool,
) -> dict[str, Any]:
    """Project one persisted command without upgrading broker telemetry."""

    result = cancellation_mapping(row.get("result"))
    return {
        "schema_version": CONTROLLED_BROKER_CANCELLATION_SCHEMA_VERSION,
        "status": str(row.get("status") or "unknown"),
        "cancel_command_id": str(row.get("cancel_command_id") or ""),
        "cancel_fingerprint": str(row.get("cancel_fingerprint") or ""),
        "submit_intent_id": str(row.get("submit_intent_id") or ""),
        "submit_fingerprint": str(row.get("submit_fingerprint") or ""),
        "ticket_fingerprint": str(row.get("ticket_fingerprint") or ""),
        "order_id": str(row.get("order_id") or ""),
        "order_fingerprint": str(row.get("order_fingerprint") or ""),
        "provider": str(row.get("provider") or ""),
        "gateway_id": str(row.get("gateway_id") or ""),
        "account_alias": str(row.get("account_alias") or ""),
        "broker_order_id": str(row.get("broker_order_id") or ""),
        "client_order_id": str(row.get("client_order_id") or ""),
        "release_evidence_id": str(row.get("release_evidence_id") or ""),
        "release_evidence_fingerprint": str(
            row.get("release_evidence_fingerprint") or ""
        ),
        "lifecycle_observation_id": str(row.get("lifecycle_observation_id") or ""),
        "lifecycle_evidence_fingerprint": str(
            row.get("lifecycle_evidence_fingerprint") or ""
        ),
        "lifecycle_source_sequence": int(row.get("lifecycle_source_sequence") or 0),
        "operator_id": str(row.get("operator_id") or ""),
        "operator_approval_id": str(row.get("operator_approval_id") or ""),
        "prepared_at": str(row.get("prepared_at") or ""),
        "finalized_at": str(row.get("finalized_at") or ""),
        "last_query_at": str(row.get("last_query_at") or ""),
        "query_count": int(row.get("query_count") or 0),
        "result": result,
        "last_query_result": cancellation_mapping(row.get("last_query_result")),
        "reused": reused,
        "external_call_performed": external_call_performed,
        "broker_cancel_request_sent": bool(
            external_call_performed
            and str(row.get("status") or "")
            in {"cancel_requested", "cancel_rejected", "cancellation_unknown"}
        ),
        "cancellation_proven": False,
        "canonical_lifecycle_mutated": False,
        "oms_mutated": False,
        "production_ledger_mutated": False,
        "risk_state_mutated": False,
        "kill_switch_mutated": False,
        "capital_authority_changed": False,
        "automatic_cancellation_enabled": False,
        "strategy_direct_cancellation_enabled": False,
        "ai_direct_cancellation_enabled": False,
        "cancellation_retry_enabled": False,
        "safety": controlled_broker_cancellation_safety_flags(),
    }
