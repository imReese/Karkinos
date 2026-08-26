"""SQLite schema ownership for external backtest research requests."""

from __future__ import annotations

EXTERNAL_BACKTEST_REPORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_external_backtest_report_requests (
    analysis_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    backtest_result_id INTEGER NOT NULL CHECK(backtest_result_id > 0),
    capture_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL UNIQUE,
    context_snapshot_id TEXT NOT NULL,
    context_fingerprint TEXT NOT NULL,
    evidence_reference_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    run_claimed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_external_backtest_reports_result
ON ai_external_backtest_report_requests(backtest_result_id, created_at DESC);
"""


__all__ = ["EXTERNAL_BACKTEST_REPORT_SCHEMA"]
