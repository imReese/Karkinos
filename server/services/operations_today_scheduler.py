"""Scheduler state projection for Operations Today."""

from __future__ import annotations

from typing import Any, Iterable

from server.services.operations_today_values import dict_value as _dict
from server.services.operations_today_values import list_value as _list
from server.services.operations_today_values import payload as _payload


def _scheduler_summary(
    *,
    automation_runs: Iterable[dict[str, Any]] | None,
    plan_date: str,
    fallback_detail_status: str,
) -> dict[str, Any]:
    latest_run = _latest_automation_run(
        automation_runs=automation_runs,
        plan_date=plan_date,
    )
    if latest_run is None:
        return {
            "status": str(fallback_detail_status or "not_recorded"),
            "run_id": None,
            "run_type": "scheduler",
            "run_date": plan_date,
            "execution_mode": "paper_shadow",
            "last_run_at": plan_date,
            "input_fingerprint": None,
            "idempotency_key": None,
            "input_snapshot": {},
            "retry_state": {},
            "error": {},
            "broker_submission_enabled": False,
            "does_not_submit_broker_order": True,
            "limitations": [
                "Daily scheduler state is summarized from current local records."
            ],
        }

    payload = _payload(latest_run)
    status = str(latest_run.get("status") or "unknown")
    run_type = latest_run.get("run_type")
    execution_mode = latest_run.get("execution_mode") or "paper_shadow"
    retry_state = _dict(payload.get("retry_state"))
    is_failure = _scheduler_run_failed(status)
    return {
        "status": status,
        "run_id": latest_run.get("run_id"),
        "run_type": run_type,
        "run_date": latest_run.get("run_date") or plan_date,
        "execution_mode": execution_mode,
        "last_run_at": latest_run.get("finished_at")
        or latest_run.get("updated_at")
        or latest_run.get("started_at")
        or latest_run.get("created_at"),
        "input_fingerprint": payload.get("input_fingerprint"),
        "idempotency_key": payload.get("idempotency_key"),
        "input_snapshot": _dict(payload.get("input_snapshot")),
        "retry_state": retry_state,
        "error": _dict(payload.get("error")),
        "suggested_action": _scheduler_suggested_action(
            status=status,
            run_type=run_type,
            execution_mode=execution_mode,
        ),
        "requires_manual_review": is_failure,
        "retry_recommended": is_failure and bool(retry_state.get("retryable")),
        "broker_submission_enabled": bool(payload.get("broker_submission_enabled")),
        "does_not_submit_broker_order": payload.get("does_not_submit_broker_order")
        is not False,
        "does_not_mutate_production_ledger": payload.get(
            "does_not_mutate_production_ledger"
        )
        is not False,
        "limitations": _list(payload.get("limitations")),
    }


def _latest_automation_run(
    *,
    automation_runs: Iterable[dict[str, Any]] | None,
    plan_date: str,
) -> dict[str, Any] | None:
    if automation_runs is None:
        return None
    rows = [
        row
        for row in automation_runs
        if isinstance(row, dict)
        and str(row.get("run_type") or "") == "market_session"
        and (not plan_date or str(row.get("run_date") or "") == plan_date)
    ]
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: str(
            row.get("finished_at")
            or row.get("updated_at")
            or row.get("started_at")
            or row.get("created_at")
            or ""
        ),
    )


def _scheduler_operation_state(run_status: str) -> tuple[str, str]:
    status = run_status.strip().lower()
    if status.endswith("_failed") or status in {"failed", "error"}:
        return "blocked", "inspect_scheduler_failure"
    if status == "blocked_by_kill_switch":
        return "blocked", "resolve_kill_switch"
    if status in {"no_manual_action", "skipped_non_trading_session", "skipped"}:
        return "skipped", "none"
    if status in {"paper_shadow_completed", "completed", "success", "pass"}:
        return "pass", "none"
    if status in {"pending_manual_confirmation", "not_recorded", ""}:
        return "pass", "none"
    return "degraded", "review_scheduler_run"


def _scheduler_run_failed(status: str) -> bool:
    value = str(status or "").strip().lower()
    return value.endswith("_failed") or value in {"failed", "error"}


def _scheduler_suggested_action(
    *,
    status: str,
    run_type: Any,
    execution_mode: Any,
) -> str:
    value = str(status or "").strip().lower()
    if value == "blocked_by_kill_switch":
        return "resolve_kill_switch"
    if value == "paper_shadow_failed" and str(execution_mode or "") == "paper_shadow":
        return "inspect_failed_paper_shadow_run"
    if _scheduler_run_failed(value) and str(run_type or "") == "market_session":
        return "inspect_scheduler_failure"
    if _scheduler_run_failed(value):
        return "inspect_failed_automation_run"
    if value in {"no_manual_action", "skipped_non_trading_session", "skipped"}:
        return "none"
    if value in {"paper_shadow_completed", "completed", "success", "pass"}:
        return "none"
    if value in {"pending_manual_confirmation", "not_recorded", ""}:
        return "none"
    return "review_scheduler_run"


scheduler_summary = _scheduler_summary
latest_automation_run = _latest_automation_run
scheduler_operation_state = _scheduler_operation_state
scheduler_run_failed = _scheduler_run_failed
scheduler_suggested_action = _scheduler_suggested_action
