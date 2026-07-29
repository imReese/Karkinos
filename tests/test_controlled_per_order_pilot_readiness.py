from __future__ import annotations

from copy import deepcopy

from server.services.controlled_per_order_pilot_readiness import (
    build_controlled_per_order_pilot_readiness,
)


def _sources() -> dict[str, object]:
    adapter_release = {
        "release_evidence_ref": "readonly-release-1",
        "manifest_fingerprint": "manifest-fingerprint-1",
        "provider": "reviewed-provider",
        "gateway_id": "gateway-1",
        "account_alias": "account-alias-1",
        "collector_id": "connector-1",
        "review_status": "accepted",
        "conformance_status": "clear",
        "conformance_run_id": "conformance-run-1",
        "collector_status": "recorded",
        "collector_run_id": "collector-run-1",
        "collector_updated_at": "2026-07-27T09:00:00+00:00",
        "status": "observing_readonly",
        "blockers": [],
        "does_not_authorize_provider_activation": True,
    }
    adapter = {
        "schema_version": "karkinos.broker_adapter_readiness.v1",
        "status": "observing_readonly",
        "releases": [adapter_release],
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
    }
    acceptance = {
        "status": "recorded_verified_owner_acceptance",
        "acceptance_id": "a" * 64,
        "recorded_at": "2026-07-27T10:00:00+00:00",
        "operator_identity_verified": True,
        "authorizes_execution": False,
    }
    soak = {
        "schema_version": "karkinos.broker_connector_soak_promotion_status.v1",
        "connector_count": 1,
        "connectors": [
            {
                "connector_id": "connector-1",
                "account_alias": "account-alias-1",
                "dossier_fingerprint": "soak-dossier-1",
                "promotion_ready": True,
                "promotion_blockers": [],
                "account_truth_reconciliation_linked": True,
                "acceptance": acceptance,
            }
        ],
        "runtime_execution_authority": "disabled",
        "broker_submission_enabled": False,
        "automatic_promotion_enabled": False,
        "safety": {
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
    }
    write_status = {
        "schema_version": "karkinos.controlled_broker_write_release_status.v1",
        "active_release_count": 1,
        "broker_contact_performed": False,
        "broker_submission_performed": False,
        "broker_cancellation_performed": False,
        "automatic_execution_allowed": False,
        "strategy_direct_submission_allowed": False,
        "authorizes_order_submission_by_itself": False,
        "does_not_grant_capital_authority": True,
    }
    write_release = {
        "schema_version": "karkinos.controlled_broker_write_release.v1",
        "status": "current_clear_signed_release",
        "release_evidence_id": "write-release-1",
        "evidence_fingerprint": "write-fingerprint-1",
        "provider": "reviewed-provider",
        "gateway_id": "gateway-1",
        "account_alias": "account-alias-1",
        "execution_edge_ref": "execution-edge-1",
        "readonly_release_evidence_ref": "readonly-release-1",
        "soak_acceptance_id": "a" * 64,
        "execution_mode": "manual_each_order",
        "effective_at": "2026-07-27T10:05:00+00:00",
        "revoked": False,
        "authorizes_order_submission_by_itself": False,
        "does_not_grant_capital_authority": True,
    }
    operator_view = {
        "schema_version": "karkinos.controlled_execution_operator_view.v4",
        "as_of": "2026-07-27T10:06:00+00:00",
        "source_blockers": [],
        "attention_order_journey_count": 0,
        "attention_queue_truncated": False,
        "current_window_session_count": 0,
        "blocked_current_session_count": 0,
        "latest_submission": None,
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
    }
    return {
        "broker_adapter_readiness": adapter,
        "broker_soak_promotion": soak,
        "broker_write_release_status": write_status,
        "broker_write_releases": [write_release],
        "controlled_execution_operator_view": operator_view,
    }


def _build(sources: dict[str, object] | None = None) -> dict[str, object]:
    values = sources or _sources()
    return build_controlled_per_order_pilot_readiness(**values)


def test_pilot_readiness_fails_closed_without_persisted_sources() -> None:
    readiness = build_controlled_per_order_pilot_readiness(
        broker_adapter_readiness=None,
        broker_soak_promotion=None,
        broker_write_release_status=None,
        broker_write_releases=None,
        controlled_execution_operator_view=None,
    )

    assert readiness["status"] == "blocked"
    assert readiness["blocked_gate_count"] == readiness["gate_count"]
    assert readiness["next_safe_action"] == ("review_pilot_readiness_source_contracts")
    assert readiness["provider_contacted"] is False
    assert readiness["database_writes_performed"] is False
    assert readiness["broker_submission_enabled"] is False
    assert readiness["broker_cancellation_enabled"] is False
    assert readiness["does_not_mutate_production_ledger"] is True
    assert readiness["does_not_mutate_capital_authority"] is True
    assert readiness["authorizes_execution"] is False


def test_pilot_readiness_allows_only_opening_an_exact_order_review() -> None:
    readiness = _build()

    assert readiness["status"] == "ready_for_exact_order_review"
    assert readiness["passed_gate_count"] == readiness["gate_count"] == 6
    assert readiness["blocked_gate_count"] == 0
    assert readiness["blockers"] == []
    assert readiness["next_safe_action"] == (
        "open_exact_order_review_without_submission"
    )
    assert readiness["release_scope"] == (
        "pilot_admission_prerequisites_not_v1_8_completion"
    )
    assert readiness["scope"] == {
        "provider": "reviewed-provider",
        "gateway_id": "gateway-1",
        "account_alias": "account-alias-1",
        "connector_id": "connector-1",
        "readonly_release_evidence_ref": "readonly-release-1",
        "write_release_evidence_id": "write-release-1",
    }
    assert len(readiness["required_next_order_gates"]) == 8
    assert readiness["authorizes_execution"] is False
    assert readiness["automatic_scale_up_enabled"] is False


def test_pilot_readiness_fingerprint_ignores_request_time_only_drift() -> None:
    sources = _sources()
    original = _build(sources)
    changed = deepcopy(sources)
    changed["broker_adapter_readiness"]["releases"][0][  # type: ignore[index]
        "collector_updated_at"
    ] = "2026-07-27T11:00:00+00:00"
    changed["controlled_execution_operator_view"]["as_of"] = (  # type: ignore[index]
        "2026-07-27T11:00:00+00:00"
    )

    later = _build(changed)

    assert later["observed_at"] != original["observed_at"]
    assert later["readiness_fingerprint"] == original["readiness_fingerprint"]


def test_pilot_readiness_blocks_exact_scope_drift() -> None:
    sources = _sources()
    sources["broker_write_releases"][0]["gateway_id"] = "other-gateway"  # type: ignore[index]

    readiness = _build(sources)

    assert readiness["status"] == "blocked"
    assert readiness["next_safe_action"] == "resolve_pilot_scope_drift"
    assert (
        "one_exact_provider_account_gateway_scope:pilot_scope_mismatch:gateway_id"
        in readiness["blockers"]
    )


def test_pilot_readiness_blocks_unfinished_journey_and_session_authority() -> None:
    sources = _sources()
    operator = sources["controlled_execution_operator_view"]
    operator["attention_order_journey_count"] = 1  # type: ignore[index]
    operator["current_window_session_count"] = 1  # type: ignore[index]
    operator["latest_submission"] = {  # type: ignore[index]
        "submit_intent_id": "intent-open",
        "order_id": "order-open",
    }

    readiness = _build(sources)

    assert readiness["status"] == "blocked"
    assert readiness["next_safe_action"] == "close_controlled_execution_attention"
    assert any(
        "unresolved_controlled_order_journey_present" in blocker
        for blocker in readiness["blockers"]
    )
    assert any(
        "session_authority_active_during_per_order_pilot" in blocker
        for blocker in readiness["blockers"]
    )


def test_pilot_readiness_rejects_unsafe_source_boundary() -> None:
    sources = _sources()
    sources["broker_adapter_readiness"]["provider_contacted"] = True  # type: ignore[index]

    readiness = _build(sources)

    assert readiness["status"] == "blocked"
    assert readiness["next_safe_action"] == ("review_pilot_readiness_source_contracts")
    assert any(
        "adapter_provider_contacted_boundary_invalid" in blocker
        for blocker in readiness["blockers"]
    )


def test_pilot_readiness_invalid_operator_counts_fail_closed() -> None:
    sources = _sources()
    operator = sources["controlled_execution_operator_view"]
    operator["attention_order_journey_count"] = "invalid"  # type: ignore[index]

    readiness = _build(sources)

    assert readiness["status"] == "blocked"
    assert any(
        "controlled_order_attention_count_invalid" in blocker
        for blocker in readiness["blockers"]
    )


def test_pilot_readiness_missing_operator_counts_fail_closed() -> None:
    sources = _sources()
    operator = sources["controlled_execution_operator_view"]
    operator.pop("attention_order_journey_count")  # type: ignore[union-attr]
    operator.pop("current_window_session_count")  # type: ignore[union-attr]
    operator.pop("blocked_current_session_count")  # type: ignore[union-attr]

    readiness = _build(sources)

    assert readiness["status"] == "blocked"
    assert {blocker.split(":", 1)[1] for blocker in readiness["blockers"]} >= {
        "controlled_order_attention_count_invalid",
        "current_runtime_session_count_invalid",
        "blocked_runtime_session_count_invalid",
    }


def test_pilot_readiness_carries_selected_adapter_blockers_forward() -> None:
    sources = _sources()
    release = sources["broker_adapter_readiness"]["releases"][0]  # type: ignore[index]
    release["blockers"] = ["collector_evidence_integrity_invalid"]

    readiness = _build(sources)

    assert readiness["status"] == "blocked"
    assert (
        "one_observing_readonly_adapter_release:collector_evidence_integrity_invalid"
        in readiness["blockers"]
    )


def test_pilot_readiness_rejects_runtime_query_on_read_path() -> None:
    sources = _sources()
    operator = sources["controlled_execution_operator_view"]
    operator["runtime_connector_query_performed"] = True  # type: ignore[index]

    readiness = _build(sources)

    assert readiness["status"] == "blocked"
    assert any(
        "operator_view_runtime_connector_query_performed_boundary_invalid" in blocker
        for blocker in readiness["blockers"]
    )
