from __future__ import annotations

import asyncio

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
