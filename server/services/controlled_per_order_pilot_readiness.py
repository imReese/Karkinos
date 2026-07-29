"""Read-only rollout gate for one-provider, manual-each-order pilot review."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

CONTROLLED_PER_ORDER_PILOT_READINESS_SCHEMA_VERSION = (
    "karkinos.controlled_per_order_pilot_readiness.v1"
)

_ADAPTER_SCHEMA_VERSION = "karkinos.broker_adapter_readiness.v1"
_SOAK_SCHEMA_VERSION = "karkinos.broker_connector_soak_promotion_status.v1"
_WRITE_STATUS_SCHEMA_VERSION = "karkinos.controlled_broker_write_release_status.v1"
_WRITE_RELEASE_SCHEMA_VERSION = "karkinos.controlled_broker_write_release.v1"
_OPERATOR_VIEW_SCHEMA_VERSION = "karkinos.controlled_execution_operator_view.v4"


def build_controlled_per_order_pilot_readiness(
    *,
    broker_adapter_readiness: Mapping[str, Any] | None,
    broker_soak_promotion: Mapping[str, Any] | None,
    broker_write_release_status: Mapping[str, Any] | None,
    broker_write_releases: Iterable[Mapping[str, Any]] | None,
    controlled_execution_operator_view: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compose persisted evidence without granting order or capital authority."""

    adapter = _mapping(broker_adapter_readiness)
    soak = _mapping(broker_soak_promotion)
    write_status = _mapping(broker_write_release_status)
    write_releases = [_mapping(item) for item in broker_write_releases or ()]
    operator_view = _mapping(controlled_execution_operator_view)

    source_contract_blockers = _source_contract_blockers(
        adapter=adapter,
        soak=soak,
        write_status=write_status,
        operator_view=operator_view,
    )
    source_gate = _gate(
        key="persisted_source_contracts",
        blockers=source_contract_blockers,
        evidence_refs=[
            str(adapter.get("schema_version") or "adapter:missing"),
            str(soak.get("schema_version") or "soak:missing"),
            str(write_status.get("schema_version") or "write_release:missing"),
            str(operator_view.get("schema_version") or "operator_view:missing"),
        ],
        resolution_condition="restore_safe_persisted_only_source_contracts",
    )

    observing_releases = [
        item
        for item in _list_of_mappings(adapter.get("releases"))
        if item.get("status") == "observing_readonly"
    ]
    adapter_blockers: list[str] = []
    if source_contract_blockers:
        adapter_blockers.append("pilot_readiness_source_contract_blocked")
    if not observing_releases:
        adapter_blockers.append("readonly_adapter_release_missing")
    elif len(observing_releases) > 1:
        adapter_blockers.append("multiple_observing_readonly_adapter_releases")
    selected_adapter = observing_releases[0] if len(observing_releases) == 1 else {}
    if selected_adapter:
        adapter_blockers.extend(_list_of_strings(selected_adapter.get("blockers")))
        if selected_adapter.get("review_status") != "accepted":
            adapter_blockers.append("readonly_adapter_release_not_accepted")
        if selected_adapter.get("conformance_status") != "clear":
            adapter_blockers.append("readonly_adapter_conformance_not_clear")
        if selected_adapter.get("collector_status") not in {"recorded", "duplicate"}:
            adapter_blockers.append("readonly_collector_observation_missing")
        if selected_adapter.get("does_not_authorize_provider_activation") is not True:
            adapter_blockers.append("readonly_adapter_release_boundary_invalid")
    adapter_gate = _gate(
        key="one_observing_readonly_adapter_release",
        blockers=adapter_blockers,
        evidence_refs=_evidence_refs(
            selected_adapter,
            "release_evidence_ref",
            "manifest_fingerprint",
            "conformance_run_id",
            "collector_run_id",
        ),
        resolution_condition="accept_and_observe_one_exact_readonly_adapter_release",
    )

    connector_id = str(selected_adapter.get("collector_id") or "")
    soak_connectors = [
        item
        for item in _list_of_mappings(soak.get("connectors"))
        if connector_id and str(item.get("connector_id") or "") == connector_id
    ]
    soak_blockers: list[str] = []
    if not selected_adapter:
        soak_blockers.append("readonly_adapter_scope_unresolved")
    if selected_adapter and not soak_connectors:
        soak_blockers.append("matching_readonly_soak_promotion_missing")
    elif len(soak_connectors) > 1:
        soak_blockers.append("multiple_matching_readonly_soak_promotions")
    selected_soak = soak_connectors[0] if len(soak_connectors) == 1 else {}
    soak_acceptance = _mapping(selected_soak.get("acceptance"))
    if selected_soak:
        soak_blockers.extend(_list_of_strings(selected_soak.get("promotion_blockers")))
        if selected_soak.get("promotion_ready") is not True:
            soak_blockers.append("readonly_soak_promotion_not_ready")
        if selected_soak.get("account_truth_reconciliation_linked") is not True:
            soak_blockers.append("readonly_soak_account_truth_not_linked")
        if soak_acceptance.get("status") != "recorded_verified_owner_acceptance":
            soak_blockers.append("readonly_soak_owner_acceptance_missing")
        if soak_acceptance.get("operator_identity_verified") is not True:
            soak_blockers.append("readonly_soak_operator_identity_unverified")
        if soak_acceptance.get("authorizes_execution") is not False:
            soak_blockers.append("readonly_soak_acceptance_boundary_invalid")
    soak_gate = _gate(
        key="signed_readonly_soak_promotion",
        blockers=soak_blockers,
        evidence_refs=_evidence_refs(
            selected_soak,
            "dossier_fingerprint",
        )
        + _evidence_refs(soak_acceptance, "acceptance_id"),
        resolution_condition="complete_exact_scope_soak_and_record_owner_acceptance",
    )

    active_write_releases = [
        item
        for item in write_releases
        if item.get("status") == "current_clear_signed_release"
    ]
    write_blockers: list[str] = []
    if write_status.get("active_release_count") != len(active_write_releases):
        write_blockers.append("write_release_status_count_mismatch")
    if not active_write_releases:
        write_blockers.append("active_manual_each_order_write_release_missing")
    elif len(active_write_releases) > 1:
        write_blockers.append("multiple_active_write_releases")
    selected_write = active_write_releases[0] if len(active_write_releases) == 1 else {}
    if selected_write:
        if selected_write.get("schema_version") != _WRITE_RELEASE_SCHEMA_VERSION:
            write_blockers.append("write_release_schema_invalid")
        if selected_write.get("execution_mode") != "manual_each_order":
            write_blockers.append("write_release_execution_mode_invalid")
        if selected_write.get("authorizes_order_submission_by_itself") is not False:
            write_blockers.append("write_release_order_authority_boundary_invalid")
        if selected_write.get("does_not_grant_capital_authority") is not True:
            write_blockers.append("write_release_capital_authority_boundary_invalid")
        if selected_write.get("revoked") is not False:
            write_blockers.append("write_release_revoked")
    write_gate = _gate(
        key="one_active_manual_each_order_write_release",
        blockers=write_blockers,
        evidence_refs=_evidence_refs(
            selected_write,
            "release_evidence_id",
            "evidence_fingerprint",
            "execution_edge_ref",
        ),
        resolution_condition="issue_one_short_lived_exact_scope_write_release",
    )

    scope_blockers: list[str] = []
    if not selected_adapter or not selected_soak or not selected_write:
        scope_blockers.append("pilot_scope_evidence_incomplete")
    else:
        for field in ("provider", "gateway_id", "account_alias"):
            if str(selected_write.get(field) or "") != str(
                selected_adapter.get(field) or ""
            ):
                scope_blockers.append(f"pilot_scope_mismatch:{field}")
        if str(selected_write.get("readonly_release_evidence_ref") or "") != str(
            selected_adapter.get("release_evidence_ref") or ""
        ):
            scope_blockers.append("pilot_scope_mismatch:readonly_release")
        if str(selected_soak.get("connector_id") or "") != connector_id:
            scope_blockers.append("pilot_scope_mismatch:connector")
        if str(selected_soak.get("account_alias") or "") != str(
            selected_write.get("account_alias") or ""
        ):
            scope_blockers.append("pilot_scope_mismatch:soak_account")
        if str(selected_write.get("soak_acceptance_id") or "") != str(
            soak_acceptance.get("acceptance_id") or ""
        ):
            scope_blockers.append("pilot_scope_mismatch:soak_acceptance")
    scope = {
        "provider": str(selected_write.get("provider") or ""),
        "gateway_id": str(selected_write.get("gateway_id") or ""),
        "account_alias": str(selected_write.get("account_alias") or ""),
        "connector_id": connector_id,
        "readonly_release_evidence_ref": str(
            selected_write.get("readonly_release_evidence_ref") or ""
        ),
        "write_release_evidence_id": str(
            selected_write.get("release_evidence_id") or ""
        ),
    }
    scope_gate = _gate(
        key="one_exact_provider_account_gateway_scope",
        blockers=scope_blockers,
        evidence_refs=[value for value in scope.values() if value],
        resolution_condition="resolve_provider_account_gateway_connector_scope_drift",
    )

    journey_blockers = _list_of_strings(operator_view.get("source_blockers"))
    if any(
        blocker.startswith("operator_view_") for blocker in source_contract_blockers
    ):
        journey_blockers.append("controlled_operator_view_untrusted")
    attention_count = _nonnegative_int(
        operator_view.get("attention_order_journey_count")
    )
    current_session_count = _nonnegative_int(
        operator_view.get("current_window_session_count")
    )
    blocked_session_count = _nonnegative_int(
        operator_view.get("blocked_current_session_count")
    )
    if attention_count is None:
        journey_blockers.append("controlled_order_attention_count_invalid")
    elif attention_count != 0:
        journey_blockers.append("unresolved_controlled_order_journey_present")
    if operator_view.get("attention_queue_truncated") is True:
        journey_blockers.append("controlled_order_attention_queue_truncated")
    if current_session_count is None:
        journey_blockers.append("current_runtime_session_count_invalid")
    elif current_session_count != 0:
        journey_blockers.append("session_authority_active_during_per_order_pilot")
    if blocked_session_count is None:
        journey_blockers.append("blocked_runtime_session_count_invalid")
    elif blocked_session_count != 0:
        journey_blockers.append("blocked_runtime_session_present")
    journey_gate = _gate(
        key="no_unresolved_order_or_session_authority",
        blockers=journey_blockers,
        evidence_refs=_evidence_refs(
            _mapping(operator_view.get("latest_submission")),
            "submit_intent_id",
            "order_id",
        ),
        resolution_condition="close_controlled_journeys_and_remove_session_authority",
    )

    gates = [
        source_gate,
        adapter_gate,
        soak_gate,
        write_gate,
        scope_gate,
        journey_gate,
    ]
    blockers = [
        f"{gate['key']}:{blocker}" for gate in gates for blocker in gate["blockers"]
    ]
    ready = not blockers
    fingerprint_core = {
        "schema_version": CONTROLLED_PER_ORDER_PILOT_READINESS_SCHEMA_VERSION,
        "status": "ready_for_exact_order_review" if ready else "blocked",
        "scope": scope,
        "gates": gates,
        "required_next_order_gates": _required_next_order_gates(),
    }
    return {
        **fingerprint_core,
        "readiness_fingerprint": _fingerprint(fingerprint_core),
        "observed_at": _latest_evidence_time(
            selected_adapter,
            soak_acceptance,
            selected_write,
        ),
        "gate_count": len(gates),
        "passed_gate_count": sum(gate["status"] == "pass" for gate in gates),
        "blocked_gate_count": sum(gate["status"] == "blocked" for gate in gates),
        "blockers": blockers,
        "next_safe_action": _next_safe_action(gates),
        "release_scope": "pilot_admission_prerequisites_not_v1_8_completion",
        "persisted_facts_only": True,
        "read_only_projection": True,
        "provider_contacted": False,
        "database_writes_performed": False,
        "broker_submission_enabled": False,
        "broker_cancellation_enabled": False,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_mutate_risk_state": True,
        "does_not_mutate_kill_switch": True,
        "does_not_mutate_capital_authority": True,
        "authorizes_execution": False,
        "automatic_scale_up_enabled": False,
        "limitations": [
            "Ready means only that the owner may open a separate exact-order review.",
            "This projection does not prove the v1.8 release gate, real-provider legal approval, or a completed pilot.",
            "Every order still requires fresh Account Truth, Decision, risk, paper/shadow, capital, gateway, lifecycle, reconciliation, posting, and short-lived operator evidence.",
        ],
    }


def _source_contract_blockers(
    *,
    adapter: dict[str, Any],
    soak: dict[str, Any],
    write_status: dict[str, Any],
    operator_view: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    expected_schemas = (
        ("adapter", adapter, _ADAPTER_SCHEMA_VERSION),
        ("soak", soak, _SOAK_SCHEMA_VERSION),
        ("write_release", write_status, _WRITE_STATUS_SCHEMA_VERSION),
        ("operator_view", operator_view, _OPERATOR_VIEW_SCHEMA_VERSION),
    )
    for prefix, source, expected in expected_schemas:
        if source.get("schema_version") != expected:
            blockers.append(f"{prefix}_schema_invalid")
        if source.get("source_error"):
            blockers.append(f"{prefix}_source_failed")
    _append_boundary_blockers(
        blockers,
        prefix="adapter",
        source=adapter,
        expected={
            "persisted_facts_only": True,
            "provider_contacted": False,
            "adapter_registered": False,
            "broker_submission_enabled": False,
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
            "does_not_mutate_risk_state": True,
            "does_not_mutate_kill_switch": True,
            "does_not_mutate_capital_authority": True,
            "authorizes_execution": False,
        },
    )
    _append_boundary_blockers(
        blockers,
        prefix="soak",
        source=soak,
        expected={
            "broker_submission_enabled": False,
            "automatic_promotion_enabled": False,
        },
    )
    if soak.get("runtime_execution_authority") != "disabled":
        blockers.append("soak_runtime_authority_boundary_invalid")
    _append_boundary_blockers(
        blockers,
        prefix="soak_safety",
        source=_mapping(soak.get("safety")),
        expected={
            "does_not_grant_capital_authority": True,
            "does_not_issue_or_resume_runtime_authority": True,
            "does_not_contact_broker": True,
            "does_not_submit_broker_order": True,
            "does_not_cancel_broker_order": True,
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
            "does_not_reserve_or_consume_budget": True,
            "automatic_promotion_enabled": False,
        },
    )
    _append_boundary_blockers(
        blockers,
        prefix="write_status",
        source=write_status,
        expected={
            "broker_contact_performed": False,
            "broker_submission_performed": False,
            "broker_cancellation_performed": False,
            "automatic_execution_allowed": False,
            "strategy_direct_submission_allowed": False,
            "authorizes_order_submission_by_itself": False,
            "does_not_grant_capital_authority": True,
        },
    )
    _append_boundary_blockers(
        blockers,
        prefix="operator_view",
        source=operator_view,
        expected={
            "reads_persisted_facts_only": True,
            "provider_contact_performed": False,
            "runtime_connector_query_performed": False,
            "broker_submission_enabled": False,
            "broker_cancel_enabled": False,
            "authority_issue_enabled": False,
            "authority_renew_enabled": False,
            "authority_resume_enabled": False,
            "automatic_scale_up_enabled": False,
            "does_not_mutate_account_truth": True,
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
        },
    )
    return list(dict.fromkeys(blockers))


def _append_boundary_blockers(
    blockers: list[str],
    *,
    prefix: str,
    source: Mapping[str, Any],
    expected: Mapping[str, bool],
) -> None:
    for field, expected_value in expected.items():
        if source.get(field) is not expected_value:
            blockers.append(f"{prefix}_{field}_boundary_invalid")


def _gate(
    *,
    key: str,
    blockers: Iterable[str],
    evidence_refs: Iterable[str],
    resolution_condition: str,
) -> dict[str, Any]:
    unique_blockers = list(dict.fromkeys(str(item) for item in blockers if str(item)))
    return {
        "key": key,
        "status": "blocked" if unique_blockers else "pass",
        "blockers": unique_blockers,
        "evidence_refs": list(
            dict.fromkeys(str(item) for item in evidence_refs if str(item))
        ),
        "resolution_condition": resolution_condition,
        "manual_acknowledgement_clears_status": False,
    }


def _required_next_order_gates() -> list[str]:
    return [
        "canonical_manually_confirmed_oms_order",
        "fresh_account_truth_and_market_evidence",
        "matching_decision_risk_and_paper_shadow_evidence",
        "bounded_capital_evaluation_and_prior_batch_reconciliation",
        "current_gateway_health_and_exact_per_order_dossier",
        "fresh_offline_operator_signature",
        "single_persistent_external_effect_claim",
        "lifecycle_reconciliation_and_separate_ledger_posting",
    ]


def _next_safe_action(gates: list[dict[str, Any]]) -> str:
    actions = {
        "persisted_source_contracts": "review_pilot_readiness_source_contracts",
        "one_observing_readonly_adapter_release": "owner_select_and_review_real_broker_provider",
        "signed_readonly_soak_promotion": "complete_readonly_soak_and_signed_acceptance",
        "one_active_manual_each_order_write_release": "issue_short_lived_manual_each_order_write_release",
        "one_exact_provider_account_gateway_scope": "resolve_pilot_scope_drift",
        "no_unresolved_order_or_session_authority": "close_controlled_execution_attention",
    }
    blocked = next((gate for gate in gates if gate["status"] == "blocked"), None)
    return (
        actions[str(blocked["key"])]
        if blocked is not None
        else "open_exact_order_review_without_submission"
    )


def _latest_evidence_time(*sources: Mapping[str, Any]) -> str | None:
    values = [
        str(value)
        for source in sources
        for key in ("collector_updated_at", "recorded_at", "effective_at")
        if (value := source.get(key))
    ]
    return max(values) if values else None


def _evidence_refs(source: Mapping[str, Any], *keys: str) -> list[str]:
    return [str(source.get(key) or "") for key in keys if source.get(key)]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_mapping(item) for item in value if isinstance(item, Mapping)]


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "CONTROLLED_PER_ORDER_PILOT_READINESS_SCHEMA_VERSION",
    "build_controlled_per_order_pilot_readiness",
]
