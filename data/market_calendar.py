"""Shared market calendar contract for research/runtime surfaces."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol

MARKET_CALENDAR_SCHEMA_VERSION = "karkinos.market_calendar.v1"

DEFAULT_MARKET_HOLIDAYS: Mapping[str, str] = MappingProxyType({})


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
class MarketCalendarSnapshot:
    """Provider-sourced exchange calendar for one exchange/year."""

    exchange: str
    year: int
    provider: str
    days: tuple[MarketCalendarDay, ...]
    source_fingerprint: str
    fetched_at: str
    status: str = "available"
    official_verification_status: str = "unverified"
    official_source_url: str | None = None
    official_verified_at: str | None = None
    official_verified_by: str | None = None
    limitations: tuple[str, ...] = ()
    schema_version: str = MARKET_CALENDAR_SCHEMA_VERSION

    @property
    def trading_day_count(self) -> int:
        return sum(1 for day in self.days if day.is_trading_day)

    @property
    def closed_day_count(self) -> int:
        return sum(1 for day in self.days if not day.is_trading_day)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "exchange": self.exchange,
            "year": self.year,
            "provider": self.provider,
            "status": self.status,
            "trading_day_count": self.trading_day_count,
            "closed_day_count": self.closed_day_count,
            "source_fingerprint": self.source_fingerprint,
            "official_verification_status": self.official_verification_status,
            "official_source_url": self.official_source_url,
            "official_verified_at": self.official_verified_at,
            "official_verified_by": self.official_verified_by,
            "limitations": list(self.limitations),
            "days": [day.to_payload() for day in self.days],
            "fetched_at": self.fetched_at,
        }


class MarketCalendarProvider(Protocol):
    """Provider interface for exchange calendar snapshots."""

    provider_name: str

    def fetch_snapshot(self, *, exchange: str, year: int) -> MarketCalendarSnapshot:
        """Return a normalized exchange calendar snapshot."""


@dataclass(frozen=True)
class HolidayLabel:
    """Traceable label for a non-trading market calendar date."""

    date: str
    label: str
    source: str
    confidence: str
    source_url: str | None = None


class HolidayLabelProvider(Protocol):
    """Provider interface for naming non-trading days after sync."""

    provider_name: str

    def labels_for(
        self,
        *,
        exchange: str,
        year: int,
        closed_dates: Iterable[str],
    ) -> Mapping[str, HolidayLabel]:
        """Return labels keyed by ISO date for known non-trading days."""


@dataclass(frozen=True)
class StaticHolidayLabelProvider:
    """Deterministic label provider for official notices and tests."""

    labels: Mapping[str, HolidayLabel]
    source_url: str | None = None
    provider_name: str = "static_holiday_labels"

    def labels_for(
        self,
        *,
        exchange: str,
        year: int,
        closed_dates: Iterable[str],
    ) -> Mapping[str, HolidayLabel]:
        closed = {_parse_calendar_date(value).isoformat() for value in closed_dates}
        result: dict[str, HolidayLabel] = {}
        for value, label in self.labels.items():
            date_text = _parse_calendar_date(value).isoformat()
            if date_text not in closed:
                continue
            result[date_text] = HolidayLabel(
                date=date_text,
                label=label.label,
                source=label.source,
                confidence=label.confidence,
                source_url=label.source_url or self.source_url,
            )
        return result


@dataclass(frozen=True)
class ChinaExchangeHolidayLabelProvider:
    """Conservative labels derived from confirmed China-market closed dates.

    This provider never marks a trading day as a holiday. It only names already
    closed weekdays in well-known China-market holiday windows; official notice
    or manual labels should override these derived labels when available.
    """

    provider_name: str = "china_exchange_holiday_labels"

    def labels_for(
        self,
        *,
        exchange: str,
        year: int,
        closed_dates: Iterable[str],
    ) -> Mapping[str, HolidayLabel]:
        labels: dict[str, HolidayLabel] = {}
        for value in closed_dates:
            day = _parse_calendar_date(value)
            if day.year != int(year) or day.weekday() >= 5:
                continue
            label = _derive_china_market_holiday_label(day)
            if label is None:
                continue
            date_text = day.isoformat()
            labels[date_text] = HolidayLabel(
                date=date_text,
                label=label,
                source="derived_from_exchange_closed_dates",
                confidence="derived",
            )
        return labels


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


def build_static_market_calendar_snapshot(
    *,
    exchange: str,
    year: int,
    provider: str,
    open_dates: Iterable[str],
    closed_reasons: Mapping[str, str] | None = None,
    holiday_label_provider: HolidayLabelProvider | None = None,
    fetched_at: str | None = None,
    limitations: Iterable[str] = (),
) -> MarketCalendarSnapshot:
    """Build a full-year snapshot from provider open dates.

    Tushare exposes open/closed flags, while AkShare's Sina helper exposes open
    dates. This helper gives both providers one deterministic normalization path.
    """

    normalized_open_dates = {
        _parse_calendar_date(value).isoformat() for value in open_dates
    }
    normalized_closed_reasons = {
        _parse_calendar_date(value).isoformat(): reason
        for value, reason in (closed_reasons or {}).items()
    }
    all_date_texts: list[str] = []
    current = date(year, 1, 1)
    end = date(year + 1, 1, 1)
    while current < end:
        all_date_texts.append(current.isoformat())
        current += timedelta(days=1)
    normalized_closed_dates = [
        date_text
        for date_text in all_date_texts
        if date_text not in normalized_open_dates
    ]
    holiday_labels = _normalize_holiday_labels(
        holiday_label_provider.labels_for(
            exchange=exchange,
            year=year,
            closed_dates=normalized_closed_dates,
        )
        if holiday_label_provider
        else {}
    )
    combined_limitations = (
        *tuple(limitations),
        *_holiday_label_limitations(holiday_labels),
    )
    days: list[MarketCalendarDay] = []
    current = date(year, 1, 1)
    end = date(year + 1, 1, 1)
    while current < end:
        date_text = current.isoformat()
        if date_text in normalized_open_dates:
            days.append(
                MarketCalendarDay(
                    date=date_text,
                    day_type=MarketCalendarDayType.TRADING_DAY,
                    reason_code="trading_day",
                    reason="Exchange trading day",
                    is_trading_day=True,
                )
            )
        elif date_text in holiday_labels:
            days.append(
                MarketCalendarDay(
                    date=date_text,
                    day_type=MarketCalendarDayType.HOLIDAY,
                    reason_code="market_holiday",
                    reason=holiday_labels[date_text].label,
                    is_trading_day=False,
                )
            )
        elif date_text in normalized_closed_reasons:
            days.append(
                MarketCalendarDay(
                    date=date_text,
                    day_type=MarketCalendarDayType.CLOSED,
                    reason_code="market_closed",
                    reason=normalized_closed_reasons[date_text],
                    is_trading_day=False,
                )
            )
        elif current.weekday() >= 5:
            days.append(
                MarketCalendarDay(
                    date=date_text,
                    day_type=MarketCalendarDayType.WEEKEND,
                    reason_code="weekend",
                    reason="Weekend",
                    is_trading_day=False,
                )
            )
        else:
            days.append(
                MarketCalendarDay(
                    date=date_text,
                    day_type=MarketCalendarDayType.CLOSED,
                    reason_code="market_closed",
                    reason="Exchange closed",
                    is_trading_day=False,
                )
            )
        current += timedelta(days=1)

    fingerprint = _fingerprint_calendar_snapshot(
        {
            "exchange": exchange.upper(),
            "year": int(year),
            "provider": provider,
            "days": [day.to_payload() for day in days],
        }
    )
    return MarketCalendarSnapshot(
        exchange=exchange.upper(),
        year=int(year),
        provider=provider,
        days=tuple(days),
        source_fingerprint=fingerprint,
        fetched_at=fetched_at or datetime.now().isoformat(),
        limitations=tuple(dict.fromkeys(combined_limitations)),
    )


class TushareMarketCalendarProvider:
    """Tushare trade_cal based exchange calendar provider."""

    provider_name = "tushare"

    def __init__(
        self,
        token: str | None = None,
        holiday_label_provider: HolidayLabelProvider | None = None,
    ) -> None:
        self._token = token
        self._holiday_label_provider = holiday_label_provider

    def fetch_snapshot(self, *, exchange: str, year: int) -> MarketCalendarSnapshot:
        try:
            import tushare as ts
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("tushare is not installed") from exc

        token = self._token or None
        if token:
            ts.set_token(token)
        pro = ts.pro_api(token) if token else ts.pro_api()
        start = f"{year}0101"
        end = f"{year}1231"
        frame = pro.trade_cal(exchange=exchange, start_date=start, end_date=end)
        records = _dataframe_records(frame)
        open_dates: set[str] = set()
        closed_reasons: dict[str, str] = {}
        for record in records:
            date_text = _normalize_provider_date(record.get("cal_date"))
            if not date_text:
                continue
            if _provider_is_open(record.get("is_open")):
                open_dates.add(date_text)
            else:
                closed_reasons[date_text] = "Exchange closed"
        return build_static_market_calendar_snapshot(
            exchange=exchange,
            year=year,
            provider=self.provider_name,
            open_dates=open_dates,
            closed_reasons=closed_reasons,
            holiday_label_provider=self._holiday_label_provider,
            limitations=(
                "Tushare trade_cal gives open/closed dates but not official holiday names.",
                "Derived holiday labels require official exchange notice review before being treated as official.",
            ),
        )


class AkShareMarketCalendarProvider:
    """AkShare/Sina trading-date based exchange calendar provider."""

    provider_name = "akshare"

    def __init__(
        self,
        holiday_label_provider: HolidayLabelProvider | None = None,
    ) -> None:
        self._holiday_label_provider = holiday_label_provider

    def fetch_snapshot(self, *, exchange: str, year: int) -> MarketCalendarSnapshot:
        try:
            import akshare as ak
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("akshare is not installed") from exc

        frame = ak.tool_trade_date_hist_sina()
        records = _dataframe_records(frame)
        open_dates: set[str] = set()
        for record in records:
            for key in ("trade_date", "交易日", "date", "calendarDate"):
                date_text = _normalize_provider_date(record.get(key))
                if date_text and date_text.startswith(str(year)):
                    open_dates.add(date_text)
                    break
        return build_static_market_calendar_snapshot(
            exchange=exchange,
            year=year,
            provider=self.provider_name,
            open_dates=open_dates,
            holiday_label_provider=self._holiday_label_provider,
            limitations=(
                "AkShare Sina trade-date data lists trading days only; closure names require manual verification.",
                "Derived holiday labels require official exchange notice review before being treated as official.",
            ),
        )


def build_market_calendar_provider(
    provider: str,
    *,
    tushare_token: str | None = None,
    holiday_label_provider: HolidayLabelProvider | None = None,
) -> MarketCalendarProvider:
    provider_name = (provider or "akshare").strip().lower()
    labels = holiday_label_provider or ChinaExchangeHolidayLabelProvider()
    if provider_name == "tushare":
        return TushareMarketCalendarProvider(
            token=tushare_token,
            holiday_label_provider=labels,
        )
    if provider_name == "akshare":
        return AkShareMarketCalendarProvider(holiday_label_provider=labels)
    raise ValueError(f"Unsupported market calendar provider: {provider}")


def _parse_calendar_date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value[:10])


def _normalize_holiday_labels(
    labels: Mapping[str, HolidayLabel],
) -> dict[str, HolidayLabel]:
    normalized: dict[str, HolidayLabel] = {}
    for value, label in labels.items():
        date_text = _parse_calendar_date(value).isoformat()
        normalized[date_text] = HolidayLabel(
            date=date_text,
            label=str(label.label).strip(),
            source=str(label.source).strip(),
            confidence=str(label.confidence).strip(),
            source_url=label.source_url,
        )
    return {
        date_text: label
        for date_text, label in normalized.items()
        if label.label and label.source and label.confidence
    }


def _holiday_label_limitations(labels: Mapping[str, HolidayLabel]) -> tuple[str, ...]:
    if not labels:
        return ()
    sources = sorted({label.source for label in labels.values() if label.source})
    urls = sorted({label.source_url for label in labels.values() if label.source_url})
    limitations = [
        *(f"Holiday labels source: {source}" for source in sources),
        *urls,
    ]
    return tuple(limitations)


def _derive_china_market_holiday_label(day: date) -> str | None:
    if day.month == 1 and day.day <= 3:
        return "元旦休市"
    if day.month == 2:
        return "春节休市"
    if day.month == 4 and day.day <= 7:
        return "清明节休市"
    if day.month == 5 and day.day <= 7:
        return "劳动节休市"
    if (day.month == 5 and day.day >= 20) or (day.month == 6 and day.day <= 25):
        return "端午节休市"
    if day.month == 9 and day.day >= 15:
        return "中秋节休市"
    if day.month == 10 and day.day <= 7:
        return "国庆节休市"
    return None


def _normalize_provider_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime | date):
        return (
            value.date().isoformat()
            if isinstance(value, datetime)
            else value.isoformat()
        )
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return date.fromisoformat(text[:10]).isoformat()
    digits = "".join(char for char in text if char.isdigit())
    if len(digits) >= 8:
        return date(
            int(digits[:4]),
            int(digits[4:6]),
            int(digits[6:8]),
        ).isoformat()
    return None


def _provider_is_open(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return int(value) == 1
    return str(value).strip() in {"1", "true", "True", "open", "OPEN"}


def _dataframe_records(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "to_dict"):
        records = value.to_dict("records")
        return [dict(record) for record in records]
    if isinstance(value, list):
        return [dict(record) for record in value]
    return []


def _fingerprint_calendar_snapshot(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
