"""Schema ownership for revocable external reviewed memory."""

from __future__ import annotations

from typing import Any

EXTERNAL_REVIEWED_MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_external_reviewed_memory_promotions (
    promotion_id TEXT PRIMARY KEY,
    review_id TEXT NOT NULL UNIQUE,
    analysis_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    promotion_target_fingerprint TEXT NOT NULL,
    memory_artifact_id TEXT NOT NULL UNIQUE,
    memory_content_json TEXT NOT NULL,
    memory_artifact_fingerprint TEXT NOT NULL,
    evidence_reference_ids_json TEXT NOT NULL,
    source_context_snapshot_id TEXT NOT NULL,
    source_context_fingerprint TEXT NOT NULL,
    source_retrieval_id TEXT,
    source_retrieval_target_fingerprint TEXT,
    report_artifact_id TEXT NOT NULL,
    report_artifact_fingerprint TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    promoted_by TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(review_id) REFERENCES ai_external_analysis_reviews(review_id),
    FOREIGN KEY(analysis_id)
        REFERENCES ai_external_memory_informed_analyses(analysis_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id),
    FOREIGN KEY(report_artifact_id) REFERENCES ai_artifacts(artifact_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_external_reviewed_memory_created
ON ai_external_reviewed_memory_promotions(created_at DESC, promotion_id DESC);

CREATE TABLE IF NOT EXISTS ai_external_reviewed_memory_revocations (
    revocation_id TEXT PRIMARY KEY,
    promotion_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    promotion_target_fingerprint TEXT NOT NULL,
    memory_artifact_fingerprint TEXT NOT NULL,
    revoked_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(promotion_id)
        REFERENCES ai_external_reviewed_memory_promotions(promotion_id)
);

CREATE TABLE IF NOT EXISTS ai_external_reviewed_memory_events (
    promotion_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL CHECK(event_type IN (
        'external_reviewed_memory_promoted',
        'external_reviewed_memory_revoked'
    )),
    payload_json TEXT NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(promotion_id, sequence),
    FOREIGN KEY(promotion_id)
        REFERENCES ai_external_reviewed_memory_promotions(promotion_id)
);
"""


class ExternalReviewedMemorySchemaMixin:
    _connection: Any

    def _init_schema(self) -> None:
        with self._connection() as conn:
            conn.executescript(EXTERNAL_REVIEWED_MEMORY_SCHEMA)
