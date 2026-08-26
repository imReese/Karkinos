"""Atomic write unit for offline memory-informed fixture analysis."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime
from typing import Any

from server.ai_runtime.contracts import (
    EvidenceBoundContextSnapshot,
    canonical_json,
    content_fingerprint,
)
from server.contracts.idempotency import IdempotencyConflict
from server.contracts.memory_informed_analysis import (
    HumanMemoryInformedAnalysisRequest,
    MemoryInformedAnalysisRecord,
)


class MemoryInformedAnalysisUnitOfWorkMixin:
    """Own idempotent creation and lease acquisition transactions."""

    _connection: Any
    _record_from_row: Callable[[sqlite3.Row], MemoryInformedAnalysisRecord]

    def _create_or_get(
        self,
        *,
        request: HumanMemoryInformedAnalysisRequest,
        workflow_id: str,
        context: EvidenceBoundContextSnapshot,
        retrieval_target_fingerprint: str,
        created_at: str,
    ) -> tuple[MemoryInformedAnalysisRecord, bool]:
        identity = {
            "request_fingerprint": request.fingerprint,
            "workflow_id": workflow_id,
            "context_fingerprint": context.fingerprint,
            "retrieval_target_fingerprint": retrieval_target_fingerprint,
        }
        analysis_id = f"ai-memory-analysis-{content_fingerprint(identity)[:24]}"
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ai_memory_informed_fixture_analyses "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if row is not None:
                stored = self._record_from_row(row)
                if (
                    stored.request_fingerprint != request.fingerprint
                    or stored.request.retrieval_id != request.retrieval_id
                ):
                    raise IdempotencyConflict(
                        "memory-informed analysis idempotency key was reused "
                        "with different input"
                    )
                return stored, True
            conn.execute(
                """
                INSERT INTO ai_memory_informed_fixture_analyses (
                    analysis_id, retrieval_id, idempotency_key, request_json,
                    request_fingerprint, workflow_id, context_snapshot_id,
                    context_fingerprint, retrieval_target_fingerprint,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    request.retrieval_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    workflow_id,
                    context.snapshot_id,
                    context.fingerprint,
                    retrieval_target_fingerprint,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_memory_informed_fixture_analyses "
                "WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("memory-informed analysis persistence failed")
        return self._record_from_row(row), False

    def _claim_run(
        self,
        analysis_id: str,
        *,
        claimed_at: str,
        expires_at: str,
    ) -> bool:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT run_claim_expires_at "
                "FROM ai_memory_informed_fixture_analyses "
                "WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
            if row is None:
                raise LookupError(f"memory-informed analysis not found: {analysis_id}")
            existing_expiry = row["run_claim_expires_at"]
            if existing_expiry is not None:
                parsed_expiry = datetime.fromisoformat(str(existing_expiry))
                parsed_claimed_at = datetime.fromisoformat(claimed_at)
                if parsed_expiry.tzinfo is None or parsed_claimed_at.tzinfo is None:
                    raise ValueError("run claim timestamps must include timezone")
                if parsed_expiry > parsed_claimed_at:
                    return False
            updated = conn.execute(
                "UPDATE ai_memory_informed_fixture_analyses "
                "SET run_claimed_at = ?, run_claim_expires_at = ? "
                "WHERE analysis_id = ?",
                (claimed_at, expires_at, analysis_id),
            )
        return updated.rowcount == 1
