from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from server.db import AppDatabase
from server.services.decision import (
    daily_decision_evidence_automation as automation_module,
)
from server.services.decision.daily_decision_evidence_automation import (
    DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
    DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE,
    DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
    project_daily_candidate_background_schedule,
    run_daily_decision_evidence_automation_loop,
)
from server.services.decision.decision_projection import (
    suppress_unverified_daily_scan_candidates,
)
from server.services.decision.decision_workflow_projection import workflow_tasks
from server.services.strategy_scan.status import build_daily_candidate_runtime_status

RUN_DATE = "2026-11-25"
PREPARATION_TIME = datetime(
    2026, 11, 25, 0, 45, tzinfo=timezone.utc
)  # 08:45 Asia/Shanghai
DECISION_TIME = datetime(
    2026, 11, 25, 1, 36, tzinfo=timezone.utc
)  # 09:36 Asia/Shanghai
AFTER_WINDOW_TIME = datetime(
    2026, 11, 25, 1, 46, tzinfo=timezone.utc
)  # 09:46 Asia/Shanghai


def _seed_calendar(db: AppDatabase) -> None:
    current = date(2026, 1, 1)
    calendar_days = []
    trading_dates = {RUN_DATE, "2026-11-24", "2026-11-23"}
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
    source_fingerprint = "c" * 64
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
        official_source_fingerprint="d" * 64,
        verified_by="fixture",
    )


def _preparation_result(
    *, run_date: str = RUN_DATE, blocked: bool = False
) -> dict[str, object]:
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
        "run_date": run_date,
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


def test_full_day_lifecycle_candidate_scenario(tmp_path, monkeypatch) -> None:
    """Scenario A: Controlled clock replay producing validated candidates."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)

    # 1. Preparation check at 08:45
    prep_called = 0

    def mock_prep(state, *, run_date):
        nonlocal prep_called
        prep_called += 1
        return _preparation_result(run_date=run_date, blocked=False)

    monkeypatch.setattr(
        automation_module,
        "build_daily_candidate_preparation_check",
        mock_prep,
    )

    state = SimpleNamespace(db=db, daily_candidate_schedule_state={})
    clock_time = PREPARATION_TIME

    sleep_count = 0

    async def advance_clock_and_stop(seconds: float) -> None:
        nonlocal clock_time, sleep_count
        sleep_count += 1
        if sleep_count == 1:
            clock_time = DECISION_TIME
        else:
            raise asyncio.CancelledError

    # Mock claimed background attempt to produce a candidate
    attempt_claimed = 0

    async def mock_run_attempt(*, db, service, schedule, clock):
        nonlocal attempt_claimed
        attempt_claimed += 1
        run_id = schedule["attempt_run_id"]
        evidence_run_id = schedule["evidence_run_id"]
        db.upsert_automation_run_sync(
            {
                "run_id": run_id,
                "run_type": DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
                "run_date": schedule["run_date"],
                "status": "completed",
                "execution_mode": "paper_shadow",
                "started_at": clock().isoformat(),
                "finished_at": clock().isoformat(),
                "source_ref": evidence_run_id,
                "payload": {"status": "completed"},
            }
        )
        db.upsert_automation_run_sync(
            {
                "run_id": evidence_run_id,
                "run_type": DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
                "run_date": schedule["run_date"],
                "status": "completed_with_candidates",
                "execution_mode": "paper_shadow",
                "started_at": clock().isoformat(),
                "finished_at": clock().isoformat(),
                "source_ref": run_id,
                "payload": {
                    "candidate_count": 1,
                    "action_ticket_candidate_ids": [101],
                    "recommendation_authoritative": True,
                },
            }
        )

    monkeypatch.setattr(
        automation_module,
        "_run_claimed_background_attempt",
        mock_run_attempt,
    )
    monkeypatch.setattr(
        automation_module,
        "build_daily_decision_evidence_automation_service",
        lambda *args, **kwargs: SimpleNamespace(),
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_daily_decision_evidence_automation_loop(
                state=state,
                interval_seconds=1,
                clock=lambda: clock_time,
                sleep=advance_clock_and_stop,
            )
        )

    assert prep_called == 1
    assert attempt_claimed == 1

    # Verify projection with validated candidates
    candidate = {
        "action_id": 101,
        "symbol": "600519",
        "action": "buy",
        "quantity": 100,
        "price": 1800.0,
        "timestamp": DECISION_TIME.isoformat(),
    }
    payload = {
        "lane": "daily",
        "decision": "buy",
        "decision_date": RUN_DATE,
        "summary": {
            "market_data": {"source_health": "live"},
            "account_truth": {"gate_status": "pass"},
            "strategy_attribution": {"gate_status": "pass"},
            "action_tasks": {"pending_count": 1},
            "audit": {},
            "workflow_tasks": workflow_tasks(
                market_data={"source_health": "live"},
                account_truth={"gate_status": "pass"},
                strategy_attribution={"gate_status": "pass"},
                action_tasks={"pending_count": 1},
                audit={},
                candidate_count=1,
                ready_for_manual_confirmation_count=1,
                generation={
                    "status": "completed_with_candidates",
                    "generation_verified": True,
                    "recommendation_authoritative": True,
                },
            ),
        },
        "candidates": [candidate],
        "generation": {
            "status": "completed_with_candidates",
            "generation_verified": True,
            "recommendation_authoritative": True,
            "formal_candidate_action_ids": [101],
            "bound_scan_action_ids": [101],
        },
        "no_action_reasons": [],
    }

    projected = suppress_unverified_daily_scan_candidates(payload)
    assert projected["decision"] == "buy"
    assert len(projected["candidates"]) == 1
    strategy_task = next(
        t
        for t in projected["summary"]["workflow_tasks"]
        if t["id"] == "strategy_evidence"
    )
    assert strategy_task["status"] == "pass"


def test_full_day_lifecycle_zero_signal_scenario(tmp_path, monkeypatch) -> None:
    """Scenario B: Controlled clock replay producing verified clean zero-signal."""
    candidate_summary = {
        "market_data": {"source_health": "live"},
        "account_truth": {"gate_status": "pass"},
        "strategy_attribution": {"gate_status": "pass"},
        "action_tasks": {"pending_count": 0},
        "audit": {},
        "workflow_tasks": workflow_tasks(
            market_data={"source_health": "live"},
            account_truth={"gate_status": "pass"},
            strategy_attribution={"gate_status": "pass"},
            action_tasks={"pending_count": 0},
            audit={},
            candidate_count=0,
            ready_for_manual_confirmation_count=0,
            generation={
                "status": "completed_no_signal",
                "generation_verified": True,
                "recommendation_authoritative": True,
            },
        ),
    }
    payload = {
        "lane": "daily",
        "decision": "no_action",
        "decision_date": RUN_DATE,
        "summary": candidate_summary,
        "candidates": [],
        "generation": {
            "status": "completed_no_signal",
            "generation_verified": True,
            "recommendation_authoritative": True,
            "formal_candidate_action_ids": [],
            "bound_scan_action_ids": [],
        },
        "no_action_reasons": ["no_pending_action_tasks"],
    }

    projected = suppress_unverified_daily_scan_candidates(payload)
    assert projected["decision"] == "no_action"
    assert projected["no_action_reasons"] == ["no_pending_action_tasks"]
    strategy_task = next(
        t
        for t in projected["summary"]["workflow_tasks"]
        if t["id"] == "strategy_evidence"
    )
    assert strategy_task["status"] == "pass"


def test_missed_window_scenario_blocks_strategy_evidence_and_no_action_reasons() -> (
    None
):
    """Scenario C: Missed window must block strategy_evidence and populate no_action_reasons."""
    initial_summary = {
        "market_data": {"source_health": "live"},
        "account_truth": {"gate_status": "pass"},
        "strategy_attribution": {"gate_status": "pass"},
        "action_tasks": {"pending_count": 0},
        "audit": {},
        "workflow_tasks": workflow_tasks(
            market_data={"source_health": "live"},
            account_truth={"gate_status": "pass"},
            strategy_attribution={"gate_status": "pass"},
            action_tasks={"pending_count": 0},
            audit={},
            candidate_count=0,
            ready_for_manual_confirmation_count=0,
            generation={
                "status": "missed_window",
                "generation_verified": False,
                "failure_code": "daily_candidate_background_window_missed",
            },
        ),
    }
    payload = {
        "lane": "daily",
        "decision": "no_action",
        "decision_date": RUN_DATE,
        "summary": initial_summary,
        "candidates": [],
        "generation": {
            "status": "missed_window",
            "generation_verified": False,
            "failure_code": "daily_candidate_background_window_missed",
        },
        "no_action_reasons": ["no_pending_action_tasks"],
    }

    projected = suppress_unverified_daily_scan_candidates(payload)
    assert projected["no_action_reasons"] == ["daily_generation_missed_window"]
    strategy_task = next(
        t
        for t in projected["summary"]["workflow_tasks"]
        if t["id"] == "strategy_evidence"
    )
    assert strategy_task["status"] == "blocked"
    assert strategy_task["blocking_reasons"] == [
        "daily_candidate_background_window_missed"
    ]


def test_schedule_state_observability_fields(tmp_path, monkeypatch) -> None:
    """Scenario D: Observability fields recorded in schedule_state and cockpit."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)

    state = SimpleNamespace(db=db, daily_candidate_schedule_state={})
    clock_time = PREPARATION_TIME

    monkeypatch.setattr(
        automation_module,
        "build_daily_candidate_preparation_check",
        lambda state, *, run_date: _preparation_result(
            run_date=run_date, blocked=False
        ),
    )

    poll_count = 0

    async def stop_after_one_poll(_: float) -> None:
        nonlocal poll_count
        poll_count += 1
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_daily_decision_evidence_automation_loop(
                state=state,
                interval_seconds=1,
                clock=lambda: clock_time,
                sleep=stop_after_one_poll,
            )
        )

    sched = state.daily_candidate_schedule_state
    assert sched.get("last_poll_started_at") == PREPARATION_TIME.isoformat()
    assert sched.get("last_poll_finished_at") == PREPARATION_TIME.isoformat()
    assert (
        sched.get("last_successful_schedule_check_at") == PREPARATION_TIME.isoformat()
    )
    assert sched.get("latest_schedule_status") == "waiting_for_decision_window"
    assert sched.get("next_expected_check_at") is not None

    schedule = project_daily_candidate_background_schedule(db=db, now=clock_time)
    runtime_status = build_daily_candidate_runtime_status(
        config=None,
        monitor_task=None,
        background_schedule=schedule,
        schedule_state=sched,
    )
    assert runtime_status.get("schedule_state") == sched


def test_historical_failure_facts_preserved(tmp_path) -> None:
    """Scenario E: Historical records for 2026-11-23 and 2026-11-24 are preserved."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    # Insert historical failure records for 2026-11-23
    db.upsert_automation_run_sync(
        {
            "run_id": "automation:daily-candidate-background-attempt:2026-11-23",
            "run_type": DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
            "run_date": "2026-11-23",
            "status": "failed_closed",
            "execution_mode": "paper_shadow",
            "started_at": "2026-11-23T01:36:00+00:00",
            "finished_at": "2026-11-23T01:36:05+00:00",
            "source_ref": None,
            "payload": {
                "outcome": "failed_closed",
                "error": "selected_quote_run_mismatch:601985",
            },
        }
    )

    # Insert historical record for 2026-11-24
    db.upsert_automation_run_sync(
        {
            "run_id": "automation:daily-candidate-preparation:2026-11-24",
            "run_type": DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE,
            "run_date": "2026-11-24",
            "status": "ready_for_window_time_evidence",
            "execution_mode": "paper_shadow",
            "started_at": "2026-11-24T00:46:14+00:00",
            "finished_at": "2026-11-24T00:46:14+00:00",
            "source_ref": None,
            "payload": {"status": "ready_for_window_time_evidence"},
        }
    )

    # Verify both records exist and remain intact
    runs_23 = db.list_automation_runs_sync(run_date="2026-11-23")
    runs_24 = db.list_automation_runs_sync(run_date="2026-11-24")

    assert len(runs_23) == 1
    assert runs_23[0]["status"] == "failed_closed"
    assert (
        runs_23[0]["run_id"]
        == "automation:daily-candidate-background-attempt:2026-11-23"
    )

    assert len(runs_24) == 1
    assert runs_24[0]["status"] == "ready_for_window_time_evidence"
    assert runs_24[0]["run_id"] == "automation:daily-candidate-preparation:2026-11-24"
