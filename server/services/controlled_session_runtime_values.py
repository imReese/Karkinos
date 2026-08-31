"""Pure normalization and response projections for runtime-session authority."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION,
)

FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
SALT_PATTERN = re.compile(r"^[a-f0-9]{32,128}$")


def session_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = json_object(row.get("payload_json"))
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "session_id": str(row.get("session_id") or payload.get("session_id") or ""),
        "session_fingerprint": str(
            row.get("session_fingerprint") or payload.get("session_fingerprint") or ""
        ),
        "issuance_fingerprint": str(
            row.get("issuance_fingerprint") or payload.get("issuance_fingerprint") or ""
        ),
        "reservation_id": str(
            row.get("reservation_id") or payload.get("reservation_id") or ""
        ),
        "attestation_id": str(
            row.get("attestation_id") or payload.get("attestation_id") or ""
        ),
        "envelope_fingerprint": str(
            row.get("envelope_fingerprint") or payload.get("envelope_fingerprint") or ""
        ),
        "authorization_id": str(
            row.get("authorization_id") or payload.get("authorization_id") or ""
        ),
        "account_alias": str(
            row.get("account_alias") or payload.get("account_alias") or ""
        ),
        "strategy_id": str(row.get("strategy_id") or payload.get("strategy_id") or ""),
        "order_ids": json_list(
            row.get("order_ids_json") or payload.get("order_ids") or []
        ),
        "effective_at": str(
            row.get("effective_at") or payload.get("effective_at") or ""
        ),
        "expires_at": str(row.get("expires_at") or payload.get("expires_at") or ""),
        "max_order_rate_per_minute": int(
            row.get("max_order_rate_per_minute")
            or payload.get("max_order_rate_per_minute")
            or 0
        ),
        "status": str(row.get("status") or payload.get("status") or "not_found"),
        "persisted": bool(row),
        "reused": reused,
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
        "raw_token_stored": False,
        "session_token": "",
        "automatic_resume_enabled": False,
        "broker_submission_enabled": False,
        "safety": safety_flags(runtime_authority=False),
    }


def revocation_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = json_object(row.get("payload_json"))
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "persisted": bool(row),
        "reused": reused,
        "revoked_at": str(row.get("revoked_at") or ""),
        "broker_submission_enabled": False,
        "safety": safety_flags(runtime_authority=False),
    }


def replacement_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = json_object(row.get("payload_json"))
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "replacement_id": str(
            row.get("replacement_id") or payload.get("replacement_id") or ""
        ),
        "replacement_fingerprint": str(
            row.get("replacement_fingerprint")
            or payload.get("replacement_fingerprint")
            or ""
        ),
        "predecessor_session_id": str(
            row.get("predecessor_session_id")
            or payload.get("predecessor_session_id")
            or ""
        ),
        "replacement_session_id": str(
            row.get("replacement_session_id")
            or payload.get("replacement_session_id")
            or ""
        ),
        "recovery_snapshot_ids": json_list(
            row.get("recovery_snapshot_ids_json")
            or payload.get("recovery_snapshot_ids")
            or []
        ),
        "persisted": bool(row),
        "reused": reused,
        "reviewed_at": str(row.get("reviewed_at") or ""),
        "session_token": "",
        "automatic_resume_enabled": False,
        "broker_submission_enabled": False,
        "safety": safety_flags(runtime_authority=False),
    }


def blocked_session(session_id: str, blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION,
        "status": "blocked",
        "session_id": session_id,
        "session_fingerprint": "",
        "reservation_id": "",
        "blockers": list(dict.fromkeys(blockers)),
        "session_authority_verified": False,
        "budget_reservation_verified": False,
        "upstream_gates_clear": False,
        "kill_switch_clear": False,
        "persistent_session_state_verified": False,
        "runtime_authentication_verified": False,
        "runtime_rate_limiter_enabled": False,
        "broker_submission_enabled": False,
        "safety": safety_flags(runtime_authority=False),
    }


def token_hash(token: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{token}".encode("utf-8")).hexdigest()


def fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def json_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


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


def safety_flags(*, runtime_authority: bool) -> dict[str, bool]:
    return {
        "runtime_session_authority_enabled": runtime_authority,
        "does_not_contact_broker": True,
        "does_not_submit_or_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_store_raw_session_token": True,
        "does_not_auto_resume_renew_or_expand": True,
        "does_not_grant_or_scale_capital_authority": True,
    }
