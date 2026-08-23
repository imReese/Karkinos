"""SQLite repository for persisted automation alerts."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class AutomationAlertRepository:
    """Own automation-alert persistence without alert-generation behavior."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        utc_now: Callable[[], str] | None = None,
        local_now: Callable[[], str] | None = None,
    ) -> None:
        self._database_path = Path(database_path)
        self._utc_now = utc_now or (lambda: datetime.now(timezone.utc).isoformat())
        self._local_now = local_now or (lambda: datetime.now().isoformat())

    def upsert_alert(
        self,
        *,
        alert_key: str,
        severity: str,
        category: str,
        title: str,
        detail: str,
        source: str,
        source_ref: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = self._utc_now()
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT created_at, status, acknowledged_at, acknowledged_by
                FROM automation_alerts
                WHERE alert_key = ?
                LIMIT 1
                """,
                (alert_key,),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            status = str(existing["status"]) if existing else "open"
            acknowledged_at = existing["acknowledged_at"] if existing else None
            acknowledged_by = existing["acknowledged_by"] if existing else None
            conn.execute(
                """
                INSERT INTO automation_alerts (
                    alert_key, severity, category, title, detail, status,
                    source, source_ref, payload_json, acknowledged_at,
                    acknowledged_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alert_key) DO UPDATE SET
                    severity = excluded.severity,
                    category = excluded.category,
                    title = excluded.title,
                    detail = excluded.detail,
                    source = excluded.source,
                    source_ref = excluded.source_ref,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    alert_key,
                    severity,
                    category,
                    title,
                    detail,
                    status,
                    source,
                    source_ref,
                    payload_json,
                    acknowledged_at,
                    acknowledged_by,
                    created_at,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM automation_alerts WHERE alert_key = ?",
                (alert_key,),
            ).fetchone()
            conn.commit()
            return dict(row)

    def list_alerts(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([int(limit), int(offset)])
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM automation_alerts
                {where_clause}
                ORDER BY
                    CASE severity
                        WHEN 'critical' THEN 0
                        WHEN 'warning' THEN 1
                        ELSE 2
                    END,
                    updated_at DESC,
                    id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(row) for row in rows]

    def acknowledge_alert(
        self,
        *,
        alert_id: int,
        actor: str | None = None,
    ) -> dict[str, Any]:
        now = self._local_now()
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                UPDATE automation_alerts
                SET status = 'acknowledged',
                    acknowledged_at = ?,
                    acknowledged_by = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, actor, now, int(alert_id)),
            )
            row = conn.execute(
                "SELECT * FROM automation_alerts WHERE id = ?",
                (int(alert_id),),
            ).fetchone()
            conn.commit()
            if row is None:
                raise KeyError(f"automation alert not found: {alert_id}")
            return dict(row)
