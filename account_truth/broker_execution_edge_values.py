"""Value normalization for deterministic execution-edge evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REVIEW_REF_FIELDS = frozenset(
    {
        "write_adapter_adr",
        "capability_matrix",
        "threat_model",
        "deployment_runbook",
        "rollback_runbook",
        "incident_runbook",
        "privacy_review",
    }
)
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "private_key",
    "api_key",
)


def _boolean_object(
    value: Any,
    *,
    allowed: frozenset[str],
    field: str,
    blockers: list[str],
) -> dict[str, bool]:
    if not isinstance(value, dict):
        blockers.append(f"broker_execution_edge_{field}_invalid")
        return {}
    _reject_unknown_fields(value, allowed, field, blockers)
    normalized: dict[str, bool] = {}
    for key in allowed:
        if not isinstance(value.get(key), bool):
            blockers.append(f"broker_execution_edge_{field}_{key}_invalid")
        else:
            normalized[key] = bool(value[key])
    return normalized


def _reference_object(value: Any, blockers: list[str]) -> dict[str, str]:
    if not isinstance(value, dict):
        blockers.append("broker_execution_edge_review_refs_invalid")
        return {}
    _reject_unknown_fields(value, _REVIEW_REF_FIELDS, "review_refs", blockers)
    normalized: dict[str, str] = {}
    for key in _REVIEW_REF_FIELDS:
        normalized[key] = _id(value.get(key), f"review_ref_{key}", blockers)
    return normalized


def _string_list(value: Any, blockers: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        blockers.append("broker_execution_edge_limitations_invalid")
        return []
    result: list[str] = []
    for item in value:
        normalized = str(item or "").strip()
        if not normalized or len(normalized) > 512:
            blockers.append("broker_execution_edge_limitation_invalid")
        else:
            result.append(normalized)
    return list(dict.fromkeys(result))


def _id(value: Any, field: str, blockers: list[str]) -> str:
    normalized = str(value or "").strip()
    if not _ID_PATTERN.fullmatch(normalized):
        blockers.append(f"broker_execution_edge_{field}_invalid")
    return normalized


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
        blockers.append(f"broker_execution_edge_{prefix}_field_unsupported:{key}")


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


FINGERPRINT_PATTERN = _FINGERPRINT_PATTERN
boolean_object = _boolean_object
reference_object = _reference_object
string_list = _string_list
identifier = _id
contains_sensitive_key = _contains_sensitive_key
reject_unknown_fields = _reject_unknown_fields
fingerprint = _fingerprint
json_value = _json
json_object = _json_object
