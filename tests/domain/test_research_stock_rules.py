"""Ordinary-session opt-in rules preserve the legacy instrument model."""

from decimal import Decimal

import pytest

from domain.instrument import (
    make_research_stock,
    make_stock,
    research_stock_session_blocker,
)


def test_star_research_lots_are_legal_conservative_minimums():
    assert make_research_stock("688001", "测试").lot_size == Decimal("200")
    assert make_research_stock("688001", "测试").limit_pct == Decimal("0.20")
    assert make_stock("688001", "测试").lot_size == Decimal("100")


def test_beijing_limit_is_distinct_from_legacy_default():
    assert make_research_stock("920001", "测试").limit_pct == Decimal("0.30")
    assert make_research_stock("920001", "测试").lot_size == Decimal("100")
    assert make_stock("920001", "测试").limit_pct == Decimal("0.10")


@pytest.mark.parametrize("symbol,count", [("688001", 5), ("300001", 5), ("920001", 1)])
def test_special_listing_sessions_cannot_inherit_ordinary_limits(symbol, count):
    assert (
        research_stock_session_blocker(
            symbol, is_st=False, listing_session_count=count, in_delisting_period=False
        )
        == "initial_listing_period_excluded"
    )
    assert (
        research_stock_session_blocker(
            symbol, is_st=False, listing_session_count=60, in_delisting_period=False
        )
        is None
    )
    assert research_stock_session_blocker(symbol) == "ordinary_session_state_unverified"


def test_st_and_delisting_states_remain_exclusions():
    assert (
        research_stock_session_blocker("600001", is_st=True)
        == "special_treatment_excluded"
    )
    assert (
        research_stock_session_blocker("600001", in_delisting_period=True)
        == "delisting_period_excluded"
    )
