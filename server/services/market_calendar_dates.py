"""Verified market-calendar date selection shared by runtime ingestion jobs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from server.services.market_calendar_evidence import (
    validate_verified_market_calendar,
)
from server.services.market_hours import get_shanghai_now

POST_CLOSE_INGESTION_TIME = time(16, 0)


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
    previous_completed = completed[-2] if len(completed) > 1 else None
    result.update(
        status=status,
        latest_completed_trade_date=latest,
        previous_completed_trade_date=previous_completed,
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
    "VerifiedClosedTradingDate",
    "latest_verified_closed_trading_date",
    "project_market_session",
    "resolve_latest_verified_closed_trading_date",
]
