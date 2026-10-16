"""Quote-ingestion run persistence capability."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Protocol

from server.contracts.quote_ingestion import (
    PUBLISHED_QUOTE_RUN_STATUSES,
)
from server.persistence.connection import DateTimeNow, connect_sqlite
from server.persistence.database_serialization import (
    metadata_payload_value,
    serialize_metadata_json,
)
from server.persistence.event_log import insert_event_sync
from server.persistence.financial_facts_quote_ingestion_uow import (
    quote_completion_fingerprint,
    quote_run_completion_metadata,
)
from server.persistence.financial_facts_valuation import (
    record_quote_acquisition_failure_on_connection,
    record_valuation_publication_failure_on_connection,
)
from server.persistence.valuation_publication_recovery import (
    assert_quote_publication_not_started,
)

_STAGED_ACQUISITION_CONTRACT = "staged_until_atomic_quote_publication.v1"


class _QuoteRunPublisher(Protocol):
    def __call__(
        self,
        *,
        run_id: str,
        finished_at: str,
        status: str,
        success_count: int,
        failure_count: int,
        cache_hit_count: int,
        error_message: str | None,
        metadata: dict[str, Any] | str | None,
    ) -> dict[str, Any]: ...


class QuoteFetchRunRepositoryMixin:
    publish_quote_fetch_run_sync: _QuoteRunPublisher
    _path: Path

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
        parsed = metadata_payload_value(metadata)
        if parsed is None or isinstance(parsed, dict):
            metadata = {
                **(parsed or {}),
                "quote_ingestion_contract": _STAGED_ACQUISITION_CONTRACT,
            }
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
        with connect_sqlite(self._path) as conn:
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
        replay = _terminal_completion_replay(
            self._path,
            run_id=run_id,
            finished_at=finished_at,
            status=status,
            success_count=success_count,
            failure_count=failure_count,
            cache_hit_count=cache_hit_count,
            error_message=error_message,
            metadata=metadata,
        )
        if replay is not None:
            return replay

        if (
            success_count > 0
            and failure_count == 0
            and status in PUBLISHED_QUOTE_RUN_STATUSES
        ):
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
            except Exception:
                replay = _terminal_completion_replay(
                    self._path,
                    run_id=run_id,
                    finished_at=finished_at,
                    status=status,
                    success_count=success_count,
                    failure_count=failure_count,
                    cache_hit_count=cache_hit_count,
                    error_message=error_message,
                    metadata=metadata,
                )
                if replay is not None:
                    return replay
                # Unconfirmed publication stays fenced; do not manufacture a terminal
                # result after a lock/commit failure in a separate transaction.
                raise
        with connect_sqlite(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT * FROM quote_fetch_runs WHERE run_id = ? LIMIT 1",
                (run_id,),
            ).fetchone()
            if current is None:
                conn.rollback()
                return None
            if (
                str(current["status"]) != "running"
                or current["finished_at"] is not None
            ):
                replay = _terminal_completion_replay_for_row(
                    current,
                    finished_at=finished_at,
                    status=status,
                    success_count=success_count,
                    failure_count=failure_count,
                    cache_hit_count=cache_hit_count,
                    error_message=error_message,
                    metadata=metadata,
                )
                if replay is not None:
                    conn.rollback()
                    return replay
                raise ValueError("quote fetch run completion conflict")
            assert_quote_publication_not_started(conn, run_id)
            metadata = quote_run_completion_metadata(
                current,
                metadata=metadata,
                finished_at=finished_at,
                status=status,
                success_count=success_count,
                failure_count=failure_count,
                cache_hit_count=cache_hit_count,
                error_message=error_message,
            )
            metadata_json = serialize_metadata_json(metadata)
            metadata_payload = metadata_payload_value(metadata)
            if status in {
                "failed",
                "partial_success",
                "partial",
                "error",
            } and _unpublished_staged_acquisition(conn, current):
                record_quote_acquisition_failure_on_connection(
                    conn,
                    updated_at=finished_at,
                    quote_fetch_run_id=run_id,
                    quote_fetch_run_status=status,
                )
            else:
                _block_valuation_publication(
                    conn,
                    run_id=run_id,
                    run_status=status,
                    updated_at=finished_at,
                )
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
        with connect_sqlite(self._path) as conn:
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
        with connect_sqlite(self._path) as conn:
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


def _terminal_completion_replay(
    path: Any,
    *,
    run_id: str,
    finished_at: str,
    status: str,
    success_count: int,
    failure_count: int,
    cache_hit_count: int,
    error_message: str | None,
    metadata: dict[str, Any] | str | None,
) -> dict[str, Any] | None:
    with connect_sqlite(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM quote_fetch_runs WHERE run_id = ? LIMIT 1",
            (run_id,),
        ).fetchone()
    if row is None or (str(row["status"]) == "running" and row["finished_at"] is None):
        return None
    replay = _terminal_completion_replay_for_row(
        row,
        finished_at=finished_at,
        status=status,
        success_count=success_count,
        failure_count=failure_count,
        cache_hit_count=cache_hit_count,
        error_message=error_message,
        metadata=metadata,
    )
    if replay is None:
        raise ValueError("quote fetch run completion conflict")
    return replay


def _terminal_completion_replay_for_row(
    row: sqlite3.Row,
    *,
    finished_at: str,
    status: str,
    success_count: int,
    failure_count: int,
    cache_hit_count: int,
    error_message: str | None,
    metadata: dict[str, Any] | str | None,
) -> dict[str, Any] | None:
    recorded = metadata_payload_value(row["metadata_json"])
    if (
        row["status"] != "running"
        and isinstance(recorded, dict)
        and recorded.get("quote_publication_completion_fingerprint")
        == quote_completion_fingerprint(
            finished_at=finished_at,
            status=status,
            success_count=success_count,
            failure_count=failure_count,
            cache_hit_count=cache_hit_count,
            error_message=error_message,
            metadata=metadata,
        )
    ):
        return dict(row)
    expected = (
        finished_at,
        status,
        int(success_count),
        int(failure_count),
        int(cache_hit_count),
        error_message,
        _completion_metadata(metadata),
    )
    actual = (
        row["finished_at"],
        row["status"],
        int(row["success_count"] or 0),
        int(row["failure_count"] or 0),
        int(row["cache_hit_count"] or 0),
        row["error_message"],
        _completion_metadata(row["metadata_json"]),
    )
    return dict(row) if actual == expected else None


def _completion_metadata(value: dict[str, Any] | str | None) -> Any:
    payload = metadata_payload_value(value)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        return payload
    return {
        key: item
        for key, item in payload.items()
        if key not in {"valuation_snapshot_id", "valuation_snapshot_status"}
    }


def _unpublished_staged_acquisition(conn: sqlite3.Connection, run: sqlite3.Row) -> bool:
    """Prove this new-format acquisition never entered a financial write lane.

    Older runs have no such original contract. Do not infer their provenance
    from a newer complete valuation or from the absence of a current quote.
    """
    try:
        metadata = metadata_payload_value(run["metadata_json"])
        if (
            not isinstance(metadata, dict)
            or metadata.get("quote_ingestion_contract") != _STAGED_ACQUISITION_CONTRACT
        ):
            return False
        starts = conn.execute(
            "SELECT payload_json FROM event_log WHERE event_type='task_run.started' "
            "AND source='quote_fetch_runs' AND source_ref=?",
            (run["run_id"],),
        ).fetchall()
        if len(starts) != 1:
            return False
        start = json.loads(starts[0][0])
        if (
            not isinstance(start, dict)
            or any(
                start.get(k) != run[k]
                for k in (
                    "run_id",
                    "started_at",
                    "trigger",
                    "provider",
                    "asset_type",
                    "symbol_count",
                )
            )
            or not isinstance(start.get("metadata"), dict)
            or start["metadata"].get("quote_ingestion_contract")
            != _STAGED_ACQUISITION_CONTRACT
        ):
            return False
        for key in (
            "valuation_snapshot_publication",
            "valuation_snapshot_publication_attempt",
        ):
            row = conn.execute(
                "SELECT value_json FROM runtime_controls WHERE key=?", (key,)
            ).fetchone()
            value = json.loads(row[0]) if row else {}
            if value.get("quote_fetch_run_id") == run["run_id"]:
                return False
        for table in ("quote_snapshots", "latest_quotes"):
            if conn.execute(
                f"SELECT 1 FROM {table} WHERE fetch_run_id=? LIMIT 1", (run["run_id"],)
            ).fetchone():
                return False
        if conn.execute(
            "SELECT 1 FROM event_log WHERE event_type IN ('market.quote.snapshot.recorded','market.quote.refreshed') "
            "AND json_extract(payload_json,'$.fetch_run_id')=? LIMIT 1",
            (run["run_id"],),
        ).fetchone():
            return False
        if conn.execute(
            "SELECT 1 FROM valuation_snapshots WHERE "
            "EXISTS (SELECT 1 FROM json_each(quotes_json) q WHERE json_extract(q.value,'$.fetch_run_id')=?) "
            "OR EXISTS (SELECT 1 FROM json_each(metadata_json,'$.ingestion_run_ids') i WHERE i.value=?) LIMIT 1",
            (run["run_id"], run["run_id"]),
        ).fetchone():
            return False
        return True
    except (ValueError, TypeError, KeyError, AttributeError, sqlite3.Error):
        return False


def _block_valuation_publication(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    run_status: str,
    updated_at: str,
) -> None:
    record_valuation_publication_failure_on_connection(
        conn,
        updated_at=updated_at,
        reason="quote_fetch_run_not_fully_successful",
        quote_fetch_run_id=run_id,
        quote_fetch_run_status=run_status,
    )


__all__ = ["QuoteFetchRunRepositoryMixin"]
