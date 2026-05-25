from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from decimal import Decimal

from core.events import OrderIntentEvent, RiskDecisionEvent
from core.types import OrderSide, Symbol
from server.db import AppDatabase


def test_app_database_initializes_quote_fetch_runs_table(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    with sqlite3.connect(tmp_path / "app.db") as conn:
        table = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'quote_fetch_runs'
            """
        ).fetchone()
        indexes = {
            row[0]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'index' AND tbl_name = 'quote_fetch_runs'
                """
            ).fetchall()
        }

    assert table is not None
    assert "idx_quote_fetch_runs_started_at" in indexes
    assert "idx_quote_fetch_runs_status" in indexes
    assert "idx_quote_fetch_runs_provider" in indexes


def test_app_database_initializes_latest_quotes_table(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    with sqlite3.connect(tmp_path / "app.db") as conn:
        table = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'latest_quotes'
            """
        ).fetchone()
        indexes = {
            row[0]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'index' AND tbl_name = 'latest_quotes'
                """
            ).fetchall()
        }

    assert table is not None
    assert "idx_latest_quotes_symbol_asset_type" in indexes
    assert "idx_latest_quotes_quote_timestamp" in indexes
    assert "idx_latest_quotes_provider_status" in indexes
    assert "idx_latest_quotes_quote_status" in indexes


def test_app_database_upserts_and_reads_latest_quote(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    db.upsert_latest_quote_sync(
        symbol="600519",
        asset_type="stock",
        price=123.45,
        volume=1000.0,
        quote_timestamp="2026-05-23T09:30:00+08:00",
        quote_source="akshare",
        provider_name="akshare",
        provider_status="live",
        quote_status="live",
        captured_at="2026-05-23T09:30:01+08:00",
        captured_reason="manual_or_route_refresh",
        metadata={"provider_status": "live"},
    )
    first = db.get_latest_quote_sync("600519", asset_type="stock")

    db.upsert_latest_quote_sync(
        symbol="600519",
        asset_type="stock",
        price=124.0,
        previous_close=122.5,
        change=1.5,
        change_percent=0.012245,
        volume=1200.0,
        turnover=500000.0,
        quote_timestamp="2026-05-23T09:31:00+08:00",
        quote_source="akshare",
        provider_name="akshare",
        provider_status="live",
        quote_status="live",
        captured_at="2026-05-23T09:31:01+08:00",
        captured_reason="scheduler_poll",
        nav_date="2026-05-23",
        metadata={"provider_status": "live", "sequence": 2},
    )
    updated = db.get_latest_quote_sync("600519", asset_type="stock")

    with sqlite3.connect(tmp_path / "app.db") as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM latest_quotes WHERE symbol = ? AND asset_type = ?",
            ("600519", "stock"),
        ).fetchone()[0]

    assert first is not None
    assert updated is not None
    assert count == 1
    assert updated["id"] == first["id"]
    assert updated["created_at"] == first["created_at"]
    assert updated["updated_at"] != first["updated_at"]
    assert updated["price"] == 124.0
    assert updated["previous_close"] == 122.5
    assert updated["captured_reason"] == "scheduler_poll"
    assert updated["metadata_json"] == '{"provider_status":"live","sequence":2}'


def test_app_database_latest_quote_default_read_uses_newest_symbol_row(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    db.upsert_latest_quote_sync(
        symbol="510300",
        asset_type="stock",
        price=3.9,
        quote_timestamp="2026-05-23T09:30:00+08:00",
        captured_at="2026-05-23T09:30:01+08:00",
    )
    db.upsert_latest_quote_sync(
        symbol="510300",
        asset_type="fund",
        price=4.0,
        quote_timestamp="2026-05-23T09:31:00+08:00",
        captured_at="2026-05-23T09:31:01+08:00",
    )

    quote = db.get_latest_quote_sync("510300")

    assert quote is not None
    assert quote["asset_type"] == "fund"
    assert quote["price"] == 4.0


def test_app_database_lists_latest_quotes_by_quote_timestamp(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    db.upsert_latest_quote_sync(
        symbol="600519",
        asset_type="stock",
        price=123.45,
        quote_timestamp="2026-05-23T09:30:00+08:00",
        captured_at="2026-05-23T09:30:01+08:00",
    )
    db.upsert_latest_quote_sync(
        symbol="510300",
        asset_type="fund",
        price=4.0,
        quote_timestamp="2026-05-23T09:31:00+08:00",
        captured_at="2026-05-23T09:31:01+08:00",
    )

    rows = db.list_latest_quotes_sync()

    assert [row["symbol"] for row in rows] == ["510300", "600519"]


def test_app_database_records_quote_fetch_run_lifecycle(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    row_id = db.create_quote_fetch_run(
        run_id="quote-run-1",
        started_at="2026-05-23T09:30:00+08:00",
        trigger="manual_refresh",
        provider="akshare",
        asset_type="stock",
        symbol_count=3,
        status="running",
        metadata={"symbols": ["600519", "510300"]},
    )

    created = db.get_quote_fetch_run("quote-run-1")
    assert row_id > 0
    assert created is not None
    assert created["run_id"] == "quote-run-1"
    assert created["finished_at"] is None
    assert created["status"] == "running"
    assert created["provider"] == "akshare"
    assert created["metadata_json"] == '{"symbols":["600519","510300"]}'

    db.finish_quote_fetch_run(
        run_id="quote-run-1",
        finished_at="2026-05-23T09:30:03+08:00",
        status="completed",
        success_count=2,
        failure_count=1,
        cache_hit_count=1,
        error_message="1 symbol timed out",
        metadata={"elapsed_ms": 3000},
    )

    finished = db.get_quote_fetch_run("quote-run-1")
    assert finished is not None
    assert finished["finished_at"] == "2026-05-23T09:30:03+08:00"
    assert finished["success_count"] == 2
    assert finished["failure_count"] == 1
    assert finished["cache_hit_count"] == 1
    assert finished["status"] == "completed"
    assert finished["error_message"] == "1 symbol timed out"
    assert finished["metadata_json"] == '{"elapsed_ms":3000}'


def test_app_database_lists_recent_quote_fetch_runs(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    db.create_quote_fetch_run(
        run_id="quote-run-older",
        started_at="2026-05-23T09:30:00+08:00",
        trigger="scheduler",
        status="completed",
    )
    db.create_quote_fetch_run(
        run_id="quote-run-newer",
        started_at="2026-05-23T09:31:00+08:00",
        trigger="manual_refresh",
        status="running",
    )

    rows = db.list_quote_fetch_runs()
    limited = db.list_quote_fetch_runs(limit=1)

    assert [row["run_id"] for row in rows] == ["quote-run-newer", "quote-run-older"]
    assert [row["run_id"] for row in limited] == ["quote-run-newer"]


def test_app_database_filters_quote_fetch_runs(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    db.create_quote_fetch_run(
        run_id="manual-akshare-success",
        started_at="2026-05-23T09:32:00+08:00",
        trigger="manual_refresh",
        provider="akshare",
        status="success",
    )
    db.create_quote_fetch_run(
        run_id="scheduler-akshare-failed",
        started_at="2026-05-23T09:31:00+08:00",
        trigger="scheduler_poll",
        provider="akshare",
        status="failed",
    )
    db.create_quote_fetch_run(
        run_id="manual-tushare-success",
        started_at="2026-05-23T09:30:00+08:00",
        trigger="manual_refresh",
        provider="tushare",
        status="success",
    )

    assert [
        row["run_id"]
        for row in db.list_quote_fetch_runs(trigger="manual_refresh")
    ] == ["manual-akshare-success", "manual-tushare-success"]
    assert [
        row["run_id"] for row in db.list_quote_fetch_runs(status="failed")
    ] == ["scheduler-akshare-failed"]
    assert [
        row["run_id"] for row in db.list_quote_fetch_runs(provider="tushare")
    ] == ["manual-tushare-success"]
    assert [
        row["run_id"]
        for row in db.list_quote_fetch_runs(
            trigger="manual_refresh",
            status="success",
            provider="akshare",
        )
    ] == ["manual-akshare-success"]


def test_app_database_rejects_duplicate_quote_fetch_run_id(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    db.create_quote_fetch_run(
        run_id="quote-run-1",
        started_at="2026-05-23T09:30:00+08:00",
        trigger="manual_refresh",
        status="running",
    )

    try:
        db.create_quote_fetch_run(
            run_id="quote-run-1",
            started_at="2026-05-23T09:31:00+08:00",
            trigger="manual_refresh",
            status="running",
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("duplicate quote fetch run_id should be rejected")


def test_app_database_persists_latest_quote_snapshot(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="600519",
        asset_class="stock",
        price=123.45,
        volume=6789.0,
        timestamp="2026-04-18T09:35:00",
        quote_source="akshare",
        provider_name="akshare",
        quote_status="live",
        provider_status="live",
        captured_reason="test_refresh",
        nav_date="2026-04-18",
    )
    quote = db.get_latest_quotes_sync()[0]

    assert quote is not None
    assert quote["symbol"] == "600519"
    assert quote["price"] == 123.45
    assert quote["asset_class"] == "stock"
    assert quote["quote_source"] == "akshare"
    assert quote["provider_name"] == "akshare"
    assert quote["quote_status"] == "live"
    assert quote["captured_reason"] == "test_refresh"
    assert quote["nav_date"] == "2026-04-18"


def test_app_database_quote_snapshots_remain_append_only_with_latest_quote(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    for minute, price in (("30", 123.45), ("31", 124.0)):
        db.save_quote_snapshot_sync(
            symbol="600519",
            asset_class="stock",
            price=price,
            volume=1000.0,
            timestamp=f"2026-05-23T09:{minute}:00+08:00",
            quote_source="akshare",
            provider_name="akshare",
            quote_status="live",
            provider_status="live",
            captured_reason="test_refresh",
        )
        db.upsert_latest_quote_sync(
            symbol="600519",
            asset_type="stock",
            price=price,
            quote_timestamp=f"2026-05-23T09:{minute}:00+08:00",
            captured_at=f"2026-05-23T09:{minute}:01+08:00",
            quote_source="akshare",
            provider_name="akshare",
        )

    recent = db.get_recent_quote_snapshots_sync("600519", limit=10)
    latest = db.list_latest_quotes_sync()

    assert len(recent) == 2
    assert len(latest) == 1
    assert latest[0]["price"] == 124.0


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


def test_app_database_persists_backtest_metrics_and_cost_summary_json(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    result_id = asyncio.run(
        db.save_backtest_result(
            config_json="{}",
            initial_cash=100000.0,
            final_equity=110000.0,
            total_return=0.1,
            sharpe=1.2,
            max_dd=0.08,
            equity_curve_json="[]",
            annual_return=0.12,
            sortino=1.8,
            win_rate=0.55,
            duration_days=252,
            metrics_json='{"calmar": 1.5}',
            cost_summary_json='{"total_commission": 12.3}',
        )
    )

    row = asyncio.run(db.get_backtest_result(result_id))

    assert row is not None
    assert row["metrics_json"] == '{"calmar": 1.5}'
    assert row["cost_summary_json"] == '{"total_commission": 12.3}'
