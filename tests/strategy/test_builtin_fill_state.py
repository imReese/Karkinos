"""Built-in holding state follows positions across blocked and partial exits."""

from dataclasses import replace
from decimal import Decimal

import pandas as pd
import pytest

from backtest.engine import BacktestEngine
from core.event_bus import EventBus
from core.types import OrderSide, Symbol
from data.handler import DataHandler
from domain.instrument import make_stock
from risk.rules import RiskCheckResult, RiskRule
from strategy.builtins.bollinger import BollingerStrategy
from strategy.builtins.donchian_breakout import DonchianBreakoutStrategy
from strategy.builtins.time_series_momentum import TimeSeriesMomentumStrategy


class FirstSellRule(RiskRule):
    def __init__(self, *, partial):
        self.partial = partial
        self.seen = False

    @property
    def name(self):
        return "first_sell_fixture"

    def check(self, order, positions, portfolio_value):
        if order.side is OrderSide.SELL and not self.seen:
            self.seen = True
            return RiskCheckResult(
                passed=self.partial,
                modified_order=replace(order, quantity=Decimal("100"))
                if self.partial
                else None,
            )
        return RiskCheckResult(passed=True)


def _engine(kind, *, partial=False, suspended=False):
    if kind == "bollinger":
        strategy = BollingerStrategy(EventBus(), bb_period=3, num_std=1)
        prices = (
            [10, 10, 9.5, 9.4, 10, 10.1, 10.2, 10.3]
            if partial
            else [10, 10, 9.5, 9.4, 10, 9, 10, 10.1]
        )
    else:
        strategy = (
            DonchianBreakoutStrategy(EventBus(), entry_window=2, exit_window=2)
            if kind == "donchian"
            else TimeSeriesMomentumStrategy(EventBus(), lookback_period=2)
        )
        prices = (
            [10, 10.1, 10.2, 10.3, 9.3, 9, 8.7, 8.6]
            if partial
            else [10, 10.1, 10.2, 10.3, 9.3, 8.37, 8, 8.1]
        )
    frame = pd.DataFrame(
        {
            "timestamp": pd.bdate_range("2026-01-05", periods=len(prices)),
            "open": prices,
            "high": [price + 0.01 for price in prices],
            "low": [price - 0.01 for price in prices],
            "close": prices,
            "volume": [100_000] * len(prices),
        }
    )
    if suspended:
        frame.loc[5, "volume"] = 0
    symbol = Symbol("600000")
    return (
        BacktestEngine(
            strategy,
            {symbol: make_stock(str(symbol), "fixture")},
            {symbol: DataHandler(frame, symbol)},
            initial_cash=Decimal("100000"),
        ),
        frame,
        symbol,
    )


@pytest.mark.parametrize("kind", ["donchian", "bollinger", "momentum"])
@pytest.mark.parametrize("blocked", ["limit", "suspension", "risk"])
def test_blocked_exit_reissues_when_condition_returns(kind, blocked):
    engine, frame, symbol = _engine(kind, suspended=blocked == "suspension")
    if blocked == "risk":
        engine.risk_manager.add_rule(FirstSellRule(partial=False))
    result = engine.run()
    assert [fill.side for fill in result.fills] == [OrderSide.BUY, OrderSide.SELL]
    assert result.fills[0].timestamp == frame.iloc[3]["timestamp"]
    assert result.fills[1].timestamp > frame.iloc[5]["timestamp"]
    assert result.positions[symbol].quantity == 0
    assert engine.strategy._position_quantity[symbol] == 0
    assert result.execution_timing[f"{blocked}_blocked_count"] == 1


@pytest.mark.parametrize("kind", ["donchian", "bollinger", "momentum"])
def test_partial_exit_keeps_holding_until_remaining_quantity_fills(kind):
    engine, frame, symbol = _engine(kind, partial=True)
    engine.risk_manager.add_rule(FirstSellRule(partial=True))
    result = engine.run()
    assert [fill.side for fill in result.fills] == [
        OrderSide.BUY,
        OrderSide.SELL,
        OrderSide.SELL,
    ]
    assert result.fills[1].fill_quantity == 100
    assert result.fills[2].fill_quantity == result.fills[0].fill_quantity - 100
    assert result.fills[2].timestamp == frame.iloc[6]["timestamp"]
    assert result.positions[symbol].quantity == 0
    assert engine.strategy._position_quantity[symbol] == 0


@pytest.mark.parametrize(
    ("kind", "strategy_id", "params"),
    [
        ("donchian", "donchian_breakout", {"entry_window": 2, "exit_window": 2}),
        ("bollinger", "bollinger", {"bb_period": 3, "num_std": 1}),
        ("momentum", "time_series_momentum", {"lookback_period": 2}),
    ],
)
def test_signal_only_preview_retains_entry_and_exit_regimes(kind, strategy_id, params):
    from analytics.strategy_signal_preview import build_strategy_signal_preview

    _, frame, symbol = _engine(kind)
    preview = build_strategy_signal_preview(
        strategy_id=strategy_id,
        symbol=str(symbol),
        params=params,
        bars=DataHandler(frame, symbol),
    )
    actions = [output["action"] for output in preview["outputs"]]
    assert "buy" in actions
    assert "sell" in actions
    assert preview["does_not_enable_execution"] is True
