"""SQLite schema ownership for lifecycle collector evidence."""

from __future__ import annotations

import sqlite3


class BrokerOrderLifecycleCollectorSchemaMixin:
    def _ensure_schema(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.executescript("""
                    CREATE TABLE IF NOT EXISTS broker_order_lifecycle_collector_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL UNIQUE,
                        scope_key TEXT NOT NULL,
                        batch_fingerprint TEXT NOT NULL,
                        evidence_fingerprint TEXT NOT NULL,
                        file_fingerprint TEXT NOT NULL,
                        collector_id TEXT NOT NULL,
                        deployment_id TEXT NOT NULL,
                        collector_version TEXT NOT NULL,
                        deployment_fingerprint TEXT NOT NULL,
                        release_evidence_ref TEXT NOT NULL,
                        release_review_status TEXT NOT NULL,
                        adapter_authorization_ref TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        gateway_id TEXT NOT NULL,
                        account_alias TEXT NOT NULL,
                        account_ref_hash TEXT NOT NULL,
                        collection_mode TEXT NOT NULL,
                        source_contact_status TEXT NOT NULL,
                        connection_status TEXT NOT NULL,
                        batch_status TEXT NOT NULL,
                        cursor_previous INTEGER NOT NULL,
                        cursor_current INTEGER NOT NULL,
                        captured_at TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        event_count INTEGER NOT NULL,
                        run_status TEXT NOT NULL CHECK(run_status IN (
                            'prepared', 'recorded', 'duplicate', 'blocked'
                        )),
                        blockers_json TEXT NOT NULL DEFAULT '[]',
                        lifecycle_observation_id TEXT NOT NULL DEFAULT '',
                        prepared_preview_json TEXT NOT NULL DEFAULT '{}',
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        source_name TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_lifecycle_collector_scope_cursor
                    ON broker_order_lifecycle_collector_runs(
                        scope_key, cursor_current DESC, id DESC
                    );

                    CREATE TABLE IF NOT EXISTS broker_order_lifecycle_collector_state (
                        scope_key TEXT PRIMARY KEY,
                        collector_id TEXT NOT NULL,
                        deployment_id TEXT NOT NULL,
                        collector_version TEXT NOT NULL,
                        deployment_fingerprint TEXT NOT NULL,
                        release_evidence_ref TEXT NOT NULL,
                        release_review_status TEXT NOT NULL,
                        adapter_authorization_ref TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        gateway_id TEXT NOT NULL,
                        account_alias TEXT NOT NULL,
                        account_ref_hash TEXT NOT NULL,
                        last_cursor INTEGER NOT NULL,
                        last_run_id TEXT NOT NULL,
                        last_batch_fingerprint TEXT NOT NULL,
                        last_lifecycle_observation_id TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """)
            conn.commit()
