from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from scripts.operator_signer import generate_identity, sign_payload

_NOW = datetime(2026, 7, 16, 8, 1, tzinfo=timezone.utc)


def _challenge_payload(
    *,
    public_key_base64: str,
    overrides: dict | None = None,
) -> str:
    payload = {
        "schema_version": "karkinos.operator_approval_challenge.v1",
        "domain": "karkinos.controlled_execution.operator_approval",
        "operator_id": "local-owner",
        "key_id": "owner-key-1",
        "algorithm": "ed25519",
        "public_key_fingerprint": hashlib.sha256(
            base64.b64decode(public_key_base64)
        ).hexdigest(),
        "action": "post_controlled_submission_ledger",
        "artifact_type": "controlled_submission_ledger_posting",
        "artifact_fingerprint": "f" * 64,
        "nonce": "n" * 32,
        "issued_at": (_NOW - timedelta(minutes=1)).isoformat(),
        "expires_at": (_NOW + timedelta(minutes=2)).isoformat(),
        "does_not_issue_execution_authority": True,
    }
    payload.update(overrides or {})
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.b64encode(canonical).decode("ascii")


def test_local_operator_signer_generates_public_config_and_detached_proof(
    tmp_path,
) -> None:
    private_key_path = tmp_path / "operator-owner.pem"

    fragment = generate_identity(
        private_key_path=private_key_path,
        operator_id="local-owner",
        key_id="owner-key-1",
    )

    identity = fragment["trusted_operator_identities"][0]
    assert identity == {
        "operator_id": "local-owner",
        "key_id": "owner-key-1",
        "algorithm": "ed25519",
        "public_key_base64": identity["public_key_base64"],
        "enabled": True,
    }
    assert "private" not in str(fragment).lower()
    assert stat.S_IMODE(private_key_path.stat().st_mode) == 0o600

    payload_base64 = _challenge_payload(public_key_base64=identity["public_key_base64"])
    payload = base64.b64decode(payload_base64)
    signature_base64 = sign_payload(
        private_key_path=private_key_path,
        payload_base64=payload_base64,
        operator_id="local-owner",
        key_id="owner-key-1",
        expected_action="post_controlled_submission_ledger",
        expected_artifact_type="controlled_submission_ledger_posting",
        clock=lambda: _NOW,
    )
    public_key = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(identity["public_key_base64"])
    )
    public_key.verify(base64.b64decode(signature_base64), payload)
    assert len(base64.b64decode(signature_base64)) == 64


def test_local_operator_signer_refuses_overwrite_or_invalid_payload(tmp_path) -> None:
    private_key_path = tmp_path / "operator-owner.pem"
    generate_identity(
        private_key_path=private_key_path,
        operator_id="local-owner",
        key_id="owner-key-1",
    )

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        generate_identity(
            private_key_path=private_key_path,
            operator_id="local-owner",
            key_id="owner-key-1",
        )
    with pytest.raises(ValueError, match="valid Base64"):
        sign_payload(
            private_key_path=private_key_path,
            payload_base64="not-base64",
            operator_id="local-owner",
            key_id="owner-key-1",
            expected_action="post_controlled_submission_ledger",
            expected_artifact_type="controlled_submission_ledger_posting",
        )


def test_local_operator_signer_rejects_wrong_domain_identity_or_expiry(
    tmp_path,
) -> None:
    private_key_path = tmp_path / "operator-owner.pem"
    fragment = generate_identity(
        private_key_path=private_key_path,
        operator_id="local-owner",
        key_id="owner-key-1",
    )
    public_key_base64 = fragment["trusted_operator_identities"][0]["public_key_base64"]
    cases = [
        (
            {"domain": "untrusted.example"},
            "domain does not match",
        ),
        (
            {"key_id": "different-key"},
            "key_id does not match",
        ),
        (
            {"public_key_fingerprint": "0" * 64},
            "public_key_fingerprint does not match",
        ),
        (
            {
                "issued_at": (_NOW - timedelta(minutes=5)).isoformat(),
                "expires_at": (_NOW - timedelta(minutes=1)).isoformat(),
            },
            "not currently valid",
        ),
        (
            {"does_not_issue_execution_authority": False},
            "authority boundary is missing",
        ),
    ]
    for overrides, message in cases:
        with pytest.raises(ValueError, match=message):
            sign_payload(
                private_key_path=private_key_path,
                payload_base64=_challenge_payload(
                    public_key_base64=public_key_base64,
                    overrides=overrides,
                ),
                operator_id="local-owner",
                key_id="owner-key-1",
                expected_action="post_controlled_submission_ledger",
                expected_artifact_type="controlled_submission_ledger_posting",
                clock=lambda: _NOW,
            )


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
def test_local_operator_signer_rejects_group_readable_private_key(tmp_path) -> None:
    private_key_path = tmp_path / "operator-owner.pem"
    generate_identity(
        private_key_path=private_key_path,
        operator_id="local-owner",
        key_id="owner-key-1",
    )
    private_key_path.chmod(0o640)

    with pytest.raises(PermissionError, match="0600 or stricter"):
        sign_payload(
            private_key_path=private_key_path,
            payload_base64=base64.b64encode(b"payload").decode("ascii"),
            operator_id="local-owner",
            key_id="owner-key-1",
            expected_action="post_controlled_submission_ledger",
            expected_artifact_type="controlled_submission_ledger_posting",
        )


def test_local_operator_signer_rejects_non_ed25519_key(tmp_path) -> None:
    from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

    private_key_path = tmp_path / "rsa.pem"
    private_key = generate_private_key(public_exponent=65537, key_size=2048)
    private_key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    private_key_path.chmod(0o600)

    with pytest.raises(ValueError, match="must be Ed25519"):
        sign_payload(
            private_key_path=private_key_path,
            payload_base64=base64.b64encode(b"payload").decode("ascii"),
            operator_id="local-owner",
            key_id="owner-key-1",
            expected_action="post_controlled_submission_ledger",
            expected_artifact_type="controlled_submission_ledger_posting",
        )


@pytest.mark.parametrize(
    ("action", "artifact_type"),
    [
        (
            "cancel_exact_controlled_broker_order",
            "controlled_broker_cancellation",
        ),
        (
            "query_exact_broker_cancellation_outcome",
            "controlled_broker_cancellation_recovery",
        ),
    ],
)
def test_local_operator_signer_accepts_controlled_cancellation_contracts(
    tmp_path,
    action: str,
    artifact_type: str,
) -> None:
    private_key_path = tmp_path / "operator-owner.pem"
    fragment = generate_identity(
        private_key_path=private_key_path,
        operator_id="local-owner",
        key_id="owner-key-1",
    )
    public_key_base64 = fragment["trusted_operator_identities"][0]["public_key_base64"]
    payload_base64 = _challenge_payload(
        public_key_base64=public_key_base64,
        overrides={"action": action, "artifact_type": artifact_type},
    )

    signature = sign_payload(
        private_key_path=private_key_path,
        payload_base64=payload_base64,
        operator_id="local-owner",
        key_id="owner-key-1",
        expected_action=action,
        expected_artifact_type=artifact_type,
        clock=lambda: _NOW,
    )

    assert len(base64.b64decode(signature)) == 64


def test_local_operator_signer_rejects_controlled_cancellation_pair_mismatch(
    tmp_path,
) -> None:
    private_key_path = tmp_path / "operator-owner.pem"
    fragment = generate_identity(
        private_key_path=private_key_path,
        operator_id="local-owner",
        key_id="owner-key-1",
    )
    public_key_base64 = fragment["trusted_operator_identities"][0]["public_key_base64"]
    action = "cancel_exact_controlled_broker_order"
    mismatched_artifact = "controlled_broker_cancellation_recovery"

    with pytest.raises(ValueError, match="not allowlisted"):
        sign_payload(
            private_key_path=private_key_path,
            payload_base64=_challenge_payload(
                public_key_base64=public_key_base64,
                overrides={
                    "action": action,
                    "artifact_type": mismatched_artifact,
                },
            ),
            operator_id="local-owner",
            key_id="owner-key-1",
            expected_action=action,
            expected_artifact_type=mismatched_artifact,
            clock=lambda: _NOW,
        )
