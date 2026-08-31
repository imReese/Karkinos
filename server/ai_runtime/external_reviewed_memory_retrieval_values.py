"""Deterministic values for external reviewed-memory retrieval."""

from __future__ import annotations

from .contracts import JsonObject, content_fingerprint


def external_reviewed_memory_retrieval_event_hash(
    *,
    retrieval_id: str,
    sequence: int,
    payload: JsonObject,
    previous_hash: str | None,
    created_at: str,
) -> str:
    return content_fingerprint(
        {
            "retrieval_id": retrieval_id,
            "sequence": sequence,
            "event_type": "external_reviewed_memory_retrieval_started",
            "payload": payload,
            "previous_hash": previous_hash,
            "created_at": created_at,
        }
    )
