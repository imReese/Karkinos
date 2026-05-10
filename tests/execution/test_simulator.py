"""SimulatedExecution 单元测试。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from core.events import OrderEvent
from core.types import OrderSide, OrderType, Symbol
from execution.commission import ETFCommission, StockACommission
from execution.simulator import SimulatedExecution
from execution.slippage import FixedSlippage, PercentSlippage, TickSlippage


class TestSimulatedExecution:
    def test_execute_market_order(self):
        exec_engine = SimulatedExecution()
        order = OrderEvent(
            timestamp=datetime(2024, 1, 1),
            order_id="ORD001",
            symbol=Symbol("600519"),
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            price=Decimal("1800"),
        )
        fill = exec_engine.execute(order)
        assert fill is not None
        assert fill.symbol == Symbol("600519")
        assert fill.side == OrderSide.BUY
        assert fill.fill_quantity == Decimal("100")
        assert fill.commission > Decimal("0")

    def test_execute_with_slippage(self):
        slippage = FixedSlippage(Decimal("0.01"))
        exec_engine = SimulatedExecution(slippage_model=slippage)
        order = OrderEvent(
            timestamp=datetime(2024, 1, 1),
            order_id="ORD001",
            symbol=Symbol("600519"),
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            price=Decimal("1800"),
        )
        fill = exec_engine.execute(order)
        # 买入滑点加价
        assert fill.fill_price == Decimal("1800.01")

    def test_execute_sell_with_slippage(self):
        slippage = FixedSlippage(Decimal("0.01"))
        exec_engine = SimulatedExecution(slippage_model=slippage)
        order = OrderEvent(
            timestamp=datetime(2024, 1, 1),
            order_id="ORD001",
            symbol=Symbol("600519"),
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            price=Decimal("1800"),
        )
        fill = exec_engine.execute(order)
        # 卖出滑点减价
        assert fill.fill_price == Decimal("1799.99")

    def test_execute_with_etf_commission(self):
        """ETF 佣金无印花税。"""
        exec_engine = SimulatedExecution(commission_calc=ETFCommission())
        order = OrderEvent(
            timestamp=datetime(2024, 1, 1),
            order_id="ORD001",
            symbol=Symbol("510300"),
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            price=Decimal("4.0"),
        )
        fill = exec_engine.execute(order)
        # ETF 佣金 = max(400 * 0.0003, 5) + 过户费 = 5 + 0.004 ≈ 5.004
        assert fill.commission > Decimal("0")

    def test_tick_slippage_adds_for_buy_and_subtracts_for_sell(self):
        slippage = TickSlippage(ticks=2, tick_size=Decimal("0.01"))

        assert slippage.apply(
            Decimal("10.00"), OrderSide.BUY, Decimal("100")
        ) == Decimal("10.02")
        assert slippage.apply(
            Decimal("10.00"), OrderSide.SELL, Decimal("100")
        ) == Decimal("9.98")

    def test_percent_slippage_adds_for_buy_and_subtracts_for_sell(self):
        slippage = PercentSlippage(Decimal("0.01"))

        assert slippage.apply(Decimal("100"), OrderSide.BUY, Decimal("100")) == Decimal(
            "101.00"
        )
        assert slippage.apply(
            Decimal("100"), OrderSide.SELL, Decimal("100")
        ) == Decimal("99.00")
