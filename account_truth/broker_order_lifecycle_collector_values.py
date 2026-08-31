"""Canonical normalization and integrity helpers for lifecycle collectors."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from account_truth.broker_order_lifecycle_collector_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_PREVIEW_SCHEMA_VERSION,
    BROKER_ORDER_LIFECYCLE_COLLECTOR_RUN_SCHEMA_VERSION,
)
from account_truth.broker_order_lifecycle_collector_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_SENSITIVE_KEY_PARTS as _SENSITIVE_KEY_PARTS,
)

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def collector_fingerprint_is_valid(value: str) -> bool:
    """Return whether an evidence fingerprint has canonical SHA-256 form."""

    return _FINGERPRINT_PATTERN.fullmatch(value) is not None


def collector_preview_integrity_blockers(preview: dict[str, Any]) -> list[str]:
    core_fields = (
        "schema_version",
        "run_id",
        "collector_id",
        "deployment_id",
        "collector_version",
        "deployment_fingerprint",
        "release_evidence_ref",
        "release_review_status",
        "adapter_authorization_ref",
        "provider",
        "gateway_id",
        "account_alias",
        "account_ref_hash",
        "collection_mode",
        "source_contact_status",
        "connection_status",
        "batch_status",
        "cursor_previous",
        "cursor_current",
        "captured_at",
        "event_count",
        "callbacks_received",
        "duplicate_callbacks_dropped",
        "out_of_order_callbacks_dropped",
        "lifecycle_evidence_fingerprint",
        "blockers",
    )
    core = {field: preview.get(field) for field in core_fields}
    core["schema_version"] = BROKER_ORDER_LIFECYCLE_COLLECTOR_RUN_SCHEMA_VERSION
    blockers: list[str] = []
    if str(preview.get("batch_fingerprint") or "") != collector_fingerprint(core):
        blockers.append("broker_order_lifecycle_collector_preview_fingerprint_drift")
    evidence_core = dict(core)
    evidence_core.pop("run_id")
    if str(preview.get("evidence_fingerprint") or "") != collector_fingerprint(
        evidence_core
    ):
        blockers.append(
            "broker_order_lifecycle_collector_preview_evidence_fingerprint_drift"
        )
    for field, expected in collector_safety_flags().items():
        if preview.get(field) is not expected:
            blockers.append(
                f"broker_order_lifecycle_collector_preview_safety_drift:{field}"
            )
    return blockers


def collector_rejection_evidence(
    preview: dict[str, Any], blockers: list[str]
) -> dict[str, Any]:
    return {
        "schema_version": BROKER_ORDER_LIFECYCLE_COLLECTOR_RUN_SCHEMA_VERSION,
        "status": "rejected",
        "run_id": str(preview.get("run_id") or ""),
        "blockers": list(dict.fromkeys(blockers)),
        **collector_safety_flags(),
    }


def collector_scope_key(value: dict[str, Any]) -> str:
    return collector_fingerprint(
        {
            "provider": str(value.get("provider") or ""),
            "gateway_id": str(value.get("gateway_id") or ""),
            "account_alias": str(value.get("account_alias") or ""),
        }
    )


def collector_safety_flags() -> dict[str, bool]:
    return {
        "explicit_ingestion_required": True,
        "provider_contacted": False,
        "broker_submission_enabled": False,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_fills": True,
        "does_not_mutate_production_ledger": True,
        "does_not_mutate_risk_state": True,
        "does_not_mutate_kill_switch": True,
        "does_not_mutate_capital_authority": True,
        "does_not_release_submission_interlock": True,
        "authorizes_execution": False,
        "default_registered": False,
    }


def normalize_collector_id(value: Any, field: str, blockers: list[str]) -> str:
    normalized = str(value or "").strip()
    if not _ID_PATTERN.fullmatch(normalized):
        blockers.append(f"broker_order_lifecycle_collector_{field}_invalid")
    return normalized


def normalize_collector_nonnegative_int(
    value: Any, field: str, blockers: list[str]
) -> int:
    if isinstance(value, bool):
        blockers.append(f"broker_order_lifecycle_collector_{field}_invalid")
        return 0
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        blockers.append(f"broker_order_lifecycle_collector_{field}_invalid")
        return 0
    if normalized < 0 or str(value).strip() != str(normalized):
        blockers.append(f"broker_order_lifecycle_collector_{field}_invalid")
    return max(0, normalized)


def normalize_collector_timestamp(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return ""
    return parsed.astimezone(UTC).isoformat()


def aware_collector_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def collector_contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS)
            or collector_contains_sensitive_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(collector_contains_sensitive_key(item) for item in value)
    return False


def reject_collector_unknown_fields(
    value: dict[str, Any],
    allowed: frozenset[str],
    prefix: str,
    blockers: list[str],
) -> None:
    for key in sorted(set(value) - allowed):
        blockers.append(
            f"broker_order_lifecycle_collector_{prefix}_field_unsupported:{key}"
        )


def sanitize_collector_source_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name or "/" in name or "\\" in name:
        return "broker order lifecycle collector batch"
    return name[:128]


def collector_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def collector_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def collector_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def collector_json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
