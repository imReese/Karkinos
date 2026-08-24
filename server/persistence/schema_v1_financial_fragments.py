"""Frozen v1 order, fill, ledger, cash-flow, and research schema fragment."""

V1_FINANCIAL_SCHEMA_SQL = """CREATE TABLE IF NOT EXISTS orders (
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

__all__ = ["V1_FINANCIAL_SCHEMA_SQL"]
