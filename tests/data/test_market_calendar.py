"""Shared market calendar contract tests."""

from __future__ import annotations

from datetime import date, timedelta

from data.market_calendar import (
    MARKET_CALENDAR_SCHEMA_VERSION,
    ChinaExchangeHolidayLabelProvider,
    HolidayLabel,
    MarketCalendar,
    MarketCalendarDayType,
    MarketCalendarSnapshot,
    StaticHolidayLabelProvider,
    build_static_market_calendar_snapshot,
    parse_sse_official_holiday_notice,
    verify_official_market_calendar,
)

_SSE_NOTICE_FIXTURE = """
<strong>2026年休市安排</strong>
<table><tbody>
<tr><td>元旦：</td><td>1月1日（星期四）至1月3日（星期六）休市，1月5日（星期一）起照常开市。</td></tr>
<tr><td>春节：</td><td>2月15日（星期日）至2月23日（星期一）休市，2月24日（星期二）起照常开市。</td></tr>
<tr><td>清明节：</td><td>4月4日（星期六）至4月6日（星期一）休市，4月7日（星期二）起照常开市。</td></tr>
<tr><td>劳动节：</td><td>5月1日（星期五）至5月5日（星期二）休市，5月6日（星期三）起照常开市。</td></tr>
<tr><td>端午节：</td><td>6月19日（星期五）至6月21日（星期日）休市，6月22日（星期一）起照常开市。</td></tr>
<tr><td>中秋节：</td><td>9月25日（星期五）至9月27日（星期日）休市，9月28日（星期一）起照常开市。</td></tr>
<tr><td>国庆节：</td><td>10月1日（星期四）至10月7日（星期三）休市，10月8日（星期四）起照常开市。</td></tr>
</tbody></table>
"""


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


def test_static_market_calendar_snapshot_applies_traceable_holiday_labels() -> None:
    snapshot = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2026,
        provider="unit_fixture",
        open_dates={"2026-06-18", "2026-06-22"},
        holiday_label_provider=StaticHolidayLabelProvider(
            labels={
                "2026-06-19": HolidayLabel(
                    date="2026-06-19",
                    label="端午节休市",
                    source="official_exchange_notice",
                    confidence="official",
                )
            },
            source_url="https://example.test/exchange-holiday-notice",
        ),
        fetched_at="2026-06-20T00:00:00+08:00",
    )

    by_date = {day.date: day for day in snapshot.days}
    assert by_date["2026-06-19"].day_type is MarketCalendarDayType.HOLIDAY
    assert by_date["2026-06-19"].reason_code == "market_holiday"
    assert by_date["2026-06-19"].reason == "端午节休市"
    assert "Holiday labels source: official_exchange_notice" in snapshot.limitations
    assert "https://example.test/exchange-holiday-notice" in snapshot.limitations


def test_china_exchange_holiday_label_provider_derives_common_holiday_names() -> None:
    snapshot = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2026,
        provider="unit_fixture",
        open_dates={"2026-06-18", "2026-06-22", "2026-10-08"},
        holiday_label_provider=ChinaExchangeHolidayLabelProvider(),
        fetched_at="2026-06-20T00:00:00+08:00",
    )

    by_date = {day.date: day for day in snapshot.days}
    assert by_date["2026-06-19"].day_type is MarketCalendarDayType.HOLIDAY
    assert by_date["2026-06-19"].reason == "端午节休市"
    assert by_date["2026-06-19"].reason_code == "market_holiday"
    assert by_date["2026-10-01"].day_type is MarketCalendarDayType.HOLIDAY
    assert by_date["2026-10-01"].reason == "国庆节休市"
    assert by_date["2026-07-01"].day_type is MarketCalendarDayType.CLOSED
    assert by_date["2026-07-01"].reason == "Exchange closed"
    assert "Holiday labels source: derived_from_exchange_closed_dates" in (
        snapshot.limitations
    )


def test_parse_sse_official_holiday_notice_requires_complete_annual_table() -> None:
    notice = parse_sse_official_holiday_notice(
        _SSE_NOTICE_FIXTURE,
        year=2026,
        source_url="https://example.test/sse-closure",
        fetched_at="2026-07-27T12:00:00+08:00",
    )

    assert notice.notice_title == "2026年休市安排"
    assert notice.day_labels["2026-05-01"] == "劳动节休市"
    assert notice.day_labels["2026-05-05"] == "劳动节休市"
    assert "2026-05-06" in notice.reopen_dates
    assert len(notice.source_fingerprint) == 64

    incomplete = _SSE_NOTICE_FIXTURE.replace(
        "<tr><td>端午节：</td><td>6月19日（星期五）至6月21日（星期日）休市，6月22日（星期一）起照常开市。</td></tr>",
        "",
    )
    try:
        parse_sse_official_holiday_notice(incomplete, year=2026)
    except ValueError as exc:
        assert "端午节" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("incomplete official notice must fail closed")


def test_verify_official_market_calendar_accepts_only_exact_supported_dates() -> None:
    notice = parse_sse_official_holiday_notice(_SSE_NOTICE_FIXTURE, year=2026)
    holiday_dates = set(notice.day_labels)
    current = date(2026, 1, 1)
    open_dates: set[str] = set()
    while current.year == 2026:
        if current.weekday() < 5 and current.isoformat() not in holiday_dates:
            open_dates.add(current.isoformat())
        current += timedelta(days=1)
    snapshot = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2026,
        provider="unit_fixture",
        open_dates=open_dates,
    )

    assert verify_official_market_calendar(snapshot, notice).verified is True

    bad_snapshot = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2026,
        provider="unit_fixture",
        open_dates={*open_dates, "2026-05-02"},
    )
    result = verify_official_market_calendar(bad_snapshot, notice)
    assert result.status == "needs_review"
    assert any("weekends as trading days" in issue for issue in result.issues)
