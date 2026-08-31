"""Pure status and payload projections for Operations Today."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from server.services.operations_today_contracts import (
    PAPER_SHADOW_MODE as _PAPER_SHADOW_MODE,
)
from server.services.operations_today_contracts import (
    PAPER_SHADOW_SOURCE as _PAPER_SHADOW_SOURCE,
)


def _paper_shadow_status_can_accept_manual_handoff(status: str) -> bool:
    return str(status or "").strip().lower() in {
        "diverged",
        "review_required",
        "within_expectations",
    }


def _is_daily_shadow_order(
    order: dict[str, Any],
    *,
    run_id: str,
    plan_date: str,
) -> bool:
    payload = _payload(order)
    payload_run_id = str(payload.get("run_id") or "")
    if payload_run_id == run_id or payload_run_id.startswith(f"{run_id}:"):
        return True
    if str(order.get("order_id") or "").startswith(f"SHADOW-{plan_date}-"):
        return True
    explicit_plan_date = str(order.get("plan_date") or payload.get("plan_date") or "")
    return explicit_plan_date == plan_date and (
        str(order.get("execution_mode") or "").lower() == _PAPER_SHADOW_MODE
        or str(order.get("source") or "").lower() == _PAPER_SHADOW_SOURCE
    )


def _paper_shadow_default_next_step(
    *,
    status: str,
    value: Any,
    review_status: Any = None,
) -> str:
    review = str(review_status or "").strip().lower()
    if (
        review == "accepted_for_manual_confirmation"
        and _paper_shadow_status_can_accept_manual_handoff(status)
    ):
        return "review_manual_confirmation"
    if review == "needs_rerun":
        return "run_paper_shadow_daily"
    if status == "failed":
        return "inspect_failed_run"
    text = str(value or "").strip()
    if text:
        return text
    if status == "running":
        return "wait_for_paper_shadow_run"
    if status == "within_expectations":
        return "review_manual_confirmation"
    if status == "failed":
        return "inspect_failed_run"
    if status == "diverged":
        return "resolve_shadow_divergence"
    if status in {"not_required", "not_run"}:
        return "none" if status == "not_required" else "run_paper_shadow_daily"
    return "review_shadow_divergence"


def _payload_status(order: dict[str, Any], key: str) -> str | None:
    value = _payload(order).get(key)
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _payload(order: dict[str, Any]) -> dict[str, Any]:
    payload = order.get("payload_json") or order.get("payload")
    if isinstance(payload, dict):
        return payload
    if not isinstance(payload, str) or not payload.strip():
        return {}
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _subsystem(
    subsystem_id: str,
    status: str,
    *,
    target: str,
    last_run_at: Any,
    next_action: Any,
    limitations: list[str],
    detail_status: str,
) -> dict[str, Any]:
    return {
        "id": subsystem_id,
        "status": status,
        "tone": _tone(status),
        "target": target,
        "last_run_at": last_run_at,
        "next_action": str(next_action or "none"),
        "limitations": limitations,
        "detail_status": detail_status,
    }


def _attention_items(subsystems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for subsystem in subsystems:
        status = str(subsystem.get("status") or "unknown")
        if status in {"pass", "skipped"}:
            continue
        subsystem_id = str(subsystem.get("id") or "unknown")
        target = str(subsystem.get("target") or subsystem_id)
        next_action = str(subsystem.get("next_action") or "none")
        resolution_condition = _attention_resolution_condition(
            subsystem_id=subsystem_id,
            next_action=next_action,
        )
        evidence = {
            "status": str(subsystem.get("detail_status") or "unknown"),
            "observed_at": subsystem.get("last_run_at"),
        }
        fingerprint_payload = {
            "schema_version": "karkinos.operations_attention_item.v1",
            "subsystem_id": subsystem_id,
            "status": status,
            "target": target,
            "evidence": evidence,
            "next_action": next_action,
            "resolution_condition": resolution_condition,
        }
        fingerprint_basis = {
            **fingerprint_payload,
            "evidence": {"status": evidence["status"]},
        }
        source_evidence_fingerprint = str(subsystem.get("evidence_fingerprint") or "")
        if source_evidence_fingerprint:
            fingerprint_basis["source_evidence_fingerprint"] = (
                source_evidence_fingerprint
            )
        encoded = json.dumps(
            fingerprint_basis,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        items.append(
            {
                **fingerprint_payload,
                "task_fingerprint": f"sha256:{hashlib.sha256(encoded).hexdigest()}",
                "manual_acknowledgement_clears_status": False,
                "read_only_projection": True,
                "provider_contacted": False,
                "database_writes_performed": False,
                "authorizes_execution": False,
            }
        )
    return items


def _attention_resolution_condition(
    *,
    subsystem_id: str,
    next_action: str,
) -> str:
    by_action = {
        "repair_market_data_source": "new_complete_market_evidence_required",
        "review_market_data_freshness": "new_complete_market_evidence_required",
        "refresh_account_truth_snapshot": "current_account_truth_snapshot_required",
        "resolve_account_truth_mismatch": "new_complete_account_truth_evidence_required",
        "attach_account_truth_evidence": "new_complete_account_truth_evidence_required",
        "review_strategy_evidence": "candidate_strategy_evidence_must_pass",
        "review_risk_blocks": "new_daily_plan_with_deterministic_risk_pass_required",
        "resolve_daily_plan_blockers": "new_daily_plan_without_blockers_required",
        "review_manual_order_intents": "explicit_manual_order_review_evidence_required",
        "run_paper_shadow_daily": "new_paper_shadow_run_evidence_required",
        "wait_for_paper_shadow_run": "current_paper_shadow_run_must_reach_terminal_evidence",
        "review_shadow_divergence": "accepted_paper_shadow_review_evidence_required",
        "resolve_shadow_divergence": "accepted_paper_shadow_review_evidence_required",
        "inspect_failed_run": "new_terminal_paper_shadow_run_evidence_required",
        "inspect_scheduler_failure": "new_recognized_terminal_scheduler_run_required",
        "review_scheduler_run": "new_recognized_terminal_scheduler_run_required",
        "resolve_kill_switch": "kill_switch_clear_and_new_scheduler_evidence_required",
        "review_acceptance_audit_gaps": "complete_acceptance_audit_evidence_required",
        "export_acceptance_audit": "complete_acceptance_audit_evidence_required",
        "provide_citic_account_truth_evidence_or_reject_source": (
            "complete_account_truth_evidence_or_explicit_source_rejection_required"
        ),
        "review_citic_source_query_windows": (
            "reviewed_query_window_for_each_pending_citic_source_required"
        ),
        "review_citic_source_intake_scan_limit": (
            "complete_citic_source_intake_scan_required"
        ),
        "repair_citic_source_intake_metadata_store": (
            "readable_citic_source_intake_metadata_required"
        ),
        "repair_citic_source_query_window_review_store": (
            "readable_citic_source_query_window_review_metadata_required"
        ),
    }
    if next_action in by_action:
        return by_action[next_action]
    by_subsystem = {
        "market_data": "new_complete_market_evidence_required",
        "account_truth": "new_complete_account_truth_evidence_required",
        "strategy_candidates": "candidate_strategy_evidence_must_pass",
        "risk": "new_daily_plan_with_deterministic_risk_pass_required",
        "daily_trading_plan": "new_daily_plan_without_blockers_required",
        "paper_shadow": "new_terminal_paper_shadow_run_evidence_required",
        "scheduler": "new_recognized_terminal_scheduler_run_required",
        "execution_reconciliation": "canonical_execution_reconciliation_must_close",
        "acceptance_audit": "complete_acceptance_audit_evidence_required",
        "broker_adapter_evidence": "explicit_provider_authorization_and_new_release_evidence_required",
    }
    return by_subsystem.get(
        subsystem_id,
        "new_canonical_evidence_required",
    )


def _health_summary(subsystems: list[dict[str, Any]]) -> dict[str, int]:
    statuses = [str(item.get("status") or "unknown") for item in subsystems]
    return {
        "total": len(statuses),
        "pass": statuses.count("pass"),
        "degraded": statuses.count("degraded"),
        "blocked": statuses.count("blocked"),
        "manual_action_required": statuses.count("manual_action_required"),
        "skipped": statuses.count("skipped"),
    }


def _conclusion(subsystems: list[dict[str, Any]]) -> tuple[str, str]:
    blocked = next(
        (item for item in subsystems if item.get("status") == "blocked"),
        None,
    )
    if blocked is not None:
        return "blocked", str(blocked.get("target") or blocked.get("id") or "decision")

    waiting_shadow = next(
        (
            item
            for item in subsystems
            if item.get("id") == "paper_shadow"
            and item.get("status") == "degraded"
            and item.get("next_action") == "wait_for_paper_shadow_run"
        ),
        None,
    )
    if waiting_shadow is not None:
        return "degraded", str(
            waiting_shadow.get("target") or waiting_shadow.get("id") or "decision"
        )

    for status in ("manual_action_required", "degraded"):
        match = None
        if status == "manual_action_required":
            match = next(
                (
                    item
                    for item in subsystems
                    if item.get("id") == "paper_shadow"
                    and item.get("status") == "manual_action_required"
                ),
                None,
            )
        match = match or next(
            (item for item in subsystems if item.get("status") == status),
            None,
        )
        if match is not None:
            return status, str(match.get("target") or match.get("id") or "decision")
    return "healthy", "decision"


def _tone(status: str) -> str:
    if status == "blocked":
        return "danger"
    if status in {"manual_action_required", "degraded"}:
        return "warning"
    return "neutral" if status == "skipped" else "success"


def _latest_timestamp(rows: list[dict[str, Any]]) -> str | None:
    timestamps = [
        str(row.get("updated_at") or row.get("timestamp") or row.get("created_at"))
        for row in rows
        if row.get("updated_at") or row.get("timestamp") or row.get("created_at")
    ]
    return max(timestamps) if timestamps else None


def _nested(value: dict[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _status(value: Any, default: str = "unknown") -> str:
    text = str(value or default).strip().lower()
    return text or default


def _int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    if value:
        return [str(value)]
    return []


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _json_list(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return _list(value)
        return _list(parsed)
    return _list(value)


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


is_daily_shadow_order = _is_daily_shadow_order
paper_shadow_default_next_step = _paper_shadow_default_next_step
payload_status = _payload_status
payload = _payload
subsystem = _subsystem
attention_items = _attention_items
attention_resolution_condition = _attention_resolution_condition
health_summary = _health_summary
conclusion = _conclusion
tone = _tone
latest_timestamp = _latest_timestamp
nested = _nested
status = _status
int_value = _int
list_value = _list
dedupe = _dedupe
json_list = _json_list
list_of_dicts = _list_of_dicts
dict_value = _dict
paper_shadow_status_can_accept_manual_handoff = (
    _paper_shadow_status_can_accept_manual_handoff
)
