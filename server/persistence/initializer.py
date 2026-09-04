"""SQLite schema initialization owned by the persistence layer."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from server.persistence.financial_fact_event_payloads import quote_instant_storage_key
from server.persistence.market_identity_migrations import (
    migrate_legacy_daily_closes_on_connection,
)
from server.persistence.migrations import (
    apply_schema_migrations,
    assert_schema_compatible,
)
from server.persistence.quote_current_materialization import (
    reconcile_quote_current_materialization_on_connection,
)
from server.persistence.schema_v1 import initialize_v1_baseline_schema


def initialize_database(database_path: str | Path) -> None:
    """Validate, initialize, and migrate one SQLite database atomically."""
    with sqlite3.connect(Path(database_path), timeout=2) as conn:
        conn.execute("PRAGMA busy_timeout=2000")
        assert_schema_compatible(
            conn,
            baseline_initializer=initialize_v1_baseline_schema,
        )
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()
        if journal_mode and str(journal_mode[0]).lower() != "wal":
            conn.execute("PRAGMA journal_mode=WAL")
        initialize_v1_baseline_schema(conn)
        apply_schema_migrations(
            conn,
            baseline_initializer=initialize_v1_baseline_schema,
        )
        _backfill_quote_snapshot_instants(conn)
        if _table_exists(conn, "daily_close_snapshots_v2"):
            migrate_legacy_daily_closes_on_connection(
                conn,
                meta_database_path=Path(database_path).parent / "meta.db",
            )
        if _table_exists(conn, "quote_current_materialization_state"):
            reconcile_quote_current_materialization_on_connection(
                conn,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        conn.commit()


def _backfill_quote_snapshot_instants(conn: sqlite3.Connection) -> None:
    """Populate the indexed canonical instant for legacy or direct quote rows."""

    columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(quote_snapshots)")
    }
    if "quote_instant_utc" not in columns:
        return
    rows = conn.execute("""
        SELECT id, timestamp
        FROM quote_snapshots
        WHERE quote_instant_utc IS NULL
        ORDER BY id
        """).fetchall()
    conn.executemany(
        """
        UPDATE quote_snapshots
        SET quote_instant_utc = ?
        WHERE id = ? AND quote_instant_utc IS NULL
        """,
        ((quote_instant_storage_key(row[1]), int(row[0])) for row in rows),
    )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return (
        conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            LIMIT 1
            """,
            (table_name,),
        ).fetchone()
        is not None
    )
