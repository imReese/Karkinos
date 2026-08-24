"""SQLite repository for paper runs, manual orders, shadow reviews, orders, and fills."""

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


class PaperTradingRepository(SQLiteRepository):
    """Own paper runs, manual orders, shadow reviews, orders, and fills."""

    def upsert_paper_shadow_run_sync(
        self,
        *,
        run_id: str,
        plan_date: str,
        input_fingerprint: str,
        status: str,
        order_intent_count: int,
        simulated_order_count: int,
        simulated_fill_count: int,
        divergence_status: str,
        next_manual_review_step: str,
        limitations: list[str] | None = None,
        payload: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        """Persist or update one idempotent daily paper/shadow run record."""
        now = self._now().isoformat()
        limitations_json = json.dumps(
            limitations or [],
            ensure_ascii=False,
            sort_keys=True,
        )
        payload_json = serialize_metadata_json(payload) or "{}"
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT *
                FROM paper_shadow_runs
                WHERE run_id = ?
                   OR (plan_date = ? AND input_fingerprint = ?)
                ORDER BY
                    CASE WHEN run_id = ? THEN 0 ELSE 1 END,
                    id ASC
                LIMIT 1
                """,
                (run_id, plan_date, input_fingerprint, run_id),
            ).fetchone()
            effective_run_id = str(existing["run_id"]) if existing else run_id
            created_at = str(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO paper_shadow_runs (
                    run_id, plan_date, input_fingerprint, status,
                    order_intent_count, simulated_order_count,
                    simulated_fill_count, divergence_status,
                    next_manual_review_step, limitations_json, payload_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    plan_date = excluded.plan_date,
                    input_fingerprint = excluded.input_fingerprint,
                    status = excluded.status,
                    order_intent_count = excluded.order_intent_count,
                    simulated_order_count = excluded.simulated_order_count,
                    simulated_fill_count = excluded.simulated_fill_count,
                    divergence_status = excluded.divergence_status,
                    next_manual_review_step = excluded.next_manual_review_step,
                    limitations_json = excluded.limitations_json,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    effective_run_id,
                    plan_date,
                    input_fingerprint,
                    status,
                    int(order_intent_count),
                    int(simulated_order_count),
                    int(simulated_fill_count),
                    divergence_status,
                    next_manual_review_step,
                    limitations_json,
                    payload_json,
                    created_at,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM paper_shadow_runs WHERE run_id = ?",
                (effective_run_id,),
            ).fetchone()
            conn.commit()
            return dict(row)

    def get_paper_shadow_run_sync(self, run_id: str) -> dict[str, Any] | None:
        """Read one persisted paper/shadow run by ID."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM paper_shadow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return dict(row) if row else None

    def latest_paper_shadow_run_sync(
        self,
        *,
        plan_date: str | None = None,
    ) -> dict[str, Any] | None:
        """Read the latest paper/shadow run, optionally scoped to a plan date."""
        conditions: list[str] = []
        params: list[Any] = []
        if plan_date is not None:
            conditions.append("plan_date = ?")
            params.append(plan_date)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"""
                SELECT *
                FROM paper_shadow_runs
                {where_clause}
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
            return dict(row) if row else None

    def record_paper_shadow_run_review_sync(
        self,
        *,
        run_id: str,
        reviewed_at: str,
        review_status: str,
        review_notes: str,
        reviewer: str | None = None,
    ) -> dict[str, Any] | None:
        """Attach an operator review outcome to a paper/shadow run."""
        next_step = paper_shadow_run_review_next_step(review_status)
        now = self._now().isoformat()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM paper_shadow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            validate_paper_shadow_run_review_transition(
                run_status=str(row["status"] or ""),
                review_status=review_status,
            )

            payload = json_dict(row["payload_json"])
            review_payload = {
                "review_status": review_status,
                "reviewed_at": reviewed_at,
                "review_notes": review_notes,
                "reviewer": reviewer,
                "does_not_submit_broker_order": True,
                "does_not_mutate_production_ledger": True,
            }
            payload["review"] = review_payload
            conn.execute(
                """
                UPDATE paper_shadow_runs
                SET review_status = ?,
                    reviewed_at = ?,
                    review_notes = ?,
                    reviewer = ?,
                    next_manual_review_step = ?,
                    payload_json = ?,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (
                    review_status,
                    reviewed_at,
                    review_notes,
                    reviewer,
                    next_step,
                    serialize_metadata_json(payload),
                    now,
                    run_id,
                ),
            )
            updated = conn.execute(
                "SELECT * FROM paper_shadow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if updated is not None:
                insert_event_sync(
                    conn,
                    event_type="paper_shadow_run.review_recorded",
                    timestamp=reviewed_at,
                    entity_type="paper_shadow_run",
                    entity_id=run_id,
                    source="paper_shadow_reviews",
                    source_ref=run_id,
                    payload={
                        "run_id": run_id,
                        "plan_date": updated["plan_date"],
                        "input_fingerprint": updated["input_fingerprint"],
                        "status": updated["status"],
                        "divergence_status": updated["divergence_status"],
                        "next_manual_review_step": next_step,
                        **review_payload,
                    },
                )
            conn.commit()
            return dict(updated) if updated is not None else None

    def record_order_sync(
        self,
        *,
        order_id: str,
        timestamp: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
        asset_class: str = "stock",
        intent_id: str | None = None,
        risk_decision_id: str | None = None,
        execution_mode: str = "paper",
        status: str = "submitted",
        source: str = "execution",
        source_ref: str | None = None,
        payload: dict[str, Any] | str | None = None,
    ) -> int:
        """Persist a shared order fact for manual, paper, and live execution."""
        now = self._now().isoformat()
        payload_json = serialize_metadata_json(payload) or "{}"
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO orders (
                    order_id, timestamp, symbol, side, order_type, quantity, price,
                    asset_class, intent_id, risk_decision_id, execution_mode, status,
                    source, source_ref, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    timestamp = excluded.timestamp,
                    symbol = excluded.symbol,
                    side = excluded.side,
                    order_type = excluded.order_type,
                    quantity = excluded.quantity,
                    price = excluded.price,
                    asset_class = excluded.asset_class,
                    intent_id = excluded.intent_id,
                    risk_decision_id = excluded.risk_decision_id,
                    execution_mode = excluded.execution_mode,
                    status = excluded.status,
                    source = excluded.source,
                    source_ref = excluded.source_ref,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    order_id,
                    timestamp,
                    symbol,
                    side,
                    order_type,
                    quantity,
                    price,
                    asset_class,
                    intent_id,
                    risk_decision_id,
                    execution_mode,
                    status,
                    source,
                    source_ref,
                    payload_json,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if row is not None:
                insert_event_sync(
                    conn,
                    event_type="order.recorded",
                    timestamp=row["timestamp"],
                    entity_type="order",
                    entity_id=row["order_id"],
                    source="orders",
                    source_ref=row["order_id"],
                    payload=order_event_payload(row),
                )
            conn.commit()
            return int(row["id"]) if row is not None else 0

    def get_order_sync(self, order_id: str) -> dict[str, Any] | None:
        """Read one shared order fact by ID."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            return dict(row) if row else None

    def record_shadow_divergence_review_sync(
        self,
        *,
        order_id: str,
        reviewed_at: str,
        divergence_status: str,
        review_notes: str,
        reviewer: str | None = None,
    ) -> dict[str, Any] | None:
        """Attach an operator divergence review to a paper/shadow order fact."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if row is None:
                return None
            if row["execution_mode"] != "paper_shadow":
                return dict(row)
            payload = json_dict(row["payload_json"])
            payload.update(
                {
                    "divergence_status": divergence_status,
                    "divergence_reviewed_at": reviewed_at,
                    "divergence_review_notes": review_notes,
                    "divergence_reviewer": reviewer,
                }
            )
            conn.execute(
                """
                UPDATE orders
                SET payload_json = ?, updated_at = ?
                WHERE order_id = ?
                """,
                (
                    serialize_metadata_json(payload),
                    self._now().isoformat(),
                    order_id,
                ),
            )
            updated = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if updated is not None:
                insert_event_sync(
                    conn,
                    event_type="order.shadow_divergence_reviewed",
                    timestamp=reviewed_at,
                    entity_type="order",
                    entity_id=updated["order_id"],
                    source="shadow_reviews",
                    source_ref=updated["order_id"],
                    payload=order_event_payload(updated),
                )
            conn.commit()
            return dict(updated) if updated is not None else None

    def list_orders_sync(
        self,
        *,
        status: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List shared order facts newest first."""
        conditions: list[str] = []
        params: list[Any] = []
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if symbol is not None:
            conditions.append("symbol = ?")
            params.append(symbol)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM orders
                {where_clause}
                ORDER BY timestamp DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_order_status_sync(
        self, *, order_id: str, status: str, note: str = ""
    ) -> dict[str, Any] | None:
        """Update shared order status and append an order status event."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                UPDATE orders
                SET status = ?, updated_at = ?
                WHERE order_id = ?
                """,
                (status, self._now().isoformat(), order_id),
            )
            row = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if row is not None:
                payload = order_event_payload(row)
                payload["note"] = note
                insert_event_sync(
                    conn,
                    event_type="order.status_changed",
                    timestamp=self._now().isoformat(),
                    entity_type="order",
                    entity_id=row["order_id"],
                    source="orders",
                    source_ref=row["order_id"],
                    payload=payload,
                )
            conn.commit()
            return dict(row) if row else None

    def save_manual_order_sync(
        self,
        *,
        order_id: str,
        timestamp: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None,
        intent_id: str | None,
        risk_decision_id: str | None,
        execution_mode: str,
        status: str,
        payload: dict[str, Any],
    ) -> int:
        """Persist an order waiting for manual confirmation."""
        now = self._now().isoformat()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                INSERT INTO manual_orders (
                    order_id, timestamp, symbol, side, order_type, quantity, price,
                    intent_id, risk_decision_id, execution_mode, status, payload_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    timestamp = excluded.timestamp,
                    symbol = excluded.symbol,
                    side = excluded.side,
                    order_type = excluded.order_type,
                    quantity = excluded.quantity,
                    price = excluded.price,
                    intent_id = excluded.intent_id,
                    risk_decision_id = excluded.risk_decision_id,
                    execution_mode = excluded.execution_mode,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    order_id,
                    timestamp,
                    symbol,
                    side,
                    order_type,
                    quantity,
                    price,
                    intent_id,
                    risk_decision_id,
                    execution_mode,
                    status,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM manual_orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if row is not None:
                insert_event_sync(
                    conn,
                    event_type="order.submitted",
                    timestamp=row["timestamp"],
                    entity_type="order",
                    entity_id=row["order_id"],
                    source="manual_orders",
                    source_ref=row["order_id"],
                    payload=manual_order_event_payload(row),
                )
            conn.commit()
            return cursor.lastrowid or 0

    def get_manual_order_sync(self, order_id: str) -> dict[str, Any] | None:
        """Read one manual order by ID."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM manual_orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_manual_orders_sync(
        self, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List manual orders, latest first."""
        query = "SELECT * FROM manual_orders"
        params: list[Any] = []
        if status is not None:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, tuple(params)).fetchall()
            return [dict(row) for row in rows]

    def update_manual_order_status_sync(
        self, *, order_id: str, status: str, note: str = ""
    ) -> dict[str, Any] | None:
        """Update manual order status and return the updated row."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                UPDATE manual_orders
                SET status = ?, note = ?, updated_at = ?
                WHERE order_id = ?
                """,
                (status, note, self._now().isoformat(), order_id),
            )
            row = conn.execute(
                "SELECT * FROM manual_orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if row is not None:
                insert_event_sync(
                    conn,
                    event_type="order.status_changed",
                    timestamp=self._now().isoformat(),
                    entity_type="order",
                    entity_id=row["order_id"],
                    source="manual_orders",
                    source_ref=row["order_id"],
                    payload=manual_order_event_payload(row),
                )
            conn.commit()
            return dict(row) if row else None

    def record_fill_sync(
        self,
        *,
        fill_id: str,
        order_id: str,
        timestamp: str,
        symbol: str,
        side: str,
        fill_price: float,
        fill_quantity: float,
        commission: float = 0.0,
        slippage: float = 0.0,
        asset_class: str = "stock",
        execution_mode: str = "paper",
        provider_name: str | None = None,
        broker_order_id: str | None = None,
        source: str = "execution",
        source_ref: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> int:
        """Persist a fill from paper/live execution and append an event."""
        now = self._now().isoformat()
        metadata_json = serialize_metadata_json(metadata)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO fills (
                    fill_id, order_id, timestamp, symbol, side, fill_price,
                    fill_quantity, commission, slippage, asset_class,
                    execution_mode, provider_name, broker_order_id, source,
                    source_ref, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fill_id) DO UPDATE SET
                    order_id = excluded.order_id,
                    timestamp = excluded.timestamp,
                    symbol = excluded.symbol,
                    side = excluded.side,
                    fill_price = excluded.fill_price,
                    fill_quantity = excluded.fill_quantity,
                    commission = excluded.commission,
                    slippage = excluded.slippage,
                    asset_class = excluded.asset_class,
                    execution_mode = excluded.execution_mode,
                    provider_name = excluded.provider_name,
                    broker_order_id = excluded.broker_order_id,
                    source = excluded.source,
                    source_ref = excluded.source_ref,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    fill_id,
                    order_id,
                    timestamp,
                    symbol,
                    side,
                    fill_price,
                    fill_quantity,
                    commission,
                    slippage,
                    asset_class,
                    execution_mode,
                    provider_name,
                    broker_order_id,
                    source,
                    source_ref,
                    metadata_json,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM fills WHERE fill_id = ?",
                (fill_id,),
            ).fetchone()
            if row is not None:
                insert_event_sync(
                    conn,
                    event_type="order.fill.recorded",
                    timestamp=row["timestamp"],
                    entity_type="fill",
                    entity_id=row["fill_id"],
                    source="fills",
                    source_ref=row["fill_id"],
                    payload=fill_event_payload(row),
                )
            conn.commit()
            return int(row["id"]) if row is not None else 0

    def get_fill_sync(self, fill_id: str) -> dict[str, Any] | None:
        """Read one persisted execution fill by ID."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM fills WHERE fill_id = ?",
                (fill_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_fills_sync(
        self,
        *,
        order_id: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List persisted execution fills newest first."""
        conditions: list[str] = []
        params: list[Any] = []
        if order_id is not None:
            conditions.append("order_id = ?")
            params.append(order_id)
        if symbol is not None:
            conditions.append("symbol = ?")
            params.append(symbol)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM fills
                {where_clause}
                ORDER BY timestamp DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(row) for row in rows]
