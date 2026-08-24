"""Frozen SQLite v1 schema and compatibility bootstrap."""

from __future__ import annotations

import sqlite3

__all__ = ["initialize_v1_baseline_schema"]


def _ensure_column(
    conn: sqlite3.Connection, table_name: str, column_name: str, column_type: str
) -> None:
    """Add a column to an existing SQLite table when it is missing."""
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    if any(row[1] == column_name for row in rows):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


_CONTROLLED_SUBMISSION_CLEARANCE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS controlled_submission_reconciliation_clearances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clearance_id TEXT NOT NULL UNIQUE,
    clearance_fingerprint TEXT NOT NULL UNIQUE,
    submit_intent_id TEXT NOT NULL UNIQUE,
    submit_fingerprint TEXT NOT NULL,
    order_id TEXT NOT NULL UNIQUE,
    broker_order_id TEXT NOT NULL,
    review_reconciliation_run_id TEXT NOT NULL,
    review_reconciliation_item_id INTEGER NOT NULL,
    broker_evidence_fingerprint TEXT NOT NULL,
    account_truth_import_run_id TEXT NOT NULL,
    account_truth_file_fingerprint TEXT NOT NULL,
    account_truth_source_fingerprint TEXT NOT NULL,
    clearance_reconciliation_run_id TEXT NOT NULL UNIQUE,
    operator_id TEXT NOT NULL,
    operator_approval_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status = 'cleared'),
    terminal_status TEXT NOT NULL CHECK(terminal_status IN ('filled', 'cancelled')),
    fill_count INTEGER NOT NULL CHECK(fill_count >= 0),
    fill_quantity TEXT NOT NULL,
    cancelled_quantity TEXT NOT NULL,
    lifecycle_observation_id TEXT NOT NULL DEFAULT '',
    lifecycle_evidence_fingerprint TEXT NOT NULL DEFAULT '',
    lifecycle_source_sequence INTEGER NOT NULL DEFAULT 0,
    cleared_at_epoch_ms INTEGER NOT NULL CHECK(cleared_at_epoch_ms >= 0),
    cleared_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(submit_intent_id)
        REFERENCES controlled_broker_submit_intents(submit_intent_id),
    FOREIGN KEY(order_id) REFERENCES oms_orders(order_id)
);
"""


_CONTROLLED_SUBMISSION_LEDGER_POSTING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS controlled_submission_ledger_postings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_id TEXT NOT NULL UNIQUE,
    posting_fingerprint TEXT NOT NULL UNIQUE,
    clearance_id TEXT NOT NULL UNIQUE,
    clearance_fingerprint TEXT NOT NULL,
    submit_intent_id TEXT NOT NULL UNIQUE,
    order_id TEXT NOT NULL UNIQUE,
    broker_order_id TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    terminal_status TEXT NOT NULL CHECK(terminal_status IN ('filled', 'cancelled')),
    clearance_reconciliation_run_id TEXT NOT NULL,
    broker_evidence_fingerprint TEXT NOT NULL,
    account_truth_import_run_id TEXT NOT NULL,
    account_truth_file_fingerprint TEXT NOT NULL,
    account_truth_source_fingerprint TEXT NOT NULL,
    account_truth_review_fingerprint TEXT NOT NULL,
    lifecycle_observation_id TEXT NOT NULL DEFAULT '',
    lifecycle_evidence_fingerprint TEXT NOT NULL DEFAULT '',
    lifecycle_source_sequence INTEGER NOT NULL DEFAULT 0,
    pre_valuation_snapshot_id TEXT NOT NULL,
    pre_valuation_as_of TEXT NOT NULL,
    pre_valuation_status TEXT NOT NULL,
    pre_ledger_cutoff_id INTEGER NOT NULL CHECK(pre_ledger_cutoff_id >= 0),
    pre_ledger_fingerprint TEXT NOT NULL,
    operator_id TEXT NOT NULL,
    operator_approval_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status = 'applied'),
    ledger_entry_count INTEGER NOT NULL CHECK(ledger_entry_count >= 0),
    ledger_entry_fingerprint TEXT NOT NULL,
    ledger_entry_ids_json TEXT NOT NULL DEFAULT '[]',
    post_ledger_cutoff_id INTEGER NOT NULL CHECK(post_ledger_cutoff_id >= 0),
    applied_at_epoch_ms INTEGER NOT NULL CHECK(applied_at_epoch_ms >= 0),
    applied_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(clearance_id)
        REFERENCES controlled_submission_reconciliation_clearances(clearance_id),
    FOREIGN KEY(submit_intent_id)
        REFERENCES controlled_broker_submit_intents(submit_intent_id),
    FOREIGN KEY(order_id) REFERENCES oms_orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_controlled_submission_ledger_posting_time
ON controlled_submission_ledger_postings(applied_at_epoch_ms DESC, id DESC);
"""


_CONTROLLED_SUBMISSION_LEDGER_CORRECTION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS controlled_submission_ledger_corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    correction_id TEXT NOT NULL UNIQUE,
    correction_fingerprint TEXT NOT NULL UNIQUE,
    posting_id TEXT NOT NULL UNIQUE,
    posting_fingerprint TEXT NOT NULL,
    original_ledger_entry_ids_json TEXT NOT NULL,
    original_ledger_entry_fingerprint TEXT NOT NULL,
    reason_code TEXT NOT NULL CHECK(reason_code IN (
        'broker_evidence_superseded',
        'duplicate_controlled_posting',
        'operator_confirmed_mapping_error'
    )),
    account_truth_import_run_id TEXT NOT NULL,
    account_truth_file_fingerprint TEXT NOT NULL,
    account_truth_source_fingerprint TEXT NOT NULL,
    account_truth_review_fingerprint TEXT NOT NULL,
    pre_valuation_snapshot_id TEXT NOT NULL,
    pre_valuation_as_of TEXT NOT NULL,
    pre_valuation_status TEXT NOT NULL,
    pre_ledger_cutoff_id INTEGER NOT NULL CHECK(pre_ledger_cutoff_id > 0),
    pre_ledger_fingerprint TEXT NOT NULL,
    plan_fingerprint TEXT NOT NULL,
    operator_id TEXT NOT NULL,
    operator_approval_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status = 'applied'),
    correction_ledger_entry_id INTEGER NOT NULL UNIQUE,
    post_ledger_cutoff_id INTEGER NOT NULL CHECK(post_ledger_cutoff_id > 0),
    applied_at_epoch_ms INTEGER NOT NULL CHECK(applied_at_epoch_ms >= 0),
    applied_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(posting_id)
        REFERENCES controlled_submission_ledger_postings(posting_id),
    FOREIGN KEY(correction_ledger_entry_id) REFERENCES ledger_entries(id)
);

CREATE INDEX IF NOT EXISTS idx_controlled_submission_ledger_correction_time
ON controlled_submission_ledger_corrections(applied_at_epoch_ms DESC, id DESC);
"""


def _ensure_controlled_submission_clearance_terminal_schema(
    conn: sqlite3.Connection,
) -> None:
    """Create or atomically migrate the exact-terminal clearance store."""

    row = conn.execute("""
        SELECT sql FROM sqlite_master
        WHERE type = 'table'
          AND name = 'controlled_submission_reconciliation_clearances'
        """).fetchone()
    if row is None:
        conn.execute(_CONTROLLED_SUBMISSION_CLEARANCE_TABLE_SQL)
    else:
        columns = {
            str(item[1])
            for item in conn.execute(
                "PRAGMA table_info(controlled_submission_reconciliation_clearances)"
            ).fetchall()
        }
        required_columns = {
            "terminal_status",
            "cancelled_quantity",
            "lifecycle_observation_id",
            "lifecycle_evidence_fingerprint",
            "lifecycle_source_sequence",
        }
        normalized_sql = "".join(str(row[0] or "").lower().split())
        requires_rebuild = not required_columns.issubset(columns) or (
            "check(fill_count>0)" in normalized_sql
        )
        if requires_rebuild:
            legacy_table = "controlled_submission_reconciliation_clearances_v2"
            conn.execute(
                "DROP INDEX IF EXISTS idx_controlled_submission_clearance_time"
            )
            legacy_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (legacy_table,),
            ).fetchone()
            if legacy_exists is not None:
                raise RuntimeError(
                    "controlled submission clearance migration recovery required"
                )
            conn.execute(
                "ALTER TABLE controlled_submission_reconciliation_clearances "
                f"RENAME TO {legacy_table}"
            )
            conn.execute(_CONTROLLED_SUBMISSION_CLEARANCE_TABLE_SQL)
            legacy_columns = {
                str(item[1])
                for item in conn.execute(
                    f"PRAGMA table_info({legacy_table})"
                ).fetchall()
            }

            def legacy(field: str, fallback: str) -> str:
                return field if field in legacy_columns else fallback

            conn.execute(f"""
                INSERT INTO controlled_submission_reconciliation_clearances (
                    id, clearance_id, clearance_fingerprint, submit_intent_id,
                    submit_fingerprint, order_id, broker_order_id,
                    review_reconciliation_run_id, review_reconciliation_item_id,
                    broker_evidence_fingerprint, account_truth_import_run_id,
                    account_truth_file_fingerprint,
                    account_truth_source_fingerprint,
                    clearance_reconciliation_run_id, operator_id,
                    operator_approval_id, status, terminal_status, fill_count,
                    fill_quantity, cancelled_quantity,
                    lifecycle_observation_id, lifecycle_evidence_fingerprint,
                    lifecycle_source_sequence, cleared_at_epoch_ms, cleared_at,
                    payload_json, created_at
                )
                SELECT
                    id, clearance_id, clearance_fingerprint, submit_intent_id,
                    submit_fingerprint, order_id, broker_order_id,
                    review_reconciliation_run_id, review_reconciliation_item_id,
                    broker_evidence_fingerprint, account_truth_import_run_id,
                    account_truth_file_fingerprint,
                    account_truth_source_fingerprint,
                    clearance_reconciliation_run_id, operator_id,
                    operator_approval_id, status,
                    {legacy('terminal_status', "'filled'")}, fill_count,
                    fill_quantity, {legacy('cancelled_quantity', "'0'")},
                    {legacy('lifecycle_observation_id', "''")},
                    {legacy('lifecycle_evidence_fingerprint', "''")},
                    {legacy('lifecycle_source_sequence', '0')},
                    cleared_at_epoch_ms, cleared_at, payload_json, created_at
                FROM {legacy_table}
                """)
            conn.execute(f"DROP TABLE {legacy_table}")
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_controlled_submission_clearance_time
        ON controlled_submission_reconciliation_clearances(cleared_at_epoch_ms DESC)
        """)


def initialize_v1_baseline_schema(conn: sqlite3.Connection) -> None:
    """Create the frozen v1 baseline used by legacy upgrades and verification."""
    conn.executescript(_SCHEMA)
    _ensure_controlled_submission_clearance_terminal_schema(conn)
    conn.executescript(_CONTROLLED_SUBMISSION_LEDGER_POSTING_TABLE_SQL)
    conn.executescript(_CONTROLLED_SUBMISSION_LEDGER_CORRECTION_TABLE_SQL)
    _ensure_column(conn, "backtest_results", "metrics_json", "TEXT")
    _ensure_column(conn, "backtest_results", "cost_summary_json", "TEXT")
    _ensure_column(conn, "quote_snapshots", "quote_source", "TEXT")
    _ensure_column(conn, "quote_snapshots", "provider_name", "TEXT")
    _ensure_column(conn, "quote_snapshots", "quote_status", "TEXT")
    _ensure_column(conn, "quote_snapshots", "stale_reason", "TEXT")
    _ensure_column(conn, "quote_snapshots", "provider_status", "TEXT")
    _ensure_column(conn, "quote_snapshots", "captured_reason", "TEXT")
    _ensure_column(conn, "quote_snapshots", "nav_date", "TEXT")
    _ensure_column(conn, "quote_snapshots", "fetch_run_id", "TEXT")
    _ensure_column(conn, "latest_quotes", "fetch_run_id", "TEXT")
    _ensure_column(conn, "ledger_entries", "gross_amount", "REAL")
    _ensure_column(conn, "ledger_entries", "net_cash_impact", "REAL")
    _ensure_column(conn, "ledger_entries", "fee_breakdown_json", "TEXT")
    _ensure_column(conn, "ledger_entries", "fee_rule_id", "TEXT")
    _ensure_column(conn, "ledger_entries", "fee_rule_version", "TEXT")
    _ensure_column(conn, "ledger_entries", "estimated_commission", "REAL")
    _ensure_column(conn, "ledger_entries", "estimated_net_cash_impact", "REAL")
    _ensure_column(conn, "ledger_entries", "estimated_fee_breakdown_json", "TEXT")
    _ensure_column(conn, "ledger_entries", "estimated_fee_rule_id", "TEXT")
    _ensure_column(conn, "ledger_entries", "estimated_fee_rule_version", "TEXT")
    _ensure_column(conn, "ledger_entries", "settlement_status", "TEXT")
    _ensure_column(conn, "ledger_entries", "settled_at", "TEXT")
    _ensure_column(conn, "ledger_entries", "settlement_source", "TEXT")
    _ensure_column(conn, "ledger_entries", "settlement_source_ref", "TEXT")
    _ensure_column(conn, "ledger_entries", "settlement_note", "TEXT")
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS
        idx_ledger_entries_settlement_evidence
        ON ledger_entries(settlement_source, settlement_source_ref)
        WHERE settlement_source_ref IS NOT NULL
        """)
    _ensure_column(conn, "ledger_entries", "cost_basis_method", "TEXT")
    _ensure_column(conn, "ledger_entries", "correction_payload_json", "TEXT")
    _ensure_column(
        conn,
        "execution_reconciliation_items",
        "broker_event_count",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _ensure_column(conn, "paper_shadow_runs", "review_status", "TEXT")
    _ensure_column(conn, "paper_shadow_runs", "reviewed_at", "TEXT")
    _ensure_column(conn, "paper_shadow_runs", "review_notes", "TEXT")
    _ensure_column(conn, "paper_shadow_runs", "reviewer", "TEXT")
    _ensure_column(
        conn,
        "controlled_session_budget_reservations",
        "reserved_by_symbol_json",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _ensure_column(
        conn,
        "controlled_session_budget_reservations",
        "symbol_capacity_json",
        "TEXT NOT NULL DEFAULT '{}'",
    )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    target_weight REAL NOT NULL,
    price REAL,
    asset_class TEXT DEFAULT 'stock'
);

CREATE TABLE IF NOT EXISTS backtest_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    config_json TEXT NOT NULL,
    initial_cash REAL NOT NULL,
    final_equity REAL NOT NULL,
    total_return REAL NOT NULL,
    sharpe REAL DEFAULT 0,
    sortino REAL DEFAULT 0,
    max_drawdown REAL DEFAULT 0,
    win_rate REAL DEFAULT 0,
    duration_days INTEGER DEFAULT 0,
    equity_curve_json TEXT NOT NULL,
    metrics_json TEXT DEFAULT '{}',
    cost_summary_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    cash REAL NOT NULL,
    total_equity REAL NOT NULL,
    positions_json TEXT NOT NULL,
    allocation_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    asset_class TEXT NOT NULL DEFAULT 'stock',
    display_name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(symbol)
);

CREATE TABLE IF NOT EXISTS instrument_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL DEFAULT 'stock',
    display_name TEXT NOT NULL,
    provider_symbol TEXT,
    exchange TEXT,
    market TEXT,
    provider_name TEXT,
    source TEXT NOT NULL DEFAULT 'provider',
    fetched_at TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(symbol, asset_type)
);

CREATE TABLE IF NOT EXISTS quote_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    asset_class TEXT NOT NULL DEFAULT 'stock',
    price REAL NOT NULL,
    volume REAL,
    timestamp TEXT NOT NULL,
    created_at TEXT NOT NULL,
    quote_source TEXT,
    provider_name TEXT,
    quote_status TEXT,
    stale_reason TEXT,
    provider_status TEXT,
    captured_reason TEXT,
    nav_date TEXT,
    fetch_run_id TEXT
);

CREATE TABLE IF NOT EXISTS daily_close_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    asset_class TEXT NOT NULL DEFAULT 'stock',
    trade_date TEXT NOT NULL,
    close_price REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'scheduler_close',
    captured_at TEXT NOT NULL,
    UNIQUE(symbol, trade_date)
);

CREATE TABLE IF NOT EXISTS latest_quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL DEFAULT 'stock',
    price REAL NOT NULL,
    previous_close REAL,
    change REAL,
    change_percent REAL,
    volume REAL,
    turnover REAL,
    quote_timestamp TEXT NOT NULL,
    quote_source TEXT,
    provider_name TEXT,
    provider_status TEXT,
    quote_status TEXT NOT NULL DEFAULT 'live',
    stale_reason TEXT,
    captured_at TEXT NOT NULL,
    captured_reason TEXT,
    nav_date TEXT,
    fetch_run_id TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(symbol, asset_type)
);

CREATE TABLE IF NOT EXISTS market_calendar_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange TEXT NOT NULL,
    year INTEGER NOT NULL,
    provider TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    status TEXT NOT NULL,
    trading_day_count INTEGER NOT NULL DEFAULT 0,
    closed_day_count INTEGER NOT NULL DEFAULT 0,
    source_fingerprint TEXT NOT NULL,
    official_verification_status TEXT NOT NULL DEFAULT 'unverified',
    official_source_url TEXT,
    official_verified_at TEXT,
    official_verified_by TEXT,
    limitations_json TEXT NOT NULL DEFAULT '[]',
    days_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(exchange, year)
);

CREATE TABLE IF NOT EXISTS action_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_signal_id INTEGER NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    direction TEXT NOT NULL,
    urgency TEXT NOT NULL,
    target_weight REAL NOT NULL,
    price REAL,
    strategy_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    asset_class TEXT NOT NULL DEFAULT 'stock',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
CREATE INDEX IF NOT EXISTS idx_backtest_created ON backtest_results(created_at);
CREATE INDEX IF NOT EXISTS idx_watchlist_assets_symbol ON watchlist_assets(symbol);
CREATE INDEX IF NOT EXISTS idx_watchlist_assets_asset_class ON watchlist_assets(asset_class);
CREATE INDEX IF NOT EXISTS idx_instrument_metadata_symbol_asset_type
ON instrument_metadata(symbol, asset_type);
CREATE INDEX IF NOT EXISTS idx_instrument_metadata_display_name
ON instrument_metadata(display_name);
CREATE INDEX IF NOT EXISTS idx_instrument_metadata_provider
ON instrument_metadata(provider_name);
CREATE INDEX IF NOT EXISTS idx_quote_snapshots_symbol_ts ON quote_snapshots(symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_daily_close_symbol_trade_date ON daily_close_snapshots(symbol, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_latest_quotes_symbol_asset_type ON latest_quotes(symbol, asset_type);
CREATE INDEX IF NOT EXISTS idx_latest_quotes_quote_timestamp ON latest_quotes(quote_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_latest_quotes_provider_status ON latest_quotes(provider_status);
CREATE INDEX IF NOT EXISTS idx_latest_quotes_quote_status ON latest_quotes(quote_status);
CREATE INDEX IF NOT EXISTS idx_market_calendar_exchange_year
ON market_calendar_snapshots(exchange, year);
CREATE INDEX IF NOT EXISTS idx_market_calendar_status
ON market_calendar_snapshots(status, official_verification_status);
CREATE INDEX IF NOT EXISTS idx_action_tasks_status_ts ON action_tasks(status, timestamp DESC);

CREATE TABLE IF NOT EXISTS quote_fetch_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    trigger TEXT NOT NULL,
    provider TEXT,
    asset_type TEXT,
    symbol_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    cache_hit_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error_message TEXT,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_quote_fetch_runs_started_at
ON quote_fetch_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_quote_fetch_runs_status
ON quote_fetch_runs(status);
CREATE INDEX IF NOT EXISTS idx_quote_fetch_runs_provider
ON quote_fetch_runs(provider);

CREATE TABLE IF NOT EXISTS valuation_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL UNIQUE,
    as_of TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    valuation_policy TEXT NOT NULL,
    ledger_cutoff_id INTEGER NOT NULL DEFAULT 0,
    ledger_fingerprint TEXT NOT NULL,
    quote_set_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    quotes_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_valuation_snapshots_as_of
ON valuation_snapshots(as_of DESC);
CREATE INDEX IF NOT EXISTS idx_valuation_snapshots_trade_date
ON valuation_snapshots(trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_valuation_snapshots_status
ON valuation_snapshots(status);

CREATE TABLE IF NOT EXISTS event_log (
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

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL UNIQUE,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL,
    asset_class TEXT NOT NULL DEFAULT 'stock',
    intent_id TEXT,
    risk_decision_id TEXT,
    execution_mode TEXT NOT NULL DEFAULT 'paper',
    status TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'execution',
    source_ref TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_status_ts
ON orders(status, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_orders_symbol_ts
ON orders(symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_orders_source
ON orders(source, source_ref);

CREATE TABLE IF NOT EXISTS manual_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL UNIQUE,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL,
    intent_id TEXT,
    risk_decision_id TEXT,
    execution_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_manual_orders_status_ts
ON manual_orders(status, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_manual_orders_symbol_ts
ON manual_orders(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fill_id TEXT NOT NULL UNIQUE,
    order_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    fill_price REAL NOT NULL,
    fill_quantity REAL NOT NULL,
    commission REAL DEFAULT 0,
    slippage REAL DEFAULT 0,
    asset_class TEXT NOT NULL DEFAULT 'stock',
    execution_mode TEXT NOT NULL DEFAULT 'paper',
    provider_name TEXT,
    broker_order_id TEXT,
    source TEXT NOT NULL DEFAULT 'execution',
    source_ref TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fills_order_ts
ON fills(order_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_fills_symbol_ts
ON fills(symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_fills_source
ON fills(source, source_ref);

CREATE TABLE IF NOT EXISTS cash_flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    amount REAL NOT NULL,
    flow_type TEXT NOT NULL DEFAULT 'deposit',
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    commission REAL DEFAULT 0,
    asset_class TEXT DEFAULT 'stock',
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);

CREATE INDEX IF NOT EXISTS idx_cash_flows_timestamp ON cash_flows(timestamp);

CREATE TABLE IF NOT EXISTS pending_fund_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submitted_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    display_name TEXT NOT NULL,
    amount REAL NOT NULL,
    commission REAL DEFAULT 0,
    asset_class TEXT DEFAULT 'fund',
    target_trade_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    note TEXT DEFAULT '',
    confirmed_nav REAL,
    confirmed_quantity REAL,
    confirmed_trade_date TEXT,
    trade_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pending_fund_orders_status_date
ON pending_fund_orders(status, target_trade_date);

CREATE TABLE IF NOT EXISTS ledger_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    amount REAL,
    symbol TEXT,
    direction TEXT,
    quantity REAL,
    price REAL,
    commission REAL DEFAULT 0,
    gross_amount REAL,
    net_cash_impact REAL,
    fee_breakdown_json TEXT,
    fee_rule_id TEXT,
    fee_rule_version TEXT,
    estimated_commission REAL,
    estimated_net_cash_impact REAL,
    estimated_fee_breakdown_json TEXT,
    estimated_fee_rule_id TEXT,
    estimated_fee_rule_version TEXT,
    settlement_status TEXT,
    settled_at TEXT,
    settlement_source TEXT,
    settlement_source_ref TEXT,
    settlement_note TEXT,
    cost_basis_method TEXT,
    correction_payload_json TEXT,
    asset_class TEXT DEFAULT 'stock',
    note TEXT DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    source_ref TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(source, source_ref)
);

CREATE INDEX IF NOT EXISTS idx_ledger_entries_timestamp ON ledger_entries(timestamp);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_type_ts ON ledger_entries(entry_type, timestamp DESC);

CREATE TABLE IF NOT EXISTS market_research_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    asset_class TEXT NOT NULL DEFAULT 'stock',
    entry_kind TEXT NOT NULL DEFAULT 'note',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'normal',
    event_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_market_research_symbol_updated
ON market_research_notes(symbol, updated_at DESC);
"""
