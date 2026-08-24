"""SQLite schema owned by the human research task store."""

from __future__ import annotations

_TASK_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_research_tasks (
    task_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    capture_id TEXT NOT NULL,
    context_snapshot_id TEXT NOT NULL,
    context_fingerprint TEXT NOT NULL,
    account_alias TEXT NOT NULL,
    valuation_snapshot_id TEXT NOT NULL,
    ledger_cutoff_id INTEGER NOT NULL CHECK(ledger_cutoff_id >= 0),
    ledger_fingerprint TEXT NOT NULL,
    created_by TEXT NOT NULL,
    title TEXT NOT NULL,
    research_question TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    blockers_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_research_tasks_status
ON ai_research_tasks(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS ai_research_task_reviews (
    review_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    reviewed_by TEXT NOT NULL,
    decision TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES ai_research_tasks(task_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_research_task_reviews_task
ON ai_research_task_reviews(task_id, created_at, review_id);

CREATE TABLE IF NOT EXISTS ai_research_task_events (
    task_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(task_id, sequence),
    FOREIGN KEY(task_id) REFERENCES ai_research_tasks(task_id)
);
"""

TASK_SCHEMA = _TASK_SCHEMA
