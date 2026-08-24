"""SQLite schema ownership for controlled broker cancellation claims."""

from __future__ import annotations

import sqlite3
from pathlib import Path

CONTROLLED_BROKER_CANCELLATION_COMMAND_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS controlled_broker_cancellation_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cancel_command_id TEXT NOT NULL UNIQUE,
    cancel_fingerprint TEXT NOT NULL UNIQUE,
    submit_intent_id TEXT NOT NULL UNIQUE,
    submit_fingerprint TEXT NOT NULL,
    ticket_fingerprint TEXT NOT NULL,
    order_id TEXT NOT NULL UNIQUE,
    order_fingerprint TEXT NOT NULL,
    provider TEXT NOT NULL,
    gateway_id TEXT NOT NULL,
    account_alias TEXT NOT NULL,
    broker_order_id TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    release_evidence_id TEXT NOT NULL,
    release_evidence_fingerprint TEXT NOT NULL,
    lifecycle_observation_id TEXT NOT NULL,
    lifecycle_evidence_fingerprint TEXT NOT NULL,
    lifecycle_source_sequence INTEGER NOT NULL CHECK(lifecycle_source_sequence >= 0),
    operator_id TEXT NOT NULL,
    operator_approval_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'prepared', 'cancel_requested', 'cancel_rejected', 'cancellation_unknown'
    )),
    prepared_at_epoch_ms INTEGER NOT NULL CHECK(prepared_at_epoch_ms >= 0),
    prepared_at TEXT NOT NULL,
    finalized_at_epoch_ms INTEGER NOT NULL DEFAULT 0,
    finalized_at TEXT NOT NULL DEFAULT '',
    last_query_at_epoch_ms INTEGER NOT NULL DEFAULT 0,
    last_query_at TEXT NOT NULL DEFAULT '',
    query_count INTEGER NOT NULL DEFAULT 0 CHECK(query_count >= 0),
    payload_json TEXT NOT NULL,
    result_json TEXT NOT NULL DEFAULT '{}',
    last_query_result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_controlled_broker_cancellation_time
ON controlled_broker_cancellation_commands(prepared_at_epoch_ms DESC, id DESC);
"""

CONTROLLED_BROKER_CANCELLATION_RECOVERY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS controlled_broker_cancellation_recovery_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recovery_claim_id TEXT NOT NULL UNIQUE,
    recovery_fingerprint TEXT NOT NULL,
    cancel_command_id TEXT NOT NULL,
    query_sequence INTEGER NOT NULL CHECK(query_sequence > 0),
    operator_id TEXT NOT NULL,
    operator_approval_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('claimed', 'completed')),
    claimed_at_epoch_ms INTEGER NOT NULL CHECK(claimed_at_epoch_ms >= 0),
    claimed_at TEXT NOT NULL,
    completed_at_epoch_ms INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(cancel_command_id, query_sequence),
    FOREIGN KEY(cancel_command_id)
        REFERENCES controlled_broker_cancellation_commands(cancel_command_id)
);

CREATE INDEX IF NOT EXISTS idx_controlled_broker_cancellation_recovery_time
ON controlled_broker_cancellation_recovery_claims(
    cancel_command_id, query_sequence DESC, id DESC
);
"""


def ensure_controlled_broker_cancellation_schema(database_path: str | Path) -> None:
    """Create cancellation-owned tables only on an explicit write path."""

    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(CONTROLLED_BROKER_CANCELLATION_COMMAND_TABLE_SQL)
        connection.executescript(CONTROLLED_BROKER_CANCELLATION_RECOVERY_TABLE_SQL)
        connection.commit()


def controlled_broker_cancellation_table_exists(
    database_path: str | Path,
    table_name: str,
) -> bool:
    """Check schema availability without creating files or tables."""

    path = Path(database_path)
    if not path.exists():
        return False
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = ? LIMIT 1
            """,
            (table_name,),
        ).fetchone()
        return row is not None
