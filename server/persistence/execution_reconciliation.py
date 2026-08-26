"""SQLite repository for broker gateway evidence and execution reconciliation."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import timezone
from typing import Any

from server.persistence.connection import SQLiteRepository

logger = logging.getLogger(__name__)


class ExecutionReconciliationRepository(SQLiteRepository):
    """Own broker gateway evidence and execution reconciliation."""

    def record_broker_gateway_event_sync(
        self,
        *,
        gateway_id: str,
        event_type: str,
        order_id: str | None = None,
        status: str = "recorded",
        actor: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one broker gateway audit event."""
        now = self._now(timezone.utc).isoformat()
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """
                INSERT INTO broker_gateway_events (
                    gateway_id, event_type, order_id, status, actor,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gateway_id,
                    event_type,
                    order_id,
                    status,
                    actor,
                    payload_json,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM broker_gateway_events WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
            conn.commit()
            return dict(row)

    def list_broker_gateway_events_sync(
        self,
        *,
        order_id: str | None = None,
        gateway_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List broker gateway audit events."""
        conditions: list[str] = []
        params: list[Any] = []
        if order_id is not None:
            conditions.append("order_id = ?")
            params.append(order_id)
        if gateway_id is not None:
            conditions.append("gateway_id = ?")
            params.append(gateway_id)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([int(limit), int(offset)])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM broker_gateway_events
                {where_clause}
                ORDER BY id ASC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_oms_orders_sync(
        self,
        *,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List OMS orders for execution reconciliation."""
        conditions: list[str] = []
        params: list[Any] = []
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([int(limit), int(offset)])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM oms_orders
                {where_clause}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(row) for row in rows]

    def upsert_execution_reconciliation_run_sync(
        self,
        *,
        run_id: str,
        run_date: str,
        status: str,
        item_count: int,
        open_item_count: int,
        payload: dict[str, Any] | None = None,
        items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Persist one execution reconciliation run and replace its items."""
        now = self._now().isoformat()
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT created_at
                FROM execution_reconciliation_runs
                WHERE run_id = ?
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO execution_reconciliation_runs (
                    run_id, run_date, status, item_count, open_item_count,
                    payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    run_date = excluded.run_date,
                    status = excluded.status,
                    item_count = excluded.item_count,
                    open_item_count = excluded.open_item_count,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    run_id,
                    run_date,
                    status,
                    int(item_count),
                    int(open_item_count),
                    payload_json,
                    created_at,
                    now,
                ),
            )
            conn.execute(
                "DELETE FROM execution_reconciliation_items WHERE run_id = ?",
                (run_id,),
            )
            for item in items or []:
                conn.execute(
                    """
                    INSERT INTO execution_reconciliation_items (
                        run_id, order_id, item_status, suggested_action,
                        gateway_event_count, broker_event_count, detail,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        item["order_id"],
                        item["item_status"],
                        item["suggested_action"],
                        int(item.get("gateway_event_count") or 0),
                        int(item.get("broker_event_count") or 0),
                        item.get("detail") or "",
                        json.dumps(
                            item.get("payload") or {},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        now,
                    ),
                )
            row = conn.execute(
                "SELECT * FROM execution_reconciliation_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            conn.commit()
            return dict(row)

    def list_execution_reconciliation_runs_sync(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List recent execution reconciliation runs."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM execution_reconciliation_runs
                ORDER BY run_date DESC, updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (int(limit), int(offset)),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_execution_reconciliation_run_sync(
        self,
        run_id: str,
    ) -> dict[str, Any] | None:
        """Read one execution reconciliation run."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM execution_reconciliation_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_execution_reconciliation_items_sync(
        self,
        run_id: str,
    ) -> list[dict[str, Any]]:
        """List item rows for one execution reconciliation run."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM execution_reconciliation_items
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_execution_reconciliation_open_items_sync(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List execution reconciliation items that still require action."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT current.*
                FROM execution_reconciliation_items AS current
                INNER JOIN (
                    SELECT order_id, MAX(id) AS latest_id
                    FROM execution_reconciliation_items
                    GROUP BY order_id
                ) AS latest
                    ON latest.latest_id = current.id
                WHERE current.suggested_action != 'no_action'
                ORDER BY
                    CASE
                        WHEN current.item_status LIKE 'controlled_submission_unknown%'
                            THEN 0
                        WHEN current.item_status LIKE 'controlled_%'
                            THEN 1
                        ELSE 2
                    END ASC,
                    current.id DESC
                LIMIT ? OFFSET ?
                """,
                (int(limit), int(offset)),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_latest_execution_reconciliation_item_for_order_sync(
        self,
        order_id: str,
    ) -> dict[str, Any] | None:
        """Return the latest persisted reconciliation fact for one OMS order."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM execution_reconciliation_items
                WHERE order_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (order_id,),
            ).fetchone()
            return dict(row) if row is not None else None
