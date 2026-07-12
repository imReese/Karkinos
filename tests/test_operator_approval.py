from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server.config import TrustedOperatorIdentityConfig
from server.db import AppDatabase
from server.services.operator_approval import (
    OperatorApprovalRejected,
    OperatorApprovalService,
)

NOW = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)
ARTIFACT_FINGERPRINT = "a" * 64


def _identity(
    private_key: Ed25519PrivateKey,
    *,
    enabled: bool = True,
) -> TrustedOperatorIdentityConfig:
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return TrustedOperatorIdentityConfig(
        operator_id="local-owner",
        key_id="owner-key-1",
        algorithm="ed25519",
        public_key_base64=base64.b64encode(public_bytes).decode("ascii"),
        enabled=enabled,
    )


def _service(tmp_path, *, clock=None, enabled: bool = True):
    db = AppDatabase(tmp_path / "operator-approval.db")
    db.init_sync()
    private_key = Ed25519PrivateKey.generate()
    service = OperatorApprovalService(
        db=db,
        trusted_identities=[_identity(private_key, enabled=enabled)],
        clock=clock or (lambda: NOW),
        nonce_factory=lambda: "deterministic-nonce-00000000000000000001",
    )
    return db, private_key, service


def _challenge_and_signature(service, private_key):
    challenge = service.create_challenge(
        operator_id="local-owner",
        key_id="owner-key-1",
        action="attest_per_order_dossier",
        artifact_type="per_order_dossier",
        artifact_fingerprint=ARTIFACT_FINGERPRINT,
        ttl_seconds=180,
    )
    signature = private_key.sign(base64.b64decode(challenge["signing_payload_base64"]))
    return challenge, base64.b64encode(signature).decode("ascii")


def test_ed25519_challenge_verification_is_append_only_and_exact(tmp_path) -> None:
    db, private_key, service = _service(tmp_path)
    challenge, signature = _challenge_and_signature(service, private_key)

    approval = service.verify_signature(
        challenge_id=challenge["challenge_id"],
        signature_base64=signature,
    )
    rerun = service.verify_signature(
        challenge_id=challenge["challenge_id"],
        signature_base64=signature,
    )
    resolved, blockers = service.resolve_approval(
        approval_id=approval["approval_id"],
        expected_action="attest_per_order_dossier",
        expected_artifact_type="per_order_dossier",
        expected_artifact_fingerprint=ARTIFACT_FINGERPRINT,
    )

    assert challenge["challenge_status"] == "pending_signature"
    assert challenge["operator_identity_verified"] is False
    assert approval["approval_status"] == "verified"
    assert "signature_base64" not in approval
    assert approval["operator_identity_verified"] is True
    assert approval["authorizes_execution"] is False
    assert rerun["event_id"] == approval["event_id"]
    assert rerun["reused"] is True
    assert blockers == []
    assert resolved["status"] == "verified"
    assert resolved["operator_id"] == "local-owner"
    assert resolved["safety"]["stores_private_keys"] is False
    assert db.list_oms_orders_sync() == []
    assert db.list_fills_sync() == []
    assert "signature_base64" not in service.list_approvals()[0]


def test_signature_or_artifact_mismatch_fails_closed_and_is_audited(tmp_path) -> None:
    _, private_key, service = _service(tmp_path)
    challenge, _ = _challenge_and_signature(service, private_key)
    wrong_signature = base64.b64encode(b"0" * 64).decode("ascii")

    with pytest.raises(OperatorApprovalRejected) as exc_info:
        service.verify_signature(
            challenge_id=challenge["challenge_id"],
            signature_base64=wrong_signature,
        )

    evidence = exc_info.value.evidence
    assert evidence["approval_status"] == "rejected"
    assert evidence["blockers"] == ["signature_verification_failed"]
    assert evidence["operator_identity_verified"] is False

    _, signature = _challenge_and_signature(service, private_key)
    approval = service.verify_signature(
        challenge_id=challenge["challenge_id"],
        signature_base64=signature,
    )
    resolved, blockers = service.resolve_approval(
        approval_id=approval["approval_id"],
        expected_action="attest_controlled_session_envelope",
        expected_artifact_type="controlled_session_envelope",
        expected_artifact_fingerprint="b" * 64,
    )
    assert resolved["status"] == "blocked"
    assert set(blockers) == {
        "operator_approval_action_mismatch",
        "operator_approval_artifact_type_mismatch",
        "operator_approval_artifact_fingerprint_mismatch",
    }


def test_expired_challenge_and_expired_approval_fail_closed(tmp_path) -> None:
    current = [NOW]
    _, private_key, service = _service(tmp_path, clock=lambda: current[0])
    challenge, signature = _challenge_and_signature(service, private_key)
    current[0] = NOW + timedelta(seconds=181)

    with pytest.raises(OperatorApprovalRejected) as exc_info:
        service.verify_signature(
            challenge_id=challenge["challenge_id"],
            signature_base64=signature,
        )

    assert exc_info.value.evidence["blockers"] == ["challenge_expired"]


def test_key_rotation_or_disable_invalidates_verified_approval(tmp_path) -> None:
    db, private_key, service = _service(tmp_path)
    challenge, signature = _challenge_and_signature(service, private_key)
    approval = service.verify_signature(
        challenge_id=challenge["challenge_id"],
        signature_base64=signature,
    )
    rotated_key = Ed25519PrivateKey.generate()
    rotated = OperatorApprovalService(
        db=db,
        trusted_identities=[_identity(rotated_key)],
        clock=lambda: NOW,
    )

    resolved, blockers = rotated.resolve_approval(
        approval_id=approval["approval_id"],
        expected_action="attest_per_order_dossier",
        expected_artifact_type="per_order_dossier",
        expected_artifact_fingerprint=ARTIFACT_FINGERPRINT,
    )

    assert resolved["status"] == "blocked"
    assert blockers == ["trusted_operator_key_changed"]


def test_status_never_returns_raw_public_or_private_key_material(tmp_path) -> None:
    _, _, service = _service(tmp_path)

    status = service.get_status()
    serialized = str(status)

    assert status["enabled_identity_count"] == 1
    assert status["private_key_storage_enabled"] is False
    assert "public_key_base64" not in serialized
    assert "private_key_base64" not in serialized


def test_disabled_identity_and_cross_action_challenge_are_rejected(tmp_path) -> None:
    _, _, service = _service(tmp_path, enabled=False)

    with pytest.raises(ValueError, match="identity disabled"):
        service.create_challenge(
            operator_id="local-owner",
            key_id="owner-key-1",
            action="attest_per_order_dossier",
            artifact_type="per_order_dossier",
            artifact_fingerprint=ARTIFACT_FINGERPRINT,
        )

    _, _, enabled_service = _service(tmp_path)
    with pytest.raises(ValueError, match="action_artifact_mismatch"):
        enabled_service.create_challenge(
            operator_id="local-owner",
            key_id="owner-key-1",
            action="attest_per_order_dossier",
            artifact_type="controlled_session_envelope",
            artifact_fingerprint=ARTIFACT_FINGERPRINT,
        )
