"""A-share trading rules and lot size validation tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from core.types import OrderSide
from domain.instrument import make_etf, make_stock
from domain.trading_rules import (
    CHINEXT_REFORM_DATE,
    MAIN_BOARD_REFORM_DATE,
    SSE_SZSE_ST_REFORM_DATE,
    STAR_LAUNCH_DATE,
    calculate_price_limits,
    is_price_within_limits,
    resolve_trading_rules,
    validate_order_lot_size,
)


class TestTradingRuleResolution:
    def test_main_board_ordinary_and_st(self):
        d = date(2023, 1, 3)
        # Ordinary 600519
        rule = resolve_trading_rules("600519", d)
        assert rule.board == "sse_main"
        assert rule.exchange == "SSE"
        assert rule.is_tradable is True
        assert rule.has_price_limit is True
        assert rule.limit_pct == Decimal("0.10")
        assert rule.min_order_qty == Decimal("100")
        assert rule.qty_step == Decimal("100")

        # ST stock has 5%
        rule_st = resolve_trading_rules("600519", d, is_st=True)
        assert rule_st.limit_pct == Decimal("0.05")

        # Infer ST from display_name
        rule_name_st = resolve_trading_rules("600519", d, display_name="*ST 茅台")
        assert rule_name_st.limit_pct == Decimal("0.05")

    def test_main_board_st_2026_reform_dates(self):
        # Before reform: 5%
        before_date = date(2026, 7, 3)
        rule_sse_before = resolve_trading_rules("600519", before_date, is_st=True)
        assert rule_sse_before.limit_pct == Decimal("0.05")

        rule_szse_before = resolve_trading_rules("000001", before_date, is_st=True)
        assert rule_szse_before.limit_pct == Decimal("0.05")

        # On and after 2026-07-06 reform: 10%
        reform_date = SSE_SZSE_ST_REFORM_DATE
        assert reform_date == date(2026, 7, 6)
        rule_sse_after = resolve_trading_rules("600519", reform_date, is_st=True)
        assert rule_sse_after.limit_pct == Decimal("0.10")

        rule_szse_after = resolve_trading_rules("000001", reform_date, is_st=True)
        assert rule_szse_after.limit_pct == Decimal("0.10")

    def test_chinext_reform_transition(self):
        # Before reform: 10%
        before_date = date(2020, 8, 21)
        rule_before = resolve_trading_rules("300750", before_date)
        assert rule_before.board == "chinext"
        assert rule_before.limit_pct == Decimal("0.10")

        # On and after reform: 20%
        rule_after = resolve_trading_rules("300750", CHINEXT_REFORM_DATE)
        assert rule_after.limit_pct == Decimal("0.20")

    def test_star_market_rules(self):
        d = date(2021, 5, 10)
        rule = resolve_trading_rules("688981", d)
        assert rule.board == "star"
        assert rule.exchange == "SSE"
        assert rule.limit_pct == Decimal("0.20")
        assert rule.min_order_qty == Decimal("200")
        assert rule.qty_step == Decimal("200")

    def test_beijing_exchange_rules(self):
        d = date(2022, 1, 10)
        rule = resolve_trading_rules("830946", d)
        assert rule.board == "beijing"
        assert rule.exchange == "BSE"
        assert rule.limit_pct == Decimal("0.30")
        assert rule.min_order_qty == Decimal("100")

    def test_ipo_initial_period_no_price_limit(self):
        # STAR Market first 5 days
        rule_star_ipo = resolve_trading_rules(
            "688001",
            date(2019, 7, 22),
            listing_session_count=1,
        )
        assert rule_star_ipo.has_price_limit is False
        assert rule_star_ipo.limit_pct is None

        # ChiNext after reform first 5 days
        rule_gem_ipo = resolve_trading_rules(
            "300888",
            date(2020, 8, 24),
            listing_session_count=3,
        )
        assert rule_gem_ipo.has_price_limit is False
        assert rule_gem_ipo.limit_pct is None

        # Main Board after reform first 5 days
        rule_main_ipo = resolve_trading_rules(
            "601000",
            date(2023, 4, 10),
            listing_session_count=5,
        )
        assert rule_main_ipo.has_price_limit is False
        assert rule_main_ipo.limit_pct is None

        # Main Board 6th day has limit
        rule_main_day6 = resolve_trading_rules(
            "601000",
            date(2023, 4, 17),
            listing_session_count=6,
        )
        assert rule_main_day6.has_price_limit is True
        assert rule_main_day6.limit_pct == Decimal("0.10")

    def test_suspension_and_delisting(self):
        d = date(2023, 1, 3)
        # Suspended
        rule_susp = resolve_trading_rules("600519", d, is_suspended_override=True)
        assert rule_susp.is_tradable is False
        assert rule_susp.status == "suspended"
        assert rule_susp.blocker_reason == "nontrading_session_excluded"

        # Trade status == "0"
        rule_ts0 = resolve_trading_rules("600519", d, trade_status="0")
        assert rule_ts0.is_tradable is False
        assert rule_ts0.status == "suspended"

        # Not yet listed
        rule_nyl = resolve_trading_rules("600519", d, listing_date=date(2023, 1, 10))
        assert rule_nyl.is_tradable is False
        assert rule_nyl.status == "not_yet_listed"

        # Delisted
        rule_delisted = resolve_trading_rules(
            "600519", d, delist_date=date(2022, 12, 31)
        )
        assert rule_delisted.is_tradable is False
        assert rule_delisted.status == "delisted"

        # Delisting period name with 退
        rule_delist_period = resolve_trading_rules("600519", d, display_name="退市茅台")
        assert rule_delist_period.is_tradable is False
        assert rule_delist_period.status == "delisting"

    def test_strict_security_status_blocks_unverified(self):
        d = date(2023, 1, 3)
        # Without status evidence in strict mode -> unverified_state
        rule_unverified = resolve_trading_rules(
            "600519", d, strict_security_status=True
        )
        assert rule_unverified.is_tradable is False
        assert rule_unverified.status == "unverified_state"
        assert rule_unverified.blocker_reason == "trading_state_unverified"

        # With status evidence in strict mode -> tradable
        rule_verified = resolve_trading_rules(
            "600519", d, is_st=False, trade_status="1", strict_security_status=True
        )
        assert rule_verified.is_tradable is True
        assert rule_verified.status == "tradable"

    def test_etf_compatibility(self):
        d = date(2023, 1, 3)
        etf = make_etf("510300", "300ETF")
        rule = resolve_trading_rules("510300", d, instrument=etf)
        assert rule.board == "etf"
        assert rule.is_tradable is True
        assert rule.price_tick == Decimal("0.001")
        assert rule.limit_pct == Decimal("0.10")

    def test_etf_differential_price_limits(self):
        d = date(2023, 1, 3)
        # STAR ETF (588xxx) -> 20%
        star_etf = make_etf("588000", "STAR50ETF")
        rule_star_etf = resolve_trading_rules("588000", d, instrument=star_etf)
        assert rule_star_etf.limit_pct == Decimal("0.20")

        # ChiNext ETF (159915) -> 20%
        gem_etf = make_etf("159915", "ChiNextETF")
        rule_gem_etf = resolve_trading_rules("159915", d, instrument=gem_etf)
        assert rule_gem_etf.limit_pct == Decimal("0.20")

        # Main Board 50 ETF (510050) -> 10%
        main_etf = make_etf("510050", "SSE50ETF")
        rule_main_etf = resolve_trading_rules("510050", d, instrument=main_etf)
        assert rule_main_etf.limit_pct == Decimal("0.10")


class TestLotSizeValidation:
    def test_buy_lot_validation(self):
        d = date(2023, 1, 3)
        rule_main = resolve_trading_rules("600519", d)

        # Main board: minimum 100, step 100
        ok, reason = validate_order_lot_size(rule_main, OrderSide.BUY, Decimal("100"))
        assert ok is True
        assert reason is None

        ok, reason = validate_order_lot_size(rule_main, OrderSide.BUY, Decimal("200"))
        assert ok is True

        ok, reason = validate_order_lot_size(rule_main, OrderSide.BUY, Decimal("50"))
        assert ok is False
        assert reason == "order_below_minimum_lot"

        ok, reason = validate_order_lot_size(rule_main, OrderSide.BUY, Decimal("150"))
        assert ok is False
        assert reason == "order_not_multiple_of_lot_step"

        # STAR Market: minimum 200, step 200
        rule_star = resolve_trading_rules("688981", d)
        ok, reason = validate_order_lot_size(rule_star, OrderSide.BUY, Decimal("100"))
        assert ok is False
        assert reason == "order_below_minimum_lot"

        ok, reason = validate_order_lot_size(rule_star, OrderSide.BUY, Decimal("200"))
        assert ok is True

    def test_sell_lot_validation_odd_lot_liquidation(self):
        d = date(2023, 1, 3)
        rule_main = resolve_trading_rules("600519", d)

        # Exceeds available
        ok, reason = validate_order_lot_size(
            rule_main, OrderSide.SELL, Decimal("200"), available_qty=Decimal("100")
        )
        assert ok is False
        assert reason == "quantity_exceeds_available"

        # Available has odd-lot remainder (< 100 shares): e.g. 60 shares
        # Must sell all 60 shares
        ok, reason = validate_order_lot_size(
            rule_main, OrderSide.SELL, Decimal("60"), available_qty=Decimal("60")
        )
        assert ok is True

        # Selling partial of odd-lot is rejected
        ok, reason = validate_order_lot_size(
            rule_main, OrderSide.SELL, Decimal("30"), available_qty=Decimal("60")
        )
        assert ok is False
        assert reason == "odd_lot_remainder_must_sell_all"

        # Available is 360 shares: 300 round + 60 odd remainder
        # 1. Selling all 360 shares (complete holding liquidation) -> Legal
        ok, reason = validate_order_lot_size(
            rule_main, OrderSide.SELL, Decimal("360"), available_qty=Decimal("360")
        )
        assert ok is True

        # 2. Selling 60 shares (selling the odd-lot remainder alone, leaving 300 round) -> Legal
        ok, reason = validate_order_lot_size(
            rule_main, OrderSide.SELL, Decimal("60"), available_qty=Decimal("360")
        )
        assert ok is True

        # 3. Selling 160 shares (selling 100 round + 60 odd, leaving 200 round) -> Legal
        ok, reason = validate_order_lot_size(
            rule_main, OrderSide.SELL, Decimal("160"), available_qty=Decimal("360")
        )
        assert ok is True

        # 4. Selling 260 shares (selling 200 round + 60 odd, leaving 100 round) -> Legal
        ok, reason = validate_order_lot_size(
            rule_main, OrderSide.SELL, Decimal("260"), available_qty=Decimal("360")
        )
        assert ok is True

        # 5. Selling round lots only (100, 200, 300) leaving odd remainder intact -> Legal
        for round_qty in (Decimal("100"), Decimal("200"), Decimal("300")):
            ok, reason = validate_order_lot_size(
                rule_main, OrderSide.SELL, round_qty, available_qty=Decimal("360")
            )
            assert ok is True, f"Failed for round_qty={round_qty}"

        # 6. Selling partial odd lot (30) or breaking odd remainder (250) -> Illegal
        ok, reason = validate_order_lot_size(
            rule_main, OrderSide.SELL, Decimal("30"), available_qty=Decimal("360")
        )
        assert ok is False
        assert reason == "odd_lot_remainder_must_sell_all"

        ok, reason = validate_order_lot_size(
            rule_main, OrderSide.SELL, Decimal("250"), available_qty=Decimal("360")
        )
        assert ok is False
        assert reason == "odd_lot_remainder_must_sell_all"


class TestPriceLimits:
    def test_calculate_and_check_price_limits(self):
        d = date(2023, 1, 3)
        rule = resolve_trading_rules("600519", d)
        ref_price = Decimal("100.00")

        down, up = calculate_price_limits(ref_price, rule)
        assert down == Decimal("90.00")
        assert up == Decimal("110.00")

        assert is_price_within_limits(Decimal("100.00"), ref_price, rule) is True
        assert is_price_within_limits(Decimal("110.00"), ref_price, rule) is True
        assert is_price_within_limits(Decimal("90.00"), ref_price, rule) is True
        assert is_price_within_limits(Decimal("110.01"), ref_price, rule) is False
        assert is_price_within_limits(Decimal("89.99"), ref_price, rule) is False
