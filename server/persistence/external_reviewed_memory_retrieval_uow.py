"""Atomic write unit for external reviewed-memory retrieval."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from server.ai_runtime.contracts import JsonObject, canonical_json, content_fingerprint
from server.contracts.external_reviewed_memory_retrieval import (
    ExternalReviewedMemoryRetrievalTarget,
    HumanExternalReviewedMemoryRetrievalRequest,
    StoredExternalReviewedMemoryRetrieval,
)
from server.contracts.idempotency import IdempotencyConflict


class ExternalReviewedMemoryRetrievalUnitOfWorkMixin:
    _connection: Any
    _retrieval_from_row: Callable[[sqlite3.Row], StoredExternalReviewedMemoryRetrieval]
    _event_hash: Callable[..., str]

    def _record(
        self,
        *,
        request: HumanExternalReviewedMemoryRetrievalRequest,
        target: ExternalReviewedMemoryRetrievalTarget,
        created_at: str,
    ) -> tuple[StoredExternalReviewedMemoryRetrieval, bool]:
        identity = {
            "request_fingerprint": request.fingerprint,
            "retrieval_target_fingerprint": target.fingerprint,
        }
        retrieval_id = (
            f"ai-external-memory-retrieval-{content_fingerprint(identity)[:24]}"
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ai_external_reviewed_memory_retrievals "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if row is not None:
                stored = self._retrieval_from_row(row)
                if stored.request_fingerprint != request.fingerprint:
                    raise IdempotencyConflict(
                        "external reviewed-memory retrieval idempotency key was "
                        "reused with different input"
                    )
                return stored, True
            conn.execute(
                """
                INSERT INTO ai_external_reviewed_memory_retrievals (
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
                payload={
                    "request_fingerprint": request.fingerprint,
                    "retrieval_target_fingerprint": target.fingerprint,
                    "current_context_snapshot_id": (
                        request.current_context_snapshot_id
                    ),
                    "promotion_ids": list(request.promotion_ids),
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            row = conn.execute(
                "SELECT * FROM ai_external_reviewed_memory_retrievals "
                "WHERE retrieval_id = ?",
                (retrieval_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("external reviewed-memory retrieval persistence failed")
        return self._retrieval_from_row(row), False

    def _append_event(
        self,
        conn: sqlite3.Connection,
        *,
        retrieval_id: str,
        payload: JsonObject,
        created_at: str,
    ) -> None:
        sequence = 1
        previous_hash = None
        event_hash = self._event_hash(
            retrieval_id=retrieval_id,
            sequence=sequence,
            payload=payload,
            previous_hash=previous_hash,
            created_at=created_at,
        )
        conn.execute(
            """
            INSERT INTO ai_external_reviewed_memory_retrieval_events (
                retrieval_id, sequence, event_type, payload_json,
                previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                retrieval_id,
                sequence,
                "external_reviewed_memory_retrieval_started",
                canonical_json(payload),
                previous_hash,
                event_hash,
                created_at,
            ),
        )
