"""Strategy Runtime market-calendar context tests."""

from __future__ import annotations

from data.market_calendar import MarketCalendar, MarketCalendarDayType
from strategy import StrategyRuntimeContext


def test_strategy_runtime_context_consumes_shared_market_calendar() -> None:
    context = StrategyRuntimeContext(
        strategy_id="calendar_aware_strategy",
        run_id="calendar-run-001",
        market_calendar=MarketCalendar(holidays={"2026-01-01": "New Year's Day"}),
    )

    holiday = context.market_calendar.explain_date("2026-01-01")
    weekend = context.market_calendar.explain_date("2026-01-04")

    assert holiday.day_type is MarketCalendarDayType.HOLIDAY
    assert holiday.is_trading_day is False
    assert weekend.day_type is MarketCalendarDayType.WEEKEND
    assert weekend.is_trading_day is False
    assert not hasattr(context.market_calendar, "submit_order")
