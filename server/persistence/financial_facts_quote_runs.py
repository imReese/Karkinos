"""Quote-ingestion run persistence capability."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from server.persistence.database_serialization import (
    metadata_payload_value,
    serialize_metadata_json,
)
from server.persistence.event_log import insert_event_sync
from server.persistence.financial_facts_quote_ingestion_uow import (
    PUBLISHED_QUOTE_RUN_STATUSES,
)

logger = logging.getLogger("server.persistence.financial_facts")


class QuoteFetchRunRepositoryMixin:
    def create_quote_fetch_run(
        self,
        *,
        run_id: str,
        started_at: str,
        trigger: str,
        status: str,
        provider: str | None = None,
        asset_type: str | None = None,
        symbol_count: int = 0,
        success_count: int = 0,
        failure_count: int = 0,
        cache_hit_count: int = 0,
        error_message: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> int:
        """Create one quote fetch run audit row."""
        payload = {
            "run_id": run_id,
            "started_at": started_at,
            "trigger": trigger,
            "provider": provider,
            "asset_type": asset_type,
            "symbol_count": symbol_count,
            "success_count": success_count,
            "failure_count": failure_count,
            "cache_hit_count": cache_hit_count,
            "status": status,
            "error_message": error_message,
            "metadata": metadata_payload_value(metadata),
        }
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO quote_fetch_runs (
                    run_id, started_at, trigger, provider, asset_type, symbol_count,
                    success_count, failure_count, cache_hit_count, status,
                    error_message, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    started_at,
                    trigger,
                    provider,
                    asset_type,
                    symbol_count,
                    success_count,
                    failure_count,
                    cache_hit_count,
                    status,
                    error_message,
                    serialize_metadata_json(metadata),
                ),
            )
            insert_event_sync(
                conn,
                event_type="task_run.started",
                timestamp=started_at,
                entity_type="task_run",
                entity_id=run_id,
                source="quote_fetch_runs",
                source_ref=run_id,
                payload=payload,
            )
            conn.commit()
            return cursor.lastrowid or 0

    def finish_quote_fetch_run(
        self,
        *,
        run_id: str,
        finished_at: str,
        status: str,
        success_count: int = 0,
        failure_count: int = 0,
        cache_hit_count: int = 0,
        error_message: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> dict[str, Any] | None:
        """Mark a quote fetch run as finished and return the updated row."""
        if success_count > 0 and status in PUBLISHED_QUOTE_RUN_STATUSES:
            try:
                return self.publish_quote_fetch_run_sync(
                    run_id=run_id,
                    finished_at=finished_at,
                    status=status,
                    success_count=success_count,
                    failure_count=failure_count,
                    cache_hit_count=cache_hit_count,
                    error_message=error_message,
                    metadata=metadata,
                )
            except Exception as exc:
                logger.exception(
                    "Failed to publish valuation snapshot for quote run %s", run_id
                )
                self._runtime_controls.set_value(
                    "valuation_snapshot_publication",
                    {
                        "status": "failed",
                        "quote_fetch_run_id": run_id,
                        "error_type": type(exc).__name__,
                        "reason": "quote_batch_publication_failed",
                    },
                )
                status = "failed"
                error_message = (
                    f"valuation snapshot publication failed: {type(exc).__name__}"
                )
                metadata_value = metadata_payload_value(metadata)
                if isinstance(metadata_value, dict):
                    metadata = {
                        **metadata_value,
                        "valuation_snapshot_publication": "failed",
                    }
        metadata_json = serialize_metadata_json(metadata)
        metadata_payload = metadata_payload_value(metadata)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            if metadata_json is None:
                conn.execute(
                    """
                    UPDATE quote_fetch_runs
                    SET finished_at = ?,
                        status = ?,
                        success_count = ?,
                        failure_count = ?,
                        cache_hit_count = ?,
                        error_message = ?
                    WHERE run_id = ?
                    """,
                    (
                        finished_at,
                        status,
                        success_count,
                        failure_count,
                        cache_hit_count,
                        error_message,
                        run_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE quote_fetch_runs
                    SET finished_at = ?,
                        status = ?,
                        success_count = ?,
                        failure_count = ?,
                        cache_hit_count = ?,
                        error_message = ?,
                        metadata_json = ?
                    WHERE run_id = ?
                    """,
                    (
                        finished_at,
                        status,
                        success_count,
                        failure_count,
                        cache_hit_count,
                        error_message,
                        metadata_json,
                        run_id,
                    ),
                )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM quote_fetch_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is not None:
                insert_event_sync(
                    conn,
                    event_type="task_run.completed",
                    timestamp=finished_at,
                    entity_type="task_run",
                    entity_id=run_id,
                    source="quote_fetch_runs",
                    source_ref=run_id,
                    payload={
                        "run_id": row["run_id"],
                        "started_at": row["started_at"],
                        "finished_at": row["finished_at"],
                        "trigger": row["trigger"],
                        "provider": row["provider"],
                        "asset_type": row["asset_type"],
                        "symbol_count": row["symbol_count"],
                        "success_count": row["success_count"],
                        "failure_count": row["failure_count"],
                        "cache_hit_count": row["cache_hit_count"],
                        "status": row["status"],
                        "error_message": row["error_message"],
                        "metadata": metadata_payload,
                    },
                )
                conn.commit()
            return dict(row) if row else None

    def get_quote_fetch_run(self, run_id: str) -> dict[str, Any] | None:
        """Read one quote fetch run by run_id."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM quote_fetch_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_quote_fetch_runs(
        self,
        limit: int = 50,
        trigger: str | None = None,
        status: str | None = None,
        provider: str | None = None,
    ) -> list[dict[str, Any]]:
        """List quote fetch runs, newest first."""
        conditions: list[str] = []
        params: list[Any] = []
        if trigger is not None:
            conditions.append("trigger = ?")
            params.append(trigger)
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if provider is not None:
            conditions.append("provider = ?")
            params.append(provider)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM quote_fetch_runs
                {where_clause}
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]


__all__ = ["QuoteFetchRunRepositoryMixin"]
