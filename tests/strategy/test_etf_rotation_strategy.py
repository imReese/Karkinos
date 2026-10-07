"""Tests for strategy/builtins/etf_rotation.py."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from core.event_bus import EventBus
from core.events import MarketEvent, SignalEvent
from core.types import Symbol
from strategy.builtins.etf_rotation import EtfRotationStrategy
from strategy.registry import StrategyRegistry


def _make_event(symbol: Symbol, price: float, day: int) -> MarketEvent:
    return MarketEvent(
        timestamp=datetime(2026, 1, day + 1),
        symbol=symbol,
        open=Decimal(str(price)),
        high=Decimal(str(price + 0.5)),
        low=Decimal(str(price - 0.5)),
        close=Decimal(str(price)),
        volume=Decimal("1000000"),
    )


def test_etf_rotation_registered() -> None:
    assert "etf_rotation" in StrategyRegistry.list_strategies()
    entry = StrategyRegistry.get("etf_rotation")
    assert entry is not None
    assert entry["display_name"] == "Cross-Sectional ETF Rotation"


def test_etf_rotation_momentum_selection_and_cash_proxy() -> None:
    bus = EventBus()
    strategy = EtfRotationStrategy(
        bus,
        lookback_period=3,
        volatility_window=3,
        top_k=1,
        rebalance_interval=1,
        min_momentum=0.0,
        trend_filter_period=0,
        use_risk_adjusted=False,
        cash_proxy="511010",
    )
    sym_a = Symbol("510300")
    sym_b = Symbol("510500")
    sym_cash = Symbol("511010")

    strategy.on_init([sym_a, sym_b, sym_cash])

    signals: list[SignalEvent] = []
    bus.subscribe(SignalEvent, signals.append)

    # Days 0..3: Warmup prices
    # sym_a: 100 -> 101 -> 102 -> 103 (+3%)
    # sym_b: 100 -> 102 -> 105 -> 110 (+10%)
    # sym_cash: 100 -> 100 -> 100 -> 100 (0%)
    prices_a = [100.0, 101.0, 102.0, 103.0]
    prices_b = [100.0, 102.0, 105.0, 110.0]
    prices_c = [100.0, 100.1, 100.2, 100.3]

    for day in range(4):
        strategy.on_data(_make_event(sym_a, prices_a[day], day))
        strategy.on_data(_make_event(sym_b, prices_b[day], day))
        strategy.on_data(_make_event(sym_cash, prices_c[day], day))
        bus.drain()

    # sym_b had higher momentum than sym_a, so sym_b should be selected with target_weight=1.0
    latest_targets = {s.symbol: float(s.target_weight) for s in signals}
    assert latest_targets.get(sym_b) == 1.0
    assert latest_targets.get(sym_a) == 0.0


def test_etf_rotation_defensive_switch_when_all_drop() -> None:
    bus = EventBus()
    strategy = EtfRotationStrategy(
        bus,
        lookback_period=2,
        volatility_window=2,
        top_k=2,
        rebalance_interval=1,
        min_momentum=0.0,
        use_risk_adjusted=False,
        cash_proxy="511010",
    )
    sym_a = Symbol("510300")
    sym_b = Symbol("510500")
    sym_cash = Symbol("511010")

    strategy.on_init([sym_a, sym_b, sym_cash])

    signals: list[SignalEvent] = []
    bus.subscribe(SignalEvent, signals.append)

    # All equities drop below min_momentum (negative return)
    # Day 0: 100, Day 1: 95, Day 2: 90 (-10%)
    prices_a = [100.0, 95.0, 90.0]
    prices_b = [100.0, 90.0, 80.0]
    prices_c = [100.0, 100.1, 100.2]

    for day in range(3):
        strategy.on_data(_make_event(sym_a, prices_a[day], day))
        strategy.on_data(_make_event(sym_b, prices_b[day], day))
        strategy.on_data(_make_event(sym_cash, prices_c[day], day))
        bus.drain()

    # Both equities have negative momentum (< 0.0), so all weight rotates to cash_proxy
    latest_targets = {s.symbol: float(s.target_weight) for s in signals}
    assert latest_targets.get(sym_cash) == 1.0
    assert latest_targets.get(sym_a) == 0.0
    assert latest_targets.get(sym_b) == 0.0
