"""Transaction-local reads for controlled clearance persistence."""

from __future__ import annotations

import sqlite3
from typing import Any


def find_existing_clearance(
    conn: sqlite3.Connection,
    requested: dict[str, Any],
) -> sqlite3.Row | None:
    return conn.execute(
        """
            SELECT *
            FROM controlled_submission_reconciliation_clearances
            WHERE clearance_id = ? OR submit_intent_id = ? OR order_id = ?
            ORDER BY id ASC LIMIT 1
            """,
        (
            requested["clearance_id"],
            requested["submit_intent_id"],
            requested["order_id"],
        ),
    ).fetchone()


def get_submit_intent(
    conn: sqlite3.Connection,
    submit_intent_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
            SELECT * FROM controlled_broker_submit_intents
            WHERE submit_intent_id = ? LIMIT 1
            """,
        (submit_intent_id,),
    ).fetchone()


def get_oms_order(
    conn: sqlite3.Connection,
    order_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM oms_orders WHERE order_id = ? LIMIT 1",
        (order_id,),
    ).fetchone()


def get_latest_reconciliation_item(
    conn: sqlite3.Connection,
    order_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
            SELECT * FROM execution_reconciliation_items
            WHERE order_id = ? ORDER BY id DESC LIMIT 1
            """,
        (order_id,),
    ).fetchone()


def get_latest_usable_broker_import(
    conn: sqlite3.Connection,
) -> sqlite3.Row | None:
    return conn.execute("""
            SELECT * FROM broker_import_runs
            WHERE validation_status != 'blocked'
            ORDER BY created_at DESC, id DESC LIMIT 1
            """).fetchone()


def get_broker_evidence_event(
    conn: sqlite3.Connection,
    *,
    import_run_id: Any,
    event_id: Any,
    row_fingerprint: Any,
) -> sqlite3.Row | None:
    return conn.execute(
        """
            SELECT * FROM broker_evidence_events
            WHERE import_run_id = ? AND event_id = ?
              AND row_fingerprint = ?
            LIMIT 1
            """,
        (import_run_id, event_id, row_fingerprint),
    ).fetchone()


def get_fill(
    conn: sqlite3.Connection,
    fill_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM fills WHERE fill_id = ? LIMIT 1",
        (fill_id,),
    ).fetchone()


def get_saved_clearance(
    conn: sqlite3.Connection,
    clearance_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
            SELECT * FROM controlled_submission_reconciliation_clearances
            WHERE clearance_id = ? LIMIT 1
            """,
        (clearance_id,),
    ).fetchone()
