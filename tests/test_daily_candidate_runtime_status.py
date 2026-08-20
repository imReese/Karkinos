from __future__ import annotations

from types import SimpleNamespace

from server.services.daily_candidate_runtime_status import (
    build_daily_candidate_runtime_status,
)


class _Task:
    def __init__(
        self,
        *,
        done: bool = False,
        cancelled: bool = False,
        failure: BaseException | None = None,
    ) -> None:
        self._done = done
        self._cancelled = cancelled
        self._failure = failure

    def done(self) -> bool:
        return self._done

    def cancelled(self) -> bool:
        return self._cancelled

    def exception(self) -> BaseException | None:
        return self._failure


def _schedule(*, due: bool = False, blockers: list[str] | None = None):
    return {
        "schema_version": "karkinos.daily_candidate_background_schedule.v2",
        "status": "due" if due else "waiting_for_decision_window",
        "run_date": "2026-08-17",
        "due": due,
        "blockers": list(blockers or []),
        "broker_submission_enabled": False,
        "authorizes_execution": False,
    }


def test_runtime_status_proves_only_running_monitor_liveness() -> None:
    result = build_daily_candidate_runtime_status(
        config=SimpleNamespace(live_auto_start=True),
        monitor_task=_Task(),
        background_schedule=_schedule(due=True),
    )

    assert result["status"] == "monitor_running_due"
    assert result["background_monitor_configured"] is True
    assert result["background_monitor_running"] is True
    assert result["background_attempt_due"] is True
    assert result["background_attempt_writes_permitted"] is True
    assert result["financial_readiness_claimed"] is False
    assert result["provider_contact_performed"] is False
    assert result["database_writes_performed"] is False
    assert result["broker_submission_enabled"] is False
    assert result["authorizes_execution"] is False
    assert result["changes_capital_authority"] is False


def test_runtime_status_distinguishes_disabled_monitor_from_open_window() -> None:
    result = build_daily_candidate_runtime_status(
        config=SimpleNamespace(live_auto_start=False),
        monitor_task=None,
        background_schedule=_schedule(due=True),
    )

    assert result["status"] == "monitor_disabled"
    assert result["background_monitor_running"] is False
    assert result["background_attempt_due"] is False
    assert result["background_attempt_writes_permitted"] is False
    assert result["manual_run_window_open"] is True
    assert result["operational_blockers"] == [
        "daily_candidate_background_monitor_disabled"
    ]


def test_runtime_status_fails_closed_when_enabled_task_has_failed() -> None:
    result = build_daily_candidate_runtime_status(
        config=SimpleNamespace(live_auto_start=True),
        monitor_task=_Task(done=True, failure=RuntimeError("private detail")),
        background_schedule=_schedule(),
    )

    assert result["status"] == "monitor_failed_closed"
    assert result["monitor_task_state"] == "failed"
    assert result["monitor_task_failure_type"] == "RuntimeError"
    assert result["operational_blockers"] == [
        "daily_candidate_background_monitor_task_failed"
    ]
    assert "private detail" not in str(result)


def test_runtime_status_rejects_unsafe_or_malformed_schedule() -> None:
    schedule = _schedule(due=True)
    schedule["authorizes_execution"] = True

    result = build_daily_candidate_runtime_status(
        config=SimpleNamespace(live_auto_start=True),
        monitor_task=_Task(),
        background_schedule=schedule,
    )

    assert result["status"] == "monitor_running_schedule_blocked"
    assert result["background_attempt_due"] is False
    assert result["manual_run_window_open"] is False
    assert result["operational_blockers"] == [
        "daily_candidate_background_schedule_invalid"
    ]
