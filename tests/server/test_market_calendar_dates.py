from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from server.services.market_calendar_dates import (
    resolve_latest_verified_closed_trading_date,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class _CalendarDb:
    def __init__(self, calendars: dict[int, dict[str, Any] | None]) -> None:
        self.calendars = calendars
        self.calls: list[tuple[str, int]] = []

    def get_market_calendar_snapshot_sync(
        self,
        *,
        exchange: str,
        year: int,
    ) -> dict[str, Any] | None:
        self.calls.append((exchange, year))
        return self.calendars.get(year)


def _verified_calendar(
    year: int,
    *,
    closed_dates: set[str] | None = None,
    verified: bool = True,
) -> dict[str, Any]:
    closed = closed_dates or set()
    current = date(year, 1, 1)
    end = date(year + 1, 1, 1)
    days: list[dict[str, object]] = []
    while current < end:
        value = current.isoformat()
        days.append(
            {
                "date": value,
                "is_trading_day": current.weekday() < 5 and value not in closed,
            }
        )
        current += timedelta(days=1)
    source_fingerprint = format(year % 16, "x") * 64
    official_source_fingerprint = format((year + 1) % 16, "x") * 64
    trading_day_count = sum(1 for day in days if day["is_trading_day"])
    return {
        "exchange": "SSE",
        "year": year,
        "provider": "unit_fixture",
        "status": "available",
        "trading_day_count": trading_day_count,
        "closed_day_count": len(days) - trading_day_count,
        "source_fingerprint": source_fingerprint,
        "verification_source_fingerprint": source_fingerprint,
        "official_verification_status": "verified" if verified else "needs_review",
        "official_source_url": "https://example.test/sse-calendar",
        "official_source_fingerprint": official_source_fingerprint,
        "official_verified_at": f"{year}-01-01T00:00:00+08:00",
        "official_verified_by": "unit-test",
        "days_json": json.dumps(days, sort_keys=True),
    }


def _evidence_ref(calendar: dict[str, Any]) -> str:
    return (
        f"market_calendar:SSE:{calendar['year']}:"
        f"{calendar['source_fingerprint']}:"
        f"{calendar['official_source_fingerprint']}"
    )


def test_closed_trading_date_switches_to_current_date_at_1600() -> None:
    calendar = _verified_calendar(2026)
    db = _CalendarDb({2026: calendar})

    before_close = resolve_latest_verified_closed_trading_date(
        db,
        datetime(2026, 6, 17, 15, 59, tzinfo=_SHANGHAI),
    )
    at_close = resolve_latest_verified_closed_trading_date(
        db,
        datetime(2026, 6, 17, 16, 0, tzinfo=_SHANGHAI),
    )

    assert before_close is not None
    assert before_close.trade_date == "2026-06-16"
    assert before_close.calendar_evidence_refs == (_evidence_ref(calendar),)
    assert at_close is not None
    assert at_close.trade_date == "2026-06-17"
    assert at_close.calendar_evidence_refs == (_evidence_ref(calendar),)


def test_closed_trading_date_skips_verified_exchange_holiday() -> None:
    calendar = _verified_calendar(2026, closed_dates={"2026-06-17"})
    db = _CalendarDb({2026: calendar})

    resolved = resolve_latest_verified_closed_trading_date(
        db,
        datetime(2026, 6, 17, 18, 0, tzinfo=_SHANGHAI),
    )

    assert resolved is not None
    assert resolved.trade_date == "2026-06-16"
    assert resolved.calendar_evidence_refs == (_evidence_ref(calendar),)


@pytest.mark.parametrize("current_calendar_status", ["missing", "unverified"])
def test_closed_trading_date_does_not_fall_back_when_current_year_is_unverified(
    current_calendar_status: str,
) -> None:
    current_calendar = (
        None
        if current_calendar_status == "missing"
        else _verified_calendar(2026, verified=False)
    )
    db = _CalendarDb(
        {
            2026: current_calendar,
            2025: _verified_calendar(2025),
        }
    )

    resolved = resolve_latest_verified_closed_trading_date(
        db,
        datetime(2026, 1, 2, 16, 1, tzinfo=_SHANGHAI),
    )

    assert resolved is None
    assert db.calls == [("SSE", 2026)]


def test_closed_trading_date_allows_verified_january_cross_year_fallback() -> None:
    current_calendar = _verified_calendar(2026, closed_dates={"2026-01-01"})
    previous_calendar = _verified_calendar(2025)
    db = _CalendarDb({2026: current_calendar, 2025: previous_calendar})

    resolved = resolve_latest_verified_closed_trading_date(
        db,
        datetime(2026, 1, 1, 16, 1, tzinfo=_SHANGHAI),
    )

    assert resolved is not None
    assert resolved.trade_date == "2025-12-31"
    assert resolved.calendar_evidence_refs == (
        _evidence_ref(current_calendar),
        _evidence_ref(previous_calendar),
    )
    assert db.calls == [("SSE", 2026), ("SSE", 2025)]
