"""Frozen v1 reference-data, market-data, and valuation schema fragment."""

V1_REFERENCE_SCHEMA_SQL = """
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

"""

__all__ = ["V1_REFERENCE_SCHEMA_SQL"]
