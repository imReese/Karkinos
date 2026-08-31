"""SQLite persistence for explicitly promoted external-memory analysis."""

from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager
from typing import Callable, Mapping

from server.ai_runtime.contracts import canonical_json, content_fingerprint
from server.ai_runtime.external_memory_informed_analysis import (
    EXTERNAL_MEMORY_ANALYSIS_PROMPT_VERSION,
    EXTERNAL_MEMORY_ANALYSIS_STAGE_IDS,
    ExternalMemoryAnalysisRecord,
    ExternalModelCallRecord,
    HumanExternalMemoryAnalysisRequest,
    model_call_from_row,
    record_from_row,
)
from server.ai_runtime.memory_informed_analysis import MemoryInformedInputs
from server.ai_runtime.store import IdempotencyConflict

EXTERNAL_PROMOTED_MEMORY_ANALYSIS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_external_promoted_memory_analyses (
    analysis_id TEXT PRIMARY KEY,
    retrieval_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    workflow_id TEXT NOT NULL UNIQUE,
    context_snapshot_id TEXT NOT NULL,
    context_fingerprint TEXT NOT NULL,
    retrieval_target_fingerprint TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    endpoint_origin TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    run_claimed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(retrieval_id)
        REFERENCES ai_external_reviewed_memory_retrievals(retrieval_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id),
    FOREIGN KEY(context_snapshot_id) REFERENCES ai_context_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_external_promoted_memory_analyses_created
ON ai_external_promoted_memory_analyses(created_at DESC, analysis_id DESC);

CREATE TABLE IF NOT EXISTS ai_external_promoted_memory_model_calls (
    workflow_id TEXT NOT NULL,
    stage_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    status TEXT NOT NULL,
    request_payload_fingerprint TEXT NOT NULL,
    response_fingerprint TEXT,
    response_model TEXT,
    http_status INTEGER,
    usage_json TEXT NOT NULL DEFAULT '{}',
    finish_reason TEXT,
    reasoning_content_present INTEGER NOT NULL DEFAULT 0,
    reasoning_content_char_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    PRIMARY KEY(workflow_id, stage_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id)
);
"""


class ExternalPromotedMemoryAnalysisPersistenceMixin:
    """Own the promoted-memory analysis schema and SQLite transitions."""

    _connection: Callable[[], AbstractContextManager[sqlite3.Connection]]

    def init(self) -> None:
        with self._connection() as conn:
            conn.executescript(EXTERNAL_PROMOTED_MEMORY_ANALYSIS_SCHEMA)

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> ExternalMemoryAnalysisRecord | None:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_external_promoted_memory_analyses "
                    "WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        return record_from_row(row) if row is not None else None

    def create_or_get(
        self,
        *,
        request: HumanExternalMemoryAnalysisRequest,
        workflow_id: str,
        inputs: MemoryInformedInputs,
        provider_id: str,
        model_id: str,
        endpoint_origin: str,
        created_at: str,
    ) -> tuple[ExternalMemoryAnalysisRecord, bool]:
        identity = {
            "request_fingerprint": request.fingerprint,
            "workflow_id": workflow_id,
            "retrieval_target_fingerprint": (
                inputs.retrieval.current_target.fingerprint
            ),
            "provider_id": provider_id,
            "model_id": model_id,
            "endpoint_origin": endpoint_origin,
            "prompt_version": EXTERNAL_MEMORY_ANALYSIS_PROMPT_VERSION,
            "memory_source": "promoted_external_reviewed_memory",
        }
        analysis_id = (
            f"ai-external-promoted-memory-{content_fingerprint(identity)[:24]}"
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ai_external_promoted_memory_analyses "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if row is not None:
                stored = record_from_row(row)
                if (
                    stored.request_fingerprint != request.fingerprint
                    or stored.stored_retrieval_id != request.retrieval_id
                    or stored.workflow_id != workflow_id
                    or stored.provider_id != provider_id
                    or stored.model_id != model_id
                    or stored.endpoint_origin != endpoint_origin
                ):
                    raise IdempotencyConflict(
                        "external promoted-memory analysis idempotency key was "
                        "reused with different input or provider configuration"
                    )
                return stored, True
            conn.execute(
                """
                INSERT INTO ai_external_promoted_memory_analyses (
                    analysis_id, retrieval_id, idempotency_key, request_json,
                    request_fingerprint, workflow_id, context_snapshot_id,
                    context_fingerprint, retrieval_target_fingerprint,
                    provider_id, model_id, endpoint_origin, prompt_version,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    request.retrieval_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    workflow_id,
                    inputs.context.snapshot_id,
                    inputs.context.fingerprint,
                    inputs.retrieval.current_target.fingerprint,
                    provider_id,
                    model_id,
                    endpoint_origin,
                    EXTERNAL_MEMORY_ANALYSIS_PROMPT_VERSION,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_external_promoted_memory_analyses "
                "WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("external promoted-memory analysis persistence failed")
        return record_from_row(row), False

    def claim_run(self, analysis_id: str, *, claimed_at: str) -> bool:
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE ai_external_promoted_memory_analyses "
                "SET run_claimed_at = ? "
                "WHERE analysis_id = ? AND run_claimed_at IS NULL",
                (claimed_at, analysis_id),
            )
        return cursor.rowcount == 1

    def get(self, analysis_id: str) -> ExternalMemoryAnalysisRecord:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_external_promoted_memory_analyses "
                    "WHERE analysis_id = ?",
                    (analysis_id,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        if row is None:
            raise LookupError(
                f"external promoted-memory analysis not found: {analysis_id}"
            )
        return record_from_row(row)

    def list(self, *, limit: int = 50) -> tuple[ExternalMemoryAnalysisRecord, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("analysis list limit must be between 1 and 200")
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM ai_external_promoted_memory_analyses "
                    "ORDER BY created_at DESC, analysis_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        return tuple(record_from_row(row) for row in rows)

    def start_model_call(
        self,
        *,
        workflow_id: str,
        stage_id: str,
        provider_id: str,
        model_id: str,
        request_payload_fingerprint: str,
        started_at: str,
    ) -> bool:
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO ai_external_promoted_memory_model_calls (
                    workflow_id, stage_id, provider_id, model_id,
                    prompt_version, status, request_payload_fingerprint,
                    started_at
                ) VALUES (?, ?, ?, ?, ?, 'running', ?, ?)
                """,
                (
                    workflow_id,
                    stage_id,
                    provider_id,
                    model_id,
                    EXTERNAL_MEMORY_ANALYSIS_PROMPT_VERSION,
                    request_payload_fingerprint,
                    started_at,
                ),
            )
        return cursor.rowcount == 1

    def finish_model_call(
        self,
        *,
        workflow_id: str,
        stage_id: str,
        status: str,
        response_fingerprint: str | None,
        response_model: str | None,
        http_status: int | None,
        usage: Mapping[str, int] | None,
        finish_reason: str | None,
        reasoning_content_present: bool,
        reasoning_content_char_count: int,
        error_code: str | None,
        finished_at: str,
    ) -> None:
        if status not in {"completed", "failed"}:
            raise ValueError("model call terminal status is invalid")
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE ai_external_promoted_memory_model_calls
                SET status = ?, response_fingerprint = ?, response_model = ?,
                    http_status = ?, usage_json = ?, finish_reason = ?,
                    reasoning_content_present = ?,
                    reasoning_content_char_count = ?, error_code = ?,
                    finished_at = ?
                WHERE workflow_id = ? AND stage_id = ? AND status = 'running'
                """,
                (
                    status,
                    response_fingerprint,
                    response_model,
                    http_status,
                    canonical_json(dict(usage or {})),
                    finish_reason,
                    int(reasoning_content_present),
                    reasoning_content_char_count,
                    error_code,
                    finished_at,
                    workflow_id,
                    stage_id,
                ),
            )
        if cursor.rowcount != 1:
            raise RuntimeError("external promoted-memory call audit transition failed")

    def list_model_calls(
        self,
        workflow_id: str,
    ) -> tuple[ExternalModelCallRecord, ...]:
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM ai_external_promoted_memory_model_calls "
                    "WHERE workflow_id = ?",
                    (workflow_id,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        records = [model_call_from_row(row) for row in rows]
        records.sort(
            key=lambda item: (
                (
                    EXTERNAL_MEMORY_ANALYSIS_STAGE_IDS.index(item.stage_id)
                    if item.stage_id in EXTERNAL_MEMORY_ANALYSIS_STAGE_IDS
                    else len(EXTERNAL_MEMORY_ANALYSIS_STAGE_IDS)
                ),
                item.started_at,
                item.stage_id,
            )
        )
        return tuple(records)
