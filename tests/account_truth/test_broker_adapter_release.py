from __future__ import annotations

import json
import sqlite3
from copy import deepcopy

import pytest

from account_truth.broker_adapter_release import (
    BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    BrokerAdapterReleaseRejected,
    BrokerAdapterReleaseReviewRepository,
    preview_broker_adapter_release_manifest,
)

REVIEWED_AT = "2026-07-15T08:00:00+00:00"


def release_manifest() -> dict:
    return {
        "schema_version": "karkinos.broker_adapter_release_manifest.v1",
        "release_evidence_ref": "fixture-release-reviewed-v1",
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


def preview_manifest(payload: dict | None = None) -> dict:
    return preview_broker_adapter_release_manifest(
        json.dumps(payload or release_manifest()),
        source_name="deterministic adapter release fixture",
    )


def accept_release(
    repository: BrokerAdapterReleaseReviewRepository,
    *,
    preview: dict | None = None,
    review_id: str = "fixture-release-review-accepted-v1",
) -> dict:
    return repository.record_review(
        preview or preview_manifest(),
        review_id=review_id,
        decision="accepted",
        reviewer_ref="fixture-human-reviewer",
        reviewed_at=REVIEWED_AT,
        reason_ref="fixture-review-approved",
        acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    )


def collector_binding(**overrides: object) -> dict:
    value = {
        "release_evidence_ref": "fixture-release-reviewed-v1",
        "collector_id": "deterministic-fixture-collector",
        "deployment_id": "fixture-deployment-1",
        "collector_version": "fixture-v1",
        "deployment_fingerprint": "d" * 64,
        "provider": "deterministic_fixture",
        "gateway_id": "fixture-gateway-1",
        "account_alias": "fixture-account",
        "adapter_authorization_ref": "test-only-user-authorization",
        "collection_mode": "callback",
    }
    value.update(overrides)
    return value


def test_manifest_preview_is_provider_neutral_readonly_and_default_closed() -> None:
    preview = preview_manifest()

    assert preview["validation_status"] == "pass"
    assert preview["recordable"] is True
    assert preview["provider"] == "deterministic_fixture"
    assert preview["provider_contacted"] is False
    assert preview["adapter_registered"] is False
    assert preview["default_registered"] is False
    assert preview["broker_submission_enabled"] is False
    assert preview["does_not_submit_broker_order"] is True
    assert preview["does_not_cancel_broker_order"] is True
    assert preview["does_not_mutate_oms"] is True
    assert preview["does_not_mutate_production_ledger"] is True
    assert preview["does_not_mutate_risk_state"] is True
    assert preview["does_not_mutate_kill_switch"] is True
    assert preview["does_not_mutate_capital_authority"] is True


def test_write_capability_boundary_violation_and_auth_material_fail_closed() -> None:
    writable = release_manifest()
    writable["capabilities"]["can_submit_orders"] = True
    writable_preview = preview_manifest(writable)
    contains_auth_material = release_manifest()
    contains_auth_material["api_token"] = "must-not-enter-evidence"
    auth_preview = preview_manifest(contains_auth_material)

    assert writable_preview["validation_status"] == "blocked"
    assert "broker_adapter_release_write_capability_present" in (
        writable_preview["blockers"]
    )
    assert auth_preview["recordable"] is False
    assert "broker_adapter_release_auth_material_not_allowed" in (
        auth_preview["record_blockers"]
    )
    assert "must-not-enter-evidence" not in json.dumps(auth_preview)


def test_acceptance_is_explicit_idempotent_and_restart_verifiable(tmp_path) -> None:
    db_path = tmp_path / "release-review.db"
    repository = BrokerAdapterReleaseReviewRepository(db_path)
    preview = preview_manifest()

    accepted = accept_release(repository, preview=preview)
    replayed = accept_release(repository, preview=preview)
    restarted = BrokerAdapterReleaseReviewRepository(db_path, ensure_schema=False)
    verification = restarted.verify_collector_binding(collector_binding())

    assert accepted["status"] == "accepted"
    assert accepted["persisted"] is True
    assert accepted["adapter_registered"] is False
    assert accepted["authorizes_execution"] is False
    assert replayed["review_id"] == accepted["review_id"]
    assert replayed["reused"] is True
    assert verification["status"] == "clear"
    assert verification["review_id"] == accepted["review_id"]
    assert verification["blockers"] == []


@pytest.mark.parametrize(
    ("field", "value", "expected_blocker"),
    [
        (
            "deployment_fingerprint",
            "e" * 64,
            "broker_adapter_release_manifest_drift:deployment_fingerprint",
        ),
        (
            "adapter_authorization_ref",
            "different-human-authorization",
            "broker_adapter_release_manifest_drift:adapter_authorization_ref",
        ),
        (
            "collection_mode",
            "replay",
            None,
        ),
    ],
)
def test_exact_binding_drift_blocks_live_collection(
    tmp_path,
    field: str,
    value: str,
    expected_blocker: str | None,
) -> None:
    repository = BrokerAdapterReleaseReviewRepository(tmp_path / "review.db")
    accept_release(repository)

    verification = repository.verify_collector_binding(
        collector_binding(**{field: value})
    )

    if expected_blocker is None:
        assert verification["status"] == "not_required"
        assert verification["blockers"] == []
    else:
        assert verification["status"] == "blocked"
        assert expected_blocker in verification["blockers"]


def test_rejection_and_revocation_are_append_only_and_fail_closed(tmp_path) -> None:
    db_path = tmp_path / "review.db"
    repository = BrokerAdapterReleaseReviewRepository(db_path)
    preview = preview_manifest()
    accepted = accept_release(repository, preview=preview)
    revoked = repository.record_review(
        preview,
        review_id="fixture-release-review-revoked-v1",
        decision="revoked",
        reviewer_ref="fixture-human-reviewer",
        reviewed_at="2026-07-15T09:00:00+00:00",
        reason_ref="fixture-release-disabled",
        acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    )
    verification = repository.verify_collector_binding(collector_binding())

    assert accepted["status"] == "accepted"
    assert revoked["status"] == "revoked"
    assert verification["status"] == "blocked"
    assert verification["blockers"] == ["broker_adapter_release_review_not_accepted"]
    with pytest.raises(BrokerAdapterReleaseRejected) as resumed:
        accept_release(
            repository,
            preview=preview,
            review_id="fixture-release-review-illegal-resume",
        )
    assert "broker_adapter_release_revoked_requires_new_release" in (
        resumed.value.evidence["blockers"]
    )

    with sqlite3.connect(db_path) as conn:
        decisions = [str(row[0]) for row in conn.execute("""
                SELECT decision FROM broker_adapter_release_review_events
                ORDER BY id
                """).fetchall()]
    assert decisions == ["accepted", "revoked"]


def test_review_event_tampering_blocks_collector_binding(tmp_path) -> None:
    db_path = tmp_path / "review.db"
    repository = BrokerAdapterReleaseReviewRepository(db_path)
    preview = preview_manifest()
    accept_release(repository, preview=preview)
    repository.record_review(
        preview,
        review_id="fixture-release-review-revoked-for-tamper-test",
        decision="revoked",
        reviewer_ref="fixture-human-reviewer",
        reviewed_at="2026-07-15T09:00:00+00:00",
        reason_ref="fixture-release-disabled",
        acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            UPDATE broker_adapter_release_review_events SET decision = 'accepted'
            WHERE review_id = 'fixture-release-review-revoked-for-tamper-test'
            """)
        conn.commit()

    verification = repository.verify_collector_binding(collector_binding())

    assert verification["status"] == "blocked"
    assert "broker_adapter_release_review_integrity_invalid" in (
        verification["blockers"]
    )


def test_preview_drift_and_wrong_acknowledgement_are_rejected(tmp_path) -> None:
    repository = BrokerAdapterReleaseReviewRepository(tmp_path / "review.db")
    preview = preview_manifest()
    drifted = deepcopy(preview)
    drifted["deployment_id"] = "different-deployment"

    with pytest.raises(BrokerAdapterReleaseRejected) as wrong_ack:
        repository.record_review(
            preview,
            review_id="fixture-review-wrong-ack",
            decision="accepted",
            reviewer_ref="fixture-human-reviewer",
            reviewed_at=REVIEWED_AT,
            reason_ref="fixture-review-approved",
            acknowledgement="",
        )
    with pytest.raises(BrokerAdapterReleaseRejected) as integrity:
        repository.record_review(
            drifted,
            review_id="fixture-review-drifted",
            decision="accepted",
            reviewer_ref="fixture-human-reviewer",
            reviewed_at=REVIEWED_AT,
            reason_ref="fixture-review-approved",
            acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
        )

    assert "broker_adapter_release_review_acknowledgement_mismatch" in (
        wrong_ack.value.evidence["blockers"]
    )
    assert "broker_adapter_release_preview_fingerprint_drift" in (
        integrity.value.evidence["blockers"]
    )


def test_semantic_blockers_cannot_be_removed_before_acceptance(tmp_path) -> None:
    repository = BrokerAdapterReleaseReviewRepository(tmp_path / "review.db")
    writable = release_manifest()
    writable["capabilities"]["can_submit_orders"] = True
    tampered_preview = preview_manifest(writable)
    tampered_preview["blockers"] = []
    tampered_preview["validation_status"] = "pass"

    with pytest.raises(BrokerAdapterReleaseRejected) as integrity:
        accept_release(repository, preview=tampered_preview)

    assert "broker_adapter_release_preview_validation_drift:blockers" in (
        integrity.value.evidence["blockers"]
    )
    assert "broker_adapter_release_preview_validation_drift:validation_status" in (
        integrity.value.evidence["blockers"]
    )


def test_read_only_status_does_not_create_absent_database(tmp_path) -> None:
    db_path = tmp_path / "absent.db"
    repository = BrokerAdapterReleaseReviewRepository(db_path, ensure_schema=False)

    status = repository.get_status("fixture-release-reviewed-v1")
    verification = repository.verify_collector_binding(collector_binding())

    assert status["status"] == "not_configured"
    assert verification["status"] == "blocked"
    assert verification["blockers"] == ["broker_adapter_release_review_not_found"]
    assert db_path.exists() is False


def test_release_review_tables_cannot_mutate_trading_domains(tmp_path) -> None:
    db_path = tmp_path / "release-review.db"
    repository = BrokerAdapterReleaseReviewRepository(db_path)
    accept_release(repository)

    with sqlite3.connect(db_path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "broker_adapter_release_manifests" in tables
    assert "broker_adapter_release_review_events" in tables
    assert "oms_orders" not in tables
    assert "fills" not in tables
    assert "ledger_entries" not in tables
    assert "risk_decisions" not in tables
    assert "capital_authorizations" not in tables
