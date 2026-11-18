"""Tests ensuring final candidate orders strictly conform to board and lot size rules."""

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from backtest.engine import BacktestEngine, ExecutionModel
from core.event_bus import EventBus
from core.events import MarketEvent, SignalEvent
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
        if event.timestamp.date() > DAYS[0] and not self.fired:
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


def test_buy_below_limit_down_is_blocked():
    """Previous close = 10.0, limit_pct = 0.10 => [9.00, 11.00].
    Next day Open = 8.00 (below limit down).
    BUY order must be strictly blocked by price limit validation with limit_blocked_count >= 1!
    """
    symbol = Symbol("600519")
    inst = make_stock(str(symbol), "Stock")
    day0 = date(2024, 1, 2)
    day1 = date(2024, 1, 3)
    frame = pd.DataFrame(
        [
            {
                "timestamp": _close(day0),
                "available_at": _close(day0),
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 100000,
            },
            {
                "timestamp": _close(day1),
                "available_at": _close(day1),
                "open": 8.0,  # Below limit down 9.00!
                "high": 8.0,
                "low": 8.0,
                "close": 8.0,
                "volume": 100000,
            },
        ]
    )
    handler = DataHandler(frame, symbol)

    class BuySignalAtDay0(Strategy):
        def __init__(self) -> None:
            super().__init__("buy_day0", EventBus())
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
        BuySignalAtDay0(),
        {symbol: inst},
        {symbol: handler},
        initial_cash=Decimal("100000.00"),
        execution_model=ExecutionModel.NEXT_BAR_OPEN,
        commission_calc=StockACommission(),
        slippage_model=FixedSlippage(ZERO),
    )

    result = engine.run()
    assert len(result.fills) == 0
    assert result.execution_timing["limit_blocked_count"] >= 1


def test_sell_above_limit_up_is_blocked():
    """Previous close = 10.0, limit_pct = 0.10 => [9.00, 11.00].
    Next day Open = 12.00 (above limit up).
    SELL order must be strictly blocked by price limit validation with limit_blocked_count >= 1!
    """
    symbol = Symbol("600519")
    inst = make_stock(str(symbol), "Stock")
    day0 = date(2024, 1, 2)
    day1 = date(2024, 1, 3)
    frame = pd.DataFrame(
        [
            {
                "timestamp": _close(day0),
                "available_at": _close(day0),
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 100000,
            },
            {
                "timestamp": _close(day1),
                "available_at": _close(day1),
                "open": 12.0,  # Above limit up 11.00!
                "high": 12.0,
                "low": 12.0,
                "close": 12.0,
                "volume": 100000,
            },
        ]
    )
    handler = DataHandler(frame, symbol)

    class SellSignalAtDay0(Strategy):
        def __init__(self) -> None:
            super().__init__("sell_day0", EventBus())
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
                        target_weight=Decimal("0.0"),  # liquidate to 0
                        price=event.close,
                    )
                )

    engine = BacktestEngine(
        SellSignalAtDay0(),
        {symbol: inst},
        {symbol: handler},
        initial_cash=Decimal("100000.00"),
        execution_model=ExecutionModel.NEXT_BAR_OPEN,
        commission_calc=StockACommission(),
        slippage_model=FixedSlippage(ZERO),
    )
    # Seed position on day 0
    from domain.position import Position

    pos = Position(symbol)
    pos.quantity = Decimal("1000")
    engine.portfolio.positions[symbol] = pos

    result = engine.run()
    assert len(result.fills) == 0
    assert result.execution_timing["limit_blocked_count"] >= 1


def test_next_bar_open_future_volume_perturbation():
    """Future volume perturbation test:
    Under NEXT_BAR_OPEN, changing day 2 full-day volume from 100,000 to 0
    must NOT change the open trading permission when open-visible status is normal!
    """
    symbol = Symbol("600519")
    inst = make_stock(str(symbol), "Stock")
    day0 = date(2024, 1, 2)
    day1 = date(2024, 1, 3)

    def _run_with_volume(v: int) -> int:
        frame = pd.DataFrame(
            [
                {
                    "timestamp": _close(day0),
                    "available_at": _close(day0),
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": _close(day1),
                    "available_at": _close(day1),
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": v,
                },
            ]
        )
        handler = DataHandler(frame, symbol)

        class OpenSignalStrategy(Strategy):
            def __init__(self) -> None:
                super().__init__("strat", EventBus())
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

        sec_status = {
            (symbol, day0): {
                "trade_status": "1",
                "is_suspended": False,
                "is_st": False,
                "listing_date": date(2001, 8, 27),
            },
            (symbol, day1): {
                "trade_status": "1",
                "is_suspended": False,
                "is_st": False,
                "listing_date": date(2001, 8, 27),
            },
        }

        engine = BacktestEngine(
            OpenSignalStrategy(),
            {symbol: inst},
            {symbol: handler},
            initial_cash=Decimal("100000.00"),
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
            security_status=sec_status,
            strict_security_status=True,
            commission_calc=StockACommission(),
            slippage_model=FixedSlippage(ZERO),
        )
        res = engine.run()
        return len(res.fills)

    fills_with_volume = _run_with_volume(100000)
    fills_zero_volume = _run_with_volume(0)

    # Both must succeed and execute open fill because open-visible status is normal!
    assert fills_with_volume == 1
    assert fills_zero_volume == 1


def test_calendar_same_year_hole_blocks_execution():
    """A calendar snapshot missing a date within the backtest year must fail-closed."""
    from data.market_calendar import (
        MarketCalendarDay,
        MarketCalendarDayType,
        MarketCalendarSnapshot,
    )

    d4 = MarketCalendarDay(
        "2024-03-04",
        MarketCalendarDayType.TRADING_DAY,
        "trading_day",
        "Trading day",
        True,
    )
    d6 = MarketCalendarDay(
        "2024-03-06",
        MarketCalendarDayType.TRADING_DAY,
        "trading_day",
        "Trading day",
        True,
    )
    # 2024-03-05 is missing!
    snap = MarketCalendarSnapshot("SSE", 2024, "test", (d4, d6), "fp", "now")

    symbol = Symbol("600001")
    inst = make_stock(str(symbol), "Stock")
    frame = pd.DataFrame(
        [
            {
                "timestamp": datetime(2024, 3, 4, 15, tzinfo=SHANGHAI),
                "available_at": datetime(2024, 3, 4, 15, tzinfo=SHANGHAI),
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 100000,
            },
            {
                "timestamp": datetime(2024, 3, 6, 15, tzinfo=SHANGHAI),
                "available_at": datetime(2024, 3, 6, 15, tzinfo=SHANGHAI),
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 100000,
            },
        ]
    )
    handler = DataHandler(frame, symbol)
    engine = BacktestEngine(
        OneShotSignalStrategy(Decimal("0.5"), symbol),
        {symbol: inst},
        {symbol: handler},
        initial_cash=Decimal("100000.00"),
        trading_calendar=snap,
    )
    with pytest.raises(
        ValueError, match="trading_calendar_coverage_incomplete:date_2024-03-05_missing"
    ):
        engine.run()


def test_mature_stock_does_not_require_historical_calendar_back_to_ipo():
    """A stock listed years ago (e.g. 600519 listed in 2001) does NOT require
    the trading calendar to backfill back to 2001. It safely recognizes mature status.
    """
    from data.market_calendar import build_static_market_calendar_snapshot

    snap_2024 = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2024,
        provider="test",
        open_dates=["2024-01-02", "2024-01-03"],
    )
    symbol = Symbol("600519")
    inst = make_stock(str(symbol), "Moutai")
    frame = pd.DataFrame(
        [
            {
                "timestamp": datetime(2024, 1, 2, 15, tzinfo=SHANGHAI),
                "available_at": datetime(2024, 1, 2, 15, tzinfo=SHANGHAI),
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 100000,
            },
            {
                "timestamp": datetime(2024, 1, 3, 15, tzinfo=SHANGHAI),
                "available_at": datetime(2024, 1, 3, 15, tzinfo=SHANGHAI),
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 100000,
            },
        ]
    )
    handler = DataHandler(frame, symbol)
    sec_status = {
        (symbol, date(2024, 1, 2)): {
            "listing_date": date(2001, 8, 27),
            "trade_status": "1",
            "is_suspended": False,
            "is_st": False,
        },
        (symbol, date(2024, 1, 3)): {
            "listing_date": date(2001, 8, 27),
            "trade_status": "1",
            "is_suspended": False,
            "is_st": False,
        },
    }
    engine = BacktestEngine(
        OneShotSignalStrategy(Decimal("0.5"), symbol),
        {symbol: inst},
        {symbol: handler},
        initial_cash=Decimal("100000.00"),
        trading_calendar=snap_2024,
        security_status=sec_status,
        strict_security_status=True,
    )
    res = engine.run()
    # Runs smoothly and fills on day 3
    assert len(res.fills) == 1


def test_fill_metadata_populated_on_all_branches():
    """All successful fill branches must have execution metadata populated,
    even on the first bar in compatibility mode where previous close is None.
    """
    symbol = Symbol("600000")
    inst = make_stock(str(symbol), "SPD Bank")
    day0 = date(2024, 1, 2)
    # 1 bar only: previous is None
    frame = pd.DataFrame(
        [
            {
                "timestamp": datetime(2024, 1, 2, 15, tzinfo=SHANGHAI),
                "available_at": datetime(2024, 1, 2, 15, tzinfo=SHANGHAI),
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 100000,
            }
        ]
    )
    handler = DataHandler(frame, symbol)

    class FirstBarSignalStrategy(Strategy):
        def __init__(self):
            super().__init__("first_bar_sig", EventBus())
            self.fired = False

        def on_init(self, symbols: list[Symbol]):
            pass

        def on_data(self, event: MarketEvent):
            if not self.fired:
                self.fired = True
                from core.events import OrderEvent
                from core.types import OrderType

                self.event_bus.publish(
                    OrderEvent(
                        order_id="test_ord_1",
                        timestamp=event.timestamp,
                        symbol=symbol,
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        quantity=Decimal("100"),
                        price=Decimal("10.0"),
                    )
                )

    # Branch A: Compatibility mode, previous is None -> fills successfully AND has metadata!
    engine_compat = BacktestEngine(
        FirstBarSignalStrategy(),
        {symbol: inst},
        {symbol: handler},
        initial_cash=Decimal("100000.00"),
        execution_model=ExecutionModel.NEXT_BAR_CLOSE,
        commission_calc=StockACommission(),
        slippage_model=FixedSlippage(ZERO),
        strict_security_status=False,
    )
    res_compat = engine_compat.run()
    assert len(res_compat.fills) == 1
    fill_compat = res_compat.fills[0]
    assert fill_compat.metadata is not None
    assert fill_compat.metadata["execution_phase"] == "close"
    assert fill_compat.metadata["execution_model"] == "next_bar_close"
    assert fill_compat.metadata["session_date"] == "2024-01-02"
    assert "bar_timestamp" in fill_compat.metadata

    # Branch B: Strict mode, previous is None -> rejected with unverified_state
    engine_strict = BacktestEngine(
        FirstBarSignalStrategy(),
        {symbol: inst},
        {symbol: handler},
        initial_cash=Decimal("100000.00"),
        execution_model=ExecutionModel.NEXT_BAR_CLOSE,
        commission_calc=StockACommission(),
        slippage_model=FixedSlippage(ZERO),
        strict_security_status=True,
    )
    res_strict = engine_strict.run()
    assert len(res_strict.fills) == 0
    assert engine_strict._execution_blocked["unverified_state"] >= 1


def test_mature_stock_zero_limit_blocked_in_strict_mode_backtest():
    """In BacktestEngine with strict_security_status=True, a mature stock configured
    with limit_pct=0 CANNOT bypass statutory price limits. A -20% drop from 10 to 8 is blocked.
    In strict_security_status=False, it is permitted.
    """
    symbol = Symbol("600000")
    # Mature stock with explicit limit_pct=0
    inst_zero = make_stock(str(symbol), "SPD Bank", limit_pct=Decimal("0"))

    day0 = date(2024, 1, 2)
    day1 = date(2024, 1, 3)
    frame = pd.DataFrame(
        [
            {
                "timestamp": datetime(2024, 1, 2, 15, tzinfo=SHANGHAI),
                "available_at": datetime(2024, 1, 2, 15, tzinfo=SHANGHAI),
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 100000,
            },
            {
                "timestamp": datetime(2024, 1, 3, 15, tzinfo=SHANGHAI),
                "available_at": datetime(2024, 1, 3, 15, tzinfo=SHANGHAI),
                "open": 8.0,
                "high": 8.0,
                "low": 8.0,
                "close": 8.0,
                "volume": 100000,
            },
        ]
    )

    sec_status = {
        (symbol, day0): {
            "listing_date": date(1999, 11, 10),
            "trade_status": "1",
            "is_suspended": False,
            "is_st": False,
        },
        (symbol, day1): {
            "listing_date": date(1999, 11, 10),
            "trade_status": "1",
            "is_suspended": False,
            "is_st": False,
        },
    }

    # Strict mode: 8.0 is below 10.0 * 0.90 = 9.00 limit down -> BLOCKED!
    engine_strict = BacktestEngine(
        OneShotSignalStrategy(Decimal("0.5"), symbol),
        {symbol: inst_zero},
        {symbol: DataHandler(frame, symbol)},
        initial_cash=Decimal("100000.00"),
        execution_model=ExecutionModel.NEXT_BAR_CLOSE,
        security_status=sec_status,
        strict_security_status=True,
    )
    res_strict = engine_strict.run()
    assert len(res_strict.fills) == 0
    assert engine_strict._execution_blocked["limit"] >= 1

    # Exploratory mode: limit_pct=0 allows trading at 8.0
    engine_exploratory = BacktestEngine(
        OneShotSignalStrategy(Decimal("0.5"), symbol),
        {symbol: inst_zero},
        {symbol: DataHandler(frame, symbol)},
        initial_cash=Decimal("100000.00"),
        execution_model=ExecutionModel.NEXT_BAR_CLOSE,
        security_status=sec_status,
        strict_security_status=False,
    )
    res_exploratory = engine_exploratory.run()
    assert len(res_exploratory.fills) == 1
    assert res_exploratory.fills[0].fill_price == Decimal("8.00")
    assert res_exploratory.fills[0].metadata is not None
