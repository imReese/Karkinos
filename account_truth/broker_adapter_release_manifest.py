"""Validated broker-adapter release manifests and review value contracts."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

BROKER_ADAPTER_RELEASE_MANIFEST_SCHEMA_VERSION = (
    "karkinos.broker_adapter_release_manifest.v1"
)
BROKER_ADAPTER_RELEASE_PREVIEW_SCHEMA_VERSION = (
    "karkinos.broker_adapter_release_preview.v1"
)
BROKER_ADAPTER_RELEASE_REVIEW_SCHEMA_VERSION = (
    "karkinos.broker_adapter_release_review.v1"
)
BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT = (
    "review_broker_adapter_release_without_registration_or_execution_authority"
)
MAX_BROKER_ADAPTER_RELEASE_MANIFEST_BYTES = 512 * 1024

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "release_evidence_ref",
        "collector_id",
        "deployment_id",
        "collector_version",
        "deployment_fingerprint",
        "provider",
        "gateway_id",
        "account_alias",
        "adapter_authorization_ref",
        "collection_modes",
        "capabilities",
        "boundaries",
        "review_refs",
        "limitations",
    }
)
_CAPABILITY_FIELDS = frozenset(
    {
        "can_read_account",
        "can_read_cash",
        "can_read_positions",
        "can_read_orders",
        "can_read_fills",
        "can_read_market_session",
        "can_read_heartbeat",
        "can_submit_orders",
        "can_cancel_orders",
    }
)
_EXPECTED_BOUNDARIES = {
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
}
_BOUNDARY_FIELDS = frozenset(_EXPECTED_BOUNDARIES)
_REVIEW_REF_FIELDS = frozenset(
    {
        "adapter_adr",
        "capability_matrix",
        "threat_model",
        "deployment_runbook",
        "rollback_runbook",
        "privacy_review",
    }
)
_LIVE_COLLECTION_MODES = frozenset({"callback", "poll"})
_REVIEW_DECISIONS = frozenset({"accepted", "rejected", "revoked"})
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "private_key",
    "api_key",
)


def preview_broker_adapter_release_manifest(
    content: str | bytes,
    *,
    source_name: str = "",
) -> dict[str, Any]:
    """Normalize one manifest without registering an adapter or contacting a broker."""

    raw = content if isinstance(content, bytes) else str(content).encode("utf-8")
    record_blockers: list[str] = []
    blockers: list[str] = []
    text = ""
    if len(raw) > MAX_BROKER_ADAPTER_RELEASE_MANIFEST_BYTES:
        record_blockers.append("broker_adapter_release_manifest_too_large")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            record_blockers.append("broker_adapter_release_manifest_not_utf8")

    data: dict[str, Any] = {}
    if not record_blockers:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            record_blockers.append("broker_adapter_release_manifest_json_invalid")
        else:
            if isinstance(parsed, dict):
                data = parsed
            else:
                record_blockers.append("broker_adapter_release_manifest_not_object")

    if _contains_sensitive_key(data):
        record_blockers.append("broker_adapter_release_auth_material_not_allowed")
    _reject_unknown_fields(data, _MANIFEST_FIELDS, "manifest", record_blockers)

    schema_version = str(data.get("schema_version") or "")
    if schema_version != BROKER_ADAPTER_RELEASE_MANIFEST_SCHEMA_VERSION:
        record_blockers.append("broker_adapter_release_manifest_schema_unsupported")

    identities = {
        field: _id(data.get(field), field, record_blockers)
        for field in (
            "release_evidence_ref",
            "collector_id",
            "deployment_id",
            "collector_version",
            "provider",
            "gateway_id",
            "account_alias",
            "adapter_authorization_ref",
        )
    }
    identities["provider"] = identities["provider"].lower()
    deployment_fingerprint = (
        str(data.get("deployment_fingerprint") or "").strip().lower()
    )
    if not _FINGERPRINT_PATTERN.fullmatch(deployment_fingerprint):
        record_blockers.append("broker_adapter_release_deployment_fingerprint_invalid")

    collection_modes = _string_list(
        data.get("collection_modes"),
        field="collection_modes",
        blockers=record_blockers,
    )
    collection_modes = sorted(dict.fromkeys(item.lower() for item in collection_modes))
    if not collection_modes or any(
        item not in _LIVE_COLLECTION_MODES for item in collection_modes
    ):
        record_blockers.append("broker_adapter_release_collection_modes_invalid")

    capabilities = _boolean_object(
        data.get("capabilities"),
        allowed=_CAPABILITY_FIELDS,
        field="capabilities",
        blockers=record_blockers,
    )
    boundaries = _boolean_object(
        data.get("boundaries"),
        allowed=_BOUNDARY_FIELDS,
        field="boundaries",
        blockers=record_blockers,
    )
    review_refs = _reference_object(data.get("review_refs"), record_blockers)
    limitations = _string_list(
        data.get("limitations", []),
        field="limitations",
        blockers=record_blockers,
        allow_empty=True,
    )

    if capabilities and (
        capabilities.get("can_submit_orders") is not False
        or capabilities.get("can_cancel_orders") is not False
    ):
        blockers.append("broker_adapter_release_write_capability_present")
    for field, expected in _EXPECTED_BOUNDARIES.items():
        if boundaries and boundaries.get(field) is not expected:
            blockers.append(f"broker_adapter_release_boundary_violation:{field}")

    unique_record_blockers = list(dict.fromkeys(record_blockers))
    unique_blockers = list(dict.fromkeys([*record_blockers, *blockers]))
    core = {
        "schema_version": BROKER_ADAPTER_RELEASE_MANIFEST_SCHEMA_VERSION,
        **identities,
        "deployment_fingerprint": deployment_fingerprint,
        "collection_modes": collection_modes,
        "capabilities": capabilities,
        "boundaries": boundaries,
        "review_refs": review_refs,
        "limitations": limitations,
    }
    manifest_fingerprint = _fingerprint(core)
    recordable = bool(
        not unique_record_blockers
        and all(str(value or "") for value in identities.values())
        and deployment_fingerprint
        and collection_modes
        and capabilities
        and boundaries
        and review_refs
    )
    return {
        **core,
        "schema_version": BROKER_ADAPTER_RELEASE_PREVIEW_SCHEMA_VERSION,
        "manifest_fingerprint": manifest_fingerprint,
        "file_fingerprint": hashlib.sha256(raw).hexdigest(),
        "source_name": _sanitized_source_name(source_name),
        "validation_status": "pass" if not unique_blockers else "blocked",
        "recordable": recordable,
        "blockers": unique_blockers,
        "record_blockers": unique_record_blockers,
        **_safety_flags(),
    }


def _manifest_core(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": BROKER_ADAPTER_RELEASE_MANIFEST_SCHEMA_VERSION,
        "release_evidence_ref": str(value.get("release_evidence_ref") or ""),
        "collector_id": str(value.get("collector_id") or ""),
        "deployment_id": str(value.get("deployment_id") or ""),
        "collector_version": str(value.get("collector_version") or ""),
        "provider": str(value.get("provider") or ""),
        "gateway_id": str(value.get("gateway_id") or ""),
        "account_alias": str(value.get("account_alias") or ""),
        "adapter_authorization_ref": str(value.get("adapter_authorization_ref") or ""),
        "deployment_fingerprint": str(value.get("deployment_fingerprint") or ""),
        "collection_modes": list(value.get("collection_modes") or []),
        "capabilities": dict(value.get("capabilities") or {}),
        "boundaries": dict(value.get("boundaries") or {}),
        "review_refs": dict(value.get("review_refs") or {}),
        "limitations": list(value.get("limitations") or []),
    }


def _preview_integrity_blockers(preview: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    manifest_core = _manifest_core(preview)
    if str(preview.get("manifest_fingerprint") or "") != _fingerprint(manifest_core):
        blockers.append("broker_adapter_release_preview_fingerprint_drift")
    canonical = preview_broker_adapter_release_manifest(_json(manifest_core))
    for field in ("recordable", "validation_status", "blockers", "record_blockers"):
        if preview.get(field) != canonical.get(field):
            blockers.append(f"broker_adapter_release_preview_validation_drift:{field}")
    for field, expected in _safety_flags().items():
        if preview.get(field) is not expected:
            blockers.append(f"broker_adapter_release_preview_safety_drift:{field}")
    return list(dict.fromkeys(blockers))


def _verification_blocked(
    release_ref: str,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "review_id": "",
        "release_evidence_ref": release_ref,
        "manifest_fingerprint": "",
        "conformance_run_id": "",
        "conformance_report_fingerprint": "",
        "blockers": list(dict.fromkeys(blockers)),
        **_safety_flags(),
    }


def _rejection(preview: Mapping[str, Any], blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": BROKER_ADAPTER_RELEASE_REVIEW_SCHEMA_VERSION,
        "status": "rejected",
        "release_evidence_ref": str(preview.get("release_evidence_ref") or ""),
        "blockers": list(dict.fromkeys(blockers)),
        **_safety_flags(),
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "explicit_review_required": True,
        "provider_contacted": False,
        "adapter_registered": False,
        "default_registered": False,
        "broker_submission_enabled": False,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_mutate_risk_state": True,
        "does_not_mutate_kill_switch": True,
        "does_not_mutate_capital_authority": True,
        "authorizes_execution": False,
    }


def _boolean_object(
    value: Any,
    *,
    allowed: frozenset[str],
    field: str,
    blockers: list[str],
) -> dict[str, bool]:
    if not isinstance(value, dict):
        blockers.append(f"broker_adapter_release_{field}_invalid")
        return {}
    _reject_unknown_fields(value, allowed, field, blockers)
    result: dict[str, bool] = {}
    for name in sorted(allowed):
        item = value.get(name)
        if not isinstance(item, bool):
            blockers.append(f"broker_adapter_release_{field}_{name}_invalid")
            continue
        result[name] = item
    return result


def _reference_object(value: Any, blockers: list[str]) -> dict[str, str]:
    if not isinstance(value, dict):
        blockers.append("broker_adapter_release_review_refs_invalid")
        return {}
    _reject_unknown_fields(value, _REVIEW_REF_FIELDS, "review_refs", blockers)
    return {
        field: _id(value.get(field), f"review_refs_{field}", blockers)
        for field in sorted(_REVIEW_REF_FIELDS)
    }


def _string_list(
    value: Any,
    *,
    field: str,
    blockers: list[str],
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        blockers.append(f"broker_adapter_release_{field}_invalid")
        return []
    result = [str(item).strip() for item in value]
    if (
        (not allow_empty and not result)
        or len(result) > 50
        or any(not item or len(item) > 256 for item in result)
    ):
        blockers.append(f"broker_adapter_release_{field}_invalid")
    return result[:50]


def _id(value: Any, field: str, blockers: list[str]) -> str:
    normalized = str(value or "").strip()
    if not _ID_PATTERN.fullmatch(normalized):
        blockers.append(f"broker_adapter_release_{field}_invalid")
    return normalized


def _timestamp(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return ""
    return parsed.astimezone(UTC).isoformat()


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS)
            or _contains_sensitive_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _reject_unknown_fields(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    prefix: str,
    blockers: list[str],
) -> None:
    for key in sorted(set(value) - allowed):
        blockers.append(f"broker_adapter_release_{prefix}_field_unsupported:{key}")


def _sanitized_source_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name or "/" in name or "\\" in name:
        return "broker adapter release manifest"
    return name[:128]


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _row_text(row: sqlite3.Row, field: str) -> str:
    return str(row[field]) if field in row.keys() else ""


EXPECTED_BOUNDARIES = _EXPECTED_BOUNDARIES
LIVE_COLLECTION_MODES = _LIVE_COLLECTION_MODES
REVIEW_DECISIONS = _REVIEW_DECISIONS
manifest_core = _manifest_core
preview_integrity_blockers = _preview_integrity_blockers
verification_blocked = _verification_blocked
rejection = _rejection
safety_flags = _safety_flags
normalize_id = _id
timestamp = _timestamp
fingerprint = _fingerprint
json_text = _json
json_object = _json_object
row_text = _row_text
