from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from server.services.daily_performance import (
    build_position_daily_context,
    calculate_account_daily_performance,
    mark_position_daily,
    price_at_tick,
)


def test_partial_same_day_add_has_one_after_cost_baseline():
    tz = ZoneInfo("Asia/Shanghai")
    context = build_position_daily_context(
        quantity=400,
        previous_close=25.46,
        same_day_buy_lots=[
            {
                "timestamp": datetime(2026, 7, 10, 10, 0, tzinfo=tz),
                "quantity": 300,
                "price": 24.95,
                "total_cost": 300 * 24.95 + 5.07485,
            }
        ],
    )
    mark = mark_position_daily(context, price=24.60)

    assert context.overnight_quantity == 100
    assert context.baseline_value == pytest.approx(100 * 25.46 + 300 * 24.95 + 5.07485)
    assert context.source == "mixed_previous_close_intraday_trade_cost"
    assert mark.today_change == pytest.approx(-196.07485)


def test_intraday_cutoff_uses_same_context_and_trade_timing():
    tz = ZoneInfo("Asia/Shanghai")
    trade_at = datetime(2026, 7, 10, 10, 0, tzinfo=tz)
    context = build_position_daily_context(
        quantity=400,
        previous_close=25.46,
        same_day_buy_lots=[
            {
                "timestamp": trade_at,
                "quantity": 300,
                "price": 24.95,
                "total_cost": 300 * 24.95 + 5.07485,
            }
        ],
    )

    before = mark_position_daily(
        context,
        price=price_at_tick(
            context,
            tick=datetime(2026, 7, 10, 9, 30, tzinfo=tz),
            quote_points=[],
        ),
        at=datetime(2026, 7, 10, 9, 30, tzinfo=tz),
    )
    after = mark_position_daily(
        context,
        price=price_at_tick(context, tick=trade_at, quote_points=[]),
        at=trade_at,
    )

    assert before.active_quantity == 100
    assert before.today_change == pytest.approx(0)
    assert after.active_quantity == 400
    assert after.today_change == pytest.approx(-56.07485)


def test_same_day_sell_and_missing_overnight_close_fail_closed():
    sell = build_position_daily_context(
        quantity=300,
        previous_close=25.46,
        same_day_buy_lots=[],
        has_same_day_sell=True,
    )
    missing = build_position_daily_context(
        quantity=400,
        previous_close=None,
        same_day_buy_lots=[],
    )

    assert mark_position_daily(sell, price=24.6).today_change is None
    assert sell.source == "same_day_sell_requires_daily_attribution"
    assert mark_position_daily(missing, price=24.6).today_change is None
    assert missing.source == "overnight_baseline_unavailable"


def test_account_daily_equation_is_canonical_and_exposes_market_move():
    performance = calculate_account_daily_performance(
        starting_equity=30046.0,
        ending_equity=29849.92515,
        external_flow=0.0,
    )

    assert performance.equity_delta == pytest.approx(-196.07485)
    assert performance.market_move == pytest.approx(-196.07485)
    assert (
        performance.equity_delta == performance.external_flow + performance.market_move
    )
