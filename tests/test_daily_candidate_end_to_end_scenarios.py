from __future__ import annotations

import asyncio
import copy
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from core.types import AssetClass
from data.store import DataStore
from server.ai_runtime.contracts import content_fingerprint
from server.db import AppDatabase
from server.projections.valuation_snapshot import (
    build_current_valuation_snapshot,
)
from server.services.decision import (
    daily_decision_evidence_automation as automation_module,
)
from server.services.decision.daily_decision_background_schedule import (
    project_daily_candidate_background_schedule,
)
from server.services.decision.daily_decision_evidence_automation import (
    DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
    DailyDecisionEvidenceAutomationService,
    build_daily_decision_evidence_automation_service,
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
from server.services.market.market_universe_truth import MarketUniversePolicy
from server.services.market.quotes import (
    build_quote_ingestion_command,
    persist_quote_ingestion,
)
from server.services.risk.trading_controls import TradingControlState
from server.services.strategy_scan.promoted_strategy_universe_scan import (
    PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE,
    PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION,
    PromotedStrategyUniverseScanService,
)
from server.services.strategy_scan.status import build_daily_candidate_runtime_status
from server.services.strategy_scan.universe import service as universe_service_module
from tests.server.test_promoted_strategy_universe_scan import (
    _calendar,
    _formula,
    _freeze_market,
    _valuation_id,
)
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


def test_integrated_orchestration_candidate_pipeline(tmp_path) -> None:
    """Full lifecycle with real scanner evaluation, real quote freezing, risk runner, and verified readback."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    market_dates = _calendar(db)
    store = DataStore(tmp_path / "market")
    symbols = _freeze_market(store, market_dates)
    run_date = "2026-08-24"

    strategy_id = "ai_formula_shadow:fixture-winner"
    db.upsert_strategy_promotion_state_sync(
        strategy_id=strategy_id,
        stage="paper_shadow",
        gate_status="paper_shadow_enabled",
        live_like_enabled=False,
        missing_requirements=[],
        backtest_result_id=1,
        payload={},
    )

    strategy = {
        "formula_ast": _formula(produces_signals=True),
        "formula_fingerprint": "sha256:fixture-formula",
        "selected_universe": symbols[:40],
    }
    strategy_fingerprint = content_fingerprint(strategy)

    def gate_resolver(_db, requested_strategy_id, *, as_of_date):
        return {
            "status": "pass",
            "promotion": {
                "daily_strategy_artifact_binding": {
                    "winner_candidate_id": "fixture-winner",
                    "run_id": "fixture-run",
                    "operating_constraints": {
                        "strategy_artifact_fingerprint": strategy_fingerprint,
                    },
                }
            },
        }, []

    def strategy_loader(*, candidate_id, run_id):
        return {
            "candidate_id": candidate_id,
            "run_id": run_id,
            "strategy_artifact_fingerprint": strategy_fingerprint,
            "strategy": strategy,
        }

    controls = TradingControlState(db=db)
    config = SimpleNamespace(data_source="akshare", start_date="2026-04-01")
    decision_time = datetime(2026, 8, 24, 1, 36, tzinfo=timezone.utc)
    scanner = PromotedStrategyUniverseScanService(
        db=db,
        config=config,
        data_store=store,
        policy=MarketUniversePolicy(minimum_master_member_count=40),
        strategy_gate_resolver=gate_resolver,
        strategy_loader=strategy_loader,
        safety_gate_reader=lambda: {
            "default_execution_mode": "manual_confirmation",
            "manual_confirmation_required": True,
            "broker_submission_enabled": False,
            "kill_switch_enabled": False,
        },
        clock=lambda: datetime(2026, 8, 24, 9, 36, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    state = SimpleNamespace(
        db=db,
        config=config,
        data_store=store,
        scanner=scanner,
        trading_controls=controls,
        notifier=RecordingNotifier(),
    )

    valuation_id = _valuation_id(db)

    async def quote_refresher(_state, symbol, asset_type, *, fetch_run_id=None):
        command = build_quote_ingestion_command(
            symbol=symbol,
            asset_type=asset_type.value
            if hasattr(asset_type, "value")
            else str(asset_type),
            snapshot={
                "price": 20.0,
                "timestamp": f"{run_date}T09:34:00+08:00",
                "quote_status": "live",
                "provider_name": "akshare",
                "quote_source": "persisted_fixture",
            },
            quote_source="persisted_fixture",
            provider_name="akshare",
            provider_status="live",
            quote_status="live",
            captured_reason="daily_candidate_freeze",
            fetch_run_id=fetch_run_id,
        )
        persist_quote_ingestion(db, command)
        return {
            "symbol": symbol,
            "status": "refreshed",
            "price": 20.0,
            "quote_timestamp": f"{run_date}T09:34:00+08:00",
        }

    async def read_base_plan(_state):
        dec = _decision(risk_checked=True)
        dec["decision_date"] = run_date
        dec["generated_at"] = f"{run_date}T09:35:00+08:00"
        dec["summary"]["portfolio"]["valuation_snapshot_id"] = valuation_id
        dec["summary"]["portfolio"]["valuation_status"] = "complete"
        dec["summary"]["portfolio"]["fact_authority"] = "persisted_valuation_snapshot"
        dec["summary"]["portfolio"]["total_equity"] = 100_000.0
        dec["summary"]["portfolio"]["cash"] = 100_000.0
        dec["summary"]["portfolio"]["board_buy_permissions"] = {
            "main": "allowed",
            "gem": "allowed",
            "star": "allowed",
            "b_share": "allowed",
        }
        dec["summary"]["account_truth"]["captured_at"] = f"{run_date}T09:30:00+08:00"
        dec["summary"]["market_data"]["latest_quote_timestamp"] = (
            f"{run_date}T09:34:00+08:00"
        )
        dec["candidates"][0]["evidence"]["strategy"]["order_generation_gate"][
            "as_of_date"
        ] = run_date
        dec["candidates"][0]["evidence"]["data_freshness"] = {
            "status": "fresh",
            "price": 20.0,
            "quote_timestamp": f"{run_date}T09:34:00+08:00",
            "quote_source": "persisted_fixture",
        }

        p = _plan(risk_checked=True)
        p["plan_date"] = run_date
        p["generated_at"] = f"{run_date}T09:35:00+08:00"
        for oi in p["order_intents"]:
            oi["market_quote_timestamp"] = f"{run_date}T09:34:00+08:00"
        return dec, p

    async def run_risk(_state):
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

    service = build_daily_decision_evidence_automation_service(
        state,
        plan_reader=read_base_plan,
        risk_runner=run_risk,
        quote_refresher=quote_refresher,
    )
    service._account_truth_replay_resolver = _fixture_account_truth_replay

    schedule = project_daily_candidate_background_schedule(db=db, now=decision_time)
    assert schedule["status"] == "due"
    assert schedule["due"] is True

    # Real claimed background execution
    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=service,
            schedule=schedule,
            clock=lambda: decision_time,
        )
    )

    gen = daily_candidate_generation_status(db, run_date, now=decision_time)
    assert gen["status"] == "completed_with_candidates"
    assert gen["generation_verified"] is True
    assert gen["recommendation_authoritative"] is True
    assert gen["failure_code"] is None

    tasks = workflow_tasks(
        market_data={"source_health": "live"},
        account_truth={"gate_status": "pass"},
        strategy_attribution={"gate_status": "pass"},
        action_tasks={"pending_count": 0},
        audit={},
        candidate_count=1,
        ready_for_manual_confirmation_count=1,
        generation=gen,
    )
    strategy_task = next(t for t in tasks if t["id"] == "strategy_evidence")
    assert strategy_task["status"] == "pass"


def test_integrated_orchestration_zero_signal_pipeline(tmp_path) -> None:
    """Full lifecycle with real scanner zero-signal evaluation and verified normal_no_signal projection."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    market_dates = _calendar(db)
    store = DataStore(tmp_path / "market")
    symbols = _freeze_market(store, market_dates)
    run_date = "2026-08-24"

    strategy_id = "ai_formula_shadow:fixture-winner"
    db.upsert_strategy_promotion_state_sync(
        strategy_id=strategy_id,
        stage="paper_shadow",
        gate_status="paper_shadow_enabled",
        live_like_enabled=False,
        missing_requirements=[],
        backtest_result_id=1,
        payload={},
    )

    strategy = {
        "formula_ast": _formula(produces_signals=False),
        "formula_fingerprint": "sha256:fixture-formula",
        "selected_universe": symbols[:40],
    }
    strategy_fingerprint = content_fingerprint(strategy)

    def gate_resolver(_db, requested_strategy_id, *, as_of_date):
        return {
            "status": "pass",
            "promotion": {
                "daily_strategy_artifact_binding": {
                    "winner_candidate_id": "fixture-winner",
                    "run_id": "fixture-run",
                    "operating_constraints": {
                        "strategy_artifact_fingerprint": strategy_fingerprint,
                    },
                }
            },
        }, []

    def strategy_loader(*, candidate_id, run_id):
        return {
            "candidate_id": candidate_id,
            "run_id": run_id,
            "strategy_artifact_fingerprint": strategy_fingerprint,
            "strategy": strategy,
        }

    controls = TradingControlState(db=db)
    config = SimpleNamespace(data_source="akshare", start_date="2026-04-01")
    decision_time = datetime(2026, 8, 24, 1, 36, tzinfo=timezone.utc)
    scanner = PromotedStrategyUniverseScanService(
        db=db,
        config=config,
        data_store=store,
        policy=MarketUniversePolicy(minimum_master_member_count=40),
        strategy_gate_resolver=gate_resolver,
        strategy_loader=strategy_loader,
        safety_gate_reader=lambda: {
            "default_execution_mode": "manual_confirmation",
            "manual_confirmation_required": True,
            "broker_submission_enabled": False,
            "kill_switch_enabled": False,
        },
        clock=lambda: datetime(2026, 8, 24, 9, 36, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    state = SimpleNamespace(
        db=db,
        config=config,
        data_store=store,
        scanner=scanner,
        trading_controls=controls,
        notifier=RecordingNotifier(),
    )

    valuation_id = _valuation_id(db)

    async def quote_refresher(_state, symbol, _asset_type, *, fetch_run_id=None):
        return {"symbol": symbol, "status": "refreshed", "price": 10.0}

    async def read_base_plan(_state):
        dec = _decision(risk_checked=True)
        dec["decision_date"] = run_date
        dec["generated_at"] = f"{run_date}T09:35:00+08:00"
        dec["candidates"] = []
        dec["summary"]["candidate_count"] = 0
        dec["summary"]["portfolio"]["valuation_snapshot_id"] = valuation_id
        dec["summary"]["portfolio"]["valuation_status"] = "complete"
        dec["summary"]["portfolio"]["fact_authority"] = "persisted_valuation_snapshot"
        dec["summary"]["portfolio"]["total_equity"] = 100_000.0
        dec["summary"]["portfolio"]["cash"] = 100_000.0
        dec["summary"]["portfolio"]["board_buy_permissions"] = {
            "main": "allowed",
            "gem": "allowed",
            "star": "allowed",
            "b_share": "allowed",
        }
        dec["summary"]["account_truth"]["captured_at"] = f"{run_date}T09:30:00+08:00"
        dec["summary"]["market_data"]["latest_quote_timestamp"] = (
            f"{run_date}T09:34:00+08:00"
        )

        p = _plan(risk_checked=True)
        p["plan_date"] = run_date
        p["generated_at"] = f"{run_date}T09:35:00+08:00"
        p["order_intents"] = []
        p["candidate_pool_count"] = 0
        return dec, p

    async def run_risk(_state):
        return {
            "status": "completed",
            "candidate_count": 0,
            "processed_count": 0,
            "passed_count": 0,
            "blocked_count": 0,
            "skipped_count": 0,
            "risk_decision_writes_performed": True,
            "blockers": [],
        }

    service = build_daily_decision_evidence_automation_service(
        state,
        plan_reader=read_base_plan,
        risk_runner=run_risk,
        quote_refresher=quote_refresher,
    )
    service._account_truth_replay_resolver = _fixture_account_truth_replay

    schedule = project_daily_candidate_background_schedule(db=db, now=decision_time)
    assert schedule["status"] == "due"
    assert schedule["due"] is True

    # Real claimed background execution
    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=service,
            schedule=schedule,
            clock=lambda: decision_time,
        )
    )

    gen = daily_candidate_generation_status(db, run_date, now=decision_time)
    assert gen["status"] == "completed_no_signal"
    assert gen["generation_verified"] is True
    assert gen["failure_code"] is None
    from server.services.decision.daily_decision_report import get_daily_decision_report

    no_signal_report = get_daily_decision_report(db, run_date)
    assert no_signal_report["status"] == "completed_no_signal"

    tasks = workflow_tasks(
        market_data={"source_health": "live"},
        account_truth={"gate_status": "pass"},
        strategy_attribution={"gate_status": "pass"},
        action_tasks={"pending_count": 0},
        audit={},
        candidate_count=0,
        ready_for_manual_confirmation_count=0,
        generation=gen,
    )
    strategy_task = next(t for t in tasks if t["id"] == "strategy_evidence")
    assert strategy_task["status"] == "pass"


def test_claimed_attempt_cancellation_after_window_outcome(tmp_path) -> None:
    """An attempt claimed in DB but left unfinished due to cancellation or timeout fails closed after window."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _calendar(db)
    run_date = "2026-08-24"

    attempt_run_id = f"automation:daily-candidate-background-attempt:{run_date}"
    db.upsert_automation_run_sync(
        {
            "run_id": attempt_run_id,
            "run_type": "daily_candidate_background_attempt",
            "run_date": run_date,
            "status": "claimed",
            "execution_mode": "paper_shadow",
            "started_at": f"{run_date}T09:35:00+08:00",
            "finished_at": None,
            "source_ref": None,
            "payload": {},
        }
    )

    after_window_time = datetime(2026, 8, 24, 1, 46, tzinfo=timezone.utc)
    schedule = project_daily_candidate_background_schedule(db=db, now=after_window_time)
    assert schedule["status"] == "claim_unresolved_after_window"
    assert schedule["due"] is False
    assert "daily_candidate_claim_unresolved" in schedule["blockers"]

    gen = daily_candidate_generation_status(db, run_date, now=after_window_time)
    assert gen["status"] == "claim_unresolved"
    assert gen["generation_verified"] is False

    tasks = workflow_tasks(
        market_data={"source_health": "live"},
        account_truth={"gate_status": "pass"},
        strategy_attribution={"gate_status": "pass"},
        action_tasks={"pending_count": 0},
        audit={},
        candidate_count=0,
        ready_for_manual_confirmation_count=0,
        generation=gen,
    )
    strategy_task = next(t for t in tasks if t["id"] == "strategy_evidence")
    assert strategy_task["status"] == "blocked"
    assert strategy_task["blocking_reasons"] == ["daily_candidate_claim_unresolved"]


def _setup_quote_drift_environment(
    tmp_path,
    *,
    initial_cash: float = 100_000.0,
    buy_date: str = "2026-08-24",
    buy_timestamp: str | None = None,
    seed_holding: bool = True,
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    market_dates = _calendar(db)
    store = DataStore(tmp_path / "market")
    symbols = _freeze_market(store, market_dates)
    run_date = "2026-08-24"

    # Seed ledger with initial cash and optional held position (100 shares of 600001)
    deposit_time = (
        f"{buy_date}T08:30:00+08:00"
        if buy_date != run_date
        else f"{run_date}T08:30:00+08:00"
    )
    buy_time = buy_timestamp or (
        f"{buy_date}T10:00:00+08:00"
        if buy_date != run_date
        else f"{run_date}T09:31:00+08:00"
    )
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp=deposit_time,
        amount=initial_cash,
        asset_class="cash",
        source_ref="deposit-initial",
    )
    if seed_holding:
        db.insert_ledger_entry_sync(
            entry_type="trade_buy",
            timestamp=buy_time,
            amount=1000.0,
            symbol="600001",
            direction="buy",
            quantity=100,
            price=10.0,
            fee_breakdown_json=json.dumps(
                {
                    "commission": 0.0,
                    "stamp_duty": 0.0,
                    "transfer_fee": 0.0,
                    "total_fee": 0.0,
                }
            ),
            asset_class="stock",
            source_ref="seed-position-600001",
        )

    # Seed fresh quotes for held position and universe
    db.upsert_latest_quote_sync(
        symbol="600001",
        asset_type="stock",
        price=10.0,
        quote_timestamp=f"{run_date}T09:34:00+08:00",
        quote_source="persisted_fixture",
        quote_status="live",
    )
    for s in symbols[1:40]:
        db.upsert_latest_quote_sync(
            symbol=s,
            asset_type="stock",
            price=20.0,
            quote_timestamp=f"{run_date}T09:34:00+08:00",
            quote_source="persisted_fixture",
            quote_status="live",
        )

    # Publish initial valuation snapshot at 09:35:55
    initial_val = db.publish_current_valuation_snapshot_sync(
        now=datetime(2026, 8, 24, 9, 35, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert initial_val["status"] == "complete"

    strategy_id = "ai_formula_shadow:fixture"
    db.upsert_strategy_promotion_state_sync(
        strategy_id=strategy_id,
        stage="paper_shadow",
        gate_status="paper_shadow_enabled",
        live_like_enabled=False,
        missing_requirements=[],
        backtest_result_id=1,
        payload={},
    )

    base_dec = _decision(risk_checked=True)
    base_binding = base_dec["candidates"][0]["evidence"]["strategy"][
        "order_generation_gate"
    ]["promotion"]["daily_strategy_artifact_binding"]

    def gate_resolver(_db, requested_strategy_id, *, as_of_date):
        return {
            "status": "pass",
            "promotion": {
                "daily_strategy_artifact_binding": base_binding,
            },
        }, []

    def strategy_loader(*, candidate_id, run_id):
        return {
            "candidate_id": candidate_id,
            "run_id": run_id,
            "strategy_artifact_fingerprint": base_binding["operating_constraints"][
                "strategy_artifact_fingerprint"
            ],
            "strategy": {
                "formula_ast": _formula(produces_signals=True),
                "formula_fingerprint": "3" * 64,
                "selected_universe": symbols[:40],
            },
        }

    controls = TradingControlState(db=db)
    config = SimpleNamespace(data_source="akshare", start_date="2026-04-01")
    decision_time = datetime(2026, 8, 24, 1, 36, tzinfo=timezone.utc)
    clock_dt = datetime(2026, 8, 24, 9, 36, tzinfo=ZoneInfo("Asia/Shanghai"))

    scanner = PromotedStrategyUniverseScanService(
        db=db,
        config=config,
        data_store=store,
        policy=MarketUniversePolicy(minimum_master_member_count=40),
        strategy_gate_resolver=gate_resolver,
        strategy_loader=strategy_loader,
        safety_gate_reader=lambda: {
            "default_execution_mode": "manual_confirmation",
            "manual_confirmation_required": True,
            "broker_submission_enabled": False,
            "kill_switch_enabled": False,
        },
        clock=lambda: clock_dt,
    )

    state = SimpleNamespace(
        db=db,
        config=config,
        data_store=store,
        scanner=scanner,
        trading_controls=controls,
        notifier=RecordingNotifier(),
    )

    return {
        "db": db,
        "store": store,
        "symbols": symbols,
        "run_date": run_date,
        "strategy_id": strategy_id,
        "decision_time": decision_time,
        "clock_dt": clock_dt,
        "scanner": scanner,
        "state": state,
    }


def _seed_reconciled_broker_statement(
    db: AppDatabase,
    *,
    run_date: str,
    cash_balance: float,
    buy_entries: list[tuple[str, str, float, float]] | None = None,
    snapshot_time: str | None = None,
) -> str:
    """Import a broker CSV matching the seeded ledger into BrokerEvidenceRepository."""
    from account_truth.broker_evidence import BrokerEvidenceRepository
    from account_truth.broker_statement import parse_broker_statement_csv

    buys = buy_entries or []
    initial_deposit = cash_balance + sum(qty * px for _, _, qty, px in buys)
    snap_at = snapshot_time or f"{run_date}T09:30:00+08:00"
    rows = [
        "event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method",
        f"dep-1,transfer_in,2026-08-21T08:30:00+08:00,2026-08-21,,,,CNY,0,0,{initial_deposit:.2f},0.00,0.00,{initial_deposit:.2f},{initial_deposit:.2f},,,deposit,0.00,",
    ]
    running_cash = initial_deposit
    totals: dict[str, tuple[float, float]] = {}
    for index, (ts, sym, qty, px) in enumerate(buys, start=1):
        gross = qty * px
        running_cash -= gross
        prev_qty, prev_cost = totals.get(sym, (0.0, 0.0))
        new_qty = prev_qty + qty
        new_avg = (prev_qty * prev_cost + gross) / new_qty if new_qty > 0 else 0.0
        totals[sym] = (new_qty, new_avg)
        buy_day = ts.split("T")[0]
        rows.append(
            f"buy-{index},trade_buy,{ts},{buy_day},{sym},合成股票{sym},stock,CNY,{qty:g},{px:.2f},{gross:.2f},0.00,0.00,-{gross:.2f},{running_cash:.2f},{new_qty:g},{new_avg:.2f},buy,0.00,moving_average_buy_cost"
        )
    rows.append(
        f"cash-snap,cash_snapshot,{snap_at},{run_date},,,,CNY,0,0,0.00,0.00,0.00,0.00,{cash_balance:.2f},,,cash,0.00,"
    )
    if totals:
        for sym, (qty, avg) in totals.items():
            rows.append(
                f"pos-{sym},position_snapshot,{snap_at},{run_date},{sym},合成股票{sym},stock,CNY,0,0,0.00,0.00,0.00,0.00,{cash_balance:.2f},{qty:g},{avg:.2f},pos,0.00,moving_average_buy_cost"
            )
    else:
        rows.append(
            f"pos-empty,position_snapshot,{snap_at},{run_date},600001,合成股票600001,stock,CNY,0,0,0.00,0.00,0.00,0.00,{cash_balance:.2f},0,0.00,pos,0.00,moving_average_buy_cost"
        )
    import_run = BrokerEvidenceRepository(db._path).save_preview(
        parse_broker_statement_csv("\n".join(rows) + "\n"),
        source_name="fixture-broker.csv",
    )
    return import_run.import_run_id


def test_daily_publication_recovers_across_intraday_quote_drift(
    tmp_path, monkeypatch
) -> None:
    """End-to-end real publication path with real Account Truth, replay, quote updates, risk, plan, and report."""
    import server.account_truth_gate as account_truth_gate
    import server.services.decision.decision_portfolio_projection as decision_portfolio_projection
    import server.services.decision.decision_projection as decision_projection
    from server.services.account.valuation import portfolio_equity_from_valuation
    from server.services.decision.daily_decision_report import get_daily_decision_report
    from server.services.decision.decision_application import (
        run_batch_pre_trade_risk_for_state,
    )
    from server.services.decision.operations_projection import (
        current_decision_and_trading_plan,
    )

    env = _setup_quote_drift_environment(
        tmp_path, initial_cash=200_000.0, buy_date="2026-08-21"
    )
    db = env["db"]
    run_date = env["run_date"]
    scanner = env["scanner"]
    state = env["state"]

    fixed_now_sh = datetime(2026, 8, 24, 9, 38, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    fixed_now_utc = datetime(2026, 8, 24, 1, 38, 0, tzinfo=timezone.utc)
    scanner._clock = lambda: fixed_now_sh

    monkeypatch.setattr(
        decision_portfolio_projection,
        "get_shanghai_now",
        lambda: fixed_now_sh,
    )

    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now_utc if tz == timezone.utc else fixed_now_sh

    monkeypatch.setattr(decision_projection, "datetime", MockDateTime)
    monkeypatch.setattr(account_truth_gate, "datetime", MockDateTime)

    import_run_id = _seed_reconciled_broker_statement(
        db,
        run_date=run_date,
        cash_balance=199_000.0,
        buy_entries=[("2026-08-21T10:00:00+08:00", "600001", 100.0, 10.0)],
    )
    val_initial = db.publish_current_valuation_snapshot_sync(now=fixed_now_sh)
    initial_equity = float(portfolio_equity_from_valuation(db, val_initial))
    assert initial_equity == 200_000.0

    base_dec = _decision(risk_checked=True)
    base_gate = base_dec["candidates"][0]["evidence"]["strategy"][
        "order_generation_gate"
    ]

    def pass_order_generation_gate(_db, requested_strategy_id, *, as_of_date):
        g = copy.deepcopy(base_gate)
        g["as_of_date"] = run_date
        g["strategy_id"] = requested_strategy_id
        return g, []

    monkeypatch.setattr(
        "server.services.research.strategy_promotion_pipeline.resolve_strategy_order_generation_gate",
        pass_order_generation_gate,
    )
    monkeypatch.setattr(
        "server.services.decision.decision_application.resolve_strategy_order_generation_gate",
        pass_order_generation_gate,
    )

    injection_state = {
        "quote_update_1_fired": False,
        "quote_update_2_fired": False,
        "equity_after_update_1": None,
        "equity_after_update_2": None,
    }

    # Update 1: Held quote changes during persist_actions=True scan before authority check
    orig_persist = universe_service_module.persist_recommendation_tasks

    def hooked_persist(*, db, decision_date, signals, current_authority_validator):
        if not injection_state["quote_update_1_fired"]:
            injection_state["quote_update_1_fired"] = True
            db.upsert_latest_quote_sync(
                symbol="600001",
                asset_type="stock",
                price=10.5,
                quote_timestamp=f"{run_date}T09:36:40+08:00",
                quote_source="persisted_fixture",
                quote_status="live",
            )
            val2 = db.publish_current_valuation_snapshot_sync(now=fixed_now_sh)
            assert val2["status"] == "complete"
            injection_state["equity_after_update_1"] = float(
                portfolio_equity_from_valuation(db, val2)
            )
            assert injection_state["equity_after_update_1"] == 200_050.0

        return orig_persist(
            db=db,
            decision_date=decision_date,
            signals=signals,
            current_authority_validator=current_authority_validator,
        )

    monkeypatch.setattr(
        universe_service_module, "persist_recommendation_tasks", hooked_persist
    )

    # Update 2: Held quote changes AFTER action persistence and BEFORE production plan reader
    async def hooked_plan_reader(target_state):
        if (
            injection_state["quote_update_1_fired"]
            and not injection_state["quote_update_2_fired"]
            and db.get_action_tasks_sync(statuses=["pending"], limit=20)
        ):
            injection_state["quote_update_2_fired"] = True
            db.upsert_latest_quote_sync(
                symbol="600001",
                asset_type="stock",
                price=10.8,
                quote_timestamp=f"{run_date}T09:37:25+08:00",
                quote_source="persisted_fixture",
                quote_status="live",
            )
            val3 = db.publish_current_valuation_snapshot_sync(now=fixed_now_sh)
            assert val3["status"] == "complete"
            injection_state["equity_after_update_2"] = float(
                portfolio_equity_from_valuation(db, val3)
            )
            assert injection_state["equity_after_update_2"] == 200_080.0
        return await current_decision_and_trading_plan(target_state)

    async def quote_refresher(_state, symbol, asset_type, *, fetch_run_id=None):
        command = build_quote_ingestion_command(
            symbol=symbol,
            asset_type=asset_type.value
            if hasattr(asset_type, "value")
            else str(asset_type),
            snapshot={
                "price": 10.0 if symbol == "600001" else 20.0,
                "timestamp": f"{run_date}T09:36:30+08:00",
                "quote_status": "live",
                "provider_name": "akshare",
                "quote_source": "persisted_fixture",
            },
            quote_source="persisted_fixture",
            provider_name="akshare",
            provider_status="live",
            quote_status="live",
            captured_reason="daily_candidate_freeze",
            fetch_run_id=fetch_run_id,
        )
        persist_quote_ingestion(db, command)
        return {
            "symbol": symbol,
            "status": "refreshed",
            "price": 10.0 if symbol == "600001" else 20.0,
            "quote_timestamp": f"{run_date}T09:36:30+08:00",
        }

    # Use real production build_account_truth_replay_evidence (no _account_truth_replay_resolver override)
    service = build_daily_decision_evidence_automation_service(
        state,
        plan_reader=hooked_plan_reader,
        risk_runner=run_batch_pre_trade_risk_for_state,
        quote_refresher=quote_refresher,
    )

    schedule = project_daily_candidate_background_schedule(db=db, now=fixed_now_utc)
    assert schedule["status"] == "due"
    assert schedule["due"] is True

    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=service,
            schedule=schedule,
            clock=lambda: fixed_now_utc,
        )
    )

    assert injection_state["quote_update_1_fired"] is True
    assert injection_state["quote_update_2_fired"] is True

    # Verify single cohesive run across attempt -> daily evidence -> scan -> risk -> plan -> report
    gen = daily_candidate_generation_status(db, run_date, now=fixed_now_utc)
    assert gen["status"] == "completed_with_candidates"
    assert gen["generation_verified"] is True
    assert gen["recommendation_authoritative"] is True
    assert gen["failure_code"] is None

    risk_decisions = db.get_risk_decisions_sync()
    assert len(risk_decisions) == 5
    assert all(r.get("passed") in (1, True) for r in risk_decisions)
    risk_by_decision_id = {r["decision_id"]: r for r in risk_decisions}

    dec_read, plan_read = asyncio.run(current_decision_and_trading_plan(state))
    assert dec_read["summary"]["account_truth"]["import_run_id"] == import_run_id
    assert dec_read["summary"]["account_truth"]["gate_status"] == "pass"
    assert dec_read["summary"]["portfolio"]["total_equity"] == 200_080.0
    assert len(dec_read["candidates"]) == 5
    assert len(plan_read["order_intents"]) == 5
    for cand in dec_read["candidates"]:
        assert cand.get("action_id") is not None
        assert cand.get("risk_gate_status") == "passed"
        assert cand.get("manual_confirmation_status") == "ready_for_manual_confirmation"
        risk_decision_id = cand["evidence"]["risk_gate"]["decision_id"]
        assert risk_decision_id in risk_by_decision_id

    report = get_daily_decision_report(db, run_date)
    assert report["status"] == "formal_candidate"
    assert report["authoritative_candidate_count"] == 5
    assert report["reason_codes"] == []
    assert len(report["attempts"]) == 1
    assert report["attempts"][0]["run_id"] == gen["attempt_run_id"]
    assert report["attempts"][0]["result_run_id"] == gen["daily_evidence_run_id"]
    assert report["attempts"][0]["scan_run_id"] == gen["scan_run_id"]
    assert len(report["daily_evidence_runs"]) == 1
    assert report["daily_evidence_runs"][0]["run_id"] == gen["daily_evidence_run_id"]
    assert report["daily_evidence_runs"][0]["scan_run_id"] == gen["scan_run_id"]
    assert [c["action_id"] for c in report["candidates"]] == [
        c["action_id"] for c in dec_read["candidates"]
    ]
    assert all(c["report_authoritative"] is True for c in report["candidates"])

    # Real production Account Truth replay binding must be persisted and valid
    evidence_row = json.loads(
        db.get_automation_run_sync(gen["daily_evidence_run_id"])["payload_json"]
    )
    replay_binding = evidence_row["input_snapshot"]["account_truth_replay_evidence"]
    assert replay_binding["status"] == "pass"
    assert replay_binding["account_truth_ref"] == f"account_truth:{import_run_id}"

    # Verify candidates are NOT suppressed by suppress_unverified_daily_scan_candidates
    payload = {
        "lane": "daily",
        "decision": "review_required",
        "decision_date": run_date,
        "summary": {},
        "candidates": dec_read["candidates"],
        "generation": gen,
        "no_action_reasons": [],
    }
    projected = suppress_unverified_daily_scan_candidates(payload)
    assert len(projected["candidates"]) == 5
    assert projected["decision"] == "review_required"


def test_daily_publication_blocks_on_missing_bound_valuation_evidence(
    tmp_path, monkeypatch
) -> None:
    """Negative test (Blocker B): If the bound valuation snapshot disappears, scan input blockers fail closed."""
    env = _setup_quote_drift_environment(
        tmp_path, initial_cash=200_000.0, buy_date="2026-08-21"
    )
    db = env["db"]
    run_date = env["run_date"]
    scanner = env["scanner"]

    val = db.publish_current_valuation_snapshot_sync(
        now=datetime(2026, 8, 24, 9, 36, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    portfolio_summary = {
        "valuation_snapshot_id": val["snapshot_id"],
        "valuation_status": val["status"],
        "total_equity": 200_000.0,
        "cash": 199_000.0,
        "symbols": ["600001"],
        "stock_symbols": ["600001"],
        "instrument_types": {"600001": "stock"},
        "ledger_cutoff_id": val["ledger_cutoff_id"],
        "ledger_fingerprint": val["ledger_fingerprint"],
        "quote_set_fingerprint": val["quote_set_fingerprint"],
        "fact_authority": "persisted_valuation_snapshot",
        "stock_position_market_values": {"600001": 1000.0},
    }
    scan_result = scanner.run_once(
        decision_date=run_date,
        portfolio_summary=portfolio_summary,
        persist_actions=True,
    )
    assert scan_result["status"] == "completed"
    persisted_scan = scan_result

    # Baseline: no blockers
    blockers = scanner.current_input_blockers(
        scan=persisted_scan,
        portfolio_summary=portfolio_summary,
    )
    assert blockers == []

    # Probe: monkeypatch db.get_valuation_snapshot_sync to return None for original snapshot
    orig_get_val = db.get_valuation_snapshot_sync

    def mocked_get_val(snapshot_id):
        if snapshot_id == val["snapshot_id"]:
            return None
        return orig_get_val(snapshot_id)

    monkeypatch.setattr(db, "get_valuation_snapshot_sync", mocked_get_val)

    # Must fail closed with portfolio changed
    drifted_blockers = scanner.current_input_blockers(
        scan=persisted_scan,
        portfolio_summary=portfolio_summary,
    )
    assert "promoted_strategy_scan_current_portfolio_changed" in drifted_blockers


def test_daily_publication_blocks_on_material_price_drift_lot_constraint(
    tmp_path,
) -> None:
    """Negative test (Blocker B): Material live quote spike making 1-lot buys unaffordable blocks scan consumption."""
    env = _setup_quote_drift_environment(
        tmp_path, initial_cash=10_000.0, buy_date="2026-08-21"
    )
    db = env["db"]
    run_date = env["run_date"]
    scanner = env["scanner"]

    # Held 600001 (100 shares @ 10 = 1000), cash = 9000, equity = 10000, available = 8700
    # 4 buys at 20.0 -> min 1-lot cost = 8000 <= 8700
    val = db.publish_current_valuation_snapshot_sync(
        now=datetime(2026, 8, 24, 9, 36, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    portfolio_summary = {
        "valuation_snapshot_id": val["snapshot_id"],
        "valuation_status": val["status"],
        "total_equity": 10_000.0,
        "cash": 9_000.0,
        "symbols": ["600001"],
        "stock_symbols": ["600001"],
        "instrument_types": {"600001": "stock"},
        "ledger_cutoff_id": val["ledger_cutoff_id"],
        "ledger_fingerprint": val["ledger_fingerprint"],
        "quote_set_fingerprint": val["quote_set_fingerprint"],
        "fact_authority": "persisted_valuation_snapshot",
        "stock_position_market_values": {"600001": 1000.0},
    }
    scan_result = scanner.run_once(
        decision_date=run_date,
        portfolio_summary=portfolio_summary,
        persist_actions=True,
    )
    assert scan_result["status"] == "completed"
    assert (
        scanner.current_input_blockers(
            scan=scan_result, portfolio_summary=portfolio_summary
        )
        == []
    )

    # Material live price spike on buy candidate 600050 (20.0 -> 45.0) pushes min 1-lot cost to 10500 > 8700
    db.upsert_latest_quote_sync(
        symbol="600050",
        asset_type="stock",
        price=45.0,
        quote_timestamp=f"{run_date}T09:37:00+08:00",
        quote_source="persisted_fixture",
        quote_status="live",
    )
    val_drifted = db.publish_current_valuation_snapshot_sync(
        now=datetime(2026, 8, 24, 9, 37, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    drifted_summary = {
        **portfolio_summary,
        "valuation_snapshot_id": val_drifted["snapshot_id"],
        "quote_set_fingerprint": val_drifted["quote_set_fingerprint"],
    }
    drifted_blockers = scanner.current_input_blockers(
        scan=scan_result,
        portfolio_summary=drifted_summary,
    )
    assert "promoted_strategy_scan_current_cash_insufficient" in drifted_blockers


def _run_sell_pipeline_control(
    tmp_path,
    monkeypatch,
    *,
    entries: list[tuple[str, str, float, float]],
    cash_balance: float,
):
    """Run the real scan -> risk -> trading plan -> report pipeline with sell signal guaranteed."""
    import server.account_truth_gate as account_truth_gate
    import server.services.decision.decision_portfolio_projection as decision_portfolio_projection
    import server.services.decision.decision_projection as decision_projection
    from server.services.decision.daily_decision_report import get_daily_decision_report
    from server.services.decision.decision_application import (
        run_batch_pre_trade_risk_for_state,
    )
    from server.services.decision.operations_projection import (
        current_decision_and_trading_plan,
    )

    initial_cash = cash_balance + sum(qty * px for _, _, qty, px in entries)
    env = _setup_quote_drift_environment(
        tmp_path, initial_cash=initial_cash, seed_holding=False
    )
    db = env["db"]
    run_date = env["run_date"]
    scanner = env["scanner"]
    state = env["state"]

    for index, (ts, sym, qty, px) in enumerate(entries, start=1):
        db.insert_ledger_entry_sync(
            entry_type="trade_buy",
            timestamp=ts,
            amount=qty * px,
            symbol=sym,
            direction="buy",
            quantity=qty,
            price=px,
            fee_breakdown_json=json.dumps(
                {
                    "commission": 0.0,
                    "stamp_duty": 0.0,
                    "transfer_fee": 0.0,
                    "total_fee": 0.0,
                }
            ),
            asset_class="stock",
            source_ref=f"seed-{sym}-{index}",
        )

    fixed_now_sh = datetime(2026, 8, 24, 9, 36, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    fixed_now_utc = datetime(2026, 8, 24, 1, 36, 0, tzinfo=timezone.utc)
    scanner._clock = lambda: fixed_now_sh
    monkeypatch.setattr(
        decision_portfolio_projection,
        "get_shanghai_now",
        lambda: fixed_now_sh,
    )

    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now_utc if tz == timezone.utc else fixed_now_sh

    monkeypatch.setattr(decision_projection, "datetime", MockDateTime)
    monkeypatch.setattr(account_truth_gate, "datetime", MockDateTime)

    db.publish_current_valuation_snapshot_sync(now=fixed_now_sh)
    _seed_reconciled_broker_statement(
        db,
        run_date=run_date,
        cash_balance=cash_balance,
        buy_entries=entries,
        snapshot_time=f"{run_date}T09:32:00+08:00",
    )

    base_dec = _decision(risk_checked=True)
    base_gate = base_dec["candidates"][0]["evidence"]["strategy"][
        "order_generation_gate"
    ]

    def pass_order_generation_gate(_db, requested_strategy_id, *, as_of_date):
        g = copy.deepcopy(base_gate)
        g["as_of_date"] = run_date
        g["strategy_id"] = requested_strategy_id
        return g, []

    monkeypatch.setattr(
        "server.services.research.strategy_promotion_pipeline.resolve_strategy_order_generation_gate",
        pass_order_generation_gate,
    )
    monkeypatch.setattr(
        "server.services.decision.decision_application.resolve_strategy_order_generation_gate",
        pass_order_generation_gate,
    )

    async def quote_refresher(_state, symbol, asset_type, *, fetch_run_id=None):
        command = build_quote_ingestion_command(
            symbol=symbol,
            asset_type=asset_type.value
            if hasattr(asset_type, "value")
            else str(asset_type),
            snapshot={
                "price": 10.0 if symbol == "600001" else 20.0,
                "timestamp": f"{run_date}T09:35:30+08:00",
                "quote_status": "live",
                "provider_name": "akshare",
                "quote_source": "persisted_fixture",
            },
            quote_source="persisted_fixture",
            provider_name="akshare",
            provider_status="live",
            quote_status="live",
            captured_reason="daily_candidate_freeze",
            fetch_run_id=fetch_run_id,
        )
        persist_quote_ingestion(db, command)
        return {
            "symbol": symbol,
            "status": "refreshed",
            "price": 10.0 if symbol == "600001" else 20.0,
            "quote_timestamp": f"{run_date}T09:35:30+08:00",
        }

    service = build_daily_decision_evidence_automation_service(
        state,
        plan_reader=current_decision_and_trading_plan,
        risk_runner=run_batch_pre_trade_risk_for_state,
        quote_refresher=quote_refresher,
    )
    schedule = project_daily_candidate_background_schedule(db=db, now=fixed_now_utc)
    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=service,
            schedule=schedule,
            clock=lambda: fixed_now_utc,
        )
    )
    dec, plan = asyncio.run(current_decision_and_trading_plan(state))
    ctx = decision_portfolio_projection.decision_portfolio_context(state)
    scans = [
        json.loads(r["payload_json"])
        for r in db.list_automation_runs_sync(
            run_type=PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE,
            run_date=run_date,
            limit=10,
            offset=0,
        )
    ]
    report = get_daily_decision_report(db, run_date)
    return {
        "db": db,
        "env": env,
        "ctx": ctx,
        "scans": scans,
        "dec": dec,
        "plan": plan,
        "report": report,
    }


def test_daily_publication_blocks_t1_violation_for_same_day_buy(
    tmp_path, monkeypatch
) -> None:
    """Verify A-share T+1 sellable quantities across prior-day, same-day, and mixed lots plus T+0 funds."""
    from decimal import Decimal

    from core.types import InstrumentType
    from server.ledger.models import LedgerEntry
    from server.projections.service import build_portfolio_projection

    # Control 1: Prior-day 100 shares -> sellable 100, risk passed, manual confirm ready, report authoritative
    prior = _run_sell_pipeline_control(
        tmp_path / "prior",
        monkeypatch,
        entries=[("2026-08-21T10:00:00+08:00", "600001", 100.0, 10.0)],
        cash_balance=199_000.0,
    )
    prior_sell_signals = [
        s
        for s in prior["scans"][-1]["selected_signals"]
        if s["symbol"] == "600001" and s["direction"] == "sell"
    ]
    assert len(prior_sell_signals) == 1
    prior_pos = prior["ctx"]["portfolio"].positions["600001"]
    assert prior_pos.quantity == Decimal("100")
    assert prior_pos.available_qty == Decimal("100")
    prior_intents = [
        i
        for i in prior["plan"]["order_intents"]
        if i.get("symbol") == "600001" and i.get("side") == "sell"
    ]
    assert len(prior_intents) == 1
    assert prior_intents[0]["estimated_quantity"] == 100.0
    assert prior_intents[0]["risk_gate_status"] == "passed"
    assert (
        prior_intents[0]["manual_confirmation_status"]
        == "ready_for_manual_confirmation"
    )
    prior_t1 = next(
        c
        for c in prior_intents[0]["constraint_checks"]
        if c["id"] == "t1_available_quantity"
    )
    assert prior_t1["status"] == "pass"
    assert prior_t1["available_quantity"] == 100.0
    prior_report_sell = next(
        c
        for c in prior["report"]["candidates"]
        if c["symbol"] == "600001" and c["direction"] == "sell"
    )
    assert prior_report_sell["report_authoritative"] is True

    # Control 2: Same-day 09:31 buy 100 shares -> target sell exists, 09:36 sellable=0, blocked & never authoritative
    same_day = _run_sell_pipeline_control(
        tmp_path / "same_day",
        monkeypatch,
        entries=[("2026-08-24T09:31:00+08:00", "600001", 100.0, 10.0)],
        cash_balance=199_000.0,
    )
    same_sell_signals = [
        s
        for s in same_day["scans"][-1]["selected_signals"]
        if s["symbol"] == "600001" and s["direction"] == "sell"
    ]
    assert len(same_sell_signals) == 1
    same_pos = same_day["ctx"]["portfolio"].positions["600001"]
    assert same_pos.quantity == Decimal("100")
    assert same_pos.frozen_qty == Decimal("100")
    assert same_pos.available_qty == Decimal("0")
    same_cand = next(
        c
        for c in same_day["dec"]["candidates"]
        if c["symbol"] == "600001" and c["action"] == "sell"
    )
    assert same_cand["allocation_quantity"] == 0.0
    assert same_cand["allocation_status"] == "no_position_available_to_sell"
    assert same_cand["allocation_evidence"]["available_quantity"] == 0.0
    assert same_cand["risk_gate_status"] != "passed"
    assert same_cand["manual_confirmation_status"] != "ready_for_manual_confirmation"
    same_sell_intents = [
        i
        for i in same_day["plan"]["order_intents"]
        if i.get("symbol") == "600001" and i.get("side") == "sell"
    ]
    assert same_sell_intents == []
    assert any(
        b.get("symbol") == "600001" and b.get("reason") == "awaiting_risk_gate"
        for b in same_day["plan"]["blockers"]
    )
    same_report_sell = next(
        c
        for c in same_day["report"]["candidates"]
        if c["symbol"] == "600001" and c["direction"] == "sell"
    )
    assert same_report_sell["report_authoritative"] is False
    assert same_day["report"]["status"] != "completed_no_signal"

    # Control 3: Prior-day 100 + today 09:31 100 -> 200 total, max sellable = 100
    mixed_lots = _run_sell_pipeline_control(
        tmp_path / "mixed_lots",
        monkeypatch,
        entries=[
            ("2026-08-21T10:00:00+08:00", "600001", 100.0, 10.0),
            ("2026-08-24T09:31:00+08:00", "600001", 100.0, 10.0),
        ],
        cash_balance=198_000.0,
    )
    mixed_pos = mixed_lots["ctx"]["portfolio"].positions["600001"]
    assert mixed_pos.quantity == Decimal("200")
    assert mixed_pos.frozen_qty == Decimal("100")
    assert mixed_pos.available_qty == Decimal("100")
    mixed_intents = [
        i
        for i in mixed_lots["plan"]["order_intents"]
        if i.get("symbol") == "600001" and i.get("side") == "sell"
    ]
    assert len(mixed_intents) == 1
    assert mixed_intents[0]["estimated_quantity"] == 100.0
    assert mixed_intents[0]["risk_gate_status"] == "passed"
    assert (
        mixed_intents[0]["manual_confirmation_status"]
        == "ready_for_manual_confirmation"
    )
    mixed_t1 = next(
        c
        for c in mixed_intents[0]["constraint_checks"]
        if c["id"] == "t1_available_quantity"
    )
    assert mixed_t1["status"] == "pass"
    assert mixed_t1["available_quantity"] == 100.0

    # Preserve T+0 open-end fund sellability on same-day subscription/buy
    fund_proj = build_portfolio_projection(
        [
            LedgerEntry(
                id=1,
                timestamp="2026-08-24T09:31:00+08:00",
                entry_type="trade_buy",
                amount=Decimal("1000"),
                symbol="018125",
                direction="buy",
                quantity=Decimal("1000"),
                price=Decimal("1"),
                asset_class="open_end_fund",
            )
        ],
        settlement_date=date(2026, 8, 24),
        instrument_types={"018125": InstrumentType.OPEN_END_FUND},
    )
    assert fund_proj.positions["018125"].frozen_qty == Decimal("0")
    assert fund_proj.positions["018125"].available_qty == Decimal("1000")


def test_daily_publication_enforces_fee_inclusive_buying_power_on_quote_drift(
    tmp_path, monkeypatch
) -> None:
    """Verify fee-inclusive buying power checks at both pre-persist and post-persist quote hikes."""
    from decimal import Decimal

    import server.services.decision.decision_portfolio_projection as decision_portfolio_projection

    def _run_case(name: str, *, initial_cash: float, hike_when: str) -> dict[str, Any]:
        env = _setup_quote_drift_environment(
            tmp_path / name, initial_cash=initial_cash, buy_date="2026-08-21"
        )
        db = env["db"]
        run_date = env["run_date"]
        scanner = env["scanner"]
        fixed_sh = datetime(2026, 8, 24, 9, 36, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        scanner._clock = lambda: fixed_sh
        monkeypatch.setattr(
            decision_portfolio_projection, "get_shanghai_now", lambda: fixed_sh
        )
        db.publish_current_valuation_snapshot_sync(now=fixed_sh)
        summary = decision_portfolio_projection.portfolio_state_summary(env["state"])

        def _hike_quotes(ts: str) -> None:
            # 4 * 100 shares at [21.74, 21.74, 21.75, 21.75] = 8,698 gross, 8,718.08698 with fees
            for sym, px in (
                ("600050", 21.74),
                ("600049", 21.74),
                ("600048", 21.75),
                ("600047", 21.75),
            ):
                db.upsert_latest_quote_sync(
                    symbol=sym,
                    asset_type="stock",
                    price=px,
                    quote_timestamp=ts,
                    quote_source="persisted_fixture",
                    quote_status="live",
                )

        if hike_when == "before_persist":
            orig_persist = universe_service_module.persist_recommendation_tasks

            def hooked_persist(
                *, db, decision_date, signals, current_authority_validator
            ):
                _hike_quotes(f"{run_date}T09:36:10+08:00")
                return orig_persist(
                    db=db,
                    decision_date=decision_date,
                    signals=signals,
                    current_authority_validator=current_authority_validator,
                )

            monkeypatch.setattr(
                universe_service_module, "persist_recommendation_tasks", hooked_persist
            )
        scan = scanner.run_once(
            decision_date=run_date, portfolio_summary=summary, persist_actions=True
        )
        blockers_after = []
        if hike_when == "after_persist":
            _hike_quotes(f"{run_date}T09:36:30+08:00")
            db.publish_current_valuation_snapshot_sync(now=fixed_sh)
            drifted_summary = decision_portfolio_projection.portfolio_state_summary(
                env["state"]
            )
            blockers_after = scanner.current_input_blockers(
                scan=scan, portfolio_summary=drifted_summary
            )
        return {
            "db": db,
            "scan": scan,
            "blockers_after": blockers_after,
            "scanner": scanner,
            "summary": summary,
        }

    # 8,700 available (cash=9,000, equity=10,000, reserve=300; sell 600001 not netted):
    # gross=8,698 <= 8,700, but fee-inclusive=8,718.08698 > 8,700
    pre_blocked = _run_case(
        "pre_hike", initial_cash=10_000.0, hike_when="before_persist"
    )
    assert pre_blocked["scan"]["status"] == "blocked"
    assert any(
        "current_portfolio_cash_insufficient" in b
        for b in pre_blocked["scan"]["blockers"]
    )
    assert pre_blocked["db"].get_action_tasks_sync(statuses=["pending"], limit=20) == []

    post_blocked = _run_case(
        "post_hike", initial_cash=10_000.0, hike_when="after_persist"
    )
    assert post_blocked["scan"]["status"] == "completed"
    assert (
        "promoted_strategy_scan_current_cash_insufficient"
        in post_blocked["blockers_after"]
    )

    # Sufficient-budget control (cash=9,020, equity=10,020, reserve=300.6 -> available=8,719.40 >= 8,718.08698)
    sufficient = _run_case(
        "sufficient", initial_cash=10_020.0, hike_when="after_persist"
    )
    assert sufficient["scan"]["status"] == "completed"
    assert sufficient["blockers_after"] == []
    assert (
        sufficient["scanner"].current_input_blockers(
            scan=sufficient["scan"], portfolio_summary=sufficient["summary"]
        )
        == []
    )

    # Re-allocation control when T-1 closes / allocation already require configured fees
    from server.services.portfolio.allocation import allocate_action_tasks
    from server.services.strategy_scan.universe.evaluation import (
        _legacy_account_signals,
    )

    raw_buys = [
        {
            "strategy_id": sufficient["scan"]["strategy_bindings"][0]["strategy_id"],
            "symbol": sym,
            "direction": "buy",
            "target_weight": 0.25,
            "frozen_close": px,
            "ranking_liquidity": 10_000_000.0 - idx,
            "asset_class": "stock",
        }
        for idx, (sym, px) in enumerate(
            [("600050", 21.74), ("600049", 21.74), ("600048", 21.75), ("600047", 21.75)]
        )
    ]
    admitted, blocked_buys = _legacy_account_signals(
        raw_buys,
        config=SimpleNamespace(data_source="akshare", start_date="2026-04-01"),
        decision_date="2026-08-24",
        portfolio={
            "cash": 9_000.0,
            "total_equity": 10_000.0,
            "fact_authority": "persisted_valuation_snapshot",
            "board_buy_permissions": {"main": "allowed"},
        },
        policy=MarketUniversePolicy(
            minimum_master_member_count=40,
            fee_buffer_rate=Decimal("0"),
        ),
        cash_buffer_ratio=Decimal("0.03"),
    )
    assert [row["symbol"] for row in admitted] == ["600050", "600049", "600048"]
    assert blocked_buys == [
        {
            "strategy_id": sufficient["scan"]["strategy_bindings"][0]["strategy_id"],
            "symbol": "600047",
            "board": "sse_main",
            "reason": "insufficient_cash_for_one_lot",
        }
    ]
    allocated_actions = allocate_action_tasks(
        [
            {"id": idx + 1, **row, "price": row["frozen_close"]}
            for idx, row in enumerate(raw_buys)
        ],
        portfolio=SimpleNamespace(cash=9_000.0, total_equity=10_000.0, positions={}),
        quotes={row["symbol"]: {"price": row["frozen_close"]} for row in raw_buys},
        config=SimpleNamespace(
            min_cash_buffer_ratio=0.03, max_single_symbol_weight=0.35
        ),
    )
    assert [item["allocation_quantity"] for item in allocated_actions] == [
        100.0,
        100.0,
        100.0,
        0.0,
    ]


def test_mixed_stock_and_fund_scan_revalidates_cleanly_when_fund_nav_missing(
    tmp_path, monkeypatch
) -> None:
    """Verify initial scan and frozen replay agree on stock-only scope even when fund 018125 lacks NAV."""
    import server.services.decision.decision_portfolio_projection as decision_portfolio_projection
    from server.services.strategy_scan.universe.validation import (
        _build_frozen_replay_portfolio,
    )

    env = _setup_quote_drift_environment(
        tmp_path, initial_cash=200_000.0, buy_date="2026-08-21"
    )
    db = env["db"]
    run_date = env["run_date"]
    scanner = env["scanner"]
    fixed_sh = datetime(2026, 8, 24, 9, 36, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    scanner._clock = lambda: fixed_sh
    monkeypatch.setattr(
        decision_portfolio_projection, "get_shanghai_now", lambda: fixed_sh
    )
    monkeypatch.setattr(
        "server.projections.valuation_snapshot.get_shanghai_now",
        lambda now=None: now or fixed_sh,
    )

    # Second stock + 3 open-end funds where 018125 lacks NAV
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-08-21T10:00:00+08:00",
        amount=2000.0,
        symbol="600002",
        direction="buy",
        quantity=100.0,
        price=20.0,
        fee_breakdown_json=json.dumps({"commission": 0.0, "total_fee": 0.0}),
        asset_class="stock",
        source_ref="seed-600002",
    )
    for sym in ("018125", "018126", "018127"):
        db.insert_ledger_entry_sync(
            entry_type="trade_buy",
            timestamp="2026-08-21T10:00:00+08:00",
            amount=1000.0,
            symbol=sym,
            direction="buy",
            quantity=1000.0,
            price=1.0,
            fee_breakdown_json=json.dumps({"commission": 0.0, "total_fee": 0.0}),
            asset_class="open_end_fund",
            source_ref=f"seed-{sym}",
        )
    db.upsert_latest_quote_sync(
        symbol="018126",
        asset_type="open_end_fund",
        price=1.02,
        quote_timestamp="2026-08-21T15:00:00+08:00",
        quote_source="persisted_fixture",
        quote_status="confirmed",
    )
    db.upsert_latest_quote_sync(
        symbol="018127",
        asset_type="open_end_fund",
        price=1.03,
        quote_timestamp="2026-08-21T15:00:00+08:00",
        quote_source="persisted_fixture",
        quote_status="confirmed",
    )
    val = db.publish_current_valuation_snapshot_sync(now=fixed_sh)
    assert val["status"] == "missing"

    summary = decision_portfolio_projection.portfolio_state_summary(env["state"])
    assert summary["total_equity"] is None
    assert summary["stock_equity"] == 197_000.0

    scan = scanner.run_once(
        decision_date=run_date, portfolio_summary=summary, persist_actions=True
    )
    assert scan["status"] == "completed"
    assert scan["blockers"] == []
    assert scanner.current_input_blockers(scan=scan, portfolio_summary=summary) == []

    replay_blockers: list[str] = []
    frozen_portfolio, eval_equity = _build_frozen_replay_portfolio(
        db=db,
        config=env["state"].config,
        portfolio=summary,
        bound_binding=scan["portfolio_binding"],
        bound_snap=val,
        bound_val_id=val["snapshot_id"],
        blockers=replay_blockers,
    )
    assert replay_blockers == []
    assert frozen_portfolio["stock_symbols"] == ["600001", "600002"]
    assert eval_equity == 197_000.0

    # Missing stock quote itself must still fail closed
    db.upsert_latest_quote_sync(
        symbol="600002",
        asset_type="stock",
        price=20.0,
        quote_timestamp=f"{run_date}T09:35:00+08:00",
        quote_source="persisted_fixture",
        quote_status="missing",
    )
    val_stock_missing = db.publish_current_valuation_snapshot_sync(now=fixed_sh)
    bad_summary = decision_portfolio_projection.portfolio_state_summary(env["state"])
    assert "promoted_strategy_scan_current_portfolio_changed" in (
        scanner.current_input_blockers(scan=scan, portfolio_summary=bad_summary)
    )
    assert val_stock_missing["status"] != "complete"

    # Missing frozen snapshot must still fail closed
    orig_get_val = db.get_valuation_snapshot_sync
    monkeypatch.setattr(db, "get_valuation_snapshot_sync", lambda _sid: None)
    assert "promoted_strategy_scan_current_portfolio_changed" in (
        scanner.current_input_blockers(scan=scan, portfolio_summary=summary)
    )
    monkeypatch.setattr(db, "get_valuation_snapshot_sync", orig_get_val)


def test_daily_publication_blocks_on_real_ledger_mutation(
    tmp_path, monkeypatch
) -> None:
    """Negative test: A real ledger mutation before authority validation blocks scan and suppresses candidates."""
    env = _setup_quote_drift_environment(tmp_path)
    db = env["db"]
    run_date = env["run_date"]
    decision_time = env["decision_time"]
    state = env["state"]
    strategy_id = env["strategy_id"]

    orig_persist = universe_service_module.persist_recommendation_tasks

    def hooked_persist(*, db, decision_date, signals, current_authority_validator):
        def wrapped_validator():
            # Mutate the ledger with an unexpected cash fee during scan
            db.insert_ledger_entry_sync(
                entry_type="fee",
                timestamp=f"{run_date}T09:36:20+08:00",
                amount=50.0,
                asset_class="cash",
                source_ref="ledger-mutation-drift",
            )
            db.publish_current_valuation_snapshot_sync(
                now=datetime(2026, 8, 24, 9, 36, 28, tzinfo=ZoneInfo("Asia/Shanghai"))
            )
            return current_authority_validator()

        return orig_persist(
            db=db,
            decision_date=decision_date,
            signals=signals,
            current_authority_validator=wrapped_validator,
        )

    monkeypatch.setattr(
        universe_service_module, "persist_recommendation_tasks", hooked_persist
    )

    async def quote_refresher(_state, symbol, asset_type, *, fetch_run_id=None):
        return {"symbol": symbol, "status": "refreshed", "price": 20.0}

    async def read_base_plan(_state):
        val = build_current_valuation_snapshot(
            db,
            persist=False,
            now=datetime(2026, 8, 24, 9, 36, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        dec = _decision(risk_checked=False)
        dec["decision_date"] = run_date
        dec["generated_at"] = f"{run_date}T09:35:00+08:00"
        dec["summary"]["portfolio"]["valuation_snapshot_id"] = val["snapshot_id"]
        dec["summary"]["portfolio"]["valuation_status"] = val["status"]
        dec["summary"]["portfolio"]["fact_authority"] = "persisted_valuation_snapshot"
        dec["summary"]["portfolio"]["total_equity"] = 100_000.0
        dec["summary"]["portfolio"]["cash"] = 99_000.0
        dec["summary"]["portfolio"]["ledger_fingerprint"] = val["ledger_fingerprint"]
        dec["summary"]["portfolio"]["ledger_cutoff_id"] = val["ledger_cutoff_id"]
        dec["summary"]["portfolio"]["quote_set_fingerprint"] = val[
            "quote_set_fingerprint"
        ]
        dec["summary"]["portfolio"]["symbols"] = ["600001"]
        dec["summary"]["portfolio"]["stock_symbols"] = ["600001"]
        dec["summary"]["portfolio"]["instrument_types"] = {"600001": "stock"}
        dec["summary"]["account_truth"]["captured_at"] = f"{run_date}T09:30:00+08:00"
        dec["summary"]["market_data"]["latest_quote_timestamp"] = (
            f"{run_date}T09:34:00+08:00"
        )
        cand = dec["candidates"][0]
        cand["action_id"] = 1
        cand["symbol"] = "600001"
        cand["direction"] = "sell"
        cand["side"] = "sell"
        cand["asset_class"] = "stock"
        cand["evidence"]["strategy"]["order_generation_gate"]["as_of_date"] = run_date
        dec["candidates"] = [cand]
        p = _plan(risk_checked=False)
        p["plan_date"] = run_date
        return dec, p

    async def run_risk(_state):
        return {"status": "skipped", "candidate_count": 0, "blockers": []}

    service = build_daily_decision_evidence_automation_service(
        state,
        plan_reader=read_base_plan,
        risk_runner=run_risk,
        quote_refresher=quote_refresher,
    )
    service._account_truth_replay_resolver = _fixture_account_truth_replay

    schedule = project_daily_candidate_background_schedule(db=db, now=decision_time)
    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=service,
            schedule=schedule,
            clock=lambda: decision_time,
        )
    )

    gen = daily_candidate_generation_status(db, run_date, now=decision_time)
    assert gen["generation_verified"] is False
    assert gen["status"] in {"blocked", "no_candidates"}

    candidate = {
        "candidate_id": f"cand-sell-{run_date}",
        "action_id": 1,
        "symbol": "600001",
        "direction": "sell",
        "side": "sell",
        "evidence": {
            "strategy": {"strategy_id": strategy_id},
            "signal": {
                "id": 1,
                "strategy_id": strategy_id,
                "timestamp": f"{run_date}T09:35:00+08:00",
            },
        },
    }
    payload = {
        "lane": "daily",
        "decision": "review_required",
        "decision_date": run_date,
        "summary": {},
        "candidates": [candidate],
        "generation": gen,
        "no_action_reasons": [],
    }
    projected = suppress_unverified_daily_scan_candidates(payload)
    assert projected["candidates"] == []
    assert projected["decision"] == "no_action"


def test_daily_publication_blocks_on_revoked_strategy(tmp_path, monkeypatch) -> None:
    """Negative test: Revoking strategy promotion fails closed and blocks decision evidence."""
    env = _setup_quote_drift_environment(tmp_path)
    db = env["db"]
    run_date = env["run_date"]
    decision_time = env["decision_time"]
    state = env["state"]
    strategy_id = env["strategy_id"]

    orig_persist = universe_service_module.persist_recommendation_tasks

    def hooked_persist(*, db, decision_date, signals, current_authority_validator):
        def wrapped_validator():
            # Revoke strategy promotion right before authority check
            db.upsert_strategy_promotion_state_sync(
                strategy_id=strategy_id,
                stage="retired",
                gate_status="paper_shadow_disabled",
                live_like_enabled=False,
                missing_requirements=["promoted_strategy_retired"],
                backtest_result_id=1,
                payload={},
            )
            return current_authority_validator()

        return orig_persist(
            db=db,
            decision_date=decision_date,
            signals=signals,
            current_authority_validator=wrapped_validator,
        )

    monkeypatch.setattr(
        universe_service_module, "persist_recommendation_tasks", hooked_persist
    )

    async def quote_refresher(_state, symbol, asset_type, *, fetch_run_id=None):
        return {"symbol": symbol, "status": "refreshed", "price": 20.0}

    async def read_base_plan(_state):
        val = build_current_valuation_snapshot(
            db,
            persist=False,
            now=datetime(2026, 8, 24, 9, 36, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        dec = _decision(risk_checked=False)
        dec["decision_date"] = run_date
        dec["generated_at"] = f"{run_date}T09:35:00+08:00"
        dec["summary"]["portfolio"]["valuation_snapshot_id"] = val["snapshot_id"]
        dec["summary"]["portfolio"]["valuation_status"] = val["status"]
        dec["summary"]["portfolio"]["fact_authority"] = "persisted_valuation_snapshot"
        dec["summary"]["portfolio"]["total_equity"] = 100_000.0
        dec["summary"]["portfolio"]["cash"] = 99_000.0
        dec["summary"]["portfolio"]["ledger_fingerprint"] = val["ledger_fingerprint"]
        dec["summary"]["portfolio"]["ledger_cutoff_id"] = val["ledger_cutoff_id"]
        dec["summary"]["portfolio"]["quote_set_fingerprint"] = val[
            "quote_set_fingerprint"
        ]
        dec["summary"]["portfolio"]["symbols"] = ["600001"]
        dec["summary"]["portfolio"]["stock_symbols"] = ["600001"]
        dec["summary"]["portfolio"]["instrument_types"] = {"600001": "stock"}
        dec["summary"]["account_truth"]["captured_at"] = f"{run_date}T09:30:00+08:00"
        dec["summary"]["market_data"]["latest_quote_timestamp"] = (
            f"{run_date}T09:34:00+08:00"
        )
        cand = dec["candidates"][0]
        cand["action_id"] = 1
        cand["symbol"] = "600001"
        cand["direction"] = "sell"
        cand["side"] = "sell"
        cand["asset_class"] = "stock"
        cand["evidence"]["strategy"]["order_generation_gate"]["as_of_date"] = run_date
        dec["candidates"] = [cand]
        p = _plan(risk_checked=False)
        p["plan_date"] = run_date
        return dec, p

    async def run_risk(_state):
        return {"status": "skipped", "candidate_count": 0, "blockers": []}

    service = build_daily_decision_evidence_automation_service(
        state,
        plan_reader=read_base_plan,
        risk_runner=run_risk,
        quote_refresher=quote_refresher,
    )
    service._account_truth_replay_resolver = _fixture_account_truth_replay

    schedule = project_daily_candidate_background_schedule(db=db, now=decision_time)
    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=service,
            schedule=schedule,
            clock=lambda: decision_time,
        )
    )

    gen = daily_candidate_generation_status(db, run_date, now=decision_time)
    assert gen["generation_verified"] is False

    candidate = {
        "candidate_id": f"cand-sell-{run_date}",
        "action_id": 1,
        "symbol": "600001",
        "direction": "sell",
        "side": "sell",
        "evidence": {
            "strategy": {"strategy_id": strategy_id},
            "signal": {
                "id": 1,
                "strategy_id": strategy_id,
                "timestamp": f"{run_date}T09:35:00+08:00",
            },
        },
    }
    payload = {
        "lane": "daily",
        "decision": "review_required",
        "decision_date": run_date,
        "summary": {},
        "candidates": [candidate],
        "generation": gen,
        "no_action_reasons": [],
    }
    projected = suppress_unverified_daily_scan_candidates(payload)
    assert projected["candidates"] == []
    assert projected["decision"] == "no_action"


def test_daily_publication_blocks_on_unhealthy_valuation(tmp_path, monkeypatch) -> None:
    """Negative test: Stale or degraded valuation fails closed and suppresses candidates."""
    env = _setup_quote_drift_environment(tmp_path)
    db = env["db"]
    run_date = env["run_date"]
    decision_time = env["decision_time"]
    state = env["state"]
    strategy_id = env["strategy_id"]

    orig_persist = universe_service_module.persist_recommendation_tasks

    def hooked_persist(*, db, decision_date, signals, current_authority_validator):
        def wrapped_validator():
            # Mark quote for 600001 as missing, making valuation degraded
            db.upsert_latest_quote_sync(
                symbol="600001",
                asset_type="stock",
                price=10.0,
                quote_timestamp=f"{run_date}T09:34:00+08:00",
                quote_source="persisted_fixture",
                quote_status="missing",
            )
            val = db.publish_current_valuation_snapshot_sync(
                now=datetime(2026, 8, 24, 9, 36, 28, tzinfo=ZoneInfo("Asia/Shanghai"))
            )
            assert val["status"] == "degraded"
            return current_authority_validator()

        return orig_persist(
            db=db,
            decision_date=decision_date,
            signals=signals,
            current_authority_validator=wrapped_validator,
        )

    monkeypatch.setattr(
        universe_service_module, "persist_recommendation_tasks", hooked_persist
    )

    async def quote_refresher(_state, symbol, asset_type, *, fetch_run_id=None):
        return {"symbol": symbol, "status": "refreshed", "price": 20.0}

    async def read_base_plan(_state):
        val = build_current_valuation_snapshot(
            db,
            persist=False,
            now=datetime(2026, 8, 24, 9, 36, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        dec = _decision(risk_checked=False)
        dec["decision_date"] = run_date
        dec["generated_at"] = f"{run_date}T09:35:00+08:00"
        dec["summary"]["portfolio"]["valuation_snapshot_id"] = val["snapshot_id"]
        dec["summary"]["portfolio"]["valuation_status"] = val["status"]
        dec["summary"]["portfolio"]["fact_authority"] = "persisted_valuation_snapshot"
        dec["summary"]["portfolio"]["total_equity"] = 100_000.0
        dec["summary"]["portfolio"]["cash"] = 99_000.0
        dec["summary"]["portfolio"]["ledger_fingerprint"] = val["ledger_fingerprint"]
        dec["summary"]["portfolio"]["ledger_cutoff_id"] = val["ledger_cutoff_id"]
        dec["summary"]["portfolio"]["quote_set_fingerprint"] = val[
            "quote_set_fingerprint"
        ]
        dec["summary"]["portfolio"]["symbols"] = ["600001"]
        dec["summary"]["portfolio"]["stock_symbols"] = ["600001"]
        dec["summary"]["portfolio"]["instrument_types"] = {"600001": "stock"}
        dec["summary"]["account_truth"]["captured_at"] = f"{run_date}T09:30:00+08:00"
        dec["summary"]["market_data"]["latest_quote_timestamp"] = (
            f"{run_date}T09:34:00+08:00"
        )
        cand = dec["candidates"][0]
        cand["action_id"] = 1
        cand["symbol"] = "600001"
        cand["direction"] = "sell"
        cand["side"] = "sell"
        cand["asset_class"] = "stock"
        cand["evidence"]["strategy"]["order_generation_gate"]["as_of_date"] = run_date
        dec["candidates"] = [cand]
        p = _plan(risk_checked=False)
        p["plan_date"] = run_date
        return dec, p

    async def run_risk(_state):
        return {"status": "skipped", "candidate_count": 0, "blockers": []}

    service = build_daily_decision_evidence_automation_service(
        state,
        plan_reader=read_base_plan,
        risk_runner=run_risk,
        quote_refresher=quote_refresher,
    )
    service._account_truth_replay_resolver = _fixture_account_truth_replay

    schedule = project_daily_candidate_background_schedule(db=db, now=decision_time)
    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=service,
            schedule=schedule,
            clock=lambda: decision_time,
        )
    )

    gen = daily_candidate_generation_status(db, run_date, now=decision_time)
    assert gen["generation_verified"] is False

    candidate = {
        "candidate_id": f"cand-sell-{run_date}",
        "action_id": 1,
        "symbol": "600001",
        "direction": "sell",
        "side": "sell",
        "evidence": {
            "strategy": {"strategy_id": strategy_id},
            "signal": {
                "id": 1,
                "strategy_id": strategy_id,
                "timestamp": f"{run_date}T09:35:00+08:00",
            },
        },
    }
    payload = {
        "lane": "daily",
        "decision": "review_required",
        "decision_date": run_date,
        "summary": {},
        "candidates": [candidate],
        "generation": gen,
        "no_action_reasons": [],
    }
    projected = suppress_unverified_daily_scan_candidates(payload)
    assert projected["candidates"] == []
    assert projected["decision"] == "no_action"


def test_daily_publication_duplicate_attempt_is_idempotent(tmp_path) -> None:
    """Duplicate attempts for an already completed daily decision run are idempotent."""
    env = _setup_quote_drift_environment(tmp_path)
    db = env["db"]
    run_date = env["run_date"]
    decision_time = env["decision_time"]
    state = env["state"]
    strategy_id = env["strategy_id"]

    run_count = {"calls": 0}

    async def quote_refresher(_state, symbol, asset_type, *, fetch_run_id=None):
        command = build_quote_ingestion_command(
            symbol=symbol,
            asset_type=asset_type.value
            if hasattr(asset_type, "value")
            else str(asset_type),
            snapshot={
                "price": 10.0 if symbol == "600001" else 20.0,
                "timestamp": f"{run_date}T09:36:30+08:00",
                "quote_status": "live",
                "provider_name": "akshare",
                "quote_source": "persisted_fixture",
            },
            quote_source="persisted_fixture",
            provider_name="akshare",
            provider_status="live",
            quote_status="live",
            captured_reason="daily_candidate_freeze",
            fetch_run_id=fetch_run_id,
        )
        persist_quote_ingestion(db, command)
        return {
            "symbol": symbol,
            "status": "refreshed",
            "price": 10.0 if symbol == "600001" else 20.0,
            "quote_timestamp": f"{run_date}T09:36:30+08:00",
        }

    async def read_base_plan(_state):
        val = build_current_valuation_snapshot(
            db,
            persist=False,
            now=datetime(2026, 8, 24, 9, 36, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        dec = _decision(risk_checked=True)
        dec["decision_date"] = run_date
        dec["generated_at"] = f"{run_date}T09:35:00+08:00"
        dec["summary"]["portfolio"]["valuation_snapshot_id"] = val["snapshot_id"]
        dec["summary"]["portfolio"]["valuation_status"] = val["status"]
        dec["summary"]["portfolio"]["fact_authority"] = "persisted_valuation_snapshot"
        dec["summary"]["portfolio"]["total_equity"] = 100_000.0
        dec["summary"]["portfolio"]["cash"] = 99_000.0
        dec["summary"]["portfolio"]["ledger_fingerprint"] = val["ledger_fingerprint"]
        dec["summary"]["portfolio"]["ledger_cutoff_id"] = val["ledger_cutoff_id"]
        dec["summary"]["portfolio"]["quote_set_fingerprint"] = val[
            "quote_set_fingerprint"
        ]
        dec["summary"]["portfolio"]["symbols"] = ["600001"]
        dec["summary"]["portfolio"]["stock_symbols"] = ["600001"]
        dec["summary"]["portfolio"]["instrument_types"] = {"600001": "stock"}
        dec["summary"]["account_truth"]["captured_at"] = f"{run_date}T09:30:00+08:00"
        dec["summary"]["market_data"]["latest_quote_timestamp"] = (
            f"{run_date}T09:34:00+08:00"
        )
        cand = dec["candidates"][0]
        cand["action_id"] = 1
        cand["symbol"] = "600001"
        cand["direction"] = "sell"
        cand["side"] = "sell"
        cand["asset_class"] = "stock"
        cand["evidence"]["strategy"]["order_generation_gate"]["as_of_date"] = run_date
        dec["candidates"] = [cand]

        p = _plan(risk_checked=True)
        p["plan_date"] = run_date
        p["generated_at"] = f"{run_date}T09:35:00+08:00"
        if p["order_intents"]:
            oi = p["order_intents"][0]
            oi["action_id"] = 1
            oi["symbol"] = "600001"
            oi["side"] = "sell"
            oi["direction"] = "sell"
            oi["asset_class"] = "stock"
            oi["market_quote_timestamp"] = f"{run_date}T09:34:00+08:00"
            p["order_intents"] = [oi]
        return dec, p

    async def run_risk(_state):
        run_count["calls"] += 1
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

    service = build_daily_decision_evidence_automation_service(
        state,
        plan_reader=read_base_plan,
        risk_runner=run_risk,
        quote_refresher=quote_refresher,
    )
    service._account_truth_replay_resolver = _fixture_account_truth_replay

    schedule = project_daily_candidate_background_schedule(db=db, now=decision_time)
    assert schedule["status"] == "due"

    # First attempt
    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=service,
            schedule=schedule,
            clock=lambda: decision_time,
        )
    )

    gen1 = daily_candidate_generation_status(db, run_date, now=decision_time)
    assert gen1["status"] == "completed_with_candidates"
    first_calls = run_count["calls"]
    assert first_calls > 0

    # Project schedule again: should not be due
    schedule2 = project_daily_candidate_background_schedule(db=db, now=decision_time)
    assert schedule2["status"] in {"completed", "already_attempted"}
    assert schedule2["due"] is False

    # Second attempt execution: returns immediately without re-running
    asyncio.run(
        run_claimed_background_attempt(
            db=db,
            service=service,
            schedule=schedule2,
            clock=lambda: decision_time,
        )
    )
    assert run_count["calls"] == first_calls
