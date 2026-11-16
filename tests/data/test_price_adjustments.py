"""Comprehensive unit and financial benchmark tests for corporate actions and price adjustments.

Covers:
1. Domain models & validation invariants.
2. Normalization of provider and CAS observations.
3. Mathematical formulas (P_ex, alpha, QFQ, HFQ, Volume).
4. Point-In-Time (PIT) look-ahead bias prevention.
5. Real A-share golden vectors (Moutai 600519, CMB 600036).
6. OHLC financial geometry invariants.
7. CAS serialization and persistence.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from core.types import Symbol
from data.corporate_actions import (
    AdjustmentFactor,
    AdjustmentFactorSeries,
    CorporateActionAdjustmentEngine,
    CorporateActionEvent,
    CorporateActionType,
    PriceBasis,
    adjust_ohlcv_dataframe,
    compute_daily_alpha,
    compute_ex_reference_price,
    deserialize_factor_series,
    generate_event_id,
    load_factor_series,
    normalize_facts_record,
    normalize_observation_evidence,
    save_factor_series,
    serialize_factor_series,
    verify_ohlcv_invariants,
)
from data.storage.objects import ContentAddressedObjectStore

# ============================================================================
# 1. Domain Model & Invariant Tests
# ============================================================================


def test_corporate_action_event_valid_cash_dividend():
    ev = CorporateActionEvent(
        event_id="ev_001",
        symbol=Symbol("600519"),
        event_type=CorporateActionType.CASH_DIVIDEND,
        record_date=date(2026, 6, 20),
        ex_date=date(2026, 6, 21),
        cash_dividend_per_share=Decimal("2.1675"),
    )
    assert ev.cash_dividend_per_share == Decimal("2.1675")
    assert ev.total_bonus_shares_ratio == Decimal("0")


def test_corporate_action_event_rejects_negative_or_inverted_dates():
    with pytest.raises(ValueError, match="corporate_action_record_date_after_ex_date"):
        CorporateActionEvent(
            event_id="ev_err",
            symbol=Symbol("600519"),
            event_type=CorporateActionType.CASH_DIVIDEND,
            record_date=date(2026, 6, 22),
            ex_date=date(2026, 6, 21),
            cash_dividend_per_share=Decimal("1.0"),
        )

    with pytest.raises(
        ValueError, match="corporate_action_cash_dividend_per_share_negative"
    ):
        CorporateActionEvent(
            event_id="ev_err",
            symbol=Symbol("600519"),
            event_type=CorporateActionType.CASH_DIVIDEND,
            record_date=date(2026, 6, 20),
            ex_date=date(2026, 6, 21),
            cash_dividend_per_share=Decimal("-1.0"),
        )


def test_corporate_action_composite_and_splits():
    ev_comp = CorporateActionEvent(
        event_id="ev_comp",
        symbol=Symbol("000001"),
        event_type=CorporateActionType.COMPOSITE,
        record_date=date(2026, 5, 10),
        ex_date=date(2026, 5, 11),
        cash_dividend_per_share=Decimal("0.5"),
        bonus_ratio=Decimal("0.2"),
        capitalization_ratio=Decimal("0.3"),
    )
    assert ev_comp.total_bonus_shares_ratio == Decimal("0.5")

    ev_split = CorporateActionEvent(
        event_id="ev_split",
        symbol=Symbol("000002"),
        event_type=CorporateActionType.STOCK_SPLIT,
        record_date=date(2026, 5, 10),
        ex_date=date(2026, 5, 11),
        split_ratio=Decimal("2.0"),
    )
    assert ev_split.split_ratio == Decimal("2.0")


# ============================================================================
# 2. Normalization Tests
# ============================================================================


def test_normalize_facts_record():
    record = {
        "record_date": "2026-06-20",
        "ex_date": "2026-06-21",
        "announcement_date": "2026-06-01",
        "implementation_announcement_date": "2026-06-15",
        "pay_date": "2026-06-21",
        "share_listing_date": None,
        "cash_dividend_before_tax": "0.50",
        "bonus_share_ratio": "0.0",
        "capitalization_ratio": "0.0",
        "implementation_status": "实施",
    }
    events = normalize_facts_record(record, "600000")
    assert len(events) == 1
    assert events[0].event_type == CorporateActionType.CASH_DIVIDEND
    assert events[0].cash_dividend_per_share == Decimal("0.50")
    assert events[0].record_date == date(2026, 6, 20)
    assert events[0].ex_date == date(2026, 6, 21)


def test_normalize_observation_evidence():
    evidence = {
        "schema_version": "karkinos.corporate_action_evidence.v1",
        "provider": "tushare",
        "available_at": "2026-06-16T08:00:00Z",
        "captured_at": "2026-06-16T08:00:00Z",
        "events": [
            {
                "symbol": "600001",
                "record_date": "2026-06-10",
                "ex_date": "2026-06-11",
                "ann_date": "2026-05-20",
                "cash_div_tax": "0.3",
                "stk_bo_rate": "0.1",
                "stk_co_rate": "0.2",
                "div_proc": "实施",
            }
        ],
    }
    events = normalize_observation_evidence(evidence)
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == CorporateActionType.COMPOSITE
    assert ev.cash_dividend_per_share == Decimal("0.3")
    assert ev.bonus_ratio == Decimal("0.1")
    assert ev.capitalization_ratio == Decimal("0.2")
    assert ev.available_at == datetime(2026, 6, 16, 8, 0, tzinfo=timezone.utc)


# ============================================================================
# 3. Mathematical Formula Tests
# ============================================================================


def test_ex_reference_price_formulas():
    # Case 1: Pure Cash Dividend (10派5元, D=0.5)
    # Pre-close = 10.0, P_ex = 10.0 - 0.5 = 9.5
    p_ex = compute_ex_reference_price(Decimal("10.0"), cash_dividend=Decimal("0.5"))
    assert p_ex == Decimal("9.5")
    alpha = compute_daily_alpha(Decimal("10.0"), p_ex)
    assert alpha == Decimal("0.95")

    # Case 2: Pure Stock Bonus (10送5股, s=0.5)
    # Pre-close = 10.0, P_ex = 10.0 / 1.5 = 6.666666666...
    p_ex_bonus = compute_ex_reference_price(Decimal("10.0"), bonus_ratio=Decimal("0.5"))
    expected_bonus = Decimal("10.0") / Decimal("1.5")
    assert p_ex_bonus == expected_bonus
    alpha_bonus = compute_daily_alpha(Decimal("10.0"), p_ex_bonus)
    assert alpha_bonus == Decimal("1.0") / Decimal("1.5")

    # Case 3: Rights Issue (10配3股 at 5元, p=0.3, P_r=5.0)
    # Pre-close = 10.0, P_ex = (10.0 + 0.3 * 5.0) / (1 + 0.3) = 11.5 / 1.3
    p_ex_rights = compute_ex_reference_price(
        Decimal("10.0"),
        rights_ratio=Decimal("0.3"),
        rights_price=Decimal("5.0"),
    )
    assert p_ex_rights == Decimal("11.5") / Decimal("1.3")

    # Case 4: Composite (10送2转3派5元: D=0.5, s=0.2, c=0.3)
    # Pre-close = 20.0, P_ex = (20.0 - 0.5) / (1 + 0.2 + 0.3) = 19.5 / 1.5 = 13.0
    p_ex_comp = compute_ex_reference_price(
        Decimal("20.0"),
        cash_dividend=Decimal("0.5"),
        bonus_ratio=Decimal("0.2"),
        capitalization_ratio=Decimal("0.3"),
    )
    assert p_ex_comp == Decimal("13.0")
    alpha_comp = compute_daily_alpha(Decimal("20.0"), p_ex_comp)
    assert alpha_comp == Decimal("13.0") / Decimal("20.0")  # 0.65


# ============================================================================
# 4. Adjustment Factor Engine & PIT Prevention Tests
# ============================================================================


def test_adjustment_factor_series_qfq_and_hfq():
    # 4 trading days: Day 0, Day 1 (record), Day 2 (ex), Day 3 (cutoff)
    dates = [
        date(2026, 4, 1),
        date(2026, 4, 2),  # Record date
        date(2026, 4, 3),  # Ex date
        date(2026, 4, 7),  # Cutoff
    ]
    prices = [Decimal("10.0"), Decimal("10.0"), Decimal("9.5"), Decimal("9.8")]
    events = [
        CorporateActionEvent(
            event_id="div_1",
            symbol=Symbol("000001"),
            event_type=CorporateActionType.CASH_DIVIDEND,
            record_date=date(2026, 4, 2),
            ex_date=date(2026, 4, 3),
            cash_dividend_per_share=Decimal("0.5"),
        )
    ]

    series = CorporateActionAdjustmentEngine.calculate_factors(
        symbol="000001",
        trading_dates=dates,
        closing_prices=prices,
        events=events,
        cutoff_date=date(2026, 4, 7),
    )

    f0 = series.get_factor(date(2026, 4, 1))
    f1 = series.get_factor(date(2026, 4, 2))
    f2 = series.get_factor(date(2026, 4, 3))
    f3 = series.get_factor(date(2026, 4, 7))

    # Single-day alphas:
    # On 4/1, 4/2: 1.0
    # On 4/3: alpha = 9.5 / 10.0 = 0.95
    # On 4/7: 1.0
    assert f0.alpha == Decimal("1.0")
    assert f1.alpha == Decimal("1.0")
    assert f2.alpha == Decimal("0.95")
    assert f3.alpha == Decimal("1.0")

    # QFQ factors (relative to cutoff 4/7 = 1.0):
    # f_qfq on 4/7 = 1.0
    # f_qfq on 4/3 = 1.0
    # f_qfq on 4/2 = 1.0 * alpha(4/3) = 0.95
    # f_qfq on 4/1 = 0.95 * alpha(4/2) = 0.95
    assert f3.qfq_factor == Decimal("1.0")
    assert f2.qfq_factor == Decimal("1.0")
    assert f1.qfq_factor == Decimal("0.95")
    assert f0.qfq_factor == Decimal("0.95")

    # HFQ factors (relative to base 4/1 = 1.0):
    # f_hfq on 4/1 = 1.0
    # f_hfq on 4/2 = 1.0
    # f_hfq on 4/3 = 1.0 / alpha(4/3) = 1 / 0.95
    # f_hfq on 4/7 = 1 / 0.95
    assert f0.hfq_factor == Decimal("1.0")
    assert f1.hfq_factor == Decimal("1.0")
    assert f2.hfq_factor == Decimal("1.0") / Decimal("0.95")
    assert f3.hfq_factor == Decimal("1.0") / Decimal("0.95")


def test_pit_lookahead_bias_prevention():
    """Verify that an event available in the future is NOT used when computing

    factors as of an earlier time.
    """
    dates = [date(2026, 4, 1), date(2026, 4, 2), date(2026, 4, 3)]
    prices = [Decimal("10.0"), Decimal("10.0"), Decimal("9.5")]

    # Event available at 2026-04-10 (future relative to 2026-04-02)
    events = [
        CorporateActionEvent(
            event_id="future_event",
            symbol=Symbol("000001"),
            event_type=CorporateActionType.CASH_DIVIDEND,
            record_date=date(2026, 4, 2),
            ex_date=date(2026, 4, 3),
            cash_dividend_per_share=Decimal("0.5"),
            available_at=datetime(2026, 4, 10, 8, 0, tzinfo=timezone.utc),
        )
    ]

    # Querying as of 2026-04-02 15:00: Event NOT yet available!
    series_past = CorporateActionAdjustmentEngine.calculate_factors(
        symbol="000001",
        trading_dates=dates,
        closing_prices=prices,
        events=events,
        as_of_time=datetime(2026, 4, 2, 15, 0, tzinfo=timezone.utc),
    )
    # Factor on 4/2 must be 1.0 (no knowledge of dividend)
    assert series_past.get_factor(date(2026, 4, 2)).qfq_factor == Decimal("1.0")

    # Querying as of 2026-04-11: Event is now available!
    series_present = CorporateActionAdjustmentEngine.calculate_factors(
        symbol="000001",
        trading_dates=dates,
        closing_prices=prices,
        events=events,
        as_of_time=datetime(2026, 4, 11, 8, 0, tzinfo=timezone.utc),
    )
    # Factor on 4/2 is now adjusted to 0.95
    assert series_present.get_factor(date(2026, 4, 2)).qfq_factor == Decimal("0.95")


# ============================================================================
# 5. Real A-Share Historical Benchmarks
# ============================================================================


def test_benchmark_kweichow_moutai_2022():
    """贵州茅台 (600519) 2021年度分红实施：

    - 方案：10派216.75元（每股派息 21.675 元）
    - 股权登记日：2022-06-29
    - 除权除息日：2022-06-30
    - 登记日收盘价 (Pre-close)：2049.00 元
    - 除权参考价 P_ex = 2049.00 - 21.675 = 2027.325 元
    - 调整系数 alpha = 2027.325 / 2049.00 = 0.989421669...
    """
    pre_close = Decimal("2049.00")
    cash_div = Decimal("21.675")

    p_ex = compute_ex_reference_price(pre_close, cash_dividend=cash_div)
    assert p_ex == Decimal("2027.325")

    alpha = compute_daily_alpha(pre_close, p_ex)
    assert abs(float(alpha) - (2027.325 / 2049.00)) < 1e-10


def test_benchmark_china_merchants_bank_2023():
    """招商银行 (600036) 2022年度分红实施：

    - 方案：10派17.38元（每股派息 1.738 元）
    - 股权登记日：2023-07-12
    - 除权除息日：2023-07-13
    - 登记日收盘价 (Pre-close)：33.00 元
    - 除权参考价 P_ex = 33.00 - 1.738 = 31.262 元
    - 调整系数 alpha = 31.262 / 33.00 = 0.947333333...
    """
    pre_close = Decimal("33.00")
    cash_div = Decimal("1.738")

    p_ex = compute_ex_reference_price(pre_close, cash_dividend=cash_div)
    assert p_ex == Decimal("31.262")

    alpha = compute_daily_alpha(pre_close, p_ex)
    assert abs(float(alpha) - (31.262 / 33.00)) < 1e-10


# ============================================================================
# 6. OHLC Price Series Adjustments & Invariants
# ============================================================================


def test_adjust_ohlcv_dataframe_invariants_and_turnover():
    # Construct a raw dataframe with a 10送10 bonus event
    # On ex-date, price drops by half, volume doubles
    dates = [date(2026, 5, 1), date(2026, 5, 2)]
    df = pd.DataFrame(
        {
            "trade_date": dates,
            "open": [20.0, 10.0],
            "high": [22.0, 11.0],
            "low": [19.0, 9.5],
            "close": [20.0, 10.0],
            "volume": [10000.0, 20000.0],
        }
    )

    events = [
        CorporateActionEvent(
            event_id="bonus_split",
            symbol=Symbol("000002"),
            event_type=CorporateActionType.STOCK_DIVIDEND,
            record_date=date(2026, 5, 1),
            ex_date=date(2026, 5, 2),
            bonus_ratio=Decimal("1.0"),  # 10送10
        )
    ]

    series = CorporateActionAdjustmentEngine.calculate_factors(
        symbol="000002",
        trading_dates=dates,
        closing_prices=[Decimal("20.0"), Decimal("10.0")],
        events=events,
        cutoff_date=date(2026, 5, 2),
    )

    qfq_df = adjust_ohlcv_dataframe(df, series, basis=PriceBasis.FORWARD)

    # 1. Check invariants
    verify_ohlcv_invariants(qfq_df)

    # 2. Check Day 1 adjusted prices:
    # 20.0 * 0.5 = 10.0
    assert qfq_df.loc[0, "close"] == 10.0
    assert qfq_df.loc[0, "open"] == 10.0
    assert qfq_df.loc[0, "high"] == 11.0
    assert qfq_df.loc[0, "low"] == 9.5

    # 3. Check Day 1 adjusted volume:
    # Raw volume 10000 * 2.0 = 20000
    assert qfq_df.loc[0, "volume"] == 20000.0

    # 4. Check Turnover invariance:
    # Raw turnover Day 1: 20.0 * 10000 = 200,000
    # QFQ turnover Day 1: 10.0 * 20000 = 200,000!
    raw_turnover = df.loc[0, "close"] * df.loc[0, "volume"]
    qfq_turnover = qfq_df.loc[0, "close"] * qfq_df.loc[0, "volume"]
    assert raw_turnover == qfq_turnover


# ============================================================================
# 7. CAS Serialization & Persistence Tests
# ============================================================================


def test_factor_store_cas_roundtrip(tmp_path):
    store = ContentAddressedObjectStore(tmp_path / "cas")
    dates = [date(2026, 4, 1), date(2026, 4, 2)]
    prices = [Decimal("10.0"), Decimal("9.5")]
    events = [
        CorporateActionEvent(
            event_id="ev_cas",
            symbol=Symbol("600000"),
            event_type=CorporateActionType.CASH_DIVIDEND,
            record_date=date(2026, 4, 1),
            ex_date=date(2026, 4, 2),
            cash_dividend_per_share=Decimal("0.5"),
        )
    ]
    series = CorporateActionAdjustmentEngine.calculate_factors(
        symbol="600000",
        trading_dates=dates,
        closing_prices=prices,
        events=events,
    )

    ref = save_factor_series(store, series)
    loaded = load_factor_series(store, ref)

    assert loaded.symbol == series.symbol
    assert loaded.cutoff_date == series.cutoff_date
    assert len(loaded.factors) == len(series.factors)
    for orig, res in zip(series.factors, loaded.factors):
        assert orig.trade_date == res.trade_date
        assert orig.alpha == res.alpha
        assert orig.qfq_factor == res.qfq_factor
        assert orig.hfq_factor == res.hfq_factor
        assert orig.volume_factor == res.volume_factor


# ============================================================================
# 8. Advanced Edge Cases (Adjacent Days, Multi-Actions, Determinism)
# ============================================================================


def test_adjacent_trading_days_corporate_actions():
    """Verify consecutive corporate actions on adjacent trading days."""
    dates = [
        date(2026, 4, 1),
        date(2026, 4, 2),  # Ex-dividend 1 (0.5 RMB)
        date(2026, 4, 3),  # Ex-bonus 2 (10送5)
        date(2026, 4, 7),  # Cutoff
    ]
    prices = [Decimal("10.0"), Decimal("9.5"), Decimal("6.333333"), Decimal("6.5")]
    events = [
        CorporateActionEvent(
            event_id="ev_day2",
            symbol=Symbol("000001"),
            event_type=CorporateActionType.CASH_DIVIDEND,
            record_date=date(2026, 4, 1),
            ex_date=date(2026, 4, 2),
            cash_dividend_per_share=Decimal("0.5"),
        ),
        CorporateActionEvent(
            event_id="ev_day3",
            symbol=Symbol("000001"),
            event_type=CorporateActionType.STOCK_DIVIDEND,
            record_date=date(2026, 4, 2),
            ex_date=date(2026, 4, 3),
            bonus_ratio=Decimal("0.5"),
        ),
    ]

    series = CorporateActionAdjustmentEngine.calculate_factors(
        symbol="000001",
        trading_dates=dates,
        closing_prices=prices,
        events=events,
        cutoff_date=date(2026, 4, 7),
    )

    f_day1 = series.get_factor(date(2026, 4, 1))
    f_day2 = series.get_factor(date(2026, 4, 2))
    f_day3 = series.get_factor(date(2026, 4, 3))
    f_day4 = series.get_factor(date(2026, 4, 7))

    # Day 2 alpha = 9.5 / 10.0 = 0.95
    # Day 3 alpha = (9.5 / 1.5) / 9.5 = 1 / 1.5
    alpha_day2 = Decimal("0.95")
    alpha_day3 = Decimal("1.0") / Decimal("1.5")

    assert abs(f_day2.alpha - alpha_day2) < Decimal("1e-6")
    assert abs(f_day3.alpha - alpha_day3) < Decimal("1e-6")

    # QFQ factors:
    # f_day4 = 1.0
    # f_day3 = 1.0
    # f_day2 = f_day3 * alpha_day3 = 1 / 1.5
    # f_day1 = f_day2 * alpha_day2 = 0.95 / 1.5
    assert f_day4.qfq_factor == Decimal("1.0")
    assert f_day3.qfq_factor == Decimal("1.0")
    assert abs(f_day2.qfq_factor - (Decimal("1.0") / Decimal("1.5"))) < Decimal("1e-6")
    expected_f1 = Decimal("0.95") / Decimal("1.5")
    assert abs(f_day1.qfq_factor - expected_f1) < Decimal("1e-6")


def test_multiple_actions_on_same_ex_date():
    """Verify aggregating separate cash and bonus events on the same ex-date."""
    dates = [date(2026, 4, 1), date(2026, 4, 2)]
    prices = [Decimal("20.0"), Decimal("13.0")]
    events = [
        CorporateActionEvent(
            event_id="ev_cash",
            symbol=Symbol("000001"),
            event_type=CorporateActionType.CASH_DIVIDEND,
            record_date=date(2026, 4, 1),
            ex_date=date(2026, 4, 2),
            cash_dividend_per_share=Decimal("0.5"),
        ),
        CorporateActionEvent(
            event_id="ev_bonus",
            symbol=Symbol("000001"),
            event_type=CorporateActionType.STOCK_DIVIDEND,
            record_date=date(2026, 4, 1),
            ex_date=date(2026, 4, 2),
            bonus_ratio=Decimal("0.2"),
        ),
        CorporateActionEvent(
            event_id="ev_capital",
            symbol=Symbol("000001"),
            event_type=CorporateActionType.CAPITALIZATION,
            record_date=date(2026, 4, 1),
            ex_date=date(2026, 4, 2),
            capitalization_ratio=Decimal("0.3"),
        ),
    ]

    series = CorporateActionAdjustmentEngine.calculate_factors(
        symbol="000001",
        trading_dates=dates,
        closing_prices=prices,
        events=events,
        cutoff_date=date(2026, 4, 2),
    )

    f_ex = series.get_factor(date(2026, 4, 2))
    # Combined P_ex = (20.0 - 0.5) / (1 + 0.2 + 0.3) = 19.5 / 1.5 = 13.0
    assert f_ex.ex_price == Decimal("13.0")
    assert f_ex.alpha == Decimal("13.0") / Decimal("20.0")  # 0.65
    assert set(f_ex.event_ids) == {"ev_cash", "ev_bonus", "ev_capital"}


def test_factor_calculation_determinism():
    """Verify identical inputs yield exact deterministic results across runs."""
    dates = [date(2026, 4, 1), date(2026, 4, 2), date(2026, 4, 3)]
    prices = [Decimal("10.0"), Decimal("9.5"), Decimal("9.6")]
    events = [
        CorporateActionEvent(
            event_id="ev_det",
            symbol=Symbol("600000"),
            event_type=CorporateActionType.CASH_DIVIDEND,
            record_date=date(2026, 4, 1),
            ex_date=date(2026, 4, 2),
            cash_dividend_per_share=Decimal("0.5"),
        )
    ]

    s1 = CorporateActionAdjustmentEngine.calculate_factors(
        symbol="600000",
        trading_dates=dates,
        closing_prices=prices,
        events=events,
    )
    s2 = CorporateActionAdjustmentEngine.calculate_factors(
        symbol="600000",
        trading_dates=dates,
        closing_prices=prices,
        events=events,
    )

    p1 = serialize_factor_series(s1)
    p2 = serialize_factor_series(s2)
    assert p1 == p2
