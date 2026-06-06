from __future__ import annotations

import asyncio
import json
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
        table = conn.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'quote_fetch_runs'
            """).fetchone()
        indexes = {row[0] for row in conn.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type = 'index' AND tbl_name = 'quote_fetch_runs'
                """).fetchall()}

    assert table is not None
    assert "idx_quote_fetch_runs_started_at" in indexes
    assert "idx_quote_fetch_runs_status" in indexes
    assert "idx_quote_fetch_runs_provider" in indexes


def test_app_database_initializes_event_log_table(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    with sqlite3.connect(tmp_path / "app.db") as conn:
        table = conn.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'event_log'
            """).fetchone()
        indexes = {row[0] for row in conn.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type = 'index' AND tbl_name = 'event_log'
                """).fetchall()}

    assert table is not None
    assert "idx_event_log_type_ts" in indexes
    assert "idx_event_log_entity" in indexes
    assert "idx_event_log_source" in indexes


def test_app_database_initializes_fills_table(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    with sqlite3.connect(tmp_path / "app.db") as conn:
        table = conn.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'fills'
            """).fetchone()
        indexes = {row[0] for row in conn.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type = 'index' AND tbl_name = 'fills'
                """).fetchall()}

    assert table is not None
    assert "idx_fills_order_ts" in indexes
    assert "idx_fills_symbol_ts" in indexes
    assert "idx_fills_source" in indexes


def test_app_database_initializes_latest_quotes_table(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    with sqlite3.connect(tmp_path / "app.db") as conn:
        table = conn.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'latest_quotes'
            """).fetchone()
        indexes = {row[0] for row in conn.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type = 'index' AND tbl_name = 'latest_quotes'
                """).fetchall()}

    assert table is not None
    assert "idx_latest_quotes_symbol_asset_type" in indexes
    assert "idx_latest_quotes_quote_timestamp" in indexes
    assert "idx_latest_quotes_provider_status" in indexes
    assert "idx_latest_quotes_quote_status" in indexes


def test_app_database_initializes_instrument_metadata_table(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    with sqlite3.connect(tmp_path / "app.db") as conn:
        table = conn.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'instrument_metadata'
            """).fetchone()
        indexes = {row[0] for row in conn.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type = 'index' AND tbl_name = 'instrument_metadata'
                """).fetchall()}

    assert table is not None
    assert "idx_instrument_metadata_symbol_asset_type" in indexes
    assert "idx_instrument_metadata_display_name" in indexes
    assert "idx_instrument_metadata_provider" in indexes


def test_app_database_persists_watchlist_assets(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    created = db.upsert_watchlist_asset_sync(
        symbol="510300",
        asset_class="etf",
        display_name="沪深300ETF",
    )
    updated = db.upsert_watchlist_asset_sync(
        symbol="510300",
        asset_class="etf",
        display_name="沪深300 ETF",
        source="manual",
    )
    seeded = db.seed_watchlist_assets_from_config_sync(
        [{"symbol": "018125", "asset_class": "fund", "display_name": "示例基金"}]
    )
    rows = db.list_watchlist_assets_sync()
    deleted = db.delete_watchlist_asset_sync("510300")

    assert created is not None
    assert updated is not None
    assert updated["id"] == created["id"]
    assert updated["display_name"] == "沪深300 ETF"
    assert seeded == 1
    assert [row["symbol"] for row in rows] == ["510300", "018125"]
    assert deleted is True
    assert [row["symbol"] for row in db.list_watchlist_assets_sync()] == ["018125"]


def test_app_database_upserts_and_reads_instrument_metadata(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    created = db.upsert_instrument_metadata_sync(
        symbol="601985",
        asset_type="stock",
        display_name="中国核电",
        provider_symbol="601985",
        exchange="SH",
        market="cn",
        provider_name="akshare",
        source="quote",
        fetched_at="2026-05-29T09:30:00+08:00",
        metadata={"provider_status": "live"},
    )
    updated = db.upsert_instrument_metadata_sync(
        symbol="601985",
        asset_type="stock",
        display_name="中国核电",
        provider_symbol="601985",
        exchange="SH",
        market="cn",
        provider_name="akshare",
        source="quote",
        fetched_at="2026-05-29T09:31:00+08:00",
        metadata={"provider_status": "live", "sequence": 2},
    )
    row = db.get_instrument_metadata_sync("601985", "stock")
    rows = db.list_instrument_metadata_sync()

    with sqlite3.connect(tmp_path / "app.db") as conn:
        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM instrument_metadata
            WHERE symbol = ? AND asset_type = ?
            """,
            ("601985", "stock"),
        ).fetchone()[0]

    assert created is not None
    assert updated is not None
    assert row is not None
    assert count == 1
    assert updated["id"] == created["id"]
    assert updated["created_at"] == created["created_at"]
    assert updated["updated_at"] != created["updated_at"]
    assert row["display_name"] == "中国核电"
    assert row["metadata_json"] == '{"provider_status":"live","sequence":2}'
    assert [item["symbol"] for item in rows] == ["601985"]


def test_app_database_appends_and_lists_domain_events(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    event_id = db.append_event_sync(
        event_type="market.quote.refreshed",
        timestamp="2026-05-23T09:30:00Z",
        entity_type="instrument",
        entity_id="600519",
        source="test",
        source_ref="quote-1",
        payload={"price": Decimal("123.45"), "status": "live"},
    )
    db.append_event_sync(
        event_type="portfolio.snapshot.created",
        timestamp="2026-05-23T09:31:00+08:00",
        entity_type="portfolio",
        entity_id="default",
        source="test",
        source_ref="snapshot-1",
        payload={"cash": 1000},
    )

    all_events = db.list_events_sync()
    quote_events = db.list_events_sync(event_type="market.quote.refreshed")
    instrument_events = db.list_events_sync(
        entity_type="instrument",
        entity_id="600519",
    )

    assert event_id == 1
    assert [event["event_type"] for event in all_events] == [
        "portfolio.snapshot.created",
        "market.quote.refreshed",
    ]
    assert quote_events[0]["source_ref"] == "quote-1"
    assert json.loads(quote_events[0]["payload_json"]) == {
        "price": "123.45",
        "status": "live",
    }
    assert instrument_events == quote_events


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
    events = db.list_events_sync(
        event_type="market.quote.refreshed",
        entity_type="instrument",
        entity_id="600519",
    )

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
    assert [event["source"] for event in events] == ["latest_quotes", "latest_quotes"]
    assert events[0]["source_ref"] == str(updated["id"])
    assert json.loads(events[0]["payload_json"]) == {
        "asset_type": "stock",
        "captured_at": "2026-05-23T09:31:01+08:00",
        "captured_reason": "scheduler_poll",
        "change": 1.5,
        "change_percent": 0.012245,
        "metadata": {"provider_status": "live", "sequence": 2},
        "nav_date": "2026-05-23",
        "previous_close": 122.5,
        "price": 124.0,
        "provider_name": "akshare",
        "provider_status": "live",
        "quote_id": updated["id"],
        "quote_source": "akshare",
        "quote_status": "live",
        "quote_timestamp": "2026-05-23T09:31:00+08:00",
        "stale_reason": None,
        "symbol": "600519",
        "turnover": 500000.0,
        "volume": 1200.0,
    }


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

    events = db.list_events_sync(entity_type="task_run", entity_id="quote-run-1")

    assert [event["event_type"] for event in events] == [
        "task_run.completed",
        "task_run.started",
    ]
    assert events[0]["source"] == "quote_fetch_runs"
    assert events[0]["source_ref"] == "quote-run-1"
    assert json.loads(events[0]["payload_json"]) == {
        "asset_type": "stock",
        "cache_hit_count": 1,
        "error_message": "1 symbol timed out",
        "failure_count": 1,
        "finished_at": "2026-05-23T09:30:03+08:00",
        "metadata": {"elapsed_ms": 3000},
        "provider": "akshare",
        "run_id": "quote-run-1",
        "started_at": "2026-05-23T09:30:00+08:00",
        "status": "completed",
        "success_count": 2,
        "symbol_count": 3,
        "trigger": "manual_refresh",
    }


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
        row["run_id"] for row in db.list_quote_fetch_runs(trigger="manual_refresh")
    ] == ["manual-akshare-success", "manual-tushare-success"]
    assert [row["run_id"] for row in db.list_quote_fetch_runs(status="failed")] == [
        "scheduler-akshare-failed"
    ]
    assert [row["run_id"] for row in db.list_quote_fetch_runs(provider="tushare")] == [
        "manual-tushare-success"
    ]
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
    events = db.list_events_sync(
        event_type="market.quote.snapshot.recorded",
        entity_type="instrument",
        entity_id="600519",
    )

    assert quote is not None
    assert quote["symbol"] == "600519"
    assert quote["price"] == 123.45
    assert quote["asset_class"] == "stock"
    assert quote["quote_source"] == "akshare"
    assert quote["provider_name"] == "akshare"
    assert quote["quote_status"] == "live"
    assert quote["captured_reason"] == "test_refresh"
    assert quote["nav_date"] == "2026-04-18"
    assert len(events) == 1
    assert events[0]["source"] == "quote_snapshots"
    assert events[0]["source_ref"] == "1"
    assert json.loads(events[0]["payload_json"]) == {
        "asset_class": "stock",
        "captured_reason": "test_refresh",
        "nav_date": "2026-04-18",
        "price": 123.45,
        "provider_name": "akshare",
        "provider_status": "live",
        "quote_source": "akshare",
        "quote_status": "live",
        "snapshot_id": 1,
        "stale_reason": None,
        "symbol": "600519",
        "timestamp": "2026-04-18T09:35:00",
        "volume": 6789.0,
    }


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


def test_app_database_portfolio_snapshots_append_portfolio_events(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    positions_json = '[{"symbol":"600519","quantity":10,"market_value":1234.5}]'
    allocation_json = '{"stock":0.8,"cash":0.2}'
    db.save_portfolio_snapshot_sync(
        cash=5000.0,
        total_equity=6234.5,
        positions_json=positions_json,
        allocation_json=allocation_json,
    )
    events = db.list_events_sync(
        event_type="portfolio.snapshot.created",
        entity_type="portfolio",
        entity_id="default",
    )

    with sqlite3.connect(tmp_path / "app.db") as conn:
        conn.row_factory = sqlite3.Row
        snapshot = conn.execute("SELECT * FROM portfolio_snapshots").fetchone()

    assert snapshot is not None
    assert snapshot["cash"] == 5000.0
    assert snapshot["total_equity"] == 6234.5
    assert snapshot["positions_json"] == positions_json
    assert snapshot["allocation_json"] == allocation_json
    assert len(events) == 1
    assert events[0]["source"] == "portfolio_snapshots"
    assert events[0]["source_ref"] == str(snapshot["id"])
    assert json.loads(events[0]["payload_json"]) == {
        "allocation": {"cash": 0.2, "stock": 0.8},
        "cash": 5000.0,
        "portfolio_id": "default",
        "positions": [
            {
                "market_value": 1234.5,
                "quantity": 10,
                "symbol": "600519",
            }
        ],
        "snapshot_id": snapshot["id"],
        "timestamp": snapshot["timestamp"],
        "total_equity": 6234.5,
    }


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

    events = db.list_events_sync(
        entity_type="action_task", entity_id=str(pending[0]["id"])
    )
    assert [event["event_type"] for event in events] == [
        "task.action.status_changed",
        "task.action.created",
    ]
    assert events[0]["source"] == "action_tasks"
    assert events[0]["source_ref"] == str(pending[0]["id"])
    assert json.loads(events[0]["payload_json"]) == {
        "asset_class": "stock",
        "detail": "dual_ma 触发，目标仓位 20%",
        "direction": "buy",
        "price": 123.45,
        "source_signal_id": 11,
        "status": "deferred",
        "strategy_id": "dual_ma",
        "symbol": "600519",
        "target_weight": 0.2,
        "task_id": pending[0]["id"],
        "timestamp": "2026-04-18T09:35:00",
        "title": "建议增持 600519",
        "urgency": "high",
    }
    assert json.loads(events[1]["payload_json"]) == {
        "asset_class": "stock",
        "detail": "dual_ma 触发，目标仓位 20%",
        "direction": "buy",
        "price": 123.45,
        "source_signal_id": 11,
        "status": "pending",
        "strategy_id": "dual_ma",
        "symbol": "600519",
        "target_weight": 0.2,
        "task_id": pending[0]["id"],
        "timestamp": "2026-04-18T09:35:00",
        "title": "建议增持 600519",
        "urgency": "high",
    }


def test_app_database_research_notes_append_research_events(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    note_id = asyncio.run(
        db.add_research_note(
            symbol="600519",
            asset_class="stock",
            entry_kind="note",
            title="Earnings read-through",
            content="Margin trend improving.",
            priority="high",
            event_date="2026-05-23",
        )
    )

    events = db.list_events_sync(
        event_type="research.note.created",
        entity_type="instrument",
        entity_id="600519",
    )

    assert note_id == 1
    assert len(events) == 1
    assert events[0]["source"] == "market_research_notes"
    assert events[0]["source_ref"] == "1"
    assert json.loads(events[0]["payload_json"]) == {
        "asset_class": "stock",
        "content": "Margin trend improving.",
        "entry_kind": "note",
        "event_date": "2026-05-23",
        "note_id": 1,
        "priority": "high",
        "symbol": "600519",
        "title": "Earnings read-through",
    }


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
    events = db.list_events_sync(
        event_type="risk.signal.recorded",
        entity_type="risk_signal",
        entity_id="RISK-1",
    )

    assert len(rows) == 1
    assert rows[0]["decision_id"] == "RISK-1"
    assert rows[0]["intent_id"] == "INTENT-1"
    assert rows[0]["passed"] == 0
    assert rows[0]["symbol"] == "600519"
    assert len(events) == 1
    assert events[0]["source"] == "risk_decisions"
    assert events[0]["source_ref"] == "RISK-1"
    assert json.loads(events[0]["payload_json"]) == {
        "decision": {
            "decision_id": "RISK-1",
            "intent_id": "INTENT-1",
            "passed": False,
            "reasons": ["single-symbol weight exceeded"],
            "severity": "warning",
            "side": "buy",
            "symbol": "600519",
            "timestamp": "2026-04-18T14:50:00",
        },
        "intent": {
            "intent_id": "INTENT-1",
            "quantity": "100",
            "reason": "unit test",
            "reference_price": "123.45",
            "side": "buy",
            "strategy_id": "dual_ma",
            "symbol": "600519",
            "target_weight": "0.20",
            "timestamp": "2026-04-18T14:50:00",
        },
        "risk_decision_id": rows[0]["id"],
    }


def test_app_database_ledger_entries_append_portfolio_events(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    entry_id = db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-04-18T09:35:00+08:00",
        symbol="600519",
        direction="buy",
        quantity=10.0,
        price=123.45,
        commission=1.23,
        asset_class="stock",
        source="manual",
        source_ref="trade-1",
        note="unit test trade",
    )
    events = db.list_events_sync(
        event_type="portfolio.ledger_entry.recorded",
        entity_type="portfolio",
        entity_id="default",
    )

    assert len(events) == 1
    assert events[0]["source"] == "ledger_entries"
    assert events[0]["source_ref"] == str(entry_id)
    assert json.loads(events[0]["payload_json"]) == {
        "amount": None,
        "asset_class": "stock",
        "commission": 1.23,
        "direction": "buy",
        "entry_id": entry_id,
        "entry_type": "trade_buy",
        "note": "unit test trade",
        "price": 123.45,
        "quantity": 10.0,
        "source": "manual",
        "source_ref": "trade-1",
        "symbol": "600519",
        "timestamp": "2026-04-18T01:35:00+00:00",
    }


def test_app_database_manual_orders_append_order_events(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    row_id = db.save_manual_order_sync(
        order_id="ORD-1",
        timestamp="2026-04-18T14:50:00",
        symbol="600519",
        side="buy",
        order_type="market",
        quantity=100.0,
        price=123.45,
        intent_id="INTENT-1",
        risk_decision_id="RISK-1",
        execution_mode="manual",
        status="pending_confirm",
        payload={"reason": "unit test"},
    )
    db.update_manual_order_status_sync(
        order_id="ORD-1",
        status="confirmed",
        note="operator approved",
    )
    events = db.list_events_sync(entity_type="order", entity_id="ORD-1")

    assert [event["event_type"] for event in events] == [
        "order.status_changed",
        "order.submitted",
    ]
    assert events[0]["source"] == "manual_orders"
    assert events[0]["source_ref"] == "ORD-1"
    assert json.loads(events[0]["payload_json"]) == {
        "execution_mode": "manual",
        "intent_id": "INTENT-1",
        "note": "operator approved",
        "order_id": "ORD-1",
        "order_row_id": row_id,
        "order_type": "market",
        "payload": {"reason": "unit test"},
        "price": 123.45,
        "quantity": 100.0,
        "risk_decision_id": "RISK-1",
        "side": "buy",
        "status": "confirmed",
        "symbol": "600519",
        "timestamp": "2026-04-18T14:50:00",
    }
    assert json.loads(events[1]["payload_json"]) == {
        "execution_mode": "manual",
        "intent_id": "INTENT-1",
        "note": "",
        "order_id": "ORD-1",
        "order_row_id": row_id,
        "order_type": "market",
        "payload": {"reason": "unit test"},
        "price": 123.45,
        "quantity": 100.0,
        "risk_decision_id": "RISK-1",
        "side": "buy",
        "status": "pending_confirm",
        "symbol": "600519",
        "timestamp": "2026-04-18T14:50:00",
    }


def test_app_database_records_fill_and_appends_order_fill_event(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    row_id = db.record_fill_sync(
        fill_id="FILL-1",
        order_id="ORD-1",
        timestamp="2026-04-18T14:50:03",
        symbol="600519",
        side="buy",
        fill_price=123.46,
        fill_quantity=100.0,
        commission=5.0,
        slippage=1.0,
        asset_class="stock",
        execution_mode="paper",
        provider_name="simulated",
        broker_order_id="SIM-ORD-1",
        source="simulated_execution",
        source_ref="SIM-FILL-1",
        metadata={"latency_ms": 12},
    )
    updated_id = db.record_fill_sync(
        fill_id="FILL-1",
        order_id="ORD-1",
        timestamp="2026-04-18T14:50:04",
        symbol="600519",
        side="buy",
        fill_price=123.47,
        fill_quantity=100.0,
        commission=5.1,
        slippage=1.1,
        asset_class="stock",
        execution_mode="paper",
        provider_name="simulated",
        broker_order_id="SIM-ORD-1",
        source="simulated_execution",
        source_ref="SIM-FILL-1",
        metadata={"latency_ms": 14},
    )

    fill = db.get_fill_sync("FILL-1")
    fills = db.list_fills_sync(order_id="ORD-1")
    events = db.list_events_sync(entity_type="fill", entity_id="FILL-1")

    assert updated_id == row_id
    assert len(fills) == 1
    assert fill == fills[0]
    assert fill["fill_id"] == "FILL-1"
    assert fill["order_id"] == "ORD-1"
    assert fill["fill_price"] == 123.47
    assert fill["source"] == "simulated_execution"
    assert fill["source_ref"] == "SIM-FILL-1"
    assert json.loads(fill["metadata_json"]) == {"latency_ms": 14}
    assert [event["event_type"] for event in events] == [
        "order.fill.recorded",
        "order.fill.recorded",
    ]
    assert json.loads(events[0]["payload_json"]) == {
        "asset_class": "stock",
        "broker_order_id": "SIM-ORD-1",
        "commission": 5.1,
        "execution_mode": "paper",
        "fill_id": "FILL-1",
        "fill_price": 123.47,
        "fill_quantity": 100.0,
        "fill_row_id": row_id,
        "metadata": {"latency_ms": 14},
        "order_id": "ORD-1",
        "provider_name": "simulated",
        "side": "buy",
        "slippage": 1.1,
        "source": "simulated_execution",
        "source_ref": "SIM-FILL-1",
        "symbol": "600519",
        "timestamp": "2026-04-18T14:50:04",
    }


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
