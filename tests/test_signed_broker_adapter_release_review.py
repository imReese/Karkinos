from __future__ import annotations

import base64
import json
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from account_truth.broker_adapter_conformance import (
    BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
    BrokerAdapterConformanceRepository,
)
from account_truth.broker_adapter_conformance_fixtures import (
    run_deterministic_broker_adapter_conformance,
)
from account_truth.broker_adapter_release import (
    BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    BrokerAdapterReleaseRejected,
    BrokerAdapterReleaseReviewRepository,
    preview_broker_adapter_release_manifest,
)
from server.config import TrustedOperatorIdentityConfig
from server.db import AppDatabase
from server.services.operator_approval import OperatorApprovalService
from server.services.signed_broker_adapter_release_review import (
    SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_ACTION,
    SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_ARTIFACT_TYPE,
    SignedBrokerAdapterReleaseReviewRejected,
    SignedBrokerAdapterReleaseReviewService,
)
from tests.account_truth.test_broker_adapter_release import (
    collector_binding,
    release_manifest,
)

NOW = datetime(2026, 7, 18, 3, 0, tzinfo=timezone.utc)


def _identity(private_key: Ed25519PrivateKey) -> TrustedOperatorIdentityConfig:
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return TrustedOperatorIdentityConfig(
        operator_id="local-owner",
        key_id="adapter-review-key-1",
        algorithm="ed25519",
        public_key_base64=base64.b64encode(public_bytes).decode("ascii"),
        enabled=True,
    )


def _environment(tmp_path, *, with_conformance: bool = True) -> dict:
    db = AppDatabase(tmp_path / "signed-adapter-review.db")
    db.init_sync()
    private_key = Ed25519PrivateKey.generate()
    identity = _identity(private_key)
    service = SignedBrokerAdapterReleaseReviewService(
        db=db,
        trusted_operator_identities=[identity],
        clock=lambda: NOW,
    )
    if with_conformance:
        preview = preview_broker_adapter_release_manifest(
            json.dumps(release_manifest()),
            source_name="signed adapter review fixture",
        )
        report = run_deterministic_broker_adapter_conformance(
            preview,
            run_id="signed-adapter-review-conformance-v1",
        )
        BrokerAdapterConformanceRepository(db._path).record_report(
            report,
            acknowledgement=BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
        )
    return {
        "db": db,
        "private_key": private_key,
        "identity": identity,
        "service": service,
    }


def _request(
    *,
    decision: str = "accepted",
    review_id: str = "signed-adapter-review-v1",
    reason_ref: str = "owner-reviewed-provider-boundary-v1",
    manifest: dict | None = None,
) -> dict:
    return {
        "manifest": deepcopy(manifest or release_manifest()),
        "source_name": "owner-reviewed-adapter-release.json",
        "review_id": review_id,
        "decision": decision,
        "reviewed_at": NOW.isoformat(),
        "reason_ref": reason_ref,
    }


def _approval(env: dict, fingerprint: str) -> tuple[dict, str]:
    service = OperatorApprovalService(
        db=env["db"],
        trusted_identities=[env["identity"]],
        clock=lambda: NOW,
        nonce_factory=lambda: "signed-adapter-review-nonce-000000001",
    )
    challenge = service.create_challenge(
        operator_id="local-owner",
        key_id="adapter-review-key-1",
        action=SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_ACTION,
        artifact_type=SIGNED_BROKER_ADAPTER_RELEASE_REVIEW_ARTIFACT_TYPE,
        artifact_fingerprint=fingerprint,
        ttl_seconds=180,
    )
    signature = env["private_key"].sign(
        base64.b64decode(challenge["signing_payload_base64"])
    )
    signature_base64 = base64.b64encode(signature).decode("ascii")
    approval = service.verify_signature(
        challenge_id=challenge["challenge_id"],
        signature_base64=signature_base64,
    )
    return approval, signature_base64


def _record(env: dict, request: dict) -> dict:
    dossier = env["service"].preview_dossier(**request)
    approval, signature = _approval(env, dossier["dossier_fingerprint"])
    return env["service"].record_review(
        **request,
        dossier_fingerprint=dossier["dossier_fingerprint"],
        operator_label="local-owner",
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=signature,
        acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    )


def test_signed_acceptance_binds_conformance_operator_and_exact_retry(tmp_path) -> None:
    env = _environment(tmp_path)
    request = _request()

    dossier = env["service"].preview_dossier(**request)
    approval, signature = _approval(env, dossier["dossier_fingerprint"])
    first = env["service"].record_review(
        **request,
        dossier_fingerprint=dossier["dossier_fingerprint"],
        operator_label="local-owner",
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=signature,
        acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    )
    replay = env["service"].record_review(
        **request,
        dossier_fingerprint=dossier["dossier_fingerprint"],
        operator_label="local-owner",
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=signature,
        acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    )
    binding = BrokerAdapterReleaseReviewRepository(
        env["db"]._path,
        ensure_schema=False,
    ).verify_collector_binding(collector_binding())

    assert dossier["review_ready"] is True
    assert dossier["conformance"]["status"] == "clear"
    assert first["status"] == "accepted"
    assert first["reviewer_ref"] == f"operator_approval:{approval['approval_id']}"
    assert first["operator_id"] == "local-owner"
    assert first["operator_identity_verified"] is True
    assert first["adapter_registered"] is False
    assert first["authorizes_execution"] is False
    assert replay["review_fingerprint"] == first["review_fingerprint"]
    assert replay["reused"] is True
    assert binding["status"] == "clear"
    assert env["service"].get_status()["recorded_review_count"] == 1


def test_acceptance_fails_closed_without_or_after_changed_conformance(tmp_path) -> None:
    missing_env = _environment(tmp_path / "missing", with_conformance=False)
    missing = missing_env["service"].preview_dossier(**_request())
    assert missing["review_ready"] is False
    assert "broker_adapter_conformance_report_not_found" in missing["review_blockers"]

    env = _environment(tmp_path / "drift")
    request = _request(review_id="signed-adapter-review-drift-v1")
    dossier = env["service"].preview_dossier(**request)
    approval, signature = _approval(env, dossier["dossier_fingerprint"])
    newer = run_deterministic_broker_adapter_conformance(
        preview_broker_adapter_release_manifest(json.dumps(release_manifest())),
        run_id="signed-adapter-review-conformance-v2",
    )
    BrokerAdapterConformanceRepository(env["db"]._path).record_report(
        newer,
        acknowledgement=BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
    )

    with pytest.raises(SignedBrokerAdapterReleaseReviewRejected) as rejected:
        env["service"].record_review(
            **request,
            dossier_fingerprint=dossier["dossier_fingerprint"],
            operator_label="local-owner",
            operator_approval_id=approval["approval_id"],
            operator_proof_signature_base64=signature,
            acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
        )
    assert "signed_broker_adapter_review_dossier_fingerprint_mismatch" in (
        rejected.value.evidence["blockers"]
    )


def test_signed_rejection_and_revocation_are_safe_append_only_decisions(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    writable = release_manifest()
    writable["release_evidence_ref"] = "fixture-release-rejected-v1"
    writable["capabilities"]["can_submit_orders"] = True
    rejected_request = _request(
        decision="rejected",
        review_id="signed-adapter-rejection-v1",
        reason_ref="write-capability-not-allowed",
        manifest=writable,
    )
    rejected_dossier = env["service"].preview_dossier(**rejected_request)
    rejected = _record(env, rejected_request)
    accepted = _record(env, _request())
    revoke_request = _request(
        decision="revoked",
        review_id="signed-adapter-revocation-v1",
        reason_ref="owner-disabled-adapter-release",
    )
    revoke_dossier = env["service"].preview_dossier(**revoke_request)
    revoked = _record(env, revoke_request)
    binding = BrokerAdapterReleaseReviewRepository(
        env["db"]._path,
        ensure_schema=False,
    ).verify_collector_binding(collector_binding())

    assert rejected_dossier["review_ready"] is True
    assert rejected["status"] == "rejected"
    assert accepted["status"] == "accepted"
    assert revoke_dossier["current_review"]["review_fingerprint"] == (
        accepted["review_fingerprint"]
    )
    assert revoked["status"] == "revoked"
    assert binding["status"] == "blocked"
    assert "broker_adapter_release_review_not_accepted" in binding["blockers"]
    assert revoked["provider_contact_performed"] is False
    assert revoked["capital_authority_changed"] is False


def test_sensitive_api_key_is_blocked_without_value_echo_or_schema_creation(
    tmp_path,
) -> None:
    env = _environment(tmp_path, with_conformance=False)
    sensitive = release_manifest()
    sensitive["nested"] = {"api_key": "must-never-leave-review-preview"}
    dossier = env["service"].preview_dossier(
        **_request(manifest=sensitive, decision="rejected")
    )

    assert dossier["review_ready"] is False
    assert "broker_adapter_release_auth_material_not_allowed" in (
        dossier["review_blockers"]
    )
    assert "must-never-leave-review-preview" not in json.dumps(dossier)

    with sqlite3.connect(env["db"]._path) as conn:
        before = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    env["service"].get_status()
    env["service"].list_releases()
    with sqlite3.connect(env["db"]._path) as conn:
        after = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert before == after
    assert "broker_adapter_release_manifests" not in after
    assert "broker_adapter_release_review_events" not in after


def test_repository_rechecks_expected_conformance_and_latest_review(tmp_path) -> None:
    env = _environment(tmp_path)
    preview = preview_broker_adapter_release_manifest(json.dumps(release_manifest()))
    conformance = BrokerAdapterConformanceRepository(
        env["db"]._path,
        ensure_schema=False,
    ).verify_release_binding(
        release_evidence_ref=preview["release_evidence_ref"],
        manifest_fingerprint=preview["manifest_fingerprint"],
    )
    repository = BrokerAdapterReleaseReviewRepository(env["db"]._path)

    with pytest.raises(BrokerAdapterReleaseRejected) as conformance_drift:
        repository.record_review(
            preview,
            review_id="expected-conformance-drift-v1",
            decision="accepted",
            reviewer_ref="operator-approval-fixture",
            reviewed_at=NOW.isoformat(),
            reason_ref="expected-conformance-drift",
            acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
            expected_conformance_run_id="different-conformance-run",
            expected_conformance_report_fingerprint=conformance["report_fingerprint"],
            expected_latest_review_fingerprint="",
        )
    assert "broker_adapter_release_conformance_run_drift" in (
        conformance_drift.value.evidence["blockers"]
    )

    accepted = repository.record_review(
        preview,
        review_id="expected-source-accepted-v1",
        decision="accepted",
        reviewer_ref="operator-approval-fixture",
        reviewed_at=NOW.isoformat(),
        reason_ref="expected-source-accepted",
        acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
        expected_conformance_run_id=conformance["run_id"],
        expected_conformance_report_fingerprint=conformance["report_fingerprint"],
        expected_latest_review_fingerprint="",
    )
    with pytest.raises(BrokerAdapterReleaseRejected) as latest_drift:
        repository.record_review(
            preview,
            review_id="expected-source-revoked-v1",
            decision="revoked",
            reviewer_ref="operator-approval-fixture",
            reviewed_at=NOW.isoformat(),
            reason_ref="expected-source-revoked",
            acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
            expected_latest_review_fingerprint="f" * 64,
        )
    assert accepted["status"] == "accepted"
    assert "broker_adapter_release_latest_review_drift" in (
        latest_drift.value.evidence["blockers"]
    )
