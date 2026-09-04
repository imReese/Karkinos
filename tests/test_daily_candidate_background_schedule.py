from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from server.db import AppDatabase
from server.services import daily_decision_evidence_automation as automation_module
from server.services.daily_decision_evidence_automation import (
    DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
    DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE,
    DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
    project_daily_candidate_background_schedule,
    run_daily_decision_evidence_automation_loop,
)

RUN_DATE = "2026-07-01"
DECISION_TIME = datetime(2026, 7, 1, 1, 36, tzinfo=timezone.utc)
PREPARATION_TIME = datetime(2026, 7, 1, 0, 45, tzinfo=timezone.utc)


def _seed_calendar(db: AppDatabase, *, is_trading_day: bool = True) -> None:
    trading_dates = {"2026-07-02"}
    if is_trading_day:
        trading_dates.add(RUN_DATE)
    current = date(2026, 1, 1)
    calendar_days = []
    while current.year == 2026:
        market_date = current.isoformat()
        trading = market_date in trading_dates
        calendar_days.append(
            {
                "date": market_date,
                "is_trading_day": trading,
                "day_type": "trading_day" if trading else "closed",
                "reason_code": "trading_day" if trading else "closed",
            }
        )
        current += timedelta(days=1)
    source_fingerprint = "a" * 64
    db.upsert_market_calendar_snapshot_sync(
        {
            "exchange": "SSE",
            "year": 2026,
            "provider": "fixture",
            "schema_version": "karkinos.market_calendar.v1",
            "status": "available",
            "trading_day_count": len(trading_dates),
            "closed_day_count": len(calendar_days) - len(trading_dates),
            "source_fingerprint": source_fingerprint,
            "days": calendar_days,
        }
    )
    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2026,
        source_fingerprint=source_fingerprint,
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="b" * 64,
        verified_by="fixture",
    )


def _record_daily_run(db: AppDatabase) -> None:
    db.upsert_automation_run_sync(
        {
            "run_id": "daily-candidate:fixture",
            "run_type": DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
            "run_date": RUN_DATE,
            "status": "no_candidates",
            "execution_mode": "paper_shadow",
            "started_at": DECISION_TIME.isoformat(),
            "finished_at": DECISION_TIME.isoformat(),
            "source_ref": None,
            "payload": {},
        }
    )


def _preparation_result(*, blocked: bool = True) -> dict[str, object]:
    blockers = ["account_truth_not_fresh"] if blocked else []
    gates = [
        {
            "gate": gate,
            "status": ("blocked" if blocked and gate == "account_truth" else "pass"),
            "blockers": blockers if gate == "account_truth" else [],
        }
        for gate in (
            "automation_policy",
            "account_truth",
            "reviewed_fees",
            "strategy",
            "execution_closure",
        )
    ]
    core = {
        "schema_version": "karkinos.daily_candidate_preparation_check.v1",
        "status": "blocked" if blocked else "ready_for_window_time_evidence",
        "run_date": RUN_DATE,
        "gates": gates,
        "blockers": blockers,
        "blocker_count": len(blockers),
        "blockers_truncated": False,
        "first_blocking_gate": "account_truth" if blocked else None,
        "first_safe_action": (
            "complete_current_account_truth_evidence_review"
            if blocked
            else "persist_current_market_quotes_and_build_reviewed_window_plan"
        ),
        "deferred_window_time_gates": [
            "market_data",
            "decision_plan",
            "runtime_window",
        ],
        "permits_risk_or_paper_shadow": False,
        "changes_attempt_eligibility": False,
        "permits_retry_or_backfill": False,
        "qualifies_forward_trial": False,
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "manual_confirmation_required": True,
        "does_not_create_oms_order": True,
        "does_not_mutate_production_ledger": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "profitability_claim": "not_established",
    }
    return {
        **core,
        "preparation_fingerprint": automation_module._fingerprint_json(core),
    }


def test_background_schedule_exposes_one_preparation_check_before_window(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)

    early = project_daily_candidate_background_schedule(
        db=db,
        now=datetime(2026, 7, 1, 0, 44, tzinfo=timezone.utc),
    )
    due = project_daily_candidate_background_schedule(db=db, now=PREPARATION_TIME)

    assert early["preparation_check_due"] is False
    assert early["background_writes_enabled"] is False
    assert due["status"] == "waiting_for_decision_window"
    assert due["due"] is False
    assert due["preparation_check_due"] is True
    assert due["preparation_check_writes_enabled"] is True
    assert due["background_attempt_writes_enabled"] is False
    assert due["background_writes_enabled"] is True
    assert due["preparation_check_changes_attempt_eligibility"] is False
    assert due["preparation_check_permits_retry_or_backfill"] is False
    assert due["broker_submission_enabled"] is False
    assert due["authorizes_execution"] is False
    assert due["changes_capital_authority"] is False

    claim = db.claim_automation_run_once_sync(
        run_id=f"automation:daily-candidate-preparation:{RUN_DATE}",
        run_type=DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE,
        run_date=RUN_DATE,
        claimed_at=PREPARATION_TIME.isoformat(),
        execution_mode="read_only_preparation",
        payload={"status": "claimed"},
    )
    replay = project_daily_candidate_background_schedule(
        db=db,
        now=PREPARATION_TIME,
    )

    assert claim["claimed"] is True
    assert replay["preparation_check_due"] is False
    assert replay["preparation_check_existing_run_id"] == (
        f"automation:daily-candidate-preparation:{RUN_DATE}"
    )
    assert replay["background_writes_enabled"] is False


def test_preparation_projection_is_deterministic_read_only_and_fail_closed(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    result = automation_module.build_daily_candidate_preparation_check(
        SimpleNamespace(db=db, trading_controls=None),
        run_date=RUN_DATE,
    )

    assert automation_module.verify_daily_candidate_preparation_check(
        result,
        run_date=RUN_DATE,
    )
    assert result["status"] == "blocked"
    assert result["permits_risk_or_paper_shadow"] is False
    assert result["provider_contact_performed"] is False
    assert result["database_writes_performed"] is False
    assert result["does_not_create_oms_order"] is True
    assert result["broker_submission_enabled"] is False
    assert result["authorizes_execution"] is False
    assert result["changes_capital_authority"] is False
    assert result["profitability_claim"] == "not_established"
    assert not db.list_automation_runs_sync()
    assert not db.list_automation_alerts_sync()


def test_ready_preparation_uses_run_audit_without_open_alert(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    result = automation_module._record_daily_candidate_preparation_alert(
        db=db,
        run_date=RUN_DATE,
        preparation=_preparation_result(blocked=False),
        error_type=None,
    )

    assert result == {
        "status": "not_required",
        "recorded": False,
        "reason": "preparation_gates_ready",
    }
    assert not db.list_automation_alerts_sync()


def test_background_loop_records_one_preparation_reminder_without_attempt(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)
    projection_calls = 0
    notifications: list[tuple[str, str]] = []

    def project_preparation(state, *, run_date):
        nonlocal projection_calls
        assert state.db is db
        assert run_date == RUN_DATE
        projection_calls += 1
        return _preparation_result()

    class Notifier:
        def send(self, *, title, message):
            notifications.append((title, message))

    monkeypatch.setattr(
        automation_module,
        "build_daily_candidate_preparation_check",
        project_preparation,
    )
    sleeps = 0

    async def stop_after_second_poll(_: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps >= 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_daily_decision_evidence_automation_loop(
                state=SimpleNamespace(
                    db=db,
                    trading_controls=None,
                    notifier=Notifier(),
                ),
                interval_seconds=1,
                clock=lambda: PREPARATION_TIME,
                sleep=stop_after_second_poll,
            )
        )

    assert projection_calls == 1
    assert len(notifications) == 1
    assert "account_truth_not_fresh" in notifications[0][1]
    assert not db.list_automation_runs_sync(
        run_type=DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
        run_date=RUN_DATE,
    )
    assert not db.list_automation_runs_sync(
        run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
        run_date=RUN_DATE,
    )
    preparation_runs = db.list_automation_runs_sync(
        run_type=DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE,
        run_date=RUN_DATE,
    )
    assert len(preparation_runs) == 1
    assert preparation_runs[0]["status"] == "blocked"
    payload = json.loads(preparation_runs[0]["payload_json"])
    assert payload["preparation"]["first_blocking_gate"] == "account_truth"
    assert payload["preparation"]["changes_attempt_eligibility"] is False
    assert payload["preparation"]["permits_retry_or_backfill"] is False
    assert payload["preparation"]["qualifies_forward_trial"] is False
    assert payload["preparation"]["provider_contact_performed"] is False
    assert payload["preparation"]["broker_submission_enabled"] is False
    assert payload["notification"] == {"status": "sent", "sent": True}
    alerts = db.list_automation_alerts_sync(status="open")
    assert len(alerts) == 1
    assert alerts[0]["category"] == "daily_candidate_preparation"
    alert_payload = json.loads(alerts[0]["payload_json"])
    assert alert_payload["changes_attempt_eligibility"] is False
    assert alert_payload["provider_contact_performed"] is False
    assert alert_payload["broker_submission_enabled"] is False


def test_background_loop_waits_for_collector_after_daily_snapshot_roll_forward(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)
    roll_forward_calls = 0
    preparation_calls = 0

    def roll_forward(*, state, run_date):
        del state
        nonlocal roll_forward_calls
        assert run_date == RUN_DATE
        roll_forward_calls += 1
        return SimpleNamespace(
            status="rolled_forward" if roll_forward_calls == 1 else "unchanged"
        )

    def project_preparation(state, *, run_date):
        del state
        nonlocal preparation_calls
        assert run_date == RUN_DATE
        preparation_calls += 1
        return _preparation_result()

    monkeypatch.setattr(
        automation_module,
        "roll_forward_daily_broker_statement_for_state",
        roll_forward,
    )
    monkeypatch.setattr(
        automation_module,
        "build_daily_candidate_preparation_check",
        project_preparation,
    )
    sleeps = 0

    async def stop_after_second_poll(_: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps >= 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_daily_decision_evidence_automation_loop(
                state=SimpleNamespace(
                    db=db,
                    notifier=None,
                    trading_controls=None,
                ),
                interval_seconds=1,
                clock=lambda: PREPARATION_TIME,
                sleep=stop_after_second_poll,
            )
        )

    assert roll_forward_calls == 2
    assert preparation_calls == 1
    preparation_runs = db.list_automation_runs_sync(
        run_type=DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE,
        run_date=RUN_DATE,
    )
    assert len(preparation_runs) == 1


def test_background_loop_bounds_polling_and_observes_runtime_interval_changes(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)
    config = SimpleNamespace(live_poll_interval=3600)
    observed_intervals: list[float] = []

    async def update_interval_then_stop(interval: float) -> None:
        observed_intervals.append(interval)
        if len(observed_intervals) == 1:
            config.live_poll_interval = 7
            return
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_daily_decision_evidence_automation_loop(
                state=SimpleNamespace(db=db, config=config),
                interval_seconds=3600,
                clock=lambda: datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
                sleep=update_interval_then_stop,
            )
        )

    assert observed_intervals == [60.0, 7.0]


def test_oversized_poll_interval_cannot_skip_the_decision_window(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)
    db.upsert_automation_run_sync(
        {
            "run_id": "daily-candidate-preparation:fixture",
            "run_type": DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE,
            "run_date": RUN_DATE,
            "status": "ready_for_window_time_evidence",
            "execution_mode": "provider_free_preparation_only",
            "started_at": PREPARATION_TIME.isoformat(),
            "finished_at": PREPARATION_TIME.isoformat(),
            "source_ref": None,
            "payload": {},
        }
    )
    run_calls = 0

    class FakeService:
        async def run_once(self, *, expected_plan_date):
            nonlocal run_calls
            run_calls += 1
            assert expected_plan_date == RUN_DATE
            return {
                "run_id": "daily-candidate:bounded-poll",
                "plan_date": RUN_DATE,
                "status": "no_candidates",
                "decision_outcome": "no_action",
                "input_fingerprint": "a" * 64,
                "no_action_reasons": ["no_strategy_candidate"],
                "manual_ticket_candidate_count": 0,
            }

        async def _send_no_action_notification(self, *, result):
            assert result["decision_outcome"] == "no_action"
            return {"status": "not_configured", "sent": False}

    monkeypatch.setattr(
        automation_module,
        "build_daily_decision_evidence_automation_service",
        lambda state: FakeService(),
    )
    current_time = {"value": datetime(2026, 7, 1, 1, 34, 59, tzinfo=timezone.utc)}
    observed_intervals: list[float] = []

    async def advance_once_then_stop(interval: float) -> None:
        observed_intervals.append(interval)
        if len(observed_intervals) == 1:
            current_time["value"] += timedelta(seconds=interval)
            return
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_daily_decision_evidence_automation_loop(
                state=SimpleNamespace(
                    db=db,
                    config=SimpleNamespace(live_poll_interval=3600),
                ),
                interval_seconds=3600,
                clock=lambda: current_time["value"],
                sleep=advance_once_then_stop,
            )
        )

    assert observed_intervals == [60.0, 60.0]
    assert current_time["value"] == datetime(2026, 7, 1, 1, 35, 59, tzinfo=timezone.utc)
    assert run_calls == 1
    attempts = db.list_automation_runs_sync(
        run_type=DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
        run_date=RUN_DATE,
    )
    assert len(attempts) == 1


def test_background_preparation_contract_drift_fails_closed_without_retry(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)
    projection_calls = 0
    notifications = 0

    def invalid_projection(state, *, run_date):
        nonlocal projection_calls
        assert state.db is db
        assert run_date == RUN_DATE
        projection_calls += 1
        result = _preparation_result(blocked=False)
        result["authorizes_execution"] = True
        return result

    class Notifier:
        def send(self, *, title, message):
            del title, message
            nonlocal notifications
            notifications += 1

    monkeypatch.setattr(
        automation_module,
        "build_daily_candidate_preparation_check",
        invalid_projection,
    )
    sleeps = 0

    async def stop_after_second_poll(_: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps >= 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_daily_decision_evidence_automation_loop(
                state=SimpleNamespace(
                    db=db,
                    trading_controls=None,
                    notifier=Notifier(),
                ),
                interval_seconds=1,
                clock=lambda: PREPARATION_TIME,
                sleep=stop_after_second_poll,
            )
        )

    assert projection_calls == 1
    assert notifications == 0
    run = db.list_automation_runs_sync(
        run_type=DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE,
        run_date=RUN_DATE,
    )[0]
    assert run["status"] == "failed_closed"
    payload = json.loads(run["payload_json"])
    assert payload["preparation"] is None
    assert payload["notification"] is None
    assert payload["error_type"] == "ValueError"
    assert payload["operator_alert"]["severity"] == "critical"
    alert = db.list_automation_alerts_sync(status="open")[0]
    assert alert["category"] == "daily_candidate_preparation"
    alert_payload = json.loads(alert["payload_json"])
    assert alert_payload["preparation_status"] == "failed_closed"
    assert alert_payload["error_type"] == "ValueError"
    assert alert_payload["permits_retry_or_backfill"] is False
    assert alert_payload["broker_submission_enabled"] is False
    assert alert_payload["authorizes_execution"] is False


def test_background_schedule_is_due_only_inside_verified_trading_window(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)

    before = project_daily_candidate_background_schedule(
        db=db,
        now=datetime(2026, 7, 1, 1, 34, tzinfo=timezone.utc),
    )
    due = project_daily_candidate_background_schedule(db=db, now=DECISION_TIME)
    missed = project_daily_candidate_background_schedule(
        db=db,
        now=datetime(2026, 7, 1, 1, 45, tzinfo=timezone.utc),
    )

    assert before["status"] == "waiting_for_decision_window"
    assert before["due"] is False
    assert before["next_reviewed_window"]["market_date"] == RUN_DATE
    assert before["next_reviewed_window"]["window_start"] == (
        "2026-07-01T09:35:00+08:00"
    )
    assert before["next_reviewed_window"]["is_current_market_date"] is True
    assert due["status"] == "due"
    assert due["due"] is True
    assert due["background_writes_enabled"] is True
    assert due["broker_submission_enabled"] is False
    assert missed["status"] == "missed_decision_window"
    assert missed["blockers"] == ["daily_candidate_background_window_missed"]
    assert missed["next_reviewed_window"]["market_date"] == "2026-07-02"
    assert missed["next_reviewed_window"]["is_current_market_date"] is False
    assert missed["next_reviewed_window"]["provider_contact_performed"] is False
    assert missed["next_reviewed_window"]["database_writes_performed"] is False
    assert missed["next_reviewed_window"]["authorizes_execution"] is False


def test_background_schedule_skips_non_trading_and_already_recorded_days(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db, is_trading_day=False)

    closed = project_daily_candidate_background_schedule(db=db, now=DECISION_TIME)

    assert closed["status"] == "not_trading_day"
    assert closed["due"] is False
    assert closed["next_reviewed_window"]["market_date"] == "2026-07-02"

    _seed_calendar(db, is_trading_day=True)
    _record_daily_run(db)
    recorded = project_daily_candidate_background_schedule(db=db, now=DECISION_TIME)

    assert recorded["status"] == "already_recorded"
    assert recorded["existing_run_id"] == "daily-candidate:fixture"
    assert recorded["due"] is False
    assert recorded["next_reviewed_window"]["market_date"] == "2026-07-02"


def test_background_schedule_resolves_next_year_only_from_verified_calendar(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    source_fingerprints: dict[int, str] = {}
    for year, open_dates in (
        (
            2026,
            {"2026-12-31"},
        ),
        (
            2027,
            {"2027-01-04"},
        ),
    ):
        current = date(year, 1, 1)
        days = []
        while current.year == year:
            market_date = current.isoformat()
            is_trading_day = market_date in open_dates
            days.append(
                {
                    "date": market_date,
                    "is_trading_day": is_trading_day,
                    "day_type": "trading_day" if is_trading_day else "closed",
                    "reason_code": "trading_day" if is_trading_day else "closed",
                }
            )
            current += timedelta(days=1)
        source_fingerprint = ("a" if year == 2026 else "c") * 64
        source_fingerprints[year] = source_fingerprint
        db.upsert_market_calendar_snapshot_sync(
            {
                "exchange": "SSE",
                "year": year,
                "provider": "fixture",
                "schema_version": "karkinos.market_calendar.v1",
                "status": "available",
                "trading_day_count": len(open_dates),
                "closed_day_count": len(days) - len(open_dates),
                "source_fingerprint": source_fingerprint,
                "days": days,
            }
        )
        db.update_market_calendar_verification_sync(
            exchange="SSE",
            year=year,
            source_fingerprint=source_fingerprint,
            verification_status="verified",
            official_source_url="https://example.test/calendar",
            official_source_fingerprint="b" * 64,
            verified_by="fixture",
        )

    result = project_daily_candidate_background_schedule(
        db=db,
        now=datetime(2026, 12, 31, 1, 46, tzinfo=timezone.utc),
    )

    assert result["status"] == "missed_decision_window"
    assert result["next_reviewed_window"] == {
        "schema_version": "karkinos.daily_candidate_next_reviewed_window.v1",
        "status": "available",
        "market_date": "2027-01-04",
        "window_start": "2027-01-04T09:35:00+08:00",
        "window_end": "2027-01-04T09:45:00+08:00",
        "is_current_market_date": False,
        "official_calendar_verified": True,
        "blockers": [],
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "permits_retry_or_backfill": False,
        "changes_attempt_eligibility": False,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }

    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2027,
        source_fingerprint=source_fingerprints[2027],
        verification_status="needs_review",
        official_source_url="https://example.invalid",
        verified_by="fixture",
        day_labels={},
    )
    blocked = project_daily_candidate_background_schedule(
        db=db,
        now=datetime(2026, 12, 31, 1, 46, tzinfo=timezone.utc),
    )

    assert blocked["next_reviewed_window"]["status"] == "unavailable"
    assert blocked["next_reviewed_window"]["blockers"] == [
        "next_verified_trading_day_not_available"
    ]
    assert blocked["due"] is False


def test_background_loop_fails_closed_when_result_plan_date_is_stale(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)
    calls = 0
    notifications = 0

    class FakeService:
        async def run_once(self, *, expected_plan_date):
            nonlocal calls
            calls += 1
            assert expected_plan_date == RUN_DATE
            return {
                "run_id": "daily-candidate:stale-plan",
                "plan_date": "2026-06-30",
                "status": "no_candidates",
                "decision_outcome": "no_action",
                "input_fingerprint": "a" * 64,
                "no_action_reasons": ["decision_plan_date_mismatch"],
                "manual_ticket_candidate_count": 0,
            }

        async def _send_no_action_notification(self, *, result):
            nonlocal notifications
            notifications += 1
            assert result["decision_outcome"] == "no_action"
            return {"status": "sent", "sent": True}

    monkeypatch.setattr(
        automation_module,
        "build_daily_decision_evidence_automation_service",
        lambda state: FakeService(),
    )
    sleeps = 0

    async def stop_after_second_poll(_: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps >= 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_daily_decision_evidence_automation_loop(
                state=SimpleNamespace(db=db),
                interval_seconds=1,
                clock=lambda: DECISION_TIME,
                sleep=stop_after_second_poll,
            )
        )

    assert calls == 1
    assert notifications == 0
    assert not db.list_automation_runs_sync(
        run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
        run_date=RUN_DATE,
    )
    attempts = db.list_automation_runs_sync(
        run_type=DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
        run_date=RUN_DATE,
    )
    assert len(attempts) == 1
    assert attempts[0]["status"] == "failed_closed"
    assert attempts[0]["source_ref"] is None
    attempt_payload = json.loads(attempts[0]["payload_json"])
    assert attempt_payload["decision_outcome"] is None
    assert attempt_payload["input_fingerprint"] is None
    assert attempt_payload["notification"] is None
    assert attempt_payload["result_plan_date"] == "2026-06-30"
    assert attempt_payload["error_type"] == "ResultPlanDateMismatch"
    assert attempt_payload["operator_alert"]["status"] == "recorded"
    alerts = db.list_automation_alerts_sync(status="open")
    assert len(alerts) == 1
    assert alerts[0]["alert_key"] == (
        f"daily_candidate_background:{RUN_DATE}:failed_closed"
    )
    assert alerts[0]["category"] == "daily_candidate_background"
    alert_payload = json.loads(alerts[0]["payload_json"])
    assert alert_payload["outcome"] == "failed_closed"
    assert alert_payload["error_type"] == "ResultPlanDateMismatch"
    assert alert_payload["broker_submission_enabled"] is False
    assert alert_payload["authorizes_execution"] is False
    assert alert_payload["changes_capital_authority"] is False


def test_background_alert_for_manual_ticket_is_read_only_and_non_authorizing(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    evidence = automation_module._record_daily_candidate_background_alert(
        db=db,
        run_date=RUN_DATE,
        outcome="manual_order_ticket_candidate",
        result={
            "run_id": "daily-candidate:ticket",
            "input_fingerprint": "b" * 64,
            "manual_ticket_candidate_count": 2,
            "no_action_reasons": [],
        },
        error_type=None,
    )

    assert evidence["status"] == "recorded"
    alert = db.list_automation_alerts_sync(status="open")[0]
    assert alert["severity"] == "warning"
    assert alert["title"] == "Daily candidate tickets require human review"
    payload = json.loads(alert["payload_json"])
    assert payload["manual_ticket_candidate_count"] == 2
    assert payload["suggested_action"] == ("review_read_only_daily_candidate_tickets")
    assert payload["does_not_create_oms_order"] is True
    assert payload["does_not_mutate_production_ledger"] is True


def test_background_alert_failure_does_not_raise_or_expose_error_detail() -> None:
    class BrokenAlertStore:
        def upsert_automation_alert_sync(self, **kwargs):
            del kwargs
            raise RuntimeError("private backend detail")

    evidence = automation_module._record_daily_candidate_background_alert(
        db=BrokenAlertStore(),
        run_date=RUN_DATE,
        outcome="no_action",
        result={"no_action_reasons": ["account_truth_not_fresh"]},
        error_type=None,
    )

    assert evidence == {
        "status": "alert_store_failed",
        "recorded": False,
        "error_type": "RuntimeError",
    }
    assert "private" not in str(evidence)


def test_background_attempt_claim_is_atomic_and_fail_closed(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    payload = {
        "schema_version": "karkinos.daily_candidate_background_attempt.v1",
        "broker_submission_enabled": False,
    }

    first = db.claim_daily_candidate_background_attempt_sync(
        run_date=RUN_DATE,
        claimed_at=DECISION_TIME.isoformat(),
        payload=payload,
    )
    replay = db.claim_daily_candidate_background_attempt_sync(
        run_date=RUN_DATE,
        claimed_at=DECISION_TIME.isoformat(),
        payload=payload,
    )

    assert first["claimed"] is True
    assert replay["claimed"] is False
    assert first["run"]["run_id"] == replay["run"]["run_id"]
    assert (
        len(
            db.list_automation_runs_sync(
                run_type=DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
                run_date=RUN_DATE,
            )
        )
        == 1
    )


def test_background_unhandled_failure_finishes_attempt_and_opens_alert(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)

    class FailingService:
        async def run_once(self, *, expected_plan_date):
            assert expected_plan_date == RUN_DATE
            raise RuntimeError("private runtime detail")

    monkeypatch.setattr(
        automation_module,
        "build_daily_decision_evidence_automation_service",
        lambda state: FailingService(),
    )

    async def stop_after_failure(_: float) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_daily_decision_evidence_automation_loop(
                state=SimpleNamespace(db=db),
                interval_seconds=1,
                clock=lambda: DECISION_TIME,
                sleep=stop_after_failure,
            )
        )

    attempt = db.list_automation_runs_sync(
        run_type=DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
        run_date=RUN_DATE,
    )[0]
    assert attempt["status"] == "failed_closed"
    attempt_payload = json.loads(attempt["payload_json"])
    assert attempt_payload["error_type"] == "RuntimeError"
    assert "private" not in json.dumps(attempt_payload)
    assert attempt_payload["operator_alert"]["status"] == "recorded"
    alert = db.list_automation_alerts_sync(status="open")[0]
    assert alert["severity"] == "critical"
    payload = json.loads(alert["payload_json"])
    assert payload["outcome"] == "failed_closed"
    assert payload["error_type"] == "RuntimeError"
    assert payload["broker_submission_enabled"] is False
    assert payload["authorizes_execution"] is False
