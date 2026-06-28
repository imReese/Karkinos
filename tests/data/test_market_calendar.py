"""Shared market calendar contract tests."""

from __future__ import annotations

from datetime import date

from data.market_calendar import (
    MARKET_CALENDAR_SCHEMA_VERSION,
    MarketCalendar,
    MarketCalendarDayType,
    MarketCalendarSnapshot,
    build_static_market_calendar_snapshot,
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


def test_default_market_calendar_does_not_hardcode_annual_holidays() -> None:
    calendar = MarketCalendar()

    labor_day_without_snapshot = calendar.explain_date("2026-05-01")
    weekend_makeup_day = calendar.explain_date("2026-02-14")

    assert labor_day_without_snapshot.day_type is MarketCalendarDayType.TRADING_DAY
    assert weekend_makeup_day.day_type is MarketCalendarDayType.WEEKEND
    assert weekend_makeup_day.is_trading_day is False


def test_static_market_calendar_snapshot_normalizes_trading_and_closed_days() -> None:
    snapshot = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2026,
        provider="unit_fixture",
        open_dates={"2026-01-02", "2026-01-05"},
        closed_reasons={"2026-01-01": "官方公告：元旦休市"},
        fetched_at="2026-01-06T00:00:00+08:00",
    )

    assert isinstance(snapshot, MarketCalendarSnapshot)
    assert snapshot.exchange == "SSE"
    assert snapshot.provider == "unit_fixture"
    assert snapshot.trading_day_count == 2
    assert snapshot.closed_day_count == 363
    assert snapshot.source_fingerprint
    assert snapshot.official_verification_status == "unverified"

    by_date = {day.date: day for day in snapshot.days}
    assert by_date["2026-01-01"].day_type is MarketCalendarDayType.CLOSED
    assert by_date["2026-01-01"].reason == "官方公告：元旦休市"
    assert by_date["2026-01-02"].day_type is MarketCalendarDayType.TRADING_DAY
    assert by_date["2026-01-03"].day_type is MarketCalendarDayType.WEEKEND
    assert snapshot.to_payload()["schema_version"] == MARKET_CALENDAR_SCHEMA_VERSION
