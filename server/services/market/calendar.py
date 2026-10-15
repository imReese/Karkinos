"""Verified market-calendar verification and trading date projections."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from server.services.market.hours import get_shanghai_now

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
POST_CLOSE_INGESTION_TIME = time(16, 0)


@dataclass(frozen=True, slots=True)
class MarketCalendarEvidenceValidation:
    """Fail-closed validation state for an official SSE calendar record."""

    verified: bool
    blockers: tuple[str, ...]
    source_fingerprint: str | None
    official_source_fingerprint: str | None
    evidence_ref: str | None


def validate_verified_market_calendar(
    row: dict[str, Any] | None,
) -> MarketCalendarEvidenceValidation:
    """Accept only a complete calendar bound to two exact source identities."""
    if row is None:
        return _validation(["market_calendar_missing"])
    blockers: list[str] = []
    source = str(row.get("source_fingerprint") or "").strip()
    verification_source = str(row.get("verification_source_fingerprint") or "").strip()
    official_source = str(row.get("official_source_fingerprint") or "").strip()
    if str(row.get("official_verification_status") or "") != "verified":
        blockers.append("market_calendar_not_verified")
    if not _SHA256.fullmatch(source):
        blockers.append("market_calendar_source_fingerprint_invalid")
    if verification_source != source or not _SHA256.fullmatch(verification_source):
        blockers.append("market_calendar_verification_binding_invalid")
    if not _SHA256.fullmatch(official_source):
        blockers.append("market_calendar_official_source_fingerprint_invalid")
    for field, blocker in (
        ("official_source_url", "market_calendar_official_source_url_missing"),
        ("official_verified_at", "market_calendar_verified_at_missing"),
        ("official_verified_by", "market_calendar_verified_by_missing"),
    ):
        if not str(row.get(field) or "").strip():
            blockers.append(blocker)
    blockers.extend(_calendar_day_blockers(row))
    unique_blockers = tuple(dict.fromkeys(blockers))
    evidence_ref = None
    if not unique_blockers:
        evidence_ref = (
            f"market_calendar:{str(row.get('exchange') or '').upper()}:"
            f"{int(row.get('year') or 0)}:{source}:{official_source}"
        )
    return MarketCalendarEvidenceValidation(
        verified=not unique_blockers,
        blockers=unique_blockers,
        source_fingerprint=source or None,
        official_source_fingerprint=official_source or None,
        evidence_ref=evidence_ref,
    )


def project_market_session(
    db: Any,
    now: datetime | None = None,
    *,
    calendar_reader: Any = None,
) -> dict[str, Any]:
    """Describe the SSE session using persisted, officially verified calendar facts."""
    current = get_shanghai_now(now)
    reader = calendar_reader or getattr(db, "get_market_calendar_snapshot_sync", None)
    row = reader(exchange="SSE", year=current.year) if callable(reader) else None
    validation = validate_verified_market_calendar(row)
    result: dict[str, Any] = {
        "status": "unknown",
        "market_date": current.date().isoformat(),
        "calendar_available": row is not None,
        "calendar_verified": validation.verified,
        "latest_completed_trade_date": None,
        "previous_completed_trade_date": None,
        "expected_quote_date": None,
        "next_trading_date": None,
        "calendar_evidence_refs": [],
        "blockers": list(validation.blockers),
    }
    if not validation.verified:
        return result
    days = _calendar_days(row)
    today = current.date().isoformat()
    trading_day = next(day for day in days if day["date"] == today)["is_trading_day"]
    clock = current.time()
    if not trading_day:
        status = "non_trading_day"
    elif time(9, 30) <= clock < time(11, 30) or time(13) <= clock < time(15):
        status = "open"
    elif time(11, 30) <= clock < time(13):
        status = "midday_break"
    elif clock < time(9, 30):
        status = "pre_open"
    else:
        status = "after_close"
    cutoff = (
        today if clock >= time(15) else (current.date() - timedelta(days=1)).isoformat()
    )
    completed = _trading_dates_on_or_before(row, cutoff)
    refs = [validation.evidence_ref]
    if len(completed) < 2 and callable(reader):
        previous = reader(exchange="SSE", year=current.year - 1)
        previous_validation = validate_verified_market_calendar(previous)
        if previous_validation.verified:
            previous_completed = _trading_dates_on_or_before(previous, cutoff)
            completed = [*previous_completed, *completed]
            if previous_validation.evidence_ref not in refs:
                refs.append(previous_validation.evidence_ref)
    next_dates = sorted(
        day["date"] for day in days if day["is_trading_day"] and day["date"] > today
    )
    if not next_dates and callable(reader):
        following = reader(exchange="SSE", year=current.year + 1)
        if validate_verified_market_calendar(following).verified:
            next_dates = sorted(
                day["date"]
                for day in _calendar_days(following)
                if day["is_trading_day"]
            )
    latest = completed[-1] if completed else None
    previous_completed_date = completed[-2] if len(completed) > 1 else None
    result.update(
        status=status,
        latest_completed_trade_date=latest,
        previous_completed_trade_date=previous_completed_date,
        expected_quote_date=today if trading_day and clock >= time(9, 30) else latest,
        next_trading_date=next_dates[0] if next_dates else None,
        calendar_evidence_refs=refs,
        blockers=[] if latest else ["latest_completed_trading_session_unavailable"],
    )
    return result


@dataclass(frozen=True, slots=True)
class VerifiedClosedTradingDate:
    trade_date: str
    calendar_evidence_refs: tuple[str, ...]


def resolve_latest_verified_closed_trading_date(
    db: Any,
    now: datetime,
    *,
    ingestion_time: time = POST_CLOSE_INGESTION_TIME,
) -> VerifiedClosedTradingDate | None:
    """Resolve a closed SSE session from complete, review-bound calendars."""
    current = get_shanghai_now(now)
    cutoff_date = current.date()
    if current.time() < ingestion_time:
        cutoff_date -= timedelta(days=1)
    row = db.get_market_calendar_snapshot_sync(
        exchange="SSE",
        year=cutoff_date.year,
    )
    validation = validate_verified_market_calendar(row)
    if not validation.verified or validation.evidence_ref is None:
        return None
    candidates = _trading_dates_on_or_before(row, cutoff_date.isoformat())
    evidence_refs = [validation.evidence_ref]
    if not candidates:
        previous = db.get_market_calendar_snapshot_sync(
            exchange="SSE",
            year=cutoff_date.year - 1,
        )
        previous_validation = validate_verified_market_calendar(previous)
        if not previous_validation.verified or previous_validation.evidence_ref is None:
            return None
        candidates = _trading_dates_on_or_before(previous, cutoff_date.isoformat())
        evidence_refs.append(previous_validation.evidence_ref)
    if not candidates:
        return None
    return VerifiedClosedTradingDate(
        trade_date=candidates[-1],
        calendar_evidence_refs=tuple(evidence_refs),
    )


def resolve_verified_closed_trading_dates(
    db: Any,
    now: datetime,
    *,
    lookback_days: int = 30,
    ingestion_time: time = POST_CLOSE_INGESTION_TIME,
) -> tuple[VerifiedClosedTradingDate, ...]:
    """Resolve a bounded natural-day window of verified closed SSE sessions."""
    if isinstance(lookback_days, bool) or not isinstance(lookback_days, int):
        raise TypeError("verified_trading_date_lookback_days_must_be_int")
    if lookback_days <= 0 or lookback_days > 366:
        raise ValueError("verified_trading_date_lookback_days_invalid")

    current = get_shanghai_now(now)
    cutoff_date = current.date()
    if current.time() < ingestion_time:
        cutoff_date -= timedelta(days=1)
    start_date = cutoff_date - timedelta(days=lookback_days - 1)

    resolved: list[VerifiedClosedTradingDate] = []
    for year in range(start_date.year, cutoff_date.year + 1):
        row = db.get_market_calendar_snapshot_sync(exchange="SSE", year=year)
        validation = validate_verified_market_calendar(row)
        if not validation.verified or validation.evidence_ref is None:
            return ()
        for value in _trading_dates_on_or_before(row, cutoff_date.isoformat()):
            parsed = datetime.fromisoformat(value).date()
            if parsed < start_date:
                continue
            resolved.append(
                VerifiedClosedTradingDate(
                    trade_date=value,
                    calendar_evidence_refs=(validation.evidence_ref,),
                )
            )

    resolved.sort(key=lambda item: item.trade_date)
    return tuple(resolved)


def resolve_verified_closed_trading_dates_in_range(
    db: Any,
    now: datetime,
    *,
    start_date: date,
    end_date: date,
    maximum_calendar_days: int = 366,
) -> tuple[VerifiedClosedTradingDate, ...]:
    """Select a bounded requested interval from complete, verified SSE calendars."""
    if (
        type(maximum_calendar_days) is not int
        or not 1 <= maximum_calendar_days <= 3653
        or start_date > end_date
        or (end_date - start_date).days >= maximum_calendar_days
    ):
        raise ValueError("verified_trading_date_range_invalid")
    current = get_shanghai_now(now)
    cutoff_date = current.date()
    if current.time() < POST_CLOSE_INGESTION_TIME:
        cutoff_date -= timedelta(days=1)
    if end_date > cutoff_date:
        raise ValueError("verified_trading_date_not_closed")

    resolved: list[VerifiedClosedTradingDate] = []
    for year in range(start_date.year, end_date.year + 1):
        row = db.get_market_calendar_snapshot_sync(exchange="SSE", year=year)
        validation = validate_verified_market_calendar(row)
        if not validation.verified or validation.evidence_ref is None:
            return ()
        for value in _trading_dates_on_or_before(row, end_date.isoformat()):
            if value >= start_date.isoformat():
                resolved.append(
                    VerifiedClosedTradingDate(
                        trade_date=value,
                        calendar_evidence_refs=(validation.evidence_ref,),
                    )
                )
    resolved.sort(key=lambda item: item.trade_date)
    return tuple(resolved)


def latest_verified_closed_trading_date(
    db: Any,
    now: datetime,
    *,
    ingestion_time: time = POST_CLOSE_INGESTION_TIME,
) -> str | None:
    """Return the latest officially verified trading day whose close is usable."""
    resolved = resolve_latest_verified_closed_trading_date(
        db,
        now,
        ingestion_time=ingestion_time,
    )
    return resolved.trade_date if resolved is not None else None


def _calendar_day_blockers(row: dict[str, Any]) -> list[str]:
    try:
        year_value = row.get("year")
        if year_value is None:
            raise TypeError("market calendar year is missing")
        year = int(year_value)
    except (TypeError, ValueError):
        return ["market_calendar_year_invalid"]
    days = _days(row)
    if days is None:
        return ["market_calendar_days_invalid"]
    expected_dates = _year_dates(year)
    actual_dates = [
        str(item.get("date") or "") for item in days if isinstance(item, dict)
    ]
    blockers: list[str] = []
    if len(days) != len(expected_dates) or len(actual_dates) != len(days):
        blockers.append("market_calendar_days_incomplete")
    if len(set(actual_dates)) != len(actual_dates):
        blockers.append("market_calendar_days_duplicated")
    if set(actual_dates) != expected_dates:
        blockers.append("market_calendar_day_coverage_invalid")
    if any(
        not isinstance(item.get("is_trading_day"), bool)
        for item in days
        if isinstance(item, dict)
    ):
        blockers.append("market_calendar_day_status_invalid")
    trading_count = sum(
        1
        for item in days
        if isinstance(item, dict) and item.get("is_trading_day") is True
    )
    closed_count = len(days) - trading_count
    if trading_count != int(row.get("trading_day_count") or 0):
        blockers.append("market_calendar_trading_day_count_mismatch")
    if closed_count != int(row.get("closed_day_count") or 0):
        blockers.append("market_calendar_closed_day_count_mismatch")
    return blockers


def _days(row: dict[str, Any]) -> list[Any] | None:
    value = row.get("days")
    if isinstance(value, list):
        return value
    value = row.get("days_json")
    if isinstance(value, list):
        return value
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, list) else None


def _year_dates(year: int) -> set[str]:
    current = date(year, 1, 1)
    end = date(year + 1, 1, 1)
    values: set[str] = set()
    while current < end:
        values.add(current.isoformat())
        current += timedelta(days=1)
    return values


def _validation(blockers: list[str]) -> MarketCalendarEvidenceValidation:
    return MarketCalendarEvidenceValidation(
        verified=False,
        blockers=tuple(blockers),
        source_fingerprint=None,
        official_source_fingerprint=None,
        evidence_ref=None,
    )


def _trading_dates_on_or_before(
    row: dict[str, Any] | None,
    cutoff_date: str,
) -> list[str]:
    if row is None:
        return []
    return sorted(
        str(day.get("date"))
        for day in _calendar_days(row)
        if isinstance(day, dict)
        and day.get("is_trading_day") is True
        and str(day.get("date") or "") <= cutoff_date
    )


def _calendar_days(row: dict[str, Any] | None) -> list[dict[str, Any]]:
    if row is None:
        return []
    value = row.get("days", row.get("days_json"))
    if isinstance(value, list):
        return value
    try:
        decoded = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return decoded if isinstance(decoded, list) else []


__all__ = [
    "POST_CLOSE_INGESTION_TIME",
    "MarketCalendarEvidenceValidation",
    "VerifiedClosedTradingDate",
    "latest_verified_closed_trading_date",
    "project_market_session",
    "resolve_latest_verified_closed_trading_date",
    "resolve_verified_closed_trading_dates",
    "resolve_verified_closed_trading_dates_in_range",
    "validate_verified_market_calendar",
]
