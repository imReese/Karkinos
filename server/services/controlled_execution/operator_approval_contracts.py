"""Pure contracts and validation helpers for signed operator approvals."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

OPERATOR_APPROVAL_CHALLENGE_SCHEMA_VERSION = "karkinos.operator_approval_challenge.v1"
OPERATOR_APPROVAL_SCHEMA_VERSION = "karkinos.operator_approval.v1"
OPERATOR_APPROVAL_STATUS_SCHEMA_VERSION = "karkinos.operator_approval_status.v1"

OPERATOR_APPROVAL_ACTIONS = frozenset(
    {
        "attest_per_order_dossier",
        "attest_controlled_session_envelope",
        "accept_broker_connector_soak_promotion",
        "review_broker_adapter_release",
        "issue_controlled_broker_write_release",
        "revoke_controlled_broker_write_release",
        "issue_controlled_session",
        "replace_paused_controlled_session",
        "revoke_controlled_session",
        "submit_confirmed_broker_order",
        "query_unknown_controlled_broker_submission",
        "cancel_exact_controlled_broker_order",
        "query_exact_broker_cancellation_outcome",
        "clear_controlled_submission_reconciliation",
        "post_controlled_submission_ledger",
        "reverse_controlled_submission_ledger_posting",
    }
)
OPERATOR_APPROVAL_ARTIFACT_TYPES = frozenset(
    {
        "per_order_dossier",
        "controlled_session_envelope",
        "broker_connector_soak_promotion_dossier",
        "broker_adapter_release_review_dossier",
        "controlled_broker_write_release_dossier",
        "controlled_broker_write_release_revocation",
        "controlled_session_issuance",
        "controlled_session_replacement",
        "controlled_session_revocation",
        "controlled_broker_submission",
        "controlled_broker_submission_recovery",
        "controlled_broker_cancellation",
        "controlled_broker_cancellation_recovery",
        "controlled_submission_reconciliation_clearance",
        "controlled_submission_ledger_posting",
        "controlled_submission_ledger_correction",
    }
)
OPERATOR_APPROVAL_ACTION_ARTIFACT_TYPES = {
    "attest_per_order_dossier": "per_order_dossier",
    "attest_controlled_session_envelope": "controlled_session_envelope",
    "accept_broker_connector_soak_promotion": (
        "broker_connector_soak_promotion_dossier"
    ),
    "review_broker_adapter_release": "broker_adapter_release_review_dossier",
    "issue_controlled_broker_write_release": (
        "controlled_broker_write_release_dossier"
    ),
    "revoke_controlled_broker_write_release": (
        "controlled_broker_write_release_revocation"
    ),
    "issue_controlled_session": "controlled_session_issuance",
    "replace_paused_controlled_session": "controlled_session_replacement",
    "revoke_controlled_session": "controlled_session_revocation",
    "submit_confirmed_broker_order": "controlled_broker_submission",
    "query_unknown_controlled_broker_submission": (
        "controlled_broker_submission_recovery"
    ),
    "cancel_exact_controlled_broker_order": "controlled_broker_cancellation",
    "query_exact_broker_cancellation_outcome": (
        "controlled_broker_cancellation_recovery"
    ),
    "clear_controlled_submission_reconciliation": (
        "controlled_submission_reconciliation_clearance"
    ),
    "post_controlled_submission_ledger": "controlled_submission_ledger_posting",
    "reverse_controlled_submission_ledger_posting": (
        "controlled_submission_ledger_correction"
    ),
}

DEFAULT_CHALLENGE_TTL_SECONDS = 180
MIN_CHALLENGE_TTL_SECONDS = 30
MAX_CHALLENGE_TTL_SECONDS = 300
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def is_valid_operator_identity_id(value: str) -> bool:
    return _ID_PATTERN.fullmatch(value) is not None


def is_valid_operator_fingerprint(value: str) -> bool:
    return _FINGERPRINT_PATTERN.fullmatch(value) is not None


def normalize_identities(values: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for value in values or ():
        read = (
            value.get
            if isinstance(value, dict)
            else lambda key, default=None: getattr(value, key, default)
        )
        operator_id = str(read("operator_id", "") or "").strip()
        key_id = str(read("key_id", "") or "").strip()
        algorithm = str(read("algorithm", "ed25519") or "").strip().lower()
        public_key_base64 = str(read("public_key_base64", "") or "").strip()
        enabled = read("enabled", False)
        if not is_valid_operator_identity_id(
            operator_id
        ) or not is_valid_operator_identity_id(key_id):
            raise ValueError("trusted operator identity id invalid")
        if algorithm != "ed25519":
            raise ValueError("trusted operator identity algorithm must be ed25519")
        if not isinstance(enabled, bool):
            raise ValueError("trusted operator identity enabled must be boolean")
        try:
            public_key = base64.b64decode(public_key_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("trusted operator public key base64 invalid") from exc
        if len(public_key) != 32:
            raise ValueError("trusted operator Ed25519 public key must be 32 bytes")
        identity_key = (operator_id, key_id)
        if identity_key in seen:
            raise ValueError("trusted operator identity duplicated")
        seen.add(identity_key)
        results.append(
            {
                "operator_id": operator_id,
                "key_id": key_id,
                "algorithm": algorithm,
                "public_key": public_key,
                "public_key_fingerprint": hashlib.sha256(public_key).hexdigest(),
                "enabled": enabled,
            }
        )
    return results


def challenge_input_blockers(
    *,
    action: str,
    artifact_type: str,
    artifact_fingerprint: str,
    ttl_seconds: int,
) -> list[str]:
    blockers: list[str] = []
    if action not in OPERATOR_APPROVAL_ACTIONS:
        blockers.append("operator_approval_action_unsupported")
    if artifact_type not in OPERATOR_APPROVAL_ARTIFACT_TYPES:
        blockers.append("operator_approval_artifact_type_unsupported")
    if OPERATOR_APPROVAL_ACTION_ARTIFACT_TYPES.get(action) != artifact_type:
        blockers.append("operator_approval_action_artifact_mismatch")
    if not is_valid_operator_fingerprint(artifact_fingerprint):
        blockers.append("operator_approval_artifact_fingerprint_invalid")
    if ttl_seconds < MIN_CHALLENGE_TTL_SECONDS or ttl_seconds > (
        MAX_CHALLENGE_TTL_SECONDS
    ):
        blockers.append("operator_approval_ttl_out_of_range")
    return blockers


def approval_resolution(
    approval_id: str,
    approval: dict[str, Any],
    blockers: list[str],
) -> tuple[dict[str, Any], list[str]]:
    unique_blockers = list(dict.fromkeys(blockers))
    result = {
        "status": "verified" if not unique_blockers else "blocked",
        "approval_id": approval_id,
        "operator_id": str(approval.get("operator_id") or ""),
        "key_id": str(approval.get("key_id") or ""),
        "public_key_fingerprint": str(approval.get("public_key_fingerprint") or ""),
        "action": str(approval.get("action") or ""),
        "artifact_type": str(approval.get("artifact_type") or ""),
        "artifact_fingerprint": str(approval.get("artifact_fingerprint") or ""),
        "issued_at": str(approval.get("issued_at") or ""),
        "expires_at": str(approval.get("expires_at") or ""),
        "verified_at": str(approval.get("verified_at") or ""),
        "operator_identity_verified": not unique_blockers,
        "blockers": unique_blockers,
        "authorizes_execution": False,
        "evidence_ref": f"operator_approval:{approval_id}" if approval_id else "",
        "safety": safety_flags(),
    }
    return result, unique_blockers


def public_approval_event(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "signature_base64"}


def parse_timestamp(value: Any) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def event_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    return {
        "event_id": int(row["id"]),
        "recorded_at": row["timestamp"],
        "created_at": row["created_at"],
        "persisted": True,
        "reused": reused,
        **json_object(row.get("payload_json")),
    }


def safety_flags() -> dict[str, bool]:
    return {
        "stores_private_keys": False,
        "stores_broker_credentials": False,
        "does_not_issue_or_expand_authority": True,
        "does_not_enable_or_resume_execution": True,
        "does_not_reserve_or_consume_budget": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_contact_broker": True,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
    }
