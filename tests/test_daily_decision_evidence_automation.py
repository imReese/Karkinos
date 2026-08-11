from __future__ import annotations

import asyncio

from server.db import AppDatabase
from server.services.daily_decision_evidence_automation import (
    DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
    DailyDecisionEvidenceAutomationService,
)
from server.services.trading_controls import TradingControlState


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def send(self, *, title: str, message: str) -> None:
        self.messages.append((title, message))


def _decision(*, risk_checked: bool) -> dict:
    return {
        "decision_date": "2026-07-02",
        "decision": "review_required",
        "summary": {
            "candidate_count": 1,
            "portfolio": {
                "valuation_snapshot_id": "valuation-001",
                "ledger_cutoff_id": 7,
            },
        },
        "candidates": [
            {
                "action_id": 1,
                "symbol": "600519",
                "action": "buy",
                "risk_gate_status": "passed" if risk_checked else "not_checked",
                "manual_confirmation_status": (
                    "ready_for_manual_confirmation"
                    if risk_checked
                    else "awaiting_risk_gate"
                ),
            }
        ],
    }


def _plan(*, risk_checked: bool) -> dict:
    order_intents = []
    blockers = [
        {
            "action_id": 1,
            "symbol": "600519",
            "reason": "awaiting_risk_gate",
        }
    ]
    if risk_checked:
        blockers = []
        order_intents = [
            {
                "intent_id": "ACTION-1-BATCH-RISK",
                "strategy_id": "dual_ma",
                "symbol": "600519",
                "side": "buy",
                "asset_class": "stock",
                "estimated_quantity": 100,
                "estimated_price": 10.0,
                "risk_decision_id": "RISK-001",
                "risk_gate_status": "passed",
                "manual_confirmation_status": "ready_for_manual_confirmation",
                "evidence_refs": ["action:1", "risk:RISK-001"],
            }
        ]
    return {
        "schema_version": "karkinos.daily_trading_plan.v1",
        "plan_date": "2026-07-02",
        "generated_at": "2026-07-02T09:35:00+08:00",
        "conclusion_status": (
            "manual_confirmation_ready" if risk_checked else "no_manual_action"
        ),
        "candidate_pool_count": 1,
        "manual_ready_count": 1 if risk_checked else 0,
        "blocked_count": 0 if risk_checked else 1,
        "order_intents": order_intents,
        "blockers": blockers,
    }


def test_automatic_evidence_chain_runs_risk_then_idempotent_paper_shadow(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    controls = TradingControlState(db=db)
    notifier = RecordingNotifier()
    state = {"risk_checked": False, "risk_calls": 0}

    async def read_plan():
        checked = bool(state["risk_checked"])
        return _decision(risk_checked=checked), _plan(risk_checked=checked)

    async def run_risk():
        state["risk_calls"] += 1
        state["risk_checked"] = True
        already_checked = state["risk_calls"] > 1
        return {
            "status": "completed",
            "candidate_count": 1,
            "processed_count": 0 if already_checked else 1,
            "passed_count": 0 if already_checked else 1,
            "blocked_count": 0,
            "skipped_count": 1 if already_checked else 0,
            "risk_decision_writes_performed": not already_checked,
            "blockers": [],
        }

    service = DailyDecisionEvidenceAutomationService(
        db=db,
        trading_controls=controls,
        notifier=notifier,
        plan_reader=read_plan,
        risk_runner=run_risk,
    )

    first = asyncio.run(service.run_once())
    second = asyncio.run(service.run_once())

    assert first["status"] == "paper_shadow_completed"
    assert first["risk"]["passed_count"] == 1
    assert first["risk"]["newly_passed_count"] == 1
    assert first["paper_shadow"]["status"] == "within_expectations"
    assert first["paper_shadow"]["simulated_order_count"] == 1
    assert first["manual_confirmation_required"] is True
    assert first["broker_submission_enabled"] is False
    assert first["does_not_submit_broker_order"] is True
    assert first["does_not_mutate_production_ledger"] is True
    assert first["notification"] == {"status": "sent", "sent": True}
    assert second["notification"] == {
        "status": "skipped_duplicate_evidence",
        "sent": False,
    }
    assert second["risk"]["passed_count"] == 1
    assert second["risk"]["newly_passed_count"] == 0
    assert state["risk_calls"] == 2
    assert len(notifier.messages) == 1
    assert "仍需在 Web 中人工复核" in notifier.messages[0][1]
    assert db.latest_paper_shadow_run_sync(plan_date="2026-07-02") is not None
    assert len(db.list_orders_sync()) == 1
    assert len(db.list_fills_sync()) == 1
    assert db.list_manual_orders_sync() == []
    assert db.get_ledger_entries_sync() == []
    assert (
        len(
            db.list_automation_runs_sync(
                run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE
            )
        )
        == 1
    )
    assert len(db.list_automation_runs_sync(run_type="daily_paper_shadow")) == 1


def test_automatic_evidence_chain_fails_closed_on_incomplete_risk_evidence(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    notifier = RecordingNotifier()

    async def read_plan():
        return _decision(risk_checked=False), _plan(risk_checked=False)

    async def run_risk():
        return {
            "status": "blocked_by_data_quality",
            "candidate_count": 1,
            "processed_count": 0,
            "passed_count": 0,
            "blocked_count": 0,
            "skipped_count": 1,
            "risk_decision_writes_performed": False,
            "blockers": [{"code": "valuation_snapshot_not_complete"}],
        }

    service = DailyDecisionEvidenceAutomationService(
        db=db,
        trading_controls=TradingControlState(db=db),
        notifier=notifier,
        plan_reader=read_plan,
        risk_runner=run_risk,
    )

    result = asyncio.run(service.run_once())

    assert result["status"] == "blocked_by_data_quality"
    assert result["risk"]["risk_decision_writes_performed"] is False
    assert result["paper_shadow"]["status"] == "not_run"
    assert db.latest_paper_shadow_run_sync(plan_date="2026-07-02") is None
    assert db.list_orders_sync() == []
    assert db.list_fills_sync() == []
    assert notifier.messages == []


def test_automatic_evidence_chain_obeys_kill_switch_before_risk_writes(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    controls = TradingControlState(db=db)
    controls.set_kill_switch(True, "operator pause")
    risk_called = False

    async def read_plan():
        return _decision(risk_checked=False), _plan(risk_checked=False)

    async def run_risk():
        nonlocal risk_called
        risk_called = True
        return {"status": "completed"}

    service = DailyDecisionEvidenceAutomationService(
        db=db,
        trading_controls=controls,
        notifier=RecordingNotifier(),
        plan_reader=read_plan,
        risk_runner=run_risk,
    )

    result = asyncio.run(service.run_once())

    assert result["status"] == "blocked_by_kill_switch"
    assert risk_called is False
    assert db.get_risk_decisions_sync() == []
    assert db.latest_paper_shadow_run_sync(plan_date="2026-07-02") is None
    assert db.list_orders_sync() == []
