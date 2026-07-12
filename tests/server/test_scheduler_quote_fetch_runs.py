from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from core.events import MarketEvent, OrderEvent, SignalEvent
from core.types import AssetClass, BarFrequency, OrderSide, OrderType, Symbol
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
        lambda self, data_manager, strategy: None,
    )
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
) -> AppDatabase:
    from server import scheduler as scheduler_module

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    watchlist = watchlist or [(Symbol("600519"), AssetClass.STOCK)]
    events = events or []
    snapshots = snapshots or {}

    config = _scheduler_config(data_source=data_source)
    runtime = _scheduler_runtime(
        data_source=data_source,
        watchlist=watchlist,
        sources=sources,
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

    monkeypatch.setattr(scheduler_module, "LiveDataFeed", FakeLiveDataFeed)
    _stub_scheduler_dependencies(
        monkeypatch,
        scheduler_module,
        runtime=runtime,
        strategy_factory=strategy_factory,
        fund_nav_sync=fund_nav_sync,
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
                "display_name": "贵州茅台",
            }
        },
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


def test_scheduler_wires_paper_orders_to_persistent_execution_connector(
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

    saved_order = db.get_order_sync("ORD-SCHED-PAPER-1")
    fills = db.list_fills_sync(order_id="ORD-SCHED-PAPER-1")

    assert saved_order is not None
    assert saved_order["status"] == "filled"
    assert saved_order["execution_mode"] == "paper"
    assert saved_order["source"] == "paper_execution"
    assert len(fills) == 1
    assert fills[0]["provider_name"] == "simulated"
    assert fills[0]["fill_price"] == 123.45


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

    def fake_refresh_fund_nav_quotes(config, db, watchlist, latest_quotes):
        fund_sync_calls.append((list(watchlist), dict(latest_quotes)))
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
        def __init__(self, source, event_bus, fallback_source=None) -> None:
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

    class FakeLiveDataFeed:
        def __init__(self, source, event_bus, fallback_source=None) -> None:
            pass

        def poll_all(self, current_watchlist):
            calls.append(tuple(current_watchlist))
            return []

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
        def __init__(self, source, event_bus, fallback_source=None) -> None:
            pass

        def poll_all(self, current_watchlist):
            holder["scheduler"]._running.clear()
            assert current_watchlist == [(Symbol("510300"), AssetClass.FUND)]
            return []

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
        def __init__(self, source, event_bus, fallback_source=None) -> None:
            pass

        def poll_all(self, current_watchlist):
            holder["scheduler"]._running.clear()
            assert current_watchlist == [(Symbol("600002"), AssetClass.STOCK)]
            return []

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
