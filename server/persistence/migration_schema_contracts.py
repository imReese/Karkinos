"""Fail-closed schema contracts for the ordered SQLite migration ledger."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Sequence
from typing import Any, Protocol


class MigrationSpec(Protocol):
    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str: ...


LEGACY_V1_REPAIR_TABLE = "controlled_submission_ledger_postings"
LEGACY_V1_REPAIR_COLUMN = "account_truth_review_fingerprint"

_VERSIONED_SCHEMA_OBJECTS = (
    (4, "table", "ledger_mutation_claims"),
    (4, "index", "idx_ledger_mutation_claims_entry"),
    (4, "index", "idx_ledger_mutation_claims_operator"),
    (5, "table", "order_state_command_claims"),
    (5, "index", "idx_order_state_command_claims_aggregate"),
    (6, "table", "portfolio_mutation_claims"),
    (6, "index", "idx_portfolio_mutation_claims_operator"),
    (6, "index", "idx_portfolio_mutation_claims_kind"),
    (7, "trigger", "market_calendar_verified_insert_guard"),
    (7, "trigger", "market_calendar_verified_update_guard"),
    (8, "table", "quote_ingestion_items"),
    (8, "index", "idx_quote_ingestion_items_run"),
    (9, "index", "idx_quote_snapshots_identity_instant"),
    (9, "index", "idx_quote_snapshots_missing_instant"),
    (10, "table", "quote_current_materialization_state"),
    (10, "index", "idx_quote_snapshots_symbol_instant"),
    (10, "index", "uq_quote_snapshots_fetch_run_identity"),
    (12, "table", "daily_close_snapshots_v2"),
    (12, "index", "idx_quote_snapshots_typed_identity_instant"),
    (12, "index", "idx_daily_close_v2_identity_trade_date"),
)


def validate_migration_registry(migrations: Sequence[MigrationSpec]) -> None:
    versions = [migration.version for migration in migrations]
    names = [migration.name for migration in migrations]
    if versions != sorted(versions) or len(versions) != len(set(versions)):
        raise RuntimeError("schema migration versions must be unique and ordered")
    if len(names) != len(set(names)):
        raise RuntimeError("schema migration names must be unique")


def validate_applied_migrations(
    applied: dict[int, tuple[str, str]],
    *,
    migrations: Sequence[MigrationSpec],
    legacy_v1_checksum: str,
) -> None:
    registered = {migration.version: migration for migration in migrations}
    unknown = sorted(set(applied) - set(registered))
    if unknown:
        raise RuntimeError(
            "database schema is newer than this Karkinos build: "
            + ", ".join(str(version) for version in unknown)
        )
    registered_versions = [migration.version for migration in migrations]
    applied_versions = sorted(applied)
    if applied_versions != registered_versions[: len(applied_versions)]:
        raise RuntimeError("schema migration history is not an ordered registry prefix")
    for version, (name, checksum) in applied.items():
        migration = registered[version]
        if version == 1 and (name, checksum) == (
            migration.name,
            legacy_v1_checksum,
        ):
            continue
        if name != migration.name or checksum != migration.checksum:
            raise RuntimeError(
                f"schema migration history mismatch at version {version}"
            )


def has_legacy_v1_repair_column(conn: sqlite3.Connection) -> bool:
    return any(
        str(row[1]) == LEGACY_V1_REPAIR_COLUMN
        for row in conn.execute(
            f"PRAGMA table_info({LEGACY_V1_REPAIR_TABLE})"
        ).fetchall()
    )


def assert_known_legacy_v1_schema(
    conn: sqlite3.Connection,
    expected: dict[str, Any],
    applied: dict[int, tuple[str, str]],
) -> None:
    """Accept only the exact known pre-release v1 repair state."""

    assert_no_unapplied_versioned_artifacts(conn, applied)
    actual = read_schema_contract(conn)
    actual_columns = actual["tables"].get(LEGACY_V1_REPAIR_TABLE, ())
    if any(column[0] == LEGACY_V1_REPAIR_COLUMN for column in actual_columns):
        assert_required_schema_contract(conn, expected)
        return

    if tuple(applied) != (1,):
        raise RuntimeError("legacy v1 schema repair is missing after later migrations")

    legacy_expected = legacy_v1_schema_contract(expected)
    assert_required_schema_contract(conn, legacy_expected)
    if actual_columns != legacy_expected["tables"][LEGACY_V1_REPAIR_TABLE]:
        raise RuntimeError(
            f"legacy v1 schema contract mismatch: table {LEGACY_V1_REPAIR_TABLE}"
        )

    expected_constraints = legacy_expected["unique_constraints"].get(
        LEGACY_V1_REPAIR_TABLE, ()
    )
    if actual["unique_constraints"].get(LEGACY_V1_REPAIR_TABLE, ()) != (
        expected_constraints
    ):
        raise RuntimeError(
            "legacy v1 schema contract mismatch: unique constraints "
            f"{LEGACY_V1_REPAIR_TABLE}"
        )

    expected_indexes = {
        name: value
        for name, value in legacy_expected["indexes"].items()
        if value[0] == LEGACY_V1_REPAIR_TABLE
    }
    actual_indexes = {
        name: value
        for name, value in actual["indexes"].items()
        if value[0] == LEGACY_V1_REPAIR_TABLE
    }
    if actual_indexes != expected_indexes:
        raise RuntimeError(
            f"legacy v1 schema contract mismatch: indexes {LEGACY_V1_REPAIR_TABLE}"
        )

    for table_name in (
        LEGACY_V1_REPAIR_TABLE,
        "controlled_submission_ledger_corrections",
    ):
        if conn.execute(f"SELECT 1 FROM {table_name} LIMIT 1").fetchone() is not None:
            raise RuntimeError(
                f"legacy v1 schema repair requires an empty table: {table_name}"
            )


def legacy_v1_schema_contract(expected: dict[str, Any]) -> dict[str, Any]:
    tables = dict(expected["tables"])
    tables[LEGACY_V1_REPAIR_TABLE] = tuple(
        column
        for column in tables[LEGACY_V1_REPAIR_TABLE]
        if column[0] != LEGACY_V1_REPAIR_COLUMN
    )
    return {
        "tables": tables,
        "indexes": dict(expected["indexes"]),
        "unique_constraints": dict(expected["unique_constraints"]),
    }


def assert_no_unapplied_versioned_artifacts(
    conn: sqlite3.Connection,
    applied: dict[int, tuple[str, str]],
) -> None:
    artifacts = [
        name
        for version, name in versioned_schema_artifacts(conn)
        if version not in applied
    ]
    if artifacts:
        raise RuntimeError(
            "database schema has versioned artifacts missing from migration "
            f"history: {', '.join(artifacts)}"
        )


def versioned_schema_artifacts_without_ledger(
    conn: sqlite3.Connection,
) -> list[str]:
    """Detect a deleted migration ledger without mistaking a true v1 database."""

    return [name for _, name in versioned_schema_artifacts(conn)]


def versioned_schema_artifacts(
    conn: sqlite3.Connection,
) -> list[tuple[int, str]]:
    """Return schema artifacts owned by migrations after the v1 baseline."""

    artifacts: list[tuple[int, str]] = []
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    for version, object_type, name in _VERSIONED_SCHEMA_OBJECTS:
        if object_type == "table" and name in tables:
            artifacts.append((version, f"table:{name}"))
    if "pending_fund_orders" in tables:
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(pending_fund_orders)").fetchall()
        }
        for column in (
            "confirmation_quote_snapshot_id",
            "confirmation_fetch_run_id",
            "confirmed_by",
            "confirmation_note",
        ):
            if column in columns:
                artifacts.append((3, f"column:pending_fund_orders.{column}"))
    if "market_calendar_snapshots" in tables:
        columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(market_calendar_snapshots)"
            ).fetchall()
        }
        for column in (
            "verification_source_fingerprint",
            "official_source_fingerprint",
        ):
            if column in columns:
                artifacts.append((7, f"column:market_calendar_snapshots.{column}"))
    if "quote_snapshots" in tables:
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(quote_snapshots)").fetchall()
        }
        if "quote_instant_utc" in columns:
            artifacts.append((9, "column:quote_snapshots.quote_instant_utc"))
        for column in ("instrument_type", "identity_provenance"):
            if column in columns:
                artifacts.append((12, f"column:quote_snapshots.{column}"))

    objects = {
        (str(row[0]), str(row[1]))
        for row in conn.execute(
            "SELECT type, name FROM sqlite_master WHERE type IN ('index', 'trigger')"
        ).fetchall()
    }
    for version, object_type, name in _VERSIONED_SCHEMA_OBJECTS:
        if object_type != "table" and (object_type, name) in objects:
            artifacts.append((version, f"{object_type}:{name}"))
    return artifacts


def build_v1_baseline_contract(
    initializer: Callable[[sqlite3.Connection], None],
    *,
    baseline_checksum: str,
) -> dict[str, Any]:
    with sqlite3.connect(":memory:") as expected_conn:
        initializer(expected_conn)
        contract = read_schema_contract(expected_conn)
    if schema_contract_checksum(contract) != baseline_checksum:
        raise RuntimeError(
            "v1 baseline schema initializer diverges from its frozen contract"
        )
    return contract


def assert_applied_schema_contract(
    conn: sqlite3.Connection,
    *,
    baseline_initializer: Callable[[sqlite3.Connection], None],
    applied: dict[int, tuple[str, str]],
    migrations: Sequence[MigrationSpec],
    baseline_checksum: str,
) -> None:
    through_version = max(applied)
    expected, expected_objects = build_schema_contract_through_version(
        baseline_initializer,
        through_version=through_version,
        migrations=migrations,
        baseline_checksum=baseline_checksum,
    )
    assert_required_schema_contract(conn, expected)
    for (object_type, name), expected_sql in expected_objects.items():
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?",
            (object_type, name),
        ).fetchone()
        actual_sql = normalize_schema_sql(row[0]) if row is not None else None
        if actual_sql != expected_sql:
            raise RuntimeError(
                f"database schema contract mismatch: {object_type} {name}"
            )


def build_schema_contract_through_version(
    initializer: Callable[[sqlite3.Connection], None],
    *,
    through_version: int,
    migrations: Sequence[MigrationSpec],
    baseline_checksum: str,
) -> tuple[dict[str, Any], dict[tuple[str, str], str]]:
    with sqlite3.connect(":memory:") as expected_conn:
        initializer(expected_conn)
        baseline = read_schema_contract(expected_conn)
        if schema_contract_checksum(baseline) != baseline_checksum:
            raise RuntimeError(
                "v1 baseline schema initializer diverges from its frozen contract"
            )
        for migration in migrations[1:]:
            if migration.version > through_version:
                break
            for statement in migration.statements:
                expected_conn.execute(statement)
        contract = read_schema_contract(expected_conn)
        objects = read_versioned_object_contracts(
            expected_conn,
            through_version=through_version,
        )
    return contract, objects


def read_versioned_object_contracts(
    conn: sqlite3.Connection,
    *,
    through_version: int,
) -> dict[tuple[str, str], str]:
    contracts: dict[tuple[str, str], str] = {}
    for version, object_type, name in _VERSIONED_SCHEMA_OBJECTS:
        if version > through_version:
            continue
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?",
            (object_type, name),
        ).fetchone()
        if row is None or row[0] is None:
            raise RuntimeError(
                "registered migration did not produce its schema object: "
                f"{object_type} {name}"
            )
        contracts[(object_type, name)] = normalize_schema_sql(row[0])
    return contracts


def normalize_schema_sql(value: Any) -> str:
    return " ".join(str(value).split())


def read_schema_contract(conn: sqlite3.Connection) -> dict[str, Any]:
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
                normalize_default(row[4]),
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


def normalize_default(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split())


def schema_contract_checksum(contract: dict[str, Any]) -> str:
    payload = json.dumps(
        contract,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def assert_required_schema_contract(
    conn: sqlite3.Connection,
    expected: dict[str, Any],
) -> None:
    try:
        actual = read_schema_contract(conn)
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
