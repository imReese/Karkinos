from __future__ import annotations

from typing import Any


def clear_current_per_order_confirmation(
    order_id: str,
    *,
    confirmation_id: str = "c" * 64,
    dossier_fingerprint: str = "d" * 64,
) -> dict[str, Any]:
    gates = {
        "account_truth": _gate(
            evidence_ref="account-truth:1",
            source_identifier="1",
            source_fingerprint="a" * 64,
            source_recorded_at="2026-07-02T08:00:00+00:00",
        ),
        "research_evidence": _gate(
            evidence_ref="research:1",
            source_identifier="1",
            source_fingerprint="b" * 64,
            source_recorded_at="2026-07-02T08:01:00+00:00",
        ),
        "risk": _gate(
            evidence_ref="risk:risk-001",
            source_identifier="risk-001",
            source_fingerprint="c" * 64,
            source_recorded_at="2026-07-02T08:02:00+00:00",
        ),
        "paper_shadow": _gate(
            evidence_ref="paper_shadow:run-001",
            source_identifier="run-001",
            source_fingerprint="d" * 64,
            source_recorded_at="2026-07-02T08:03:00+00:00",
        ),
    }
    current_dossier = {
        "schema_version": "karkinos.current_per_order_confirmation_dossier.v1",
        "dossier_fingerprint": dossier_fingerprint,
        "review_status": "review_ready_non_submitting",
        "review_ready": True,
        "review_blockers": [],
        "gateway_gates": {
            "schema_version": "karkinos.per_order_gateway_gate_summary.v2",
            "status": "pass",
            "gates": gates,
            "blockers": [],
            "persisted_facts_only": True,
            "provider_contact_performed": False,
            "authorizes_execution": False,
        },
        "capital_evaluation": {
            "status": "pass",
            "input_fingerprint": "e" * 64,
            "mode": "manual_each_order",
            "does_not_enable_execution": True,
        },
        "submission_status": "blocked",
        "authorizes_execution": False,
    }
    return {
        "schema_version": "karkinos.current_per_order_confirmation_resolution.v1",
        "status": "current_verified_non_authorizing_confirmation",
        "confirmation_id": confirmation_id,
        "order_id": order_id,
        "dossier_fingerprint": dossier_fingerprint,
        "capital_evaluation_input_fingerprint": "e" * 64,
        "prior_batch_reconciliation_fingerprint": "f" * 64,
        "execution_gateway_verification_fingerprint": "1" * 64,
        "operator_id": "local-owner",
        "operator_approval_id": "2" * 64,
        "current_dossier": current_dossier,
        "expected_foundation_blockers": [
            "broker_submission_disabled",
            "live_gateway_not_implemented",
            "operator_identity_unverified",
            "runtime_execution_authority_disabled",
        ],
        "unexpected_hard_blockers": [],
        "blockers": [],
        "reads_persisted_facts_only": True,
        "provider_contact_performed": False,
        "runtime_connector_query_performed": False,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_mutate_risk": True,
        "does_not_mutate_kill_switch": True,
        "does_not_change_capital_authority": True,
        "broker_submission_enabled": False,
        "broker_cancel_enabled": False,
        "authorizes_execution": False,
    }


def _gate(
    *,
    evidence_ref: str,
    source_identifier: str,
    source_fingerprint: str,
    source_recorded_at: str,
) -> dict[str, Any]:
    return {
        "status": "pass",
        "raw_status": "pass",
        "evidence_ref": evidence_ref,
        "source_kind": evidence_ref.partition(":")[0],
        "source_identifier": source_identifier,
        "source_fingerprint": source_fingerprint,
        "source_recorded_at": source_recorded_at,
        "resolution_status": "resolved_clear",
        "blockers": [],
    }
