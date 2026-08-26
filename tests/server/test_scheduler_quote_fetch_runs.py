from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from core.events import MarketEvent, OrderEvent, OrderIntentEvent, SignalEvent
from core.types import AssetClass, BarFrequency, OrderSide, OrderType, Symbol
from data.store import DataStore
from server.db import AppDatabase
from server.services.valuation_snapshot import build_current_valuation_snapshot


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


def _scheduler_config(**overrides):
    values = {
        "data_source": "akshare",
        "live_poll_interval": 0,
        "initial_cash": Decimal("100000"),
        "start_date": "2026-01-01",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _scheduler_runtime(
    *,
    data_source: str = "akshare",
    watchlist: list[tuple[Symbol, AssetClass]] | None = None,
    instruments: dict | None = None,
    data_manager=None,
    sources: dict | None = None,
):
    return SimpleNamespace(
        sources=(
            sources
            if sources is not None
            else {
                data_source: object(),
                "akshare": object(),
            }
        ),
        watchlist=(
            [(Symbol("600519"), AssetClass.STOCK)] if watchlist is None else watchlist
        ),
        instruments={} if instruments is None else instruments,
        data_manager=data_manager if data_manager is not None else SimpleNamespace(),
    )


def _empty_fund_nav_sync(config, db, watchlist, latest_quotes):
    return SimpleNamespace(
        refreshed=[],
        skipped=[],
        failed={},
        quotes={},
    )


def _stub_scheduler_dependencies(
    monkeypatch,
    scheduler_module,
    *,
    runtime,
    strategy_factory=None,
    market_open: bool = True,
    rebuild_portfolio=None,
    fund_nav_sync=None,
    warmup_strategy=None,
    now: datetime | None = None,
):
    monkeypatch.setattr(
        scheduler_module,
        "create_runtime_context",
        lambda config: runtime,
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_strategy",
        lambda config, bus: (
            strategy_factory(bus) if strategy_factory is not None else FakeStrategy()
        ),
    )
    monkeypatch.setattr(
        scheduler_module.TradingScheduler,
        "_warmup_strategy",
        warmup_strategy or (lambda self, data_manager, strategy: None),
    )
    if now is not None:
        monkeypatch.setattr(scheduler_module, "scheduler_now", lambda: now)
    monkeypatch.setattr(
        scheduler_module.TradingScheduler,
        "_is_market_open",
        staticmethod(lambda: market_open),
    )
    if rebuild_portfolio is not None:
        monkeypatch.setattr(
            scheduler_module,
            "rebuild_portfolio_from_ledger",
            rebuild_portfolio,
        )
    monkeypatch.setattr(
        scheduler_module,
        "refresh_fund_nav_quotes",
        fund_nav_sync or _empty_fund_nav_sync,
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
    strategy_factory=None,
    fund_nav_sync=None,
    sources: dict | None = None,
    warmup_strategy=None,
    now: datetime | None = None,
    configure_database=None,
    observe_scheduler=None,
) -> AppDatabase:
    from server import scheduler as scheduler_module

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    if configure_database is not None:
        configure_database(db)
    watchlist = watchlist or [(Symbol("600519"), AssetClass.STOCK)]
    events = events or []
    snapshots = snapshots or {}
    batch_now = (
        now
        if now is not None
        else (
            max(event.timestamp for event in events) + timedelta(seconds=1)
            if events
            else None
        )
    )

    config = _scheduler_config(data_source=data_source)
    runtime = _scheduler_runtime(
        data_source=data_source,
        watchlist=watchlist,
        sources=sources,
    )

    holder = {}

    class FakeLiveDataFeed:
        def __init__(
            self,
            source,
            event_bus,
            fallback_source=None,
            prefer_fallback_asset_classes=None,
        ) -> None:
            self.source = source
            self.event_bus = event_bus
            self.fallback_source = fallback_source
            self.prefer_fallback_asset_classes = prefer_fallback_asset_classes

        def poll_all(self, current_watchlist):
            assert current_watchlist == watchlist
            if poll_error is not None:
                raise poll_error
            return events

        def get_last_snapshot(self, symbol, asset_class=AssetClass.STOCK):
            explicit = snapshots.get((str(symbol), asset_class))
            if explicit is not None:
                return explicit
            event = next(
                (
                    item
                    for item in events
                    if item.symbol == symbol and item.asset_class == asset_class
                ),
                None,
            )
            if event is None:
                return {}
            return {
                "timestamp": event.timestamp.isoformat(),
                "source": data_source,
                "provider_name": data_source,
                "previous_close": float(event.close) - 1,
                "previous_close_date": (
                    event.timestamp.date() - timedelta(days=1)
                ).isoformat(),
            }

        def close(self) -> None:
            pass

    monkeypatch.setattr(scheduler_module, "LiveDataFeed", FakeLiveDataFeed)
    _stub_scheduler_dependencies(
        monkeypatch,
        scheduler_module,
        runtime=runtime,
        strategy_factory=strategy_factory,
        fund_nav_sync=fund_nav_sync,
        warmup_strategy=warmup_strategy,
        now=batch_now,
    )

    scheduler = scheduler_module.TradingScheduler(config, FakeBridge(), db=db)
    holder["scheduler"] = scheduler
    scheduler.wait_for_scheduler_stop = lambda timeout: scheduler._running.clear()
    scheduler._running.set()
    scheduler._run_loop()
    if observe_scheduler is not None:
        observe_scheduler(scheduler)
    return db


def test_scheduler_poll_success_records_quote_fetch_run(monkeypatch, tmp_path):
    event = _market_event("600519")
    observed_runtime_quotes = {}
    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        events=[event],
        snapshots={
            ("600519", AssetClass.STOCK): {
                "timestamp": "2026-05-23T10:00:00",
                "source": "akshare",
                "display_name": "贵州茅台",
                "previous_close": 11.5,
                "previous_close_date": "2026-05-22",
            }
        },
        observe_scheduler=lambda scheduler: observed_runtime_quotes.update(
            scheduler.latest_quotes
        ),
    )

    runs = db.list_quote_fetch_runs()
    quotes = db.get_latest_quotes_sync()
    latest = db.get_latest_quote_sync("600519", asset_type="stock")
    instrument = db.get_instrument_metadata_sync("600519", "stock")

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
    assert quotes[0]["fetch_run_id"] == runs[0]["run_id"]
    assert latest is not None
    assert latest["symbol"] == "600519"
    assert latest["asset_type"] == "stock"
    assert latest["price"] == 12.5
    assert latest["provider_name"] == "akshare"
    assert latest["provider_status"] == "live"
    assert latest["quote_status"] == "live"
    assert latest["captured_reason"] == "scheduler_poll"
    assert latest["fetch_run_id"] == runs[0]["run_id"]
    assert instrument is not None
    assert instrument["display_name"] == "贵州茅台"
    assert instrument["provider_name"] == "akshare"
    assert observed_runtime_quotes["600519"]["quote_status"] == "live"
    assert observed_runtime_quotes["600519"]["quote_source"] == "akshare"


def test_scheduler_signal_persists_action_task_without_notifier(
    monkeypatch,
    tmp_path,
):
    class SignalStrategy:
        def __init__(self, event_bus) -> None:
            self.event_bus = event_bus
            self.initialized_symbols = []

        def on_init(self, symbols) -> None:
            self.initialized_symbols = list(symbols)

        def on_data(self, event) -> None:
            self.event_bus.publish(
                SignalEvent(
                    timestamp=event.timestamp,
                    strategy_id="dual_ma",
                    symbol=event.symbol,
                    target_weight=Decimal("0.20"),
                    price=event.close,
                )
            )

    event = _market_event("600519")
    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        events=[event],
        strategy_factory=lambda bus: SignalStrategy(bus),
        snapshots={
            ("600519", AssetClass.STOCK): {
                "timestamp": "2026-05-23T10:00:00",
                "source": "akshare",
                "display_name": "贵州茅台",
                "previous_close": 11.5,
                "previous_close_date": "2026-05-22",
            }
        },
    )

    signals = asyncio.run(db.get_latest_signals(limit=5))
    actions = db.get_action_tasks_sync()

    assert signals[0]["strategy_id"] == "dual_ma"
    assert signals[0]["symbol"] == "600519"
    assert signals[0]["direction"] == "buy"
    assert actions[0]["source_signal_id"] == signals[0]["id"]
    assert actions[0]["direction"] == "buy"
    assert actions[0]["title"] == "建议增持 600519"
    assert actions[0]["manual_confirmation_status"] == "awaiting_risk_gate"
    assert db.get_risk_decisions_sync() == []
    assert db.list_manual_orders_sync() == []
    assert db.list_orders_sync() == []


def test_scheduler_action_persistence_failure_leaves_no_execution_side_effects(
    monkeypatch,
    tmp_path,
) -> None:
    failed_action_writes = []

    def configure_database(db: AppDatabase) -> None:
        db.insert_ledger_entry_sync(
            entry_type="cash_deposit",
            timestamp="2026-05-23T09:00:00+08:00",
            amount=100000.0,
            created_at="2026-05-23T09:00:01+08:00",
        )

    def fail_action_persistence(self, **kwargs) -> None:
        failed_action_writes.append(dict(kwargs))
        raise RuntimeError("injected action persistence failure")

    def publish_parallel_events(scheduler) -> None:
        event_bus = scheduler._event_bus
        assert event_bus is not None
        timestamp = datetime(2026, 5, 23, 10, 0)
        event_bus.publish(
            SignalEvent(
                timestamp=timestamp,
                strategy_id="action_write_failure",
                symbol=Symbol("600519"),
                target_weight=Decimal("0.20"),
                price=Decimal("12.5"),
            )
        )
        event_bus.publish(
            OrderIntentEvent(
                timestamp=timestamp,
                intent_id="INTENT-ACTION-WRITE-FAILURE",
                strategy_id="action_write_failure",
                symbol=Symbol("600519"),
                side=OrderSide.BUY,
                target_weight=Decimal("0.20"),
                quantity=Decimal("100"),
                reference_price=Decimal("12.5"),
                asset_class=AssetClass.STOCK,
            )
        )
        event_bus.drain()

    monkeypatch.setattr(
        AppDatabase,
        "upsert_action_task_sync",
        fail_action_persistence,
    )
    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        events=[],
        configure_database=configure_database,
        observe_scheduler=publish_parallel_events,
    )

    signals = asyncio.run(db.get_latest_signals(limit=5))
    assert len(failed_action_writes) == 1
    assert len(signals) == 1
    assert signals[0]["strategy_id"] == "action_write_failure"
    assert db.get_action_tasks_sync() == []
    assert db.get_risk_decisions_sync() == []
    assert db.list_manual_orders_sync() == []
    assert db.list_orders_sync() == []


def test_scheduler_discards_strategy_output_created_during_warmup(
    monkeypatch,
    tmp_path,
) -> None:
    class WarmupSignalStrategy:
        def __init__(self, event_bus) -> None:
            self.event_bus = event_bus

        def on_init(self, symbols) -> None:
            pass

        def on_data(self, event) -> None:
            self.event_bus.publish(
                SignalEvent(
                    timestamp=event.timestamp,
                    strategy_id="warmup_only",
                    symbol=event.symbol,
                    target_weight=Decimal("0.20"),
                    price=event.close,
                )
            )

    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        events=[],
        strategy_factory=WarmupSignalStrategy,
        warmup_strategy=lambda _self, _manager, strategy: strategy.on_data(
            _market_event("600519")
        ),
    )

    assert asyncio.run(db.get_latest_signals(limit=5)) == []
    assert db.get_action_tasks_sync() == []


def test_scheduler_syncs_default_market_indices_without_strategy_watchlist(
    monkeypatch,
    tmp_path,
):
    class IndexSource:
        def __init__(self) -> None:
            self.calls = []

        def fetch_latest(self, symbol, asset_class):
            self.calls.append((str(symbol), asset_class))
            if asset_class is not AssetClass.INDEX:
                return None
            return {
                "price": 3120.5,
                "volume": "12345",
                "timestamp": "2026-05-23T10:00:00",
                "quote_source": "akshare_index_spot",
                "provider_name": "akshare",
                "display_name": "上证指数",
                "daily_change": "10.5",
                "daily_change_pct": "0.34",
            }

    source = IndexSource()
    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        watchlist=[(Symbol("600519"), AssetClass.STOCK)],
        events=[],
        sources={"akshare": source},
    )

    assert source.calls
    assert all(asset_class is AssetClass.INDEX for _, asset_class in source.calls)
    latest = db.get_latest_quote_sync("000001", asset_type="index")
    metadata = db.get_instrument_metadata_sync("000001", "index")
    run = db.list_quote_fetch_runs()[0]

    assert latest is not None
    assert latest["symbol"] == "000001"
    assert latest["asset_type"] == "index"
    assert latest["price"] == 3120.5
    assert latest["change"] == 10.5
    assert latest["change_percent"] == 0.34
    assert latest["captured_reason"] == "scheduler_market_index_sync"
    assert metadata is not None
    assert metadata["display_name"] == "上证指数"
    assert run["symbol_count"] == 1
    assert json.loads(run["metadata_json"])["symbols"] == ["600519"]


def test_scheduler_rejects_strategy_order_that_bypasses_pre_trade_gate(
    monkeypatch,
    tmp_path,
):
    class PaperOrderStrategy:
        def __init__(self, event_bus) -> None:
            self.event_bus = event_bus
            self.initialized_symbols = []

        def on_init(self, symbols) -> None:
            self.initialized_symbols = list(symbols)

        def on_data(self, event) -> None:
            self.event_bus.publish(
                OrderEvent(
                    timestamp=event.timestamp,
                    order_id="ORD-SCHED-PAPER-1",
                    symbol=event.symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=Decimal("100"),
                    price=event.close,
                    intent_id="INTENT-SCHED-1",
                    risk_decision_id="RISK-SCHED-1",
                    execution_mode="paper",
                )
            )

    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        events=[_market_event("600519", price=Decimal("123.45"))],
        strategy_factory=PaperOrderStrategy,
    )

    assert db.get_order_sync("ORD-SCHED-PAPER-1") is None
    assert db.list_fills_sync(order_id="ORD-SCHED-PAPER-1") == []
    assert db.list_quote_fetch_runs()[0]["status"] == "success"


def test_scheduler_rejects_strategy_intent_outside_action_evidence_boundary(
    monkeypatch,
    tmp_path,
) -> None:
    class IntentStrategy:
        def __init__(self, event_bus) -> None:
            self.event_bus = event_bus

        def on_init(self, symbols) -> None:
            pass

        def on_data(self, event) -> None:
            self.event_bus.publish(
                OrderIntentEvent(
                    timestamp=event.timestamp,
                    intent_id="INTENT-SCHED-GATED-1",
                    strategy_id="gated_strategy",
                    symbol=event.symbol,
                    side=OrderSide.BUY,
                    target_weight=Decimal("0.10"),
                    quantity=Decimal("100"),
                    reference_price=event.close,
                    asset_class=event.asset_class,
                )
            )

    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        events=[_market_event("600519", price=Decimal("123.45"))],
        strategy_factory=IntentStrategy,
    )

    assert asyncio.run(db.get_latest_signals(limit=5)) == []
    assert db.get_action_tasks_sync() == []
    assert db.get_risk_decisions_sync() == []
    assert db.list_manual_orders_sync() == []
    assert db.list_orders_sync() == []
    assert db.list_quote_fetch_runs()[0]["status"] == "success"


def test_scheduler_poll_partial_success_records_quote_fetch_run(monkeypatch, tmp_path):
    watchlist = [
        (Symbol("600519"), AssetClass.STOCK),
        (Symbol("510300"), AssetClass.FUND),
    ]
    strategy = FakeStrategy()
    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        watchlist=watchlist,
        events=[_market_event("600519")],
        strategy_factory=lambda _bus: strategy,
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
    assert strategy.market_events == []


def test_scheduler_syncs_fund_nav_quotes_before_live_poll(monkeypatch, tmp_path):
    from server import scheduler as scheduler_module

    calls = []

    def fake_refresh_fund_nav_quotes(config, db, watchlist, latest_quotes):
        calls.append(
            {
                "data_source": config.data_source,
                "watchlist": list(watchlist),
                "latest_quotes": dict(latest_quotes),
            }
        )
        return SimpleNamespace(
            refreshed=["019999"],
            skipped=[],
            failed={},
            quotes={
                "019999": {
                    "price": 2.2527,
                    "timestamp": "2026-06-12 15:00",
                    "asset_class": "fund",
                    "quote_source": "eastmoney_fund_estimate",
                    "provider_name": "akshare",
                    "quote_status": "live",
                    "provider_status": "live",
                    "captured_reason": "fund_nav_sync",
                    "nav_date": "2026-06-12",
                }
            },
        )

    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        watchlist=[(Symbol("019999"), AssetClass.FUND)],
        events=[],
        fund_nav_sync=fake_refresh_fund_nav_quotes,
    )

    assert calls == [
        {
            "data_source": "akshare",
            "watchlist": [(Symbol("019999"), AssetClass.FUND)],
            "latest_quotes": {},
        }
    ]
    assert db.list_quote_fetch_runs()[0]["status"] == "failed"


def test_scheduler_does_not_send_intraday_fund_estimates_to_strategy(
    monkeypatch, tmp_path
):
    strategy = FakeStrategy()
    observed_runtime_quotes = {}
    stock_event = _market_event("600519", AssetClass.STOCK)
    fund_event = _market_event("019999", AssetClass.FUND, Decimal("2.2527"))

    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        watchlist=[
            (Symbol("600519"), AssetClass.STOCK),
            (Symbol("019999"), AssetClass.FUND),
        ],
        events=[stock_event, fund_event],
        snapshots={
            ("600519", AssetClass.STOCK): {
                "timestamp": "2026-06-12T10:00:00+08:00",
                "quote_source": "fixture_stock",
            },
            ("019999", AssetClass.FUND): {
                "timestamp": "2026-06-12T10:00:00+08:00",
                "quote_source": "sina_fund_estimate",
                "provider_name": "sina",
                "nav_date": "2026-06-11",
            },
        },
        strategy_factory=lambda _bus: strategy,
        observe_scheduler=lambda scheduler: observed_runtime_quotes.update(
            scheduler.latest_quotes
        ),
    )

    assert strategy.market_events == []
    # The quote is still persisted for portfolio display even though strategy skips it.
    latest_fund = db.get_latest_quote_sync("019999", asset_type="fund")
    assert latest_fund is not None
    assert latest_fund["quote_source"] == "sina_fund_estimate"
    run_metadata = json.loads(db.list_quote_fetch_runs()[0]["metadata_json"])
    assert run_metadata["quote_status_counts"] == {"estimated": 1, "live": 1}
    assert observed_runtime_quotes == {}


def test_scheduler_poll_exception_finishes_failed_quote_fetch_run(
    monkeypatch, tmp_path
):
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


def test_scheduler_blocks_strategy_and_runtime_quote_on_ingestion_stage_failure(
    monkeypatch,
    tmp_path,
) -> None:
    from server import scheduler as scheduler_module

    event = _market_event("600519")
    strategy = FakeStrategy()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    runtime = _scheduler_runtime()
    holder = {}

    class FakeLiveDataFeed:
        def __init__(
            self,
            source,
            event_bus,
            fallback_source=None,
            prefer_fallback_asset_classes=None,
        ) -> None:
            pass

        def poll_all(self, current_watchlist):
            holder["scheduler"]._running.clear()
            return [event]

        def get_last_snapshot(self, symbol, asset_class=AssetClass.STOCK):
            return {
                "timestamp": "2026-05-23T10:00:00",
                "source": "akshare",
            }

        def close(self) -> None:
            pass

    def fail_quote_ingestion(_command):
        raise RuntimeError("quote ingestion staging unavailable")

    monkeypatch.setattr(scheduler_module, "LiveDataFeed", FakeLiveDataFeed)
    monkeypatch.setattr(db, "persist_quote_ingestion_sync", fail_quote_ingestion)
    _stub_scheduler_dependencies(
        monkeypatch,
        scheduler_module,
        runtime=runtime,
        strategy_factory=lambda _bus: strategy,
        now=event.timestamp + timedelta(seconds=1),
    )
    scheduler = scheduler_module.TradingScheduler(
        _scheduler_config(),
        FakeBridge(),
        db=db,
    )
    holder["scheduler"] = scheduler
    scheduler._running.set()

    scheduler._run_loop()

    run = db.list_quote_fetch_runs()[0]
    assert run["status"] == "failed"
    assert run["error_message"] == "quote ingestion staging unavailable"
    assert scheduler.latest_quotes == {}
    assert strategy.market_events == []


def test_scheduler_rejects_stale_provider_snapshot_before_publication(
    monkeypatch,
    tmp_path,
) -> None:
    event = _market_event("600519")
    strategy = FakeStrategy()

    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        events=[event],
        strategy_factory=lambda _bus: strategy,
        snapshots={
            ("600519", AssetClass.STOCK): {
                "timestamp": event.timestamp.isoformat(),
                "source": "akshare",
            }
        },
        now=event.timestamp + timedelta(hours=1),
    )

    run = db.list_quote_fetch_runs()[0]
    assert run["status"] == "failed"
    assert run["error_message"] == "scheduler quote is stale: 600519"
    assert db.list_quote_snapshots_sync() == []
    assert db.get_latest_quotes_sync() == []
    assert strategy.market_events == []


def test_scheduler_rejects_quote_without_provider_provenance(
    monkeypatch,
    tmp_path,
) -> None:
    event = _market_event("600519")

    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        events=[event],
        snapshots={
            ("600519", AssetClass.STOCK): {
                "timestamp": event.timestamp.isoformat(),
            }
        },
    )

    run = db.list_quote_fetch_runs()[0]
    assert run["status"] == "failed"
    assert run["error_message"] == "scheduler quote provenance missing: 600519"
    assert db.get_latest_quotes_sync() == []


def test_scheduler_rejects_unhealthy_provider_snapshot(
    monkeypatch,
    tmp_path,
) -> None:
    event = _market_event("600519")

    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        events=[event],
        snapshots={
            ("600519", AssetClass.STOCK): {
                "timestamp": event.timestamp.isoformat(),
                "source": "akshare",
                "provider_status": "error",
            }
        },
    )

    run = db.list_quote_fetch_runs()[0]
    assert run["status"] == "failed"
    assert run["error_message"] == (
        "scheduler quote provider is not healthy: 600519 (error)"
    )
    assert db.get_latest_quotes_sync() == []


def test_scheduler_does_not_materialize_partially_staged_quote_batch(
    monkeypatch,
    tmp_path,
) -> None:
    call_count = 0

    def configure_database(db) -> None:
        original = db.persist_quote_ingestion_sync

        def fail_second_stage(command):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("second quote staging failed")
            return original(command)

        monkeypatch.setattr(db, "persist_quote_ingestion_sync", fail_second_stage)

    db = _run_scheduler_once(
        monkeypatch,
        tmp_path,
        watchlist=[
            (Symbol("600519"), AssetClass.STOCK),
            (Symbol("600001"), AssetClass.STOCK),
        ],
        events=[_market_event("600519"), _market_event("600001")],
        configure_database=configure_database,
    )

    run = db.list_quote_fetch_runs()[0]
    assert call_count == 2
    assert run["status"] == "failed"
    assert run["error_message"] == "second quote staging failed"
    assert db.list_quote_snapshots_sync() == []
    assert db.get_latest_quotes_sync() == []


def test_scheduler_backfills_historical_bars_once_per_effective_close_date():
    from server.scheduler import TradingScheduler

    config = _scheduler_config(live_poll_interval=120)
    scheduler = TradingScheduler(config, FakeBridge())
    scheduler._watchlist = [(Symbol("600001"), AssetClass.STOCK)]
    calls = []

    class FakeManager:
        def get_bars(self, *args, **kwargs):
            calls.append((args, kwargs))
            return SimpleNamespace(total_bars=2)

    manager = FakeManager()

    scheduler._maybe_backfill_historical_bars(
        manager,
        now=datetime(2026, 5, 29, 16, 0),
    )
    scheduler._maybe_backfill_historical_bars(
        manager,
        now=datetime(2026, 5, 29, 16, 5),
    )
    scheduler._maybe_backfill_historical_bars(
        manager,
        now=datetime(2026, 5, 30, 10, 0),
    )
    scheduler._maybe_backfill_historical_bars(
        manager,
        now=datetime(2026, 5, 30, 16, 0),
    )

    assert len(calls) == 2
    first_args, first_kwargs = calls[0]
    assert first_args[0] == Symbol("600001")
    assert first_kwargs["frequency"] == BarFrequency.DAILY
    assert first_kwargs["asset_class"] == AssetClass.STOCK
    assert first_kwargs["allow_remote_refresh"] is True
    assert first_kwargs["refresh_ttl_seconds"] == 0
    assert first_kwargs["degrade_to_cache"] is True
    assert first_kwargs["end"].date().isoformat() == "2026-05-29"
    assert calls[1][1]["end"].date().isoformat() == "2026-05-30"


def test_scheduler_backfill_publishes_the_changed_valuation_identity(tmp_path):
    from server.scheduler import TradingScheduler

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_latest_quote_sync(
        symbol="019999",
        asset_type="fund",
        price=1.126,
        quote_timestamp="2026-05-29T10:30:00+08:00",
        quote_source="eastmoney_fund_estimate",
        provider_name="akshare",
        quote_status="live",
    )
    published_before = db.publish_current_valuation_snapshot_sync()
    store = DataStore(tmp_path)

    class PersistingManager:
        def get_bars(self, symbol, *args, **kwargs):
            frame = pd.DataFrame(
                [
                    {
                        "timestamp": "2026-05-29T00:00:00",
                        "open": 1.12,
                        "high": 1.13,
                        "low": 1.11,
                        "close": 1.126,
                        "volume": 1000,
                    }
                ]
            )
            store.save_bars(
                symbol,
                BarFrequency.DAILY,
                frame,
                provider_name="akshare",
                data_source="akshare",
            )
            return SimpleNamespace(total_bars=1)

    scheduler = TradingScheduler(_scheduler_config(), FakeBridge(), db=db)
    scheduler._watchlist = [(Symbol("019999"), AssetClass.FUND)]

    scheduler._maybe_backfill_historical_bars(
        PersistingManager(),
        now=datetime(2026, 5, 29, 16, 0),
    )

    publication = db.get_runtime_control_sync("valuation_snapshot_publication")
    current = build_current_valuation_snapshot(db, persist=False)
    assert publication is not None
    assert publication["snapshot_id"] == current["snapshot_id"]
    assert publication["snapshot_id"] != published_before["snapshot_id"]
    assert current["quotes"][0]["quote_source"] == "market_bar_close"


def test_scheduler_retries_snapshot_publication_without_refetching_bars():
    from server.scheduler import TradingScheduler

    class FlakyPublicationDb:
        def __init__(self) -> None:
            self.calls = 0

        def publish_current_valuation_snapshot_sync(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("database temporarily busy")
            return {"snapshot_id": "valuation-recovered"}

    class CountingManager:
        def __init__(self) -> None:
            self.calls = 0

        def get_bars(self, *args, **kwargs):
            self.calls += 1
            return SimpleNamespace(total_bars=1)

    db = FlakyPublicationDb()
    manager = CountingManager()
    scheduler = TradingScheduler(_scheduler_config(), FakeBridge(), db=db)
    scheduler._watchlist = [(Symbol("600001"), AssetClass.STOCK)]

    scheduler._maybe_backfill_historical_bars(
        manager,
        now=datetime(2026, 5, 29, 16, 0),
    )
    assert scheduler._pending_valuation_publication_reason is not None

    scheduler._maybe_backfill_historical_bars(
        manager,
        now=datetime(2026, 5, 29, 16, 5),
    )

    assert manager.calls == 1
    assert db.calls == 2
    assert scheduler._pending_valuation_publication_reason is None


def test_scheduler_post_close_valuation_refresh_runs_once_per_trade_date(
    monkeypatch, tmp_path
):
    from server import scheduler as scheduler_module

    config = _scheduler_config(live_poll_interval=120)
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    scheduler = scheduler_module.TradingScheduler(config, FakeBridge(), db=db)
    scheduler._watchlist = [
        (Symbol("600001"), AssetClass.STOCK),
        (Symbol("019999"), AssetClass.FUND),
    ]
    fund_sync_calls = []
    bar_calls = []

    def fake_refresh_fund_nav_quotes(
        config,
        db,
        watchlist,
        latest_quotes,
        *,
        confirmation_only=False,
    ):
        fund_sync_calls.append(
            (list(watchlist), dict(latest_quotes), confirmation_only)
        )
        return SimpleNamespace(
            refreshed=["019999"],
            skipped=[],
            failed={},
            quotes={
                "019999": {
                    "price": 2.2527,
                    "timestamp": "2026-06-17 15:30",
                    "asset_class": "fund",
                }
            },
        )

    class FakeManager:
        def get_bars(self, *args, **kwargs):
            bar_calls.append((args, kwargs))
            return SimpleNamespace(total_bars=1)

    monkeypatch.setattr(
        scheduler_module,
        "refresh_fund_nav_quotes",
        fake_refresh_fund_nav_quotes,
    )

    manager = FakeManager()
    before_cutoff = datetime(2026, 6, 17, 15, 30)
    stock_cutoff = datetime(2026, 6, 17, 16, 0)
    fund_cutoff = datetime(2026, 6, 17, 21, 30)

    assert (
        scheduler._maybe_refresh_post_close_valuation_data(
            manager,
            now=before_cutoff,
        )
        is False
    )
    assert (
        scheduler._maybe_refresh_post_close_valuation_data(
            manager,
            now=stock_cutoff,
        )
        is True
    )
    assert (
        scheduler._maybe_refresh_post_close_valuation_data(
            manager,
            now=datetime(2026, 6, 17, 16, 30),
        )
        is False
    )
    assert (
        scheduler._maybe_refresh_post_close_valuation_data(
            manager,
            now=fund_cutoff,
        )
        is True
    )

    assert len(fund_sync_calls) == 1
    assert fund_sync_calls[0][2] is True
    assert len(bar_calls) == 2
    assert {call[0][0] for call in bar_calls} == {
        Symbol("600001"),
        Symbol("019999"),
    }
    assert {call[1]["end"].date().isoformat() for call in bar_calls} == {"2026-06-17"}


def test_scheduler_waits_until_fixed_post_close_refresh_time(monkeypatch, tmp_path):
    from server import scheduler as scheduler_module

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    config = _scheduler_config(live_poll_interval=120)
    runtime = _scheduler_runtime(
        watchlist=[(Symbol("600001"), AssetClass.STOCK)],
    )
    market_refresh_calls = []
    stop_waits = []
    now_values = iter(
        [
            datetime(2026, 6, 17, 15, 30),
            datetime(2026, 6, 17, 16, 0),
        ]
    )

    class FakeLiveDataFeed:
        def __init__(
            self,
            source,
            event_bus,
            fallback_source=None,
            prefer_fallback_asset_classes=None,
        ) -> None:
            pass

        def close(self) -> None:
            pass

    class FakeStopEvent:
        def set(self):
            pass

        def wait(self, timeout=None):
            stop_waits.append(timeout)
            if len(stop_waits) >= 2:
                holder["scheduler"]._running.clear()
            return False

    monkeypatch.setattr(scheduler_module, "LiveDataFeed", FakeLiveDataFeed)
    _stub_scheduler_dependencies(
        monkeypatch,
        scheduler_module,
        runtime=runtime,
        market_open=False,
    )
    monkeypatch.setattr(
        scheduler_module.TradingScheduler,
        "_maybe_backfill_historical_bars",
        lambda self, data_manager, now=None: market_refresh_calls.append(now),
    )
    monkeypatch.setattr(
        scheduler_module.TradingScheduler,
        "_sync_fund_nav_quotes",
        lambda self: None,
    )

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = next(now_values)
            if tz is not None:
                return current.replace(tzinfo=tz)
            return current

    monkeypatch.setattr(scheduler_module, "datetime", FakeDateTime)

    holder = {}
    scheduler = scheduler_module.TradingScheduler(config, FakeBridge(), db=db)
    holder["scheduler"] = scheduler
    scheduler._stop_requested = FakeStopEvent()
    scheduler._running.set()
    scheduler._run_loop()

    assert stop_waits == [30, 30]
    assert market_refresh_calls == [datetime(2026, 6, 17, 16, 0)]


def test_scheduler_strategy_warmup_does_not_fetch_remote_bars(monkeypatch):
    from server import scheduler as scheduler_module

    config = _scheduler_config(live_poll_interval=120)
    scheduler = scheduler_module.TradingScheduler(config, FakeBridge())
    scheduler._watchlist = [(Symbol("019999"), AssetClass.FUND)]
    calls = []

    class FakeManager:
        def get_bars(self, *args, **kwargs):
            calls.append((args, kwargs))
            assert kwargs["allow_remote_refresh"] is False
            assert kwargs["degrade_to_cache"] is True
            return []

    monkeypatch.setattr(
        scheduler_module.TradingScheduler,
        "_is_market_open",
        staticmethod(lambda: True),
    )

    scheduler._warmup_strategy(FakeManager(), FakeStrategy())

    assert calls
    assert calls[0][0][0] == Symbol("019999")
    assert calls[0][1]["asset_class"] == AssetClass.FUND


def test_scheduler_runs_controlled_session_pause_callback_fail_closed() -> None:
    from server.scheduler import TradingScheduler

    calls: list[str] = []
    scheduler = TradingScheduler(
        _scheduler_config(),
        FakeBridge(),
        controlled_session_pause_runner=lambda: (
            calls.append("evaluated")
            or {
                "evaluated_count": 1,
                "paused_count": 1,
                "failure_count": 0,
                "broker_submission_enabled": False,
            }
        ),
    )

    result = scheduler._evaluate_controlled_session_pauses()

    assert calls == ["evaluated"]
    assert result is not None and result["paused_count"] == 1
    assert result["broker_submission_enabled"] is False

    scheduler._controlled_session_pause_runner = lambda: (_ for _ in ()).throw(
        RuntimeError("provider unavailable")
    )
    failed = scheduler._evaluate_controlled_session_pauses()
    assert failed == {
        "status": "failed",
        "failure_count": 1,
        "broker_submission_enabled": False,
    }


def test_scheduler_waits_between_poll_iterations(monkeypatch, tmp_path):
    from server import scheduler as scheduler_module

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    config = _scheduler_config(live_poll_interval=0.2)
    runtime = _scheduler_runtime(
        watchlist=[(Symbol("600001"), AssetClass.STOCK)],
    )
    calls = []
    feed_closed = threading.Event()

    class FakeLiveDataFeed:
        def __init__(
            self,
            source,
            event_bus,
            fallback_source=None,
            prefer_fallback_asset_classes=None,
        ) -> None:
            pass

        def poll_all(self, current_watchlist):
            calls.append(tuple(current_watchlist))
            return []

        def close(self) -> None:
            feed_closed.set()

    monkeypatch.setattr(scheduler_module, "LiveDataFeed", FakeLiveDataFeed)
    _stub_scheduler_dependencies(
        monkeypatch,
        scheduler_module,
        runtime=runtime,
    )

    scheduler = scheduler_module.TradingScheduler(config, FakeBridge(), db=db)
    scheduler.start()
    try:
        deadline = time.monotonic() + 1
        while not calls and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.05)
    finally:
        scheduler.stop()

    assert calls == [((Symbol("600001"), AssetClass.STOCK),)]
    assert feed_closed.is_set()


def test_scheduler_stop_timeout_blocks_overlapping_worker_generation(
    monkeypatch,
) -> None:
    from server import scheduler as scheduler_module

    entered = threading.Event()
    release = threading.Event()
    scheduler = scheduler_module.TradingScheduler(
        _scheduler_config(),
        FakeBridge(),
    )

    def blocking_loop() -> None:
        entered.set()
        release.wait(timeout=1)

    monkeypatch.setattr(scheduler, "_run_loop", blocking_loop)
    monkeypatch.setattr(
        scheduler_module,
        "_SCHEDULER_STOP_TIMEOUT_SECONDS",
        0.01,
    )

    scheduler.start()
    assert entered.wait(timeout=1)
    worker = scheduler._thread
    assert worker is not None

    scheduler.stop()

    assert scheduler.is_running is True
    assert scheduler._thread is worker
    scheduler.start()
    assert scheduler._thread is worker

    release.set()
    worker.join(timeout=1)
    assert scheduler.is_running is False
    assert scheduler._thread is None


def test_scheduler_worker_failure_clears_reported_liveness(monkeypatch) -> None:
    from server import scheduler as scheduler_module

    finished = threading.Event()
    scheduler = scheduler_module.TradingScheduler(
        _scheduler_config(),
        FakeBridge(),
    )

    def failing_loop() -> None:
        try:
            raise RuntimeError("runtime initialization failed")
        finally:
            finished.set()

    monkeypatch.setattr(scheduler, "_run_loop", failing_loop)

    scheduler.start()
    assert finished.wait(timeout=1)
    deadline = time.monotonic() + 1
    while scheduler.is_running and time.monotonic() < deadline:
        time.sleep(0.01)

    assert scheduler.is_running is False
    assert scheduler._thread is None


def test_scheduler_fails_closed_when_persisted_watchlist_cannot_be_read(
    monkeypatch,
    tmp_path,
) -> None:
    from server import scheduler as scheduler_module

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    runtime = _scheduler_runtime(
        watchlist=[(Symbol("600519"), AssetClass.STOCK)],
    )

    def fail_watchlist_read():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(db, "list_watchlist_assets_sync", fail_watchlist_read)
    _stub_scheduler_dependencies(
        monkeypatch,
        scheduler_module,
        runtime=runtime,
    )
    scheduler = scheduler_module.TradingScheduler(
        _scheduler_config(),
        FakeBridge(),
        db=db,
    )
    scheduler._running.set()

    with pytest.raises(
        RuntimeError,
        match="persisted scheduler watchlist could not be restored",
    ):
        scheduler._run_loop()

    assert scheduler.watchlist == []


def test_scheduler_fails_closed_on_unknown_persisted_asset_class(
    monkeypatch,
    tmp_path,
) -> None:
    from server import scheduler as scheduler_module

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    runtime = _scheduler_runtime(
        watchlist=[(Symbol("600519"), AssetClass.STOCK)],
        data_manager=SimpleNamespace(
            get_instrument=lambda symbol, asset_class: SimpleNamespace(symbol=symbol)
        ),
    )
    monkeypatch.setattr(
        db,
        "list_watchlist_assets_sync",
        lambda: [{"symbol": "BTCUSD", "asset_class": "crypto"}],
    )
    _stub_scheduler_dependencies(
        monkeypatch,
        scheduler_module,
        runtime=runtime,
    )
    scheduler = scheduler_module.TradingScheduler(
        _scheduler_config(),
        FakeBridge(),
        db=db,
    )
    scheduler._running.set()

    with pytest.raises(
        RuntimeError,
        match="persisted scheduler watchlist contains unsupported asset class",
    ):
        scheduler._run_loop()

    assert scheduler.watchlist == []


def test_scheduler_prefers_persistent_watchlist_over_config_assets(
    monkeypatch, tmp_path
):
    from server import scheduler as scheduler_module

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_watchlist_asset_sync(
        symbol="510300",
        asset_class="etf",
        display_name="沪深300ETF",
    )
    config = _scheduler_config(
        assets=[{"symbol": "600519", "asset_class": "stock"}],
    )
    runtime = _scheduler_runtime(
        watchlist=[(Symbol("600519"), AssetClass.STOCK)],
        instruments={Symbol("600519"): object()},
        data_manager=SimpleNamespace(
            get_instrument=lambda symbol, asset_class: SimpleNamespace(symbol=symbol)
        ),
    )
    holder = {}

    class FakeLiveDataFeed:
        def __init__(
            self,
            source,
            event_bus,
            fallback_source=None,
            prefer_fallback_asset_classes=None,
        ) -> None:
            pass

        def poll_all(self, current_watchlist):
            holder["scheduler"]._running.clear()
            assert current_watchlist == [(Symbol("510300"), AssetClass.FUND)]
            return []

        def close(self) -> None:
            pass

    monkeypatch.setattr(scheduler_module, "LiveDataFeed", FakeLiveDataFeed)
    _stub_scheduler_dependencies(
        monkeypatch,
        scheduler_module,
        runtime=runtime,
        rebuild_portfolio=lambda config, db, latest_quotes: None,
    )

    scheduler = scheduler_module.TradingScheduler(config, FakeBridge(), db=db)
    holder["scheduler"] = scheduler
    scheduler._running.set()
    scheduler._run_loop()

    assert scheduler.watchlist == [(Symbol("510300"), AssetClass.FUND)]


def test_scheduler_adds_ledger_holdings_to_watchlist(monkeypatch, tmp_path):
    from server import scheduler as scheduler_module

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-05-29T06:16:00+00:00",
        amount=1980.0,
        symbol="600002",
        direction="buy",
        quantity=100.0,
        price=19.80,
        commission=5.03,
        asset_class="stock",
        note="示例材料买入 1 手",
        source_ref="manual-stock-b-20260110-141600",
    )
    config = _scheduler_config()
    runtime = _scheduler_runtime(
        watchlist=[],
    )
    holder = {}

    class FakeLiveDataFeed:
        def __init__(
            self,
            source,
            event_bus,
            fallback_source=None,
            prefer_fallback_asset_classes=None,
        ) -> None:
            pass

        def poll_all(self, current_watchlist):
            holder["scheduler"]._running.clear()
            assert current_watchlist == [(Symbol("600002"), AssetClass.STOCK)]
            return []

        def close(self) -> None:
            pass

    monkeypatch.setattr(scheduler_module, "LiveDataFeed", FakeLiveDataFeed)
    _stub_scheduler_dependencies(
        monkeypatch,
        scheduler_module,
        runtime=runtime,
    )

    scheduler = scheduler_module.TradingScheduler(config, FakeBridge(), db=db)
    holder["scheduler"] = scheduler
    scheduler._running.set()
    scheduler._run_loop()

    assert scheduler.watchlist == [(Symbol("600002"), AssetClass.STOCK)]
