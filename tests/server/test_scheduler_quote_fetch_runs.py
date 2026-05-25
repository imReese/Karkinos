from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from core.events import MarketEvent
from core.types import AssetClass, BarFrequency, Symbol
from server.db import AppDatabase


class FakeBridge:
    def __init__(self) -> None:
        self.bound_bus = None

    def rebind(self, event_bus) -> None:
        self.bound_bus = event_bus


class FakeStrategy:
    def __init__(self) -> None:
        self.initialized_symbols = []
        self.market_events = []

    def on_init(self, symbols) -> None:
        self.initialized_symbols = list(symbols)

    def on_data(self, event) -> None:
        self.market_events.append(event)


def _market_event(
    symbol: str,
    asset_class: AssetClass = AssetClass.STOCK,
    price: Decimal = Decimal("12.5"),
) -> MarketEvent:
    return MarketEvent(
        timestamp=datetime(2026, 5, 23, 10, 0),
        symbol=Symbol(symbol),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("1000"),
        frequency=BarFrequency.DAILY,
        asset_class=asset_class,
    )


def _run_scheduler_once(
    monkeypatch,
    tmp_path,
    *,
    data_source: str = "akshare",
    watchlist: list[tuple[Symbol, AssetClass]] | None = None,
    events: list[MarketEvent] | None = None,
    snapshots: dict[tuple[str, AssetClass], dict] | None = None,
    poll_error: Exception | None = None,
) -> AppDatabase:
    from server import scheduler as scheduler_module

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    watchlist = watchlist or [(Symbol("600519"), AssetClass.STOCK)]
    events = events or []
    snapshots = snapshots or {}

    config = SimpleNamespace(
        data_source=data_source,
        live_poll_interval=0,
        initial_cash=Decimal("100000"),
    )
    runtime = SimpleNamespace(
        sources={
            data_source: object(),
            "akshare": object(),
        },
        watchlist=watchlist,
        instruments={},
        data_manager=SimpleNamespace(),
    )

    holder = {}

    class FakeLiveDataFeed:
        def __init__(self, source, event_bus, fallback_source=None) -> None:
            self.source = source
            self.event_bus = event_bus
            self.fallback_source = fallback_source

        def poll_all(self, current_watchlist):
            holder["scheduler"]._running.clear()
            assert current_watchlist == watchlist
            if poll_error is not None:
                raise poll_error
            return events

        def get_last_snapshot(self, symbol, asset_class=AssetClass.STOCK):
            return snapshots.get((str(symbol), asset_class), {})

    monkeypatch.setattr(
        scheduler_module,
        "create_runtime_context",
        lambda config: runtime,
    )
    monkeypatch.setattr(scheduler_module, "LiveDataFeed", FakeLiveDataFeed)
    monkeypatch.setattr(
        scheduler_module,
        "build_strategy",
        lambda config, bus: FakeStrategy(),
    )
    monkeypatch.setattr(
        scheduler_module.TradingScheduler,
        "_warmup_strategy",
        lambda self, data_manager, strategy: None,
    )
    monkeypatch.setattr(
        scheduler_module.TradingScheduler,
        "_is_market_open",
        staticmethod(lambda: True),
    )
    monkeypatch.setattr(
        scheduler_module,
        "rebuild_portfolio_from_ledger",
        lambda config, db, latest_quotes: None,
    )

    scheduler = scheduler_module.TradingScheduler(config, FakeBridge(), db=db)
    holder["scheduler"] = scheduler
    scheduler._running.set()
    scheduler._run_loop()
    return db


def test_scheduler_poll_success_records_quote_fetch_run(monkeypatch, tmp_path):
    event = _market_event("600519")
    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        events=[event],
        snapshots={
            ("600519", AssetClass.STOCK): {
                "timestamp": "2026-05-23T10:00:00",
                "source": "akshare",
            }
        },
    )

    runs = db.list_quote_fetch_runs()
    quotes = db.get_latest_quotes_sync()
    latest = db.get_latest_quote_sync("600519", asset_type="stock")

    assert len(runs) == 1
    assert runs[0]["trigger"] == "scheduler_poll"
    assert runs[0]["status"] == "success"
    assert runs[0]["finished_at"] is not None
    assert runs[0]["symbol_count"] == 1
    assert runs[0]["success_count"] == 1
    assert runs[0]["failure_count"] == 0
    assert runs[0]["cache_hit_count"] == 0
    metadata = json.loads(runs[0]["metadata_json"])
    assert metadata["provider"] == "akshare"
    assert metadata["provider_status"] == "live"
    assert quotes[0]["symbol"] == "600519"
    assert quotes[0]["captured_reason"] == "scheduler_poll"
    assert latest is not None
    assert latest["symbol"] == "600519"
    assert latest["asset_type"] == "stock"
    assert latest["price"] == 12.5
    assert latest["provider_name"] == "akshare"
    assert latest["provider_status"] == "live"
    assert latest["quote_status"] == "live"
    assert latest["captured_reason"] == "scheduler_poll"


def test_scheduler_poll_partial_success_records_quote_fetch_run(monkeypatch, tmp_path):
    watchlist = [
        (Symbol("600519"), AssetClass.STOCK),
        (Symbol("510300"), AssetClass.FUND),
    ]
    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        watchlist=watchlist,
        events=[_market_event("600519")],
    )

    run = db.list_quote_fetch_runs()[0]
    metadata = json.loads(run["metadata_json"])

    assert run["status"] == "partial_success"
    assert run["symbol_count"] == 2
    assert run["success_count"] == 1
    assert run["failure_count"] == 1
    assert metadata["provider_status"] == "partial"
    assert metadata["success_symbols"] == ["600519"]
    assert metadata["failed_symbols"] == ["510300"]


def test_scheduler_poll_exception_finishes_failed_quote_fetch_run(monkeypatch, tmp_path):
    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        poll_error=RuntimeError("provider exploded"),
    )

    run = db.list_quote_fetch_runs()[0]
    latest = db.list_latest_quotes_sync()
    metadata = json.loads(run["metadata_json"])

    assert run["status"] == "failed"
    assert run["finished_at"] is not None
    assert run["success_count"] == 0
    assert run["failure_count"] == 1
    assert run["error_message"] == "provider exploded"
    assert metadata["provider_status"] == "failed"
    assert latest == []
