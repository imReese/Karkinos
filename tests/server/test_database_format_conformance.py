"""Conformance tests for the stable Karkinos Database Format v1."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from server.db import AppDatabase
from server.persistence.connection import connect_sqlite, sqlite_runtime_profile
from server.persistence.database_format import DATABASE_FORMAT_VERSION
from server.persistence.financial_canonical_migrations import V18_SCHEMA_OBJECTS
from server.persistence.financial_invariant_migrations import V17_SCHEMA_OBJECTS
from server.persistence.migrations import migration_registry
from server.persistence.structured_fact_migrations import V19_SCHEMA_OBJECTS

pytestmark = pytest.mark.database_format


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "app.db"
    AppDatabase(path).init_sync()
    return path


def test_format_v1_has_exact_immutable_migration_ledger(tmp_path: Path) -> None:
    path = _database(tmp_path)
    expected = [
        (item.version, item.name, item.checksum) for item in migration_registry()
    ]

    with connect_sqlite(path, readonly=True) as conn:
        actual = conn.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert DATABASE_FORMAT_VERSION == 1
    assert actual == expected


def test_format_v1_runtime_sqlite_baseline_is_enforced(tmp_path: Path) -> None:
    path = _database(tmp_path)

    with connect_sqlite(path) as conn:
        profile = sqlite_runtime_profile(conn)
        assert profile["journal_mode"] == "wal"
        assert profile["synchronous"] == 2
        assert profile["foreign_keys"] == 1
        assert profile["busy_timeout_ms"] == 2_000
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_format_v1_financial_and_structured_guards_are_present(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path)
    expected = {
        (object_type, name)
        for object_type, name in (
            *V17_SCHEMA_OBJECTS,
            *V18_SCHEMA_OBJECTS,
            *V19_SCHEMA_OBJECTS,
        )
    }

    with connect_sqlite(path, readonly=True) as conn:
        actual = {
            (row[0], row[1])
            for row in conn.execute(
                "SELECT type, name FROM sqlite_master WHERE type IN ('index','trigger')"
            )
        }

    assert expected <= actual


def test_format_v1_rejects_direct_sql_contract_bypasses(tmp_path: Path) -> None:
    path = _database(tmp_path)

    with connect_sqlite(path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="structured JSON required"):
            conn.execute(
                """
                INSERT INTO event_log (
                    event_type, timestamp, source, payload_json, created_at
                ) VALUES ('bad-json', ?, 'fixture', '{broken', ?)
                """,
                ("2026-09-18T00:00:00+00:00", "2026-09-18T00:00:00+00:00"),
            )

        with pytest.raises(
            sqlite3.IntegrityError,
            match="canonical financial decimals required",
        ):
            conn.execute(
                """
                INSERT INTO orders (
                    order_id, timestamp, symbol, side, order_type,
                    quantity, quantity_decimal, price, price_decimal,
                    asset_class, execution_mode, status, source, payload_json,
                    created_at, updated_at, currency_code, decimal_provenance
                ) VALUES (
                    'bad-decimal', ?, '600519', 'buy', 'limit',
                    1, '01', 25.5, '25.5',
                    'stock', 'paper', 'submitted', 'fixture', '{}',
                    ?, ?, 'CNY', 'exact_decimal_write_v1'
                )
                """,
                (
                    "2026-09-18T00:00:00+00:00",
                    "2026-09-18T00:00:00+00:00",
                    "2026-09-18T00:00:00+00:00",
                ),
            )

        conn.execute(
            """
            INSERT INTO event_log (
                event_type, timestamp, source, payload_json, created_at
            ) VALUES ('immutable', ?, 'fixture', '{}', ?)
            """,
            ("2026-09-18T00:00:00+00:00", "2026-09-18T00:00:00+00:00"),
        )
        with pytest.raises(
            sqlite3.IntegrityError, match="audit events are append-only"
        ):
            conn.execute(
                "UPDATE event_log SET payload_json='{}' WHERE event_type='immutable'"
            )
