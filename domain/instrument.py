"""Instrument — 标的资产，frozen dataclass，所有资产差异通过字段值表达。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from core.types import (
    AssetClass,
    CommissionType,
    InstrumentType,
    Settlement,
    Symbol,
)


@dataclass(frozen=True)
class Instrument:
    """标的资产定义。

    所有资产差异通过字段值表达，下游无需 isinstance 判断。
    """

    symbol: Symbol
    name: str
    asset_class: AssetClass
    instrument_type: InstrumentType
    commission_type: CommissionType
    settlement: Settlement
    lot_size: Decimal  # 交易手数（股票/ETF=100, 黄金=1）
    price_tick: Decimal  # 最小价格变动单位
    limit_pct: Decimal  # 涨跌幅限制（0 表示无限制）

    @property
    def is_t_plus_1(self) -> bool:
        return self.settlement == Settlement.T_PLUS_1


# ---------- 工厂函数 ----------

RESEARCH_STOCK_TRADING_RULES_ID = (
    "karkinos.a_share.ordinary_session.conservative_lots.v1"
)


def a_share_identity(symbol: str) -> dict[str, str] | None:
    """Canonical ordinary A-share exchange and board identity."""
    if len(symbol) != 6 or not symbol.isdigit():
        return None
    if symbol.startswith(("600", "601", "603", "605")):
        return {"exchange": "SSE", "board": "sse_main"}
    if symbol.startswith(("688", "689")):
        return {"exchange": "SSE", "board": "star"}
    if symbol.startswith(("000", "001", "002", "003")):
        return {"exchange": "SZSE", "board": "szse_main"}
    if symbol.startswith(("300", "301")):
        return {"exchange": "SZSE", "board": "chinext"}
    if symbol.startswith(("4", "8", "92")):
        return {"exchange": "BSE", "board": "beijing"}
    return None


def entry_board_symbols(
    allowed_boards: Sequence[str], symbols: Sequence[str]
) -> set[str]:
    """Apply an entry mask without shrinking market membership or forecasts."""
    allowed = set(allowed_boards)
    return {
        symbol
        for symbol in symbols
        if (identity := a_share_identity(symbol)) is not None
        and (
            identity["board"] in allowed
            or "main" in allowed
            and identity["board"] in {"sse_main", "szse_main"}
        )
    }


def make_research_stock(symbol: str, name: str) -> Instrument:
    """Opt-in ordinary-session model for the deployment-scope research path.

    STAR trades use a legal conservative subset (multiples of 200), rather than
    claiming the exchange requires a 200-share increment. BSE trades similarly
    use multiples of 100. This factory does not establish current permissions,
    ST status, listing age, or eligibility for an ordinary-session price limit.

    Exchange rules: SSE 2026 sections 6.6/6.7; BSE 2026 sections 3.3.8/3.3.11.
    https://www.sse.com.cn/lawandrules/sselawsrules2025/fund/trading/c/c_20260424_10817739.shtml
    https://www.bse.cn/jygl_list/200028217.html
    """
    if len(symbol) != 6 or not symbol.isdigit():
        raise ValueError("research_stock_symbol_invalid")
    identity = a_share_identity(symbol)
    if identity is None:
        raise ValueError("research_stock_board_unsupported")
    if identity["board"] == "star":
        return replace(
            make_stock(symbol, name), lot_size=Decimal("200"), limit_pct=Decimal("0.20")
        )
    if identity["board"] == "beijing":
        return replace(make_stock(symbol, name), limit_pct=Decimal("0.30"))
    return make_stock(symbol, name)


def research_stock_session_blocker(
    symbol: str,
    *,
    is_st: bool | None = None,
    listing_session_count: int | None = None,
    in_delisting_period: bool | None = None,
) -> str | None:
    """Separate known exclusions from unavailable ordinary-session evidence."""
    make_research_stock(symbol, symbol)
    if is_st is True:
        return "special_treatment_excluded"
    if in_delisting_period is True:
        return "delisting_period_excluded"
    if listing_session_count is not None:
        if type(listing_session_count) is not int or listing_session_count < 1:
            raise ValueError("research_stock_listing_age_invalid")
        initial_sessions = 1 if symbol.startswith(("4", "8", "92")) else 5
        if listing_session_count <= initial_sessions:
            return "initial_listing_period_excluded"
    if (
        is_st is not False
        or in_delisting_period is not False
        or listing_session_count is None
    ):
        return "ordinary_session_state_unverified"
    return None


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
        instrument_type=InstrumentType.STOCK,
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
        instrument_type=InstrumentType.ETF,
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
        instrument_type=InstrumentType.OPEN_END_FUND,
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
        instrument_type=InstrumentType.GOLD,
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
        instrument_type=InstrumentType.BOND,
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
        instrument_type=InstrumentType.INDEX,
        commission_type=CommissionType.STOCK_A,
        settlement=Settlement.T_PLUS_0,
        lot_size=Decimal("1"),
        price_tick=Decimal("0.01"),
        limit_pct=Decimal("0"),
    )
