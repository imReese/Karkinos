"""Commission 单元测试。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.types import OrderSide
from execution.commission import (
    BondExchangeCommission,
    ETFCommission,
    GoldSpotCommission,
    StockACommission,
)


class TestStockACommission:
    def test_buy_fee_breakdown_includes_rule_id_and_components(self):
        """买入费用拆分保留佣金、过户费、总费用和规则 id。"""
        calc = StockACommission(
            commission_rate=Decimal("0.00015"),
            min_commission=Decimal("5"),
            fee_rule_id="cn_stock_a_local_v1",
        )

        breakdown = calc.breakdown(OrderSide.BUY, Decimal("16.25"), Decimal("200"))

        assert breakdown.gross_amount == Decimal("3250.00")
        assert breakdown.commission == Decimal("5")
        assert breakdown.stamp_tax == Decimal("0")
        assert breakdown.transfer_fee == Decimal("0.032500")
        assert breakdown.other_fees == Decimal("0")
        assert breakdown.total_fee == Decimal("5.032500")
        assert breakdown.fee_rule_id == "cn_stock_a_local_v1"
        assert breakdown.limitations == (
            "transfer_fee_exchange_not_split",
            "broker_regulatory_fees_assumed_absorbed",
        )

    def test_sell_fee_breakdown_includes_stamp_tax(self):
        """卖出费用拆分包含印花税。"""
        calc = StockACommission(
            commission_rate=Decimal("0.00015"),
            min_commission=Decimal("5"),
            fee_rule_id="cn_stock_a_local_v1",
        )

        breakdown = calc.breakdown(OrderSide.SELL, Decimal("16.25"), Decimal("200"))

        assert breakdown.gross_amount == Decimal("3250.00")
        assert breakdown.commission == Decimal("5")
        assert breakdown.stamp_tax == Decimal("1.625000")
        assert breakdown.transfer_fee == Decimal("0.032500")
        assert breakdown.other_fees == Decimal("0")
        assert breakdown.total_fee == Decimal("6.657500")
        assert breakdown.fee_rule_id == "cn_stock_a_local_v1"

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

    def test_exchange_specific_transfer_fee_rates_can_be_configured(self):
        """A 股费用模型可以显式表达不同交易所过户费口径。"""
        shanghai = StockACommission(
            commission_rate=Decimal("0.00015"),
            min_commission=Decimal("5"),
            transfer_fee_rate=Decimal("0.00001"),
            exchange="shanghai",
            exchange_transfer_fee_rates={
                "shanghai": Decimal("0.00001"),
                "shenzhen": Decimal("0"),
            },
            fee_rule_id="cn_stock_a_exchange_split_v1",
        )
        shenzhen = StockACommission(
            commission_rate=Decimal("0.00015"),
            min_commission=Decimal("5"),
            transfer_fee_rate=Decimal("0.00001"),
            exchange="shenzhen",
            exchange_transfer_fee_rates={
                "shanghai": Decimal("0.00001"),
                "shenzhen": Decimal("0"),
            },
            fee_rule_id="cn_stock_a_exchange_split_v1",
        )

        shanghai_breakdown = shanghai.breakdown(
            OrderSide.BUY, Decimal("10"), Decimal("1000")
        )
        shenzhen_breakdown = shenzhen.breakdown(
            OrderSide.BUY, Decimal("10"), Decimal("1000")
        )

        assert shanghai_breakdown.transfer_fee == Decimal("0.10000")
        assert shenzhen_breakdown.transfer_fee == Decimal("0")
        assert shanghai_breakdown.total_fee == Decimal("5.10000")
        assert shenzhen_breakdown.total_fee == Decimal("5")
        assert shanghai_breakdown.fee_rule_id == "cn_stock_a_exchange_split_v1"
        assert shenzhen_breakdown.fee_rule_id == "cn_stock_a_exchange_split_v1"

    def test_default_stock_a_transfer_fee_keeps_legacy_exchange_unsplit_limit(self):
        """默认 A 股费用数字和未拆交易所限制保持兼容。"""
        breakdown = StockACommission().breakdown(
            OrderSide.BUY, Decimal("10"), Decimal("1000")
        )

        assert breakdown.transfer_fee == Decimal("0.10000")
        assert breakdown.total_fee == Decimal("5.10000")
        assert "transfer_fee_exchange_not_split" in breakdown.limitations


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
    def test_bond_fee_breakdown_uses_structured_components(self):
        """债券/可转债费用拆分保留佣金和规则 id，不伪造印花税或过户费。"""
        calc = BondExchangeCommission(
            commission_rate=Decimal("0.00004"),
            min_commission=Decimal("1"),
            fee_rule_id="cn_bond_exchange_local_v1",
        )

        breakdown = calc.breakdown(OrderSide.SELL, Decimal("100"), Decimal("1000"))

        assert breakdown.gross_amount == Decimal("100000")
        assert breakdown.commission == Decimal("4.00000")
        assert breakdown.stamp_tax == Decimal("0")
        assert breakdown.transfer_fee == Decimal("0")
        assert breakdown.other_fees == Decimal("0")
        assert breakdown.total_fee == Decimal("4.00000")
        assert breakdown.fee_rule_id == "cn_bond_exchange_local_v1"
        assert breakdown.limitations == ("bond_fee_rules_need_broker_confirmation",)

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
