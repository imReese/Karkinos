"""Local-only Ed25519 provisioning and signing for operator approvals.

The private key stays in a user-selected file. Karkinos receives only the raw
public key in local configuration and a detached signature for one short-lived
challenge. This helper never calls the Karkinos API or edits config.json.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server.services.operator_approval import (
    MAX_CHALLENGE_TTL_SECONDS,
    OPERATOR_APPROVAL_ACTION_ARTIFACT_TYPES,
    OPERATOR_APPROVAL_CHALLENGE_SCHEMA_VERSION,
)

_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_SIGNING_PAYLOAD_BYTES = 64 * 1024


def generate_identity(
    *,
    private_key_path: Path,
    operator_id: str,
    key_id: str,
) -> dict[str, Any]:
    """Create one local private key and return its public config fragment."""

    normalized_operator = _validated_identity("operator_id", operator_id)
    normalized_key = _validated_identity("key_id", key_id)
    path = private_key_path.expanduser()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing private key: {path}")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(private_bytes)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return {
        "trusted_operator_identities": [
            {
                "operator_id": normalized_operator,
                "key_id": normalized_key,
                "algorithm": "ed25519",
                "public_key_base64": base64.b64encode(public_bytes).decode("ascii"),
                "enabled": True,
            }
        ]
    }


def sign_payload(
    *,
    private_key_path: Path,
    payload_base64: str,
    operator_id: str,
    key_id: str,
    expected_action: str,
    expected_artifact_type: str,
    clock: Callable[[], datetime] | None = None,
) -> str:
    """Sign one canonical challenge payload and return a detached signature."""

    path = private_key_path.expanduser()
    normalized_operator = _validated_identity("operator_id", operator_id)
    normalized_key = _validated_identity("key_id", key_id)
    _require_private_key_permissions(path)
    try:
        private_key = serialization.load_pem_private_key(
            path.read_bytes(),
            password=None,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError(
            f"unable to load unencrypted PKCS8 private key: {path}"
        ) from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("operator private key must be Ed25519")
    normalized_payload = "".join(str(payload_base64 or "").split())
    try:
        payload = base64.b64decode(normalized_payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("signing payload must be valid Base64") from exc
    if not payload:
        raise ValueError("signing payload must not be empty")
    if len(payload) > _MAX_SIGNING_PAYLOAD_BYTES:
        raise ValueError("signing payload exceeds the 64 KiB safety limit")
    challenge = _validated_challenge(
        payload=payload,
        public_key=private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ),
        operator_id=normalized_operator,
        key_id=normalized_key,
        expected_action=expected_action,
        expected_artifact_type=expected_artifact_type,
        now=(clock or (lambda: datetime.now(timezone.utc)))(),
    )
    print(
        "verified challenge: "
        f"operator={challenge['operator_id']} "
        f"action={challenge['action']} "
        f"artifact={challenge['artifact_type']} "
        f"fingerprint={challenge['artifact_fingerprint']} "
        f"expires_at={challenge['expires_at']}",
        file=sys.stderr,
    )
    signature = private_key.sign(payload)
    return base64.b64encode(signature).decode("ascii")


def _validated_challenge(
    *,
    payload: bytes,
    public_key: bytes,
    operator_id: str,
    key_id: str,
    expected_action: str,
    expected_artifact_type: str,
    now: datetime,
) -> dict[str, Any]:
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("signing payload must contain one JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError("signing payload must contain one JSON object")
    canonical = json.dumps(
        parsed,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if canonical != payload:
        raise ValueError("signing payload is not canonical JSON")
    checks = {
        "schema_version": OPERATOR_APPROVAL_CHALLENGE_SCHEMA_VERSION,
        "domain": "karkinos.controlled_execution.operator_approval",
        "operator_id": operator_id,
        "key_id": key_id,
        "algorithm": "ed25519",
        "public_key_fingerprint": hashlib.sha256(public_key).hexdigest(),
        "action": str(expected_action or "").strip(),
        "artifact_type": str(expected_artifact_type or "").strip(),
    }
    for field, expected in checks.items():
        if parsed.get(field) != expected:
            raise ValueError(
                f"signing payload {field} does not match the expected value"
            )
    expected_pair = OPERATOR_APPROVAL_ACTION_ARTIFACT_TYPES.get(checks["action"])
    if expected_pair != checks["artifact_type"]:
        raise ValueError(
            "expected operator action and artifact type are not allowlisted"
        )
    if parsed.get("does_not_issue_execution_authority") is not True:
        raise ValueError("signing payload authority boundary is missing")
    nonce = str(parsed.get("nonce") or "")
    if len(nonce) < 32 or len(nonce) > 256:
        raise ValueError("signing payload nonce is invalid")
    issued_at = _parse_timestamp(parsed.get("issued_at"), field="issued_at")
    expires_at = _parse_timestamp(parsed.get("expires_at"), field="expires_at")
    normalized_now = _aware_utc(now)
    if expires_at <= issued_at:
        raise ValueError("signing payload expiry window is invalid")
    if (expires_at - issued_at).total_seconds() > MAX_CHALLENGE_TTL_SECONDS:
        raise ValueError("signing payload expiry window exceeds the safety limit")
    if normalized_now < issued_at or normalized_now >= expires_at:
        raise ValueError("signing payload is not currently valid")
    return parsed


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    normalized = str(value or "").strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"signing payload {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"signing payload {field} must be timezone-aware")
    return _aware_utc(parsed)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("signing clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _require_private_key_permissions(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"private key file not found: {path}")
    if os.name == "posix":
        permissions = stat.S_IMODE(path.stat().st_mode)
        if permissions & 0o077:
            raise PermissionError(
                f"private key permissions must be 0600 or stricter: {path}"
            )


def _validated_identity(field: str, value: str) -> str:
    normalized = str(value or "").strip()
    if not _IDENTITY_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"{field} must match {_IDENTITY_PATTERN.pattern} and contain at most 128 characters"
        )
    return normalized


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Provision or use a local-only Karkinos Ed25519 operator key.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    initialize = subparsers.add_parser(
        "init",
        help="create a private key and print the public config fragment",
    )
    initialize.add_argument("--private-key", required=True, type=Path)
    initialize.add_argument("--operator-id", required=True)
    initialize.add_argument("--key-id", required=True)
    sign = subparsers.add_parser(
        "sign",
        help="read a Base64 challenge payload from stdin and print its signature",
    )
    sign.add_argument("--private-key", required=True, type=Path)
    sign.add_argument("--operator-id", required=True)
    sign.add_argument("--key-id", required=True)
    sign.add_argument("--expected-action", required=True)
    sign.add_argument("--expected-artifact-type", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            fragment = generate_identity(
                private_key_path=args.private_key,
                operator_id=args.operator_id,
                key_id=args.key_id,
            )
            print(json.dumps(fragment, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        payload_base64 = sys.stdin.read()
        print(
            sign_payload(
                private_key_path=args.private_key,
                payload_base64=payload_base64,
                operator_id=args.operator_id,
                key_id=args.key_id,
                expected_action=args.expected_action,
                expected_artifact_type=args.expected_artifact_type,
            )
        )
        return 0
    except (FileExistsError, FileNotFoundError, PermissionError, ValueError) as exc:
        print(f"operator signer failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
