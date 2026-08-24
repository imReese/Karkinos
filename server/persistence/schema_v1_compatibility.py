"""Additive compatibility bootstrap for databases predating frozen v1."""

from __future__ import annotations

import sqlite3


def _ensure_column(
    conn: sqlite3.Connection, table_name: str, column_name: str, column_type: str
) -> None:
    """Add a column to an existing SQLite table when it is missing."""
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    if any(row[1] == column_name for row in rows):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def ensure_v1_compatibility_schema(conn: sqlite3.Connection) -> None:
    """Apply the ordered, additive compatibility surface idempotently."""
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


__all__ = ["ensure_v1_compatibility_schema"]
