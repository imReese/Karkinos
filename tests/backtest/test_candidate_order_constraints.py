"""Tests ensuring final candidate orders strictly conform to board and lot size rules."""

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from backtest.engine import BacktestEngine, ExecutionModel
from core.event_bus import EventBus
from core.events import SignalEvent
from core.types import ZERO, OrderSide, Symbol
from data.handler import DataHandler
from domain.instrument import make_stock
from execution.commission import StockACommission
from execution.slippage import FixedSlippage
from strategy.base import Strategy

SHANGHAI = ZoneInfo("Asia/Shanghai")
DAYS = [day.date() for day in pd.bdate_range("2026-05-11", periods=5)]


def _close(day: date) -> datetime:
    return datetime.combine(day, time(15), SHANGHAI)


def _frame(prices: list[float], *, days: list[date] = DAYS) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp": _close(day),
                "available_at": _close(day),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 100000,
            }
            for day, price in zip(days, prices, strict=True)
        ]
    )


class OneShotSignalStrategy(Strategy):
    def __init__(self, target_weight: Decimal, symbol: Symbol) -> None:
        super().__init__("oneshot", EventBus())
        self.target_weight = target_weight
        self.symbol = symbol
        self.fired = False

    def on_init(self, symbols) -> None:
        pass

    def on_data(self, event) -> None:
        if not self.fired:
            self.fired = True
            self.event_bus.publish(
                SignalEvent(
                    timestamp=event.timestamp,
                    strategy_id=self.strategy_id,
                    symbol=self.symbol,
                    target_weight=self.target_weight,
                    price=event.close,
                )
            )


def test_star_market_insufficient_cash_does_not_shrink_to_illegal_100_shares():
    """For STAR Market (min_order_qty=200), if cash only affords 150 shares,
    it must NOT shrink to 100 shares. It must shrink to 0 and block on cash/lot_size.
    """
    star_symbol = Symbol("688001")
    # Stock price is 50. 200 shares = 10,000 + commission (~10,005).
    # If initial cash is 8,000, max affordable is ~159 shares.
    # A faulty engine using 100-share step would produce a 100-share candidate order.
    # A correct engine recognizes STAR min lot is 200 and rejects.
    inst = make_stock(str(star_symbol), "STAR Stock")
    frame = _frame([50.0, 50.0, 50.0, 50.0, 50.0])
    handler = DataHandler(frame, star_symbol)

    strategy = OneShotSignalStrategy(Decimal("1.0"), star_symbol)
    engine = BacktestEngine(
        strategy,
        {star_symbol: inst},
        {star_symbol: handler},
        initial_cash=Decimal("8000.00"),
        execution_model=ExecutionModel.NEXT_BAR_CLOSE,
        commission_calc=StockACommission(),
        slippage_model=FixedSlippage(ZERO),
    )

    result = engine.run()

    # The order must not have been filled at 100 shares!
    assert len(result.fills) == 0
    timing = result.execution_timing
    assert (
        timing["cash_blocked_count"] >= 1
        or timing["lot_size_blocked_count"] >= 1
        or timing["risk_blocked_count"] >= 1
    )
    assert engine.portfolio.positions == {}


class DirectOrderStrategy(Strategy):
    def __init__(self, symbol: Symbol, quantity: Decimal, price: Decimal) -> None:
        super().__init__("direct_order", EventBus())
        self.symbol = symbol
        self.quantity = quantity
        self.price = price
        self.fired = False

    def on_init(self, symbols) -> None:
        pass

    def on_data(self, event) -> None:
        if not self.fired:
            self.fired = True
            from core.events import OrderEvent
            from core.types import OrderType

            self.event_bus.publish(
                OrderEvent(
                    timestamp=event.timestamp,
                    order_id="direct_ord_1",
                    symbol=self.symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=self.quantity,
                    price=self.price,
                )
            )


def test_star_market_200_share_order_insufficient_cash_does_not_shrink_to_100():
    """An approved 200-share order for STAR market stock cannot be afforded
    (cash=8000, cost=10005). _cash_funded_fill must NOT step down to 100 shares.
    It must abort with cash_blocked_count >= 1 and 0 fills.
    """
    star_symbol = Symbol("688001")
    inst = make_stock(str(star_symbol), "STAR Stock")
    frame = _frame([50.0, 50.0, 50.0, 50.0, 50.0])
    handler = DataHandler(frame, star_symbol)

    strategy = DirectOrderStrategy(star_symbol, Decimal("200"), Decimal("50.0"))
    engine = BacktestEngine(
        strategy,
        {star_symbol: inst},
        {star_symbol: handler},
        initial_cash=Decimal("8000.00"),
        execution_model=ExecutionModel.NEXT_BAR_CLOSE,
        commission_calc=StockACommission(),
        slippage_model=FixedSlippage(ZERO),
    )

    result = engine.run()

    assert len(result.fills) == 0
    assert result.execution_timing["cash_blocked_count"] >= 1
    assert engine.portfolio.positions == {}


def test_star_market_capacity_insufficient_does_not_shrink_to_100():
    """For STAR market stock with 200 share order, if remaining capacity is 150 shares,
    it must NOT shrink to 100 shares. It must abort with capacity_blocked_count >= 1.
    """
    star_symbol = Symbol("688001")
    inst = make_stock(str(star_symbol), "STAR Stock")
    # Volume is 1,500 shares. With max_volume_participation=0.10, capacity is 150 shares.
    frame = pd.DataFrame(
        [
            {
                "timestamp": _close(day),
                "available_at": _close(day),
                "open": 50.0,
                "high": 50.0,
                "low": 50.0,
                "close": 50.0,
                "volume": 1500,
            }
            for day in DAYS
        ]
    )
    handler = DataHandler(frame, star_symbol)

    from backtest.engine import BacktestExecutionConfig

    config = BacktestExecutionConfig(
        max_volume_participation=Decimal("0.10"),
        execution_model=ExecutionModel.NEXT_BAR_CLOSE,
        commission_calc=StockACommission(),
        slippage_model=FixedSlippage(ZERO),
    )
    strategy = DirectOrderStrategy(star_symbol, Decimal("200"), Decimal("50.0"))
    engine = BacktestEngine(
        strategy,
        {star_symbol: inst},
        {star_symbol: handler},
        initial_cash=Decimal("100000.00"),
        execution_config=config,
    )

    result = engine.run()

    assert len(result.fills) == 0
    assert result.execution_timing["capacity_blocked_count"] >= 1
    assert engine.portfolio.positions == {}


def test_ex_dividend_reference_price_used_for_price_limits():
    """On ex-dividend day, price limits must be calculated from the ex-reference price,
    NOT the prior raw close.
    P_prev = 100.0, cash_div = 10.0 => P_ex = 90.0 => Limit-up is 99.00.
    Open price = 99.50 exceeds limit-up and must be blocked!
    """
    symbol = Symbol("600001")
    inst = make_stock(str(symbol), "Dividend Stock")

    # Day 0: Close 100 (record date)
    # Day 1: Open 99.5, Close 99.5 (ex-dividend date)
    day0 = date(2026, 6, 1)
    day1 = date(2026, 6, 2)
    frame = pd.DataFrame(
        [
            {
                "timestamp": _close(day0),
                "available_at": _close(day0),
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 100000,
            },
            {
                "timestamp": _close(day1),
                "available_at": _close(day1),
                "open": 99.5,
                "high": 99.5,
                "low": 99.5,
                "close": 99.5,
                "volume": 100000,
            },
        ]
    )
    handler = DataHandler(frame, symbol)

    from backtest.distributions import StockDistribution

    dist = StockDistribution(
        symbol=symbol,
        action_id="div_1",
        record_date=day0,
        ex_date=day1,
        cash_per_share=Decimal("10.0"),
        available_at=_close(day0),
        pay_date=day1,
    )

    # Strategy signals a buy on day 0 close, to be executed on day 1 open
    class ExDivSignalStrategy(Strategy):
        def __init__(self) -> None:
            super().__init__("ex_div_strat", EventBus())
            self.fired = False

        def on_init(self, symbols) -> None:
            pass

        def on_data(self, event) -> None:
            if not self.fired and event.timestamp.date() == day0:
                self.fired = True
                self.event_bus.publish(
                    SignalEvent(
                        timestamp=event.timestamp,
                        strategy_id=self.strategy_id,
                        symbol=symbol,
                        target_weight=Decimal("0.5"),
                        price=event.close,
                    )
                )

    engine = BacktestEngine(
        ExDivSignalStrategy(),
        {symbol: inst},
        {symbol: handler},
        initial_cash=Decimal("100000.00"),
        execution_model=ExecutionModel.NEXT_BAR_OPEN,
        cash_dividends=(dist,),
        allow_ex_date_trading=True,
        commission_calc=StockACommission(),
        slippage_model=FixedSlippage(ZERO),
    )

    result = engine.run()

    # The buy at 99.5 must be blocked because limit-up is 99.00!
    assert len(result.fills) == 0
    assert result.execution_timing["limit_blocked_count"] >= 1


def test_strict_security_status_blocks_unverified():
    """In strict security status mode, unverified securities are blocked."""
    symbol = Symbol("600001")
    inst = make_stock(str(symbol), "Unverified Stock")
    frame = _frame([10.0, 10.0, 10.0, 10.0, 10.0])
    handler = DataHandler(frame, symbol)

    strategy = OneShotSignalStrategy(Decimal("0.5"), symbol)
    engine = BacktestEngine(
        strategy,
        {symbol: inst},
        {symbol: handler},
        initial_cash=Decimal("100000.00"),
        execution_model=ExecutionModel.NEXT_BAR_CLOSE,
        strict_security_status=True,
    )

    result = engine.run()
    assert len(result.fills) == 0
    assert result.execution_timing["unverified_state_blocked_count"] >= 1


def test_trading_calendar_coverage_incomplete_raises():
    """When a trading calendar does not cover the backtest window, fail-closed."""
    symbol = Symbol("600001")
    inst = make_stock(str(symbol), "Stock")
    # Data spans 2023 to 2024
    frame = pd.DataFrame(
        [
            {
                "timestamp": datetime(2023, 1, 3, 15, tzinfo=SHANGHAI),
                "available_at": datetime(2023, 1, 3, 15, tzinfo=SHANGHAI),
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 100000,
            },
            {
                "timestamp": datetime(2024, 1, 3, 15, tzinfo=SHANGHAI),
                "available_at": datetime(2024, 1, 3, 15, tzinfo=SHANGHAI),
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 100000,
            },
        ]
    )
    handler = DataHandler(frame, symbol)
    from data.market_calendar import build_static_market_calendar_snapshot

    # Snapshot only covers 2023
    snapshot_2023 = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2023,
        provider="test",
        open_dates=["2023-01-03"],
    )

    strategy = OneShotSignalStrategy(Decimal("0.5"), symbol)
    engine = BacktestEngine(
        strategy,
        {symbol: inst},
        {symbol: handler},
        initial_cash=Decimal("100000.00"),
        trading_calendar=snapshot_2023,
    )

    with pytest.raises(ValueError, match="trading_calendar_coverage_incomplete"):
        engine.run()
