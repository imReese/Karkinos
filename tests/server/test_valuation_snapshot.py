from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from server.db import AppDatabase
from server.services.valuation_snapshot import build_current_valuation_snapshot


def test_valuation_snapshot_is_content_addressed_and_replayable(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
        quote_source="tushare_realtime_quote",
        provider_name="tushare",
        quote_status="live",
        provider_status="live",
        captured_reason="scheduler_poll",
    )

    first = build_current_valuation_snapshot(db)
    second = build_current_valuation_snapshot(db)
    stored = db.get_valuation_snapshot_sync(first["snapshot_id"])

    assert first == second
    assert first["snapshot_id"].startswith("valuation-")
    assert first["status"] == "complete"
    assert first["metadata"] == {
        "quote_count": 1,
        "ledger_entry_count": 0,
        "persisted_facts_only": True,
        "runtime_cache_used": False,
        "provider_fetch_used": False,
        "ingestion_run_ids": [],
    }
    assert stored is not None
    assert json.loads(stored["quotes_json"])[0]["symbol"] == "603659"


def test_valuation_snapshot_changes_when_persisted_quote_changes(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )
    first = build_current_valuation_snapshot(db)

    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.7,
        volume=1200.0,
        timestamp="2026-07-10T14:58:03+08:00",
    )
    second = build_current_valuation_snapshot(db)

    assert second["snapshot_id"] != first["snapshot_id"]
    assert second["quote_set_fingerprint"] != first["quote_set_fingerprint"]


def test_valuation_snapshot_freezes_previous_close_evidence(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_daily_close_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        trade_date="2026-07-09",
        close_price=25.46,
        source="test_close",
    )
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )

    first = build_current_valuation_snapshot(db)
    stored_first = db.get_valuation_snapshot_sync(first["snapshot_id"])
    assert first["quotes"][0]["previous_close"] == 25.46
    assert first["quotes"][0]["previous_close_date"] == "2026-07-09"
    assert first["quotes"][0]["valuation_baseline_status"] == "complete"

    db.save_daily_close_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        trade_date="2026-07-09",
        close_price=25.40,
        source="corrected_close",
    )
    second = build_current_valuation_snapshot(db)

    assert second["snapshot_id"] != first["snapshot_id"]
    assert second["quote_set_fingerprint"] != first["quote_set_fingerprint"]
    assert json.loads(stored_first["quotes_json"])[0]["previous_close"] == 25.46
    assert second["quotes"][0]["previous_close"] == 25.40


def test_valuation_trade_date_comes_from_quotes_not_later_ledger_event(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-07-12T10:00:00+08:00",
        amount=1000.0,
    )

    snapshot = build_current_valuation_snapshot(db)

    assert snapshot["as_of"] == "2026-07-12T10:00:00+08:00"
    assert snapshot["trade_date"] == "2026-07-10"


def test_valuation_snapshot_freezes_confirmed_same_day_close():
    class FakeDb:
        close = 24.58

        def list_latest_quotes_sync(self):
            return [
                {
                    "id": 1,
                    "symbol": "603659",
                    "asset_type": "stock",
                    "price": 24.6,
                    "quote_timestamp": "2026-07-10T14:57:03+08:00",
                }
            ]

        def list_quote_snapshots_sync(self):
            return []

        def get_ledger_entries_sync(self, limit=500, offset=0):
            return []

        def get_market_bar_on_date_sync(self, symbol, trade_date):
            assert symbol == "603659"
            assert trade_date == "2026-07-10"
            return {"close": self.close, "source": "market_bars"}

        def get_latest_market_bar_before_date_sync(self, symbol, trade_date):
            return {"close": 25.46, "trade_date": "2026-07-09"}

    db = FakeDb()
    first = build_current_valuation_snapshot(db, persist=False)
    db.close = 24.57
    second = build_current_valuation_snapshot(db, persist=False)

    assert first["quotes"][0]["observed_price"] == 24.6
    assert first["quotes"][0]["price"] == 24.58
    assert first["quotes"][0]["observed_timestamp"] == ("2026-07-10T14:57:03+08:00")
    assert first["quotes"][0]["quote_timestamp"] == ("2026-07-10T15:00:00+08:00")
    assert first["quotes"][0]["quote_source"] == "market_bar_close"
    assert first["quotes"][0]["quote_status"] == "confirmed"
    assert first["quotes"][0]["valuation_price_source"] == "market_bar_close"
    assert first["as_of"] == "2026-07-10T15:00:00+08:00"
    assert first["snapshot_id"] != second["snapshot_id"]


def test_valuation_snapshot_orders_mixed_timezone_timestamps_by_instant(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T15:00:00+08:00",
        fetch_run_id="run-earlier",
    )
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.7,
        volume=1200.0,
        timestamp="2026-07-10T08:00:00Z",
        fetch_run_id="run-later",
    )

    snapshot = build_current_valuation_snapshot(db)

    assert snapshot["quotes"][0]["price"] == 24.7
    assert snapshot["as_of"] == "2026-07-10T16:00:00+08:00"
    assert snapshot["metadata"]["ingestion_run_ids"] == ["run-later"]


def test_valuation_snapshot_fails_closed_without_persisted_quotes(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    snapshot = build_current_valuation_snapshot(db)

    assert snapshot["status"] == "missing"
    assert snapshot["quotes"] == []
    assert snapshot["metadata"]["runtime_cache_used"] is False


def test_valuation_snapshot_routes_separate_create_and_read(monkeypatch, tmp_path):
    from server.routes import portfolio as portfolio_routes

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=db),
    )
    router = portfolio_routes.create_router()
    create_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/portfolio/valuation-snapshots"
        and "POST" in route.methods
    )

    created = asyncio.run(create_route.endpoint())
    read_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/portfolio/valuation-snapshots/{snapshot_id}"
    )
    read = asyncio.run(read_route.endpoint(created["snapshot_id"]))

    assert read["snapshot_id"] == created["snapshot_id"]
    assert read["quotes"] == created["quotes"]
    assert read["metadata"] == created["metadata"]


def test_successful_quote_run_publishes_replayable_snapshot(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    run_id = "run-publish-snapshot"
    db.create_quote_fetch_run(
        run_id=run_id,
        started_at="2026-07-10T14:56:00+08:00",
        trigger="test",
        provider="test",
        asset_type="stock",
        symbol_count=1,
        status="running",
    )
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
        fetch_run_id=run_id,
    )

    finished = db.finish_quote_fetch_run(
        run_id=run_id,
        finished_at="2026-07-10T14:58:00+08:00",
        status="success",
        success_count=1,
        metadata={"trigger": "test"},
    )

    metadata = json.loads(finished["metadata_json"])
    snapshot_id = metadata["valuation_snapshot_id"]
    stored = db.get_valuation_snapshot_sync(snapshot_id)
    publication = db.get_runtime_control_sync("valuation_snapshot_publication")
    assert finished["status"] == "success"
    assert stored is not None
    assert publication["status"] == "ready"
    assert publication["snapshot_id"] == snapshot_id
    assert json.loads(stored["quotes_json"])[0]["fetch_run_id"] == run_id


def test_quote_run_fails_closed_when_snapshot_publication_fails(monkeypatch, tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    run_id = "run-publication-failure"
    db.create_quote_fetch_run(
        run_id=run_id,
        started_at="2026-07-10T14:56:00+08:00",
        trigger="test",
        provider="test",
        asset_type="stock",
        symbol_count=1,
        status="running",
    )
    monkeypatch.setattr(
        db,
        "publish_current_valuation_snapshot_sync",
        lambda: (_ for _ in ()).throw(RuntimeError("disk unavailable")),
    )

    finished = db.finish_quote_fetch_run(
        run_id=run_id,
        finished_at="2026-07-10T14:58:00+08:00",
        status="success",
        success_count=1,
        metadata={"trigger": "test"},
    )

    assert finished["status"] == "failed"
    assert "valuation snapshot publication failed" in finished["error_message"]
    assert (
        json.loads(finished["metadata_json"])["valuation_snapshot_publication"]
        == "failed"
    )


def test_ledger_commit_publishes_new_replayable_snapshot(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )

    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-07-10T09:00:00+08:00",
        amount=10000.0,
        asset_class="cash",
    )

    current = build_current_valuation_snapshot(db, persist=False)
    stored = db.get_valuation_snapshot_sync(current["snapshot_id"])
    assert stored is not None
    assert stored["ledger_cutoff_id"] == 1


def test_financial_read_fails_closed_when_facts_are_newer_than_publication(tmp_path):
    from server.routes.portfolio import _current_valuation_snapshot

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )
    published = db.publish_current_valuation_snapshot_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.7,
        volume=1200.0,
        timestamp="2026-07-10T14:58:03+08:00",
    )

    with pytest.raises(HTTPException) as exc_info:
        _current_valuation_snapshot(SimpleNamespace(db=db))

    assert exc_info.value.status_code == 503
    assert db.get_valuation_snapshot_sync(published["snapshot_id"]) is not None
