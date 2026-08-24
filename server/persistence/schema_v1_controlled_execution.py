"""Frozen v1 controlled-execution schema and exact-terminal migration."""

from __future__ import annotations

import sqlite3

_CONTROLLED_SUBMISSION_CLEARANCE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS controlled_submission_reconciliation_clearances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clearance_id TEXT NOT NULL UNIQUE,
    clearance_fingerprint TEXT NOT NULL UNIQUE,
    submit_intent_id TEXT NOT NULL UNIQUE,
    submit_fingerprint TEXT NOT NULL,
    order_id TEXT NOT NULL UNIQUE,
    broker_order_id TEXT NOT NULL,
    review_reconciliation_run_id TEXT NOT NULL,
    review_reconciliation_item_id INTEGER NOT NULL,
    broker_evidence_fingerprint TEXT NOT NULL,
    account_truth_import_run_id TEXT NOT NULL,
    account_truth_file_fingerprint TEXT NOT NULL,
    account_truth_source_fingerprint TEXT NOT NULL,
    clearance_reconciliation_run_id TEXT NOT NULL UNIQUE,
    operator_id TEXT NOT NULL,
    operator_approval_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status = 'cleared'),
    terminal_status TEXT NOT NULL CHECK(terminal_status IN ('filled', 'cancelled')),
    fill_count INTEGER NOT NULL CHECK(fill_count >= 0),
    fill_quantity TEXT NOT NULL,
    cancelled_quantity TEXT NOT NULL,
    lifecycle_observation_id TEXT NOT NULL DEFAULT '',
    lifecycle_evidence_fingerprint TEXT NOT NULL DEFAULT '',
    lifecycle_source_sequence INTEGER NOT NULL DEFAULT 0,
    cleared_at_epoch_ms INTEGER NOT NULL CHECK(cleared_at_epoch_ms >= 0),
    cleared_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(submit_intent_id)
        REFERENCES controlled_broker_submit_intents(submit_intent_id),
    FOREIGN KEY(order_id) REFERENCES oms_orders(order_id)
);
"""


CONTROLLED_SUBMISSION_LEDGER_POSTING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS controlled_submission_ledger_postings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_id TEXT NOT NULL UNIQUE,
    posting_fingerprint TEXT NOT NULL UNIQUE,
    clearance_id TEXT NOT NULL UNIQUE,
    clearance_fingerprint TEXT NOT NULL,
    submit_intent_id TEXT NOT NULL UNIQUE,
    order_id TEXT NOT NULL UNIQUE,
    broker_order_id TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    terminal_status TEXT NOT NULL CHECK(terminal_status IN ('filled', 'cancelled')),
    clearance_reconciliation_run_id TEXT NOT NULL,
    broker_evidence_fingerprint TEXT NOT NULL,
    account_truth_import_run_id TEXT NOT NULL,
    account_truth_file_fingerprint TEXT NOT NULL,
    account_truth_source_fingerprint TEXT NOT NULL,
    account_truth_review_fingerprint TEXT NOT NULL,
    lifecycle_observation_id TEXT NOT NULL DEFAULT '',
    lifecycle_evidence_fingerprint TEXT NOT NULL DEFAULT '',
    lifecycle_source_sequence INTEGER NOT NULL DEFAULT 0,
    pre_valuation_snapshot_id TEXT NOT NULL,
    pre_valuation_as_of TEXT NOT NULL,
    pre_valuation_status TEXT NOT NULL,
    pre_ledger_cutoff_id INTEGER NOT NULL CHECK(pre_ledger_cutoff_id >= 0),
    pre_ledger_fingerprint TEXT NOT NULL,
    operator_id TEXT NOT NULL,
    operator_approval_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status = 'applied'),
    ledger_entry_count INTEGER NOT NULL CHECK(ledger_entry_count >= 0),
    ledger_entry_fingerprint TEXT NOT NULL,
    ledger_entry_ids_json TEXT NOT NULL DEFAULT '[]',
    post_ledger_cutoff_id INTEGER NOT NULL CHECK(post_ledger_cutoff_id >= 0),
    applied_at_epoch_ms INTEGER NOT NULL CHECK(applied_at_epoch_ms >= 0),
    applied_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(clearance_id)
        REFERENCES controlled_submission_reconciliation_clearances(clearance_id),
    FOREIGN KEY(submit_intent_id)
        REFERENCES controlled_broker_submit_intents(submit_intent_id),
    FOREIGN KEY(order_id) REFERENCES oms_orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_controlled_submission_ledger_posting_time
ON controlled_submission_ledger_postings(applied_at_epoch_ms DESC, id DESC);
"""


CONTROLLED_SUBMISSION_LEDGER_CORRECTION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS controlled_submission_ledger_corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    correction_id TEXT NOT NULL UNIQUE,
    correction_fingerprint TEXT NOT NULL UNIQUE,
    posting_id TEXT NOT NULL UNIQUE,
    posting_fingerprint TEXT NOT NULL,
    original_ledger_entry_ids_json TEXT NOT NULL,
    original_ledger_entry_fingerprint TEXT NOT NULL,
    reason_code TEXT NOT NULL CHECK(reason_code IN (
        'broker_evidence_superseded',
        'duplicate_controlled_posting',
        'operator_confirmed_mapping_error'
    )),
    account_truth_import_run_id TEXT NOT NULL,
    account_truth_file_fingerprint TEXT NOT NULL,
    account_truth_source_fingerprint TEXT NOT NULL,
    account_truth_review_fingerprint TEXT NOT NULL,
    pre_valuation_snapshot_id TEXT NOT NULL,
    pre_valuation_as_of TEXT NOT NULL,
    pre_valuation_status TEXT NOT NULL,
    pre_ledger_cutoff_id INTEGER NOT NULL CHECK(pre_ledger_cutoff_id > 0),
    pre_ledger_fingerprint TEXT NOT NULL,
    plan_fingerprint TEXT NOT NULL,
    operator_id TEXT NOT NULL,
    operator_approval_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status = 'applied'),
    correction_ledger_entry_id INTEGER NOT NULL UNIQUE,
    post_ledger_cutoff_id INTEGER NOT NULL CHECK(post_ledger_cutoff_id > 0),
    applied_at_epoch_ms INTEGER NOT NULL CHECK(applied_at_epoch_ms >= 0),
    applied_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(posting_id)
        REFERENCES controlled_submission_ledger_postings(posting_id),
    FOREIGN KEY(correction_ledger_entry_id) REFERENCES ledger_entries(id)
);

CREATE INDEX IF NOT EXISTS idx_controlled_submission_ledger_correction_time
ON controlled_submission_ledger_corrections(applied_at_epoch_ms DESC, id DESC);
"""


def ensure_controlled_submission_clearance_terminal_schema(
    conn: sqlite3.Connection,
) -> None:
    """Create or atomically migrate the exact-terminal clearance store."""

    savepoint = "controlled_submission_clearance_terminal_schema"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        _apply_controlled_submission_clearance_terminal_schema(conn)
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise


def _apply_controlled_submission_clearance_terminal_schema(
    conn: sqlite3.Connection,
) -> None:
    """Apply the exact-terminal schema inside the caller-owned savepoint."""

    row = conn.execute("""
        SELECT sql FROM sqlite_master
        WHERE type = 'table'
          AND name = 'controlled_submission_reconciliation_clearances'
        """).fetchone()
    if row is None:
        conn.execute(_CONTROLLED_SUBMISSION_CLEARANCE_TABLE_SQL)
    else:
        columns = {
            str(item[1])
            for item in conn.execute(
                "PRAGMA table_info(controlled_submission_reconciliation_clearances)"
            ).fetchall()
        }
        required_columns = {
            "terminal_status",
            "cancelled_quantity",
            "lifecycle_observation_id",
            "lifecycle_evidence_fingerprint",
            "lifecycle_source_sequence",
        }
        normalized_sql = "".join(str(row[0] or "").lower().split())
        requires_rebuild = not required_columns.issubset(columns) or (
            "check(fill_count>0)" in normalized_sql
        )
        if requires_rebuild:
            legacy_table = "controlled_submission_reconciliation_clearances_v2"
            conn.execute(
                "DROP INDEX IF EXISTS idx_controlled_submission_clearance_time"
            )
            legacy_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (legacy_table,),
            ).fetchone()
            if legacy_exists is not None:
                raise RuntimeError(
                    "controlled submission clearance migration recovery required"
                )
            conn.execute(
                "ALTER TABLE controlled_submission_reconciliation_clearances "
                f"RENAME TO {legacy_table}"
            )
            conn.execute(_CONTROLLED_SUBMISSION_CLEARANCE_TABLE_SQL)
            legacy_columns = {
                str(item[1])
                for item in conn.execute(
                    f"PRAGMA table_info({legacy_table})"
                ).fetchall()
            }

            def legacy(field: str, fallback: str) -> str:
                return field if field in legacy_columns else fallback

            conn.execute(f"""
                INSERT INTO controlled_submission_reconciliation_clearances (
                    id, clearance_id, clearance_fingerprint, submit_intent_id,
                    submit_fingerprint, order_id, broker_order_id,
                    review_reconciliation_run_id, review_reconciliation_item_id,
                    broker_evidence_fingerprint, account_truth_import_run_id,
                    account_truth_file_fingerprint,
                    account_truth_source_fingerprint,
                    clearance_reconciliation_run_id, operator_id,
                    operator_approval_id, status, terminal_status, fill_count,
                    fill_quantity, cancelled_quantity,
                    lifecycle_observation_id, lifecycle_evidence_fingerprint,
                    lifecycle_source_sequence, cleared_at_epoch_ms, cleared_at,
                    payload_json, created_at
                )
                SELECT
                    id, clearance_id, clearance_fingerprint, submit_intent_id,
                    submit_fingerprint, order_id, broker_order_id,
                    review_reconciliation_run_id, review_reconciliation_item_id,
                    broker_evidence_fingerprint, account_truth_import_run_id,
                    account_truth_file_fingerprint,
                    account_truth_source_fingerprint,
                    clearance_reconciliation_run_id, operator_id,
                    operator_approval_id, status,
                    {legacy('terminal_status', "'filled'")}, fill_count,
                    fill_quantity, {legacy('cancelled_quantity', "'0'")},
                    {legacy('lifecycle_observation_id', "''")},
                    {legacy('lifecycle_evidence_fingerprint', "''")},
                    {legacy('lifecycle_source_sequence', '0')},
                    cleared_at_epoch_ms, cleared_at, payload_json, created_at
                FROM {legacy_table}
                """)
            conn.execute(f"DROP TABLE {legacy_table}")
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_controlled_submission_clearance_time
        ON controlled_submission_reconciliation_clearances(cleared_at_epoch_ms DESC)
        """)


__all__ = [
    "CONTROLLED_SUBMISSION_LEDGER_CORRECTION_TABLE_SQL",
    "CONTROLLED_SUBMISSION_LEDGER_POSTING_TABLE_SQL",
    "ensure_controlled_submission_clearance_terminal_schema",
]
