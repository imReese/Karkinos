from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from server.db import AppDatabase
from server.services import daily_decision_evidence_automation as automation_module
from server.services.daily_decision_evidence_automation import (
    DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
    DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
    project_daily_candidate_background_schedule,
    run_daily_decision_evidence_automation_loop,
)

RUN_DATE = "2026-07-01"
DECISION_TIME = datetime(2026, 7, 1, 1, 36, tzinfo=timezone.utc)


def _seed_calendar(db: AppDatabase, *, is_trading_day: bool = True) -> None:
    db.upsert_market_calendar_snapshot_sync(
        {
            "exchange": "SSE",
            "year": 2026,
            "provider": "fixture",
            "schema_version": "karkinos.market_calendar.v1",
            "status": "available",
            "trading_day_count": 2 if is_trading_day else 1,
            "closed_day_count": 363 if is_trading_day else 364,
            "source_fingerprint": "calendar-fingerprint",
            "official_verification_status": "verified",
            "days": [
                {
                    "date": RUN_DATE,
                    "is_trading_day": is_trading_day,
                    "day_type": "trading_day" if is_trading_day else "closed",
                    "reason_code": "trading_day" if is_trading_day else "closed",
                },
                {
                    "date": "2026-07-02",
                    "is_trading_day": True,
                    "day_type": "trading_day",
                    "reason_code": "trading_day",
                },
            ],
        }
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
    for year, verified, days in (
        (
            2026,
            True,
            [
                {
                    "date": "2026-12-31",
                    "is_trading_day": True,
                    "day_type": "trading_day",
                    "reason_code": "trading_day",
                }
            ],
        ),
        (
            2027,
            True,
            [
                {
                    "date": "2027-01-04",
                    "is_trading_day": True,
                    "day_type": "trading_day",
                    "reason_code": "trading_day",
                }
            ],
        ),
    ):
        db.upsert_market_calendar_snapshot_sync(
            {
                "exchange": "SSE",
                "year": year,
                "provider": "fixture",
                "schema_version": "karkinos.market_calendar.v1",
                "status": "available",
                "trading_day_count": len(days),
                "closed_day_count": 365 - len(days),
                "source_fingerprint": f"calendar-{year}",
                "official_verification_status": (
                    "verified" if verified else "needs_review"
                ),
                "days": days,
            }
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


def test_background_loop_claims_once_even_when_result_plan_date_is_stale(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)
    calls = 0
    notifications = 0

    class FakeService:
        async def run_once(self):
            nonlocal calls
            calls += 1
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
    assert notifications == 1
    assert not db.list_automation_runs_sync(
        run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
        run_date=RUN_DATE,
    )
    attempts = db.list_automation_runs_sync(
        run_type=DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
        run_date=RUN_DATE,
    )
    assert len(attempts) == 1
    assert attempts[0]["status"] == "completed"
    assert attempts[0]["source_ref"] == "daily-candidate:stale-plan"
    attempt_payload = json.loads(attempts[0]["payload_json"])
    assert attempt_payload["decision_outcome"] == "no_action"
    assert attempt_payload["input_fingerprint"] == "a" * 64
    assert attempt_payload["no_action_reasons"] == ["decision_plan_date_mismatch"]
    assert attempt_payload["notification"] == {"status": "sent", "sent": True}
    assert attempt_payload["operator_alert"]["status"] == "recorded"
    alerts = db.list_automation_alerts_sync(status="open")
    assert len(alerts) == 1
    assert alerts[0]["alert_key"] == (
        f"daily_candidate_background:{RUN_DATE}:no_action"
    )
    assert alerts[0]["category"] == "daily_candidate_background"
    alert_payload = json.loads(alerts[0]["payload_json"])
    assert alert_payload["no_action_reasons"] == ["decision_plan_date_mismatch"]
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
        async def run_once(self):
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
