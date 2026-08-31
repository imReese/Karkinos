"""SQLite schema ownership for broker order-lifecycle evidence."""

from __future__ import annotations

import sqlite3


class BrokerOrderLifecycleEvidenceSchemaMixin:
    def _ensure_schema(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.executescript("""
                    CREATE TABLE IF NOT EXISTS broker_order_lifecycle_observations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        observation_id TEXT NOT NULL UNIQUE,
                        schema_version TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        snapshot_kind TEXT NOT NULL,
                        gateway_id TEXT NOT NULL,
                        account_alias TEXT NOT NULL,
                        account_ref_hash TEXT NOT NULL,
                        source_name TEXT NOT NULL DEFAULT '',
                        source_sequence INTEGER NOT NULL CHECK(source_sequence >= 0),
                        captured_at TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        max_snapshot_age_seconds INTEGER NOT NULL,
                        file_fingerprint TEXT NOT NULL,
                        evidence_fingerprint TEXT NOT NULL,
                        validation_status TEXT NOT NULL CHECK(
                            validation_status IN ('pass', 'blocked')
                        ),
                        blockers_json TEXT NOT NULL DEFAULT '[]',
                        broker_order_id TEXT NOT NULL DEFAULT '',
                        client_order_id TEXT NOT NULL DEFAULT '',
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_order_lifecycle_scope_sequence
                    ON broker_order_lifecycle_observations(
                        provider, gateway_id, account_alias,
                        source_sequence DESC, id DESC
                    );

                    CREATE INDEX IF NOT EXISTS idx_order_lifecycle_order_ids
                    ON broker_order_lifecycle_observations(
                        broker_order_id, client_order_id, id DESC
                    );

                    CREATE TABLE IF NOT EXISTS broker_order_lifecycle_orders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        observation_id TEXT NOT NULL UNIQUE,
                        broker_order_id TEXT NOT NULL,
                        client_order_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        status TEXT NOT NULL,
                        order_quantity TEXT NOT NULL,
                        cumulative_filled_quantity TEXT NOT NULL,
                        cancelled_quantity TEXT NOT NULL,
                        average_fill_price TEXT,
                        submitted_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        order_fingerprint TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(observation_id)
                            REFERENCES broker_order_lifecycle_observations(observation_id)
                    );

                    CREATE TABLE IF NOT EXISTS broker_order_lifecycle_fills (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        observation_id TEXT NOT NULL,
                        broker_trade_id TEXT NOT NULL,
                        broker_order_id TEXT NOT NULL,
                        client_order_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        quantity TEXT NOT NULL,
                        price TEXT NOT NULL,
                        fee TEXT NOT NULL,
                        tax TEXT NOT NULL,
                        transfer_fee TEXT NOT NULL,
                        net_amount TEXT NOT NULL,
                        filled_at TEXT NOT NULL,
                        fill_fingerprint TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(observation_id, broker_trade_id),
                        FOREIGN KEY(observation_id)
                            REFERENCES broker_order_lifecycle_observations(observation_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_order_lifecycle_fills_observation
                    ON broker_order_lifecycle_fills(observation_id, filled_at, id);
                    """)
            conn.commit()
