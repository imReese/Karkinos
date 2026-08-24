"""Pure normalization and policy helpers for automation alerts."""

from __future__ import annotations

import hashlib
import json
from typing import Any

AUTOMATION_ALERT_SCHEMA_VERSION = "karkinos.automation_alert.v1"

FAILED_AUTOMATION_RUN_STATUSES = {
    "failed",
    "paper_shadow_failed",
    "scheduler_failed",
}
STALE_MARKET_DATA_STATUSES = {
    "cache",
    "confirmed_nav_missing",
    "estimated",
    "missing",
    "partial",
    "stale",
}
ACCOUNT_TRUTH_ALERT_STATUSES = {
    "blocked",
    "degraded",
    "failed",
    "fail",
    "mismatch",
    "warning",
}
PAPER_SHADOW_DIVERGENCE_STATUSES = {
    "diverged",
    "failed",
    "review_required",
}
RUNTIME_CONNECTOR_DEGRADED_STATUSES = {
    "collector_evidence_blocked",
    "collector_evidence_missing",
    "collector_evidence_pending",
    "collector_evidence_unavailable",
    "connection_failed",
    "degraded",
    "disconnected",
    "error",
    "failed",
    "heartbeat_stale",
    "runtime_degraded",
    "runtime_unavailable",
    "stale",
    "unavailable",
}


def automation_run_suggested_action(
    *,
    status: Any,
    run_type: Any,
    execution_mode: Any,
) -> str:
    normalized_run_type = str(run_type or "").strip().lower()
    normalized_status = str(status or "").strip().lower()
    normalized_execution_mode = str(execution_mode or "").strip().lower()
    if normalized_run_type == "market_session":
        return "inspect_scheduler_failure"
    if (
        normalized_execution_mode == "paper_shadow"
        or "paper_shadow" in normalized_status
    ):
        return "inspect_failed_paper_shadow_run"
    return "inspect_failed_automation_run"


def current_review_alert_boundary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "reads_persisted_facts_only": summary.get("reads_persisted_facts_only") is True,
        "provider_contact_performed": False,
        "runtime_connector_query_performed": False,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_mutate_risk": True,
        "does_not_mutate_kill_switch": True,
        "does_not_change_capital_authority": True,
        "authorizes_execution": False,
    }


def stable_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    object_value = object_dict(value)
    if object_value:
        return object_value
    if value in {None, ""}:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def object_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return {}


def json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in {None, ""}:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
