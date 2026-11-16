"""Migration 27: Archive and decommission deprecated broker automation tables.

This migration archives and decommissions the SQLite tables previously used for
automated broker session authority, automated budget reservations, live gate
snapshots, and automatic pause events.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

DEPRECATED_BROKER_TABLES: tuple[str, ...] = (
    "controlled_session_budget_reservations",
    "controlled_session_gate_snapshots",
    "controlled_session_pause_events",
    "controlled_session_rate_admissions",
    "controlled_session_replacement_events",
    "controlled_session_revocation_events",
    "controlled_session_runtime_sessions",
    "controlled_session_runtime_states",
)

V27_STATEMENTS: tuple[str, ...] = tuple(
    f'ALTER TABLE "{table}" RENAME TO "_deprecated_{table}";'
    for table in DEPRECATED_BROKER_TABLES
)


def get_deprecated_broker_tables_status(
    conn: sqlite3.Connection,
) -> dict[str, str]:
    """Inspect the current existence and naming state of deprecated broker tables."""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table';")
    existing_tables = {row[0] for row in cursor.fetchall()}

    status: dict[str, str] = {}
    for table in DEPRECATED_BROKER_TABLES:
        deprecated_name = f"_deprecated_{table}"
        if deprecated_name in existing_tables:
            status[table] = "archived"
        elif table in existing_tables:
            status[table] = "active"
        else:
            status[table] = "dropped"
    return status


def archive_deprecated_broker_tables(
    conn: sqlite3.Connection,
) -> dict[str, str]:
    """Idempotently rename deprecated broker tables to _deprecated_* prefix."""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table';")
    existing_tables = {row[0] for row in cursor.fetchall()}

    actions: dict[str, str] = {}
    for table in DEPRECATED_BROKER_TABLES:
        deprecated_name = f"_deprecated_{table}"
        if deprecated_name in existing_tables:
            actions[table] = "already_archived"
        elif table in existing_tables:
            cursor.execute(f'ALTER TABLE "{table}" RENAME TO "{deprecated_name}";')
            actions[table] = "renamed_to_deprecated"
        else:
            actions[table] = "not_found"
    return actions


def verify_archived_broker_tables(
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Verify integrity and row consistency of archived tables."""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table';")
    existing_tables = {row[0] for row in cursor.fetchall()}

    archived_details: dict[str, dict[str, Any]] = {}
    active_leaks: list[str] = []

    for table in DEPRECATED_BROKER_TABLES:
        deprecated_name = f"_deprecated_{table}"
        if table in existing_tables:
            active_leaks.append(table)
        if deprecated_name in existing_tables:
            cursor.execute(f'SELECT COUNT(*) FROM "{deprecated_name}";')
            row_count = cursor.fetchone()[0]
            cursor.execute(f'PRAGMA table_info("{deprecated_name}");')
            columns = [c[1] for c in cursor.fetchall()]
            archived_details[deprecated_name] = {
                "row_count": row_count,
                "columns": columns,
            }

    cursor.execute("PRAGMA integrity_check;")
    integrity = cursor.fetchall()

    cursor.execute("PRAGMA foreign_key_check;")
    foreign_keys = cursor.fetchall()

    return {
        "active_leaks": active_leaks,
        "archived_details": archived_details,
        "integrity_ok": integrity == [("ok",)],
        "foreign_keys_ok": len(foreign_keys) == 0,
        "ready_for_drop": len(active_leaks) == 0
        and integrity == [("ok",)]
        and len(foreign_keys) == 0,
    }


def drop_deprecated_broker_tables(
    conn: sqlite3.Connection,
) -> dict[str, str]:
    """Physically drop archived deprecated broker tables table-by-table."""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table';")
    existing_tables = {row[0] for row in cursor.fetchall()}

    actions: dict[str, str] = {}
    for table in DEPRECATED_BROKER_TABLES:
        deprecated_name = f"_deprecated_{table}"
        dropped_any = False
        if deprecated_name in existing_tables:
            cursor.execute(f'DROP TABLE IF EXISTS "{deprecated_name}";')
            dropped_any = True
        if table in existing_tables:
            cursor.execute(f'DROP TABLE IF EXISTS "{table}";')
            dropped_any = True
        actions[table] = "dropped" if dropped_any else "already_absent"
    return actions


def revert_archived_broker_tables(
    conn: sqlite3.Connection,
) -> dict[str, str]:
    """Revert _deprecated_* tables back to their original names for disaster recovery."""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table';")
    existing_tables = {row[0] for row in cursor.fetchall()}

    actions: dict[str, str] = {}
    for table in DEPRECATED_BROKER_TABLES:
        deprecated_name = f"_deprecated_{table}"
        if deprecated_name in existing_tables and table not in existing_tables:
            cursor.execute(f'ALTER TABLE "{deprecated_name}" RENAME TO "{table}";')
            actions[table] = "reverted_to_original"
        elif table in existing_tables:
            actions[table] = "already_original"
        else:
            actions[table] = "not_found"
    return actions
