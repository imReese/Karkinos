"""SQLite schema initialization owned by the persistence layer."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from server.persistence.migrations import (
    apply_schema_migrations,
    assert_schema_compatible,
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
        apply_schema_migrations(conn)
        conn.commit()
