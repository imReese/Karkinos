"""Commission 单元测试。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.types import OrderSide
from execution.commission import (
    StockACommission,
    ETFCommission,
    GoldSpotCommission,
    BondExchangeCommission,
)


class TestStockACommission:
    def test_buy_commission(self):
        """买入佣金 = max(金额×佣金率, 5) + 过户费。"""
        calc = StockACommission()
        # 100 股 × 10 元 = 1000 元
        # 佣金 = max(1000 * 0.0003, 5) = 5
        # 过户费 = 1000 * 0.00001 = 0.01
        # 总计 = 5 + 0.01 = 5.01
        commission = calc.calculate(OrderSide.BUY, Decimal("10"), Decimal("100"))
        assert commission == Decimal("5.01")

    def test_sell_commission_with_stamp_tax(self):
        """卖出含印花税。"""
        calc = StockACommission()
        # 100 股 × 1800 元 = 180000 元
        # 佣金 = max(180000 * 0.0003, 5) = 54
        # 印花税 = 180000 * 0.0005 = 90
        # 过户费 = 180000 * 0.00001 = 1.8
        # 总计 = 54 + 90 + 1.8 = 145.8
        commission = calc.calculate(OrderSide.SELL, Decimal("1800"), Decimal("100"))
        assert commission == Decimal("145.8")

    def test_large_amount_commission(self):
        """大额交易佣金。"""
        calc = StockACommission()
        # 1000 股 × 1800 元 = 1800000 元
        # 佣金 = 1800000 * 0.0003 = 540
        # 印花税 = 1800000 * 0.0005 = 900
        # 过户费 = 1800000 * 0.00001 = 18
        # 总计 = 540 + 900 + 18 = 1458
        commission = calc.calculate(OrderSide.SELL, Decimal("1800"), Decimal("1000"))
        assert commission == Decimal("1458")


class TestETFCommission:
    def test_etf_no_stamp_tax(self):
        """ETF 无印花税。"""
        calc = ETFCommission()
        buy_comm = calc.calculate(OrderSide.BUY, Decimal("4.0"), Decimal("100"))
        sell_comm = calc.calculate(OrderSide.SELL, Decimal("4.0"), Decimal("100"))
        # 买入和卖出佣金相同（都只有券商佣金+过户费，无印花税）
        assert buy_comm == sell_comm

    def test_etf_min_commission(self):
        """ETF 最低佣金 5 元。"""
        calc = ETFCommission()
        # 100 股 × 4 元 = 400 元
        # 佣金 = max(400 * 0.0003, 5) = 5
        # 过户费 = 400 * 0.00001 = 0.004
        # 总计 = 5.004
        commission = calc.calculate(OrderSide.BUY, Decimal("4.0"), Decimal("100"))
        assert commission == Decimal("5.004")


class TestGoldSpotCommission:
    def test_gold_commission(self):
        calc = GoldSpotCommission()
        # 1 手 × 450 元 = 450 元
        # 佣金 = 450 * 0.0008 = 0.36
        commission = calc.calculate(OrderSide.BUY, Decimal("450"), Decimal("1"))
        assert commission == Decimal("0.36")


class TestBondExchangeCommission:
    def test_bond_min_commission(self):
        """债券最低佣金 1 元。"""
        calc = BondExchangeCommission()
        # 小额：金额 × 万0.4 < 1，取 1
        commission = calc.calculate(OrderSide.BUY, Decimal("100"), Decimal("1"))
        assert commission == Decimal("1")

    def test_bond_large_commission(self):
        """大额债券交易。"""
        calc = BondExchangeCommission()
        # 1000 张 × 100 元 = 100000 元
        # 佣金 = 100000 * 0.00004 = 4
        commission = calc.calculate(OrderSide.BUY, Decimal("100"), Decimal("1000"))
        assert commission == Decimal("4")
