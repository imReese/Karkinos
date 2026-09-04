"""Ordered, checksum-verified SQLite schema migrations.

The v0.3.0 entry records the schema that predates this migration ledger. Existing
compatibility bootstrap code runs before this registry is updated, so legacy and
new databases enter the same explicit version state. Future schema changes must
be appended here rather than added as untracked startup mutations.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import server.persistence.migration_schema_contracts as _schema_contracts
from server.persistence.legacy_trade_migration_preflight import (
    run_pending_legacy_trade_migration_preflight,
)
from server.persistence.market_identity_schema import (
    build_market_identity_schema_migration,
)
from server.persistence.quote_schema_migrations import build_quote_schema_migrations


@dataclass(frozen=True)
class SchemaMigration:
    version: int
    name: str
    statements: tuple[str, ...] = ()
    blockers: tuple[tuple[str, str], ...] = ()
    schema_contract_checksum: str | None = None

    @property
    def checksum(self) -> str:
        payload = "\0".join(
            (
                str(self.version),
                self.name,
                self.schema_contract_checksum or "",
                *(value for blocker in self.blockers for value in blocker),
                *self.statements,
            )
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


V1_BASELINE_SCHEMA_CONTRACT_CHECKSUM = (
    "06667c9d72bfa7fcbe263ee8c41a95948f839bf3a460fdb5ecb9bb45eb862f31"
)

# A pre-release v0.3.0 build recorded this v1 row after initializing an older
# controlled-ledger-posting table. Keep the checksum as provenance: the narrow
# repair below recognizes it but never rewrites the historical ledger row.
_LEGACY_V1_MIGRATION_CHECKSUM = (
    "01efbdc71a58a8e0952553ec947b270a69f2d7bb789e6b34b27764da9ac97b74"
)
_LEGACY_V1_REPAIR_TABLE = _schema_contracts.LEGACY_V1_REPAIR_TABLE
_LEGACY_V1_REPAIR_COLUMN = _schema_contracts.LEGACY_V1_REPAIR_COLUMN

_MIGRATIONS = (
    SchemaMigration(
        version=1,
        name="v0.3.0_legacy_schema_baseline",
        schema_contract_checksum=V1_BASELINE_SCHEMA_CONTRACT_CHECKSUM,
    ),
    SchemaMigration(
        version=2,
        name="canonicalize_legacy_portfolio_trades",
        blockers=(
            (
                """
                SELECT id
                FROM trades
                WHERE direction IS NULL
                   OR direction NOT IN ('buy', 'sell')
                   OR symbol IS NULL OR trim(symbol) = ''
                   OR timestamp IS NULL OR trim(timestamp) = ''
                   OR quantity IS NULL OR quantity <= 0
                   OR quantity > 1.7976931348623157e308
                   OR price IS NULL OR price <= 0
                   OR price > 1.7976931348623157e308
                   OR COALESCE(commission, 0) < 0
                   OR COALESCE(commission, 0) > 1.7976931348623157e308
                   OR quantity > 1.7976931348623157e308 / price
                   OR (
                       direction = 'buy'
                       AND quantity * price
                           > 1.7976931348623157e308 - COALESCE(commission, 0)
                   )
                LIMIT 1
                """,
                "legacy portfolio trade cannot be canonicalized safely",
            ),
        ),
        statements=(
            """
            INSERT INTO ledger_entries (
                entry_type, timestamp, amount, symbol, direction, quantity,
                price, commission, gross_amount, net_cash_impact,
                fee_rule_id, fee_rule_version, cost_basis_method, asset_class,
                note, source, source_ref, created_at
            )
            SELECT
                'trade_' || lower(t.direction), t.timestamp,
                t.quantity * t.price, t.symbol, lower(t.direction), t.quantity,
                t.price, COALESCE(t.commission, 0), t.quantity * t.price,
                CASE lower(t.direction)
                    WHEN 'buy' THEN -(t.quantity * t.price + COALESCE(t.commission, 0))
                    ELSE t.quantity * t.price - COALESCE(t.commission, 0)
                END,
                'legacy_manual_trade', 'legacy_manual_trade',
                'moving_average_buy_cost', COALESCE(t.asset_class, 'stock'),
                COALESCE(t.note, ''), 'portfolio_trade', 'trade:' || t.id,
                t.created_at
            FROM trades AS t
            WHERE lower(t.direction) IN ('buy', 'sell')
              AND NOT EXISTS (
                  SELECT 1 FROM ledger_entries AS ledger
                  WHERE ledger.source = 'portfolio_trade'
                    AND ledger.source_ref = 'trade:' || t.id
              )
            """,
            """
            INSERT INTO event_log (
                event_type, timestamp, entity_type, entity_id, source,
                source_ref, payload_json, created_at
            )
            SELECT
                'portfolio.ledger_entry.recorded', ledger.timestamp,
                'portfolio', 'default', 'ledger_entries', CAST(ledger.id AS TEXT),
                json_object(
                    'entry_id', ledger.id,
                    'entry_type', ledger.entry_type,
                    'timestamp', ledger.timestamp,
                    'symbol', ledger.symbol,
                    'direction', ledger.direction,
                    'quantity', ledger.quantity,
                    'price', ledger.price,
                    'commission', ledger.commission,
                    'asset_class', ledger.asset_class,
                    'source', ledger.source,
                    'source_ref', ledger.source_ref
                ),
                ledger.created_at
            FROM ledger_entries AS ledger
            WHERE ledger.source = 'portfolio_trade'
              AND ledger.source_ref LIKE 'trade:%'
              AND NOT EXISTS (
                  SELECT 1 FROM event_log AS event
                  WHERE event.event_type = 'portfolio.ledger_entry.recorded'
                    AND event.source = 'ledger_entries'
                    AND event.source_ref = CAST(ledger.id AS TEXT)
              )
            """,
        ),
    ),
    SchemaMigration(
        version=3,
        name="canonicalize_portfolio_cash_flows_and_bind_fund_nav_evidence",
        blockers=(
            (
                """
                SELECT id
                FROM cash_flows
                WHERE flow_type IS NULL
                   OR flow_type NOT IN ('deposit', 'withdraw')
                   OR amount IS NULL OR amount <= 0
                   OR amount > 1.7976931348623157e308
                   OR timestamp IS NULL OR trim(timestamp) = ''
                LIMIT 1
                """,
                "legacy portfolio cash flow cannot be canonicalized safely",
            ),
        ),
        statements=(
            """
            ALTER TABLE pending_fund_orders
            ADD COLUMN confirmation_quote_snapshot_id INTEGER
            """,
            """
            ALTER TABLE pending_fund_orders
            ADD COLUMN confirmation_fetch_run_id TEXT
            """,
            """
            ALTER TABLE pending_fund_orders
            ADD COLUMN confirmed_by TEXT
            """,
            """
            ALTER TABLE pending_fund_orders
            ADD COLUMN confirmation_note TEXT
            """,
            """
            INSERT INTO ledger_entries (
                entry_type, timestamp, amount, asset_class, note,
                source, source_ref, created_at
            )
            SELECT
                CASE flow.flow_type
                    WHEN 'deposit' THEN 'cash_deposit'
                    ELSE 'cash_withdrawal'
                END,
                flow.timestamp, flow.amount, 'cash', COALESCE(flow.note, ''),
                'portfolio_cash_flow', 'cash_flow:' || flow.id, flow.created_at
            FROM cash_flows AS flow
            WHERE flow.flow_type IN ('deposit', 'withdraw')
              AND flow.amount > 0
              AND flow.amount <= 1.7976931348623157e308
              AND NOT EXISTS (
                  SELECT 1 FROM ledger_entries AS ledger
                  WHERE ledger.source = 'portfolio_cash_flow'
                    AND ledger.source_ref = 'cash_flow:' || flow.id
              )
            """,
            """
            INSERT INTO event_log (
                event_type, timestamp, entity_type, entity_id, source,
                source_ref, payload_json, created_at
            )
            SELECT
                'portfolio.ledger_entry.recorded', ledger.timestamp,
                'portfolio', 'default', 'ledger_entries', CAST(ledger.id AS TEXT),
                json_object(
                    'entry_id', ledger.id,
                    'entry_type', ledger.entry_type,
                    'timestamp', ledger.timestamp,
                    'amount', ledger.amount,
                    'asset_class', ledger.asset_class,
                    'note', ledger.note,
                    'source', ledger.source,
                    'source_ref', ledger.source_ref
                ),
                ledger.created_at
            FROM ledger_entries AS ledger
            WHERE ledger.source = 'portfolio_cash_flow'
              AND ledger.source_ref LIKE 'cash_flow:%'
              AND NOT EXISTS (
                  SELECT 1 FROM event_log AS event
                  WHERE event.event_type = 'portfolio.ledger_entry.recorded'
                    AND event.source = 'ledger_entries'
                    AND event.source_ref = CAST(ledger.id AS TEXT)
              )
            """,
        ),
    ),
    SchemaMigration(
        version=4,
        name="claim_operator_ledger_mutations",
        statements=(
            """
            CREATE TABLE ledger_mutation_claims (
                request_id TEXT PRIMARY KEY,
                operator_id TEXT NOT NULL,
                mutation_kind TEXT NOT NULL CHECK(
                    mutation_kind IN ('append', 'trade_settlement')
                ),
                request_fingerprint TEXT NOT NULL,
                request_json TEXT NOT NULL,
                ledger_entry_id INTEGER,
                result_json TEXT,
                result_fingerprint TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                CHECK(
                    (result_json IS NULL AND result_fingerprint IS NULL
                        AND completed_at IS NULL)
                    OR
                    (result_json IS NOT NULL AND result_fingerprint IS NOT NULL
                        AND completed_at IS NOT NULL AND ledger_entry_id IS NOT NULL)
                ),
                FOREIGN KEY(ledger_entry_id) REFERENCES ledger_entries(id)
            )
            """,
            """
            CREATE INDEX idx_ledger_mutation_claims_entry
            ON ledger_mutation_claims(ledger_entry_id, mutation_kind)
            """,
            """
            CREATE INDEX idx_ledger_mutation_claims_operator
            ON ledger_mutation_claims(operator_id, created_at DESC)
            """,
        ),
    ),
    SchemaMigration(
        version=5,
        name="claim_atomic_order_state_commands",
        statements=(
            """
            CREATE TABLE order_state_command_claims (
                command_key TEXT PRIMARY KEY,
                command_type TEXT NOT NULL CHECK(
                    command_type IN (
                        'manual_order_ticket.create',
                        'manual_order_ticket.transition',
                        'oms_order.create',
                        'oms_order.transition'
                    )
                ),
                command_fingerprint TEXT NOT NULL CHECK(
                    length(command_fingerprint) = 64
                ),
                aggregate_id TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX idx_order_state_command_claims_aggregate
            ON order_state_command_claims(aggregate_id, command_type, created_at)
            """,
        ),
    ),
    SchemaMigration(
        version=6,
        name="claim_atomic_portfolio_mutations",
        statements=(
            """
            CREATE TABLE portfolio_mutation_claims (
                command_id TEXT PRIMARY KEY,
                operator_id TEXT NOT NULL,
                mutation_kind TEXT NOT NULL CHECK(
                    mutation_kind IN (
                        'manual_trade.record',
                        'manual_trade.correct',
                        'pending_fund_order.create',
                        'pending_fund_order.confirm',
                        'cash_flow.record',
                        'cash_flow.correct'
                    )
                ),
                request_fingerprint TEXT NOT NULL CHECK(
                    length(request_fingerprint) = 64
                ),
                request_json TEXT NOT NULL,
                result_json TEXT,
                result_fingerprint TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                CHECK(
                    (result_json IS NULL AND result_fingerprint IS NULL
                        AND completed_at IS NULL)
                    OR
                    (result_json IS NOT NULL AND result_fingerprint IS NOT NULL
                        AND completed_at IS NOT NULL)
                )
            )
            """,
            """
            CREATE INDEX idx_portfolio_mutation_claims_operator
            ON portfolio_mutation_claims(operator_id, created_at DESC)
            """,
            """
            CREATE INDEX idx_portfolio_mutation_claims_kind
            ON portfolio_mutation_claims(mutation_kind, created_at DESC)
            """,
        ),
    ),
    SchemaMigration(
        version=7,
        name="bind_market_calendar_official_evidence",
        statements=(
            """
            ALTER TABLE market_calendar_snapshots
            ADD COLUMN verification_source_fingerprint TEXT
            """,
            """
            ALTER TABLE market_calendar_snapshots
            ADD COLUMN official_source_fingerprint TEXT
            """,
            """
            UPDATE market_calendar_snapshots
            SET official_verification_status = 'needs_review',
                official_verified_at = NULL,
                official_verified_by = NULL,
                verification_source_fingerprint = NULL,
                official_source_fingerprint = NULL
            WHERE official_verification_status <> 'unverified'
            """,
            """
            CREATE TRIGGER market_calendar_verified_insert_guard
            BEFORE INSERT ON market_calendar_snapshots
            WHEN NEW.official_verification_status = 'verified'
             AND (
                NEW.verification_source_fingerprint IS NULL
                OR NEW.verification_source_fingerprint <> NEW.source_fingerprint
                OR length(NEW.verification_source_fingerprint) <> 64
                OR NEW.verification_source_fingerprint GLOB '*[^0-9a-f]*'
                OR NEW.official_source_fingerprint IS NULL
                OR length(NEW.official_source_fingerprint) <> 64
                OR NEW.official_source_fingerprint GLOB '*[^0-9a-f]*'
                OR trim(COALESCE(NEW.official_source_url, '')) = ''
                OR trim(COALESCE(NEW.official_verified_by, '')) = ''
                OR NEW.official_verified_at IS NULL
             )
            BEGIN
                SELECT RAISE(ABORT, 'verified market calendar evidence is incomplete');
            END
            """,
            """
            CREATE TRIGGER market_calendar_verified_update_guard
            BEFORE UPDATE ON market_calendar_snapshots
            WHEN NEW.official_verification_status = 'verified'
             AND (
                NEW.verification_source_fingerprint IS NULL
                OR NEW.verification_source_fingerprint <> NEW.source_fingerprint
                OR length(NEW.verification_source_fingerprint) <> 64
                OR NEW.verification_source_fingerprint GLOB '*[^0-9a-f]*'
                OR NEW.official_source_fingerprint IS NULL
                OR length(NEW.official_source_fingerprint) <> 64
                OR NEW.official_source_fingerprint GLOB '*[^0-9a-f]*'
                OR trim(COALESCE(NEW.official_source_url, '')) = ''
                OR trim(COALESCE(NEW.official_verified_by, '')) = ''
                OR NEW.official_verified_at IS NULL
             )
            BEGIN
                SELECT RAISE(ABORT, 'verified market calendar evidence is incomplete');
            END
            """,
        ),
    ),
    SchemaMigration(
        version=8,
        name="stage_quote_ingestion_items",
        statements=(
            """
            CREATE TABLE quote_ingestion_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_fingerprint TEXT NOT NULL,
                staged_at TEXT NOT NULL,
                UNIQUE(run_id, symbol, asset_type)
            )
            """,
            """
            CREATE INDEX idx_quote_ingestion_items_run
            ON quote_ingestion_items(run_id, id)
            """,
        ),
    ),
    *build_quote_schema_migrations(SchemaMigration),
    SchemaMigration(
        version=11,
        name="protect_immutable_valuation_snapshots",
        statements=(
            """
            CREATE TRIGGER valuation_snapshots_update_guard
            BEFORE UPDATE ON valuation_snapshots
            BEGIN
                SELECT RAISE(ABORT, 'valuation snapshots are immutable');
            END
            """,
            """
            CREATE TRIGGER valuation_snapshots_delete_guard
            BEFORE DELETE ON valuation_snapshots
            BEGIN
                SELECT RAISE(ABORT, 'valuation snapshots are immutable');
            END
            """,
        ),
    ),
    build_market_identity_schema_migration(SchemaMigration),
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
    _assert_migration_table_structure(conn)
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
    _assert_migration_table_structure(conn)
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

    run_immediate_schema_transaction(conn, repair)


def run_immediate_schema_transaction(
    conn: sqlite3.Connection,
    operation: Callable[[], Any],
) -> Any:
    """Run one schema operation under the canonical immediate transaction."""

    if conn.in_transaction:
        raise RuntimeError("schema operation requires its own write transaction")
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = operation()
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


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
        migrations=_MIGRATIONS,
        baseline_checksum=V1_BASELINE_SCHEMA_CONTRACT_CHECKSUM,
    )


def _build_schema_contract_through_version(
    initializer: Callable[[sqlite3.Connection], None],
    *,
    through_version: int,
) -> tuple[dict[str, Any], dict[tuple[str, str], str]]:
    return _schema_contracts.build_schema_contract_through_version(
        initializer,
        through_version=through_version,
        migrations=_MIGRATIONS,
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
    _schema_contracts.validate_applied_migrations(
        applied,
        migrations=_MIGRATIONS,
        legacy_v1_checksum=_LEGACY_V1_MIGRATION_CHECKSUM,
    )


def _validate_registry() -> None:
    _schema_contracts.validate_migration_registry(_MIGRATIONS)
