"""SQLite repository for persisted market-calendar evidence."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class MarketCalendarRepository:
    """Own market-calendar persistence without provider or scheduling behavior."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    def upsert_snapshot(self, snapshot: Any) -> dict[str, Any]:
        payload = (
            snapshot.to_payload() if hasattr(snapshot, "to_payload") else dict(snapshot)
        )
        now = datetime.now().isoformat()
        days = payload.get("days") or []
        limitations = payload.get("limitations") or []
        exchange = str(payload["exchange"]).upper()
        year = int(payload["year"])
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT *
                FROM market_calendar_snapshots
                WHERE exchange = ? AND year = ?
                LIMIT 1
                """,
                (exchange, year),
            ).fetchone()
            if existing is not None:
                payload = _merge_snapshot_payload(payload, dict(existing))
                days = payload.get("days") or []
                limitations = payload.get("limitations") or []
            conn.execute(
                """
                INSERT INTO market_calendar_snapshots (
                    exchange, year, provider, schema_version, status,
                    trading_day_count, closed_day_count, source_fingerprint,
                    official_verification_status, official_source_url,
                    official_verified_at, official_verified_by, limitations_json,
                    days_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(exchange, year) DO UPDATE SET
                    provider = excluded.provider,
                    schema_version = excluded.schema_version,
                    status = excluded.status,
                    trading_day_count = excluded.trading_day_count,
                    closed_day_count = excluded.closed_day_count,
                    source_fingerprint = excluded.source_fingerprint,
                    official_verification_status = excluded.official_verification_status,
                    official_source_url = excluded.official_source_url,
                    official_verified_at = excluded.official_verified_at,
                    official_verified_by = excluded.official_verified_by,
                    limitations_json = excluded.limitations_json,
                    days_json = excluded.days_json,
                    updated_at = excluded.updated_at
                """,
                (
                    exchange,
                    year,
                    str(payload.get("provider") or "unknown"),
                    str(payload.get("schema_version") or "karkinos.market_calendar.v1"),
                    str(payload.get("status") or "available"),
                    int(payload.get("trading_day_count") or 0),
                    int(payload.get("closed_day_count") or 0),
                    str(payload.get("source_fingerprint") or ""),
                    str(payload.get("official_verification_status") or "unverified"),
                    payload.get("official_source_url"),
                    payload.get("official_verified_at"),
                    payload.get("official_verified_by"),
                    json.dumps(limitations, ensure_ascii=False, sort_keys=True),
                    json.dumps(days, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT *
                FROM market_calendar_snapshots
                WHERE exchange = ? AND year = ?
                LIMIT 1
                """,
                (exchange, year),
            ).fetchone()
            return dict(row)

    def get_snapshot(self, *, exchange: str, year: int) -> dict[str, Any] | None:
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM market_calendar_snapshots
                WHERE exchange = ? AND year = ?
                LIMIT 1
                """,
                (str(exchange).upper(), int(year)),
            ).fetchone()
            return dict(row) if row else None

    def update_verification(
        self,
        *,
        exchange: str,
        year: int,
        verification_status: str,
        official_source_url: str | None = None,
        verified_by: str | None = None,
        review_notes: str | None = None,
        day_labels: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        row = self.get_snapshot(exchange=exchange, year=year)
        if row is None:
            return None
        now = datetime.now().isoformat()
        limitations = _json_list(row.get("limitations_json"))
        days = _json_list(row.get("days_json"))
        normalized_day_labels = {
            str(day).strip()[:10]: str(label).strip()
            for day, label in (day_labels or {}).items()
            if str(day).strip() and str(label).strip()
        }
        if normalized_day_labels:
            days = [
                (
                    {
                        **day,
                        "reason": normalized_day_labels[day.get("date")],
                        "day_type": "holiday",
                        "reason_code": "market_holiday",
                        "is_trading_day": False,
                    }
                    if isinstance(day, dict)
                    and day.get("date") in normalized_day_labels
                    and not bool(day.get("is_trading_day"))
                    else day
                )
                for day in days
            ]
        if review_notes:
            limitations = [*limitations, review_notes]
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                UPDATE market_calendar_snapshots
                SET official_verification_status = ?,
                    official_source_url = ?,
                    official_verified_at = ?,
                    official_verified_by = ?,
                    limitations_json = ?,
                    days_json = ?,
                    updated_at = ?
                WHERE exchange = ? AND year = ?
                """,
                (
                    verification_status,
                    official_source_url,
                    now,
                    verified_by,
                    json.dumps(limitations, ensure_ascii=False, sort_keys=True),
                    json.dumps(days, ensure_ascii=False, sort_keys=True),
                    now,
                    str(exchange).upper(),
                    int(year),
                ),
            )
            conn.commit()
            updated = conn.execute(
                """
                SELECT *
                FROM market_calendar_snapshots
                WHERE exchange = ? AND year = ?
                LIMIT 1
                """,
                (str(exchange).upper(), int(year)),
            ).fetchone()
            return dict(updated) if updated else None


def _merge_snapshot_payload(
    payload: dict[str, Any], existing: dict[str, Any]
) -> dict[str, Any]:
    """Preserve reviewed holiday labels when refreshing provider snapshots."""
    merged = dict(payload)
    existing_days = _json_list(existing.get("days_json"))
    incoming_days = list(merged.get("days") or [])
    existing_holiday_labels = {
        str(day.get("date")): day
        for day in existing_days
        if isinstance(day, dict)
        and day.get("reason_code") == "market_holiday"
        and not bool(day.get("is_trading_day"))
        and day.get("date")
        and day.get("reason")
    }
    if existing_holiday_labels:
        merged_days: list[dict[str, Any]] = []
        for day in incoming_days:
            if not isinstance(day, dict):
                merged_days.append(day)
                continue
            label = existing_holiday_labels.get(str(day.get("date")))
            if label and not bool(day.get("is_trading_day")):
                merged_days.append(
                    {
                        **day,
                        "day_type": "holiday",
                        "reason_code": "market_holiday",
                        "reason": label["reason"],
                        "is_trading_day": False,
                    }
                )
            else:
                merged_days.append(day)
        merged["days"] = merged_days

    existing_status = str(existing.get("official_verification_status") or "unverified")
    incoming_status = str(merged.get("official_verification_status") or "unverified")
    if existing_status != "unverified" and incoming_status == "unverified":
        merged["official_verification_status"] = existing_status
        merged["official_source_url"] = existing.get("official_source_url")
        merged["official_verified_at"] = existing.get("official_verified_at")
        merged["official_verified_by"] = existing.get("official_verified_by")

    merged["limitations"] = list(
        dict.fromkeys(
            [
                *(merged.get("limitations") or []),
                *_json_list(existing.get("limitations_json")),
            ]
        )
    )
    return merged


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    decoded = json.loads(str(value))
    return decoded if isinstance(decoded, list) else []
