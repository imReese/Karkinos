"""Unified domain models for corporate actions and price adjustment factors.

Follows strict quantitative research standards:
- Immutable dataclasses with slots.
- Exact financial arithmetic with Decimal.
- Point-In-Time (PIT) auditability (announcement, record, ex, pay, available_at).
- Decoupled from broker execution and ledger accounting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, DecimalException, Inexact, localcontext
from enum import Enum
from typing import Any

from core.types import ZERO, Symbol


class CorporateActionType(str, Enum):
    """Supported corporate action categories for A-share securities."""

    CASH_DIVIDEND = "cash_dividend"  # 现金分红
    STOCK_DIVIDEND = "stock_dividend"  # 送红股
    CAPITALIZATION = "capitalization"  # 公积金转增股本
    RIGHTS_ISSUE = "rights_issue"  # 配股
    STOCK_SPLIT = "stock_split"  # 拆股
    REVERSE_SPLIT = "reverse_split"  # 缩股
    COMPOSITE = "composite"  # 复合方案（同时包含分红、送股和/或转增）


class PriceBasis(str, Enum):
    """Price basis options for historical bar series."""

    UNADJUSTED = "unadjusted"  # 原始未复权价格（实盘记账、撮合与结算的权威价格）
    FORWARD = "forward"  # 前复权（以最新/指定 cutoff 日为基准 1.0 向前折算）
    BACKWARD = "backward"  # 后复权（以上市或起始日为基准 1.0 向后累乘）
    POINT_IN_TIME = (
        "point_in_time"  # 历史时点复权（严格排除观察点之后的未来事件与未来可用数据）
    )


@dataclass(frozen=True, slots=True)
class CorporateActionEvent:
    """Canonical domain representation of an observed corporate action event.

    All share ratios are normalized to 'per 1 existing share' (e.g. 10送3 is 0.3).
    Cash dividends are normalized to 'CNY per 1 existing share before tax' (e.g. 10派5 is 0.5).
    """

    event_id: str
    symbol: Symbol
    event_type: CorporateActionType
    record_date: date  # 股权登记日 (R)
    ex_date: date  # 除权除息日 (E)

    # Optional lifecycle business dates
    announcement_date: date | None = None  # 预案公告日
    implementation_announcement_date: date | None = None  # 实施公告日
    pay_date: date | None = None  # 现金红利发放日
    listing_date: date | None = None  # 增发/送转股份上市交易日

    # Economic terms (all per share, in Decimal)
    cash_dividend_per_share: Decimal = ZERO  # 每股派现（含税，元/股）
    bonus_ratio: Decimal = ZERO  # 每股送红股比例（股/股）
    capitalization_ratio: Decimal = ZERO  # 每股转增股比例（股/股）
    rights_ratio: Decimal = ZERO  # 每股配股比例（股/股）
    rights_price: Decimal = ZERO  # 配股价格（元/股）
    split_ratio: Decimal = Decimal("1.0")  # 拆细/缩股乘数（>1拆股，<1缩股，1为不变）

    # Operational & PIT tracking metadata
    currency: str = "CNY"
    source: str = "canonical"
    captured_at: datetime | None = None
    available_at: datetime | None = None
    div_proc: str = "实施"  # "预案" or "实施"
    description: str = ""

    def __post_init__(self) -> None:
        if not self.event_id or not str(self.event_id).strip():
            raise ValueError("corporate_action_event_id_empty")
        if not self.symbol:
            raise ValueError("corporate_action_symbol_empty")
        if not isinstance(self.record_date, date) or not isinstance(self.ex_date, date):
            raise ValueError("corporate_action_dates_invalid")
        if self.record_date > self.ex_date:
            raise ValueError("corporate_action_record_date_after_ex_date")

        # Decimal traps and checks
        for name, val in [
            ("cash_dividend_per_share", self.cash_dividend_per_share),
            ("bonus_ratio", self.bonus_ratio),
            ("capitalization_ratio", self.capitalization_ratio),
            ("rights_ratio", self.rights_ratio),
            ("rights_price", self.rights_price),
            ("split_ratio", self.split_ratio),
        ]:
            if not isinstance(val, Decimal) or not val.is_finite():
                raise ValueError(f"corporate_action_{name}_not_finite_decimal")
            if val < ZERO and name != "split_ratio":
                raise ValueError(f"corporate_action_{name}_negative")

        if self.split_ratio <= ZERO:
            raise ValueError("corporate_action_split_ratio_must_be_positive")

        if self.rights_ratio > ZERO and self.rights_price <= ZERO:
            raise ValueError(
                "corporate_action_rights_price_required_when_rights_offered"
            )

        # Type-specific invariants
        if self.event_type == CorporateActionType.CASH_DIVIDEND:
            if self.cash_dividend_per_share <= ZERO:
                raise ValueError("cash_dividend_requires_positive_cash_amount")
        elif self.event_type == CorporateActionType.STOCK_DIVIDEND:
            if self.bonus_ratio <= ZERO:
                raise ValueError("stock_dividend_requires_positive_bonus_ratio")
        elif self.event_type == CorporateActionType.CAPITALIZATION:
            if self.capitalization_ratio <= ZERO:
                raise ValueError(
                    "capitalization_requires_positive_capitalization_ratio"
                )
        elif self.event_type == CorporateActionType.RIGHTS_ISSUE:
            if self.rights_ratio <= ZERO or self.rights_price <= ZERO:
                raise ValueError("rights_issue_requires_positive_ratio_and_price")
        elif self.event_type == CorporateActionType.STOCK_SPLIT:
            if self.split_ratio <= Decimal("1.0"):
                raise ValueError("stock_split_requires_ratio_greater_than_one")
        elif self.event_type == CorporateActionType.REVERSE_SPLIT:
            if self.split_ratio >= Decimal("1.0"):
                raise ValueError("reverse_split_requires_ratio_less_than_one")
        elif self.event_type == CorporateActionType.COMPOSITE:
            if (
                self.cash_dividend_per_share <= ZERO
                and self.bonus_ratio <= ZERO
                and self.capitalization_ratio <= ZERO
                and self.rights_ratio <= ZERO
            ):
                raise ValueError("composite_action_requires_at_least_one_positive_term")

        if self.available_at is not None and self.available_at.tzinfo is None:
            raise ValueError("corporate_action_available_at_must_be_timezone_aware")
        if self.captured_at is not None and self.captured_at.tzinfo is None:
            raise ValueError("corporate_action_captured_at_must_be_timezone_aware")

    @property
    def total_bonus_shares_ratio(self) -> Decimal:
        """Combined new shares per share from bonus and capitalization."""
        return self.bonus_ratio + self.capitalization_ratio


@dataclass(frozen=True, slots=True)
class AdjustmentFactor:
    """Exact adjustment factors for a single trading date."""

    trade_date: date
    pre_close: Decimal | None  # Closing price of record date (day before ex-date)
    ex_price: Decimal | None  # Theoretical ex-rights / ex-dividend reference price
    alpha: (
        Decimal  # Single-day adjustment multiplier P_ex / P_prev (1.0 on non-ex dates)
    )
    qfq_factor: Decimal  # Cumulative forward-adjustment factor f_qfq
    hfq_factor: Decimal  # Cumulative backward-adjustment factor f_hfq
    volume_factor: (
        Decimal  # Volume scaling multiplier (inversely related to price dilution)
    )
    event_ids: tuple[str, ...] = ()  # Event IDs active on this date

    def __post_init__(self) -> None:
        if not isinstance(self.trade_date, date):
            raise ValueError("adjustment_factor_date_invalid")
        for name, val in [
            ("alpha", self.alpha),
            ("qfq_factor", self.qfq_factor),
            ("hfq_factor", self.hfq_factor),
            ("volume_factor", self.volume_factor),
        ]:
            if not isinstance(val, Decimal) or not val.is_finite() or val <= ZERO:
                raise ValueError(f"adjustment_factor_{name}_must_be_positive_decimal")


@dataclass(frozen=True, slots=True)
class AdjustmentFactorSeries:
    """Full time-series of adjustment factors for a security."""

    symbol: Symbol
    cutoff_date: date
    factors: tuple[AdjustmentFactor, ...]
    manifest_id: str = ""

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("adjustment_factor_series_symbol_empty")
        # Ensure factors are sorted by trade_date ascending
        dates = [f.trade_date for f in self.factors]
        if dates != sorted(dates) or len(dates) != len(set(dates)):
            raise ValueError(
                "adjustment_factor_series_dates_must_be_strictly_ascending"
            )

    def get_factor(self, trade_date: date) -> AdjustmentFactor | None:
        """Lookup adjustment factor by trade date using binary search."""
        import bisect

        idx = bisect.bisect_left([f.trade_date for f in self.factors], trade_date)
        if idx < len(self.factors) and self.factors[idx].trade_date == trade_date:
            return self.factors[idx]
        return None
