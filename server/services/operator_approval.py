"""Short-lived Ed25519 operator approvals for exact review artifacts."""

from __future__ import annotations

import base64
import binascii
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from server.services.operator_approval_contracts import (
    DEFAULT_CHALLENGE_TTL_SECONDS,
    MAX_CHALLENGE_TTL_SECONDS,
    MIN_CHALLENGE_TTL_SECONDS,
    OPERATOR_APPROVAL_ACTION_ARTIFACT_TYPES,
    OPERATOR_APPROVAL_ACTIONS,
    OPERATOR_APPROVAL_ARTIFACT_TYPES,
    OPERATOR_APPROVAL_CHALLENGE_SCHEMA_VERSION,
    OPERATOR_APPROVAL_SCHEMA_VERSION,
    OPERATOR_APPROVAL_STATUS_SCHEMA_VERSION,
)
from server.services.operator_approval_contracts import (
    approval_resolution as _approval_resolution,
)
from server.services.operator_approval_contracts import aware_utc as _aware_utc
from server.services.operator_approval_contracts import (
    canonical_bytes as _canonical_bytes,
)
from server.services.operator_approval_contracts import (
    challenge_input_blockers as _challenge_input_blockers,
)
from server.services.operator_approval_contracts import (
    event_response as _event_response,
)
from server.services.operator_approval_contracts import fingerprint as _fingerprint
from server.services.operator_approval_contracts import (
    is_valid_operator_fingerprint as _is_valid_operator_fingerprint,
)
from server.services.operator_approval_contracts import (
    is_valid_operator_identity_id as _is_valid_operator_identity_id,
)
from server.services.operator_approval_contracts import json_object as _json_object
from server.services.operator_approval_contracts import (
    normalize_identities as _normalize_identities,
)
from server.services.operator_approval_contracts import (
    parse_timestamp as _parse_timestamp,
)
from server.services.operator_approval_contracts import (
    public_approval_event as _public_approval_event,
)
from server.services.operator_approval_contracts import safety_flags as _safety_flags

OPERATOR_APPROVAL_CHALLENGE_EVENT_TYPE = "operator_approval.challenge_created"
OPERATOR_APPROVAL_CHALLENGE_ENTITY_TYPE = "operator_approval_challenge"
OPERATOR_APPROVAL_CHALLENGE_SOURCE = "operator_approval"
OPERATOR_APPROVAL_VERIFIED_EVENT_TYPE = "operator_approval.signature_verified"
OPERATOR_APPROVAL_VERIFIED_ENTITY_TYPE = "operator_approval"
OPERATOR_APPROVAL_VERIFIED_SOURCE = "operator_approval"
OPERATOR_APPROVAL_REJECTED_EVENT_TYPE = "operator_approval.verification_rejected"
OPERATOR_APPROVAL_REJECTED_ENTITY_TYPE = "operator_approval_rejection"
OPERATOR_APPROVAL_REJECTED_SOURCE = "operator_approval"


class OperatorApprovalRejected(ValueError):
    """Raised after a signature verification attempt is rejected and audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class OperatorApprovalService:
    """Verify offline signatures without storing private keys or granting authority."""

    def __init__(
        self,
        *,
        db: Any,
        trusted_identities: list[Any] | tuple[Any, ...] = (),
        clock: Callable[[], datetime] | None = None,
        nonce_factory: Callable[[], str] | None = None,
    ) -> None:
        self._db = db
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._nonce_factory = nonce_factory or (lambda: secrets.token_urlsafe(32))
        self._identities = _normalize_identities(trusted_identities)

    def get_status(self) -> dict[str, Any]:
        identities = [
            {
                "operator_id": identity["operator_id"],
                "key_id": identity["key_id"],
                "algorithm": identity["algorithm"],
                "enabled": identity["enabled"],
                "public_key_fingerprint": identity["public_key_fingerprint"],
            }
            for identity in self._identities
        ]
        return {
            "schema_version": OPERATOR_APPROVAL_STATUS_SCHEMA_VERSION,
            "contract_status": "public_key_verification_only",
            "trusted_identity_count": len(identities),
            "enabled_identity_count": sum(item["enabled"] for item in identities),
            "trusted_identities": identities,
            "supported_actions": sorted(OPERATOR_APPROVAL_ACTIONS),
            "default_challenge_ttl_seconds": DEFAULT_CHALLENGE_TTL_SECONDS,
            "maximum_challenge_ttl_seconds": MAX_CHALLENGE_TTL_SECONDS,
            "private_key_storage_enabled": False,
            "runtime_execution_authority": "disabled",
            "broker_submission_enabled": False,
            "safety": _safety_flags(),
        }

    def create_challenge(
        self,
        *,
        operator_id: str,
        key_id: str,
        action: str,
        artifact_type: str,
        artifact_fingerprint: str,
        ttl_seconds: int = DEFAULT_CHALLENGE_TTL_SECONDS,
    ) -> dict[str, Any]:
        identity = self._require_identity(operator_id, key_id)
        normalized_action = str(action or "").strip()
        normalized_artifact_type = str(artifact_type or "").strip()
        normalized_fingerprint = str(artifact_fingerprint or "").strip().lower()
        ttl = int(ttl_seconds)
        blockers = _challenge_input_blockers(
            action=normalized_action,
            artifact_type=normalized_artifact_type,
            artifact_fingerprint=normalized_fingerprint,
            ttl_seconds=ttl,
        )
        if blockers:
            raise ValueError(
                "invalid operator approval challenge: " + ", ".join(blockers)
            )
        issued_at = _aware_utc(self._clock()).replace(microsecond=0)
        expires_at = issued_at + timedelta(seconds=ttl)
        nonce = str(self._nonce_factory() or "").strip()
        if len(nonce) < 32 or len(nonce) > 256:
            raise ValueError("operator approval nonce must contain 32-256 characters")
        signing_payload = {
            "schema_version": OPERATOR_APPROVAL_CHALLENGE_SCHEMA_VERSION,
            "domain": "karkinos.controlled_execution.operator_approval",
            "operator_id": identity["operator_id"],
            "key_id": identity["key_id"],
            "algorithm": "ed25519",
            "public_key_fingerprint": identity["public_key_fingerprint"],
            "action": normalized_action,
            "artifact_type": normalized_artifact_type,
            "artifact_fingerprint": normalized_fingerprint,
            "nonce": nonce,
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "does_not_issue_execution_authority": True,
        }
        signing_bytes = _canonical_bytes(signing_payload)
        challenge_id = _fingerprint(signing_payload)
        existing = self._db.list_events_sync(
            event_type=OPERATOR_APPROVAL_CHALLENGE_EVENT_TYPE,
            entity_type=OPERATOR_APPROVAL_CHALLENGE_ENTITY_TYPE,
            entity_id=challenge_id,
            source=OPERATOR_APPROVAL_CHALLENGE_SOURCE,
            limit=1,
        )
        if existing:
            return _event_response(existing[0], reused=True)
        payload = {
            "schema_version": OPERATOR_APPROVAL_CHALLENGE_SCHEMA_VERSION,
            "challenge_id": challenge_id,
            "challenge_status": "pending_signature",
            "signing_payload": signing_payload,
            "signing_payload_base64": base64.b64encode(signing_bytes).decode("ascii"),
            "operator_id": identity["operator_id"],
            "key_id": identity["key_id"],
            "public_key_fingerprint": identity["public_key_fingerprint"],
            "action": normalized_action,
            "artifact_type": normalized_artifact_type,
            "artifact_fingerprint": normalized_fingerprint,
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "operator_identity_verified": False,
            "authorizes_execution": False,
            "safety": _safety_flags(),
        }
        self._db.append_event_sync(
            event_type=OPERATOR_APPROVAL_CHALLENGE_EVENT_TYPE,
            timestamp=issued_at.isoformat(),
            entity_type=OPERATOR_APPROVAL_CHALLENGE_ENTITY_TYPE,
            entity_id=challenge_id,
            source=OPERATOR_APPROVAL_CHALLENGE_SOURCE,
            source_ref=f"{identity['operator_id']}:{identity['key_id']}",
            payload=payload,
        )
        saved = self._db.list_events_sync(
            event_type=OPERATOR_APPROVAL_CHALLENGE_EVENT_TYPE,
            entity_type=OPERATOR_APPROVAL_CHALLENGE_ENTITY_TYPE,
            entity_id=challenge_id,
            source=OPERATOR_APPROVAL_CHALLENGE_SOURCE,
            limit=1,
        )
        if not saved:
            raise RuntimeError("operator approval challenge was not recorded")
        return _event_response(saved[0], reused=False)

    def verify_signature(
        self,
        *,
        challenge_id: str,
        signature_base64: str,
    ) -> dict[str, Any]:
        normalized_challenge_id = str(challenge_id or "").strip().lower()
        signature_text = str(signature_base64 or "").strip()
        challenge = self._get_challenge(normalized_challenge_id)
        existing = self._db.list_events_sync(
            event_type=OPERATOR_APPROVAL_VERIFIED_EVENT_TYPE,
            entity_type=OPERATOR_APPROVAL_VERIFIED_ENTITY_TYPE,
            entity_id=normalized_challenge_id,
            source=OPERATOR_APPROVAL_VERIFIED_SOURCE,
            limit=1,
        )
        signature_fingerprint = _fingerprint(signature_text)
        if existing:
            recorded = _event_response(existing[0], reused=True)
            if recorded.get("signature_fingerprint") == signature_fingerprint:
                return _public_approval_event(recorded)
            evidence = self._record_rejection(
                challenge=challenge,
                signature_fingerprint=signature_fingerprint,
                blockers=["challenge_already_verified_with_different_signature"],
            )
            raise OperatorApprovalRejected(
                "operator approval rejected: challenge already verified",
                evidence=evidence,
            )

        blockers: list[str] = []
        now = _aware_utc(self._clock())
        expires_at = _parse_timestamp(challenge.get("expires_at"))
        if expires_at is None:
            blockers.append("challenge_expiry_invalid")
        elif now >= expires_at:
            blockers.append("challenge_expired")
        identity = self._find_identity(
            str(challenge.get("operator_id") or ""),
            str(challenge.get("key_id") or ""),
        )
        if identity is None:
            blockers.append("trusted_operator_identity_not_found")
        elif not identity["enabled"]:
            blockers.append("trusted_operator_identity_disabled")
        elif identity["public_key_fingerprint"] != challenge.get(
            "public_key_fingerprint"
        ):
            blockers.append("trusted_operator_key_changed")
        signature: bytes | None = None
        try:
            signature = base64.b64decode(signature_text, validate=True)
        except (binascii.Error, ValueError):
            blockers.append("signature_base64_invalid")
        if signature is not None and len(signature) != 64:
            blockers.append("signature_length_invalid")
        signing_payload = challenge.get("signing_payload")
        signing_payload = signing_payload if isinstance(signing_payload, dict) else {}
        if _fingerprint(signing_payload) != normalized_challenge_id:
            blockers.append("challenge_payload_fingerprint_invalid")
        if not blockers and identity is not None and signature is not None:
            try:
                public_key = Ed25519PublicKey.from_public_bytes(identity["public_key"])
                public_key.verify(signature, _canonical_bytes(signing_payload))
            except (InvalidSignature, ValueError):
                blockers.append("signature_verification_failed")
        if blockers:
            evidence = self._record_rejection(
                challenge=challenge,
                signature_fingerprint=signature_fingerprint,
                blockers=blockers,
            )
            raise OperatorApprovalRejected(
                "operator approval rejected: " + ", ".join(blockers),
                evidence=evidence,
            )

        verified_at = now.replace(microsecond=0)
        payload = {
            "schema_version": OPERATOR_APPROVAL_SCHEMA_VERSION,
            "approval_id": normalized_challenge_id,
            "challenge_id": normalized_challenge_id,
            "approval_status": "verified",
            "operator_id": challenge.get("operator_id"),
            "key_id": challenge.get("key_id"),
            "algorithm": "ed25519",
            "public_key_fingerprint": challenge.get("public_key_fingerprint"),
            "action": challenge.get("action"),
            "artifact_type": challenge.get("artifact_type"),
            "artifact_fingerprint": challenge.get("artifact_fingerprint"),
            "issued_at": challenge.get("issued_at"),
            "expires_at": challenge.get("expires_at"),
            "verified_at": verified_at.isoformat(),
            "signature_base64": signature_text,
            "signature_fingerprint": signature_fingerprint,
            "operator_identity_verified": True,
            "authorizes_execution": False,
            "safety": _safety_flags(),
        }
        self._db.append_event_sync(
            event_type=OPERATOR_APPROVAL_VERIFIED_EVENT_TYPE,
            timestamp=verified_at.isoformat(),
            entity_type=OPERATOR_APPROVAL_VERIFIED_ENTITY_TYPE,
            entity_id=normalized_challenge_id,
            source=OPERATOR_APPROVAL_VERIFIED_SOURCE,
            source_ref=normalized_challenge_id,
            payload=payload,
        )
        saved = self._db.list_events_sync(
            event_type=OPERATOR_APPROVAL_VERIFIED_EVENT_TYPE,
            entity_type=OPERATOR_APPROVAL_VERIFIED_ENTITY_TYPE,
            entity_id=normalized_challenge_id,
            source=OPERATOR_APPROVAL_VERIFIED_SOURCE,
            limit=1,
        )
        if not saved:
            raise RuntimeError("verified operator approval was not recorded")
        return _public_approval_event(_event_response(saved[0], reused=False))

    def resolve_approval(
        self,
        *,
        approval_id: str,
        expected_action: str,
        expected_artifact_type: str,
        expected_artifact_fingerprint: str,
    ) -> tuple[dict[str, Any], list[str]]:
        normalized = str(approval_id or "").strip().lower()
        blockers: list[str] = []
        rows = (
            self._db.list_events_sync(
                event_type=OPERATOR_APPROVAL_VERIFIED_EVENT_TYPE,
                entity_type=OPERATOR_APPROVAL_VERIFIED_ENTITY_TYPE,
                entity_id=normalized,
                source=OPERATOR_APPROVAL_VERIFIED_SOURCE,
                limit=1,
            )
            if _is_valid_operator_fingerprint(normalized)
            else []
        )
        if not _is_valid_operator_fingerprint(normalized):
            blockers.append("operator_approval_id_invalid")
        if not rows:
            blockers.append("operator_approval_not_found")
            return _approval_resolution(normalized, {}, blockers)
        approval = _event_response(rows[0], reused=False)
        if approval.get("schema_version") != OPERATOR_APPROVAL_SCHEMA_VERSION:
            blockers.append("operator_approval_schema_invalid")
        if approval.get("approval_status") != "verified" or not approval.get(
            "operator_identity_verified"
        ):
            blockers.append("operator_approval_not_verified")
        if approval.get("action") != expected_action:
            blockers.append("operator_approval_action_mismatch")
        if approval.get("artifact_type") != expected_artifact_type:
            blockers.append("operator_approval_artifact_type_mismatch")
        if approval.get("artifact_fingerprint") != expected_artifact_fingerprint:
            blockers.append("operator_approval_artifact_fingerprint_mismatch")
        expires_at = _parse_timestamp(approval.get("expires_at"))
        if expires_at is None or _aware_utc(self._clock()) >= expires_at:
            blockers.append("operator_approval_expired")
        identity = self._find_identity(
            str(approval.get("operator_id") or ""),
            str(approval.get("key_id") or ""),
        )
        if identity is None:
            blockers.append("trusted_operator_identity_not_found")
        elif not identity["enabled"]:
            blockers.append("trusted_operator_identity_disabled")
        elif identity["public_key_fingerprint"] != approval.get(
            "public_key_fingerprint"
        ):
            blockers.append("trusted_operator_key_changed")
        return _approval_resolution(normalized, approval, blockers)

    def resolve_approval_with_proof(
        self,
        *,
        approval_id: str,
        proof_signature_base64: str,
        expected_action: str,
        expected_artifact_type: str,
        expected_artifact_fingerprint: str,
    ) -> tuple[dict[str, Any], list[str]]:
        """Require possession of the verified signature without exposing it."""
        resolved, blockers = self.resolve_approval(
            approval_id=approval_id,
            expected_action=expected_action,
            expected_artifact_type=expected_artifact_type,
            expected_artifact_fingerprint=expected_artifact_fingerprint,
        )
        normalized = str(approval_id or "").strip().lower()
        proof = str(proof_signature_base64 or "").strip()
        rows = self._db.list_events_sync(
            event_type=OPERATOR_APPROVAL_VERIFIED_EVENT_TYPE,
            entity_type=OPERATOR_APPROVAL_VERIFIED_ENTITY_TYPE,
            entity_id=normalized,
            source=OPERATOR_APPROVAL_VERIFIED_SOURCE,
            limit=1,
        )
        proof_blockers = list(blockers)
        try:
            decoded = base64.b64decode(proof, validate=True)
        except (binascii.Error, ValueError):
            decoded = b""
        if len(decoded) != 64:
            proof_blockers.append("operator_approval_proof_signature_invalid")
        recorded = _event_response(rows[0], reused=False) if rows else {}
        if not recorded or not hmac.compare_digest(
            str(recorded.get("signature_fingerprint") or ""),
            _fingerprint(proof),
        ):
            proof_blockers.append("operator_approval_proof_signature_mismatch")
        unique_blockers = list(dict.fromkeys(proof_blockers))
        return (
            {
                **resolved,
                "status": "verified" if not unique_blockers else "blocked",
                "operator_identity_verified": not unique_blockers,
                "proof_signature_verified": not unique_blockers,
                "blockers": unique_blockers,
            },
            unique_blockers,
        )

    def list_challenges(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=OPERATOR_APPROVAL_CHALLENGE_EVENT_TYPE,
            entity_type=OPERATOR_APPROVAL_CHALLENGE_ENTITY_TYPE,
            source=OPERATOR_APPROVAL_CHALLENGE_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
        return [_event_response(row, reused=False) for row in rows]

    def list_approvals(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=OPERATOR_APPROVAL_VERIFIED_EVENT_TYPE,
            entity_type=OPERATOR_APPROVAL_VERIFIED_ENTITY_TYPE,
            source=OPERATOR_APPROVAL_VERIFIED_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
        return [
            _public_approval_event(_event_response(row, reused=False)) for row in rows
        ]

    def _get_challenge(self, challenge_id: str) -> dict[str, Any]:
        if not _is_valid_operator_fingerprint(challenge_id):
            raise KeyError("operator approval challenge not found")
        rows = self._db.list_events_sync(
            event_type=OPERATOR_APPROVAL_CHALLENGE_EVENT_TYPE,
            entity_type=OPERATOR_APPROVAL_CHALLENGE_ENTITY_TYPE,
            entity_id=challenge_id,
            source=OPERATOR_APPROVAL_CHALLENGE_SOURCE,
            limit=1,
        )
        if not rows:
            raise KeyError("operator approval challenge not found")
        return _event_response(rows[0], reused=False)

    def _require_identity(self, operator_id: str, key_id: str) -> dict[str, Any]:
        normalized_operator_id = str(operator_id or "").strip()
        normalized_key_id = str(key_id or "").strip()
        if not _is_valid_operator_identity_id(normalized_operator_id):
            raise ValueError("operator_id invalid")
        if not _is_valid_operator_identity_id(normalized_key_id):
            raise ValueError("key_id invalid")
        identity = self._find_identity(normalized_operator_id, normalized_key_id)
        if identity is None:
            raise ValueError("trusted operator identity not found")
        if not identity["enabled"]:
            raise ValueError("trusted operator identity disabled")
        return identity

    def _find_identity(
        self,
        operator_id: str,
        key_id: str,
    ) -> dict[str, Any] | None:
        return next(
            (
                identity
                for identity in self._identities
                if identity["operator_id"] == operator_id
                and identity["key_id"] == key_id
            ),
            None,
        )

    def _record_rejection(
        self,
        *,
        challenge: dict[str, Any],
        signature_fingerprint: str,
        blockers: list[str],
    ) -> dict[str, Any]:
        payload_core = {
            "schema_version": OPERATOR_APPROVAL_SCHEMA_VERSION,
            "approval_status": "rejected",
            "challenge_id": challenge.get("challenge_id"),
            "operator_id": challenge.get("operator_id"),
            "key_id": challenge.get("key_id"),
            "action": challenge.get("action"),
            "artifact_type": challenge.get("artifact_type"),
            "artifact_fingerprint": challenge.get("artifact_fingerprint"),
            "signature_fingerprint": signature_fingerprint,
            "blockers": list(dict.fromkeys(blockers)),
            "operator_identity_verified": False,
            "authorizes_execution": False,
            "safety": _safety_flags(),
        }
        attempt_id = _fingerprint(payload_core)
        existing = self._db.list_events_sync(
            event_type=OPERATOR_APPROVAL_REJECTED_EVENT_TYPE,
            entity_type=OPERATOR_APPROVAL_REJECTED_ENTITY_TYPE,
            entity_id=attempt_id,
            source=OPERATOR_APPROVAL_REJECTED_SOURCE,
            limit=1,
        )
        if not existing:
            self._db.append_event_sync(
                event_type=OPERATOR_APPROVAL_REJECTED_EVENT_TYPE,
                timestamp=_aware_utc(self._clock()).isoformat(),
                entity_type=OPERATOR_APPROVAL_REJECTED_ENTITY_TYPE,
                entity_id=attempt_id,
                source=OPERATOR_APPROVAL_REJECTED_SOURCE,
                source_ref=str(challenge.get("challenge_id") or ""),
                payload={**payload_core, "attempt_id": attempt_id},
            )
            existing = self._db.list_events_sync(
                event_type=OPERATOR_APPROVAL_REJECTED_EVENT_TYPE,
                entity_type=OPERATOR_APPROVAL_REJECTED_ENTITY_TYPE,
                entity_id=attempt_id,
                source=OPERATOR_APPROVAL_REJECTED_SOURCE,
                limit=1,
            )
        if not existing:
            raise RuntimeError("rejected operator approval was not audited")
        return _event_response(existing[0], reused=False)


def resolve_operator_approval(
    *,
    db: Any,
    trusted_identities: list[Any] | tuple[Any, ...],
    approval_id: str,
    expected_action: str,
    expected_artifact_type: str,
    expected_artifact_fingerprint: str,
    clock: Callable[[], datetime] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    return OperatorApprovalService(
        db=db,
        trusted_identities=trusted_identities,
        clock=clock,
    ).resolve_approval(
        approval_id=approval_id,
        expected_action=expected_action,
        expected_artifact_type=expected_artifact_type,
        expected_artifact_fingerprint=expected_artifact_fingerprint,
    )


def resolve_operator_approval_with_proof(
    *,
    db: Any,
    trusted_identities: list[Any] | tuple[Any, ...],
    approval_id: str,
    proof_signature_base64: str,
    expected_action: str,
    expected_artifact_type: str,
    expected_artifact_fingerprint: str,
    clock: Callable[[], datetime] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    return OperatorApprovalService(
        db=db,
        trusted_identities=trusted_identities,
        clock=clock,
    ).resolve_approval_with_proof(
        approval_id=approval_id,
        proof_signature_base64=proof_signature_base64,
        expected_action=expected_action,
        expected_artifact_type=expected_artifact_type,
        expected_artifact_fingerprint=expected_artifact_fingerprint,
    )
