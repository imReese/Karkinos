"""Schema ownership for external reviewed-memory retrieval."""

from __future__ import annotations

from typing import Any

EXTERNAL_REVIEWED_MEMORY_RETRIEVAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_external_reviewed_memory_retrievals (
    retrieval_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    current_context_snapshot_id TEXT NOT NULL,
    retrieval_target_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(current_context_snapshot_id)
        REFERENCES ai_context_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_external_reviewed_memory_retrievals_created
ON ai_external_reviewed_memory_retrievals(created_at DESC, retrieval_id DESC);

CREATE TABLE IF NOT EXISTS ai_external_reviewed_memory_retrieval_events (
    retrieval_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL CHECK(
        event_type = 'external_reviewed_memory_retrieval_started'
    ),
    payload_json TEXT NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(retrieval_id, sequence),
    FOREIGN KEY(retrieval_id)
        REFERENCES ai_external_reviewed_memory_retrievals(retrieval_id)
);
"""


class ExternalReviewedMemoryRetrievalSchemaMixin:
    _connection: Any

    def _init_schema(self) -> None:
        with self._connection() as conn:
            conn.executescript(EXTERNAL_REVIEWED_MEMORY_RETRIEVAL_SCHEMA)
