"""Schema owned by the AI audit repository."""

AI_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_provider_registrations (
    provider_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    payload_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_model_registrations (
    model_id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(provider_id) REFERENCES ai_provider_registrations(provider_id)
);

CREATE TABLE IF NOT EXISTS ai_agent_roles (
    role_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    payload_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_context_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    context_fingerprint TEXT NOT NULL UNIQUE,
    valuation_snapshot_id TEXT NOT NULL,
    ledger_cutoff_id INTEGER NOT NULL CHECK(ledger_cutoff_id >= 0),
    ledger_fingerprint TEXT NOT NULL,
    persisted_facts_only INTEGER NOT NULL CHECK(persisted_facts_only = 1),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_workflows (
    workflow_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    definition_id TEXT NOT NULL,
    definition_fingerprint TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    context_snapshot_id TEXT NOT NULL,
    context_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    current_stage_index INTEGER NOT NULL DEFAULT 0,
    partial_result INTEGER NOT NULL DEFAULT 0,
    failure_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(context_snapshot_id) REFERENCES ai_context_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_workflows_status
ON ai_workflows(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS ai_agent_runs (
    run_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    stage_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    status TEXT NOT NULL,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    response_json TEXT,
    response_fingerprint TEXT,
    error_code TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(workflow_id, stage_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id)
);

CREATE TABLE IF NOT EXISTS ai_tool_calls (
    call_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    stage_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    result_json TEXT,
    denial_reason TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(run_id, call_id),
    FOREIGN KEY(run_id) REFERENCES ai_agent_runs(run_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id)
);

CREATE TABLE IF NOT EXISTS ai_artifacts (
    artifact_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    stage_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    content_json TEXT NOT NULL,
    evidence_reference_ids_json TEXT NOT NULL,
    artifact_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES ai_agent_runs(run_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_artifacts_workflow
ON ai_artifacts(workflow_id, artifact_kind, created_at);

CREATE TABLE IF NOT EXISTS ai_workflow_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE(workflow_id, sequence_number),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id)
);
"""
