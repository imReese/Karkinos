"""Instrument 单元测试。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.types import AssetClass, CommissionType, Settlement
from domain.instrument import (
    Instrument,
    make_bond,
    make_etf,
    make_gold_spot,
    make_open_end_fund,
    make_stock,
)


class TestMakeStock:
    """A 股工厂函数。"""

    def test_main_board_defaults(self):
        inst = make_stock("600519", "贵州茅台")
        assert inst.symbol == "600519"
        assert inst.name == "贵州茅台"
        assert inst.asset_class == AssetClass.STOCK
        assert inst.commission_type == CommissionType.STOCK_A
        assert inst.settlement == Settlement.T_PLUS_1
        assert inst.lot_size == Decimal("100")
        assert inst.price_tick == Decimal("0.01")
        assert inst.limit_pct == Decimal("0.10")
        assert inst.is_t_plus_1 is True

    def test_gem_board_defaults(self):
        """3 开头为创业板，涨跌幅 20%。"""
        inst = make_stock("300750", "宁德时代")
        assert inst.limit_pct == Decimal("0.20")

    def test_star_board_defaults(self):
        """68 开头为科创板，涨跌幅 20%。"""
        inst = make_stock("688981", "中芯国际")
        assert inst.limit_pct == Decimal("0.20")

    def test_custom_limit_pct(self):
        inst = make_stock("600519", "贵州茅台", limit_pct=Decimal("0.05"))
        assert inst.limit_pct == Decimal("0.05")


class TestMakeETF:
    def test_etf_fields(self):
        inst = make_etf("510300", "沪深300ETF")
        assert inst.asset_class == AssetClass.FUND
        assert inst.commission_type == CommissionType.FUND_ETF
        assert inst.settlement == Settlement.T_PLUS_1
        assert inst.lot_size == Decimal("100")
        assert inst.price_tick == Decimal("0.001")
        assert inst.is_t_plus_1 is True


class TestMakeOpenEndFund:
    def test_open_end_fund_fields(self):
        inst = make_open_end_fund("000001", "华夏成长")
        assert inst.asset_class == AssetClass.FUND
        assert inst.commission_type == CommissionType.FUND_OPENEND
        assert inst.settlement == Settlement.T_PLUS_0
        assert inst.lot_size == Decimal("1")
        assert inst.is_t_plus_1 is False


class TestMakeGoldSpot:
    def test_gold_fields(self):
        inst = make_gold_spot()
        assert inst.symbol == "AU9999"
        assert inst.asset_class == AssetClass.GOLD
        assert inst.commission_type == CommissionType.GOLD_SPOT
        assert inst.settlement == Settlement.T_PLUS_0
        assert inst.lot_size == Decimal("1")
        assert inst.is_t_plus_1 is False


class TestMakeBond:
    def test_bond_fields(self):
        inst = make_bond("123456", "某债券")
        assert inst.asset_class == AssetClass.BOND
        assert inst.commission_type == CommissionType.BOND_EXCHANGE
        assert inst.settlement == Settlement.T_PLUS_0
        assert inst.lot_size == Decimal("10")


class TestInstrumentFrozen:
    def test_frozen_dataclass(self):
        inst = make_stock("600519", "贵州茅台")
        with pytest.raises(AttributeError):
            inst.symbol = "000001"  # type: ignore[misc]
