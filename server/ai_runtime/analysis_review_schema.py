"""SQLite schema owned by the fixture-analysis review store."""

from __future__ import annotations

_ANALYSIS_REVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_research_task_analysis_reviews (
    review_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    analysis_target_fingerprint TEXT NOT NULL,
    memory_artifact_id TEXT,
    reviewed_by TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN (
        'accept_as_reviewed_memory', 'request_revision', 'reject'
    )),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(analysis_id) REFERENCES ai_research_task_analyses(analysis_id),
    FOREIGN KEY(task_id) REFERENCES ai_research_tasks(task_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id),
    FOREIGN KEY(memory_artifact_id) REFERENCES ai_artifacts(artifact_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_analysis_reviews_created
ON ai_research_task_analysis_reviews(created_at DESC, review_id DESC);

CREATE TABLE IF NOT EXISTS ai_research_task_analysis_review_events (
    review_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(review_id, sequence),
    FOREIGN KEY(review_id)
        REFERENCES ai_research_task_analysis_reviews(review_id)
);
"""

ANALYSIS_REVIEW_SCHEMA = _ANALYSIS_REVIEW_SCHEMA
