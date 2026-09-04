"""SQLite adapter for explicit AI context capture lifecycle records."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import server.ai_runtime.persistence.ai_audit as ai_audit_persistence

CONTEXT_CAPTURE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_context_capture_runs (
    capture_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    context_snapshot_id TEXT,
    evidence_reference_ids_json TEXT NOT NULL DEFAULT '[]',
    failure_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_context_capture_runs_status
ON ai_context_capture_runs(status, updated_at DESC);
"""


class ContextCaptureSqliteRepository:
    """Own connections and SQL for ``ai_context_capture_runs``."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=2000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self) -> None:
        with self.connection() as conn:
            conn.executescript(CONTEXT_CAPTURE_SCHEMA)

    def create_or_get(
        self,
        *,
        capture_id: str,
        idempotency_key: str,
        request_json: str,
        request_fingerprint: str,
        status: str,
        created_at: str,
    ) -> tuple[dict[str, Any] | None, bool]:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO ai_context_capture_runs (
                    capture_id, idempotency_key, request_json,
                    request_fingerprint, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    idempotency_key,
                    request_json,
                    request_fingerprint,
                    status,
                    created_at,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_context_capture_runs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return (dict(row) if row is not None else None), cursor.rowcount == 0

    def get(self, capture_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_context_capture_runs WHERE capture_id = ?",
                (capture_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def update(
        self,
        *,
        capture_id: str,
        status: str,
        context_snapshot_id: str | None,
        evidence_reference_ids_json: str,
        failure_code: str | None,
        updated_at: str,
        preserve_status: str | None,
    ) -> tuple[dict[str, Any] | None, bool]:
        with self.connection() as conn:
            completed_guard = " AND status != ?" if preserve_status else ""
            params: list[Any] = [
                status,
                context_snapshot_id,
                evidence_reference_ids_json,
                failure_code,
                updated_at,
                capture_id,
            ]
            if preserve_status:
                params.append(preserve_status)
            cursor = conn.execute(
                f"""
                UPDATE ai_context_capture_runs
                SET status = ?, context_snapshot_id = ?,
                    evidence_reference_ids_json = ?, failure_code = ?,
                    updated_at = ?
                WHERE capture_id = ?{completed_guard}
                """,
                params,
            )
            row = conn.execute(
                "SELECT * FROM ai_context_capture_runs WHERE capture_id = ?",
                (capture_id,),
            ).fetchone()
        return (dict(row) if row is not None else None), cursor.rowcount == 1

    def capture_guarded(
        self,
        *,
        capture_id: str,
        idempotency_key: str,
        request_json: str,
        request_fingerprint: str,
        running_status: str,
        completed_status: str,
        created_at: Callable[[], str],
        updated_at: Callable[[], str],
        write_guard: Callable[[], Any],
        build_records: Callable[[str], Sequence[Any]],
        record_values: Callable[[Any], Mapping[str, Any]],
        build_context: Callable[[Sequence[Any], str], Any],
        context_values: Callable[[Any, Sequence[Any]], Mapping[str, Any]],
        identity_conflict: Callable[[str], Exception],
        evidence_conflict: Callable[[str], Exception],
    ) -> tuple[dict[str, Any], tuple[Any, ...], Any | None, bool, bool]:
        """Atomically persist one already-validated guarded capture."""

        write_guard()
        conn = sqlite3.connect(self._path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=2000")
        try:
            ai_audit_persistence.begin_immediate(conn)
            write_guard()
            row = conn.execute(
                "SELECT * FROM ai_context_capture_runs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            reused = row is not None
            if row is not None:
                if str(row["request_fingerprint"]) != request_fingerprint:
                    raise identity_conflict(
                        "capture idempotency key was reused with different input"
                    )
                if str(row["status"]) == completed_status:
                    write_guard()
                    conn.commit()
                    return dict(row), (), None, True, True
                capture_created_at = str(row["created_at"])
            else:
                capture_created_at = created_at()
                conn.execute(
                    """
                    INSERT INTO ai_context_capture_runs (
                        capture_id, idempotency_key, request_json,
                        request_fingerprint, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        capture_id,
                        idempotency_key,
                        request_json,
                        request_fingerprint,
                        running_status,
                        capture_created_at,
                        capture_created_at,
                    ),
                )

            records = tuple(build_records(capture_created_at))
            for record in records:
                values = record_values(record)
                existing = conn.execute(
                    "SELECT record_fingerprint FROM ai_canonical_evidence "
                    "WHERE reference_id = ?",
                    (values["reference_id"],),
                ).fetchone()
                if existing is not None:
                    if (
                        str(existing["record_fingerprint"])
                        != values["record_fingerprint"]
                    ):
                        raise evidence_conflict(
                            f"conflicting canonical evidence: {values['reference_id']}"
                        )
                    continue
                conn.execute(
                    """
                    INSERT INTO ai_canonical_evidence (
                        reference_id, tool_name, kind, valuation_snapshot_id,
                        ledger_cutoff_id, ledger_fingerprint, status, as_of,
                        source_schema_version, payload_json, payload_fingerprint,
                        record_fingerprint, captured_at, persisted_facts_only
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        values["reference_id"],
                        values["tool_name"],
                        values["kind"],
                        values["valuation_snapshot_id"],
                        values["ledger_cutoff_id"],
                        values["ledger_fingerprint"],
                        values["status"],
                        values["as_of"],
                        values["source_schema_version"],
                        values["payload_json"],
                        values["payload_fingerprint"],
                        values["record_fingerprint"],
                        values["captured_at"],
                    ),
                )
            context = build_context(records, capture_created_at)
            context_row = context_values(context, records)
            conn.execute(
                """
                INSERT INTO ai_context_snapshots (
                    snapshot_id, context_fingerprint, valuation_snapshot_id,
                    ledger_cutoff_id, ledger_fingerprint,
                    persisted_facts_only, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(snapshot_id) DO NOTHING
                """,
                (
                    context_row["snapshot_id"],
                    context_row["context_fingerprint"],
                    context_row["valuation_snapshot_id"],
                    context_row["ledger_cutoff_id"],
                    context_row["ledger_fingerprint"],
                    context_row["payload_json"],
                    context_row["created_at"],
                ),
            )
            existing_context = conn.execute(
                "SELECT context_fingerprint FROM ai_context_snapshots "
                "WHERE snapshot_id = ?",
                (context_row["snapshot_id"],),
            ).fetchone()
            if existing_context is None or str(
                existing_context["context_fingerprint"]
            ) != str(context_row["context_fingerprint"]):
                raise identity_conflict(
                    f"conflicting context snapshot: {context_row['snapshot_id']}"
                )
            conn.execute(
                """
                UPDATE ai_context_capture_runs
                SET status = ?, context_snapshot_id = ?,
                    evidence_reference_ids_json = ?, failure_code = NULL,
                    updated_at = ?
                WHERE capture_id = ? AND status != ?
                """,
                (
                    completed_status,
                    context_row["snapshot_id"],
                    context_row["evidence_reference_ids_json"],
                    updated_at(),
                    capture_id,
                    completed_status,
                ),
            )
            completed_row = conn.execute(
                "SELECT * FROM ai_context_capture_runs WHERE capture_id = ?",
                (capture_id,),
            ).fetchone()
            if completed_row is None:
                raise RuntimeError("guarded capture completion returned no row")
            write_guard()
            conn.commit()
            return dict(completed_row), records, context, reused, False
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
