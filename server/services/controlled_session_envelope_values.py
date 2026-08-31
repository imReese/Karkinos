"""Pure normalization and response projections for session envelopes."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from server.contracts.controlled_session_envelope import (
    CONTROLLED_SESSION_ATTESTATION_SCHEMA_VERSION,
)

FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def public_capital_summary(capital: dict[str, Any]) -> dict[str, Any]:
    policy = capital.get("policy") if isinstance(capital.get("policy"), dict) else {}
    context = capital.get("context") if isinstance(capital.get("context"), dict) else {}
    decision = (
        capital.get("decision") if isinstance(capital.get("decision"), dict) else {}
    )
    return {
        "status": str(capital.get("status") or "missing"),
        "input_fingerprint": str(capital.get("input_fingerprint") or ""),
        "evaluation_id": capital.get("evaluation_id"),
        "recorded_at": str(capital.get("recorded_at") or ""),
        "authorization_id": str(policy.get("authorization_id") or ""),
        "policy_version": str(policy.get("policy_version") or ""),
        "mode": str(policy.get("mode") or ""),
        "effective_at": str(policy.get("effective_at") or ""),
        "expires_at": str(policy.get("expires_at") or ""),
        "scope": {
            "connector_id": str(context.get("connector_id") or ""),
            "evidence_connector_id": str(context.get("evidence_connector_id") or ""),
            "execution_gateway_id": str(context.get("execution_gateway_id") or ""),
            "account_alias": str(context.get("account_alias") or ""),
            "strategy_id": str(context.get("strategy_id") or ""),
            "symbols": [str(item) for item in policy.get("symbols") or []],
        },
        "effective_limits": (
            decision.get("effective_limits")
            if isinstance(decision.get("effective_limits"), dict)
            else {}
        ),
        "remaining_budget": (
            decision.get("remaining_budget")
            if isinstance(decision.get("remaining_budget"), dict)
            else {}
        ),
        "calculation_allowed": bool(decision.get("allowed")),
        "blockers": [str(item) for item in capital.get("blockers") or []],
        "operator_identity_verified": False,
        "runtime_session_authority": "disabled",
    }


def missing_capital_summary(input_fingerprint: str = "") -> dict[str, Any]:
    return {
        "status": "missing",
        "input_fingerprint": input_fingerprint,
        "evaluation_id": None,
        "recorded_at": "",
        "policy": {},
        "context": {},
        "decision": {},
        "blockers": ["capital_evaluation_missing"],
    }


def order_payload(order: dict[str, Any]) -> dict[str, Any]:
    value = order.get("payload")
    if isinstance(value, dict):
        return value
    return json_object(order.get("payload_json"))


def connector_id(connector: Any) -> str:
    value = getattr(connector, "connector_id", None)
    if value:
        return str(value)
    snapshot = getattr(connector, "_snapshot", None)
    return str(getattr(snapshot, "connector_id", "") or "")


def event_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    return {
        "event_id": int(row["id"]),
        "recorded_at": row["timestamp"],
        "created_at": row["created_at"],
        "persisted": True,
        "reused": reused,
        **json_object(row.get("payload_json")),
    }


def blocked_attestation_resolution(
    attestation_id: str,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": CONTROLLED_SESSION_ATTESTATION_SCHEMA_VERSION,
        "status": "blocked",
        "attestation_id": attestation_id,
        "envelope_fingerprint": "",
        "operator_label": "",
        "operator_approval_id": "",
        "recorded_at": "",
        "current_envelope": {},
        "blockers": list(dict.fromkeys(blockers)),
        "runtime_session_status": "not_issued",
        "operator_identity_verified": False,
        "authorizes_execution": False,
        "broker_submission_enabled": False,
        "safety": safety_flags(),
    }


def safety_flags() -> dict[str, bool]:
    return {
        "does_not_contact_broker": True,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_issue_or_enable_runtime_session": True,
        "does_not_consume_or_reserve_runtime_budget": True,
        "does_not_auto_resume_renew_or_expand": True,
        "does_not_grant_or_scale_capital_authority": True,
    }


def decimal_value(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def decimal_string(value: Decimal | None) -> str:
    if value is None:
        return ""
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
