"""Versioned schema ownership for Karkinos ``meta.db``."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from data.market_bar_identity import _INSTRUMENT_TYPE_CHECK, MARKET_BAR_V2_SCHEMA
from data.meta_store_connection import connect_meta_sqlite

META_DATABASE_FORMAT_VERSION = 1
META_DATABASE_FORMAT_NAME = (
    f"Karkinos Market Metadata Format v{META_DATABASE_FORMAT_VERSION}"
)

_BAR_META_AUDIT_COLUMNS = {
    "provider_name": "TEXT",
    "data_source": "TEXT",
    "adjustment_mode": "TEXT",
    "fetched_at": "TEXT",
    "dataset_id": "TEXT",
    "diagnostics_json": "TEXT",
    "duplicate_timestamp_count": "INTEGER DEFAULT 0",
    "missing_ohlcv_count": "INTEGER DEFAULT 0",
    "is_monotonic": "INTEGER DEFAULT 1",
}


class MetaDatabaseSchemaError(RuntimeError):
    """The market metadata store is not compatible with the known schema."""


@dataclass(frozen=True)
class MetaSchemaMigration:
    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        payload = "\0".join((str(self.version), self.name, *self.statements))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_V1_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS bar_meta (
        symbol TEXT NOT NULL,
        frequency TEXT NOT NULL,
        start_date TEXT,
        end_date TEXT,
        last_updated TEXT,
        row_count INTEGER DEFAULT 0,
        provider_name TEXT,
        data_source TEXT,
        adjustment_mode TEXT,
        fetched_at TEXT,
        dataset_id TEXT,
        diagnostics_json TEXT,
        duplicate_timestamp_count INTEGER DEFAULT 0,
        missing_ohlcv_count INTEGER DEFAULT 0,
        is_monotonic INTEGER DEFAULT 1,
        PRIMARY KEY (symbol, frequency)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS market_bars (
        symbol TEXT NOT NULL,
        frequency TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        open REAL,
        high REAL,
        low REAL,
        close REAL NOT NULL,
        volume REAL,
        amount REAL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (symbol, frequency, timestamp)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_market_bars_symbol_frequency_ts
    ON market_bars(symbol, frequency, timestamp)
    """,
    *MARKET_BAR_V2_SCHEMA,
    """
    CREATE TABLE IF NOT EXISTS market_universe_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        trade_date TEXT NOT NULL,
        provider_name TEXT NOT NULL,
        member_count INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(trade_date, provider_name)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_market_universe_snapshots_date
    ON market_universe_snapshots(trade_date DESC, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS market_daily_ingestion_receipts (
        trade_date TEXT NOT NULL,
        provider_name TEXT NOT NULL,
        row_count INTEGER NOT NULL,
        dataset_fingerprint TEXT NOT NULL,
        receipt_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (trade_date, provider_name)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_market_daily_receipts_date
    ON market_daily_ingestion_receipts(trade_date DESC)
    """,
)

_V2_STATEMENTS = (
    "ALTER TABLE market_universe_snapshots RENAME TO market_universe_snapshots_v1",
    """
    CREATE TABLE market_universe_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        trade_date TEXT NOT NULL,
        provider_name TEXT NOT NULL,
        member_count INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        capture_started_at TEXT,
        capture_completed_at TEXT,
        available_at TEXT,
        CHECK (
            (capture_started_at IS NULL AND capture_completed_at IS NULL
             AND available_at IS NULL)
            OR
            (capture_started_at IS NOT NULL AND capture_completed_at IS NOT NULL
             AND available_at IS NOT NULL
             AND available_at = capture_completed_at
             AND capture_started_at <= capture_completed_at)
        )
    )
    """,
    """
    INSERT INTO market_universe_snapshots
        (snapshot_id, trade_date, provider_name, member_count, snapshot_json, created_at)
    SELECT snapshot_id, trade_date, provider_name, member_count, snapshot_json, created_at
    FROM market_universe_snapshots_v1
    """,
    "DROP TABLE market_universe_snapshots_v1",
    """
    CREATE INDEX idx_market_universe_snapshots_date
    ON market_universe_snapshots(trade_date DESC, available_at DESC,
                                capture_started_at DESC, snapshot_id DESC)
    """,
    """
    CREATE UNIQUE INDEX idx_market_universe_snapshots_legacy
    ON market_universe_snapshots(trade_date, provider_name)
    WHERE available_at IS NULL
    """,
    """
    CREATE INDEX idx_market_universe_snapshots_available
    ON market_universe_snapshots(provider_name, available_at DESC,
                                capture_started_at DESC, snapshot_id DESC)
    """,
)

# A development runtime applied this exact v2 definition before ee46ddc0.
# Keep its identity and original ledger entry; v3 closes its nullable CHECK gap.
_LEGACY_V2_MIGRATION = MetaSchemaMigration(
    2,
    "market_universe_observation_times_v2",
    tuple(
        statement.replace("             AND available_at IS NOT NULL\n", "")
        for statement in _V2_STATEMENTS
    ),
)

_V3_STATEMENTS = (
    "ALTER TABLE market_universe_snapshots RENAME TO market_universe_snapshots_v2",
    _V2_STATEMENTS[1],
    """
    INSERT INTO market_universe_snapshots
        (snapshot_id, trade_date, provider_name, member_count, snapshot_json,
         created_at, capture_started_at, capture_completed_at, available_at)
    SELECT snapshot_id, trade_date, provider_name, member_count, snapshot_json,
           created_at, capture_started_at, capture_completed_at, available_at
    FROM market_universe_snapshots_v2
    """,
    "DROP TABLE market_universe_snapshots_v2",
    *_V2_STATEMENTS[4:],
)

_META_MIGRATIONS = (
    MetaSchemaMigration(1, "market_metadata_format_v1", _V1_STATEMENTS),
    MetaSchemaMigration(2, "market_universe_observation_times_v2", _V2_STATEMENTS),
    MetaSchemaMigration(
        3, "market_universe_observation_times_integrity_v3", _V3_STATEMENTS
    ),
)

_MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS meta_schema_migrations (
    version INTEGER PRIMARY KEY CHECK(version > 0),
    name TEXT NOT NULL UNIQUE,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""


def _ensure_canonical_market_tables(connection: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }
    if "market_bars" not in tables and "bar_meta" not in tables:
        return

    cols_bars = (
        {row[1] for row in connection.execute("PRAGMA table_info(market_bars)")}
        if "market_bars" in tables
        else set()
    )
    cols_meta = (
        {row[1] for row in connection.execute("PRAGMA table_info(bar_meta)")}
        if "bar_meta" in tables
        else set()
    )

    if "instrument_type" not in cols_bars and "market_bars" in tables:
        connection.execute("DROP TABLE IF EXISTS market_bars_legacy_old")
        connection.execute("ALTER TABLE market_bars RENAME TO market_bars_legacy_old")
        connection.execute(f"""
        CREATE TABLE market_bars (
            symbol TEXT NOT NULL CHECK(trim(symbol) <> ''),
            instrument_type TEXT NOT NULL
                CHECK(instrument_type IN ({_INSTRUMENT_TYPE_CHECK})),
            frequency TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL NOT NULL CHECK(close > 0),
            volume REAL,
            amount REAL,
            identity_provenance TEXT NOT NULL
                CHECK(trim(identity_provenance) <> ''),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (symbol, instrument_type, frequency, timestamp)
        )
        """)
        connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_market_bars_identity_frequency_ts
        ON market_bars(symbol, instrument_type, frequency, timestamp)
        """)

        v2_type = connection.execute(
            "SELECT type FROM sqlite_master WHERE name = 'market_bars_v2'"
        ).fetchone()
        if v2_type and v2_type[0] == "view":
            connection.execute("DROP VIEW IF EXISTS market_bars_v2")
        elif v2_type and v2_type[0] == "table":
            connection.execute("""
            INSERT OR IGNORE INTO market_bars
            SELECT symbol, instrument_type, frequency, timestamp,
                   open, high, low, close, volume, amount,
                   identity_provenance, created_at, updated_at
            FROM market_bars_v2
            """)
            connection.execute("DROP TABLE IF EXISTS market_bars_v2")

        old_bar_cols = {
            row[1]
            for row in connection.execute("PRAGMA table_info(market_bars_legacy_old)")
        }
        bar_cols = [
            c
            for c in (
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "created_at",
                "updated_at",
            )
            if c in old_bar_cols
        ]
        col_names = (", " + ", ".join(bar_cols)) if bar_cols else ""
        connection.execute(f"""
        INSERT OR IGNORE INTO market_bars (
            symbol, instrument_type, frequency, timestamp, identity_provenance{col_names}
        )
        SELECT symbol, 'stock', frequency, timestamp, 'legacy_bootstrap'{col_names}
        FROM market_bars_legacy_old
        """)
        connection.execute("DROP TABLE IF EXISTS market_bars_legacy_old")

    if "instrument_type" not in cols_meta and "bar_meta" in tables:
        connection.execute("DROP TABLE IF EXISTS bar_meta_legacy_old")
        connection.execute("ALTER TABLE bar_meta RENAME TO bar_meta_legacy_old")
        connection.execute(f"""
        CREATE TABLE bar_meta (
            symbol TEXT NOT NULL CHECK(trim(symbol) <> ''),
            instrument_type TEXT NOT NULL
                CHECK(instrument_type IN ({_INSTRUMENT_TYPE_CHECK})),
            frequency TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            last_updated TEXT,
            row_count INTEGER DEFAULT 0,
            provider_name TEXT,
            data_source TEXT,
            adjustment_mode TEXT,
            fetched_at TEXT,
            dataset_id TEXT,
            diagnostics_json TEXT,
            duplicate_timestamp_count INTEGER DEFAULT 0,
            missing_ohlcv_count INTEGER DEFAULT 0,
            is_monotonic INTEGER DEFAULT 1,
            identity_provenance TEXT NOT NULL
                CHECK(trim(identity_provenance) <> ''),
            PRIMARY KEY (symbol, instrument_type, frequency)
        )
        """)

        meta_v2_type = connection.execute(
            "SELECT type FROM sqlite_master WHERE name = 'bar_meta_v2'"
        ).fetchone()
        if meta_v2_type and meta_v2_type[0] == "view":
            connection.execute("DROP VIEW IF EXISTS bar_meta_v2")
        elif meta_v2_type and meta_v2_type[0] == "table":
            connection.execute("""
            INSERT OR IGNORE INTO bar_meta
            SELECT symbol, instrument_type, frequency, start_date, end_date,
                   last_updated, row_count, provider_name, data_source,
                   adjustment_mode, fetched_at, dataset_id, diagnostics_json,
                   duplicate_timestamp_count, missing_ohlcv_count, is_monotonic,
                   identity_provenance
            FROM bar_meta_v2
            """)
            connection.execute("DROP TABLE IF EXISTS bar_meta_v2")

        old_meta_cols = {
            row[1]
            for row in connection.execute("PRAGMA table_info(bar_meta_legacy_old)")
        }
        common_cols = [
            c
            for c in (
                "start_date",
                "end_date",
                "last_updated",
                "row_count",
                "provider_name",
                "data_source",
                "adjustment_mode",
                "fetched_at",
                "dataset_id",
                "diagnostics_json",
                "duplicate_timestamp_count",
                "missing_ohlcv_count",
                "is_monotonic",
            )
            if c in old_meta_cols
        ]
        col_names = (", " + ", ".join(common_cols)) if common_cols else ""
        connection.execute(f"""
        INSERT OR IGNORE INTO bar_meta (
            symbol, instrument_type, frequency, identity_provenance{col_names}
        )
        SELECT symbol, 'stock', frequency, 'legacy_bootstrap'{col_names}
        FROM bar_meta_legacy_old
        """)
        connection.execute("DROP TABLE IF EXISTS bar_meta_legacy_old")

    for obj_name in ("market_bars_v2", "bar_meta_v2"):
        connection.execute(f"DROP TRIGGER IF EXISTS trg_{obj_name}_insert")
        connection.execute(f"DROP TRIGGER IF EXISTS trg_{obj_name}_update")
        connection.execute(f"DROP TRIGGER IF EXISTS trg_{obj_name}_delete")
        connection.execute(f"DROP VIEW IF EXISTS {obj_name}")
        connection.execute(f"DROP TABLE IF EXISTS {obj_name}")

    if "market_bars" in tables:
        connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_market_bars_symbol_frequency_ts
        ON market_bars(symbol, frequency, timestamp)
        """)
        connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_market_bars_updated_at
        ON market_bars(updated_at)
        """)


def prepare_meta_database(database_path: str | Path) -> None:
    """Bootstrap or verify ``meta.db`` under one schema owner."""

    path = Path(database_path)
    if not meta_database_requires_preparation(path):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_meta_sqlite(path)) as connection:
        mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if mode != "wal":
            connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("BEGIN IMMEDIATE")
        try:
            _prepare_on_connection(connection)
            _ensure_canonical_market_tables(connection)
            if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise MetaDatabaseSchemaError("meta_database_integrity_failed")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise


def require_meta_database_ready(database_path: str | Path) -> None:
    """Verify a prepared metadata store without mutating it."""

    path = Path(database_path)
    if not path.is_file():
        raise MetaDatabaseSchemaError("meta_database_missing")
    with closing(connect_meta_sqlite(path, readonly=True)) as connection:
        applied_count = _assert_migration_history(connection)
        _assert_market_universe_schema(connection, applied_count)
        bar_cols = {
            row[1] for row in connection.execute("PRAGMA table_info(market_bars)")
        }
        if "instrument_type" not in bar_cols:
            raise MetaDatabaseSchemaError("meta_database_market_bars_schema_mismatch")


def meta_database_requires_preparation(
    database_path: str | Path, *, verify_integrity: bool = True
) -> bool:
    """Validate known history/structure before backup or DDL, without creating files."""
    path = Path(database_path)
    if path.is_symlink():
        raise MetaDatabaseSchemaError("meta_database_path_invalid")
    if not path.exists():
        return True
    if not path.is_file() or path.stat().st_nlink != 1:
        raise MetaDatabaseSchemaError("meta_database_path_invalid")
    with closing(connect_meta_sqlite(path, readonly=True)) as connection:
        # History, table structure and rows must describe the same WAL snapshot
        # even if another preparer commits while this process waits for ownership.
        connection.execute("BEGIN")
        if verify_integrity and connection.execute("PRAGMA quick_check").fetchall() != [
            ("ok",)
        ]:
            raise MetaDatabaseSchemaError("meta_database_integrity_failed")
        if (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='meta_schema_migrations'"
            ).fetchone()
            is None
        ):
            return True
        applied_count = _assert_migration_history(connection, allow_prefix=True)
        _assert_market_universe_schema(connection, applied_count)
        if (
            applied_count >= 2
            and connection.execute(
                """
            SELECT 1 FROM market_universe_snapshots
            WHERE NOT (
                (capture_started_at IS NULL AND capture_completed_at IS NULL
                 AND available_at IS NULL)
                OR
                (capture_started_at IS NOT NULL AND capture_completed_at IS NOT NULL
                 AND available_at IS NOT NULL
                 AND available_at = capture_completed_at
                 AND capture_started_at <= capture_completed_at)
            ) LIMIT 1
            """
            ).fetchone()
            is not None
        ):
            raise MetaDatabaseSchemaError("meta_database_observation_times_incomplete")
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
        bar_cols = {
            row[1] for row in connection.execute("PRAGMA table_info(market_bars)")
        }
        return (
            applied_count < len(_META_MIGRATIONS)
            or journal_mode.lower() != "wal"
            or "instrument_type" not in bar_cols
        )


def _prepare_on_connection(connection: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "meta_schema_migrations" not in tables:
        _bootstrap_legacy_schema(connection)
        connection.execute(_MIGRATION_TABLE_SQL)
        migration = _META_MIGRATIONS[0]
        connection.execute(
            """
            INSERT INTO meta_schema_migrations(version, name, checksum, applied_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                migration.version,
                migration.name,
                migration.checksum,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    applied_count = _assert_migration_history(connection, allow_prefix=True)
    _assert_market_universe_schema(connection, applied_count)
    for migration in _META_MIGRATIONS[applied_count:]:
        for statement in migration.statements:
            connection.execute(statement)
        connection.execute(
            """
            INSERT INTO meta_schema_migrations(version, name, checksum, applied_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                migration.version,
                migration.name,
                migration.checksum,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    _assert_migration_history(connection)
    _assert_market_universe_schema(connection, len(_META_MIGRATIONS))


def _assert_market_universe_schema(
    connection: sqlite3.Connection, version: int
) -> None:
    """Never drop unknown columns or schema objects while upgrading this table."""
    statements: tuple[str, ...] = _V1_STATEMENTS if version == 1 else _V2_STATEMENTS
    if version == 2:
        identity = connection.execute(
            "SELECT name, checksum FROM meta_schema_migrations WHERE version=2"
        ).fetchone()
        if identity == (_LEGACY_V2_MIGRATION.name, _LEGACY_V2_MIGRATION.checksum):
            statements = _LEGACY_V2_MIGRATION.statements
    expected_table = next(
        statement
        for statement in statements
        if "CREATETABLEMARKET_UNIVERSE_SNAPSHOTS(" in _normalized_schema_sql(statement)
    )
    expected_indexes = {
        _normalized_schema_sql(statement)
        for statement in statements
        if "INDEX" in statement
        and "ONMARKET_UNIVERSE_SNAPSHOTS(" in _normalized_schema_sql(statement)
    }
    rows = connection.execute(
        "SELECT type, sql FROM sqlite_master WHERE tbl_name = 'market_universe_snapshots'"
    ).fetchall()
    tables = [sql for kind, sql in rows if kind == "table"]
    # Autoindexes are defined by the checked PRIMARY KEY / UNIQUE table clauses.
    indexes = {
        _normalized_schema_sql(sql)
        for kind, sql in rows
        if kind == "index" and sql is not None
    }
    if (
        len(tables) != 1
        or _normalized_schema_sql(tables[0]) != _normalized_schema_sql(expected_table)
        or indexes != expected_indexes
        or any(kind == "trigger" for kind, _ in rows)
    ):
        raise MetaDatabaseSchemaError("meta_database_market_universe_schema_mismatch")


def _normalized_schema_sql(statement: str) -> str:
    return (
        "".join(statement.split()).upper().replace("IFNOTEXISTS", "").replace('"', "")
    )


def _bootstrap_legacy_schema(connection: sqlite3.Connection) -> None:
    for statement in _V1_STATEMENTS[:3]:
        connection.execute(statement)
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(bar_meta)")}
    for name, definition in _BAR_META_AUDIT_COLUMNS.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE bar_meta ADD COLUMN {name} {definition}")
    for statement in _V1_STATEMENTS[3:]:
        connection.execute(statement)


def _assert_migration_history(
    connection: sqlite3.Connection, *, allow_prefix: bool = False
) -> int:
    try:
        rows = connection.execute(
            """
            SELECT version, name, checksum
            FROM meta_schema_migrations
            ORDER BY version
            """
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise MetaDatabaseSchemaError(
            "meta_database_migration_history_missing"
        ) from exc
    expected = [
        (migration.version, migration.name, migration.checksum)
        for migration in _META_MIGRATIONS
    ]
    expected_rows = expected[: len(rows)] if allow_prefix else expected
    normalized = [
        expected[1]
        if row
        == (
            _LEGACY_V2_MIGRATION.version,
            _LEGACY_V2_MIGRATION.name,
            _LEGACY_V2_MIGRATION.checksum,
        )
        else row
        for row in rows
    ]
    if not rows or normalized != expected_rows:
        raise MetaDatabaseSchemaError("meta_database_migration_history_mismatch")
    return len(rows)


def meta_migration_registry() -> tuple[MetaSchemaMigration, ...]:
    """Return the immutable metadata-store migration registry."""

    return _META_MIGRATIONS


__all__ = [
    "META_DATABASE_FORMAT_NAME",
    "META_DATABASE_FORMAT_VERSION",
    "MetaDatabaseSchemaError",
    "meta_migration_registry",
    "meta_database_requires_preparation",
    "prepare_meta_database",
    "require_meta_database_ready",
]
