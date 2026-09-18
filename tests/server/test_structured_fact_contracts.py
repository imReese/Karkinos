from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from server.db import AppDatabase
from server.persistence.connection import connect_sqlite


def test_event_log_rejects_malformed_json_from_direct_sql(tmp_path: Path) -> None:
    path = tmp_path / "app.db"
    AppDatabase(path).init_sync()

    with connect_sqlite(path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="structured JSON required"):
            conn.execute(
                """
                INSERT INTO event_log (
                    event_type, timestamp, source, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "fixture.invalid",
                    "2026-09-18T01:00:00+00:00",
                    "fixture",
                    "{not-json",
                    "2026-09-18T01:00:00+00:00",
                ),
            )


def test_mutation_claim_rejects_malformed_json_from_direct_sql(
    tmp_path: Path,
) -> None:
    path = tmp_path / "app.db"
    AppDatabase(path).init_sync()

    with connect_sqlite(path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="structured JSON required"):
            conn.execute(
                """
                INSERT INTO portfolio_mutation_claims (
                    command_id, operator_id, mutation_kind, request_fingerprint,
                    request_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "fixture-command",
                    "fixture-operator",
                    "cash_flow.record",
                    "a" * 64,
                    "{broken",
                    "2026-09-18T01:00:00+00:00",
                ),
            )


def test_structured_fact_guards_accept_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "app.db"
    AppDatabase(path).init_sync()

    with connect_sqlite(path) as conn:
        conn.execute(
            """
            INSERT INTO event_log (
                event_type, timestamp, source, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "fixture.valid",
                "2026-09-18T01:00:00+00:00",
                "fixture",
                '{"ok":true}',
                "2026-09-18T01:00:00+00:00",
            ),
        )
        conn.commit()
        assert conn.execute(
            "SELECT payload_json FROM event_log WHERE event_type='fixture.valid'"
        ).fetchone() == ('{"ok":true}',)
