from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from server.ai_runtime.contracts import content_fingerprint
from server.db import AppDatabase
from server.services.decision import (
    daily_decision_evidence_automation as automation_module,
)
from server.services.decision.daily_decision_background_schedule import (
    project_daily_candidate_background_schedule,
)
from server.services.decision.daily_decision_evidence_automation import (
    DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
    DailyDecisionEvidenceAutomationService,
    run_daily_decision_evidence_automation_loop,
)
from server.services.decision.daily_decision_evidence_orchestration import (
    run_claimed_background_attempt,
)
from server.services.decision.decision_projection import (
    daily_candidate_generation_status,
    suppress_unverified_daily_scan_candidates,
)
from server.services.decision.decision_workflow_projection import (
    strategy_evidence_workflow_task,
    workflow_tasks,
)
from server.services.risk.trading_controls import TradingControlState
from server.services.strategy_scan.promoted_strategy_universe_scan import (
    PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE,
    PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION,
)
from server.services.strategy_scan.status import build_daily_candidate_runtime_status
from tests.test_daily_decision_evidence_automation import (
    RecordingNotifier,
    _decision,
    _fixture_account_truth_replay,
    _plan,
)

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


def _seed_scan_row(
    db: AppDatabase,
    *,
    run_date: str = RUN_DATE,
    candidate_count: int = 1,
) -> str:
    portfolio_binding = {
        "valuation_snapshot_id": "valuation-001",
        "valuation_status": "complete",
        "held_symbol_fingerprint": "sha256:" + "d" * 64,
        "held_stock_count": 1,
        "capital_constraint_fingerprint": "sha256:"
        + content_fingerprint(
            {
                "valuation_snapshot_id": "valuation-001",
                "valuation_status": "complete",
                "total_equity": 100_000.0,
            }
        ),
    }
    input_core = {
        "schema_version": PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION,
        "decision_date": run_date,
        "market_date": "2026-11-24",
        "market_universe_snapshot_id": "market-snapshot",
        "receipt_fingerprints": ["sha256:" + "9" * 64],
        "strategy_bindings": [
            {
                "strategy_id": "ai_formula_shadow:fixture",
                "strategy_artifact_fingerprint": "a" * 64,
                "order_generation_gate_fingerprint": "sha256:" + "b" * 64,
                "universe_truth_fingerprint": "sha256:" + "c" * 64,
            }
        ],
        "portfolio_binding": portfolio_binding,
        "evaluation_policy_fingerprint": "sha256:" + "6" * 64,
        "signal_selection_policy": "exits_first_then_20d_median_amount_desc_then_symbol_asc",
        "signal_selection_fingerprint": "sha256:" + "8" * 64,
        "safety_gate_fingerprint": "sha256:" + "7" * 64,
    }
    input_fingerprint = "sha256:" + content_fingerprint(input_core)
    scan_run_id = (
        f"automation:promoted-strategy-universe-scan:{run_date}:"
        + input_fingerprint.removeprefix("sha256:")[:16]
    )

    if candidate_count > 0:
        signals = [
            {
                "action_id": 1,
                "symbol": "600519",
                "side": "buy",
                "strategy_id": "ai_formula_shadow:fixture",
            }
        ]
        payload_core = {
            **input_core,
            "status": "completed",
            "input_fingerprint": input_fingerprint,
            "blockers": [],
            "raw_signal_count": 1,
            "selected_signal_count": 1,
            "selected_signals": signals,
            "action_tasks": signals,
            "full_market_truths": [],
            "normal_no_signal": False,
            "preview_only": False,
            "manual_confirmation_required": True,
            "creates_oms_order": False,
            "submits_broker_order": False,
            "mutates_account_ledger": False,
            "changes_strategy_promotion": False,
            "changes_capital_authority": False,
            "finished_at": f"{run_date}T01:35:00+00:00",
        }
        status = "completed"
    else:
        payload_core = {
            **input_core,
            "status": "completed_no_signal",
            "normal_no_signal": True,
            "input_fingerprint": input_fingerprint,
            "blockers": [],
            "raw_signal_count": 0,
            "selected_signal_count": 0,
            "selected_signals": [],
            "action_tasks": [],
            "full_market_truths": [],
            "preview_only": False,
            "manual_confirmation_required": True,
            "creates_oms_order": False,
            "submits_broker_order": False,
            "mutates_account_ledger": False,
            "changes_strategy_promotion": False,
            "changes_capital_authority": False,
            "finished_at": f"{run_date}T01:35:00+00:00",
        }
        status = "completed_no_signal"

    db.upsert_automation_run_sync(
        {
            "run_id": scan_run_id,
            "run_type": PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE,
            "run_date": run_date,
            "status": status,
            "execution_mode": "paper_shadow",
            "started_at": f"{run_date}T09:35:00+08:00",
            "finished_at": f"{run_date}T09:35:01+08:00",
            "source_ref": None,
            "payload": {
                **payload_core,
                "output_fingerprint": "sha256:" + content_fingerprint(payload_core),
            },
        }
    )
    return scan_run_id


def test_full_day_lifecycle_candidate_scenario(tmp_path) -> None:
    """Scenario A: Real isolated service orchestration producing validated candidate advice."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)
    scan_run_id = _seed_scan_row(db, candidate_count=1)

    db.upsert_strategy_promotion_state_sync(
        strategy_id="ai_formula_shadow:fixture",
        stage="paper_shadow",
        gate_status="paper_shadow_enabled",
        live_like_enabled=False,
    )

    state_box = {"risk_checked": False, "plan_reads": 0}

    async def read_plan():
        state_box["plan_reads"] += 1
        checked = bool(state_box["risk_checked"])
        dec = _decision(risk_checked=checked)
        dec["decision_date"] = RUN_DATE
        dec["generated_at"] = f"{RUN_DATE}T09:35:00+08:00"
        dec["summary"]["portfolio"]["valuation_snapshot_id"] = "valuation-001"
        dec["summary"]["account_truth"]["captured_at"] = f"{RUN_DATE}T09:30:00+08:00"
        dec["summary"]["market_data"]["latest_quote_timestamp"] = (
            f"{RUN_DATE}T09:34:00+08:00"
        )
        dec["summary"]["promoted_strategy_universe_scan"] = {
            "run_id": scan_run_id,
            "schema_version": PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION,
            "status": "completed",
            "normal_no_signal": False,
            "blockers": [],
        }
        dec["candidates"][0]["evidence"]["data_freshness"] = {
            "status": "fresh",
            "price": 10.0,
            "quote_timestamp": f"{RUN_DATE}T09:34:00+08:00",
            "quote_source": "persisted_fixture",
        }
        dec["candidates"][0]["evidence"]["strategy"]["order_generation_gate"][
            "as_of_date"
        ] = RUN_DATE
        p = _plan(risk_checked=checked)
        p["plan_date"] = RUN_DATE
        p["generated_at"] = f"{RUN_DATE}T09:35:00+08:00"
        if checked:
            for oi in p["order_intents"]:
                oi["market_quote_timestamp"] = f"{RUN_DATE}T09:34:00+08:00"
        return dec, p

    async def run_risk():
        state_box["risk_checked"] = True
        return {
            "status": "completed",
            "candidate_count": 1,
            "processed_count": 1,
            "passed_count": 1,
            "blocked_count": 0,
            "skipped_count": 0,
            "risk_decision_writes_performed": True,
            "blockers": [],
        }

    controls = TradingControlState(db=db)
    notifier = RecordingNotifier()
    service = DailyDecisionEvidenceAutomationService(
        db=db,
        trading_controls=controls,
        notifier=notifier,
        plan_reader=read_plan,
        risk_runner=run_risk,
        account_truth_replay_resolver=_fixture_account_truth_replay,
    )

    schedule = project_daily_candidate_background_schedule(db=db, now=DECISION_TIME)
    assert schedule["status"] == "due"
    assert schedule["due"] is True

    # Genuinely execute claimed background attempt with real service orchestration
    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=service,
            schedule=schedule,
            clock=lambda: DECISION_TIME,
        )
    )

    # Read back through real daily_candidate_generation_status contract
    gen = daily_candidate_generation_status(db, RUN_DATE)
    assert gen["status"] == "completed_with_candidates"
    assert gen["generation_verified"] is True
    assert gen["recommendation_authoritative"] is True
    assert gen["formal_candidate_action_ids"] == [1]
    assert gen["bound_scan_action_ids"] == [1]

    # Verify end-to-end decision projection
    candidate = {
        "action_id": 1,
        "symbol": "600519",
        "action": "buy",
        "quantity": 100,
        "price": 1800.0,
        "timestamp": DECISION_TIME.isoformat(),
    }
    candidate_summary = {
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
            generation=gen,
        ),
    }
    payload = {
        "lane": "daily",
        "decision": "buy",
        "decision_date": RUN_DATE,
        "summary": candidate_summary,
        "candidates": [candidate],
        "generation": gen,
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


def test_full_day_lifecycle_zero_signal_scenario(tmp_path) -> None:
    """Scenario B: Real isolated service orchestration producing verified clean zero-signal."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)
    scan_run_id = _seed_scan_row(db, candidate_count=0)

    db.upsert_strategy_promotion_state_sync(
        strategy_id="ai_formula_shadow:fixture",
        stage="paper_shadow",
        gate_status="paper_shadow_enabled",
        live_like_enabled=False,
    )

    async def read_zero_plan():
        dec = _decision(risk_checked=False)
        dec["decision_date"] = RUN_DATE
        dec["generated_at"] = f"{RUN_DATE}T09:35:00+08:00"
        dec["candidates"] = []
        dec["summary"]["candidate_count"] = 0
        dec["summary"]["portfolio"]["valuation_snapshot_id"] = "valuation-001"
        dec["summary"]["account_truth"]["captured_at"] = f"{RUN_DATE}T09:30:00+08:00"
        dec["summary"]["market_data"]["latest_quote_timestamp"] = (
            f"{RUN_DATE}T09:34:00+08:00"
        )
        dec["summary"]["promoted_strategy_universe_scan"] = {
            "run_id": scan_run_id,
            "schema_version": PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION,
            "status": "completed_no_signal",
            "normal_no_signal": True,
            "blockers": [],
        }
        p = _plan(risk_checked=False)
        p["plan_date"] = RUN_DATE
        p["generated_at"] = f"{RUN_DATE}T09:35:00+08:00"
        p["order_intents"] = []
        p["candidate_pool_count"] = 0
        p["manual_ready_count"] = 0
        p["blocked_count"] = 0
        p["blockers"] = []
        return dec, p

    async def run_risk():
        return {"status": "completed"}

    controls = TradingControlState(db=db)
    notifier = RecordingNotifier()
    service = DailyDecisionEvidenceAutomationService(
        db=db,
        trading_controls=controls,
        notifier=notifier,
        plan_reader=read_zero_plan,
        risk_runner=run_risk,
        account_truth_replay_resolver=_fixture_account_truth_replay,
    )

    schedule = project_daily_candidate_background_schedule(db=db, now=DECISION_TIME)
    assert schedule["status"] == "due"
    assert schedule["due"] is True

    # Real execution through run_claimed_background_attempt
    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=service,
            schedule=schedule,
            clock=lambda: DECISION_TIME,
        )
    )

    gen = daily_candidate_generation_status(db, RUN_DATE)
    assert gen["status"] == "completed_no_signal"
    assert gen["generation_verified"] is True
    assert gen["failure_code"] is None

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
            generation=gen,
        ),
    }
    payload = {
        "lane": "daily",
        "decision": "no_action",
        "decision_date": RUN_DATE,
        "summary": candidate_summary,
        "candidates": [],
        "generation": gen,
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


def test_full_day_lifecycle_timeout_protection(tmp_path, monkeypatch) -> None:
    """Scenario C: Bounded timeout in background loop catches timeout without crashing daemon."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)

    state = SimpleNamespace(db=db, daily_candidate_schedule_state={})
    clock_time = DECISION_TIME

    monkeypatch.setattr(
        automation_module,
        "project_daily_candidate_background_schedule",
        lambda *args, **kwargs: {
            "status": "decision_window_open",
            "due": True,
            "run_date": RUN_DATE,
            "attempt_run_id": f"automation:daily-candidate-background-attempt:{RUN_DATE}",
            "evidence_run_id": f"automation:daily-decision-evidence:{RUN_DATE}:test",
        },
    )

    async def timing_out_attempt(*args, **kwargs):
        raise TimeoutError("Attempt timed out after bounded timeout")

    monkeypatch.setattr(
        automation_module,
        "_run_claimed_background_attempt",
        timing_out_attempt,
    )
    monkeypatch.setattr(
        automation_module,
        "build_daily_decision_evidence_automation_service",
        lambda *args, **kwargs: SimpleNamespace(),
    )

    poll_count = 0

    async def stop_after_one_poll(_: float) -> None:
        nonlocal poll_count
        poll_count += 1
        raise asyncio.CancelledError

    # Loop should catch TimeoutError and record exception in schedule state
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
    assert sched.get("last_exception") == "TimeoutError"
    assert "Attempt timed out" in sched.get("last_exception_message", "")
    assert sched.get("current_stage") == "sleeping"


def test_corrupt_decision_evidence_fails_closed(tmp_path) -> None:
    """Scenario D: Corrupt, tampered, or mismatched evidence fails closed with concrete reasons."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)
    scan_run_id = _seed_scan_row(db, candidate_count=1)

    db.upsert_strategy_promotion_state_sync(
        strategy_id="ai_formula_shadow:fixture",
        stage="paper_shadow",
        gate_status="paper_shadow_enabled",
        live_like_enabled=False,
    )

    state_box = {"risk_checked": False, "plan_reads": 0}

    async def read_plan():
        state_box["plan_reads"] += 1
        checked = bool(state_box["risk_checked"])
        dec = _decision(risk_checked=checked)
        dec["decision_date"] = RUN_DATE
        dec["generated_at"] = f"{RUN_DATE}T09:35:00+08:00"
        dec["summary"]["portfolio"]["valuation_snapshot_id"] = "valuation-001"
        dec["summary"]["account_truth"]["captured_at"] = f"{RUN_DATE}T09:30:00+08:00"
        dec["summary"]["market_data"]["latest_quote_timestamp"] = (
            f"{RUN_DATE}T09:34:00+08:00"
        )
        dec["summary"]["promoted_strategy_universe_scan"] = {
            "run_id": scan_run_id,
            "schema_version": PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION,
            "status": "completed",
            "normal_no_signal": False,
            "blockers": [],
        }
        dec["candidates"][0]["evidence"]["data_freshness"] = {
            "status": "fresh",
            "price": 10.0,
            "quote_timestamp": f"{RUN_DATE}T09:34:00+08:00",
            "quote_source": "persisted_fixture",
        }
        dec["candidates"][0]["evidence"]["strategy"]["order_generation_gate"][
            "as_of_date"
        ] = RUN_DATE
        p = _plan(risk_checked=checked)
        p["plan_date"] = RUN_DATE
        p["generated_at"] = f"{RUN_DATE}T09:35:00+08:00"
        if checked:
            for oi in p["order_intents"]:
                oi["market_quote_timestamp"] = f"{RUN_DATE}T09:34:00+08:00"
        return dec, p

    async def run_risk():
        state_box["risk_checked"] = True
        return {
            "status": "completed",
            "candidate_count": 1,
            "processed_count": 1,
            "passed_count": 1,
            "blocked_count": 0,
            "skipped_count": 0,
            "risk_decision_writes_performed": True,
            "blockers": [],
        }

    controls = TradingControlState(db=db)
    service = DailyDecisionEvidenceAutomationService(
        db=db,
        trading_controls=controls,
        notifier=RecordingNotifier(),
        plan_reader=read_plan,
        risk_runner=run_risk,
        account_truth_replay_resolver=_fixture_account_truth_replay,
    )

    schedule = project_daily_candidate_background_schedule(db=db, now=DECISION_TIME)
    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=service,
            schedule=schedule,
            clock=lambda: DECISION_TIME,
        )
    )

    # Base genuine run verified
    gen = daily_candidate_generation_status(db, RUN_DATE)
    assert gen["status"] == "completed_with_candidates"
    assert gen["generation_verified"] is True

    attempt_row = db.list_automation_runs_sync(
        run_date=RUN_DATE,
        run_type=DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
    )[0]
    evidence_row = db.get_automation_run_sync(attempt_row["source_ref"])
    assert evidence_row is not None
    original_attempt_payload = json.loads(attempt_row["payload_json"])
    original_evidence_payload = json.loads(evidence_row["payload_json"])

    # Case 1: daily_evidence_link_invalid (attempt source_ref does not match result_run_id)
    attempt_row["source_ref"] = "mismatched-ref"
    attempt_row["payload"] = original_attempt_payload
    db.upsert_automation_run_sync(attempt_row)

    gen = daily_candidate_generation_status(db, RUN_DATE)
    assert gen["status"] == "blocked"
    assert gen["generation_verified"] is False
    assert gen["failure_code"] == "daily_evidence_link_invalid"

    task = strategy_evidence_workflow_task(
        strategy_attribution={"gate_status": "pass"},
        candidate_count=0,
        generation=gen,
    )
    assert task["status"] == "blocked"
    assert task["blocking_reasons"] == ["daily_evidence_link_invalid"]

    proj = suppress_unverified_daily_scan_candidates(
        {
            "lane": "daily",
            "decision": "no_action",
            "decision_date": RUN_DATE,
            "summary": {
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
                    generation=gen,
                ),
            },
            "candidates": [],
            "generation": gen,
            "no_action_reasons": ["no_pending_action_tasks"],
        }
    )
    assert proj["decision"] == "no_action"
    assert proj["no_action_reasons"] == ["daily_generation_blocked"]

    # Case 2: daily_evidence_missing (evidence row does not exist in DB)
    missing_ev_id = "automation:daily-decision-evidence:nonexistent"
    attempt_row["source_ref"] = missing_ev_id
    attempt_payload_missing = dict(original_attempt_payload)
    attempt_payload_missing["result_run_id"] = missing_ev_id
    attempt_row["payload"] = attempt_payload_missing
    db.upsert_automation_run_sync(attempt_row)

    gen = daily_candidate_generation_status(db, RUN_DATE)
    assert gen["status"] == "blocked"
    assert gen["generation_verified"] is False
    assert gen["failure_code"] == "daily_evidence_missing"

    # Case 3: daily_evidence_fingerprint_invalid (payload tampered with)
    attempt_row["source_ref"] = evidence_row["run_id"]
    attempt_row["payload"] = original_attempt_payload
    db.upsert_automation_run_sync(attempt_row)

    tampered_ev_payload = dict(original_evidence_payload)
    tampered_ev_payload["candidate_count"] = 999  # tampered field
    evidence_row["payload"] = tampered_ev_payload
    db.upsert_automation_run_sync(evidence_row)

    gen = daily_candidate_generation_status(db, RUN_DATE)
    assert gen["status"] == "blocked"
    assert gen["generation_verified"] is False
    assert gen["failure_code"] == "daily_evidence_fingerprint_invalid"

    # Case 4: daily_evidence_outcome_mismatch
    evidence_row["payload"] = original_evidence_payload  # restore valid evidence
    db.upsert_automation_run_sync(evidence_row)

    mismatched_attempt_payload = dict(original_attempt_payload)
    mismatched_attempt_payload["decision_outcome"] = "no_action"  # mismatch
    attempt_row["payload"] = mismatched_attempt_payload
    db.upsert_automation_run_sync(attempt_row)

    gen = daily_candidate_generation_status(db, RUN_DATE)
    assert gen["status"] == "blocked"
    assert gen["generation_verified"] is False
    assert gen["failure_code"] == "daily_evidence_outcome_mismatch"

    # Case 5: Unconfigured / non-daily fallback
    # 5a. Database without automation tables / unconfigured capability
    gen_unconfigured = daily_candidate_generation_status(
        SimpleNamespace(), "2026-11-20"
    )
    assert gen_unconfigured["status"] == "unavailable"
    assert gen_unconfigured.get("failure_code") is None

    # Fallback preserves valid strategy attribution status without failing closed
    task_fallback = strategy_evidence_workflow_task(
        strategy_attribution={"gate_status": "pass"},
        candidate_count=0,
        generation=gen_unconfigured,
    )
    assert task_fallback["status"] == "pass"

    proj_fallback = suppress_unverified_daily_scan_candidates(
        {
            "lane": "daily",
            "decision": "no_action",
            "decision_date": "2026-11-20",
            "summary": {
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
                    generation=gen_unconfigured,
                ),
            },
            "candidates": [],
            "generation": gen_unconfigured,
            "no_action_reasons": ["no_pending_action_tasks"],
        }
    )
    assert proj_fallback["decision"] == "no_action"
    assert proj_fallback["no_action_reasons"] == ["no_pending_action_tasks"]

    # 5b. Empty database where no decision attempt exists for an arbitrary historical date
    empty_db = AppDatabase(tmp_path / "empty.db")
    empty_db.init_sync()
    gen_empty = daily_candidate_generation_status(empty_db, "2026-11-20")
    assert gen_empty["status"] == "not_generated"
    assert gen_empty.get("failure_code") is None


def test_missed_window_scenario_blocks_strategy_evidence_and_no_action_reasons() -> (
    None
):
    """Scenario E: Missed window must block strategy_evidence and populate no_action_reasons."""
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
    """Scenario F: Observability fields recorded in schedule_state and cockpit."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_calendar(db)

    state = SimpleNamespace(db=db, daily_candidate_schedule_state={})
    clock_time = PREPARATION_TIME

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
