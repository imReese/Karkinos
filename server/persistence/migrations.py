"""Ordered, checksum-verified SQLite schema migrations.

The v0.3.0 entry records the schema that predates this migration ledger. Existing
compatibility bootstrap code runs before this registry is updated, so legacy and
new databases enter the same explicit version state. Future schema changes must
be appended here rather than added as untracked startup mutations.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class SchemaMigration:
    version: int
    name: str
    statements: tuple[str, ...] = ()
    schema_contract_checksum: str | None = None

    @property
    def checksum(self) -> str:
        payload = "\0".join(
            (
                str(self.version),
                self.name,
                self.schema_contract_checksum or "",
                *self.statements,
            )
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


V1_BASELINE_SCHEMA_CONTRACT_CHECKSUM = (
    "06667c9d72bfa7fcbe263ee8c41a95948f839bf3a460fdb5ecb9bb45eb862f31"
)

_MIGRATIONS = (
    SchemaMigration(
        version=1,
        name="v0.3.0_legacy_schema_baseline",
        schema_contract_checksum=V1_BASELINE_SCHEMA_CONTRACT_CHECKSUM,
    ),
)

CURRENT_SCHEMA_VERSION = _MIGRATIONS[-1].version

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


def apply_schema_migrations(conn: sqlite3.Connection) -> None:
    """Apply pending migrations and fail closed on unknown or changed history."""
    _validate_registry()
    conn.execute(_MIGRATION_TABLE_SQL)
    _assert_migration_table_structure(conn)
    applied = _read_applied_migrations(conn)
    _validate_applied_migrations(applied)

    for migration in _MIGRATIONS:
        if migration.version in applied:
            continue
        savepoint = f"schema_migration_{migration.version}"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
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
        return
    _validate_registry()
    _assert_migration_table_structure(conn)
    applied = _read_applied_migrations(conn)
    _validate_applied_migrations(applied)
    if 1 not in applied:
        raise RuntimeError("schema_migrations history is unexpectedly empty")
    if baseline_initializer is None:
        raise RuntimeError("v1 schema contract initializer is required")
    expected = _build_v1_baseline_contract(baseline_initializer)
    _assert_required_schema_contract(conn, expected)


def _build_v1_baseline_contract(
    initializer: Callable[[sqlite3.Connection], None],
) -> dict[str, Any]:
    with sqlite3.connect(":memory:") as expected_conn:
        initializer(expected_conn)
        contract = _read_schema_contract(expected_conn)
    checksum = _schema_contract_checksum(contract)
    if checksum != V1_BASELINE_SCHEMA_CONTRACT_CHECKSUM:
        raise RuntimeError(
            "v1 baseline schema initializer diverges from its frozen contract"
        )
    return contract


def _read_schema_contract(conn: sqlite3.Connection) -> dict[str, Any]:
    table_names = tuple(str(row[0]) for row in conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """).fetchall())
    tables: dict[str, tuple[tuple[Any, ...], ...]] = {}
    indexes: dict[str, tuple[Any, ...]] = {}
    unique_constraints: dict[str, tuple[tuple[tuple[str | None, int], ...], ...]] = {}
    for table_name in table_names:
        tables[table_name] = tuple(
            (
                str(row[1]),
                " ".join(str(row[2] or "").upper().split()),
                int(row[3]),
                _normalize_default(row[4]),
                int(row[5]),
                int(row[6]),
            )
            for row in conn.execute(
                "SELECT * FROM pragma_table_xinfo(?) ORDER BY cid", (table_name,)
            ).fetchall()
        )
        table_unique_constraints: list[tuple[tuple[str | None, int], ...]] = []
        for row in conn.execute(
            "SELECT * FROM pragma_index_list(?) ORDER BY name", (table_name,)
        ).fetchall():
            index_name = str(row[1])
            ordered_columns = tuple(
                (None if item[2] is None else str(item[2]), int(item[3]))
                for item in conn.execute(
                    "SELECT * FROM pragma_index_xinfo(?) WHERE key = 1 ORDER BY seqno",
                    (index_name,),
                ).fetchall()
            )
            origin = str(row[3])
            if origin == "c":
                indexes[index_name] = (
                    table_name,
                    int(row[2]),
                    int(row[4]),
                    ordered_columns,
                )
            elif origin == "u":
                table_unique_constraints.append(ordered_columns)
        if table_unique_constraints:
            unique_constraints[table_name] = tuple(sorted(table_unique_constraints))
    return {
        "tables": tables,
        "indexes": indexes,
        "unique_constraints": unique_constraints,
    }


def _normalize_default(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split())


def _schema_contract_checksum(contract: dict[str, Any]) -> str:
    payload = json.dumps(
        contract,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _assert_required_schema_contract(
    conn: sqlite3.Connection, expected: dict[str, Any]
) -> None:
    try:
        actual = _read_schema_contract(conn)
    except sqlite3.DatabaseError as exc:
        raise RuntimeError("database schema contract could not be verified") from exc

    actual_tables = actual["tables"]
    for table_name, expected_columns in expected["tables"].items():
        actual_columns = {
            column[0]: column for column in actual_tables.get(table_name, ())
        }
        if table_name not in actual_tables:
            raise RuntimeError(
                f"database schema contract mismatch: missing table {table_name}"
            )
        for expected_column in expected_columns:
            column_name = expected_column[0]
            if actual_columns.get(column_name) != expected_column:
                raise RuntimeError(
                    "database schema contract mismatch: "
                    f"column {table_name}.{column_name}"
                )

    actual_indexes = actual["indexes"]
    for index_name, expected_index in expected["indexes"].items():
        if actual_indexes.get(index_name) != expected_index:
            raise RuntimeError(f"database schema contract mismatch: index {index_name}")

    actual_unique_constraints = actual["unique_constraints"]
    for table_name, expected_constraints in expected["unique_constraints"].items():
        actual_constraints = set(actual_unique_constraints.get(table_name, ()))
        for expected_constraint in expected_constraints:
            if expected_constraint not in actual_constraints:
                columns = ",".join(
                    column or "<expression>" for column, _ in expected_constraint
                )
                raise RuntimeError(
                    "database schema contract mismatch: "
                    f"unique constraint {table_name}({columns})"
                )


def _assert_migration_table_structure(conn: sqlite3.Connection) -> None:
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
    registered = {migration.version: migration for migration in _MIGRATIONS}

    unknown = sorted(set(applied) - set(registered))
    if unknown:
        raise RuntimeError(
            "database schema is newer than this Karkinos build: "
            + ", ".join(str(version) for version in unknown)
        )

    registered_versions = [migration.version for migration in _MIGRATIONS]
    applied_versions = sorted(applied)
    if applied_versions != registered_versions[: len(applied_versions)]:
        raise RuntimeError("schema migration history is not an ordered registry prefix")

    for version, (name, checksum) in applied.items():
        migration = registered[version]
        if name != migration.name or checksum != migration.checksum:
            raise RuntimeError(
                f"schema migration history mismatch at version {version}"
            )


def _validate_registry() -> None:
    versions = [migration.version for migration in _MIGRATIONS]
    names = [migration.name for migration in _MIGRATIONS]
    if versions != sorted(versions) or len(versions) != len(set(versions)):
        raise RuntimeError("schema migration versions must be unique and ordered")
    if len(names) != len(set(names)):
        raise RuntimeError("schema migration names must be unique")
