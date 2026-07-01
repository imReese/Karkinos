"""Research strategy algorithm tests."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from core.event_bus import EventBus
from core.events import MarketEvent, SignalEvent
from core.types import Symbol
from strategy.builtins.donchian_breakout import DonchianBreakoutStrategy
from strategy.builtins.pairs_ratio_mean_reversion import (
    PairsRatioMeanReversionStrategy,
)
from strategy.builtins.time_series_momentum import TimeSeriesMomentumStrategy
from strategy.builtins.volatility_target_trend import VolatilityTargetTrendStrategy


def _make_event(
    symbol: Symbol,
    price: float,
    day: int,
    *,
    high: float | None = None,
    low: float | None = None,
) -> MarketEvent:
    return MarketEvent(
        timestamp=datetime(2026, 1, day + 1),
        symbol=symbol,
        open=Decimal(str(price)),
        high=Decimal(str(high if high is not None else price + 1)),
        low=Decimal(str(low if low is not None else price - 1)),
        close=Decimal(str(price)),
        volume=Decimal("1000000"),
    )


def _collect_signals(bus: EventBus) -> list[SignalEvent]:
    signals: list[SignalEvent] = []
    bus.subscribe(SignalEvent, signals.append)
    return signals


def test_time_series_momentum_enters_positive_momentum_and_exits_negative() -> None:
    bus = EventBus()
    strategy = TimeSeriesMomentumStrategy(
        bus,
        lookback_period=3,
        min_return=0.0,
        exit_return=0.0,
        target_weight=0.8,
    )
    strategy.on_init([Symbol("510300")])
    signals = _collect_signals(bus)

    for day, price in enumerate([100, 101, 102, 106, 99]):
        strategy.on_data(_make_event(Symbol("510300"), price, day))
        bus.drain()

    assert [(signal.target_weight, signal.price) for signal in signals] == [
        (Decimal("0.8"), Decimal("106")),
        (Decimal("0.0"), Decimal("99")),
    ]


def test_donchian_breakout_buys_channel_breakout_and_exits_breakdown() -> None:
    bus = EventBus()
    strategy = DonchianBreakoutStrategy(
        bus,
        entry_window=3,
        exit_window=2,
        target_weight=1.0,
    )
    strategy.on_init([Symbol("510500")])
    signals = _collect_signals(bus)

    events = [
        _make_event(Symbol("510500"), 100, 0, high=101, low=99),
        _make_event(Symbol("510500"), 102, 1, high=103, low=101),
        _make_event(Symbol("510500"), 103, 2, high=104, low=102),
        _make_event(Symbol("510500"), 105, 3, high=106, low=104),
        _make_event(Symbol("510500"), 99, 4, high=100, low=98),
    ]
    for event in events:
        strategy.on_data(event)
        bus.drain()

    assert [(signal.target_weight, signal.price) for signal in signals] == [
        (Decimal("1.0"), Decimal("105")),
        (Decimal("0.0"), Decimal("99")),
    ]


def test_volatility_target_trend_scales_positive_momentum_by_realized_vol() -> None:
    bus = EventBus()
    strategy = VolatilityTargetTrendStrategy(
        bus,
        lookback_period=3,
        volatility_window=3,
        target_annual_volatility=0.20,
        max_weight=1.0,
        min_momentum=0.0,
        rebalance_threshold=0.01,
    )
    strategy.on_init([Symbol("159915")])
    signals = _collect_signals(bus)

    for day, price in enumerate([100, 110, 100, 120, 90]):
        strategy.on_data(_make_event(Symbol("159915"), price, day))
        bus.drain()

    assert len(signals) == 2
    assert Decimal("0") < signals[0].target_weight < Decimal("0.5")
    assert signals[0].price == Decimal("120")
    assert signals[1].target_weight == Decimal("0.0")
    assert signals[1].price == Decimal("90")


def test_pairs_ratio_mean_reversion_rotates_to_cheap_leg_and_neutralizes() -> None:
    bus = EventBus()
    strategy = PairsRatioMeanReversionStrategy(
        bus,
        symbol_a="510300",
        symbol_b="510500",
        lookback_period=4,
        entry_z=1.2,
        exit_z=0.3,
        pair_weight=1.0,
        neutral_weight=0.5,
    )
    symbol_a = Symbol("510300")
    symbol_b = Symbol("510500")
    strategy.on_init([symbol_a, symbol_b])
    signals = _collect_signals(bus)

    pair_prices = [
        (100, 100),
        (100, 100),
        (100, 100),
        (80, 100),
        (95, 100),
    ]
    for day, (price_a, price_b) in enumerate(pair_prices):
        strategy.on_data(_make_event(symbol_a, price_a, day))
        strategy.on_data(_make_event(symbol_b, price_b, day))
        bus.drain()

    signal_summary = [
        (str(signal.symbol), signal.target_weight, signal.price) for signal in signals
    ]
    assert signal_summary == [
        ("510300", Decimal("1.0"), Decimal("80")),
        ("510500", Decimal("0.0"), Decimal("100")),
        ("510300", Decimal("0.5"), Decimal("95")),
        ("510500", Decimal("0.5"), Decimal("100")),
    ]


def test_new_research_strategies_are_registered_with_typed_params() -> None:
    import strategy.builtins  # noqa: F401
    from strategy.registry import StrategyRegistry

    info_by_id = {entry["strategy_id"]: entry for entry in StrategyRegistry.get_info()}

    assert info_by_id["time_series_momentum"]["benchmark_role"] == (
        "time_series_momentum"
    )
    assert info_by_id["donchian_breakout"]["benchmark_role"] == (
        "channel_breakout_trend_following"
    )
    assert info_by_id["volatility_target_trend"]["benchmark_role"] == (
        "volatility_target_trend_following"
    )
    assert info_by_id["pairs_ratio_mean_reversion"]["benchmark_role"] == (
        "pair_relative_value_mean_reversion"
    )
    assert {
        param["name"]
        for param in info_by_id["volatility_target_trend"]["parameter_schema"]
    } == {
        "lookback_period",
        "volatility_window",
        "target_annual_volatility",
        "max_weight",
        "min_momentum",
        "rebalance_threshold",
    }
