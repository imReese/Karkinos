"""Shared market calendar contract for research/runtime surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping

MARKET_CALENDAR_SCHEMA_VERSION = "karkinos.market_calendar.v1"

DEFAULT_MARKET_HOLIDAYS: Mapping[str, str] = MappingProxyType(
    {
        "2026-01-01": "New Year's Day",
    }
)


class MarketCalendarDayType(Enum):
    """Market calendar day categories shared by runtime and UI surfaces."""

    TRADING_DAY = "trading_day"
    WEEKEND = "weekend"
    HOLIDAY = "holiday"
    CLOSED = "closed"


@dataclass(frozen=True)
class MarketCalendarDay:
    """One deterministic explanation for a calendar date."""

    date: str
    day_type: MarketCalendarDayType
    reason_code: str
    reason: str
    is_trading_day: bool
    schema_version: str = MARKET_CALENDAR_SCHEMA_VERSION

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "date": self.date,
            "day_type": self.day_type.value,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "is_trading_day": self.is_trading_day,
        }


@dataclass(frozen=True)
class MarketCalendar:
    """Small deterministic market calendar with configurable holidays."""

    holidays: Mapping[str, str] = DEFAULT_MARKET_HOLIDAYS
    extra_trading_days: tuple[str, ...] = ()
    closed_days: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "holidays", MappingProxyType(dict(self.holidays)))
        object.__setattr__(self, "extra_trading_days", tuple(self.extra_trading_days))
        object.__setattr__(
            self,
            "closed_days",
            MappingProxyType(dict(self.closed_days)),
        )

    def explain_date(self, value: str | date | datetime) -> MarketCalendarDay:
        day = _parse_calendar_date(value)
        date_text = day.isoformat()

        if date_text in self.extra_trading_days:
            return MarketCalendarDay(
                date=date_text,
                day_type=MarketCalendarDayType.TRADING_DAY,
                reason_code="extra_trading_day",
                reason="Configured trading day",
                is_trading_day=True,
            )
        if date_text in self.closed_days:
            return MarketCalendarDay(
                date=date_text,
                day_type=MarketCalendarDayType.CLOSED,
                reason_code="market_closed",
                reason=self.closed_days[date_text],
                is_trading_day=False,
            )
        if date_text in self.holidays:
            return MarketCalendarDay(
                date=date_text,
                day_type=MarketCalendarDayType.HOLIDAY,
                reason_code="market_holiday",
                reason=self.holidays[date_text],
                is_trading_day=False,
            )
        if day.weekday() >= 5:
            return MarketCalendarDay(
                date=date_text,
                day_type=MarketCalendarDayType.WEEKEND,
                reason_code="weekend",
                reason="Weekend",
                is_trading_day=False,
            )
        return MarketCalendarDay(
            date=date_text,
            day_type=MarketCalendarDayType.TRADING_DAY,
            reason_code="trading_day",
            reason="Trading day",
            is_trading_day=True,
        )


def _parse_calendar_date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value[:10])
