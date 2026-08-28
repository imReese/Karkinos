"""SQLite adapter for secret-free provider connectivity audit records."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

PROVIDER_CONNECTIVITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_provider_connectivity_checks (
    check_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_fingerprint TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    adapter_kind TEXT NOT NULL,
    endpoint_origin TEXT NOT NULL,
    status TEXT NOT NULL,
    probe_version TEXT NOT NULL,
    request_payload_fingerprint TEXT,
    response_fingerprint TEXT,
    response_model TEXT,
    usage_json TEXT NOT NULL,
    http_status INTEGER,
    error_code TEXT,
    credential_source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    latency_ms INTEGER,
    financial_context_sent INTEGER NOT NULL CHECK(financial_context_sent = 0),
    tool_calls_allowed INTEGER NOT NULL CHECK(tool_calls_allowed = 0),
    authority_effect TEXT NOT NULL CHECK(authority_effect = 'none')
);
"""


class ProviderConnectivitySqliteRepository:
    """Own connections and SQL for provider connectivity audits."""

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
            conn.executescript(PROVIDER_CONNECTIVITY_SCHEMA)

    def create_or_get(
        self,
        *,
        check_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        requested_by: str,
        provider_id: str,
        model_id: str,
        model_name: str,
        adapter_kind: str,
        endpoint_origin: str,
        status: str,
        probe_version: str,
        credential_source: str,
        started_at: str,
    ) -> tuple[dict[str, Any] | None, bool]:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM ai_provider_connectivity_checks WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["status"] == "deferred"
                    and existing["request_fingerprint"] == request_fingerprint
                ):
                    conn.execute(
                        """
                        UPDATE ai_provider_connectivity_checks
                        SET status=?, started_at=?, finished_at=NULL, latency_ms=NULL,
                            error_code=NULL
                        WHERE check_id=? AND status='deferred'
                        """,
                        (status, started_at, existing["check_id"]),
                    )
                    reopened = conn.execute(
                        "SELECT * FROM ai_provider_connectivity_checks WHERE check_id=?",
                        (existing["check_id"],),
                    ).fetchone()
                    return (dict(reopened) if reopened is not None else None), True
                return dict(existing), False
            conn.execute(
                """
                INSERT INTO ai_provider_connectivity_checks (
                    check_id, idempotency_key, request_fingerprint, requested_by,
                    provider_id, model_id, model_name, adapter_kind,
                    endpoint_origin, status, probe_version,
                    request_payload_fingerprint, response_fingerprint,
                    response_model, usage_json, http_status, error_code,
                    credential_source, started_at, finished_at, latency_ms,
                    financial_context_sent, tool_calls_allowed, authority_effect
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL,
                          '{}', NULL, NULL, ?, ?, NULL, NULL, 0, 0, 'none')
                """,
                (
                    check_id,
                    idempotency_key,
                    request_fingerprint,
                    requested_by,
                    provider_id,
                    model_id,
                    model_name,
                    adapter_kind,
                    endpoint_origin,
                    status,
                    probe_version,
                    credential_source,
                    started_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_provider_connectivity_checks WHERE check_id = ?",
                (check_id,),
            ).fetchone()
        return (dict(row) if row is not None else None), True

    def finalize(
        self,
        *,
        check_id: str,
        expected_status: str,
        status: str,
        request_payload_fingerprint: str | None,
        response_fingerprint: str | None,
        response_model: str | None,
        usage_json: str,
        http_status: int | None,
        error_code: str | None,
        finished_at: str,
        latency_ms: int,
    ) -> dict[str, Any] | None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE ai_provider_connectivity_checks
                SET status = ?, request_payload_fingerprint = ?,
                    response_fingerprint = ?, response_model = ?, usage_json = ?,
                    http_status = ?, error_code = ?, finished_at = ?, latency_ms = ?
                WHERE check_id = ? AND status = ?
                """,
                (
                    status,
                    request_payload_fingerprint,
                    response_fingerprint,
                    response_model,
                    usage_json,
                    http_status,
                    error_code,
                    finished_at,
                    latency_ms,
                    check_id,
                    expected_status,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_provider_connectivity_checks WHERE check_id = ?",
                (check_id,),
            ).fetchone()
        return dict(row) if row is not None else None
