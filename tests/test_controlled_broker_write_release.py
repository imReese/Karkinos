from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from account_truth.broker_execution_edge_conformance import (
    BROKER_EXECUTION_EDGE_CONFORMANCE_ACKNOWLEDGEMENT,
    BROKER_EXECUTION_EDGE_CONFORMANCE_RESULT_SCHEMA_VERSION,
    BROKER_EXECUTION_EDGE_MANIFEST_SCHEMA_VERSION,
    BrokerExecutionEdgeConformanceRepository,
    preview_broker_execution_edge_conformance_result,
    preview_broker_execution_edge_manifest,
)
from account_truth.broker_execution_edge_conformance_fixtures import (
    run_deterministic_broker_execution_edge_conformance,
)
from server.config import TrustedOperatorIdentityConfig
from server.db import AppDatabase
from server.services.broker_adapter_readiness import build_broker_adapter_readiness
from server.services.controlled_broker_write_release import (
    CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_ACKNOWLEDGEMENT,
    ControlledBrokerWriteReleaseRejected,
    ControlledBrokerWriteReleaseService,
)
from server.services.operator_approval import OperatorApprovalService
from tests.test_per_order_confirmation import _record_observing_adapter_release

NOW = datetime(2026, 7, 18, 2, 15, tzinfo=timezone.utc)
READONLY_RELEASE_REF = "fixture-per-order-adapter-release-v1"
CONNECTOR_ID = "fixture-readonly-confirmation"
GATEWAY_ID = "fixture-execution-disabled"
ACCOUNT_ALIAS = "fixture-review"
PROVIDER = "deterministic_fixture"
SOAK_ACCEPTANCE_ID = "b" * 64


def _identity(private_key: Ed25519PrivateKey) -> TrustedOperatorIdentityConfig:
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return TrustedOperatorIdentityConfig(
        operator_id="local-owner",
        key_id="write-release-key-1",
        algorithm="ed25519",
        public_key_base64=base64.b64encode(public_bytes).decode("ascii"),
        enabled=True,
    )


def _manifest() -> dict:
    return {
        "schema_version": BROKER_EXECUTION_EDGE_MANIFEST_SCHEMA_VERSION,
        "execution_edge_ref": "fixture-reviewed-write-edge-v1",
        "adapter_ref": "fixture-reviewed-write-adapter",
        "adapter_version": "fixture-v1",
        "provider": PROVIDER,
        "gateway_id": GATEWAY_ID,
        "account_alias": ACCOUNT_ALIAS,
        "deployment_fingerprint": "a" * 64,
        "capabilities": {
            "can_dry_run_orders": True,
            "can_submit_orders": True,
            "can_query_orders": True,
            "can_cancel_orders": True,
            "supports_idempotent_client_order_id": True,
        },
        "boundaries": {
            "runtime_auth_material_external": True,
            "default_registered": False,
            "production_enabled": False,
            "strategy_imports_adapter": False,
            "ai_imports_adapter": False,
            "core_imports_provider_sdk": False,
            "writes_oms": False,
            "writes_production_ledger": False,
            "writes_risk_state": False,
            "writes_kill_switch": False,
            "writes_capital_authority": False,
        },
        "review_refs": {
            "write_adapter_adr": "fixture-write-adapter-adr",
            "capability_matrix": "fixture-write-capability-matrix",
            "threat_model": "fixture-write-threat-model",
            "deployment_runbook": "fixture-write-deployment-runbook",
            "rollback_runbook": "fixture-write-rollback-runbook",
            "incident_runbook": "fixture-write-incident-runbook",
            "privacy_review": "fixture-write-privacy-review",
        },
        "limitations": ["Deterministic write-release fixture only."],
    }


def _owner_review_refs() -> dict[str, str]:
    return {
        "broker_agreement_review": "review:broker-agreement-v1",
        "account_permissions_review": "review:account-permissions-v1",
        "program_trading_reporting_review": "review:program-reporting-v1",
        "provider_acceptance_test_report": "review:provider-acceptance-v1",
        "deployment_authorization": "review:deployment-authorization-v1",
        "risk_controls_review": "review:risk-controls-v1",
        "rollback_drill_review": "review:rollback-drill-v1",
    }


def _soak_promotion() -> dict:
    return {
        "connector_id": CONNECTOR_ID,
        "account_alias": ACCOUNT_ALIAS,
        "dossier_fingerprint": "c" * 64,
        "promotion_ready": True,
        "promotion_blockers": [],
        "acceptance": {
            "status": "recorded_verified_owner_acceptance",
            "acceptance_id": SOAK_ACCEPTANCE_ID,
            "operator_identity_verified": True,
            "authorizes_execution": False,
        },
        "operational_evidence": {"source_fingerprint": "d" * 64},
        "account_truth_evidence": {"source_fingerprint": "e" * 64},
        "account_truth_reconciliation_linked": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
    }


def _record_execution_edge_conformance(
    db: AppDatabase, *, failed: bool = False
) -> None:
    manifest = preview_broker_execution_edge_manifest(_canonical_json(_manifest()))
    preview = run_deterministic_broker_execution_edge_conformance(
        manifest,
        run_id=(
            "fixture-write-edge-conformance-failed"
            if failed
            else "fixture-write-edge-conformance-v1"
        ),
    )
    if failed:
        payload = {
            "schema_version": BROKER_EXECUTION_EDGE_CONFORMANCE_RESULT_SCHEMA_VERSION,
            "run_id": preview["run_id"],
            "execution_edge_ref": preview["execution_edge_ref"],
            "manifest_fingerprint": preview["manifest_fingerprint"],
            "suite_version": preview["suite_version"],
            "fixture_kind": preview["fixture_kind"],
            "scenarios": deepcopy(preview["scenarios"]),
            "provider_contacted": False,
            "adapter_registered": False,
            "production_broker_contacted": False,
            "real_order_side_effect_count": 0,
        }
        payload["scenarios"][0]["observed_status"] = "unexpected"
        preview = preview_broker_execution_edge_conformance_result(payload)
    BrokerExecutionEdgeConformanceRepository(db._path).record_report(
        preview,
        acknowledgement=BROKER_EXECUTION_EDGE_CONFORMANCE_ACKNOWLEDGEMENT,
    )


def _environment(tmp_path) -> dict:
    db = AppDatabase(tmp_path / "controlled-write-release.db")
    db.init_sync()
    _record_observing_adapter_release(db, NOW)
    _record_execution_edge_conformance(db)
    private_key = Ed25519PrivateKey.generate()
    identity = _identity(private_key)
    soak = [_soak_promotion()]
    service = ControlledBrokerWriteReleaseService(
        db=db,
        trusted_operator_identities=[identity],
        soak_promotion_provider=lambda connector_id: (
            soak[0] if connector_id == CONNECTOR_ID else {}
        ),
        clock=lambda: NOW,
    )
    return {
        "db": db,
        "private_key": private_key,
        "identity": identity,
        "soak": soak,
        "service": service,
    }


def _dossier_request() -> dict:
    return {
        "execution_edge_manifest": _manifest(),
        "readonly_release_evidence_ref": READONLY_RELEASE_REF,
        "soak_acceptance_id": SOAK_ACCEPTANCE_ID,
        "effective_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=8)).isoformat(),
        "owner_review_refs": _owner_review_refs(),
    }


def _approval(env: dict, *, action: str, artifact_type: str, fingerprint: str):
    approval_service = OperatorApprovalService(
        db=env["db"],
        trusted_identities=[env["identity"]],
        clock=lambda: NOW,
        nonce_factory=lambda: "write-release-deterministic-nonce-000000001",
    )
    challenge = approval_service.create_challenge(
        operator_id="local-owner",
        key_id="write-release-key-1",
        action=action,
        artifact_type=artifact_type,
        artifact_fingerprint=fingerprint,
        ttl_seconds=180,
    )
    signature = env["private_key"].sign(
        base64.b64decode(challenge["signing_payload_base64"])
    )
    signature_base64 = base64.b64encode(signature).decode("ascii")
    approval = approval_service.verify_signature(
        challenge_id=challenge["challenge_id"],
        signature_base64=signature_base64,
    )
    return approval, signature_base64


def _issue(env: dict) -> dict:
    request = _dossier_request()
    dossier = env["service"].preview_dossier(**request)
    approval, signature = _approval(
        env,
        action="issue_controlled_broker_write_release",
        artifact_type="controlled_broker_write_release_dossier",
        fingerprint=dossier["dossier_fingerprint"],
    )
    return env["service"].record_release(
        **request,
        dossier_fingerprint=dossier["dossier_fingerprint"],
        operator_label="local-owner",
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=signature,
        acknowledgement=CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT,
    )


def test_signed_release_binds_all_sources_and_resolves_production_contract(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    request = _dossier_request()

    dossier = env["service"].preview_dossier(**request)
    recorded = _issue(env)
    resolved = env["service"].resolve_release_evidence(recorded["release_evidence_id"])
    status = env["service"].get_status()

    assert dossier["review_ready"] is True
    assert dossier["review_blockers"] == []
    assert dossier["scope"] == {
        "provider": PROVIDER,
        "gateway_id": GATEWAY_ID,
        "account_alias": ACCOUNT_ALIAS,
        "connector_id": CONNECTOR_ID,
    }
    assert recorded["status"] == "recorded_expiring_manual_each_order_release"
    assert recorded["operator_identity_verified"] is True
    assert resolved["status"] == "current_clear_signed_release"
    assert resolved["operator_identity_verified"] is True
    assert resolved["execution_mode"] == "manual_each_order"
    assert resolved["broker_agreement_reviewed"] is True
    assert resolved["connector_tested"] is True
    assert resolved["program_trading_reporting_reviewed"] is True
    assert resolved["risk_controls_reviewed"] is True
    assert resolved["authorizes_order_submission_by_itself"] is False
    assert resolved["does_not_grant_capital_authority"] is True
    assert resolved["provider_contact_performed"] is False
    assert status["active_release_count"] == 1
    assert env["db"].list_oms_orders_sync() == []
    assert env["db"].list_fills_sync() == []


def test_status_and_resolution_do_not_create_authority_schema(tmp_path) -> None:
    db = AppDatabase(tmp_path / "read-only-status.db")
    db.init_sync()
    service = ControlledBrokerWriteReleaseService(db=db, clock=lambda: NOW)

    status = service.get_status()
    missing = service.resolve_release_evidence("9" * 64)
    with sqlite3.connect(db._path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert status["active_release_count"] == 0
    assert status["default_registered"] is False
    assert missing["status"] == "blocked"
    assert "controlled_broker_write_releases" not in tables
    assert "controlled_broker_write_release_revocations" not in tables


def test_exact_issue_retry_is_idempotent_but_second_live_scope_is_blocked(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    first = _issue(env)
    request = _dossier_request()
    dossier = env["service"].preview_dossier(**request)
    approval, signature = _approval(
        env,
        action="issue_controlled_broker_write_release",
        artifact_type="controlled_broker_write_release_dossier",
        fingerprint=dossier["dossier_fingerprint"],
    )

    replay = env["service"].record_release(
        **request,
        dossier_fingerprint=dossier["dossier_fingerprint"],
        operator_label="local-owner",
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=signature,
        acknowledgement=CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT,
    )

    assert replay["release_evidence_id"] == first["release_evidence_id"]
    assert replay["reused"] is True

    changed = deepcopy(request)
    changed["execution_edge_manifest"]["deployment_fingerprint"] = "f" * 64
    changed_preview = env["service"].preview_dossier(**changed)
    approval, signature = _approval(
        env,
        action="issue_controlled_broker_write_release",
        artifact_type="controlled_broker_write_release_dossier",
        fingerprint=changed_preview["dossier_fingerprint"],
    )
    with pytest.raises(ControlledBrokerWriteReleaseRejected) as exc:
        env["service"].record_release(
            **changed,
            dossier_fingerprint=changed_preview["dossier_fingerprint"],
            operator_label="local-owner",
            operator_approval_id=approval["approval_id"],
            operator_proof_signature_base64=signature,
            acknowledgement=CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT,
        )
    assert (
        "controlled_broker_write_release_conformance_not_clear"
        in exc.value.evidence["blockers"]
    )


def test_source_drift_expiry_and_key_rotation_fail_closed(tmp_path) -> None:
    env = _environment(tmp_path)
    recorded = _issue(env)
    release_id = recorded["release_evidence_id"]

    env["soak"][0] = {
        **env["soak"][0],
        "promotion_ready": False,
        "promotion_blockers": ["newer_soak_failure"],
    }
    drifted = env["service"].resolve_release_evidence(release_id)
    assert drifted["status"] == "blocked"
    assert "newer_soak_failure" in drifted["blockers"]

    env["soak"][0] = _soak_promotion()
    rotated = Ed25519PrivateKey.generate()
    rotated_service = ControlledBrokerWriteReleaseService(
        db=env["db"],
        trusted_operator_identities=[_identity(rotated)],
        soak_promotion_provider=lambda _: _soak_promotion(),
        clock=lambda: NOW,
    )
    assert "controlled_broker_write_release_operator_key_changed" in (
        rotated_service.resolve_release_evidence(release_id)["blockers"]
    )

    expired_service = ControlledBrokerWriteReleaseService(
        db=env["db"],
        trusted_operator_identities=[env["identity"]],
        soak_promotion_provider=lambda _: _soak_promotion(),
        clock=lambda: NOW + timedelta(hours=9),
    )
    expired = expired_service.resolve_release_evidence(release_id)
    assert expired["status"] == "blocked"
    assert "controlled_broker_write_release_expired" in expired["blockers"]


def test_newer_exact_scope_readonly_release_invalidates_old_write_release(
    tmp_path,
    monkeypatch,
) -> None:
    env = _environment(tmp_path)
    recorded = _issue(env)
    readiness = build_broker_adapter_readiness(env["db"])
    old = deepcopy(readiness["releases"][0])
    newer = {
        **old,
        "release_evidence_ref": "fixture-per-order-adapter-release-v2",
        "manifest_fingerprint": "7" * 64,
    }
    monkeypatch.setattr(
        "server.services.controlled_broker_write_release.build_broker_adapter_readiness",
        lambda _: {**readiness, "latest_release": newer, "releases": [newer, old]},
    )

    resolved = env["service"].resolve_release_evidence(recorded["release_evidence_id"])

    assert resolved["status"] == "blocked"
    assert "broker_adapter_release_not_latest_for_scope" in resolved["blockers"]


def test_recomputed_payload_hash_cannot_change_signed_scope_or_row_binding(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    recorded = _issue(env)
    release_id = recorded["release_evidence_id"]
    with sqlite3.connect(env["db"]._path) as conn:
        payload = json.loads(
            conn.execute(
                "SELECT payload_json FROM controlled_broker_write_releases "
                "WHERE release_evidence_id = ?",
                (release_id,),
            ).fetchone()[0]
        )
        payload["provider"] = "tampered-provider"
        payload_json = _canonical_json(payload)
        conn.execute(
            "UPDATE controlled_broker_write_releases "
            "SET payload_json = ?, evidence_fingerprint = ?, provider = ?, "
            "gateway_id = ? WHERE release_evidence_id = ?",
            (
                payload_json,
                hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                payload["provider"],
                "tampered-gateway",
                release_id,
            ),
        )
        conn.commit()

    resolved = env["service"].resolve_release_evidence(release_id)

    assert resolved["status"] == "blocked"
    assert (
        "controlled_broker_write_release_payload_binding_invalid:provider"
        in resolved["blockers"]
    )
    assert (
        "controlled_broker_write_release_row_binding_invalid:gateway_id"
        in resolved["blockers"]
    )


def test_signed_revocation_is_one_way_idempotent_and_source_drift_cannot_block_it(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    recorded = _issue(env)
    release_id = recorded["release_evidence_id"]
    env["soak"][0] = {
        **env["soak"][0],
        "promotion_ready": False,
        "promotion_blockers": ["newer_soak_failure"],
    }
    preview = env["service"].preview_revocation(
        release_evidence_id=release_id,
        reason_code="incident_or_anomaly",
    )
    approval, signature = _approval(
        env,
        action="revoke_controlled_broker_write_release",
        artifact_type="controlled_broker_write_release_revocation",
        fingerprint=preview["revocation_fingerprint"],
    )
    request = {
        "release_evidence_id": release_id,
        "reason_code": "incident_or_anomaly",
        "revocation_fingerprint": preview["revocation_fingerprint"],
        "operator_label": "local-owner",
        "operator_approval_id": approval["approval_id"],
        "operator_proof_signature_base64": signature,
        "acknowledgement": CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_ACKNOWLEDGEMENT,
    }

    revoked = env["service"].revoke_release(**request)
    replay = env["service"].revoke_release(**request)
    resolved = env["service"].resolve_release_evidence(release_id)

    assert revoked["status"] == "revoked"
    assert revoked["resume_enabled"] is False
    assert replay["revocation_id"] == revoked["revocation_id"]
    assert replay["reused"] is True
    assert resolved["status"] == "blocked"
    assert "controlled_broker_write_release_revoked" in resolved["blockers"]
    assert env["service"].get_status()["active_release_count"] == 0


def test_spoofed_scope_and_provider_failure_are_sanitized_and_write_nothing(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    request = _dossier_request()
    request["execution_edge_manifest"]["account_alias"] = "wrong-account"
    blocked = env["service"].preview_dossier(**request)
    assert blocked["review_ready"] is False
    assert (
        "controlled_broker_write_release_readonly_scope_mismatch:account_alias"
        in blocked["review_blockers"]
    )

    failed = ControlledBrokerWriteReleaseService(
        db=env["db"],
        trusted_operator_identities=[env["identity"]],
        soak_promotion_provider=lambda _: (_ for _ in ()).throw(
            RuntimeError("private-provider-detail")
        ),
        clock=lambda: NOW,
    ).preview_dossier(**_dossier_request())
    serialized = str(failed)
    assert "broker_soak_promotion_source_failed" in serialized
    assert "private-provider-detail" not in serialized
    assert env["service"].list_releases() == []


def _canonical_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
