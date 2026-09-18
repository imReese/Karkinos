"""Checksum-verified SQLite migration execution and compatibility checks."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import server.persistence.migration_schema_contracts as _schema_contracts
from server.persistence.connection import run_immediate_transaction
from server.persistence.legacy_trade_migration_preflight import (
    run_pending_legacy_trade_migration_preflight,
)
from server.persistence.migration_history_compat import (
    migrations_for_applied_history,
    normalize_known_history,
)
from server.persistence.migration_registry import (
    LEGACY_HISTORY_VARIANTS as _LEGACY_HISTORY_VARIANTS,
)
from server.persistence.migration_registry import (
    LEGACY_MUTATED_V14 as _LEGACY_MUTATED_V14,
)
from server.persistence.migration_registry import (
    LEGACY_V1_MIGRATION_CHECKSUM as _LEGACY_V1_MIGRATION_CHECKSUM,
)
from server.persistence.migration_registry import (
    LEGACY_V1_REPAIR_COLUMN as _LEGACY_V1_REPAIR_COLUMN,
)
from server.persistence.migration_registry import (
    LEGACY_V1_REPAIR_TABLE as _LEGACY_V1_REPAIR_TABLE,
)
from server.persistence.migration_registry import (
    MIGRATIONS as _MIGRATIONS,
)
from server.persistence.migration_registry import (
    V1_BASELINE_SCHEMA_CONTRACT_CHECKSUM,
    SchemaMigration,
)

CURRENT_MIGRATION_HEAD = CURRENT_SCHEMA_VERSION = _MIGRATIONS[-1].version


def migration_registry() -> tuple[SchemaMigration, ...]:
    """Return the immutable ordered migration registry."""

    return _MIGRATIONS


_MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY CHECK(version > 0),
    name TEXT NOT NULL UNIQUE,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""

_EXPECTED_MIGRATION_COLUMNS = (
    ("version", "INTEGER", 0, None, 1),
    ("name", "TEXT", 1, None, 0),
    ("checksum", "TEXT", 1, None, 0),
    ("applied_at", "TEXT", 1, None, 0),
)


def apply_schema_migrations(
    conn: sqlite3.Connection,
    *,
    baseline_initializer: Callable[[sqlite3.Connection], None] | None = None,
) -> None:
    """Apply pending migrations and fail closed on unknown or changed history."""
    _validate_registry()
    table_exists = conn.execute("""
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'schema_migrations'
        """).fetchone()
    if table_exists is None:
        if baseline_initializer is None:
            raise RuntimeError("v1 schema contract initializer is required")
        expected = _build_v1_baseline_contract(baseline_initializer)
        _assert_required_schema_contract(conn, expected)
    conn.execute(_MIGRATION_TABLE_SQL)
    assert_migration_table_structure(conn)
    applied = _read_applied_migrations(conn)
    _validate_applied_migrations(applied)
    if _uses_legacy_v1_provenance(applied):
        if baseline_initializer is None:
            raise RuntimeError("v1 schema contract initializer is required")
        expected = _build_v1_baseline_contract(baseline_initializer)
        _repair_known_legacy_v1_schema(
            conn,
            expected,
            applied,
            baseline_initializer=baseline_initializer,
        )

    for migration in _MIGRATIONS:
        if migration.version in applied:
            continue
        savepoint = f"schema_migration_{migration.version}"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            for query, blocker in migration.blockers:
                if conn.execute(query).fetchone() is not None:
                    raise RuntimeError(blocker)
            run_pending_legacy_trade_migration_preflight(
                conn,
                version=migration.version,
                name=migration.name,
            )
            for statement in migration.statements:
                conn.execute(statement)
            conn.execute(
                """
                INSERT INTO schema_migrations (version, name, checksum, applied_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    migration.version,
                    migration.name,
                    migration.checksum,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise

    if baseline_initializer is not None:
        applied = _read_applied_migrations(conn)
        _validate_applied_migrations(applied)
        _assert_no_unapplied_versioned_artifacts(conn, applied)
        _assert_applied_schema_contract(
            conn,
            baseline_initializer=baseline_initializer,
            applied=applied,
        )


def assert_schema_compatible(
    conn: sqlite3.Connection,
    *,
    baseline_initializer: Callable[[sqlite3.Connection], None] | None = None,
) -> None:
    """Reject incompatible ledgers and v1 schema before bootstrap can mutate them."""
    table_exists = conn.execute("""
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'schema_migrations'
        """).fetchone()
    if table_exists is None:
        artifacts = _versioned_schema_artifacts_without_ledger(conn)
        if artifacts:
            raise RuntimeError(
                "schema_migrations is missing while versioned schema artifacts "
                f"exist: {', '.join(artifacts)}"
            )
        return
    _validate_registry()
    assert_migration_table_structure(conn)
    applied = _read_applied_migrations(conn)
    _validate_applied_migrations(applied)
    if 1 not in applied:
        raise RuntimeError("schema_migrations history is unexpectedly empty")
    _assert_no_unapplied_versioned_artifacts(conn, applied)
    if baseline_initializer is None:
        raise RuntimeError("v1 schema contract initializer is required")
    if _uses_legacy_v1_provenance(applied):
        expected = _build_v1_baseline_contract(baseline_initializer)
        _assert_known_legacy_v1_schema(conn, expected, applied)
        if _has_legacy_v1_repair_column(conn):
            _assert_applied_schema_contract(
                conn,
                baseline_initializer=baseline_initializer,
                applied=applied,
            )
    else:
        _assert_applied_schema_contract(
            conn,
            baseline_initializer=baseline_initializer,
            applied=applied,
        )


def _uses_legacy_v1_provenance(
    applied: dict[int, tuple[str, str]],
) -> bool:
    return applied.get(1) == (
        _MIGRATIONS[0].name,
        _LEGACY_V1_MIGRATION_CHECKSUM,
    )


def _repair_known_legacy_v1_schema(
    conn: sqlite3.Connection,
    expected: dict[str, Any],
    applied: dict[int, tuple[str, str]],
    *,
    baseline_initializer: Callable[[sqlite3.Connection], None],
) -> None:
    """Add the one missing legacy column without rewriting migration history."""

    if _has_legacy_v1_repair_column(conn):
        _assert_applied_schema_contract(
            conn,
            baseline_initializer=baseline_initializer,
            applied=applied,
        )
        return

    def repair() -> None:
        # Revalidate after acquiring the write lock so an older process cannot
        # insert a posting or correction between the empty check and ALTER.
        _assert_known_legacy_v1_schema(conn, expected, applied)
        if not _has_legacy_v1_repair_column(conn):
            conn.execute(
                f"ALTER TABLE {_LEGACY_V1_REPAIR_TABLE} "
                f"ADD COLUMN {_LEGACY_V1_REPAIR_COLUMN} TEXT NOT NULL"
            )
        _assert_applied_schema_contract(
            conn,
            baseline_initializer=baseline_initializer,
            applied=applied,
        )

    if conn.in_transaction:
        repair()
    else:
        run_immediate_transaction(conn, repair)


def _build_v1_baseline_contract(
    initializer: Callable[[sqlite3.Connection], None],
) -> dict[str, Any]:
    return _schema_contracts.build_v1_baseline_contract(
        initializer,
        baseline_checksum=V1_BASELINE_SCHEMA_CONTRACT_CHECKSUM,
    )


def _assert_applied_schema_contract(
    conn: sqlite3.Connection,
    *,
    baseline_initializer: Callable[[sqlite3.Connection], None],
    applied: dict[int, tuple[str, str]],
) -> None:
    _schema_contracts.assert_applied_schema_contract(
        conn,
        baseline_initializer=baseline_initializer,
        applied=applied,
        migrations=migrations_for_applied_history(
            applied, _MIGRATIONS, _LEGACY_HISTORY_VARIANTS
        ),
        baseline_checksum=V1_BASELINE_SCHEMA_CONTRACT_CHECKSUM,
    )


_has_legacy_v1_repair_column = _schema_contracts.has_legacy_v1_repair_column
_assert_known_legacy_v1_schema = _schema_contracts.assert_known_legacy_v1_schema
_legacy_v1_schema_contract = _schema_contracts.legacy_v1_schema_contract
_assert_no_unapplied_versioned_artifacts = (
    _schema_contracts.assert_no_unapplied_versioned_artifacts
)
_versioned_schema_artifacts_without_ledger = (
    _schema_contracts.versioned_schema_artifacts_without_ledger
)
_versioned_schema_artifacts = _schema_contracts.versioned_schema_artifacts
_read_versioned_object_contracts = _schema_contracts.read_versioned_object_contracts
_normalize_schema_sql = _schema_contracts.normalize_schema_sql
_read_schema_contract = _schema_contracts.read_schema_contract
_normalize_default = _schema_contracts.normalize_default
_schema_contract_checksum = _schema_contracts.schema_contract_checksum
_assert_required_schema_contract = _schema_contracts.assert_required_schema_contract


def assert_migration_table_structure(conn: sqlite3.Connection) -> None:
    """Reject a weakened ledger table before trusting its recorded history."""
    try:
        columns = tuple(
            (
                str(row[1]),
                str(row[2]).upper(),
                int(row[3]),
                row[4],
                int(row[5]),
            )
            for row in conn.execute("PRAGMA table_info(schema_migrations)").fetchall()
        )
        indexes = conn.execute("PRAGMA index_list(schema_migrations)").fetchall()
        has_unique_name_index = any(
            int(index[2]) == 1
            and int(index[4]) == 0
            and tuple(
                str(row[2])
                for row in conn.execute(
                    "SELECT * FROM pragma_index_info(?) ORDER BY seqno",
                    (str(index[1]),),
                ).fetchall()
            )
            == ("name",)
            for index in indexes
        )
        table_row = conn.execute("""
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = 'schema_migrations'
            """).fetchone()
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(
            "schema_migrations table structure could not be verified"
        ) from exc

    table_sql = str(table_row[0]) if table_row and table_row[0] else ""
    has_positive_version_check = re.search(
        r"check\s*\(\s*version\s*>\s*0\s*\)",
        table_sql,
        flags=re.IGNORECASE,
    )
    if (
        columns != _EXPECTED_MIGRATION_COLUMNS
        or not has_unique_name_index
        or has_positive_version_check is None
    ):
        raise RuntimeError("schema_migrations table structure mismatch")


def _read_applied_migrations(
    conn: sqlite3.Connection,
) -> dict[int, tuple[str, str]]:
    return {
        int(row[0]): (str(row[1]), str(row[2]))
        for row in conn.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
    }


def _validate_applied_migrations(applied: dict[int, tuple[str, str]]) -> None:
    _schema_contracts.validate_applied_migrations(
        normalize_known_history(applied, _MIGRATIONS, _LEGACY_HISTORY_VARIANTS),
        migrations=_MIGRATIONS,
        legacy_v1_checksum=_LEGACY_V1_MIGRATION_CHECKSUM,
    )


def _validate_registry() -> None:
    _schema_contracts.validate_migration_registry(_MIGRATIONS)
