"""Canonical fail-closed validation for authoritative market calendars."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class MarketCalendarEvidenceValidation:
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


def _calendar_day_blockers(row: dict[str, Any]) -> list[str]:
    try:
        year = int(row.get("year"))
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


__all__ = ["MarketCalendarEvidenceValidation", "validate_verified_market_calendar"]
