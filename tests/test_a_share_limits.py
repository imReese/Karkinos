from __future__ import annotations

from decimal import Decimal

from execution.a_share_limits import (
    GROWTH_BOARD_RATE,
    MAIN_BOARD_RATE,
    is_limit_down,
    is_limit_up,
    is_suspended,
    limit_down_price,
    limit_rate_for_symbol,
    limit_up_price,
    normalize_code,
)


def test_limit_rate_is_board_based():
    assert limit_rate_for_symbol("600000") == MAIN_BOARD_RATE
    assert limit_rate_for_symbol("000001") == MAIN_BOARD_RATE
    assert limit_rate_for_symbol("300750") == GROWTH_BOARD_RATE
    assert limit_rate_for_symbol("688981") == GROWTH_BOARD_RATE
    assert limit_rate_for_symbol("600000.SH") == MAIN_BOARD_RATE


def test_normalize_code_strips_suffix():
    assert normalize_code("600000.SH") == "600000"
    assert normalize_code("300750.SZ") == "300750"


def test_limit_up_and_down_prices_round_to_tick():
    assert limit_up_price(Decimal("10.00"), MAIN_BOARD_RATE) == Decimal("11.00")
    assert limit_down_price(Decimal("10.00"), MAIN_BOARD_RATE) == Decimal("9.00")
    # 10.11 * 1.1 = 11.121 -> rounds to 11.12
    assert limit_up_price(Decimal("10.11"), MAIN_BOARD_RATE) == Decimal("11.12")


def test_limit_detection():
    assert is_limit_up(Decimal("11.00"), Decimal("10.00"), MAIN_BOARD_RATE)
    assert not is_limit_up(Decimal("10.99"), Decimal("10.00"), MAIN_BOARD_RATE)
    assert is_limit_down(Decimal("9.00"), Decimal("10.00"), MAIN_BOARD_RATE)
    assert not is_limit_down(Decimal("9.01"), Decimal("10.00"), MAIN_BOARD_RATE)


def test_suspension_detection():
    assert is_suspended(Decimal("0"))
    assert is_suspended(Decimal("-1"))
    assert not is_suspended(Decimal("1"))
