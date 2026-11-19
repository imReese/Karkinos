"""Unit tests and counterexamples for BacktestEngine lifecycle cleanup and post-close isolation."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from backtest.costs import RESEARCH_SLIPPAGE_BPS
from backtest.engine import BacktestEngine
from core.event_bus import EventBus
from core.events import MarketEvent, OrderEvent
from core.types import InstrumentType, OrderSide, OrderType, Symbol
from domain.instrument import make_stock
from execution.commission import StockACommission
from execution.slippage import PercentSlippage
from strategy.base import Strategy

SH = ZoneInfo("Asia/Shanghai")
SYMBOL = Symbol("600000")


def _make_daily_bars(prices: list[float]) -> list[MarketEvent]:
    events = []
    base_dt = datetime(2026, 1, 5, 15, 0, tzinfo=SH)
    for i, px in enumerate(prices):
        ts = base_dt + timedelta(days=i)
        val = Decimal(str(px))
        events.append(
            MarketEvent(
                timestamp=ts,
                symbol=SYMBOL,
                open=val,
                high=val,
                low=val,
                close=val,
                volume=Decimal("100000"),
                available_at=ts + timedelta(hours=1),
                instrument_type=InstrumentType.STOCK,
            )
        )
    return events


class OrderThenExplodeStrategy(Strategy):
    """Submits an order on step 1, then immediately raises an exception in on_data."""

    def __init__(self) -> None:
        super().__init__("order_explode", EventBus())
        self.step = 0

    def on_init(self, symbols: list[Symbol]) -> None:
        pass

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        self.step += 1
        if self.step == 1:
            self.emit_signal(event.symbol, target_weight=0.5, price=float(event.close))
            raise RuntimeError("strategy_failed_after_submitting_order")


def _build_test_engine(
    strategy: Strategy, prices: list[float] | None = None, **kwargs
) -> BacktestEngine:
    bars = _make_daily_bars(prices or [10.0, 10.5, 11.0])
    inst = make_stock(str(SYMBOL), "synthetic_stock")
    return BacktestEngine(
        strategy=strategy,
        instruments={SYMBOL: inst},
        data_handlers={SYMBOL: bars},
        initial_cash=Decimal("100000"),
        commission_calc=StockACommission(),
        slippage_model=PercentSlippage(RESEARCH_SLIPPAGE_BPS / Decimal("10000")),
        strict_event_errors=True,
        **kwargs,
    )


def test_exception_in_on_data_clears_residual_orders_from_bus():
    """Counterexample A1: Strategy throwing exception in on_data after submitting orders

    must not leave residual orders in event_bus that drain to fills later.
    """
    strat = OrderThenExplodeStrategy()
    engine = _build_test_engine(strat)

    with pytest.raises(RuntimeError, match="strategy_failed_after_submitting_order"):
        engine.run()

    # Engine is now closed. Draining the bus must NOT execute any residual orders into fills
    drained_count = engine.event_bus.drain()
    assert drained_count == 0
    assert len(engine.fills) == 0
    assert len(engine.portfolio.positions) == 0
    assert engine.portfolio.cash == Decimal("100000")


def test_post_run_order_does_not_mutate_result_positions():
    """Counterexample A2: Post-run order publishing must not mutate result.positions.

    result.positions must be an immutable defensive snapshot.
    """

    class SimpleBuyStrategy(Strategy):
        def on_init(self, symbols: list[Symbol]) -> None:
            pass

        def on_data(self, event: MarketEvent) -> None:
            self._last_timestamp = event.timestamp
            self.emit_signal(event.symbol, target_weight=0.5, price=float(event.close))

    strat = SimpleBuyStrategy("simple_buy", EventBus())
    engine = _build_test_engine(strat)
    result = engine.run()

    initial_pos_qty = result.positions[SYMBOL].quantity
    initial_fills_count = len(result.fills)
    assert initial_pos_qty > 0
    assert initial_fills_count > 0

    # Mutate portfolio directly or publish order
    engine.portfolio.positions[SYMBOL].quantity = Decimal("999999")

    # result.positions must NOT have mutated
    assert result.positions[SYMBOL].quantity == initial_pos_qty
    assert len(result.fills) == initial_fills_count


def test_init_failure_restores_strategy_bus_and_fill_tracking(monkeypatch):
    """Counterexample A3: BacktestEngine.__init__ failure must restore strategy's original

    event_bus and fill_tracking_enabled flag, even if failure occurs after rebinding.
    """
    custom_bus = EventBus()
    strat = OrderThenExplodeStrategy()
    strat.event_bus = custom_bus
    strat.fill_tracking_enabled = False

    def explode_execution(**kwargs):
        raise RuntimeError("execution_init_exploded")

    monkeypatch.setattr("backtest.engine.SimulatedExecution", explode_execution)

    with pytest.raises(RuntimeError, match="execution_init_exploded"):
        _build_test_engine(strat)

    assert strat.event_bus is custom_bus
    assert strat.fill_tracking_enabled is False
    assert getattr(strat, "_bound_engine", None) is None


def test_engine_close_clears_event_bus_handlers_and_queue():
    """Counterexample A4: Calling close() on engine must clear the event bus handlers and queue."""
    strat = OrderThenExplodeStrategy()
    engine = _build_test_engine(strat)
    assert engine.event_bus.queue_size == 0
    assert len(engine.event_bus._handlers) > 0

    engine.close()

    assert len(engine.event_bus._handlers) == 0
    assert engine.event_bus.queue_size == 0
