"""Pure policy and response shaping for controlled broker write releases."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from server.contracts.controlled_broker_write_release import (
    CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_WRITE_RELEASE_FINGERPRINT_PATTERN,
    CONTROLLED_BROKER_WRITE_RELEASE_ID_PATTERN,
    CONTROLLED_BROKER_WRITE_RELEASE_ISSUE_CLOCK_SKEW_SECONDS,
    CONTROLLED_BROKER_WRITE_RELEASE_MAX_SECONDS,
    CONTROLLED_BROKER_WRITE_RELEASE_OWNER_REVIEW_REF_FIELDS,
    CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_REASONS,
    CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_SCHEMA_VERSION,
    CONTROLLED_BROKER_WRITE_RELEASE_SCHEMA_VERSION,
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


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


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def blocked_source(blocker: str) -> dict[str, Any]:
    return {"status": "blocked", "blockers": [blocker]}


def normalize_owner_review_refs(
    value: Mapping[str, Any],
) -> tuple[dict[str, str], list[str]]:
    raw = dict(value)
    blockers: list[str] = []
    expected = set(CONTROLLED_BROKER_WRITE_RELEASE_OWNER_REVIEW_REF_FIELDS)
    blockers.extend(
        f"controlled_broker_write_release_owner_review_ref_unsupported:{key}"
        for key in sorted(set(raw) - expected)
    )
    normalized: dict[str, str] = {}
    for field in CONTROLLED_BROKER_WRITE_RELEASE_OWNER_REVIEW_REF_FIELDS:
        item = str(raw.get(field) or "").strip()
        normalized[field] = item
        if not CONTROLLED_BROKER_WRITE_RELEASE_ID_PATTERN.fullmatch(item):
            blockers.append(
                f"controlled_broker_write_release_owner_review_ref_invalid:{field}"
            )
    return normalized, blockers


def normalize_release_window(
    effective_at: str,
    expires_at: str,
    *,
    now: datetime,
    issuance: bool,
) -> tuple[str, str, list[str]]:
    effective = parse_timestamp(effective_at)
    expires = parse_timestamp(expires_at)
    blockers: list[str] = []
    if effective is None or expires is None or expires <= effective:
        blockers.append("controlled_broker_write_release_window_invalid")
    else:
        duration = int((expires - effective).total_seconds())
        if duration > CONTROLLED_BROKER_WRITE_RELEASE_MAX_SECONDS:
            blockers.append("controlled_broker_write_release_window_too_wide")
        if now < effective:
            blockers.append("controlled_broker_write_release_not_effective")
        if now >= expires:
            blockers.append("controlled_broker_write_release_expired")
        if issuance and now - effective > timedelta(
            seconds=CONTROLLED_BROKER_WRITE_RELEASE_ISSUE_CLOCK_SKEW_SECONDS
        ):
            blockers.append("controlled_broker_write_release_effective_at_too_old")
    return (
        effective.isoformat() if effective is not None else str(effective_at or ""),
        expires.isoformat() if expires is not None else str(expires_at or ""),
        blockers,
    )


def release_request_blockers(
    *,
    dossier: Mapping[str, Any],
    dossier_fingerprint: str,
    operator_label: str,
    acknowledgement: str,
) -> list[str]:
    blockers = list(dossier.get("review_blockers") or [])
    if str(dossier_fingerprint or "") != dossier.get("dossier_fingerprint"):
        blockers.append("controlled_broker_write_release_dossier_fingerprint_mismatch")
    if acknowledgement != CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT:
        blockers.append("controlled_broker_write_release_acknowledgement_mismatch")
    if not CONTROLLED_BROKER_WRITE_RELEASE_ID_PATTERN.fullmatch(
        str(operator_label or "").strip()
    ):
        blockers.append("controlled_broker_write_release_operator_invalid")
    return list(dict.fromkeys(blockers))


def operator_identity_blockers(
    payload: Mapping[str, Any],
    trusted_operator_identities: tuple[Any, ...],
) -> list[str]:
    operator_id = str(payload.get("operator_id") or "")
    key_id = str(payload.get("operator_key_id") or "")
    expected_fingerprint = str(payload.get("operator_public_key_fingerprint") or "")
    for identity in trusted_operator_identities:
        read = (
            identity.get
            if isinstance(identity, dict)
            else lambda key, default=None: getattr(identity, key, default)
        )
        if (
            str(read("operator_id", "") or "") == operator_id
            and str(read("key_id", "") or "") == key_id
        ):
            if read("enabled", False) is not True:
                return ["controlled_broker_write_release_operator_disabled"]
            try:
                public_key = base64.b64decode(
                    str(read("public_key_base64", "") or ""), validate=True
                )
            except Exception:
                return ["controlled_broker_write_release_operator_key_invalid"]
            if hashlib.sha256(public_key).hexdigest() != expected_fingerprint:
                return ["controlled_broker_write_release_operator_key_changed"]
            return []
    return ["controlled_broker_write_release_operator_not_trusted"]


def release_row_response(row: Mapping[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = json_object(row.get("payload_json"))
    return {
        **payload,
        "status": "recorded_expiring_manual_each_order_release",
        "evidence_fingerprint": str(row.get("evidence_fingerprint") or ""),
        "created_at": str(row.get("created_at") or ""),
        "persisted": True,
        "reused": reused,
        "broker_contact_performed": False,
        "adapter_registered": False,
        "broker_submission_performed": False,
        "broker_cancellation_performed": False,
    }


def revocation_row_response(row: Mapping[str, Any], *, reused: bool) -> dict[str, Any]:
    return {
        **json_object(row.get("payload_json")),
        "revocation_id": str(row.get("revocation_id") or ""),
        "status": "revoked",
        "created_at": str(row.get("created_at") or ""),
        "persisted": True,
        "reused": reused,
    }


def build_revocation_preview(
    *,
    release_evidence_id: str,
    reason_code: str,
    release_row: Mapping[str, Any] | None,
    revocation_row: Mapping[str, Any] | None,
    read_blockers: list[str] | None = None,
) -> dict[str, Any]:
    release_id = str(release_evidence_id or "").strip().lower()
    reason = str(reason_code or "").strip().lower()
    blockers = list(read_blockers or [])
    if not CONTROLLED_BROKER_WRITE_RELEASE_FINGERPRINT_PATTERN.fullmatch(release_id):
        blockers.append("controlled_broker_write_release_id_invalid")
    if reason not in CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_REASONS:
        blockers.append("controlled_broker_write_release_revocation_reason_invalid")
    if release_row is None:
        blockers.append("controlled_broker_write_release_not_found")
    stored = release_row_response(release_row, reused=False) if release_row else {}
    core = {
        "schema_version": CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_SCHEMA_VERSION,
        "action": "revoke_controlled_broker_write_release",
        "release_evidence_id": release_id,
        "release_evidence_fingerprint": str(stored.get("evidence_fingerprint") or ""),
        "reason_code": reason,
    }
    revocation_fingerprint = fingerprint(core)
    if (
        revocation_row is not None
        and str(revocation_row.get("revocation_fingerprint") or "")
        != revocation_fingerprint
    ):
        blockers.append("controlled_broker_write_release_already_revoked")
    unique_blockers = list(dict.fromkeys(blockers))
    return {
        **core,
        "revocation_fingerprint": revocation_fingerprint,
        "status": (
            "already_revoked"
            if revocation_row is not None
            else ("ready_for_signature" if not unique_blockers else "blocked")
        ),
        "ready": not unique_blockers and revocation_row is None,
        "blockers": unique_blockers,
        "required_operator_approval": {
            "action": "revoke_controlled_broker_write_release",
            "artifact_type": "controlled_broker_write_release_revocation",
            "artifact_fingerprint": revocation_fingerprint,
        },
        "broker_contact_performed": False,
        "broker_submission_performed": False,
        "broker_cancellation_performed": False,
        "capital_authority_changed": False,
        "resume_enabled": False,
    }


def blocked_resolution(release_evidence_id: str, blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": CONTROLLED_BROKER_WRITE_RELEASE_SCHEMA_VERSION,
        "status": "blocked",
        "release_evidence_id": release_evidence_id,
        "evidence_fingerprint": "",
        "operator_identity_verified": False,
        "execution_mode": "manual_each_order",
        "automatic_execution_allowed": False,
        "strategy_direct_submission_allowed": False,
        "broker_agreement_reviewed": False,
        "connector_tested": False,
        "program_trading_reporting_reviewed": False,
        "risk_controls_reviewed": False,
        "blockers": list(dict.fromkeys(blockers)),
        "provider_contact_performed": False,
        "adapter_registered": False,
        "broker_submission_performed": False,
        "broker_cancellation_performed": False,
        "authorizes_order_submission_by_itself": False,
        "does_not_grant_capital_authority": True,
    }
