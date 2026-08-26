"""Schema ownership for AI strategy research audit evidence."""

from __future__ import annotations


class StrategyResearchSchemaMixin:
    def init(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS ai_strategy_research_sessions (
                    session_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    selection_fingerprint TEXT NOT NULL,
                    context_snapshot_id TEXT,
                    context_fingerprint TEXT,
                    evidence_reference_id TEXT,
                    workflow_id TEXT,
                    status TEXT NOT NULL,
                    failure_code TEXT,
                    provider_id TEXT,
                    model_id TEXT,
                    prompt_version TEXT NOT NULL,
                    run_claimed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_strategy_hypothesis_drafts (
                    draft_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    contract_json TEXT NOT NULL,
                    artifact_fingerprint TEXT NOT NULL,
                    formula_fingerprint TEXT,
                    validation_status TEXT NOT NULL,
                    validation_errors_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(session_id, ordinal)
                );
                CREATE TABLE IF NOT EXISTS ai_strategy_formula_backtests (
                    backtest_run_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    draft_id TEXT NOT NULL,
                    formula_fingerprint TEXT NOT NULL,
                    dataset_snapshot_id TEXT NOT NULL,
                    cost_model_reference TEXT NOT NULL,
                    status TEXT NOT NULL,
                    canonical_backtest_result_id INTEGER,
                    evidence_fingerprint TEXT,
                    failure_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_strategy_backtest_critiques (
                    critique_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    draft_id TEXT NOT NULL,
                    backtest_run_id TEXT NOT NULL,
                    workflow_id TEXT,
                    status TEXT NOT NULL,
                    normalized_artifact_json TEXT,
                    artifact_fingerprint TEXT,
                    failure_code TEXT,
                    run_claimed_at TEXT,
                    provider_id TEXT,
                    model_id TEXT,
                    prompt_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_strategy_research_reviews (
                    review_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    session_id TEXT NOT NULL,
                    critique_id TEXT NOT NULL,
                    critique_artifact_fingerprint TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_strategy_research_events (
                    event_id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT,
                    event_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_strategy_sealed_tests (
                    sealed_test_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    draft_id TEXT NOT NULL,
                    backtest_run_id TEXT NOT NULL,
                    research_family_id TEXT NOT NULL,
                    partition_fingerprint TEXT NOT NULL,
                    champion_formula_fingerprint TEXT NOT NULL,
                    consumed_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    evidence_json TEXT,
                    evidence_fingerprint TEXT,
                    challenger_comparison_json TEXT,
                    failure_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ai_strategy_drafts_session
                    ON ai_strategy_hypothesis_drafts(session_id, ordinal);
                CREATE INDEX IF NOT EXISTS idx_ai_strategy_backtests_session
                    ON ai_strategy_formula_backtests(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_ai_strategy_critiques_session
                    ON ai_strategy_backtest_critiques(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_ai_strategy_events_entity
                    ON ai_strategy_research_events(entity_id, created_at, event_id);
                CREATE INDEX IF NOT EXISTS idx_ai_strategy_sealed_partition
                    ON ai_strategy_sealed_tests(partition_fingerprint);
                CREATE INDEX IF NOT EXISTS idx_ai_strategy_sealed_session
                    ON ai_strategy_sealed_tests(session_id, created_at);
                """)
