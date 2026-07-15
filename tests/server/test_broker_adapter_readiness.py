from __future__ import annotations

import json

from account_truth.broker_adapter_conformance import (
    BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
    BrokerAdapterConformanceRepository,
)
from account_truth.broker_adapter_conformance_fixtures import (
    run_deterministic_broker_adapter_conformance,
)
from account_truth.broker_adapter_release import (
    BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    BrokerAdapterReleaseReviewRepository,
    preview_broker_adapter_release_manifest,
)
from server.services.broker_adapter_readiness import BrokerAdapterReadinessService


def _manifest() -> dict:
    return {
        "schema_version": "karkinos.broker_adapter_release_manifest.v1",
        "release_evidence_ref": "fixture-readiness-release-v1",
        "collector_id": "deterministic-fixture-collector",
        "deployment_id": "fixture-deployment-1",
        "collector_version": "fixture-v1",
        "deployment_fingerprint": "d" * 64,
        "provider": "deterministic_fixture",
        "gateway_id": "fixture-gateway-1",
        "account_alias": "fixture-account",
        "adapter_authorization_ref": "test-only-user-authorization",
        "collection_modes": ["callback", "poll"],
        "capabilities": {
            "can_read_account": False,
            "can_read_cash": False,
            "can_read_positions": False,
            "can_read_orders": True,
            "can_read_fills": True,
            "can_read_market_session": False,
            "can_read_heartbeat": True,
            "can_submit_orders": False,
            "can_cancel_orders": False,
        },
        "boundaries": {
            "runtime_auth_material_external": True,
            "strategy_imports_adapter": False,
            "ai_imports_adapter": False,
            "core_imports_provider_sdk": False,
            "writes_oms": False,
            "writes_production_ledger": False,
            "writes_risk_state": False,
            "writes_kill_switch": False,
            "writes_capital_authority": False,
            "default_registered": False,
        },
        "review_refs": {
            "adapter_adr": "fixture-adr-v1",
            "capability_matrix": "fixture-capability-matrix-v1",
            "threat_model": "fixture-threat-model-v1",
            "deployment_runbook": "fixture-deployment-runbook-v1",
            "rollback_runbook": "fixture-rollback-runbook-v1",
            "privacy_review": "fixture-privacy-review-v1",
        },
        "limitations": [
            "Deterministic fixture only; no broker or provider is contacted."
        ],
    }


def _accept_release(db_path, *, review_id: str = "readiness-review-v1") -> dict:
    preview = preview_broker_adapter_release_manifest(
        json.dumps(_manifest()),
        source_name="deterministic readiness fixture",
    )
    conformance = run_deterministic_broker_adapter_conformance(
        preview,
        run_id=f"{review_id}-conformance",
    )
    BrokerAdapterConformanceRepository(db_path).record_report(
        conformance,
        acknowledgement=BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
    )
    return BrokerAdapterReleaseReviewRepository(db_path).record_review(
        preview,
        review_id=review_id,
        decision="accepted",
        reviewer_ref="fixture-human-reviewer",
        reviewed_at="2026-07-15T08:00:00+00:00",
        reason_ref="fixture-review-approved",
        acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    )


def test_readiness_without_persisted_release_is_neutral_and_does_not_create_db(
    tmp_path,
) -> None:
    db_path = tmp_path / "absent.db"

    projection = BrokerAdapterReadinessService(db_path).project()

    assert projection["status"] == "not_configured"
    assert projection["subsystem_status"] == "skipped"
    assert projection["configured_release_count"] == 0
    assert projection["latest_release"] is None
    assert projection["provider_contacted"] is False
    assert projection["adapter_registered"] is False
    assert projection["broker_submission_enabled"] is False
    assert projection["authorizes_execution"] is False
    assert not db_path.exists()


def test_accepted_evidence_is_visible_but_does_not_activate_provider(tmp_path) -> None:
    db_path = tmp_path / "readiness.db"
    _accept_release(db_path)

    projection = BrokerAdapterReadinessService(db_path).project()

    assert projection["status"] == "evidence_ready_not_activated"
    assert projection["subsystem_status"] == "skipped"
    assert projection["accepted_release_count"] == 1
    assert projection["blocked_release_count"] == 0
    latest = projection["latest_release"]
    assert latest["provider"] == "deterministic_fixture"
    assert latest["review_status"] == "accepted"
    assert latest["conformance_status"] == "clear"
    assert latest["collector_status"] == "not_started"
    assert latest["status"] == "evidence_ready_not_activated"
    assert latest["does_not_authorize_provider_activation"] is True
    assert projection["provider_contacted"] is False
    assert projection["adapter_registered"] is False
    assert projection["default_registered"] is False
    assert projection["does_not_mutate_oms"] is True
    assert projection["does_not_mutate_production_ledger"] is True
    assert projection["does_not_mutate_risk_state"] is True
    assert projection["does_not_mutate_kill_switch"] is True
    assert projection["does_not_mutate_capital_authority"] is True


def test_newer_conformance_evidence_requires_a_new_human_review(tmp_path) -> None:
    db_path = tmp_path / "drift.db"
    _accept_release(db_path)
    preview = preview_broker_adapter_release_manifest(json.dumps(_manifest()))
    newer = run_deterministic_broker_adapter_conformance(
        preview,
        run_id="readiness-conformance-newer-pass",
    )
    BrokerAdapterConformanceRepository(db_path).record_report(
        newer,
        acknowledgement=BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
    )

    projection = BrokerAdapterReadinessService(db_path).project()

    assert projection["status"] == "evidence_attention_required"
    assert projection["subsystem_status"] == "degraded"
    assert projection["blocked_release_count"] == 1
    assert projection["latest_release"]["status"] == "blocked"
    assert "broker_adapter_release_conformance_review_drift" in projection["blockers"]
    assert projection["broker_submission_enabled"] is False
    assert projection["authorizes_execution"] is False
