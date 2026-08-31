"""Schema ownership for offline memory-informed fixture analysis."""

from __future__ import annotations

from typing import Any

MEMORY_INFORMED_ANALYSIS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_memory_informed_fixture_analyses (
    analysis_id TEXT PRIMARY KEY,
    retrieval_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    workflow_id TEXT NOT NULL UNIQUE,
    context_snapshot_id TEXT NOT NULL,
    context_fingerprint TEXT NOT NULL,
    retrieval_target_fingerprint TEXT NOT NULL,
    run_claimed_at TEXT,
    run_claim_expires_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(retrieval_id)
        REFERENCES ai_reviewed_memory_retrievals(retrieval_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id),
    FOREIGN KEY(context_snapshot_id) REFERENCES ai_context_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_memory_informed_fixture_created
ON ai_memory_informed_fixture_analyses(created_at DESC, analysis_id DESC);
"""


class MemoryInformedAnalysisSchemaMixin:
    """Initialize only the schema owned by this persistence boundary."""

    _connection: Any

    def _init_schema(self) -> None:
        with self._connection() as conn:
            conn.executescript(MEMORY_INFORMED_ANALYSIS_SCHEMA)
