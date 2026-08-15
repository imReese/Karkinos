"""Read-only runtime status for the production daily-candidate monitor."""

from __future__ import annotations

from typing import Any

from server.services.daily_decision_evidence_automation import (
    DAILY_CANDIDATE_BACKGROUND_SCHEDULE_SCHEMA_VERSION,
)

DAILY_CANDIDATE_RUNTIME_STATUS_SCHEMA_VERSION = (
    "karkinos.daily_candidate_runtime_status.v1"
)


def build_daily_candidate_runtime_status(
    *,
    config: Any,
    monitor_task: Any,
    background_schedule: dict[str, Any] | None,
) -> dict[str, Any]:
    """Project monitor liveness without claiming financial readiness."""

    schedule = (
        dict(background_schedule) if isinstance(background_schedule, dict) else {}
    )
    schedule_valid = (
        schedule.get("schema_version")
        == DAILY_CANDIDATE_BACKGROUND_SCHEDULE_SCHEMA_VERSION
        and schedule.get("broker_submission_enabled") is False
        and schedule.get("authorizes_execution") is False
    )
    schedule_due = schedule_valid and schedule.get("due") is True
    schedule_blockers = (
        [str(item) for item in schedule.get("blockers", []) if str(item)]
        if schedule_valid and isinstance(schedule.get("blockers"), list)
        else []
    )

    configured = getattr(config, "live_auto_start", None)
    task_state, task_failure_type = _monitor_task_state(
        monitor_task if configured is True else None
    )
    blockers: list[str] = []
    if configured is False:
        task_state = "disabled"
        blockers.append("daily_candidate_background_monitor_disabled")
    elif configured is not True:
        task_state = "unavailable"
        blockers.append("daily_candidate_background_monitor_configuration_unavailable")
    elif task_state != "running":
        blockers.append(f"daily_candidate_background_monitor_task_{task_state}")
    if not schedule_valid:
        blockers.append("daily_candidate_background_schedule_invalid")
    blockers.extend(schedule_blockers)
    blockers = list(dict.fromkeys(blockers))

    monitor_running = configured is True and task_state == "running"
    if configured is False:
        status = "monitor_disabled"
        next_safe_action = "restart_with_owner_enabled_live_monitoring_if_approved"
    elif not monitor_running:
        status = "monitor_failed_closed"
        next_safe_action = "restart_and_verify_daily_candidate_monitor"
    elif not schedule_valid or schedule_blockers:
        status = "monitor_running_schedule_blocked"
        next_safe_action = "resolve_persisted_schedule_evidence_before_window"
    elif schedule_due:
        status = "monitor_running_due"
        next_safe_action = "allow_single_claimed_fail_closed_background_attempt"
    else:
        status = "monitor_running_waiting"
        next_safe_action = "keep_service_running_and_prepare_current_evidence"

    return {
        "schema_version": DAILY_CANDIDATE_RUNTIME_STATUS_SCHEMA_VERSION,
        "status": status,
        "background_monitor_configured": configured is True,
        "background_monitor_running": monitor_running,
        "monitor_task_state": task_state,
        "monitor_task_failure_type": task_failure_type,
        "run_date": schedule.get("run_date") if schedule_valid else None,
        "schedule_status": schedule.get("status") if schedule_valid else "invalid",
        "background_attempt_due": monitor_running and schedule_due,
        "background_attempt_writes_permitted": monitor_running and schedule_due,
        "manual_run_window_open": schedule_due,
        "operational_blockers": blockers,
        "next_safe_action": next_safe_action,
        "financial_readiness_claimed": False,
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "does_not_submit_broker_order": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "limitations": [
            "Monitor liveness does not prove current Account Truth, market, strategy, fee, risk, or reconciliation readiness.",
            "This projection reads runtime task state and an existing persisted-only schedule projection; it performs no provider or broker call.",
        ],
    }


def unavailable_daily_candidate_runtime_status(
    background_schedule: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the canonical fail-closed shape when runtime state is unavailable."""

    return build_daily_candidate_runtime_status(
        config=None,
        monitor_task=None,
        background_schedule=background_schedule,
    )


def _monitor_task_state(task: Any) -> tuple[str, str | None]:
    if task is None:
        return "missing", None
    done = getattr(task, "done", None)
    cancelled = getattr(task, "cancelled", None)
    exception = getattr(task, "exception", None)
    if not callable(done) or not callable(cancelled) or not callable(exception):
        return "invalid", None
    if not done():
        return "running", None
    if cancelled():
        return "cancelled", None
    failure = exception()
    if failure is None:
        return "completed", None
    return "failed", type(failure).__name__
