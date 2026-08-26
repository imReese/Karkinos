"""SQLite schema ownership for external-analysis human reviews."""

from __future__ import annotations

from typing import Any

EXTERNAL_ANALYSIS_REVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_external_analysis_reviews (
    review_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL UNIQUE,
    workflow_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    analysis_target_fingerprint TEXT NOT NULL,
    report_artifact_id TEXT,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    quality_evidence_json TEXT NOT NULL,
    cost_evidence_json TEXT NOT NULL,
    reviewed_by TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN (
        'accept_as_reviewed_research', 'request_revision', 'reject'
    )),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(analysis_id)
        REFERENCES ai_external_memory_informed_analyses(analysis_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id),
    FOREIGN KEY(report_artifact_id) REFERENCES ai_artifacts(artifact_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_external_analysis_reviews_created
ON ai_external_analysis_reviews(created_at DESC, review_id DESC);

CREATE TABLE IF NOT EXISTS ai_external_analysis_review_events (
    review_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(review_id, sequence),
    FOREIGN KEY(review_id) REFERENCES ai_external_analysis_reviews(review_id)
);
"""


class ExternalAnalysisReviewSchemaMixin:
    _connection: Any

    def _init_schema(self) -> None:
        with self._connection() as conn:
            conn.executescript(EXTERNAL_ANALYSIS_REVIEW_SCHEMA)
