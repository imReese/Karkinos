from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal

from core.events import OrderIntentEvent, RiskDecisionEvent
from core.types import OrderSide, Symbol
from server.db import AppDatabase


def test_app_database_persists_latest_quote_snapshot(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="600519",
        asset_class="stock",
        price=123.45,
        volume=6789.0,
        timestamp="2026-04-18T09:35:00",
    )
    quote = db.get_latest_quotes_sync()[0]

    assert quote is not None
    assert quote["symbol"] == "600519"
    assert quote["price"] == 123.45
    assert quote["asset_class"] == "stock"


def test_app_database_persists_action_tasks_and_status_updates(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    db.upsert_action_task_sync(
        source_signal_id=11,
        symbol="600519",
        title="建议增持 600519",
        detail="dual_ma 触发，目标仓位 20%",
        direction="buy",
        urgency="high",
        target_weight=0.2,
        price=123.45,
        strategy_id="dual_ma",
        timestamp="2026-04-18T09:35:00",
        asset_class="stock",
    )

    pending = asyncio.run(db.get_action_tasks(statuses=["pending"]))
    assert len(pending) == 1
    assert pending[0]["status"] == "pending"
    assert pending[0]["symbol"] == "600519"

    updated = asyncio.run(db.update_action_task_status(pending[0]["id"], "deferred"))
    assert updated is not None
    assert updated["status"] == "deferred"

    deferred = asyncio.run(db.get_action_tasks(statuses=["deferred"]))
    assert len(deferred) == 1
    assert deferred[0]["source_signal_id"] == 11


def test_app_database_persists_risk_decision_audit(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    intent = OrderIntentEvent(
        timestamp=datetime(2026, 4, 18, 14, 50),
        intent_id="INTENT-1",
        strategy_id="dual_ma",
        symbol=Symbol("600519"),
        side=OrderSide.BUY,
        target_weight=Decimal("0.20"),
        quantity=Decimal("100"),
        reference_price=Decimal("123.45"),
        reason="unit test",
    )
    decision = RiskDecisionEvent(
        timestamp=intent.timestamp,
        decision_id="RISK-1",
        intent_id=intent.intent_id,
        passed=False,
        symbol=intent.symbol,
        side=intent.side,
        reasons=["single-symbol weight exceeded"],
        severity="warning",
    )

    db.save_risk_decision_sync(intent=intent, decision=decision)
    rows = db.get_risk_decisions_sync()

    assert len(rows) == 1
    assert rows[0]["decision_id"] == "RISK-1"
    assert rows[0]["intent_id"] == "INTENT-1"
    assert rows[0]["passed"] == 0
    assert rows[0]["symbol"] == "600519"
