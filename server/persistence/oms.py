"""SQLite repository for OMS orders and their append-only transitions."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from server.persistence.connection import DateTimeNow, SQLiteRepository
from server.persistence.database_support import (
    account_truth_review_identity_from_connection,
    action_task_event_payload,
    apply_manual_confirmation_readiness,
    controlled_broker_submit_rejection,
    controlled_lifecycle_invalidated_clearance_rows,
    controlled_session_authority_rejection,
    controlled_session_budget_rejection,
    controlled_session_gate_snapshot_rejection,
    controlled_session_pause_rejection,
    controlled_session_rate_admission_rejection,
    controlled_submission_clearance_rejection,
    controlled_submission_ledger_correction_rejection,
    controlled_submission_ledger_posting_rejection,
    decimal_values_equal,
    event_log_response,
    event_matches_signal_journal_entry,
    fill_event_payload,
    json_dict,
    json_list,
    latest_quote_event_payload,
    latest_signal_journal_event,
    manual_order_event_payload,
    metadata_payload_value,
    normalize_timestamp,
    order_event_payload,
    paper_shadow_run_review_next_step,
    quote_observation_rank,
    risk_decision_journal_response,
    serialize_metadata_json,
    stable_json_fingerprint,
    validate_paper_shadow_run_review_transition,
    verify_controlled_ledger_entry,
)
from server.persistence.event_log import (
    insert_event_sync,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)

logger = logging.getLogger(__name__)


class OmsRepository(SQLiteRepository):
    """Own OMS orders and their append-only transitions."""

    def get_oms_order_sync(self, order_id: str) -> dict[str, Any] | None:
        """Read one OMS order by its stable order ID."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM oms_orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_oms_order_by_intent_key_sync(
        self, intent_key: str
    ) -> dict[str, Any] | None:
        """Read one OMS order by its idempotency key."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM oms_orders WHERE intent_key = ?",
                (intent_key,),
            ).fetchone()
            return dict(row) if row else None

    def upsert_oms_order_sync(self, order: dict[str, Any]) -> dict[str, Any]:
        """Persist or update an OMS order fact."""
        now = self._now().isoformat()
        payload_json = json.dumps(
            order.get("payload") or {},
            ensure_ascii=False,
            sort_keys=True,
        )
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT created_at
                FROM oms_orders
                WHERE order_id = ?
                LIMIT 1
                """,
                (order["order_id"],),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO oms_orders (
                    order_id, intent_key, symbol, side, asset_class, quantity,
                    order_type, limit_price, status, broker_submission_enabled,
                    source, source_ref, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    intent_key = excluded.intent_key,
                    symbol = excluded.symbol,
                    side = excluded.side,
                    asset_class = excluded.asset_class,
                    quantity = excluded.quantity,
                    order_type = excluded.order_type,
                    limit_price = excluded.limit_price,
                    status = excluded.status,
                    broker_submission_enabled = excluded.broker_submission_enabled,
                    source = excluded.source,
                    source_ref = excluded.source_ref,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    order["order_id"],
                    order["intent_key"],
                    order["symbol"],
                    order["side"],
                    order["asset_class"],
                    float(order["quantity"]),
                    order["order_type"],
                    order.get("limit_price"),
                    order["status"],
                    1 if order.get("broker_submission_enabled") else 0,
                    order["source"],
                    order.get("source_ref"),
                    payload_json,
                    created_at,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM oms_orders WHERE order_id = ?",
                (order["order_id"],),
            ).fetchone()
            conn.commit()
            return dict(row)

    def update_oms_order_status_sync(
        self,
        *,
        order_id: str,
        status: str,
    ) -> dict[str, Any]:
        """Update one OMS order status."""
        now = self._now().isoformat()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                UPDATE oms_orders
                SET status = ?, updated_at = ?
                WHERE order_id = ?
                """,
                (status, now, order_id),
            )
            row = conn.execute(
                "SELECT * FROM oms_orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            conn.commit()
            if row is None:
                raise KeyError(f"OMS order not found: {order_id}")
            return dict(row)

    def record_oms_transition_sync(
        self,
        *,
        order_id: str,
        from_status: str,
        to_status: str,
        reason: str,
        actor: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record one OMS state transition."""
        now = self._now().isoformat()
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """
                INSERT INTO oms_transitions (
                    order_id, from_status, to_status, reason, actor,
                    payload_json, transitioned_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    from_status,
                    to_status,
                    reason,
                    actor,
                    payload_json,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM oms_transitions WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
            conn.commit()
            return dict(row)

    def list_oms_transitions_sync(self, order_id: str) -> list[dict[str, Any]]:
        """List OMS transitions for one order in chronological order."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM oms_transitions
                WHERE order_id = ?
                ORDER BY id ASC
                """,
                (order_id,),
            ).fetchall()
            return [dict(row) for row in rows]
