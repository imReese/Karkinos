"""Stable value helpers for broker-soak promotion evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def connector_id(connector: Any) -> str:
    return str(
        getattr(connector, "connector_id", "")
        or getattr(getattr(connector, "snapshot", None), "connector_id", "")
        or ""
    ).strip()


def drill_connector_scope(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {
        str(item.get("connector_id") or "").strip()
        for item in value
        if isinstance(item, dict) and str(item.get("connector_id") or "").strip()
    }


def blocked_account_truth(blockers: list[str]) -> dict[str, Any]:
    return {
        "status": "blocked",
        "source_fingerprint": "",
        "gate_status": "blocked",
        "data_freshness_status": "missing",
        "unresolved_mismatch_count": 0,
        "blockers": list(dict.fromkeys(blockers)),
        "does_not_mutate_production_ledger": True,
        "does_not_issue_execution_authority": True,
        "broker_submission_enabled": False,
    }


def without_volatile_age(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "current_age_seconds"}


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def event_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    return {
        "event_id": int(row["id"]),
        "recorded_at": row["timestamp"],
        "created_at": row["created_at"],
        "persisted": True,
        "reused": reused,
        **json_object(row.get("payload_json")),
    }


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


def fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def safety_flags() -> dict[str, bool]:
    return {
        "stores_broker_credentials": False,
        "does_not_grant_capital_authority": True,
        "does_not_issue_or_resume_runtime_authority": True,
        "does_not_contact_broker": True,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_reserve_or_consume_budget": True,
        "automatic_promotion_enabled": False,
    }
