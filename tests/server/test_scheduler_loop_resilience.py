from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable

from core.event_bus import EventBus
from core.types import AssetClass, Symbol
from server.scheduler_loop import SchedulerLoopDependencies, run_scheduler_loop


@dataclass
class FakeSchedulerState:
    running: bool = True
    initialized: bool = False
    activation_guarded: bool = False
    watchlist: list[tuple[Symbol, AssetClass]] = field(default_factory=list)
    instruments: dict[Symbol, Any] = field(default_factory=dict)
    latest_quotes: dict[str, dict[str, Any]] = field(default_factory=dict)
    portfolio: Any = None
    waits: list[float] = field(default_factory=list)
    on_wait: Callable[[int], None] | None = None
    event_bus: EventBus | None = None
    readiness_transitions: list[bool] = field(default_factory=list)
    completed_iterations: int = 0

    def scheduler_should_continue(self) -> bool:
        return self.running

    def scheduler_activation_guarded(self) -> bool:
        return self.activation_guarded

    def mark_scheduler_initialized(self) -> None:
        self.initialized = True
        self.readiness_transitions.append(True)

    def mark_scheduler_uninitialized(self) -> None:
        self.initialized = False
        self.readiness_transitions.append(False)

    def mark_scheduler_iteration_completed(self) -> None:
        self.completed_iterations += 1

    def wait_for_scheduler_stop(self, timeout: float) -> bool:
        self.waits.append(timeout)
        if self.on_wait is not None:
            self.on_wait(len(self.waits))
        return not self.running

    def runtime_event_bus(self) -> EventBus:
        assert self.event_bus is not None
        return self.event_bus

    def install_runtime_event_bus(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus

    def replace_runtime_assets(
        self,
        watchlist: list[tuple[Symbol, AssetClass]],
        instruments: dict[Symbol, Any],
    ) -> None:
        self.watchlist = list(watchlist)
        self.instruments = dict(instruments)

    def replace_runtime_quotes(self, quotes: dict[str, dict[str, Any]]) -> None:
        self.latest_quotes = dict(quotes)

    def publish_runtime_quote(self, symbol: str, quote: dict[str, Any]) -> None:
        self.latest_quotes[symbol] = dict(quote)

    def install_runtime_portfolio(self, portfolio: Any) -> None:
        self.portfolio = portfolio


class FakeFeed:
    def __init__(self) -> None:
        self.closed = False

    def poll_all(self, watchlist):
        return []

    def get_last_snapshot(self, symbol, asset_class):
        return None

    def close(self) -> None:
        self.closed = True


class FakeStrategy:
    def on_init(self, symbols) -> None:
        self.symbols = list(symbols)

    def on_data(self, event) -> None:
        raise AssertionError("no market event should reach the strategy")


def _runtime(*, watchlist: list[tuple[Symbol, AssetClass]], sources=None):
    return SimpleNamespace(
        sources={"akshare": object()} if sources is None else sources,
        data_manager=SimpleNamespace(),
        watchlist=watchlist,
        instruments={},
    )


def _dependencies(
    *,
    config,
    runtime_context_factory,
    feeds: list[FakeFeed],
    poll_watchlist_quotes,
    evaluate_controlled_session_pauses=lambda: None,
    database=None,
) -> SchedulerLoopDependencies:
    def live_data_feed_factory(*args, **kwargs) -> FakeFeed:
        feed = FakeFeed()
        feeds.append(feed)
        return feed

    return SchedulerLoopDependencies(
        event_bus_factory=EventBus,
        runtime_context_factory=runtime_context_factory,
        live_data_feed_factory=live_data_feed_factory,
        portfolio_rebuilder=lambda *args, **kwargs: None,
        strategy_factory=lambda config, publisher: FakeStrategy(),
        now=lambda: datetime(2026, 8, 28, 10, 0),
        afternoon_close=time(15, 0),
        config=config,
        database=database,
        bridge_rebinder=lambda event_bus: None,
        warmup_strategy=lambda data_manager, strategy: None,
        signal_handler=lambda event: None,
        evaluate_controlled_session_pauses=(evaluate_controlled_session_pauses),
        retry_pending_valuation_publication=lambda: False,
        is_market_open=lambda: True,
        is_post_close_refresh_window=lambda now: False,
        refresh_post_close_valuation_data=lambda *args, **kwargs: False,
        backfill_historical_bars=lambda *args, **kwargs: None,
        sync_fund_nav_quotes=lambda: None,
        sync_market_index_quotes=lambda source, fallback_source: None,
        poll_watchlist_quotes=poll_watchlist_quotes,
        finish_persisted_quote_fetch_run=lambda *args, **kwargs: True,
        finish_quote_fetch_run=lambda *args, **kwargs: True,
    )


def test_empty_watchlist_waits_and_reinitializes_until_assets_appear() -> None:
    symbol = (Symbol("600519"), AssetClass.STOCK)
    runtimes = iter(
        [
            _runtime(watchlist=[]),
            _runtime(watchlist=[symbol]),
        ]
    )
    state = FakeSchedulerState()
    state.on_wait = lambda wait_count: setattr(
        state,
        "running",
        wait_count < 2,
    )
    feeds: list[FakeFeed] = []
    polls: list[str] = []

    run_scheduler_loop(
        state,
        _dependencies(
            config=SimpleNamespace(
                data_source="akshare",
                live_poll_interval=17,
                initial_cash=Decimal("0"),
            ),
            runtime_context_factory=lambda config: next(runtimes),
            feeds=feeds,
            poll_watchlist_quotes=lambda feed: (polls.append("poll") or ([], "run")),
        ),
    )

    assert state.watchlist == [symbol]
    assert state.waits == [17, 17]
    assert polls == ["poll"]
    assert len(feeds) == 2
    assert all(feed.closed for feed in feeds)
    assert state.initialized is True
    assert state.completed_iterations == 2


def test_initialization_failure_waits_and_observes_recovered_config(caplog) -> None:
    symbol = (Symbol("600519"), AssetClass.STOCK)
    config = SimpleNamespace(
        data_source="missing",
        live_poll_interval=19,
        initial_cash=Decimal("0"),
    )
    state = FakeSchedulerState()

    def on_wait(wait_count: int) -> None:
        if wait_count == 1:
            config.data_source = "akshare"
        else:
            state.running = False

    state.on_wait = on_wait
    feeds: list[FakeFeed] = []
    polls: list[str] = []

    run_scheduler_loop(
        state,
        _dependencies(
            config=config,
            runtime_context_factory=lambda current: _runtime(
                watchlist=[symbol],
            ),
            feeds=feeds,
            poll_watchlist_quotes=lambda feed: (polls.append("poll") or ([], "run")),
        ),
    )

    assert state.waits == [19, 19]
    assert polls == ["poll"]
    assert len(feeds) == 1
    assert feeds[0].closed is True
    assert "Trading scheduler initialization failed; retrying" in caplog.text
    assert state.readiness_transitions == [False, True]
    assert state.completed_iterations == 1


def test_runtime_failure_closes_feed_waits_and_reinitializes(caplog) -> None:
    symbol = (Symbol("600519"), AssetClass.STOCK)
    state = FakeSchedulerState()
    state.on_wait = lambda wait_count: setattr(
        state,
        "running",
        wait_count < 2,
    )
    feeds: list[FakeFeed] = []
    pause_checks: list[str] = []
    polls: list[str] = []

    def evaluate_controlled_session_pauses() -> None:
        pause_checks.append("check")
        if len(pause_checks) == 1:
            raise RuntimeError("temporary runtime failure")

    run_scheduler_loop(
        state,
        _dependencies(
            config=SimpleNamespace(
                data_source="akshare",
                live_poll_interval=23,
                initial_cash=Decimal("0"),
            ),
            runtime_context_factory=lambda config: _runtime(watchlist=[symbol]),
            feeds=feeds,
            poll_watchlist_quotes=lambda feed: (polls.append("poll") or ([], "run")),
            evaluate_controlled_session_pauses=(evaluate_controlled_session_pauses),
        ),
    )

    assert state.waits == [23, 23]
    assert pause_checks == ["check", "check"]
    assert polls == ["poll"]
    assert len(feeds) == 2
    assert all(feed.closed for feed in feeds)
    assert "Trading scheduler runtime failed; reinitializing" in caplog.text
    assert state.readiness_transitions == [True, False, True]
    assert state.completed_iterations == 1


def test_initialization_failure_is_not_reported_ready() -> None:
    state = FakeSchedulerState()
    state.on_wait = lambda _wait_count: setattr(state, "running", False)
    feeds: list[FakeFeed] = []

    run_scheduler_loop(
        state,
        _dependencies(
            config=SimpleNamespace(
                data_source="missing",
                live_poll_interval=13,
                initial_cash=Decimal("0"),
            ),
            runtime_context_factory=lambda config: _runtime(watchlist=[]),
            feeds=feeds,
            poll_watchlist_quotes=lambda feed: ([], "run"),
        ),
    )

    assert state.initialized is False
    assert state.readiness_transitions == [False]
    assert feeds == []
    assert state.completed_iterations == 0


def test_persisted_quote_restore_failure_is_not_reported_ready() -> None:
    state = FakeSchedulerState()
    state.on_wait = lambda _wait_count: setattr(state, "running", False)
    feeds: list[FakeFeed] = []

    class BrokenQuoteDatabase:
        @staticmethod
        def list_watchlist_assets_sync() -> list[dict[str, Any]]:
            return []

        @staticmethod
        def get_latest_quotes_sync() -> list[dict[str, Any]]:
            raise RuntimeError("database unavailable")

    run_scheduler_loop(
        state,
        _dependencies(
            config=SimpleNamespace(
                data_source="akshare",
                live_poll_interval=13,
                initial_cash=Decimal("0"),
            ),
            runtime_context_factory=lambda config: _runtime(watchlist=[]),
            feeds=feeds,
            poll_watchlist_quotes=lambda feed: ([], "run"),
            database=BrokenQuoteDatabase(),
        ),
    )

    assert state.initialized is False
    assert state.readiness_transitions == [False]
    assert len(feeds) == 1
    assert feeds[0].closed is True
    assert state.completed_iterations == 0


def test_empty_watchlist_is_initialized_idle() -> None:
    state = FakeSchedulerState()
    state.on_wait = lambda _wait_count: setattr(state, "running", False)
    feeds: list[FakeFeed] = []
    polls: list[str] = []

    run_scheduler_loop(
        state,
        _dependencies(
            config=SimpleNamespace(
                data_source="akshare",
                live_poll_interval=11,
                initial_cash=Decimal("0"),
            ),
            runtime_context_factory=lambda config: _runtime(watchlist=[]),
            feeds=feeds,
            poll_watchlist_quotes=lambda feed: (polls.append("poll") or ([], "run")),
        ),
    )

    assert state.initialized is True
    assert state.readiness_transitions == [True]
    assert polls == []
    assert len(feeds) == 1
    assert feeds[0].closed is True
    assert state.completed_iterations == 1


def test_activation_guard_blocks_iterations_until_removed_without_restart() -> None:
    symbol = (Symbol("600519"), AssetClass.STOCK)
    state = FakeSchedulerState(activation_guarded=True)

    def on_wait(wait_count: int) -> None:
        if wait_count == 1:
            state.activation_guarded = False
        else:
            state.running = False

    state.on_wait = on_wait
    feeds: list[FakeFeed] = []
    pause_checks: list[str] = []
    polls: list[str] = []

    run_scheduler_loop(
        state,
        _dependencies(
            config=SimpleNamespace(
                data_source="akshare",
                live_poll_interval=29,
                initial_cash=Decimal("0"),
            ),
            runtime_context_factory=lambda config: _runtime(watchlist=[symbol]),
            feeds=feeds,
            poll_watchlist_quotes=lambda feed: (polls.append("poll") or ([], "run")),
            evaluate_controlled_session_pauses=lambda: pause_checks.append("check"),
        ),
    )

    assert state.initialized is True
    assert state.readiness_transitions == [True]
    assert state.waits == [1.0, 29]
    assert pause_checks == ["check"]
    assert polls == ["poll"]
    assert len(feeds) == 1
    assert feeds[0].closed is True
    assert state.completed_iterations == 1


def test_guarded_empty_watchlist_counts_idle_readiness_only_after_release() -> None:
    state = FakeSchedulerState(activation_guarded=True)

    def on_wait(wait_count: int) -> None:
        if wait_count == 1:
            assert state.completed_iterations == 0
            state.activation_guarded = False
        else:
            state.running = False

    state.on_wait = on_wait
    feeds: list[FakeFeed] = []

    run_scheduler_loop(
        state,
        _dependencies(
            config=SimpleNamespace(
                data_source="akshare",
                live_poll_interval=29,
                initial_cash=Decimal("0"),
            ),
            runtime_context_factory=lambda config: _runtime(watchlist=[]),
            feeds=feeds,
            poll_watchlist_quotes=lambda feed: ([], "run"),
        ),
    )

    assert state.waits == [1.0, 29]
    assert state.completed_iterations == 1
    assert len(feeds) == 2
    assert all(feed.closed for feed in feeds)
