"""Shared market calendar contract tests."""

from __future__ import annotations

from datetime import date

from data.market_calendar import (
    MARKET_CALENDAR_SCHEMA_VERSION,
    MarketCalendar,
    MarketCalendarDayType,
)


def test_market_calendar_explains_trading_weekend_and_holiday_dates() -> None:
    calendar = MarketCalendar(holidays={"2026-01-01": "New Year's Day"})

    trading_day = calendar.explain_date("2026-01-02")
    weekend = calendar.explain_date(date(2026, 1, 4))
    holiday = calendar.explain_date("2026-01-01")

    assert MARKET_CALENDAR_SCHEMA_VERSION == "karkinos.market_calendar.v1"
    assert trading_day.day_type is MarketCalendarDayType.TRADING_DAY
    assert trading_day.is_trading_day is True
    assert trading_day.reason_code == "trading_day"
    assert weekend.day_type is MarketCalendarDayType.WEEKEND
    assert weekend.is_trading_day is False
    assert weekend.reason_code == "weekend"
    assert holiday.day_type is MarketCalendarDayType.HOLIDAY
    assert holiday.is_trading_day is False
    assert holiday.reason_code == "market_holiday"
    assert holiday.reason == "New Year's Day"
    assert holiday.to_payload()["schema_version"] == MARKET_CALENDAR_SCHEMA_VERSION
