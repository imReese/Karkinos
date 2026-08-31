"""Shared market calendar contract for research/runtime surfaces."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from data.market_calendar_values import dataframe_records as _dataframe_records
from data.market_calendar_values import (
    derive_china_market_holiday_label as _derive_china_market_holiday_label,
)
from data.market_calendar_values import (
    fingerprint_calendar_snapshot as _fingerprint_calendar_snapshot,
)
from data.market_calendar_values import (
    holiday_label_limitations as _holiday_label_limitations,
)
from data.market_calendar_values import html_fragment_text as _html_fragment_text
from data.market_calendar_values import is_leap_year as _is_leap_year
from data.market_calendar_values import (
    normalize_holiday_labels as _normalize_holiday_labels_impl,
)
from data.market_calendar_values import (
    normalize_provider_date as _normalize_provider_date,
)
from data.market_calendar_values import parse_calendar_date as _parse_calendar_date
from data.market_calendar_values import provider_is_open as _provider_is_open

MARKET_CALENDAR_SCHEMA_VERSION = "karkinos.market_calendar.v1"
SSE_OFFICIAL_HOLIDAY_NOTICE_URL = (
    "https://www.sse.com.cn/disclosure/dealinstruc/closed/"
)

_SSE_REQUIRED_HOLIDAY_NAMES = (
    "元旦",
    "春节",
    "清明节",
    "劳动节",
    "端午节",
    "中秋节",
    "国庆节",
)
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

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


def _normalize_holiday_labels(
    labels: Mapping[str, HolidayLabel],
) -> dict[str, HolidayLabel]:
    return _normalize_holiday_labels_impl(labels, label_factory=HolidayLabel)


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
class OfficialMarketHolidayNotice:
    """One parsed, fingerprinted exchange holiday notice."""

    exchange: str
    year: int
    source_url: str
    source_fingerprint: str
    fetched_at: str
    notice_title: str
    day_labels: Mapping[str, str]
    reopen_dates: tuple[str, ...]


@dataclass(frozen=True)
class OfficialMarketCalendarVerification:
    """Deterministic comparison of one provider calendar and official notice."""

    status: str
    issues: tuple[str, ...]

    @property
    def verified(self) -> bool:
        return self.status == "verified"


class SseOfficialHolidayNoticeProvider:
    """Fetch and parse the fixed official SSE annual closure page."""

    provider_name = "sse_official_notice"
    source_url = SSE_OFFICIAL_HOLIDAY_NOTICE_URL

    def fetch_notice(self, *, year: int) -> OfficialMarketHolidayNotice:
        try:
            import requests
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("requests is not installed") from exc

        response = requests.get(
            self.source_url,
            headers={"User-Agent": "Karkinos/market-calendar-audit"},
            timeout=10,
        )
        response.raise_for_status()
        try:
            document = response.content.decode("utf-8")
        except UnicodeDecodeError:
            document = response.text
        return parse_sse_official_holiday_notice(
            document,
            year=year,
            source_url=self.source_url,
            fetched_at=datetime.now(_SHANGHAI_TZ).isoformat(),
        )


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


def parse_sse_official_holiday_notice(
    document: str,
    *,
    year: int,
    source_url: str = SSE_OFFICIAL_HOLIDAY_NOTICE_URL,
    fetched_at: str | None = None,
) -> OfficialMarketHolidayNotice:
    """Parse one complete annual holiday table from the official SSE page."""
    normalized_year = int(year)
    title = f"{normalized_year}年休市安排"
    section_match = re.search(
        rf"<strong[^>]*>\s*{normalized_year}年休市安排\s*</strong>(?P<body>.*)",
        document,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if section_match is None:
        raise ValueError(f"official SSE holiday notice does not contain {title}")
    table_match = re.search(
        r"<table\b[^>]*>(?P<table>.*?)</table>",
        section_match.group("body"),
        flags=re.DOTALL | re.IGNORECASE,
    )
    if table_match is None:
        raise ValueError(f"official SSE holiday notice has no table for {title}")

    holiday_descriptions: dict[str, str] = {}
    for row_html in re.findall(
        r"<tr\b[^>]*>(.*?)</tr>",
        table_match.group("table"),
        flags=re.DOTALL | re.IGNORECASE,
    ):
        cells = re.findall(
            r"<td\b[^>]*>(.*?)</td>",
            row_html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if len(cells) < 2:
            continue
        holiday_name = _html_fragment_text(cells[0]).rstrip("：:").strip()
        if holiday_name not in _SSE_REQUIRED_HOLIDAY_NAMES:
            continue
        holiday_descriptions[holiday_name] = _html_fragment_text(cells[1])

    missing_names = sorted(set(_SSE_REQUIRED_HOLIDAY_NAMES) - set(holiday_descriptions))
    if missing_names:
        raise ValueError(
            "official SSE holiday notice is incomplete for "
            f"{normalized_year}: missing {', '.join(missing_names)}"
        )

    day_labels: dict[str, str] = {}
    reopen_dates: list[str] = []
    for holiday_name in _SSE_REQUIRED_HOLIDAY_NAMES:
        description = holiday_descriptions[holiday_name]
        range_match = re.search(
            r"(?P<start_month>\d{1,2})月(?P<start_day>\d{1,2})日"
            r".*?至(?:(?P<end_month>\d{1,2})月)?(?P<end_day>\d{1,2})日"
            r".*?休市",
            description,
        )
        if range_match is None:
            raise ValueError(
                f"official SSE holiday range is unparseable: {holiday_name}"
            )
        start_month = int(range_match.group("start_month"))
        start_day = int(range_match.group("start_day"))
        end_month = int(range_match.group("end_month") or start_month)
        end_day = int(range_match.group("end_day"))
        start = date(normalized_year, start_month, start_day)
        end = date(normalized_year, end_month, end_day)
        if end < start:
            raise ValueError(f"official SSE holiday range is reversed: {holiday_name}")
        current = start
        while current <= end:
            day_labels[current.isoformat()] = f"{holiday_name}休市"
            current += timedelta(days=1)

        reopen_match = re.search(
            r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
            r"(?:（[^）]+）|\([^)]*\))?起照常开市",
            description,
        )
        if reopen_match is None:
            raise ValueError(f"official SSE reopen date is unparseable: {holiday_name}")
        reopen_dates.append(
            date(
                normalized_year,
                int(reopen_match.group("month")),
                int(reopen_match.group("day")),
            ).isoformat()
        )

    return OfficialMarketHolidayNotice(
        exchange="SSE",
        year=normalized_year,
        source_url=source_url,
        source_fingerprint=hashlib.sha256(document.encode("utf-8")).hexdigest(),
        fetched_at=fetched_at or datetime.now(_SHANGHAI_TZ).isoformat(),
        notice_title=title,
        day_labels=MappingProxyType(day_labels),
        reopen_dates=tuple(reopen_dates),
    )


def verify_official_market_calendar(
    snapshot: MarketCalendarSnapshot,
    notice: OfficialMarketHolidayNotice,
) -> OfficialMarketCalendarVerification:
    """Fail closed unless provider dates exactly support the official notice."""
    issues: list[str] = []
    if snapshot.exchange.upper() != notice.exchange.upper():
        issues.append(
            f"exchange mismatch: provider={snapshot.exchange}, notice={notice.exchange}"
        )
    if snapshot.year != notice.year:
        issues.append(f"year mismatch: provider={snapshot.year}, notice={notice.year}")

    expected_days = 366 if _is_leap_year(snapshot.year) else 365
    if len(snapshot.days) != expected_days:
        actual_days = len(snapshot.days)
        issues.append(
            f"provider calendar is incomplete: {actual_days}/{expected_days} days"
        )
    if not 200 <= snapshot.trading_day_count <= 260:
        issues.append(
            f"provider trading-day count is implausible: {snapshot.trading_day_count}"
        )

    by_date = {day.date: day for day in snapshot.days}
    if len(by_date) != len(snapshot.days):
        issues.append("provider calendar contains duplicate dates")

    weekend_trading_dates = sorted(
        day.date
        for day in snapshot.days
        if day.is_trading_day and _parse_calendar_date(day.date).weekday() >= 5
    )
    if weekend_trading_dates:
        issues.append(
            "provider marks weekends as trading days: "
            + ", ".join(weekend_trading_dates)
        )

    for date_text in sorted(notice.day_labels):
        day = by_date.get(date_text)
        if day is None:
            issues.append(
                f"official holiday missing from provider calendar: {date_text}"
            )
        elif day.is_trading_day:
            issues.append(f"official holiday marked open by provider: {date_text}")

    for date_text in notice.reopen_dates:
        day = by_date.get(date_text)
        if day is None:
            issues.append(
                f"official reopen date missing from provider calendar: {date_text}"
            )
        elif not day.is_trading_day:
            issues.append(
                f"official reopen date marked closed by provider: {date_text}"
            )

    official_closed_dates = set(notice.day_labels)
    unexplained_weekday_closures = sorted(
        day.date
        for day in snapshot.days
        if not day.is_trading_day
        and _parse_calendar_date(day.date).weekday() < 5
        and day.date not in official_closed_dates
    )
    if unexplained_weekday_closures:
        issues.append(
            "provider has weekday closures absent from official notice: "
            + ", ".join(unexplained_weekday_closures)
        )

    return OfficialMarketCalendarVerification(
        status="verified" if not issues else "needs_review",
        issues=tuple(issues),
    )
