"""Frozen v1 audit, automation, execution, and strategy schema fragment."""

V1_OPERATIONAL_SCHEMA_SQL = """CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    source TEXT NOT NULL DEFAULT 'app',
    source_ref TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_log_type_ts
ON event_log(event_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_event_log_entity
ON event_log(entity_type, entity_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_event_log_source
ON event_log(source, source_ref);

CREATE TABLE IF NOT EXISTS decision_outcome_reviews (
    review_id TEXT PRIMARY KEY,
    signal_id INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    target_json TEXT NOT NULL,
    target_fingerprint TEXT NOT NULL,
    reviewed_by TEXT NOT NULL,
    user_decision TEXT NOT NULL CHECK(user_decision IN (
        'acted', 'ignored', 'deferred', 'blocked'
    )),
    outcome TEXT NOT NULL CHECK(outcome IN (
        'evidence_supported', 'evidence_not_supported',
        'risk_gate_validated', 'not_executed', 'inconclusive'
    )),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(signal_id) REFERENCES signals(id)
);

CREATE INDEX IF NOT EXISTS idx_decision_outcome_reviews_signal
ON decision_outcome_reviews(signal_id, created_at DESC, review_id DESC);

CREATE TABLE IF NOT EXISTS decision_outcome_review_events (
    review_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(review_id, sequence),
    FOREIGN KEY(review_id) REFERENCES decision_outcome_reviews(review_id)
);

CREATE TABLE IF NOT EXISTS decision_quality_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    decision_date TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    target_json TEXT NOT NULL,
    target_fingerprint TEXT NOT NULL,
    qualified INTEGER NOT NULL CHECK(qualified IN (0, 1)),
    captured_by TEXT NOT NULL,
    captured_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decision_quality_snapshots_date
ON decision_quality_snapshots(decision_date, captured_at DESC, snapshot_id DESC);

CREATE TABLE IF NOT EXISTS decision_quality_snapshot_events (
    snapshot_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, sequence),
    FOREIGN KEY(snapshot_id) REFERENCES decision_quality_snapshots(snapshot_id)
);

CREATE TABLE IF NOT EXISTS controlled_session_budget_reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reservation_id TEXT NOT NULL UNIQUE,
    attestation_id TEXT NOT NULL UNIQUE,
    envelope_fingerprint TEXT NOT NULL,
    capital_evaluation_input_fingerprint TEXT NOT NULL,
    authorization_id TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    account_alias TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    trading_day TEXT NOT NULL,
    requested_start_at TEXT NOT NULL,
    requested_expires_at TEXT NOT NULL,
    reserved_gross_units INTEGER NOT NULL CHECK(reserved_gross_units >= 0),
    reserved_buy_units INTEGER NOT NULL CHECK(reserved_buy_units >= 0),
    reserved_turnover_units INTEGER NOT NULL CHECK(reserved_turnover_units >= 0),
    reserved_order_count INTEGER NOT NULL CHECK(reserved_order_count > 0),
    capital_capacity_units INTEGER NOT NULL CHECK(capital_capacity_units >= 0),
    cash_capacity_units INTEGER NOT NULL CHECK(cash_capacity_units >= 0),
    turnover_capacity_units INTEGER NOT NULL CHECK(turnover_capacity_units >= 0),
    order_count_capacity INTEGER NOT NULL CHECK(order_count_capacity > 0),
    reserved_by_symbol_json TEXT NOT NULL DEFAULT '{}',
    symbol_capacity_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK(status = 'reserved'),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_controlled_session_budget_scope_window
ON controlled_session_budget_reservations(
    authorization_id, account_alias, requested_start_at, requested_expires_at
);
CREATE INDEX IF NOT EXISTS idx_controlled_session_budget_scope_day
ON controlled_session_budget_reservations(
    authorization_id, account_alias, trading_day
);

CREATE TABLE IF NOT EXISTS controlled_session_pause_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pause_event_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    session_fingerprint TEXT NOT NULL,
    reservation_id TEXT NOT NULL,
    gate_fingerprint TEXT NOT NULL,
    reason_fingerprint TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    gate_snapshot_json TEXT NOT NULL,
    paused_at_epoch_ms INTEGER NOT NULL CHECK(paused_at_epoch_ms >= 0),
    paused_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status = 'paused'),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_controlled_session_pause_session_time
ON controlled_session_pause_events(session_id, paused_at_epoch_ms DESC);

CREATE TABLE IF NOT EXISTS controlled_session_runtime_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    session_fingerprint TEXT NOT NULL UNIQUE,
    issuance_fingerprint TEXT NOT NULL UNIQUE,
    reservation_id TEXT NOT NULL UNIQUE,
    attestation_id TEXT NOT NULL,
    envelope_fingerprint TEXT NOT NULL,
    authorization_id TEXT NOT NULL,
    account_alias TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    operator_id TEXT NOT NULL,
    operator_approval_id TEXT NOT NULL,
    order_ids_json TEXT NOT NULL,
    effective_at_epoch_ms INTEGER NOT NULL CHECK(effective_at_epoch_ms >= 0),
    expires_at_epoch_ms INTEGER NOT NULL CHECK(expires_at_epoch_ms > effective_at_epoch_ms),
    effective_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    max_order_rate_per_minute INTEGER NOT NULL CHECK(max_order_rate_per_minute > 0),
    token_salt TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('enabled', 'revoked')),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_controlled_session_runtime_scope_window
ON controlled_session_runtime_sessions(
    authorization_id, account_alias, effective_at_epoch_ms, expires_at_epoch_ms
);

CREATE TABLE IF NOT EXISTS controlled_session_revocation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    revocation_id TEXT NOT NULL UNIQUE,
    revocation_fingerprint TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL UNIQUE,
    session_fingerprint TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    operator_id TEXT NOT NULL,
    operator_approval_id TEXT NOT NULL,
    revoked_at_epoch_ms INTEGER NOT NULL CHECK(revoked_at_epoch_ms >= 0),
    revoked_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS controlled_session_replacement_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    replacement_id TEXT NOT NULL UNIQUE,
    replacement_fingerprint TEXT NOT NULL UNIQUE,
    predecessor_session_id TEXT NOT NULL UNIQUE,
    predecessor_session_fingerprint TEXT NOT NULL,
    pause_event_id TEXT NOT NULL,
    recovery_snapshot_ids_json TEXT NOT NULL,
    replacement_session_id TEXT NOT NULL UNIQUE,
    replacement_session_fingerprint TEXT NOT NULL,
    replacement_reservation_id TEXT NOT NULL UNIQUE,
    operator_id TEXT NOT NULL,
    operator_approval_id TEXT NOT NULL,
    reviewed_at_epoch_ms INTEGER NOT NULL CHECK(reviewed_at_epoch_ms >= 0),
    reviewed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_controlled_session_replacement_review_time
ON controlled_session_replacement_events(reviewed_at_epoch_ms DESC);

CREATE TABLE IF NOT EXISTS controlled_session_gate_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL UNIQUE,
    snapshot_fingerprint TEXT NOT NULL,
    session_id TEXT NOT NULL,
    session_fingerprint TEXT NOT NULL,
    source_fingerprint TEXT NOT NULL,
    observed_at_epoch_ms INTEGER NOT NULL CHECK(observed_at_epoch_ms >= 0),
    observed_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('clear', 'blocked')),
    gate_snapshot_json TEXT NOT NULL,
    source_evidence_json TEXT NOT NULL,
    blockers_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_controlled_session_gate_snapshot_session_time
ON controlled_session_gate_snapshots(session_id, observed_at_epoch_ms DESC);

CREATE TABLE IF NOT EXISTS controlled_session_runtime_states (
    session_id TEXT PRIMARY KEY,
    session_fingerprint TEXT NOT NULL,
    reservation_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status = 'paused'),
    pause_event_id TEXT NOT NULL UNIQUE,
    reason_fingerprint TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    paused_at_epoch_ms INTEGER NOT NULL CHECK(paused_at_epoch_ms >= 0),
    paused_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS controlled_session_rate_admissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admission_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    session_fingerprint TEXT NOT NULL,
    reservation_id TEXT NOT NULL,
    authorization_id TEXT NOT NULL,
    account_alias TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    max_order_rate_per_minute INTEGER NOT NULL
        CHECK(max_order_rate_per_minute > 0),
    admitted_at_epoch_ms INTEGER NOT NULL CHECK(admitted_at_epoch_ms >= 0),
    admitted_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status = 'admitted'),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, order_id),
    UNIQUE(session_id, request_id)
);

CREATE INDEX IF NOT EXISTS idx_controlled_session_rate_scope_time
ON controlled_session_rate_admissions(
    authorization_id, account_alias, admitted_at_epoch_ms DESC
);
CREATE INDEX IF NOT EXISTS idx_controlled_session_rate_session_time
ON controlled_session_rate_admissions(session_id, admitted_at_epoch_ms DESC);

CREATE TABLE IF NOT EXISTS risk_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL UNIQUE,
    intent_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    passed INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    resulting_order_id TEXT,
    severity TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_risk_decisions_timestamp
ON risk_decisions(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_risk_decisions_symbol_ts
ON risk_decisions(symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_risk_decisions_passed_ts
ON risk_decisions(passed, timestamp DESC);

CREATE TABLE IF NOT EXISTS runtime_controls (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS automation_policies (
    policy_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT
);

CREATE TABLE IF NOT EXISTS automation_runs (
    run_id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL,
    run_date TEXT NOT NULL,
    status TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    source_ref TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_automation_runs_type_date
ON automation_runs(run_type, run_date DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_automation_runs_status
ON automation_runs(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS oms_orders (
    order_id TEXT PRIMARY KEY,
    intent_key TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    quantity REAL NOT NULL,
    order_type TEXT NOT NULL,
    limit_price REAL,
    status TEXT NOT NULL,
    broker_submission_enabled INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    source_ref TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_oms_orders_status
ON oms_orders(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_oms_orders_symbol
ON oms_orders(symbol, updated_at DESC);

CREATE TABLE IF NOT EXISTS oms_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    transitioned_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(order_id) REFERENCES oms_orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_oms_transitions_order
ON oms_transitions(order_id, id ASC);

CREATE TABLE IF NOT EXISTS controlled_broker_submit_intents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submit_intent_id TEXT NOT NULL UNIQUE,
    submit_fingerprint TEXT NOT NULL UNIQUE,
    order_id TEXT NOT NULL UNIQUE,
    order_fingerprint TEXT NOT NULL,
    confirmation_id TEXT NOT NULL,
    dossier_fingerprint TEXT NOT NULL,
    gateway_id TEXT NOT NULL,
    gateway_verification_fingerprint TEXT NOT NULL,
    release_evidence_id TEXT NOT NULL,
    release_evidence_fingerprint TEXT NOT NULL,
    client_order_id TEXT NOT NULL UNIQUE,
    operator_id TEXT NOT NULL,
    operator_approval_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'prepared', 'submitted', 'rejected', 'submission_unknown'
    )),
    broker_order_id TEXT NOT NULL DEFAULT '',
    broker_status TEXT NOT NULL DEFAULT '',
    prepared_at_epoch_ms INTEGER NOT NULL CHECK(prepared_at_epoch_ms >= 0),
    prepared_at TEXT NOT NULL,
    last_recovery_at_epoch_ms INTEGER NOT NULL DEFAULT 0,
    last_recovery_at TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(order_id) REFERENCES oms_orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_controlled_broker_submit_status_time
ON controlled_broker_submit_intents(status, prepared_at_epoch_ms DESC);

CREATE TABLE IF NOT EXISTS controlled_broker_rejection_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id TEXT NOT NULL UNIQUE,
    review_fingerprint TEXT NOT NULL UNIQUE,
    submit_intent_id TEXT NOT NULL UNIQUE,
    submit_fingerprint TEXT NOT NULL,
    order_id TEXT NOT NULL UNIQUE,
    order_fingerprint TEXT NOT NULL,
    result_fingerprint TEXT NOT NULL,
    gateway_id TEXT NOT NULL,
    account_alias TEXT NOT NULL,
    client_order_id TEXT NOT NULL UNIQUE,
    submission_operator_id TEXT NOT NULL,
    reviewer_id TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK(disposition = 'acknowledged_no_retry'),
    rejection_classification TEXT NOT NULL CHECK(rejection_classification IN (
        'local_pre_gateway_rejection',
        'definitive_gateway_rejection'
    )),
    evidence_as_of TEXT NOT NULL,
    recorded_at_epoch_ms INTEGER NOT NULL CHECK(recorded_at_epoch_ms >= 0),
    recorded_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(submit_intent_id)
        REFERENCES controlled_broker_submit_intents(submit_intent_id),
    FOREIGN KEY(order_id) REFERENCES oms_orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_controlled_broker_rejection_review_time
ON controlled_broker_rejection_reviews(recorded_at_epoch_ms DESC, id DESC);

CREATE TABLE IF NOT EXISTS broker_gateway_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gateway_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    order_id TEXT,
    status TEXT NOT NULL,
    actor TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_broker_gateway_events_order
ON broker_gateway_events(order_id, id ASC);
CREATE INDEX IF NOT EXISTS idx_broker_gateway_events_gateway
ON broker_gateway_events(gateway_id, id ASC);

CREATE TABLE IF NOT EXISTS execution_reconciliation_runs (
    run_id TEXT PRIMARY KEY,
    run_date TEXT NOT NULL,
    status TEXT NOT NULL,
    item_count INTEGER NOT NULL DEFAULT 0,
    open_item_count INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_execution_reconciliation_runs_date
ON execution_reconciliation_runs(run_date DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS execution_reconciliation_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    item_status TEXT NOT NULL,
    suggested_action TEXT NOT NULL,
    gateway_event_count INTEGER NOT NULL DEFAULT 0,
    broker_event_count INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES execution_reconciliation_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_execution_reconciliation_items_run
ON execution_reconciliation_items(run_id, id ASC);
CREATE INDEX IF NOT EXISTS idx_execution_reconciliation_items_order
ON execution_reconciliation_items(order_id, id ASC);

CREATE TABLE IF NOT EXISTS strategy_promotion_states (
    strategy_id TEXT PRIMARY KEY,
    stage TEXT NOT NULL,
    gate_status TEXT NOT NULL,
    live_like_enabled INTEGER NOT NULL DEFAULT 0,
    missing_requirements_json TEXT NOT NULL DEFAULT '[]',
    backtest_result_id INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_strategy_promotion_states_stage
ON strategy_promotion_states(stage, updated_at DESC);

CREATE TABLE IF NOT EXISTS strategy_promotion_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    from_stage TEXT,
    to_stage TEXT,
    actor TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_strategy_promotion_events_strategy
ON strategy_promotion_events(strategy_id, id ASC);

CREATE TABLE IF NOT EXISTS automation_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_key TEXT NOT NULL UNIQUE,
    severity TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    source TEXT NOT NULL,
    source_ref TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    acknowledged_at TEXT,
    acknowledged_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_automation_alerts_status
ON automation_alerts(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_automation_alerts_category
ON automation_alerts(category, updated_at DESC);

CREATE TABLE IF NOT EXISTS paper_shadow_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    plan_date TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    order_intent_count INTEGER NOT NULL DEFAULT 0,
    simulated_order_count INTEGER NOT NULL DEFAULT 0,
    simulated_fill_count INTEGER NOT NULL DEFAULT 0,
    divergence_status TEXT NOT NULL,
    next_manual_review_step TEXT NOT NULL,
    review_status TEXT,
    reviewed_at TEXT,
    review_notes TEXT,
    reviewer TEXT,
    limitations_json TEXT NOT NULL DEFAULT '[]',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(plan_date, input_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_paper_shadow_runs_plan_date
ON paper_shadow_runs(plan_date, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_paper_shadow_runs_input
ON paper_shadow_runs(plan_date, input_fingerprint);
CREATE INDEX IF NOT EXISTS idx_paper_shadow_runs_created
ON paper_shadow_runs(created_at DESC);

"""

__all__ = ["V1_OPERATIONAL_SCHEMA_SQL"]
