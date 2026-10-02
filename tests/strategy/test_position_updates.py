"""Absolute book positions drive strategy exits after non-trade share awards."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from core.event_bus import EventBus
from core.events import FillEvent, MarketEvent, SignalEvent
from core.types import OrderSide, Symbol
from server.ai_runtime.formula_dsl import FORMULA_AST_CONTRACT
from server.ai_runtime.strategy_research_backtest import _FormulaSignalStrategy
from strategy.builtins.bollinger import BollingerStrategy
from strategy.builtins.donchian_breakout import DonchianBreakoutStrategy
from strategy.builtins.time_series_momentum import TimeSeriesMomentumStrategy

SYMBOL = Symbol("600000")
OTHER_SYMBOL = Symbol("600001")


def _strategy(kind):
    bus = EventBus()
    if kind == "bollinger":
        strategy = BollingerStrategy(bus, bb_period=3, num_std=1)
    elif kind == "donchian":
        strategy = DonchianBreakoutStrategy(bus, entry_window=2, exit_window=2)
    elif kind == "momentum":
        strategy = TimeSeriesMomentumStrategy(bus, lookback_period=2)
    else:
        comparison = {
            "left": {"op": "field", "name": "close"},
            "right": {"op": "constant", "value": 10},
        }
        strategy = _FormulaSignalStrategy(
            {
                "schema_version": FORMULA_AST_CONTRACT,
                "entry": {"op": "gt", **comparison},
                "exit": {"op": "lt", **comparison},
                "position_size": {"op": "equal_weight"},
            },
            2,
        )
        strategy.event_bus = bus
    strategy.fill_tracking_enabled = True
    strategy.on_init([SYMBOL, OTHER_SYMBOL])
    signals = []
    bus.subscribe(SignalEvent, signals.append)
    return strategy, bus, signals


def _bar(strategy, bus, price, day):
    price = Decimal(str(price))
    strategy.on_data(
        MarketEvent(
            timestamp=datetime(2026, 1, 5) + timedelta(days=day),
            symbol=SYMBOL,
            open=price,
            high=price + Decimal("0.01"),
            low=price - Decimal("0.01"),
            close=price,
            volume=Decimal("100000"),
        )
    )
    bus.drain()


def _fill_then_position(strategy, side, quantity, actual):
    strategy.on_fill(
        FillEvent(
            timestamp=datetime(2026, 1, 5),
            fill_id=f"fill-{side.value}-{quantity}",
            order_id=f"order-{side.value}-{quantity}",
            symbol=SYMBOL,
            side=side,
            fill_price=Decimal("10"),
            fill_quantity=Decimal(quantity),
            commission=Decimal("0"),
            slippage=Decimal("0"),
        )
    )
    strategy.on_position_update(SYMBOL, Decimal(actual))


@pytest.mark.parametrize("kind", ["bollinger", "donchian", "momentum", "formula"])
@pytest.mark.parametrize("partial_exit", [False, True])
def test_share_award_keeps_exit_state_until_actual_position_is_zero(kind, partial_exit):
    strategy, bus, signals = _strategy(kind)
    _fill_then_position(strategy, OrderSide.BUY, "100", "100")
    strategy.on_position_update(SYMBOL, Decimal("130"))
    strategy.on_position_update(SYMBOL, Decimal("130"))
    assert strategy._position_quantity[SYMBOL] == Decimal("130")
    assert strategy._position_quantity[OTHER_SYMBOL] == 0
    for day, price in enumerate([10, 11, 12]):
        _bar(strategy, bus, price, day)
    signals.clear()

    exit_prices = [13, 14, 15] if kind == "bollinger" else [9, 8, 7]
    _bar(strategy, bus, exit_prices[0], 3)
    assert [signal.target_weight for signal in signals] == [Decimal("0")]
    signals.clear()
    if partial_exit:
        _fill_then_position(strategy, OrderSide.SELL, "100", "30")
        _bar(strategy, bus, exit_prices[1], 4)
        assert [signal.target_weight for signal in signals] == [Decimal("0")]
        signals.clear()
    _fill_then_position(strategy, OrderSide.SELL, "30" if partial_exit else "130", "0")
    _bar(strategy, bus, exit_prices[2], 5)
    assert signals == []
    assert strategy._position_quantity[SYMBOL] == 0
    if kind == "formula":
        assert strategy._active == {SYMBOL: False, OTHER_SYMBOL: False}

    # A full exit must also permit the next genuine entry regime.
    _bar(strategy, bus, 1 if kind == "bollinger" else 20, 6)
    assert len(signals) == 1
    assert signals[0].target_weight > 0
