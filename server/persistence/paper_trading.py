"""SQLite repository for paper runs, manual orders, shadow reviews, orders, and fills."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from server.persistence.connection import SQLiteRepository
from server.persistence.database_normalization import (
    json_dict,
    paper_shadow_run_review_next_step,
    validate_paper_shadow_run_review_transition,
)
from server.persistence.database_serialization import serialize_metadata_json
from server.persistence.event_log import (
    insert_event_sync,
)
from server.persistence.execution_fact_uow import ExecutionFactUnitOfWorkMixin
from server.persistence.financial_fact_event_payloads import (
    order_event_payload,
)
from server.persistence.manual_order_ticket_uow import (
    ManualOrderTicketUnitOfWorkMixin,
)
from server.persistence.paper_shadow_run_uow import PaperShadowRunUnitOfWorkMixin

logger = logging.getLogger(__name__)


class PaperTradingRepository(
    PaperShadowRunUnitOfWorkMixin,
    ExecutionFactUnitOfWorkMixin,
    ManualOrderTicketUnitOfWorkMixin,
    SQLiteRepository,
):
    """Own paper runs, manual orders, shadow reviews, orders, and fills."""

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
