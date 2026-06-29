"""Instrument — 标的资产，frozen dataclass，所有资产差异通过字段值表达。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.types import AssetClass, CommissionType, Settlement, Symbol


@dataclass(frozen=True)
class Instrument:
    """标的资产定义。

    所有资产差异通过字段值表达，下游无需 isinstance 判断。
    """

    symbol: Symbol
    name: str
    asset_class: AssetClass
    commission_type: CommissionType
    settlement: Settlement
    lot_size: Decimal  # 交易手数（股票/ETF=100, 黄金=1）
    price_tick: Decimal  # 最小价格变动单位
    limit_pct: Decimal  # 涨跌幅限制（0 表示无限制）

    @property
    def is_t_plus_1(self) -> bool:
        return self.settlement == Settlement.T_PLUS_1


# ---------- 工厂函数 ----------


def make_stock(
    symbol: str, name: str, *, limit_pct: Decimal | None = None
) -> Instrument:
    """创建 A 股标的。"""
    from core.types import GEM_LIMIT_PCT, MAIN_BOARD_LIMIT_PCT

    if limit_pct is None:
        # 简单判断：6/0 开头为主板，3/68 开头为创业板/科创板
        if symbol.startswith(("3", "68")):
            limit_pct = GEM_LIMIT_PCT
        else:
            limit_pct = MAIN_BOARD_LIMIT_PCT

    return Instrument(
        symbol=Symbol(symbol),
        name=name,
        asset_class=AssetClass.STOCK,
        commission_type=CommissionType.STOCK_A,
        settlement=Settlement.T_PLUS_1,
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
        limit_pct=limit_pct,
    )


def make_etf(symbol: str, name: str) -> Instrument:
    """创建 ETF 标的。"""
    return Instrument(
        symbol=Symbol(symbol),
        name=name,
        asset_class=AssetClass.FUND,
        commission_type=CommissionType.FUND_ETF,
        settlement=Settlement.T_PLUS_1,
        lot_size=Decimal("100"),
        price_tick=Decimal("0.001"),
        limit_pct=Decimal("0.10"),
    )


def make_open_end_fund(symbol: str, name: str) -> Instrument:
    """创建开放式基金标的。"""
    return Instrument(
        symbol=Symbol(symbol),
        name=name,
        asset_class=AssetClass.FUND,
        commission_type=CommissionType.FUND_OPENEND,
        settlement=Settlement.T_PLUS_0,
        lot_size=Decimal("1"),
        price_tick=Decimal("0.0001"),
        limit_pct=Decimal("0"),
    )


def make_gold_spot(symbol: str = "AU9999", name: str = "黄金现货") -> Instrument:
    """创建黄金现货标的。"""
    return Instrument(
        symbol=Symbol(symbol),
        name=name,
        asset_class=AssetClass.GOLD,
        commission_type=CommissionType.GOLD_SPOT,
        settlement=Settlement.T_PLUS_0,
        lot_size=Decimal("1"),
        price_tick=Decimal("0.02"),
        limit_pct=Decimal("0"),
    )


def make_bond(symbol: str, name: str) -> Instrument:
    """创建交易所债券标的。"""
    return Instrument(
        symbol=Symbol(symbol),
        name=name,
        asset_class=AssetClass.BOND,
        commission_type=CommissionType.BOND_EXCHANGE,
        settlement=Settlement.T_PLUS_0,
        lot_size=Decimal("10"),
        price_tick=Decimal("0.001"),
        limit_pct=Decimal("0"),
    )


def make_index(symbol: str, name: str) -> Instrument:
    """创建只读市场指数标的。"""
    return Instrument(
        symbol=Symbol(symbol),
        name=name,
        asset_class=AssetClass.INDEX,
        commission_type=CommissionType.STOCK_A,
        settlement=Settlement.T_PLUS_0,
        lot_size=Decimal("1"),
        price_tick=Decimal("0.01"),
        limit_pct=Decimal("0"),
    )
