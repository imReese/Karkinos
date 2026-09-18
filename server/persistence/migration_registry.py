"""Declarative, append-only SQLite migration registry."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import server.persistence.financial_canonical_migrations as _canonical_migrations
import server.persistence.financial_decimal_migrations as _decimal_migrations
import server.persistence.financial_invariant_migrations as _invariant_migrations
import server.persistence.migration_schema_contracts as _schema_contracts
import server.persistence.structured_fact_migrations as _structured_migrations
from server.persistence.job_schema_migrations import V13_DURABLE_BACKGROUND_JOBS
from server.persistence.market_identity_schema import (
    build_market_identity_schema_migration,
)
from server.persistence.quote_schema_migrations import (
    build_legacy_mutated_v14,
    build_quote_schema_migrations,
)


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
LEGACY_V1_MIGRATION_CHECKSUM = (
    "01efbdc71a58a8e0952553ec947b270a69f2d7bb789e6b34b27764da9ac97b74"
)
LEGACY_V1_REPAIR_TABLE = _schema_contracts.LEGACY_V1_REPAIR_TABLE
LEGACY_V1_REPAIR_COLUMN = _schema_contracts.LEGACY_V1_REPAIR_COLUMN

_QUOTE_MIGRATIONS = build_quote_schema_migrations(SchemaMigration)
LEGACY_MUTATED_V14 = build_legacy_mutated_v14(SchemaMigration)
LEGACY_HISTORY_VARIANTS = {14: LEGACY_MUTATED_V14}
MIGRATIONS = (
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
    *_QUOTE_MIGRATIONS[:2],
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
    SchemaMigration(
        version=13,
        name="durable_background_jobs",
        statements=V13_DURABLE_BACKGROUND_JOBS,
    ),
    *_QUOTE_MIGRATIONS[2:],
    _decimal_migrations.build_financial_decimal_migration(SchemaMigration),
    _invariant_migrations.build_financial_invariant_migration(SchemaMigration),
    _canonical_migrations.build_financial_canonical_migration(SchemaMigration),
    _structured_migrations.build_structured_fact_migration(SchemaMigration),
)
