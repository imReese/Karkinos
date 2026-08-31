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
    try:
        days = json.loads(str(row.get("days_json") or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return sorted(
        str(day.get("date"))
        for day in days
        if isinstance(day, dict)
        and day.get("is_trading_day") is True
        and str(day.get("date") or "") <= cutoff_date
    )


__all__ = [
    "POST_CLOSE_INGESTION_TIME",
    "VerifiedClosedTradingDate",
    "latest_verified_closed_trading_date",
    "resolve_latest_verified_closed_trading_date",
]
