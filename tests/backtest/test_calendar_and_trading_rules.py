"""Tests for market calendar session driving and trading rules in BacktestEngine."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from backtest.engine import BacktestEngine, BacktestExecutionConfig
from core.event_bus import EventBus
from core.events import MarketEvent, OrderEvent
from core.types import ExecutionModel, OrderSide, OrderType, Symbol
from data.handler import DataHandler
from data.market_calendar import MarketCalendar, build_static_market_calendar_snapshot
from domain.instrument import make_research_stock, make_stock
from strategy.base import Strategy

_SH = ZoneInfo("Asia/Shanghai")


class DirectOrderStrategy(Strategy):
    """Strategy that places explicit orders on target dates."""

    def __init__(self, orders_by_date: dict[str, list[tuple[OrderSide, Decimal]]]):
        super().__init__("direct_order_test", EventBus())
        self.orders_by_date = orders_by_date

    def on_init(self, symbols: list[Symbol]) -> None:
        pass

    def on_data(self, event: MarketEvent) -> None:
        date_str = event.timestamp.strftime("%Y-%m-%d")
        if date_str in self.orders_by_date:
            for side, qty in self.orders_by_date[date_str]:
                self.event_bus.publish(
                    OrderEvent(
                        timestamp=event.timestamp,
                        order_id=f"ord-{date_str}-{side.value}-{qty}",
                        symbol=event.symbol,
                        side=side,
                        order_type=OrderType.MARKET,
                        quantity=qty,
                        price=event.close,
                    )
                )


def _make_bar_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize("UTC")
    return df


class TestMarketCalendarIntegration:
    def test_calendar_holiday_fails_closed(self):
        """Feeding bars on a configured market holiday must fail closed."""
        calendar = MarketCalendar(
            holidays={"2023-01-02": "New Year Holiday"},
        )
        frame = _make_bar_frame(
            [
                {
                    "timestamp": "2023-01-02 15:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
            ]
        )
        symbol = Symbol("600000")
        inst = make_stock(str(symbol), "浦发银行")
        engine = BacktestEngine(
            strategy=DirectOrderStrategy({}),
            instruments={symbol: inst},
            data_handlers={symbol: DataHandler(frame, symbol)},
            trading_calendar=calendar,
        )
        with pytest.raises(
            ValueError, match="session_bar_on_non_trading_day:2023-01-02:market_holiday"
        ):
            engine.run()

    def test_calendar_snapshot_ref_recorded(self):
        """Calendar snapshot fingerprint must be recorded in execution_timing."""
        snapshot = build_static_market_calendar_snapshot(
            exchange="SSE",
            year=2023,
            provider="static_test",
            open_dates=["2023-01-03", "2023-01-04"],
        )
        frame = _make_bar_frame(
            [
                {
                    "timestamp": "2023-01-03 15:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2023-01-04 15:00",
                    "open": 10.2,
                    "high": 10.2,
                    "low": 10.2,
                    "close": 10.2,
                    "volume": 100000,
                },
            ]
        )
        symbol = Symbol("600000")
        inst = make_stock(str(symbol), "浦发银行")
        engine = BacktestEngine(
            strategy=DirectOrderStrategy({}),
            instruments={symbol: inst},
            data_handlers={symbol: DataHandler(frame, symbol)},
            trading_calendar=snapshot,
        )
        result = engine.run()
        assert (
            result.execution_timing["calendar_snapshot_ref"]
            == snapshot.source_fingerprint
        )
        assert (
            result.execution_timing["trading_rule_policy_id"]
            == "karkinos.a_share.trading_rules.v1"
        )


class TestTradingRuleExecutionChecks:
    def test_star_market_min_lot_size_blocked(self):
        """STAR market minimum order is 200 shares; 100 shares must be rejected."""
        frame = _make_bar_frame(
            [
                {
                    "timestamp": "2023-01-03 15:00",
                    "open": 50.0,
                    "high": 50.0,
                    "low": 50.0,
                    "close": 50.0,
                    "volume": 100000,
                },
            ]
        )
        symbol = Symbol("688001")
        inst = make_research_stock(str(symbol), "华兴源创")
        # Attempt to buy 100 shares (illegal for STAR)
        strategy = DirectOrderStrategy(
            {"2023-01-03": [(OrderSide.BUY, Decimal("100"))]}
        )
        engine = BacktestEngine(
            strategy=strategy,
            instruments={symbol: inst},
            data_handlers={symbol: DataHandler(frame, symbol)},
            initial_cash=Decimal("100000"),
        )
        result = engine.run()
        assert len(result.fills) == 0
        assert result.execution_timing["lot_size_blocked_count"] == 1

    def test_star_market_legal_200_lot_executes(self):
        """Buying 200 shares on STAR market succeeds."""
        frame = _make_bar_frame(
            [
                {
                    "timestamp": "2023-01-03 15:00",
                    "open": 50.0,
                    "high": 50.0,
                    "low": 50.0,
                    "close": 50.0,
                    "volume": 100000,
                },
            ]
        )
        symbol = Symbol("688001")
        inst = make_research_stock(str(symbol), "华兴源创")
        strategy = DirectOrderStrategy(
            {"2023-01-03": [(OrderSide.BUY, Decimal("200"))]}
        )
        engine = BacktestEngine(
            strategy=strategy,
            instruments={symbol: inst},
            data_handlers={symbol: DataHandler(frame, symbol)},
            initial_cash=Decimal("100000"),
        )
        result = engine.run()
        assert len(result.fills) == 1
        assert result.fills[0].fill_quantity == Decimal("200")
        assert result.execution_timing["lot_size_blocked_count"] == 0

    def test_odd_lot_remainder_full_liquidation(self):
        """If available quantity is an odd-lot remainder (< 100), must sell all of it."""
        frame = _make_bar_frame(
            [
                {
                    "timestamp": "2023-01-03 15:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2023-01-04 15:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
            ]
        )
        symbol = Symbol("600000")
        inst = make_stock(str(symbol), "浦发银行")
        # Buy 100 shares Day 1, advance to Day 2
        # Then manually simulate partial position of 60 shares
        strategy = DirectOrderStrategy({})
        engine = BacktestEngine(
            strategy=strategy,
            instruments={symbol: inst},
            data_handlers={symbol: DataHandler(frame, symbol)},
            initial_cash=Decimal("100000"),
        )
        # Pre-seed position with 60 settled shares (e.g. after bonus share distribution / odd lot)
        engine.portfolio.advance_settlement_day(date(2023, 1, 3))
        pos = engine.portfolio.positions.setdefault(
            symbol,
            engine.portfolio.positions.get(symbol)
            or engine.portfolio.positions.get(symbol),
        )
        from domain.position import Position

        pos = Position(symbol, last_settlement_date=date(2023, 1, 3))
        pos.quantity = Decimal("60")
        pos.avg_cost = Decimal("10.0")
        engine.portfolio.positions[symbol] = pos

        # Order to sell 30 shares (illegal partial sell of odd lot remainder)
        order_partial = OrderEvent(
            timestamp=datetime(2023, 1, 4, 15, 0),
            order_id="sell-partial",
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("30"),
            price=Decimal("10.0"),
        )
        approved_partial = engine._approved_order(order_partial)
        assert approved_partial is None
        assert engine._execution_blocked["lot_size"] == 1

        # Order to sell all 60 shares (legal odd lot liquidation)
        order_all = OrderEvent(
            timestamp=datetime(2023, 1, 4, 15, 0),
            order_id="sell-all",
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("60"),
            price=Decimal("10.0"),
        )
        approved_all = engine._approved_order(order_all)
        assert approved_all is not None
        assert approved_all.quantity == Decimal("60")

    def test_available_qty_blocked_distinct_counter(self):
        """Selling more than available quantity increments both risk and available_qty counters."""
        symbol = Symbol("600000")
        inst = make_stock(str(symbol), "浦发银行")
        frame = _make_bar_frame(
            [
                {
                    "timestamp": "2023-01-03 15:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
            ]
        )
        # Attempt to sell 100 shares when holding 0 shares
        strategy = DirectOrderStrategy(
            {"2023-01-03": [(OrderSide.SELL, Decimal("100"))]}
        )
        engine = BacktestEngine(
            strategy=strategy,
            instruments={symbol: inst},
            data_handlers={symbol: DataHandler(frame, symbol)},
            initial_cash=Decimal("100000"),
        )
        result = engine.run()
        assert len(result.fills) == 0
        assert result.execution_timing["risk_blocked_count"] == 1
        assert result.execution_timing["available_qty_blocked_count"] == 1
