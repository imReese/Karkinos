"""Pure values and response projections for per-order confirmation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from server.contracts.per_order_confirmation import (
    PER_ORDER_CONFIRMATION_SCHEMA_VERSION,
)

FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def missing_capital_summary(input_fingerprint: str = "") -> dict[str, Any]:
    return {
        "status": "missing",
        "input_fingerprint": input_fingerprint,
        "evaluation_id": None,
        "recorded_at": "",
        "authorization_id": "",
        "policy_version": "",
        "mode": "",
        "calculation_allowed": False,
        "effective_at": "",
        "expires_at": "",
        "scope": {
            "connector_id": "",
            "account_alias": "",
            "strategy_id": "",
            "symbol": "",
        },
        "effective_limits": {},
        "remaining_budget": {},
        "evidence_refs": [],
        "blockers": ["capital_evaluation_missing"],
        "operator_identity_verified": False,
        "runtime_authority_status": "disabled",
        "does_not_enable_execution": True,
    }


def missing_signed_soak_promotion(blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "karkinos.per_order_broker_soak_promotion_binding.v1",
        "status": "blocked",
        "connector_id": "",
        "dossier_fingerprint": "",
        "operational_source_fingerprint": "",
        "account_truth_source_fingerprint": "",
        "acceptance_id": "",
        "acceptance_recorded_at": "",
        "operator_label": "",
        "promotion_ready": False,
        "owner_acceptance_recorded": False,
        "account_truth_reconciliation_linked": False,
        "blockers": list(dict.fromkeys(blockers)),
        "authorizes_execution": False,
        "broker_submission_enabled": False,
    }


def connector_id(connector: Any) -> str:
    value = getattr(connector, "connector_id", None)
    if value:
        return str(value)
    snapshot = getattr(connector, "_snapshot", None)
    return str(getattr(snapshot, "connector_id", "") or "")


def event_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = json_object(row.get("payload_json"))
    return {
        "event_id": int(row["id"]),
        "recorded_at": row["timestamp"],
        "created_at": row["created_at"],
        "persisted": True,
        "reused": reused,
        **payload,
    }


def blocked_confirmation_resolution(
    confirmation_id: str,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": PER_ORDER_CONFIRMATION_SCHEMA_VERSION,
        "status": "blocked",
        "confirmation_id": confirmation_id,
        "order_id": "",
        "blockers": list(dict.fromkeys(blockers)),
        "authorizes_execution": False,
        "broker_submission_enabled": False,
        "safety": safety_flags(),
    }


def mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def safety_flags() -> dict[str, bool]:
    return {
        "does_not_contact_broker": True,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_grant_or_expand_capital_authority": True,
        "does_not_auto_resume": True,
    }


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
