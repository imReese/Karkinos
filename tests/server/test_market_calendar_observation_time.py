"""Calendar capture survives storage without inventing legacy availability."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from data.market_calendar import build_static_market_calendar_snapshot
from server.contracts.market_calendar import MarketCalendarVerificationCommand
from server.db import AppDatabase
from server.persistence import migrations
from server.persistence.market_calendar import MarketCalendarRepository
from server.services.research_observation_inputs import (
    ResearchObservationInputError,
    latest_closed_session,
)


def _snapshot():
    return build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2026,
        provider="fixture",
        open_dates=["2026-09-18"],
        fetched_at="2026-09-17T15:40:00+08:00",
    )


def _review(fingerprint):
    return MarketCalendarVerificationCommand(
        exchange="SSE",
        year=2026,
        source_fingerprint=fingerprint,
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="a" * 64,
        verified_by="fixture",
    )


def test_fresh_provider_default_has_explicit_timezone():
    snapshot = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2026,
        provider="fixture",
        open_dates=["2026-09-18"],
    )
    assert datetime.fromisoformat(snapshot.fetched_at).utcoffset() is not None


def test_calendar_capture_and_real_review_clock_survive_restart(tmp_path):
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    review_at = datetime(2026, 9, 18, 7, 30, tzinfo=timezone.utc)
    clock_args = []

    def now(tz=None):
        clock_args.append(tz)
        return review_at.astimezone(tz)

    repository = MarketCalendarRepository(database.path, now=now)
    original = _snapshot()
    saved = repository.upsert_snapshot(original)
    assert saved["fetched_at"] == original.fetched_at
    reviewed = repository.update_verification(_review(original.source_fingerprint))
    assert reviewed["official_verified_at"] == review_at.isoformat()
    assert clock_args == [timezone.utc, timezone.utc]
    restarted = MarketCalendarRepository(database.path).get_snapshot(
        exchange="SSE", year=2026
    )
    assert restarted["fetched_at"] == original.fetched_at
    assert latest_closed_session([restarted], now=review_at).isoformat() == "2026-09-18"
    with pytest.raises(ResearchObservationInputError, match="calendar_not_available"):
        latest_closed_session([restarted], now=review_at.replace(minute=29))


@pytest.mark.database_format
def test_v23_preserves_old_calendar_bytes_and_leaves_capture_unknown(
    tmp_path, monkeypatch
):
    path = tmp_path / "app.db"
    before = tuple(item for item in migrations._MIGRATIONS if item.version <= 22)
    with monkeypatch.context() as old:
        old.setattr(migrations, "_MIGRATIONS", before)
        AppDatabase(path).init_sync()
    with sqlite3.connect(path) as conn:
        conn.execute(
            """INSERT INTO market_calendar_snapshots (
            exchange, year, provider, schema_version, status, trading_day_count,
            closed_day_count, source_fingerprint, official_verification_status,
            limitations_json, days_json, created_at, updated_at
        ) VALUES ('SSE', 2026, 'fixture', 'karkinos.market_calendar.v1', 'available',
                  0, 365, ?, 'unverified', '[]', '[]', 'legacy-local-time', 'legacy-local-time')""",
            ("a" * 64,),
        )
        legacy = conn.execute("SELECT * FROM market_calendar_snapshots").fetchone()
        ledger = conn.execute(
            "SELECT * FROM schema_migrations ORDER BY version"
        ).fetchall()
        conn.commit()
    AppDatabase(path).init_sync()
    with sqlite3.connect(path) as conn:
        after = conn.execute("SELECT * FROM market_calendar_snapshots").fetchone()
        assert after[:-1] == legacy
        assert after[-1] is None
        assert (
            conn.execute(
                "SELECT * FROM schema_migrations WHERE version <= 22 ORDER BY version"
            ).fetchall()
            == ledger
        )
        assert (
            conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            == 23
        )
