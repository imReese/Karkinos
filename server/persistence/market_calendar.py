"""SQLite repository for persisted market-calendar evidence."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from server.contracts.market_calendar import MarketCalendarVerificationCommand
from server.persistence.connection import SQLiteRepository


class MarketCalendarRepository(SQLiteRepository):
    """Own market-calendar persistence without provider or scheduling behavior."""

    def upsert_snapshot(self, snapshot: Any) -> dict[str, Any]:
        """Ingest provider evidence without accepting self-asserted verification."""

        payload = _snapshot_payload(snapshot)
        now = self._now().isoformat()
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            row = upsert_market_calendar_snapshot_in_transaction(
                conn,
                _as_unverified_provider_payload(payload),
                now=now,
                preserve_same_evidence_review=True,
            )
            conn.commit()
            return row

    def get_snapshot(self, *, exchange: str, year: int) -> dict[str, Any] | None:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = _find_snapshot(conn, exchange=exchange, year=year)
            return dict(row) if row else None

    def update_verification(
        self,
        command: MarketCalendarVerificationCommand,
    ) -> dict[str, Any] | None:
        """Apply a review only when the exact provider evidence is still current."""

        now = self._now().isoformat()
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            current = _find_snapshot(
                conn,
                exchange=command.exchange,
                year=command.year,
            )
            if current is None:
                conn.commit()
                return None
            if str(current["source_fingerprint"]) != command.source_fingerprint:
                raise ValueError(
                    "market calendar verification source fingerprint is stale"
                )
            verified_payload = bind_market_calendar_verification(
                _stored_snapshot_payload(dict(current)),
                command,
                verified_at=now,
            )
            updated = upsert_market_calendar_snapshot_in_transaction(
                conn,
                verified_payload,
                now=now,
                preserve_same_evidence_review=False,
            )
            conn.commit()
            return updated


def upsert_market_calendar_snapshot_in_transaction(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    now: str,
    preserve_same_evidence_review: bool,
) -> dict[str, Any]:
    """Write one normalized snapshot on a caller-owned transaction."""

    exchange = str(payload.get("exchange") or "").strip().upper()
    source_fingerprint = str(payload.get("source_fingerprint") or "").strip()
    try:
        year = int(payload.get("year"))
    except (TypeError, ValueError) as exc:
        raise ValueError("market calendar year is invalid") from exc
    if not exchange or not source_fingerprint:
        raise ValueError("market calendar evidence identity is incomplete")
    normalized = dict(payload)
    normalized["exchange"] = exchange
    normalized["year"] = year
    existing = _find_snapshot(conn, exchange=exchange, year=year)
    if preserve_same_evidence_review and existing is not None:
        normalized = _merge_same_evidence_review(normalized, dict(existing))
    days = list(normalized.get("days") or [])
    limitations = list(normalized.get("limitations") or [])
    conn.execute(
        """
        INSERT INTO market_calendar_snapshots (
            exchange, year, provider, schema_version, status,
            trading_day_count, closed_day_count, source_fingerprint,
            official_verification_status, official_source_url,
            verification_source_fingerprint, official_source_fingerprint,
            official_verified_at,
            official_verified_by, limitations_json, days_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(exchange, year) DO UPDATE SET
            provider = excluded.provider,
            schema_version = excluded.schema_version,
            status = excluded.status,
            trading_day_count = excluded.trading_day_count,
            closed_day_count = excluded.closed_day_count,
            source_fingerprint = excluded.source_fingerprint,
            official_verification_status = excluded.official_verification_status,
            official_source_url = excluded.official_source_url,
            verification_source_fingerprint = excluded.verification_source_fingerprint,
            official_source_fingerprint = excluded.official_source_fingerprint,
            official_verified_at = excluded.official_verified_at,
            official_verified_by = excluded.official_verified_by,
            limitations_json = excluded.limitations_json,
            days_json = excluded.days_json,
            updated_at = excluded.updated_at
        """,
        (
            exchange,
            year,
            str(normalized.get("provider") or "unknown"),
            str(normalized.get("schema_version") or "karkinos.market_calendar.v1"),
            str(normalized.get("status") or "available"),
            int(normalized.get("trading_day_count") or 0),
            int(normalized.get("closed_day_count") or 0),
            source_fingerprint,
            str(normalized.get("official_verification_status") or "unverified"),
            normalized.get("official_source_url"),
            normalized.get("verification_source_fingerprint"),
            normalized.get("official_source_fingerprint"),
            normalized.get("official_verified_at"),
            normalized.get("official_verified_by"),
            json.dumps(limitations, ensure_ascii=False, sort_keys=True),
            json.dumps(days, ensure_ascii=False, sort_keys=True),
            now,
            now,
        ),
    )
    row = _find_snapshot(conn, exchange=exchange, year=year)
    if row is None:
        raise RuntimeError("market calendar snapshot was not persisted")
    return dict(row)


def bind_market_calendar_verification(
    payload: dict[str, Any],
    command: MarketCalendarVerificationCommand,
    *,
    verified_at: str,
) -> dict[str, Any]:
    """Project one exact verification decision onto its provider snapshot."""

    if str(payload.get("source_fingerprint") or "") != command.source_fingerprint:
        raise ValueError("market calendar verification source fingerprint is stale")
    limitations = list(payload.get("limitations") or [])
    if command.review_notes:
        limitations = list(dict.fromkeys([*limitations, command.review_notes.strip()]))
    verified = command.verification_status == "verified"
    return {
        **payload,
        "official_verification_status": command.verification_status,
        "official_source_url": command.official_source_url,
        "verification_source_fingerprint": (
            command.source_fingerprint if verified else None
        ),
        "official_source_fingerprint": command.official_source_fingerprint,
        "official_verified_at": verified_at if verified else None,
        "official_verified_by": command.verified_by if verified else None,
        "limitations": limitations,
        "days": _apply_day_labels(
            list(payload.get("days") or []),
            command.day_labels,
        ),
    }


def _snapshot_payload(snapshot: Any) -> dict[str, Any]:
    return snapshot.to_payload() if hasattr(snapshot, "to_payload") else dict(snapshot)


def _stored_snapshot_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "limitations": _json_list(row.get("limitations_json")),
        "days": _json_list(row.get("days_json")),
    }


def _as_unverified_provider_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        "official_verification_status": "unverified",
        "official_source_url": None,
        "verification_source_fingerprint": None,
        "official_source_fingerprint": None,
        "official_verified_at": None,
        "official_verified_by": None,
    }


def _find_snapshot(
    conn: sqlite3.Connection,
    *,
    exchange: str,
    year: int,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM market_calendar_snapshots
        WHERE exchange = ? AND year = ?
        LIMIT 1
        """,
        (str(exchange).upper(), int(year)),
    ).fetchone()


def _merge_same_evidence_review(
    payload: dict[str, Any],
    existing: dict[str, Any],
) -> dict[str, Any]:
    """Carry review metadata only across an exact provider-evidence replay."""

    if str(payload.get("source_fingerprint") or "") != str(
        existing.get("source_fingerprint") or ""
    ):
        return payload
    merged = dict(payload)
    existing_days = _json_list(existing.get("days_json"))
    incoming_days = list(merged.get("days") or [])
    labels = {
        str(day.get("date")): str(day.get("reason"))
        for day in existing_days
        if isinstance(day, dict)
        and day.get("reason_code") == "market_holiday"
        and not bool(day.get("is_trading_day"))
        and day.get("date")
        and day.get("reason")
    }
    merged["days"] = _apply_day_labels(incoming_days, labels)
    for field in (
        "official_verification_status",
        "official_source_url",
        "verification_source_fingerprint",
        "official_source_fingerprint",
        "official_verified_at",
        "official_verified_by",
    ):
        merged[field] = existing.get(field)
    merged["limitations"] = list(
        dict.fromkeys(
            [
                *(merged.get("limitations") or []),
                *_json_list(existing.get("limitations_json")),
            ]
        )
    )
    return merged


def _apply_day_labels(
    days: list[Any],
    day_labels: dict[str, str],
) -> list[Any]:
    labels = {
        str(day).strip()[:10]: str(label).strip()
        for day, label in day_labels.items()
        if str(day).strip() and str(label).strip()
    }
    return [
        (
            {
                **day,
                "reason": labels[str(day.get("date"))],
                "day_type": "holiday",
                "reason_code": "market_holiday",
                "is_trading_day": False,
            }
            if isinstance(day, dict)
            and str(day.get("date")) in labels
            and not bool(day.get("is_trading_day"))
            else day
        )
        for day in days
    ]


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    decoded = json.loads(str(value))
    return decoded if isinstance(decoded, list) else []


__all__ = [
    "MarketCalendarRepository",
    "bind_market_calendar_verification",
    "upsert_market_calendar_snapshot_in_transaction",
]
