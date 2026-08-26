"""Atomic write unit for explicit reviewed-memory retrieval."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from server.ai_runtime.contracts import JsonObject, canonical_json, content_fingerprint
from server.contracts.idempotency import IdempotencyConflict
from server.contracts.memory_retrieval import (
    HumanReviewedMemoryRetrievalRequest,
    ReviewedMemoryRetrievalTarget,
    StoredReviewedMemoryRetrieval,
)


class ReviewedMemoryRetrievalUnitOfWorkMixin:
    _connection: Any
    _retrieval_from_row: Callable[[sqlite3.Row], StoredReviewedMemoryRetrieval]
    _retrieval_event_hash: Callable[..., str]

    def _record(
        self,
        *,
        request: HumanReviewedMemoryRetrievalRequest,
        target: ReviewedMemoryRetrievalTarget,
        created_at: str,
    ) -> tuple[StoredReviewedMemoryRetrieval, bool]:
        identity = {
            "request_fingerprint": request.fingerprint,
            "retrieval_target_fingerprint": target.fingerprint,
        }
        retrieval_id = f"ai-memory-retrieval-{content_fingerprint(identity)[:24]}"
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ai_reviewed_memory_retrievals "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if row is not None:
                stored = self._retrieval_from_row(row)
                if stored.request_fingerprint != request.fingerprint:
                    raise IdempotencyConflict(
                        "reviewed-memory retrieval idempotency key was reused "
                        "with different input"
                    )
                return stored, True
            conn.execute(
                """
                INSERT INTO ai_reviewed_memory_retrievals (
                    retrieval_id, idempotency_key, request_json,
                    request_fingerprint, current_context_snapshot_id,
                    retrieval_target_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    retrieval_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    request.current_context_snapshot_id,
                    target.fingerprint,
                    created_at,
                ),
            )
            self._append_event(
                conn,
                retrieval_id=retrieval_id,
                event_type="reviewed_memory_retrieval_started",
                payload={
                    "request_fingerprint": request.fingerprint,
                    "retrieval_target_fingerprint": target.fingerprint,
                    "current_context_snapshot_id": (
                        request.current_context_snapshot_id
                    ),
                    "review_ids": list(request.review_ids),
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            row = conn.execute(
                "SELECT * FROM ai_reviewed_memory_retrievals WHERE retrieval_id = ?",
                (retrieval_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("reviewed-memory retrieval persistence failed")
        return self._retrieval_from_row(row), False

    def _append_event(
        self,
        conn: sqlite3.Connection,
        *,
        retrieval_id: str,
        event_type: str,
        payload: JsonObject,
        created_at: str,
    ) -> None:
        previous = conn.execute(
            "SELECT sequence, event_hash "
            "FROM ai_reviewed_memory_retrieval_events "
            "WHERE retrieval_id = ? ORDER BY sequence DESC LIMIT 1",
            (retrieval_id,),
        ).fetchone()
        sequence = int(previous["sequence"]) + 1 if previous is not None else 1
        previous_hash = str(previous["event_hash"]) if previous is not None else None
        event_hash = self._retrieval_event_hash(
            retrieval_id=retrieval_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            previous_hash=previous_hash,
            created_at=created_at,
        )
        conn.execute(
            """
            INSERT INTO ai_reviewed_memory_retrieval_events (
                retrieval_id, sequence, event_type, payload_json,
                previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                retrieval_id,
                sequence,
                event_type,
                canonical_json(payload),
                previous_hash,
                event_hash,
                created_at,
            ),
        )
