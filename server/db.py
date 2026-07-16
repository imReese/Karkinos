"""SQLite 持久化 — 信号历史、回测结果、组合快照。"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_DB_DIR = Path("data/store")
_DB_PATH = _DB_DIR / "app.db"
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_MIN_QUOTE_TIMESTAMP = datetime.min.replace(tzinfo=timezone.utc)


def _quote_observation_rank(row: dict[str, Any]) -> tuple[datetime, int]:
    """Order quote observations by instant, never by ISO string spelling."""
    raw = str(row.get("timestamp") or row.get("quote_timestamp") or "").strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        parsed = _MIN_QUOTE_TIMESTAMP
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI_TZ)
    return parsed.astimezone(timezone.utc), int(row.get("id") or 0)


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


def _merge_market_calendar_snapshot_payload(
    payload: dict[str, Any],
    existing: dict[str, Any],
) -> dict[str, Any]:
    """Preserve reviewed holiday labels when refreshing provider snapshots."""
    merged = dict(payload)
    existing_days = _json_list(existing.get("days_json"))
    incoming_days = list(merged.get("days") or [])
    existing_holiday_labels = {
        str(day.get("date")): day
        for day in existing_days
        if isinstance(day, dict)
        and day.get("reason_code") == "market_holiday"
        and not bool(day.get("is_trading_day"))
        and day.get("date")
        and day.get("reason")
    }
    if existing_holiday_labels:
        merged_days: list[dict[str, Any]] = []
        for day in incoming_days:
            if not isinstance(day, dict):
                merged_days.append(day)
                continue
            label = existing_holiday_labels.get(str(day.get("date")))
            if label and not bool(day.get("is_trading_day")):
                merged_days.append(
                    {
                        **day,
                        "day_type": "holiday",
                        "reason_code": "market_holiday",
                        "reason": label["reason"],
                        "is_trading_day": False,
                    }
                )
            else:
                merged_days.append(day)
        merged["days"] = merged_days

    existing_status = str(existing.get("official_verification_status") or "unverified")
    incoming_status = str(merged.get("official_verification_status") or "unverified")
    if existing_status != "unverified" and incoming_status == "unverified":
        merged["official_verification_status"] = existing_status
        merged["official_source_url"] = existing.get("official_source_url")
        merged["official_verified_at"] = existing.get("official_verified_at")
        merged["official_verified_by"] = existing.get("official_verified_by")

    merged["limitations"] = list(
        dict.fromkeys(
            [
                *(merged.get("limitations") or []),
                *_json_list(existing.get("limitations_json")),
            ]
        )
    )
    return merged


def _apply_manual_confirmation_readiness(
    task: dict[str, Any],
    *,
    risk_gate_status: str,
) -> None:
    task["manual_confirmation_required"] = True
    if risk_gate_status == "passed":
        task["manual_confirmation_status"] = "ready_for_manual_confirmation"
        task["manual_confirmation_reason"] = (
            "Risk gate passed; manual confirmation is required before execution."
        )
    elif risk_gate_status == "blocked":
        task["manual_confirmation_status"] = "blocked_by_risk_gate"
        task["manual_confirmation_reason"] = (
            "Risk gate blocked this action; do not execute without review."
        )
    else:
        task["manual_confirmation_status"] = "awaiting_risk_gate"
        task["manual_confirmation_reason"] = (
            "Risk gate has not produced a decision yet."
        )


class AppDatabase:
    """应用数据库。

    后台线程用同步 sqlite3 写入，API 层用 aiosqlite 读取。
    WAL 模式支持并发读写。
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._path = Path(db_path) if db_path else _DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        """初始化数据库表。"""
        self.init_sync()
        logger.info("Database initialized: %s", self._path)

    def init_sync(self) -> None:
        """同步初始化数据库表。"""
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.execute("PRAGMA busy_timeout=2000")
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()
            if journal_mode and str(journal_mode[0]).lower() != "wal":
                conn.execute("PRAGMA journal_mode=WAL")
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
            _ensure_column(
                conn, "ledger_entries", "estimated_fee_breakdown_json", "TEXT"
            )
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
            conn.commit()
        logger.info("Database initialized: %s", self._path)

    # ---------- Market Calendar Snapshots ----------

    def upsert_market_calendar_snapshot_sync(self, snapshot: Any) -> dict[str, Any]:
        """Persist a provider-normalized market calendar snapshot."""
        payload = (
            snapshot.to_payload() if hasattr(snapshot, "to_payload") else dict(snapshot)
        )
        now = datetime.now().isoformat()
        days = payload.get("days") or []
        limitations = payload.get("limitations") or []
        exchange = str(payload["exchange"]).upper()
        year = int(payload["year"])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT *
                FROM market_calendar_snapshots
                WHERE exchange = ? AND year = ?
                LIMIT 1
                """,
                (exchange, year),
            ).fetchone()
            if existing is not None:
                payload = _merge_market_calendar_snapshot_payload(
                    payload,
                    dict(existing),
                )
                days = payload.get("days") or []
                limitations = payload.get("limitations") or []
            conn.execute(
                """
                INSERT INTO market_calendar_snapshots (
                    exchange, year, provider, schema_version, status,
                    trading_day_count, closed_day_count, source_fingerprint,
                    official_verification_status, official_source_url,
                    official_verified_at, official_verified_by, limitations_json,
                    days_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(exchange, year) DO UPDATE SET
                    provider = excluded.provider,
                    schema_version = excluded.schema_version,
                    status = excluded.status,
                    trading_day_count = excluded.trading_day_count,
                    closed_day_count = excluded.closed_day_count,
                    source_fingerprint = excluded.source_fingerprint,
                    official_verification_status = excluded.official_verification_status,
                    official_source_url = excluded.official_source_url,
                    official_verified_at = excluded.official_verified_at,
                    official_verified_by = excluded.official_verified_by,
                    limitations_json = excluded.limitations_json,
                    days_json = excluded.days_json,
                    updated_at = excluded.updated_at
                """,
                (
                    exchange,
                    year,
                    str(payload.get("provider") or "unknown"),
                    str(payload.get("schema_version") or "karkinos.market_calendar.v1"),
                    str(payload.get("status") or "available"),
                    int(payload.get("trading_day_count") or 0),
                    int(payload.get("closed_day_count") or 0),
                    str(payload.get("source_fingerprint") or ""),
                    str(payload.get("official_verification_status") or "unverified"),
                    payload.get("official_source_url"),
                    payload.get("official_verified_at"),
                    payload.get("official_verified_by"),
                    json.dumps(limitations, ensure_ascii=False, sort_keys=True),
                    json.dumps(days, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT *
                FROM market_calendar_snapshots
                WHERE exchange = ? AND year = ?
                LIMIT 1
                """,
                (exchange, year),
            ).fetchone()
            return dict(row)

    def get_market_calendar_snapshot_sync(
        self,
        *,
        exchange: str,
        year: int,
    ) -> dict[str, Any] | None:
        """Fetch the latest stored market calendar snapshot for an exchange/year."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM market_calendar_snapshots
                WHERE exchange = ? AND year = ?
                LIMIT 1
                """,
                (str(exchange).upper(), int(year)),
            ).fetchone()
            return dict(row) if row else None

    def update_market_calendar_verification_sync(
        self,
        *,
        exchange: str,
        year: int,
        verification_status: str,
        official_source_url: str | None = None,
        verified_by: str | None = None,
        review_notes: str | None = None,
        day_labels: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        """Attach manual official-notice verification metadata to a snapshot."""
        row = self.get_market_calendar_snapshot_sync(exchange=exchange, year=year)
        if row is None:
            return None
        now = datetime.now().isoformat()
        limitations = json.loads(row.get("limitations_json") or "[]")
        days = json.loads(row.get("days_json") or "[]")
        normalized_day_labels = {
            str(day).strip()[:10]: str(label).strip()
            for day, label in (day_labels or {}).items()
            if str(day).strip() and str(label).strip()
        }
        if normalized_day_labels:
            days = [
                (
                    {
                        **day,
                        "reason": normalized_day_labels[day.get("date")],
                        "day_type": "holiday",
                        "reason_code": "market_holiday",
                        "is_trading_day": False,
                    }
                    if isinstance(day, dict)
                    and day.get("date") in normalized_day_labels
                    and not bool(day.get("is_trading_day"))
                    else day
                )
                for day in days
            ]
        if review_notes:
            limitations = [*limitations, review_notes]
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                UPDATE market_calendar_snapshots
                SET official_verification_status = ?,
                    official_source_url = ?,
                    official_verified_at = ?,
                    official_verified_by = ?,
                    limitations_json = ?,
                    days_json = ?,
                    updated_at = ?
                WHERE exchange = ? AND year = ?
                """,
                (
                    verification_status,
                    official_source_url,
                    now,
                    verified_by,
                    json.dumps(limitations, ensure_ascii=False, sort_keys=True),
                    json.dumps(days, ensure_ascii=False, sort_keys=True),
                    now,
                    str(exchange).upper(),
                    int(year),
                ),
            )
            conn.commit()
            updated = conn.execute(
                """
                SELECT *
                FROM market_calendar_snapshots
                WHERE exchange = ? AND year = ?
                LIMIT 1
                """,
                (str(exchange).upper(), int(year)),
            ).fetchone()
            return dict(updated) if updated else None

    # ---------- Watchlist Assets ----------

    def upsert_watchlist_asset_sync(
        self,
        *,
        symbol: str,
        asset_class: str = "stock",
        display_name: str | None = None,
        source: str = "manual",
    ) -> dict[str, Any] | None:
        """Upsert a user-tracked asset into the persistent watchlist."""
        clean_symbol = str(symbol).strip()
        clean_asset_class = str(asset_class or "stock").strip().lower() or "stock"
        clean_display_name = str(display_name or clean_symbol).strip() or clean_symbol
        if not clean_symbol:
            return None
        now = datetime.now().isoformat()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO watchlist_assets (
                    symbol, asset_class, display_name, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    asset_class = excluded.asset_class,
                    display_name = excluded.display_name,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    clean_symbol,
                    clean_asset_class,
                    clean_display_name,
                    source,
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT *
                FROM watchlist_assets
                WHERE lower(symbol) = lower(?)
                LIMIT 1
                """,
                (clean_symbol,),
            ).fetchone()
            return dict(row) if row else None

    def list_watchlist_assets_sync(self) -> list[dict[str, Any]]:
        """List persistent watchlist assets in user insertion order."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT *
                FROM watchlist_assets
                ORDER BY created_at ASC, id ASC
                """).fetchall()
            return [dict(row) for row in rows]

    def delete_watchlist_asset_sync(self, symbol: str) -> bool:
        """Remove a user-tracked asset from the persistent watchlist."""
        clean_symbol = str(symbol).strip()
        if not clean_symbol:
            return False
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                "DELETE FROM watchlist_assets WHERE lower(symbol) = lower(?)",
                (clean_symbol,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def seed_watchlist_assets_from_config_sync(self, assets: Any) -> int:
        """Migrate legacy config assets into the persistent watchlist."""
        seeded = 0
        if not assets:
            return seeded
        iterable = assets.items() if isinstance(assets, dict) else enumerate(assets)
        for key, raw_asset in iterable:
            if isinstance(raw_asset, str):
                symbol = str(key if not isinstance(key, int) else raw_asset).strip()
                asset_class = "stock"
                display_name = raw_asset if not isinstance(key, int) else symbol
            elif isinstance(raw_asset, dict):
                symbol = str(
                    raw_asset.get("provider_symbol")
                    or raw_asset.get("provider_code")
                    or raw_asset.get("code")
                    or raw_asset.get("symbol")
                    or ("" if isinstance(key, int) else key)
                ).strip()
                asset_class = str(raw_asset.get("asset_class") or "stock")
                display_name = str(
                    raw_asset.get("display_name")
                    or raw_asset.get("name")
                    or raw_asset.get("symbol")
                    or symbol
                )
            else:
                continue
            if not symbol:
                continue
            if self.upsert_watchlist_asset_sync(
                symbol=symbol,
                asset_class=asset_class,
                display_name=display_name,
                source="config_migration",
            ):
                seeded += 1
        return seeded

    # ---------- Instrument Metadata ----------

    def upsert_instrument_metadata_sync(
        self,
        *,
        symbol: str,
        asset_type: str = "stock",
        display_name: str,
        provider_symbol: str | None = None,
        exchange: str | None = None,
        market: str | None = None,
        provider_name: str | None = None,
        source: str = "provider",
        fetched_at: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> dict[str, Any] | None:
        """Upsert local instrument identity metadata."""
        clean_symbol = str(symbol).strip()
        clean_name = str(display_name).strip()
        if not clean_symbol or not clean_name:
            return None
        now = datetime.now().isoformat()
        fetched_at_value = fetched_at or now
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO instrument_metadata (
                    symbol, asset_type, display_name, provider_symbol, exchange,
                    market, provider_name, source, fetched_at, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, asset_type) DO UPDATE SET
                    display_name = excluded.display_name,
                    provider_symbol = excluded.provider_symbol,
                    exchange = excluded.exchange,
                    market = excluded.market,
                    provider_name = excluded.provider_name,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    clean_symbol,
                    asset_type,
                    clean_name,
                    provider_symbol,
                    exchange,
                    market,
                    provider_name,
                    source,
                    fetched_at_value,
                    _serialize_metadata_json(metadata),
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT *
                FROM instrument_metadata
                WHERE symbol = ? AND asset_type = ?
                """,
                (clean_symbol, asset_type),
            ).fetchone()
            return dict(row) if row else None

    def get_instrument_metadata_sync(
        self, symbol: str, asset_type: str | None = None
    ) -> dict[str, Any] | None:
        """Read local instrument identity metadata."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            if asset_type:
                row = conn.execute(
                    """
                    SELECT *
                    FROM instrument_metadata
                    WHERE symbol = ? AND asset_type = ?
                    LIMIT 1
                    """,
                    (symbol, asset_type),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT *
                    FROM instrument_metadata
                    WHERE symbol = ?
                    ORDER BY fetched_at DESC, updated_at DESC, id DESC
                    LIMIT 1
                    """,
                    (symbol,),
                ).fetchone()
            return dict(row) if row else None

    def list_instrument_metadata_sync(self) -> list[dict[str, Any]]:
        """List local instrument identities newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT *
                FROM instrument_metadata
                ORDER BY fetched_at DESC, updated_at DESC, id DESC
                """).fetchall()
            return [dict(row) for row in rows]

    # ---------- Signals ----------

    def save_signal_sync(
        self,
        timestamp: str,
        strategy_id: str,
        symbol: str,
        direction: str,
        target_weight: float,
        price: float | None,
        asset_class: str,
    ) -> int:
        """同步写入信号（后台线程调用）。"""
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                """INSERT INTO signals
                   (timestamp, strategy_id, symbol, direction, target_weight, price, asset_class)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    timestamp,
                    strategy_id,
                    symbol,
                    direction,
                    target_weight,
                    price,
                    asset_class,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    async def get_signals(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """异步读取信号历史。"""
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM signals ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_latest_signals(self, limit: int = 10) -> list[dict[str, Any]]:
        """获取最新信号。"""
        return await self.get_signals(limit=limit, offset=0)

    async def list_signal_journal(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Async wrapper for the signal journal audit view."""
        return self.list_signal_journal_sync(limit=limit, offset=offset)

    def list_signal_journal_sync(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List signal → action task → risk decision journal entries."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            signal_rows = conn.execute(
                """
                SELECT *
                FROM signals
                ORDER BY timestamp DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            action_rows = conn.execute("""
                SELECT *
                FROM action_tasks
                WHERE source_signal_id IN (
                    SELECT id FROM signals
                )
                ORDER BY updated_at DESC, id DESC
                """).fetchall()
            risk_rows = conn.execute("""
                SELECT *
                FROM risk_decisions
                ORDER BY timestamp DESC, id DESC
                """).fetchall()
            event_rows = conn.execute("""
                SELECT *
                FROM event_log
                WHERE source IN (
                    'action_tasks',
                    'risk_decisions',
                    'manual_orders',
                    'orders',
                    'signal_reviews'
                )
                ORDER BY timestamp DESC, id DESC
                """).fetchall()

        actions_by_signal: dict[int, dict[str, Any]] = {}
        for row in action_rows:
            action = dict(row)
            source_signal_id = action.get("source_signal_id")
            if (
                source_signal_id is not None
                and int(source_signal_id) not in actions_by_signal
            ):
                actions_by_signal[int(source_signal_id)] = action

        risks_by_signal: dict[int, dict[str, Any]] = {}
        for row in risk_rows:
            risk = dict(row)
            payload = _json_dict(risk.get("payload_json"))
            source_signal_id = payload.get("intent", {}).get("source_signal_id")
            if source_signal_id is None:
                continue
            signal_id = int(source_signal_id)
            if signal_id not in risks_by_signal:
                risk["payload"] = payload
                risk["reasons"] = _json_list(risk.get("reasons_json"))
                risk["passed"] = bool(risk.get("passed"))
                risks_by_signal[signal_id] = risk

        latest_events = [_event_log_response(row) for row in event_rows]
        reviews_by_signal: dict[int, dict[str, Any]] = {}
        for event in latest_events:
            if event["source"] != "signal_reviews":
                continue
            payload = event.get("payload", {})
            source_signal_id = payload.get("signal_id")
            if source_signal_id is None:
                continue
            signal_id = int(source_signal_id)
            if signal_id not in reviews_by_signal:
                reviews_by_signal[signal_id] = payload

        entries: list[dict[str, Any]] = []
        for row in signal_rows:
            signal = dict(row)
            signal_id = int(signal["id"])
            action = actions_by_signal.get(signal_id)
            risk = risks_by_signal.get(signal_id)
            entries.append(
                {
                    "signal": signal,
                    "action_task": action,
                    "risk_decision": (
                        _risk_decision_journal_response(risk)
                        if risk is not None
                        else None
                    ),
                    "review": reviews_by_signal.get(signal_id),
                    "latest_event": _latest_signal_journal_event(
                        signal_id=signal_id,
                        action_task=action,
                        risk_decision=risk,
                        events=latest_events,
                    ),
                }
            )
        return entries

    # ---------- Action Tasks ----------

    def upsert_action_task_sync(
        self,
        *,
        source_signal_id: int,
        symbol: str,
        title: str,
        detail: str,
        direction: str,
        urgency: str,
        target_weight: float,
        price: float | None,
        strategy_id: str,
        timestamp: str,
        asset_class: str,
    ) -> None:
        """同步写入或更新待执行任务，避免重复生成。"""
        now = datetime.now().isoformat()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO action_tasks (
                    source_signal_id, symbol, title, detail, direction, urgency,
                    target_weight, price, strategy_id, timestamp, asset_class, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                ON CONFLICT(source_signal_id) DO UPDATE SET
                    symbol = excluded.symbol,
                    title = excluded.title,
                    detail = excluded.detail,
                    direction = excluded.direction,
                    urgency = excluded.urgency,
                    target_weight = excluded.target_weight,
                    price = excluded.price,
                    strategy_id = excluded.strategy_id,
                    timestamp = excluded.timestamp,
                    asset_class = excluded.asset_class,
                    updated_at = excluded.updated_at
                """,
                (
                    source_signal_id,
                    symbol,
                    title,
                    detail,
                    direction,
                    urgency,
                    target_weight,
                    price,
                    strategy_id,
                    timestamp,
                    asset_class,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT id, source_signal_id, symbol, title, detail, direction, urgency,
                       target_weight, price, strategy_id, timestamp, asset_class, status,
                       created_at, updated_at
                FROM action_tasks WHERE source_signal_id = ?
                """,
                (source_signal_id,),
            ).fetchone()
            if row is not None:
                _insert_event_sync(
                    conn,
                    event_type="task.action.created",
                    timestamp=row["timestamp"],
                    entity_type="action_task",
                    entity_id=str(row["id"]),
                    source="action_tasks",
                    source_ref=str(row["id"]),
                    payload=_action_task_event_payload(row),
                )
            conn.commit()

    async def get_action_tasks(
        self, statuses: list[str] | None = None, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        """列出待执行任务。"""
        return self.get_action_tasks_sync(statuses=statuses, limit=limit, offset=offset)

    def get_action_tasks_sync(
        self, statuses: list[str] | None = None, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        """同步版本，避免事件循环中 sqlite 读取挂住。"""
        query = """
            SELECT id, source_signal_id, symbol, title, detail, direction, urgency,
                   target_weight, price, strategy_id, timestamp, asset_class, status,
                   created_at, updated_at
            FROM action_tasks
        """
        params: list[Any] = []
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            query += f" WHERE status IN ({placeholders})"
            params.extend(statuses)
        query += " ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, tuple(params)).fetchall()
            return self._enrich_action_tasks_with_risk_decisions(conn, rows)

    def get_action_task_sync(self, task_id: int) -> dict[str, Any] | None:
        """Read one action task with its latest risk and manual-confirm state."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, source_signal_id, symbol, title, detail, direction, urgency,
                       target_weight, price, strategy_id, timestamp, asset_class, status,
                       created_at, updated_at
                FROM action_tasks WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
            if row is None:
                return None
            tasks = self._enrich_action_tasks_with_risk_decisions(conn, [row])
            return tasks[0] if tasks else None

    def _enrich_action_tasks_with_risk_decisions(
        self, conn: sqlite3.Connection, rows: list[sqlite3.Row]
    ) -> list[dict[str, Any]]:
        """Attach latest risk-gate outcome for each action task's source signal."""
        tasks = [dict(row) for row in rows]
        source_signal_ids = [
            int(task["source_signal_id"])
            for task in tasks
            if task.get("source_signal_id") is not None
        ]
        if not source_signal_ids:
            for task in tasks:
                _apply_manual_confirmation_readiness(
                    task,
                    risk_gate_status="not_checked",
                )
            return tasks

        risk_rows = conn.execute("""
            SELECT *
            FROM risk_decisions
            ORDER BY timestamp DESC, id DESC
            """).fetchall()
        latest_by_signal: dict[int, dict[str, Any]] = {}
        source_signal_id_set = set(source_signal_ids)
        for row in risk_rows:
            risk = dict(row)
            payload = _json_dict(risk.get("payload_json"))
            source_signal_id = payload.get("intent", {}).get("source_signal_id")
            if source_signal_id is None:
                continue
            signal_id = int(source_signal_id)
            if signal_id in source_signal_id_set and signal_id not in latest_by_signal:
                latest_by_signal[signal_id] = risk

        for task in tasks:
            risk = latest_by_signal.get(int(task["source_signal_id"]))
            if risk is None:
                task["risk_decision_id"] = None
                task["risk_gate_passed"] = None
                task["risk_gate_status"] = "not_checked"
                task["risk_gate_severity"] = None
                task["risk_gate_reasons"] = []
                _apply_manual_confirmation_readiness(
                    task,
                    risk_gate_status="not_checked",
                )
                continue
            task["risk_decision_id"] = risk["decision_id"]
            task["risk_gate_passed"] = bool(risk["passed"])
            task["risk_gate_status"] = "passed" if bool(risk["passed"]) else "blocked"
            task["risk_gate_severity"] = risk["severity"]
            task["risk_gate_reasons"] = _json_list(risk.get("reasons_json"))
            _apply_manual_confirmation_readiness(
                task,
                risk_gate_status=task["risk_gate_status"],
            )
        return tasks

    async def update_action_task_status(
        self, task_id: int, status: str
    ) -> dict[str, Any] | None:
        """更新任务状态并返回新值。"""
        return self.update_action_task_status_sync(task_id=task_id, status=status)

    def update_action_task_status_sync(
        self, task_id: int, status: str
    ) -> dict[str, Any] | None:
        """同步版本，供线程池包装。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                "UPDATE action_tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, datetime.now().isoformat(), task_id),
            )
            row = conn.execute(
                """
                SELECT id, source_signal_id, symbol, title, detail, direction, urgency,
                       target_weight, price, strategy_id, timestamp, asset_class, status,
                       created_at, updated_at
                FROM action_tasks WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
            if row is not None:
                _insert_event_sync(
                    conn,
                    event_type="task.action.status_changed",
                    timestamp=datetime.now().isoformat(),
                    entity_type="action_task",
                    entity_id=str(row["id"]),
                    source="action_tasks",
                    source_ref=str(row["id"]),
                    payload=_action_task_event_payload(row),
                )
            conn.commit()
            return dict(row) if row else None

    async def record_signal_review(
        self,
        *,
        signal_id: int,
        reviewed_at: str,
        user_decision: str,
        outcome: str,
        review_notes: str,
        reviewer: str | None = None,
    ) -> dict[str, Any] | None:
        """Async wrapper for a signal review/outcome audit event."""
        return self.record_signal_review_sync(
            signal_id=signal_id,
            reviewed_at=reviewed_at,
            user_decision=user_decision,
            outcome=outcome,
            review_notes=review_notes,
            reviewer=reviewer,
        )

    def record_signal_review_sync(
        self,
        *,
        signal_id: int,
        reviewed_at: str,
        user_decision: str,
        outcome: str,
        review_notes: str,
        reviewer: str | None = None,
    ) -> dict[str, Any] | None:
        """Persist a post-decision signal review as an immutable audit event."""
        payload = {
            "signal_id": signal_id,
            "reviewed_at": reviewed_at,
            "user_decision": user_decision,
            "outcome": outcome,
            "review_notes": review_notes,
            "reviewer": reviewer,
        }
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            signal = conn.execute(
                "SELECT id FROM signals WHERE id = ?",
                (signal_id,),
            ).fetchone()
            if signal is None:
                return None
            cursor = _insert_event_sync(
                conn,
                event_type="signal.review.recorded",
                timestamp=reviewed_at,
                entity_type="signal",
                entity_id=str(signal_id),
                source="signal_reviews",
                source_ref=str(signal_id),
                payload=payload,
            )
            row = conn.execute(
                "SELECT * FROM event_log WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            conn.commit()
            return _event_log_response(row) if row is not None else None

    # ---------- Risk Decisions ----------

    def save_risk_decision_sync(self, *, intent, decision) -> int:
        """同步写入风控决策审计记录。"""
        payload = {
            "intent": {
                "timestamp": intent.timestamp.isoformat(),
                "intent_id": intent.intent_id,
                "strategy_id": intent.strategy_id,
                "symbol": str(intent.symbol),
                "side": intent.side.value,
                "target_weight": str(intent.target_weight),
                "quantity": str(intent.quantity),
                "reference_price": str(intent.reference_price),
                "asset_class": (
                    intent.asset_class.value if intent.asset_class is not None else None
                ),
                "source_signal_id": intent.source_signal_id,
                "reason": intent.reason,
                "metadata": intent.metadata,
            },
            "decision": {
                "timestamp": decision.timestamp.isoformat(),
                "decision_id": decision.decision_id,
                "intent_id": decision.intent_id,
                "passed": decision.passed,
                "symbol": str(decision.symbol),
                "side": decision.side.value,
                "reasons": decision.reasons,
                "resulting_order_id": decision.resulting_order_id,
                "severity": decision.severity,
                "metadata": decision.metadata,
            },
        }
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO risk_decisions
                    (decision_id, intent_id, timestamp, passed, symbol, side,
                     reasons_json, resulting_order_id, severity, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.intent_id,
                    decision.timestamp.isoformat(),
                    1 if decision.passed else 0,
                    str(decision.symbol),
                    decision.side.value,
                    json.dumps(decision.reasons, ensure_ascii=False),
                    decision.resulting_order_id,
                    decision.severity,
                    json.dumps(payload, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            row_id = cursor.lastrowid or 0
            _insert_event_sync(
                conn,
                event_type="risk.signal.recorded",
                timestamp=decision.timestamp.isoformat(),
                entity_type="risk_signal",
                entity_id=decision.decision_id,
                source="risk_decisions",
                source_ref=decision.decision_id,
                payload={
                    "intent": {
                        "timestamp": intent.timestamp.isoformat(),
                        "intent_id": intent.intent_id,
                        "strategy_id": intent.strategy_id,
                        "symbol": str(intent.symbol),
                        "side": intent.side.value,
                        "target_weight": str(intent.target_weight),
                        "quantity": str(intent.quantity),
                        "reference_price": str(intent.reference_price),
                        "reason": intent.reason,
                    },
                    "decision": {
                        "timestamp": decision.timestamp.isoformat(),
                        "decision_id": decision.decision_id,
                        "intent_id": decision.intent_id,
                        "passed": decision.passed,
                        "symbol": str(decision.symbol),
                        "side": decision.side.value,
                        "reasons": decision.reasons,
                        "severity": decision.severity,
                    },
                    "risk_decision_id": row_id,
                },
            )
            conn.commit()
            return row_id

    def get_risk_decisions_sync(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """同步读取风控决策审计记录，最新优先。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM risk_decisions
                ORDER BY timestamp DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            return [dict(row) for row in rows]

    # ---------- Runtime Controls ----------

    def set_runtime_control_sync(self, key: str, value: dict[str, Any]) -> None:
        """Persist runtime control state such as kill switch."""
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """
                INSERT INTO runtime_controls (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (
                    key,
                    json.dumps(value, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

    def get_runtime_control_sync(self, key: str) -> dict[str, Any] | None:
        """Read persisted runtime control state."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT value_json FROM runtime_controls WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            return json.loads(row["value_json"])

    # ---------- Automation Control ----------

    def get_automation_policy_sync(self, policy_id: str) -> dict[str, Any] | None:
        """Read one persisted automation policy by ID."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM automation_policies
                WHERE policy_id = ?
                LIMIT 1
                """,
                (policy_id,),
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(row["payload_json"])
            return {
                **payload,
                "policy_id": row["policy_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "updated_by": row["updated_by"],
            }

    def upsert_automation_policy_sync(
        self,
        *,
        policy_id: str,
        payload: dict[str, Any],
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        """Persist an automation policy snapshot."""
        now = datetime.now().isoformat()
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT created_at
                FROM automation_policies
                WHERE policy_id = ?
                LIMIT 1
                """,
                (policy_id,),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO automation_policies (
                    policy_id, payload_json, created_at, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(policy_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (policy_id, payload_json, created_at, now, updated_by),
            )
            conn.commit()
        saved = self.get_automation_policy_sync(policy_id)
        if saved is None:
            raise RuntimeError("automation policy was not saved")
        return saved

    def upsert_automation_run_sync(self, run: dict[str, Any]) -> dict[str, Any]:
        """Persist or update an automation run audit record."""
        now = datetime.now().isoformat()
        payload = dict(run.get("payload") or {})
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        run_id = str(run["run_id"])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT created_at
                FROM automation_runs
                WHERE run_id = ?
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO automation_runs (
                    run_id, run_type, run_date, status, execution_mode,
                    started_at, finished_at, source_ref, payload_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    run_type = excluded.run_type,
                    run_date = excluded.run_date,
                    status = excluded.status,
                    execution_mode = excluded.execution_mode,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    source_ref = excluded.source_ref,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    run_id,
                    str(run["run_type"]),
                    str(run["run_date"]),
                    str(run["status"]),
                    str(run["execution_mode"]),
                    str(run.get("started_at") or now),
                    run.get("finished_at"),
                    run.get("source_ref"),
                    payload_json,
                    created_at,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM automation_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            conn.commit()
            return dict(row)

    def get_automation_run_sync(self, run_id: str) -> dict[str, Any] | None:
        """Read one automation run audit record."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM automation_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_automation_runs_sync(
        self,
        *,
        run_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List recent automation run audit records."""
        conditions: list[str] = []
        params: list[Any] = []
        if run_type is not None:
            conditions.append("run_type = ?")
            params.append(run_type)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([int(limit), int(offset)])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM automation_runs
                {where_clause}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(row) for row in rows]

    # ---------- OMS Orders ----------

    def get_oms_order_sync(self, order_id: str) -> dict[str, Any] | None:
        """Read one OMS order by its stable order ID."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM oms_orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_oms_order_by_intent_key_sync(
        self, intent_key: str
    ) -> dict[str, Any] | None:
        """Read one OMS order by its idempotency key."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM oms_orders WHERE intent_key = ?",
                (intent_key,),
            ).fetchone()
            return dict(row) if row else None

    def upsert_oms_order_sync(self, order: dict[str, Any]) -> dict[str, Any]:
        """Persist or update an OMS order fact."""
        now = datetime.now().isoformat()
        payload_json = json.dumps(
            order.get("payload") or {},
            ensure_ascii=False,
            sort_keys=True,
        )
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT created_at
                FROM oms_orders
                WHERE order_id = ?
                LIMIT 1
                """,
                (order["order_id"],),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO oms_orders (
                    order_id, intent_key, symbol, side, asset_class, quantity,
                    order_type, limit_price, status, broker_submission_enabled,
                    source, source_ref, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    intent_key = excluded.intent_key,
                    symbol = excluded.symbol,
                    side = excluded.side,
                    asset_class = excluded.asset_class,
                    quantity = excluded.quantity,
                    order_type = excluded.order_type,
                    limit_price = excluded.limit_price,
                    status = excluded.status,
                    broker_submission_enabled = excluded.broker_submission_enabled,
                    source = excluded.source,
                    source_ref = excluded.source_ref,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    order["order_id"],
                    order["intent_key"],
                    order["symbol"],
                    order["side"],
                    order["asset_class"],
                    float(order["quantity"]),
                    order["order_type"],
                    order.get("limit_price"),
                    order["status"],
                    1 if order.get("broker_submission_enabled") else 0,
                    order["source"],
                    order.get("source_ref"),
                    payload_json,
                    created_at,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM oms_orders WHERE order_id = ?",
                (order["order_id"],),
            ).fetchone()
            conn.commit()
            return dict(row)

    def update_oms_order_status_sync(
        self,
        *,
        order_id: str,
        status: str,
    ) -> dict[str, Any]:
        """Update one OMS order status."""
        now = datetime.now().isoformat()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                UPDATE oms_orders
                SET status = ?, updated_at = ?
                WHERE order_id = ?
                """,
                (status, now, order_id),
            )
            row = conn.execute(
                "SELECT * FROM oms_orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            conn.commit()
            if row is None:
                raise KeyError(f"OMS order not found: {order_id}")
            return dict(row)

    def record_oms_transition_sync(
        self,
        *,
        order_id: str,
        from_status: str,
        to_status: str,
        reason: str,
        actor: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record one OMS state transition."""
        now = datetime.now().isoformat()
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """
                INSERT INTO oms_transitions (
                    order_id, from_status, to_status, reason, actor,
                    payload_json, transitioned_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    from_status,
                    to_status,
                    reason,
                    actor,
                    payload_json,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM oms_transitions WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
            conn.commit()
            return dict(row)

    # ---------- Controlled Broker Submit Intents ----------

    def prepare_controlled_broker_submit_intent_sync(
        self,
        *,
        intent: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one one-shot submit intent before any external broker call."""
        requested = dict(intent)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                    SELECT * FROM controlled_broker_submit_intents
                    WHERE submit_intent_id = ? OR order_id = ? OR client_order_id = ?
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (
                        requested["submit_intent_id"],
                        requested["order_id"],
                        requested["client_order_id"],
                    ),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["submit_intent_id"] == requested["submit_intent_id"]
                        and existing["submit_fingerprint"]
                        == requested["submit_fingerprint"]
                        and existing["order_id"] == requested["order_id"]
                        and existing["client_order_id"] == requested["client_order_id"]
                    ):
                        conn.commit()
                        return {
                            "status": str(existing["status"]),
                            "blockers": [],
                            "reused": True,
                            "external_call_permitted": False,
                            "intent": dict(existing),
                        }
                    conn.rollback()
                    return _controlled_broker_submit_rejection(
                        requested,
                        ["controlled_broker_submit_intent_conflict"],
                    )
                unresolved = conn.execute(
                    """
                    SELECT submit_intent_id, order_id, status
                    FROM controlled_broker_submit_intents AS intent
                    WHERE intent.status IN (
                        'prepared', 'submitted', 'submission_unknown'
                    )
                      AND intent.order_id != ?
                      AND NOT EXISTS (
                          SELECT 1
                          FROM controlled_submission_reconciliation_clearances AS clearance
                          WHERE clearance.submit_intent_id = intent.submit_intent_id
                            AND clearance.status = 'cleared'
                      )
                    ORDER BY intent.id ASC
                    LIMIT 1
                    """,
                    (requested["order_id"],),
                ).fetchone()
                lifecycle_invalidated_clearances = (
                    _controlled_lifecycle_invalidated_clearance_rows(
                        conn,
                        exclude_order_id=requested["order_id"],
                        limit=1,
                    )
                )
                order = conn.execute(
                    "SELECT * FROM oms_orders WHERE order_id = ? LIMIT 1",
                    (requested["order_id"],),
                ).fetchone()
                blockers: list[str] = []
                if unresolved is not None:
                    blockers.append(
                        "controlled_broker_submit_unreconciled_intent_exists"
                    )
                if lifecycle_invalidated_clearances:
                    blockers.append(
                        "controlled_broker_submit_lifecycle_clearance_invalidated"
                    )
                if order is None:
                    blockers.append("controlled_broker_submit_order_not_found")
                else:
                    if order["status"] != "manually_confirmed":
                        blockers.append(
                            "controlled_broker_submit_order_not_manually_confirmed"
                        )
                    snapshot = requested["order_snapshot"]
                    for field in ("symbol", "side", "asset_class", "order_type"):
                        if str(order[field] or "") != str(snapshot.get(field) or ""):
                            blockers.append(
                                f"controlled_broker_submit_order_{field}_changed"
                            )
                    if float(order["quantity"]) != float(snapshot.get("quantity")):
                        blockers.append(
                            "controlled_broker_submit_order_quantity_changed"
                        )
                    current_limit = (
                        None
                        if order["limit_price"] is None
                        else float(order["limit_price"])
                    )
                    requested_limit = (
                        None
                        if snapshot.get("limit_price") in {None, ""}
                        else float(snapshot.get("limit_price"))
                    )
                    if current_limit != requested_limit:
                        blockers.append(
                            "controlled_broker_submit_order_limit_price_changed"
                        )
                kill_switch_row = conn.execute(
                    "SELECT value_json FROM runtime_controls WHERE key = 'kill_switch' LIMIT 1"
                ).fetchone()
                if kill_switch_row is not None:
                    kill_switch = _json_dict(kill_switch_row["value_json"])
                    if kill_switch.get("enabled") is True:
                        blockers.append("controlled_broker_submit_kill_switch_enabled")
                if blockers:
                    conn.rollback()
                    return _controlled_broker_submit_rejection(requested, blockers)
                conn.execute(
                    """
                    INSERT INTO controlled_broker_submit_intents (
                        submit_intent_id, submit_fingerprint, order_id,
                        order_fingerprint, confirmation_id, dossier_fingerprint,
                        gateway_id, gateway_verification_fingerprint,
                        release_evidence_id, release_evidence_fingerprint,
                        client_order_id, operator_id, operator_approval_id,
                        status, broker_order_id, broker_status,
                        prepared_at_epoch_ms, prepared_at, last_recovery_at_epoch_ms,
                        last_recovery_at, payload_json, result_json, created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["submit_intent_id"],
                        requested["submit_fingerprint"],
                        requested["order_id"],
                        requested["order_fingerprint"],
                        requested["confirmation_id"],
                        requested["dossier_fingerprint"],
                        requested["gateway_id"],
                        requested["gateway_verification_fingerprint"],
                        requested["release_evidence_id"],
                        requested["release_evidence_fingerprint"],
                        requested["client_order_id"],
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        "prepared",
                        "",
                        "",
                        int(requested["prepared_at_epoch_ms"]),
                        requested["prepared_at"],
                        0,
                        "",
                        _serialize_event_payload_json(requested["payload"]),
                        "{}",
                        requested["created_at"],
                        requested["created_at"],
                    ),
                )
                conn.execute(
                    """
                    UPDATE oms_orders
                    SET status = 'submission_pending', updated_at = ?
                    WHERE order_id = ? AND status = 'manually_confirmed'
                    """,
                    (requested["created_at"], requested["order_id"]),
                )
                conn.execute(
                    """
                    INSERT INTO oms_transitions (
                        order_id, from_status, to_status, reason, actor,
                        payload_json, transitioned_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["order_id"],
                        "manually_confirmed",
                        "submission_pending",
                        "signed controlled broker submit intent prepared",
                        requested["operator_id"],
                        _serialize_event_payload_json(
                            {
                                "submit_intent_id": requested["submit_intent_id"],
                                "submit_fingerprint": requested["submit_fingerprint"],
                                "gateway_id": requested["gateway_id"],
                                "client_order_id": requested["client_order_id"],
                                "one_shot_manual_authority": True,
                                "strategy_direct_submission": False,
                            }
                        ),
                        requested["created_at"],
                        requested["created_at"],
                    ),
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_broker_submit_intents
                    WHERE submit_intent_id = ? LIMIT 1
                    """,
                    (requested["submit_intent_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "prepared",
                    "blockers": [],
                    "reused": False,
                    "external_call_permitted": True,
                    "intent": dict(saved) if saved is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()
                return _controlled_broker_submit_rejection(
                    requested,
                    ["controlled_broker_submit_prepare_transaction_unavailable"],
                )

    def finalize_controlled_broker_submit_intent_sync(
        self,
        *,
        submit_intent_id: str,
        status: str,
        broker_order_id: str,
        broker_status: str,
        result: dict[str, Any],
        actor: str,
        finalized_at_epoch_ms: int,
        finalized_at: str,
        recovered: bool = False,
    ) -> dict[str, Any]:
        """Persist a broker result without ever retrying the external submit call."""
        normalized_status = str(status or "")
        if normalized_status not in {"submitted", "rejected", "submission_unknown"}:
            return _controlled_broker_submit_rejection(
                {"submit_intent_id": submit_intent_id},
                ["controlled_broker_submit_result_status_invalid"],
            )
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                intent = conn.execute(
                    """
                    SELECT * FROM controlled_broker_submit_intents
                    WHERE submit_intent_id = ? LIMIT 1
                    """,
                    (submit_intent_id,),
                ).fetchone()
                if intent is None:
                    conn.rollback()
                    return _controlled_broker_submit_rejection(
                        {"submit_intent_id": submit_intent_id},
                        ["controlled_broker_submit_intent_not_found"],
                    )
                current_status = str(intent["status"])
                if current_status in {"submitted", "rejected"}:
                    if current_status != normalized_status:
                        conn.rollback()
                        return _controlled_broker_submit_rejection(
                            dict(intent),
                            ["controlled_broker_submit_terminal_result_conflict"],
                        )
                    conn.commit()
                    return {
                        "status": current_status,
                        "blockers": [],
                        "reused": True,
                        "intent": dict(intent),
                    }
                if current_status not in {"prepared", "submission_unknown"}:
                    conn.rollback()
                    return _controlled_broker_submit_rejection(
                        dict(intent),
                        ["controlled_broker_submit_state_invalid"],
                    )
                order = conn.execute(
                    "SELECT * FROM oms_orders WHERE order_id = ? LIMIT 1",
                    (intent["order_id"],),
                ).fetchone()
                expected_order_statuses = {"submission_pending", "submission_unknown"}
                if order is None or str(order["status"]) not in expected_order_statuses:
                    conn.rollback()
                    return _controlled_broker_submit_rejection(
                        dict(intent),
                        ["controlled_broker_submit_oms_state_changed"],
                    )
                from_status = str(order["status"])
                conn.execute(
                    """
                    UPDATE controlled_broker_submit_intents
                    SET status = ?, broker_order_id = ?, broker_status = ?,
                        result_json = ?, last_recovery_at_epoch_ms = ?,
                        last_recovery_at = ?, updated_at = ?
                    WHERE submit_intent_id = ?
                    """,
                    (
                        normalized_status,
                        broker_order_id,
                        broker_status,
                        _serialize_event_payload_json(result),
                        int(finalized_at_epoch_ms) if recovered else 0,
                        finalized_at if recovered else "",
                        finalized_at,
                        submit_intent_id,
                    ),
                )
                if from_status != normalized_status:
                    conn.execute(
                        "UPDATE oms_orders SET status = ?, updated_at = ? WHERE order_id = ?",
                        (normalized_status, finalized_at, intent["order_id"]),
                    )
                    conn.execute(
                        """
                        INSERT INTO oms_transitions (
                            order_id, from_status, to_status, reason, actor,
                            payload_json, transitioned_at, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            intent["order_id"],
                            from_status,
                            normalized_status,
                            (
                                "controlled broker submission recovered by query"
                                if recovered
                                else "controlled broker submission result recorded"
                            ),
                            actor,
                            _serialize_event_payload_json(
                                {
                                    "submit_intent_id": submit_intent_id,
                                    "gateway_id": intent["gateway_id"],
                                    "client_order_id": intent["client_order_id"],
                                    "broker_order_id": broker_order_id,
                                    "broker_status": broker_status,
                                    "recovered": recovered,
                                    "production_ledger_mutated": False,
                                }
                            ),
                            finalized_at,
                            finalized_at,
                        ),
                    )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_broker_submit_intents
                    WHERE submit_intent_id = ? LIMIT 1
                    """,
                    (submit_intent_id,),
                ).fetchone()
                conn.commit()
                return {
                    "status": normalized_status,
                    "blockers": [],
                    "reused": False,
                    "intent": dict(saved) if saved is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()
                return _controlled_broker_submit_rejection(
                    {"submit_intent_id": submit_intent_id},
                    ["controlled_broker_submit_finalize_transaction_unavailable"],
                )

    def get_controlled_broker_submit_intent_sync(
        self,
        submit_intent_id: str,
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_broker_submit_intents
                WHERE submit_intent_id = ? LIMIT 1
                """,
                (submit_intent_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_controlled_broker_submit_intent_for_order_sync(
        self,
        order_id: str,
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_broker_submit_intents
                WHERE order_id = ? LIMIT 1
                """,
                (order_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_broker_submit_intents_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_broker_submit_intents
                ORDER BY prepared_at_epoch_ms DESC, id DESC LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_unreconciled_controlled_broker_submit_intents_sync(
        self,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """List controlled intents that still block every different order."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT intent.*
                FROM controlled_broker_submit_intents AS intent
                WHERE intent.status IN (
                    'prepared', 'submitted', 'submission_unknown'
                )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM controlled_submission_reconciliation_clearances AS clearance
                      WHERE clearance.submit_intent_id = intent.submit_intent_id
                        AND clearance.status = 'cleared'
                  )
                ORDER BY intent.prepared_at_epoch_ms ASC, intent.id ASC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            unresolved = [dict(row) for row in rows]
            known_ids = {str(row.get("submit_intent_id") or "") for row in unresolved}
            for row in _controlled_lifecycle_invalidated_clearance_rows(
                conn,
                limit=max(1, min(int(limit), 500)),
            ):
                if str(row.get("submit_intent_id") or "") not in known_ids:
                    unresolved.append(row)
            unresolved.sort(
                key=lambda row: (
                    int(row.get("prepared_at_epoch_ms") or 0),
                    int(row.get("id") or 0),
                )
            )
            return unresolved[: max(1, min(int(limit), 500))]

    def get_controlled_submission_reconciliation_clearance_sync(
        self,
        clearance_id: str,
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM controlled_submission_reconciliation_clearances
                WHERE clearance_id = ? LIMIT 1
                """,
                (clearance_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_controlled_submission_reconciliation_clearance_for_intent_sync(
        self,
        submit_intent_id: str,
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM controlled_submission_reconciliation_clearances
                WHERE submit_intent_id = ? LIMIT 1
                """,
                (submit_intent_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_submission_reconciliation_clearances_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM controlled_submission_reconciliation_clearances
                ORDER BY cleared_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_controlled_submission_ledger_posting_sync(
        self,
        posting_id: str,
    ) -> dict[str, Any] | None:
        """Read one immutable controlled-order ledger posting."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_submission_ledger_postings
                WHERE posting_id = ? LIMIT 1
                """,
                (posting_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_account_truth_review_identity_sync(
        self,
        import_run_id: str,
    ) -> dict[str, Any]:
        """Fingerprint current manual-review decisions for one broker import."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            return _account_truth_review_identity_from_connection(
                conn,
                import_run_id=import_run_id,
            )

    def get_controlled_submission_ledger_posting_for_clearance_sync(
        self,
        clearance_id: str,
    ) -> dict[str, Any] | None:
        """Read the exactly-once posting associated with one clearance."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_submission_ledger_postings
                WHERE clearance_id = ? LIMIT 1
                """,
                (clearance_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_submission_ledger_postings_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable controlled-order ledger postings, newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_submission_ledger_postings
                ORDER BY applied_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_controlled_submission_ledger_correction_sync(
        self,
        correction_id: str,
    ) -> dict[str, Any] | None:
        """Read one immutable compensating correction."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_submission_ledger_corrections
                WHERE correction_id = ? LIMIT 1
                """,
                (correction_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_controlled_submission_ledger_correction_for_posting_sync(
        self,
        posting_id: str,
    ) -> dict[str, Any] | None:
        """Read the exactly-once correction associated with one posting."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_submission_ledger_corrections
                WHERE posting_id = ? LIMIT 1
                """,
                (posting_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_submission_ledger_corrections_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable compensating corrections, newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_submission_ledger_corrections
                ORDER BY applied_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def record_controlled_submission_ledger_correction_sync(
        self,
        *,
        correction: dict[str, Any],
    ) -> dict[str, Any]:
        """Re-derive and atomically append one exact correction event."""
        from server.services.controlled_submission_ledger_correction import (
            CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ENTRY_TYPE,
            CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE,
            build_controlled_ledger_correction_plan,
            correction_plan_fingerprint,
        )
        from server.services.valuation_snapshot import (
            build_current_valuation_snapshot,
            ledger_identity_from_rows,
        )

        requested = dict(correction)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                    SELECT * FROM controlled_submission_ledger_corrections
                    WHERE correction_id = ? OR posting_id = ?
                    ORDER BY id ASC LIMIT 1
                    """,
                    (requested["correction_id"], requested["posting_id"]),
                ).fetchone()
                if existing is not None:
                    if (
                        str(existing["correction_id"]) == requested["correction_id"]
                        and str(existing["correction_fingerprint"])
                        == requested["correction_fingerprint"]
                        and str(existing["posting_id"]) == requested["posting_id"]
                    ):
                        conn.commit()
                        return {
                            "status": "applied",
                            "blockers": [],
                            "reused": True,
                            "correction": dict(existing),
                        }
                    conn.rollback()
                    return _controlled_submission_ledger_correction_rejection(
                        requested,
                        ["controlled_ledger_correction_conflict"],
                    )

                posting = conn.execute(
                    """
                    SELECT * FROM controlled_submission_ledger_postings
                    WHERE posting_id = ? LIMIT 1
                    """,
                    (requested["posting_id"],),
                ).fetchone()
                blockers: list[str] = []
                if posting is None:
                    blockers.append("controlled_ledger_correction_posting_missing")
                else:
                    if str(posting["status"]) != "applied":
                        blockers.append("controlled_ledger_correction_posting_changed")
                    if (
                        str(posting["posting_fingerprint"])
                        != requested["posting_fingerprint"]
                    ):
                        blockers.append(
                            "controlled_ledger_correction_posting_fingerprint_changed"
                        )
                    posting_entry_ids = sorted(
                        int(item)
                        for item in _json_list(posting["ledger_entry_ids_json"])
                    )
                    if posting_entry_ids != sorted(
                        int(item) for item in requested["original_ledger_entry_ids"]
                    ):
                        blockers.append(
                            "controlled_ledger_correction_original_entry_ids_changed"
                        )
                    posting_fields = {
                        "account_truth_import_run_id": "account_truth_import_run_id",
                        "account_truth_file_fingerprint": (
                            "account_truth_file_fingerprint"
                        ),
                        "account_truth_source_fingerprint": (
                            "account_truth_source_fingerprint"
                        ),
                        "account_truth_review_fingerprint": (
                            "account_truth_review_fingerprint"
                        ),
                    }
                    for request_field, posting_field in posting_fields.items():
                        if str(requested.get(request_field) or "") != str(
                            posting[posting_field] or ""
                        ):
                            blockers.append(
                                f"controlled_ledger_correction_{request_field}_changed"
                            )

                import_row = conn.execute(
                    """
                    SELECT * FROM broker_import_runs
                    WHERE import_run_id = ? LIMIT 1
                    """,
                    (requested["account_truth_import_run_id"],),
                ).fetchone()
                if import_row is None:
                    blockers.append("controlled_ledger_correction_import_missing")
                else:
                    if str(import_row["validation_status"]) != "pass":
                        blockers.append("controlled_ledger_correction_import_not_pass")
                    if (
                        str(import_row["file_fingerprint"])
                        != requested["account_truth_file_fingerprint"]
                    ):
                        blockers.append(
                            "controlled_ledger_correction_import_fingerprint_changed"
                        )
                review_identity = _account_truth_review_identity_from_connection(
                    conn,
                    import_run_id=requested["account_truth_import_run_id"],
                )
                if (
                    review_identity["fingerprint"]
                    != requested["account_truth_review_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_correction_account_truth_review_changed"
                    )

                ledger_rows = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM ledger_entries ORDER BY id ASC"
                    ).fetchall()
                ]
                ledger_identity = ledger_identity_from_rows(ledger_rows)
                if int(ledger_identity["ledger_cutoff_id"]) != int(
                    requested["pre_ledger_cutoff_id"]
                ):
                    blockers.append(
                        "controlled_ledger_correction_pre_ledger_cutoff_changed"
                    )
                if (
                    str(ledger_identity["ledger_fingerprint"])
                    != requested["pre_ledger_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_correction_pre_ledger_fingerprint_changed"
                    )
                current_valuation = build_current_valuation_snapshot(
                    self,
                    persist=False,
                )
                valuation_fields = (
                    "snapshot_id",
                    "as_of",
                    "status",
                    "ledger_cutoff_id",
                    "ledger_fingerprint",
                )
                request_fields = {
                    "snapshot_id": "pre_valuation_snapshot_id",
                    "as_of": "pre_valuation_as_of",
                    "status": "pre_valuation_status",
                    "ledger_cutoff_id": "pre_ledger_cutoff_id",
                    "ledger_fingerprint": "pre_ledger_fingerprint",
                }
                for valuation_field in valuation_fields:
                    request_field = request_fields[valuation_field]
                    if str(current_valuation.get(valuation_field) or "") != str(
                        requested.get(request_field) or ""
                    ):
                        blockers.append(
                            "controlled_ledger_correction_pre_valuation_"
                            f"{valuation_field}_changed"
                        )

                original_ids = sorted(
                    int(item) for item in requested["original_ledger_entry_ids"]
                )
                original_rows = [
                    row
                    for row in ledger_rows
                    if int(row.get("id") or 0) in set(original_ids)
                ]
                if len(original_rows) != len(original_ids):
                    blockers.append(
                        "controlled_ledger_correction_original_entry_missing"
                    )
                if (
                    _stable_json_fingerprint(original_rows)
                    != requested["original_ledger_entry_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_correction_original_entry_changed"
                    )
                try:
                    derived_plan = build_controlled_ledger_correction_plan(
                        ledger_rows=ledger_rows,
                        original_entry_ids=original_ids,
                        posting_id=requested["posting_id"],
                    )
                except ValueError as exc:
                    blockers.append(str(exc))
                    derived_plan = {}
                if derived_plan != requested.get("correction_plan"):
                    blockers.append("controlled_ledger_correction_plan_changed")
                if (
                    correction_plan_fingerprint(derived_plan)
                    != requested["plan_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_correction_plan_fingerprint_changed"
                    )
                if blockers:
                    conn.rollback()
                    return _controlled_submission_ledger_correction_rejection(
                        requested,
                        blockers,
                    )

                before = derived_plan["position_before"]
                after = derived_plan["position_after"]
                quantity_delta = Decimal(after["quantity"]) - Decimal(
                    before["quantity"]
                )
                correction_payload_json = _serialize_event_payload_json(derived_plan)
                cursor = conn.execute(
                    """
                    INSERT INTO ledger_entries (
                        entry_type, timestamp, amount, symbol, direction,
                        quantity, price, commission, correction_payload_json,
                        asset_class, note, source, source_ref, created_at
                    ) VALUES (?, ?, ?, ?, NULL, ?, NULL, 0, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ENTRY_TYPE,
                        _normalize_timestamp(derived_plan["effective_at"]),
                        float(Decimal(derived_plan["cash_delta"])),
                        derived_plan["symbol"],
                        float(quantity_delta),
                        correction_payload_json,
                        derived_plan["asset_class"],
                        (
                            "Append-only correction derived from canonical replay; "
                            f"original posting {requested['posting_id']}."
                        ),
                        CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE,
                        requested["correction_id"],
                        requested["applied_at"],
                    ),
                )
                correction_entry_id = int(cursor.lastrowid or 0)
                stored_payload = dict(requested.get("payload") or {})
                stored_payload.update(
                    {
                        "correction_ledger_entry_id": correction_entry_id,
                        "post_ledger_cutoff_id": correction_entry_id,
                    }
                )
                _insert_event_sync(
                    conn,
                    event_type="portfolio.ledger_entry.recorded",
                    timestamp=_normalize_timestamp(derived_plan["effective_at"]),
                    entity_type="portfolio",
                    entity_id="default",
                    source="ledger_entries",
                    source_ref=str(correction_entry_id),
                    payload={
                        "entry_id": correction_entry_id,
                        "entry_type": CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ENTRY_TYPE,
                        "timestamp": _normalize_timestamp(derived_plan["effective_at"]),
                        "symbol": derived_plan["symbol"],
                        "source": CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE,
                        "source_ref": requested["correction_id"],
                        "correction_plan": derived_plan,
                    },
                )
                conn.execute(
                    """
                    INSERT INTO controlled_submission_ledger_corrections (
                        correction_id, correction_fingerprint, posting_id,
                        posting_fingerprint, original_ledger_entry_ids_json,
                        original_ledger_entry_fingerprint, reason_code,
                        account_truth_import_run_id,
                        account_truth_file_fingerprint,
                        account_truth_source_fingerprint,
                        account_truth_review_fingerprint,
                        pre_valuation_snapshot_id, pre_valuation_as_of,
                        pre_valuation_status, pre_ledger_cutoff_id,
                        pre_ledger_fingerprint, plan_fingerprint, operator_id,
                        operator_approval_id, status,
                        correction_ledger_entry_id, post_ledger_cutoff_id,
                        applied_at_epoch_ms, applied_at, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["correction_id"],
                        requested["correction_fingerprint"],
                        requested["posting_id"],
                        requested["posting_fingerprint"],
                        _serialize_event_payload_json(original_ids),
                        requested["original_ledger_entry_fingerprint"],
                        requested["reason_code"],
                        requested["account_truth_import_run_id"],
                        requested["account_truth_file_fingerprint"],
                        requested["account_truth_source_fingerprint"],
                        requested["account_truth_review_fingerprint"],
                        requested["pre_valuation_snapshot_id"],
                        requested["pre_valuation_as_of"],
                        requested["pre_valuation_status"],
                        int(requested["pre_ledger_cutoff_id"]),
                        requested["pre_ledger_fingerprint"],
                        requested["plan_fingerprint"],
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        correction_entry_id,
                        correction_entry_id,
                        int(requested["applied_at_epoch_ms"]),
                        requested["applied_at"],
                        _serialize_event_payload_json(stored_payload),
                        requested["applied_at"],
                    ),
                )
                _insert_event_sync(
                    conn,
                    event_type="controlled_broker.ledger_corrected",
                    timestamp=requested["applied_at"],
                    entity_type="controlled_submission_ledger_correction",
                    entity_id=requested["correction_id"],
                    source=CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE,
                    source_ref=requested["posting_id"],
                    payload=stored_payload,
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_submission_ledger_corrections
                    WHERE correction_id = ? LIMIT 1
                    """,
                    (requested["correction_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "applied",
                    "blockers": [],
                    "reused": False,
                    "correction": dict(saved) if saved is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
                ArithmeticError,
            ):
                conn.rollback()
                return _controlled_submission_ledger_correction_rejection(
                    requested,
                    ["controlled_ledger_correction_transaction_unavailable"],
                )

    def record_controlled_submission_ledger_posting_sync(
        self,
        *,
        posting: dict[str, Any],
    ) -> dict[str, Any]:
        """Verify and atomically post exact cleared fills to the ledger once."""
        requested = dict(posting)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                    SELECT * FROM controlled_submission_ledger_postings
                    WHERE posting_id = ? OR clearance_id = ?
                       OR submit_intent_id = ? OR order_id = ?
                    ORDER BY id ASC LIMIT 1
                    """,
                    (
                        requested["posting_id"],
                        requested["clearance_id"],
                        requested["submit_intent_id"],
                        requested["order_id"],
                    ),
                ).fetchone()
                if existing is not None:
                    if (
                        str(existing["posting_id"]) == requested["posting_id"]
                        and str(existing["posting_fingerprint"])
                        == requested["posting_fingerprint"]
                        and str(existing["clearance_id"]) == requested["clearance_id"]
                    ):
                        conn.commit()
                        return {
                            "status": "applied",
                            "blockers": [],
                            "reused": True,
                            "posting": dict(existing),
                        }
                    conn.rollback()
                    return _controlled_submission_ledger_posting_rejection(
                        requested,
                        ["controlled_ledger_posting_conflict"],
                    )

                clearance = conn.execute(
                    """
                    SELECT * FROM controlled_submission_reconciliation_clearances
                    WHERE clearance_id = ? LIMIT 1
                    """,
                    (requested["clearance_id"],),
                ).fetchone()
                intent = conn.execute(
                    """
                    SELECT * FROM controlled_broker_submit_intents
                    WHERE submit_intent_id = ? LIMIT 1
                    """,
                    (requested["submit_intent_id"],),
                ).fetchone()
                order = conn.execute(
                    "SELECT * FROM oms_orders WHERE order_id = ? LIMIT 1",
                    (requested["order_id"],),
                ).fetchone()
                latest_item = conn.execute(
                    """
                    SELECT * FROM execution_reconciliation_items
                    WHERE order_id = ? ORDER BY id DESC LIMIT 1
                    """,
                    (requested["order_id"],),
                ).fetchone()
                blockers: list[str] = []
                if clearance is None:
                    blockers.append("controlled_ledger_posting_clearance_missing")
                else:
                    clearance_fields = {
                        "clearance_fingerprint": "clearance_fingerprint",
                        "submit_intent_id": "submit_intent_id",
                        "order_id": "order_id",
                        "broker_order_id": "broker_order_id",
                        "terminal_status": "terminal_status",
                        "clearance_reconciliation_run_id": (
                            "clearance_reconciliation_run_id"
                        ),
                        "broker_evidence_fingerprint": ("broker_evidence_fingerprint"),
                        "account_truth_import_run_id": ("account_truth_import_run_id"),
                        "account_truth_file_fingerprint": (
                            "account_truth_file_fingerprint"
                        ),
                        "account_truth_source_fingerprint": (
                            "account_truth_source_fingerprint"
                        ),
                        "lifecycle_observation_id": "lifecycle_observation_id",
                        "lifecycle_evidence_fingerprint": (
                            "lifecycle_evidence_fingerprint"
                        ),
                        "lifecycle_source_sequence": "lifecycle_source_sequence",
                        "operator_id": "operator_id",
                    }
                    for request_field, clearance_field in clearance_fields.items():
                        if str(requested.get(request_field) or "") != str(
                            clearance[clearance_field] or ""
                        ):
                            blockers.append(
                                "controlled_ledger_posting_clearance_"
                                f"{request_field}_changed"
                            )
                    if str(clearance["status"]) != "cleared":
                        blockers.append(
                            "controlled_ledger_posting_clearance_not_cleared"
                        )
                if intent is None:
                    blockers.append("controlled_ledger_posting_intent_missing")
                else:
                    if str(intent["status"]) != "submitted":
                        blockers.append("controlled_ledger_posting_intent_changed")
                    if str(intent["order_id"]) != requested["order_id"]:
                        blockers.append(
                            "controlled_ledger_posting_intent_order_changed"
                        )
                    if str(intent["broker_order_id"]) != requested["broker_order_id"]:
                        blockers.append(
                            "controlled_ledger_posting_intent_broker_order_changed"
                        )
                    if str(intent["client_order_id"]) != requested["client_order_id"]:
                        blockers.append(
                            "controlled_ledger_posting_intent_client_order_changed"
                        )
                if order is None:
                    blockers.append("controlled_ledger_posting_order_missing")
                elif str(order["status"]) != requested["terminal_status"]:
                    blockers.append("controlled_ledger_posting_order_status_changed")
                if latest_item is None:
                    blockers.append("controlled_ledger_posting_reconciliation_missing")
                else:
                    if (
                        str(latest_item["run_id"])
                        != requested["clearance_reconciliation_run_id"]
                    ):
                        blockers.append(
                            "controlled_ledger_posting_reconciliation_superseded"
                        )
                    if str(latest_item["item_status"]) != (
                        "controlled_submission_reconciliation_cleared"
                    ):
                        blockers.append(
                            "controlled_ledger_posting_reconciliation_changed"
                        )

                invalidated = _controlled_lifecycle_invalidated_clearance_rows(conn)
                if any(
                    str(item.get("order_id") or "") == requested["order_id"]
                    for item in invalidated
                ):
                    blockers.append(
                        "controlled_ledger_posting_lifecycle_clearance_invalidated"
                    )

                import_row = conn.execute(
                    """
                    SELECT * FROM broker_import_runs
                    WHERE import_run_id = ? LIMIT 1
                    """,
                    (requested["account_truth_import_run_id"],),
                ).fetchone()
                if import_row is None:
                    blockers.append("controlled_ledger_posting_import_missing")
                else:
                    if str(import_row["validation_status"]) != "pass":
                        blockers.append("controlled_ledger_posting_import_not_pass")
                    if (
                        str(import_row["file_fingerprint"])
                        != requested["account_truth_file_fingerprint"]
                    ):
                        blockers.append(
                            "controlled_ledger_posting_import_fingerprint_changed"
                        )
                review_identity = _account_truth_review_identity_from_connection(
                    conn,
                    import_run_id=requested["account_truth_import_run_id"],
                )
                if (
                    review_identity["fingerprint"]
                    != requested["account_truth_review_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_posting_account_truth_review_changed"
                    )

                from server.services.valuation_snapshot import (
                    ledger_identity_from_rows,
                )

                ledger_rows = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM ledger_entries ORDER BY id ASC"
                    ).fetchall()
                ]
                ledger_identity = ledger_identity_from_rows(ledger_rows)
                if int(ledger_identity["ledger_cutoff_id"]) != int(
                    requested["pre_ledger_cutoff_id"]
                ):
                    blockers.append(
                        "controlled_ledger_posting_pre_ledger_cutoff_changed"
                    )
                if (
                    str(ledger_identity["ledger_fingerprint"])
                    != requested["pre_ledger_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_posting_pre_ledger_fingerprint_changed"
                    )

                entries = requested.get("ledger_entries")
                entries = entries if isinstance(entries, list) else []
                if len(entries) != int(requested["ledger_entry_count"]):
                    blockers.append("controlled_ledger_posting_entry_count_changed")
                if (
                    _stable_json_fingerprint(entries)
                    != requested["ledger_entry_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_posting_entry_fingerprint_changed"
                    )
                clearance_fill_count = (
                    int(clearance["fill_count"]) if clearance is not None else -1
                )
                if len(entries) != clearance_fill_count:
                    blockers.append("controlled_ledger_posting_clearance_fill_changed")
                if requested["terminal_status"] == "filled" and not entries:
                    blockers.append("controlled_ledger_posting_filled_without_entries")

                verified_entries: list[dict[str, Any]] = []
                for entry in entries:
                    if not isinstance(entry, dict):
                        blockers.append("controlled_ledger_posting_entry_invalid")
                        continue
                    entry_blockers = _verify_controlled_ledger_entry(
                        conn,
                        entry=entry,
                        request=requested,
                    )
                    blockers.extend(entry_blockers)
                    verified_entries.append(entry)
                if blockers:
                    conn.rollback()
                    return _controlled_submission_ledger_posting_rejection(
                        requested,
                        blockers,
                    )

                ledger_entry_ids: list[int] = []
                for entry in verified_entries:
                    normalized_timestamp = _normalize_timestamp(entry["timestamp"])
                    cursor = conn.execute(
                        """
                        INSERT INTO ledger_entries (
                            entry_type, timestamp, amount, symbol, direction,
                            quantity, price, commission, gross_amount,
                            net_cash_impact, fee_breakdown_json, fee_rule_id,
                            fee_rule_version, settlement_status, settled_at,
                            settlement_source, settlement_source_ref,
                            settlement_note, cost_basis_method, asset_class,
                            note, source, source_ref, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            entry["entry_type"],
                            normalized_timestamp,
                            float(Decimal(entry["amount"])),
                            entry["symbol"],
                            entry["direction"],
                            float(Decimal(entry["quantity"])),
                            float(Decimal(entry["price"])),
                            float(Decimal(entry["commission"])),
                            float(Decimal(entry["gross_amount"])),
                            float(Decimal(entry["net_cash_impact"])),
                            _serialize_metadata_json(entry["fee_breakdown"]),
                            entry["fee_rule_id"],
                            entry["fee_rule_version"],
                            entry["settlement_status"],
                            _normalize_timestamp(entry["settled_at"]),
                            entry["settlement_source"],
                            entry["settlement_source_ref"],
                            entry["settlement_note"],
                            entry["cost_basis_method"],
                            entry["asset_class"],
                            entry["note"],
                            entry["source"],
                            entry["source_ref"],
                            requested["applied_at"],
                        ),
                    )
                    entry_id = int(cursor.lastrowid or 0)
                    ledger_entry_ids.append(entry_id)
                    _insert_event_sync(
                        conn,
                        event_type="portfolio.ledger_entry.recorded",
                        timestamp=normalized_timestamp,
                        entity_type="portfolio",
                        entity_id="default",
                        source="ledger_entries",
                        source_ref=str(entry_id),
                        payload={"entry_id": entry_id, **entry},
                    )

                post_cutoff_id = (
                    ledger_entry_ids[-1]
                    if ledger_entry_ids
                    else int(requested["pre_ledger_cutoff_id"])
                )
                stored_payload = dict(requested.get("payload") or {})
                stored_payload.update(
                    {
                        "ledger_entry_ids": ledger_entry_ids,
                        "post_ledger_cutoff_id": post_cutoff_id,
                    }
                )
                conn.execute(
                    """
                    INSERT INTO controlled_submission_ledger_postings (
                        posting_id, posting_fingerprint, clearance_id,
                        clearance_fingerprint, submit_intent_id, order_id,
                        broker_order_id, client_order_id, terminal_status,
                        clearance_reconciliation_run_id,
                        broker_evidence_fingerprint,
                        account_truth_import_run_id,
                        account_truth_file_fingerprint,
                        account_truth_source_fingerprint,
                        account_truth_review_fingerprint,
                        lifecycle_observation_id,
                        lifecycle_evidence_fingerprint,
                        lifecycle_source_sequence, pre_valuation_snapshot_id,
                        pre_valuation_as_of, pre_valuation_status,
                        pre_ledger_cutoff_id, pre_ledger_fingerprint,
                        operator_id, operator_approval_id, status,
                        ledger_entry_count, ledger_entry_fingerprint,
                        ledger_entry_ids_json, post_ledger_cutoff_id,
                        applied_at_epoch_ms, applied_at, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["posting_id"],
                        requested["posting_fingerprint"],
                        requested["clearance_id"],
                        requested["clearance_fingerprint"],
                        requested["submit_intent_id"],
                        requested["order_id"],
                        requested["broker_order_id"],
                        requested["client_order_id"],
                        requested["terminal_status"],
                        requested["clearance_reconciliation_run_id"],
                        requested["broker_evidence_fingerprint"],
                        requested["account_truth_import_run_id"],
                        requested["account_truth_file_fingerprint"],
                        requested["account_truth_source_fingerprint"],
                        requested["account_truth_review_fingerprint"],
                        requested["lifecycle_observation_id"],
                        requested["lifecycle_evidence_fingerprint"],
                        int(requested["lifecycle_source_sequence"]),
                        requested["pre_valuation_snapshot_id"],
                        requested["pre_valuation_as_of"],
                        requested["pre_valuation_status"],
                        int(requested["pre_ledger_cutoff_id"]),
                        requested["pre_ledger_fingerprint"],
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        len(ledger_entry_ids),
                        requested["ledger_entry_fingerprint"],
                        _serialize_event_payload_json(ledger_entry_ids),
                        post_cutoff_id,
                        int(requested["applied_at_epoch_ms"]),
                        requested["applied_at"],
                        _serialize_event_payload_json(stored_payload),
                        requested["applied_at"],
                    ),
                )
                _insert_event_sync(
                    conn,
                    event_type="controlled_broker.ledger_posted",
                    timestamp=requested["applied_at"],
                    entity_type="controlled_submission_ledger_posting",
                    entity_id=requested["posting_id"],
                    source="controlled_submission_ledger_posting",
                    source_ref=requested["clearance_id"],
                    payload=stored_payload,
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_submission_ledger_postings
                    WHERE posting_id = ? LIMIT 1
                    """,
                    (requested["posting_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "applied",
                    "blockers": [],
                    "reused": False,
                    "posting": dict(saved) if saved is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
                ArithmeticError,
            ):
                conn.rollback()
                return _controlled_submission_ledger_posting_rejection(
                    requested,
                    ["controlled_ledger_posting_transaction_unavailable"],
                )

    def record_controlled_submission_reconciliation_clearance_sync(
        self,
        *,
        clearance: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically record real fills, terminal OMS state, and clearance."""
        requested = dict(clearance)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                    SELECT *
                    FROM controlled_submission_reconciliation_clearances
                    WHERE clearance_id = ? OR submit_intent_id = ? OR order_id = ?
                    ORDER BY id ASC LIMIT 1
                    """,
                    (
                        requested["clearance_id"],
                        requested["submit_intent_id"],
                        requested["order_id"],
                    ),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["clearance_id"] == requested["clearance_id"]
                        and existing["clearance_fingerprint"]
                        == requested["clearance_fingerprint"]
                        and existing["submit_intent_id"]
                        == requested["submit_intent_id"]
                    ):
                        conn.commit()
                        return {
                            "status": "cleared",
                            "blockers": [],
                            "reused": True,
                            "clearance": dict(existing),
                        }
                    conn.rollback()
                    return _controlled_submission_clearance_rejection(
                        requested,
                        ["controlled_submission_clearance_conflict"],
                    )

                intent = conn.execute(
                    """
                    SELECT * FROM controlled_broker_submit_intents
                    WHERE submit_intent_id = ? LIMIT 1
                    """,
                    (requested["submit_intent_id"],),
                ).fetchone()
                order = conn.execute(
                    "SELECT * FROM oms_orders WHERE order_id = ? LIMIT 1",
                    (requested["order_id"],),
                ).fetchone()
                latest_item = conn.execute(
                    """
                    SELECT * FROM execution_reconciliation_items
                    WHERE order_id = ? ORDER BY id DESC LIMIT 1
                    """,
                    (requested["order_id"],),
                ).fetchone()
                blockers: list[str] = []
                if intent is None:
                    blockers.append("controlled_submission_intent_not_found")
                else:
                    if str(intent["status"]) != "submitted":
                        blockers.append("controlled_submission_intent_not_submitted")
                    if str(intent["order_id"]) != requested["order_id"]:
                        blockers.append("controlled_submission_intent_order_mismatch")
                    if (
                        str(intent["submit_fingerprint"])
                        != requested["submit_fingerprint"]
                    ):
                        blockers.append(
                            "controlled_submission_submit_fingerprint_changed"
                        )
                    if str(intent["broker_order_id"]) != requested["broker_order_id"]:
                        blockers.append("controlled_submission_broker_order_changed")
                    if str(intent["client_order_id"]) != requested["client_order_id"]:
                        blockers.append("controlled_submission_client_order_changed")
                if order is None or str(order["status"]) != "submitted":
                    blockers.append("controlled_submission_oms_not_submitted")
                if intent is not None and order is not None:
                    from account_truth.broker_order_lifecycle import (
                        broker_order_lifecycle_terminal_outcome,
                        resolve_broker_order_lifecycle_from_connection,
                    )

                    account_alias = str(
                        _json_dict(intent["payload_json"]).get("account_alias") or ""
                    )
                    if account_alias:
                        lifecycle_evidence = (
                            resolve_broker_order_lifecycle_from_connection(
                                conn,
                                gateway_id=str(intent["gateway_id"] or ""),
                                account_alias=account_alias,
                                broker_order_id=str(intent["broker_order_id"] or ""),
                                client_order_id=str(intent["client_order_id"] or ""),
                            )
                        )
                        terminal_lifecycle = broker_order_lifecycle_terminal_outcome(
                            dict(order),
                            lifecycle_evidence,
                        )
                        if terminal_lifecycle["status"] in {
                            "blocked",
                            "non_terminal",
                        }:
                            blockers.extend(terminal_lifecycle["blockers"])
                            blockers.append(
                                "controlled_submission_terminal_outcome_changed"
                            )
                        elif terminal_lifecycle["status"] == "terminal":
                            expected_terminal_fields = {
                                "terminal_status": requested["terminal_status"],
                                "filled_quantity": requested["fill_quantity"],
                                "cancelled_quantity": requested["cancelled_quantity"],
                                "observation_id": requested["lifecycle_observation_id"],
                                "evidence_fingerprint": requested[
                                    "lifecycle_evidence_fingerprint"
                                ],
                                "source_sequence": requested[
                                    "lifecycle_source_sequence"
                                ],
                            }
                            for field, expected in expected_terminal_fields.items():
                                if str(terminal_lifecycle.get(field) or "") != str(
                                    expected or ""
                                ):
                                    blockers.append(
                                        "controlled_submission_terminal_"
                                        f"lifecycle_{field}_changed"
                                    )
                        elif requested["terminal_status"] == "cancelled":
                            blockers.append(
                                "controlled_submission_terminal_lifecycle_missing"
                            )
                if latest_item is None:
                    blockers.append("controlled_submission_reconciliation_item_missing")
                else:
                    if int(latest_item["id"]) != int(
                        requested["review_reconciliation_item_id"]
                    ):
                        blockers.append(
                            "controlled_submission_reconciliation_item_superseded"
                        )
                    if (
                        str(latest_item["run_id"])
                        != requested["review_reconciliation_run_id"]
                    ):
                        blockers.append(
                            "controlled_submission_reconciliation_run_changed"
                        )
                    clearable_item_statuses = {
                        "filled": {"controlled_submission_broker_evidence_available"},
                        "cancelled": {
                            "controlled_submission_partial_fill_cancel_evidence_available",
                            "controlled_submission_cancel_evidence_available",
                        },
                    }
                    if str(
                        latest_item["item_status"]
                    ) not in clearable_item_statuses.get(
                        str(requested.get("terminal_status") or ""),
                        set(),
                    ):
                        blockers.append(
                            "controlled_submission_reconciliation_item_not_clearable"
                        )
                    item_payload = _json_dict(latest_item["payload_json"])
                    item_summary = item_payload.get(
                        "controlled_submission_evidence_summary"
                    )
                    item_summary = (
                        item_summary if isinstance(item_summary, dict) else {}
                    )
                    if (
                        str(item_summary.get("submit_intent_id") or "")
                        != requested["submit_intent_id"]
                    ):
                        blockers.append(
                            "controlled_submission_reconciliation_intent_changed"
                        )
                    if (
                        str(item_summary.get("broker_evidence_fingerprint") or "")
                        != requested["broker_evidence_fingerprint"]
                    ):
                        blockers.append("controlled_submission_broker_evidence_changed")

                latest_import = conn.execute("""
                    SELECT * FROM broker_import_runs
                    WHERE validation_status != 'blocked'
                    ORDER BY created_at DESC, id DESC LIMIT 1
                    """).fetchone()
                if latest_import is None:
                    blockers.append(
                        "controlled_submission_account_truth_import_missing"
                    )
                else:
                    if (
                        str(latest_import["import_run_id"])
                        != requested["account_truth_import_run_id"]
                    ):
                        blockers.append(
                            "controlled_submission_account_truth_import_superseded"
                        )
                    if (
                        str(latest_import["file_fingerprint"])
                        != requested["account_truth_file_fingerprint"]
                    ):
                        blockers.append(
                            "controlled_submission_account_truth_file_changed"
                        )

                fill_rows = list(requested.get("fills") or [])
                terminal_status = str(requested.get("terminal_status") or "")
                if not fill_rows and terminal_status != "cancelled":
                    blockers.append("controlled_submission_fill_evidence_missing")
                fill_quantity = sum(
                    (
                        Decimal(str(item.get("fill_quantity") or "0"))
                        for item in fill_rows
                    ),
                    Decimal("0"),
                )
                order_quantity = (
                    Decimal(str(order["quantity"]))
                    if order is not None
                    else Decimal("0")
                )
                cancelled_quantity = Decimal(
                    str(requested.get("cancelled_quantity") or "0")
                )
                if str(requested.get("fill_quantity") or "0") != str(fill_quantity):
                    blockers.append("controlled_submission_fill_quantity_changed")
                if terminal_status == "filled" and (
                    fill_quantity <= 0
                    or fill_quantity != abs(order_quantity)
                    or cancelled_quantity != 0
                ):
                    blockers.append("controlled_submission_full_fill_incomplete")
                elif terminal_status == "cancelled" and (
                    cancelled_quantity <= 0
                    or fill_quantity + cancelled_quantity != abs(order_quantity)
                ):
                    blockers.append("controlled_submission_cancel_quantity_incomplete")
                elif terminal_status not in {"filled", "cancelled"}:
                    blockers.append("controlled_submission_terminal_status_invalid")
                for fill in fill_rows:
                    broker_event = conn.execute(
                        """
                        SELECT * FROM broker_evidence_events
                        WHERE import_run_id = ? AND event_id = ?
                          AND row_fingerprint = ?
                        LIMIT 1
                        """,
                        (
                            fill.get("account_truth_import_run_id"),
                            fill.get("broker_event_id"),
                            fill.get("broker_row_fingerprint"),
                        ),
                    ).fetchone()
                    if broker_event is None:
                        blockers.append(
                            "controlled_submission_broker_event_source_changed"
                        )
                        continue
                    expected_values = {
                        "symbol": fill.get("symbol"),
                        "price": fill.get("fill_price"),
                        "fee": fill.get("fee"),
                        "tax": fill.get("tax"),
                        "transfer_fee": fill.get("transfer_fee"),
                        "broker_order_id": requested["broker_order_id"],
                        "client_order_id": requested["client_order_id"],
                    }
                    for field, expected in expected_values.items():
                        if str(broker_event[field] or "") != str(expected or ""):
                            blockers.append(
                                f"controlled_submission_broker_event_{field}_changed"
                            )
                    if abs(Decimal(str(broker_event["quantity"]))) != Decimal(
                        str(fill.get("fill_quantity") or "0")
                    ):
                        blockers.append(
                            "controlled_submission_broker_event_quantity_changed"
                        )
                if blockers:
                    conn.rollback()
                    return _controlled_submission_clearance_rejection(
                        requested,
                        blockers,
                    )

                for fill in fill_rows:
                    existing_fill = conn.execute(
                        "SELECT * FROM fills WHERE fill_id = ? LIMIT 1",
                        (fill["fill_id"],),
                    ).fetchone()
                    if existing_fill is not None:
                        conn.rollback()
                        return _controlled_submission_clearance_rejection(
                            requested,
                            ["controlled_submission_fill_id_conflict"],
                        )
                    metadata_json = _serialize_metadata_json(fill["metadata"])
                    conn.execute(
                        """
                        INSERT INTO fills (
                            fill_id, order_id, timestamp, symbol, side,
                            fill_price, fill_quantity, commission, slippage,
                            asset_class, execution_mode, provider_name,
                            broker_order_id, source, source_ref, metadata_json,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            fill["fill_id"],
                            requested["order_id"],
                            fill["timestamp"],
                            fill["symbol"],
                            fill["side"],
                            float(fill["fill_price"]),
                            float(fill["fill_quantity"]),
                            float(fill["fee"]),
                            0.0,
                            fill["asset_class"],
                            "controlled_live",
                            fill["provider_name"],
                            requested["broker_order_id"],
                            "controlled_submission_clearance",
                            fill["broker_event_id"],
                            metadata_json,
                            requested["cleared_at"],
                            requested["cleared_at"],
                        ),
                    )
                    saved_fill = conn.execute(
                        "SELECT * FROM fills WHERE fill_id = ? LIMIT 1",
                        (fill["fill_id"],),
                    ).fetchone()
                    if saved_fill is not None:
                        _insert_event_sync(
                            conn,
                            event_type="order.fill.recorded",
                            timestamp=str(saved_fill["timestamp"]),
                            entity_type="fill",
                            entity_id=str(saved_fill["fill_id"]),
                            source="fills",
                            source_ref=str(saved_fill["fill_id"]),
                            payload=_fill_event_payload(saved_fill),
                        )

                transition_payload = {
                    "clearance_id": requested["clearance_id"],
                    "submit_intent_id": requested["submit_intent_id"],
                    "broker_order_id": requested["broker_order_id"],
                    "filled_quantity": str(fill_quantity),
                    "cancelled_quantity": str(cancelled_quantity),
                    "terminal_status": terminal_status,
                    "account_truth_import_run_id": requested[
                        "account_truth_import_run_id"
                    ],
                    "production_ledger_mutated": False,
                }
                if terminal_status == "filled":
                    transition_steps = (
                        (
                            "submitted",
                            "accepted",
                            "broker acceptance confirmed by signed reconciliation clearance",
                        ),
                        (
                            "accepted",
                            "filled",
                            "full broker fill confirmed by signed reconciliation clearance",
                        ),
                    )
                elif fill_quantity > 0:
                    transition_steps = (
                        (
                            "submitted",
                            "accepted",
                            "broker acceptance confirmed by signed reconciliation clearance",
                        ),
                        (
                            "accepted",
                            "partially_filled",
                            "partial broker fills confirmed by signed reconciliation clearance",
                        ),
                        (
                            "partially_filled",
                            "cancelled",
                            "remaining quantity cancelled in exact terminal broker evidence",
                        ),
                    )
                else:
                    transition_steps = (
                        (
                            "submitted",
                            "cancelled",
                            "no-fill cancellation confirmed by signed reconciliation clearance",
                        ),
                    )
                for from_status, to_status, reason in transition_steps:
                    conn.execute(
                        "UPDATE oms_orders SET status = ?, updated_at = ? WHERE order_id = ?",
                        (to_status, requested["cleared_at"], requested["order_id"]),
                    )
                    conn.execute(
                        """
                        INSERT INTO oms_transitions (
                            order_id, from_status, to_status, reason, actor,
                            payload_json, transitioned_at, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            requested["order_id"],
                            from_status,
                            to_status,
                            reason,
                            requested["operator_id"],
                            _serialize_event_payload_json(transition_payload),
                            requested["cleared_at"],
                            requested["cleared_at"],
                        ),
                    )

                conn.execute(
                    """
                    INSERT INTO controlled_submission_reconciliation_clearances (
                        clearance_id, clearance_fingerprint, submit_intent_id,
                        submit_fingerprint, order_id, broker_order_id,
                        review_reconciliation_run_id,
                        review_reconciliation_item_id,
                        broker_evidence_fingerprint,
                        account_truth_import_run_id,
                        account_truth_file_fingerprint,
                        account_truth_source_fingerprint,
                        clearance_reconciliation_run_id,
                        operator_id, operator_approval_id, status,
                        terminal_status, fill_count, fill_quantity,
                        cancelled_quantity, lifecycle_observation_id,
                        lifecycle_evidence_fingerprint,
                        lifecycle_source_sequence, cleared_at_epoch_ms,
                        cleared_at, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["clearance_id"],
                        requested["clearance_fingerprint"],
                        requested["submit_intent_id"],
                        requested["submit_fingerprint"],
                        requested["order_id"],
                        requested["broker_order_id"],
                        requested["review_reconciliation_run_id"],
                        int(requested["review_reconciliation_item_id"]),
                        requested["broker_evidence_fingerprint"],
                        requested["account_truth_import_run_id"],
                        requested["account_truth_file_fingerprint"],
                        requested["account_truth_source_fingerprint"],
                        requested["clearance_reconciliation_run_id"],
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        "cleared",
                        terminal_status,
                        len(fill_rows),
                        str(fill_quantity),
                        str(cancelled_quantity),
                        requested["lifecycle_observation_id"],
                        requested["lifecycle_evidence_fingerprint"],
                        int(requested["lifecycle_source_sequence"]),
                        int(requested["cleared_at_epoch_ms"]),
                        requested["cleared_at"],
                        _serialize_event_payload_json(requested["payload"]),
                        requested["cleared_at"],
                    ),
                )

                clearance_run_payload = {
                    "schema_version": "karkinos.execution_reconciliation.v1",
                    "source": "controlled_submission_reconciliation_clearance",
                    "clearance_id": requested["clearance_id"],
                    "review_reconciliation_run_id": requested[
                        "review_reconciliation_run_id"
                    ],
                }
                conn.execute(
                    """
                    INSERT INTO execution_reconciliation_runs (
                        run_id, run_date, status, item_count, open_item_count,
                        payload_json, created_at, updated_at
                    ) VALUES (?, ?, 'clear', 1, 0, ?, ?, ?)
                    """,
                    (
                        requested["clearance_reconciliation_run_id"],
                        requested["clearance_run_date"],
                        _serialize_event_payload_json(clearance_run_payload),
                        requested["cleared_at"],
                        requested["cleared_at"],
                    ),
                )
                clearance_item_payload = {
                    "oms_status": terminal_status,
                    "execution_mode": "controlled_live",
                    "controlled_submission_evidence_summary": {
                        "schema_version": (
                            "karkinos.controlled_submission_reconciliation.v3"
                        ),
                        "submit_intent_id": requested["submit_intent_id"],
                        "clearance_id": requested["clearance_id"],
                        "intent_status": "submitted",
                        "oms_status": terminal_status,
                        "terminal_status": terminal_status,
                        "filled_quantity": str(fill_quantity),
                        "cancelled_quantity": str(cancelled_quantity),
                        "new_submissions_blocked": False,
                        "recovery_resubmission_enabled": False,
                        "production_ledger_mutated": False,
                    },
                }
                conn.execute(
                    """
                    INSERT INTO execution_reconciliation_items (
                        run_id, order_id, item_status, suggested_action,
                        gateway_event_count, broker_event_count, detail,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, 'no_action', 0, ?, ?, ?, ?)
                    """,
                    (
                        requested["clearance_reconciliation_run_id"],
                        requested["order_id"],
                        "controlled_submission_reconciliation_cleared",
                        len(fill_rows),
                        (
                            "Signed controlled-submission reconciliation clearance "
                            f"recorded exact {terminal_status} outcome without "
                            "production-ledger mutation."
                        ),
                        _serialize_event_payload_json(clearance_item_payload),
                        requested["cleared_at"],
                    ),
                )
                _insert_event_sync(
                    conn,
                    event_type="controlled_broker.reconciliation_cleared",
                    timestamp=requested["cleared_at"],
                    entity_type="controlled_submission_reconciliation_clearance",
                    entity_id=requested["clearance_id"],
                    source="controlled_submission_reconciliation_clearance",
                    source_ref=requested["submit_intent_id"],
                    payload=requested["payload"],
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_submission_reconciliation_clearances
                    WHERE clearance_id = ? LIMIT 1
                    """,
                    (requested["clearance_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "cleared",
                    "blockers": [],
                    "reused": False,
                    "clearance": dict(saved) if saved is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
                ArithmeticError,
            ):
                conn.rollback()
                return _controlled_submission_clearance_rejection(
                    requested,
                    ["controlled_submission_clearance_transaction_unavailable"],
                )

    def list_oms_transitions_sync(self, order_id: str) -> list[dict[str, Any]]:
        """List OMS transitions for one order in chronological order."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM oms_transitions
                WHERE order_id = ?
                ORDER BY id ASC
                """,
                (order_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    # ---------- Broker Gateway Events ----------

    def record_broker_gateway_event_sync(
        self,
        *,
        gateway_id: str,
        event_type: str,
        order_id: str | None = None,
        status: str = "recorded",
        actor: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one broker gateway audit event."""
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """
                INSERT INTO broker_gateway_events (
                    gateway_id, event_type, order_id, status, actor,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gateway_id,
                    event_type,
                    order_id,
                    status,
                    actor,
                    payload_json,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM broker_gateway_events WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
            conn.commit()
            return dict(row)

    def list_broker_gateway_events_sync(
        self,
        *,
        order_id: str | None = None,
        gateway_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List broker gateway audit events."""
        conditions: list[str] = []
        params: list[Any] = []
        if order_id is not None:
            conditions.append("order_id = ?")
            params.append(order_id)
        if gateway_id is not None:
            conditions.append("gateway_id = ?")
            params.append(gateway_id)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([int(limit), int(offset)])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM broker_gateway_events
                {where_clause}
                ORDER BY id ASC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(row) for row in rows]

    # ---------- Execution Reconciliation ----------

    def list_oms_orders_sync(
        self,
        *,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List OMS orders for execution reconciliation."""
        conditions: list[str] = []
        params: list[Any] = []
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([int(limit), int(offset)])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM oms_orders
                {where_clause}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(row) for row in rows]

    def upsert_execution_reconciliation_run_sync(
        self,
        *,
        run_id: str,
        run_date: str,
        status: str,
        item_count: int,
        open_item_count: int,
        payload: dict[str, Any] | None = None,
        items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Persist one execution reconciliation run and replace its items."""
        now = datetime.now().isoformat()
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT created_at
                FROM execution_reconciliation_runs
                WHERE run_id = ?
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO execution_reconciliation_runs (
                    run_id, run_date, status, item_count, open_item_count,
                    payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    run_date = excluded.run_date,
                    status = excluded.status,
                    item_count = excluded.item_count,
                    open_item_count = excluded.open_item_count,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    run_id,
                    run_date,
                    status,
                    int(item_count),
                    int(open_item_count),
                    payload_json,
                    created_at,
                    now,
                ),
            )
            conn.execute(
                "DELETE FROM execution_reconciliation_items WHERE run_id = ?",
                (run_id,),
            )
            for item in items or []:
                conn.execute(
                    """
                    INSERT INTO execution_reconciliation_items (
                        run_id, order_id, item_status, suggested_action,
                        gateway_event_count, broker_event_count, detail,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        item["order_id"],
                        item["item_status"],
                        item["suggested_action"],
                        int(item.get("gateway_event_count") or 0),
                        int(item.get("broker_event_count") or 0),
                        item.get("detail") or "",
                        json.dumps(
                            item.get("payload") or {},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        now,
                    ),
                )
            row = conn.execute(
                "SELECT * FROM execution_reconciliation_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            conn.commit()
            return dict(row)

    def list_execution_reconciliation_runs_sync(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List recent execution reconciliation runs."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM execution_reconciliation_runs
                ORDER BY run_date DESC, updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (int(limit), int(offset)),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_execution_reconciliation_run_sync(
        self,
        run_id: str,
    ) -> dict[str, Any] | None:
        """Read one execution reconciliation run."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM execution_reconciliation_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_execution_reconciliation_items_sync(
        self,
        run_id: str,
    ) -> list[dict[str, Any]]:
        """List item rows for one execution reconciliation run."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM execution_reconciliation_items
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    # ---------- Strategy Promotion Pipeline ----------

    def upsert_strategy_promotion_state_sync(
        self,
        *,
        strategy_id: str,
        stage: str,
        gate_status: str,
        live_like_enabled: bool,
        missing_requirements: list[str] | None = None,
        backtest_result_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one strategy promotion state."""
        now = datetime.now().isoformat()
        missing_json = json.dumps(
            missing_requirements or [],
            ensure_ascii=False,
            sort_keys=True,
        )
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT created_at
                FROM strategy_promotion_states
                WHERE strategy_id = ?
                LIMIT 1
                """,
                (strategy_id,),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO strategy_promotion_states (
                    strategy_id, stage, gate_status, live_like_enabled,
                    missing_requirements_json, backtest_result_id, payload_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id) DO UPDATE SET
                    stage = excluded.stage,
                    gate_status = excluded.gate_status,
                    live_like_enabled = excluded.live_like_enabled,
                    missing_requirements_json = excluded.missing_requirements_json,
                    backtest_result_id = excluded.backtest_result_id,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    strategy_id,
                    stage,
                    gate_status,
                    1 if live_like_enabled else 0,
                    missing_json,
                    backtest_result_id,
                    payload_json,
                    created_at,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM strategy_promotion_states
                WHERE strategy_id = ?
                """,
                (strategy_id,),
            ).fetchone()
            conn.commit()
            return dict(row)

    def get_strategy_promotion_state_sync(
        self,
        strategy_id: str,
    ) -> dict[str, Any] | None:
        """Read one strategy promotion state."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM strategy_promotion_states
                WHERE strategy_id = ?
                """,
                (strategy_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_strategy_promotion_states_sync(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List strategy promotion states."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM strategy_promotion_states
                ORDER BY updated_at DESC, strategy_id ASC
                LIMIT ? OFFSET ?
                """,
                (int(limit), int(offset)),
            ).fetchall()
            return [dict(row) for row in rows]

    def record_strategy_promotion_event_sync(
        self,
        *,
        strategy_id: str,
        event_type: str,
        from_stage: str | None = None,
        to_stage: str | None = None,
        actor: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one strategy promotion audit event."""
        now = datetime.now().isoformat()
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """
                INSERT INTO strategy_promotion_events (
                    strategy_id, event_type, from_stage, to_stage, actor,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    strategy_id,
                    event_type,
                    from_stage,
                    to_stage,
                    actor,
                    payload_json,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM strategy_promotion_events WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
            conn.commit()
            return dict(row)

    def list_strategy_promotion_events_sync(
        self,
        strategy_id: str,
    ) -> list[dict[str, Any]]:
        """List strategy promotion audit events for one strategy."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM strategy_promotion_events
                WHERE strategy_id = ?
                ORDER BY id ASC
                """,
                (strategy_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    # ---------- Automation Alerts ----------

    def upsert_automation_alert_sync(
        self,
        *,
        alert_key: str,
        severity: str,
        category: str,
        title: str,
        detail: str,
        source: str,
        source_ref: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist an idempotent automation alert by alert key."""
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT created_at, status, acknowledged_at, acknowledged_by
                FROM automation_alerts
                WHERE alert_key = ?
                LIMIT 1
                """,
                (alert_key,),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            status = str(existing["status"]) if existing else "open"
            acknowledged_at = existing["acknowledged_at"] if existing else None
            acknowledged_by = existing["acknowledged_by"] if existing else None
            conn.execute(
                """
                INSERT INTO automation_alerts (
                    alert_key, severity, category, title, detail, status,
                    source, source_ref, payload_json, acknowledged_at,
                    acknowledged_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alert_key) DO UPDATE SET
                    severity = excluded.severity,
                    category = excluded.category,
                    title = excluded.title,
                    detail = excluded.detail,
                    source = excluded.source,
                    source_ref = excluded.source_ref,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    alert_key,
                    severity,
                    category,
                    title,
                    detail,
                    status,
                    source,
                    source_ref,
                    payload_json,
                    acknowledged_at,
                    acknowledged_by,
                    created_at,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM automation_alerts WHERE alert_key = ?",
                (alert_key,),
            ).fetchone()
            conn.commit()
            return dict(row)

    def list_automation_alerts_sync(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List persisted automation alerts."""
        conditions: list[str] = []
        params: list[Any] = []
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([int(limit), int(offset)])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM automation_alerts
                {where_clause}
                ORDER BY
                    CASE severity
                        WHEN 'critical' THEN 0
                        WHEN 'warning' THEN 1
                        ELSE 2
                    END,
                    updated_at DESC,
                    id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(row) for row in rows]

    def acknowledge_automation_alert_sync(
        self,
        *,
        alert_id: int,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Mark one automation alert acknowledged."""
        now = datetime.now().isoformat()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                UPDATE automation_alerts
                SET status = 'acknowledged',
                    acknowledged_at = ?,
                    acknowledged_by = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, actor, now, int(alert_id)),
            )
            row = conn.execute(
                "SELECT * FROM automation_alerts WHERE id = ?",
                (int(alert_id),),
            ).fetchone()
            conn.commit()
            if row is None:
                raise KeyError(f"automation alert not found: {alert_id}")
            return dict(row)

    def list_execution_reconciliation_open_items_sync(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List execution reconciliation items that still require action."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT current.*
                FROM execution_reconciliation_items AS current
                INNER JOIN (
                    SELECT order_id, MAX(id) AS latest_id
                    FROM execution_reconciliation_items
                    GROUP BY order_id
                ) AS latest
                    ON latest.latest_id = current.id
                WHERE current.suggested_action != 'no_action'
                ORDER BY
                    CASE
                        WHEN current.item_status LIKE 'controlled_submission_unknown%'
                            THEN 0
                        WHEN current.item_status LIKE 'controlled_%'
                            THEN 1
                        ELSE 2
                    END ASC,
                    current.id DESC
                LIMIT ? OFFSET ?
                """,
                (int(limit), int(offset)),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_latest_execution_reconciliation_item_for_order_sync(
        self,
        order_id: str,
    ) -> dict[str, Any] | None:
        """Return the latest persisted reconciliation fact for one OMS order."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM execution_reconciliation_items
                WHERE order_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (order_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    # ---------- Paper/Shadow Runs ----------

    def upsert_paper_shadow_run_sync(
        self,
        *,
        run_id: str,
        plan_date: str,
        input_fingerprint: str,
        status: str,
        order_intent_count: int,
        simulated_order_count: int,
        simulated_fill_count: int,
        divergence_status: str,
        next_manual_review_step: str,
        limitations: list[str] | None = None,
        payload: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        """Persist or update one idempotent daily paper/shadow run record."""
        now = datetime.now().isoformat()
        limitations_json = json.dumps(
            limitations or [],
            ensure_ascii=False,
            sort_keys=True,
        )
        payload_json = _serialize_metadata_json(payload) or "{}"
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT *
                FROM paper_shadow_runs
                WHERE run_id = ?
                   OR (plan_date = ? AND input_fingerprint = ?)
                ORDER BY
                    CASE WHEN run_id = ? THEN 0 ELSE 1 END,
                    id ASC
                LIMIT 1
                """,
                (run_id, plan_date, input_fingerprint, run_id),
            ).fetchone()
            effective_run_id = str(existing["run_id"]) if existing else run_id
            created_at = str(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO paper_shadow_runs (
                    run_id, plan_date, input_fingerprint, status,
                    order_intent_count, simulated_order_count,
                    simulated_fill_count, divergence_status,
                    next_manual_review_step, limitations_json, payload_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    plan_date = excluded.plan_date,
                    input_fingerprint = excluded.input_fingerprint,
                    status = excluded.status,
                    order_intent_count = excluded.order_intent_count,
                    simulated_order_count = excluded.simulated_order_count,
                    simulated_fill_count = excluded.simulated_fill_count,
                    divergence_status = excluded.divergence_status,
                    next_manual_review_step = excluded.next_manual_review_step,
                    limitations_json = excluded.limitations_json,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    effective_run_id,
                    plan_date,
                    input_fingerprint,
                    status,
                    int(order_intent_count),
                    int(simulated_order_count),
                    int(simulated_fill_count),
                    divergence_status,
                    next_manual_review_step,
                    limitations_json,
                    payload_json,
                    created_at,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM paper_shadow_runs WHERE run_id = ?",
                (effective_run_id,),
            ).fetchone()
            conn.commit()
            return dict(row)

    def get_paper_shadow_run_sync(self, run_id: str) -> dict[str, Any] | None:
        """Read one persisted paper/shadow run by ID."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM paper_shadow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return dict(row) if row else None

    def latest_paper_shadow_run_sync(
        self,
        *,
        plan_date: str | None = None,
    ) -> dict[str, Any] | None:
        """Read the latest paper/shadow run, optionally scoped to a plan date."""
        conditions: list[str] = []
        params: list[Any] = []
        if plan_date is not None:
            conditions.append("plan_date = ?")
            params.append(plan_date)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"""
                SELECT *
                FROM paper_shadow_runs
                {where_clause}
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
            return dict(row) if row else None

    def record_paper_shadow_run_review_sync(
        self,
        *,
        run_id: str,
        reviewed_at: str,
        review_status: str,
        review_notes: str,
        reviewer: str | None = None,
    ) -> dict[str, Any] | None:
        """Attach an operator review outcome to a paper/shadow run."""
        next_step = _paper_shadow_run_review_next_step(review_status)
        now = datetime.now().isoformat()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM paper_shadow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            _validate_paper_shadow_run_review_transition(
                run_status=str(row["status"] or ""),
                review_status=review_status,
            )

            payload = _json_dict(row["payload_json"])
            review_payload = {
                "review_status": review_status,
                "reviewed_at": reviewed_at,
                "review_notes": review_notes,
                "reviewer": reviewer,
                "does_not_submit_broker_order": True,
                "does_not_mutate_production_ledger": True,
            }
            payload["review"] = review_payload
            conn.execute(
                """
                UPDATE paper_shadow_runs
                SET review_status = ?,
                    reviewed_at = ?,
                    review_notes = ?,
                    reviewer = ?,
                    next_manual_review_step = ?,
                    payload_json = ?,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (
                    review_status,
                    reviewed_at,
                    review_notes,
                    reviewer,
                    next_step,
                    _serialize_metadata_json(payload),
                    now,
                    run_id,
                ),
            )
            updated = conn.execute(
                "SELECT * FROM paper_shadow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if updated is not None:
                _insert_event_sync(
                    conn,
                    event_type="paper_shadow_run.review_recorded",
                    timestamp=reviewed_at,
                    entity_type="paper_shadow_run",
                    entity_id=run_id,
                    source="paper_shadow_reviews",
                    source_ref=run_id,
                    payload={
                        "run_id": run_id,
                        "plan_date": updated["plan_date"],
                        "input_fingerprint": updated["input_fingerprint"],
                        "status": updated["status"],
                        "divergence_status": updated["divergence_status"],
                        "next_manual_review_step": next_step,
                        **review_payload,
                    },
                )
            conn.commit()
            return dict(updated) if updated is not None else None

    # ---------- Orders ----------

    def record_order_sync(
        self,
        *,
        order_id: str,
        timestamp: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
        asset_class: str = "stock",
        intent_id: str | None = None,
        risk_decision_id: str | None = None,
        execution_mode: str = "paper",
        status: str = "submitted",
        source: str = "execution",
        source_ref: str | None = None,
        payload: dict[str, Any] | str | None = None,
    ) -> int:
        """Persist a shared order fact for manual, paper, and live execution."""
        now = datetime.now().isoformat()
        payload_json = _serialize_metadata_json(payload) or "{}"
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO orders (
                    order_id, timestamp, symbol, side, order_type, quantity, price,
                    asset_class, intent_id, risk_decision_id, execution_mode, status,
                    source, source_ref, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    timestamp = excluded.timestamp,
                    symbol = excluded.symbol,
                    side = excluded.side,
                    order_type = excluded.order_type,
                    quantity = excluded.quantity,
                    price = excluded.price,
                    asset_class = excluded.asset_class,
                    intent_id = excluded.intent_id,
                    risk_decision_id = excluded.risk_decision_id,
                    execution_mode = excluded.execution_mode,
                    status = excluded.status,
                    source = excluded.source,
                    source_ref = excluded.source_ref,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    order_id,
                    timestamp,
                    symbol,
                    side,
                    order_type,
                    quantity,
                    price,
                    asset_class,
                    intent_id,
                    risk_decision_id,
                    execution_mode,
                    status,
                    source,
                    source_ref,
                    payload_json,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if row is not None:
                _insert_event_sync(
                    conn,
                    event_type="order.recorded",
                    timestamp=row["timestamp"],
                    entity_type="order",
                    entity_id=row["order_id"],
                    source="orders",
                    source_ref=row["order_id"],
                    payload=_order_event_payload(row),
                )
            conn.commit()
            return int(row["id"]) if row is not None else 0

    def get_order_sync(self, order_id: str) -> dict[str, Any] | None:
        """Read one shared order fact by ID."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            return dict(row) if row else None

    def record_shadow_divergence_review_sync(
        self,
        *,
        order_id: str,
        reviewed_at: str,
        divergence_status: str,
        review_notes: str,
        reviewer: str | None = None,
    ) -> dict[str, Any] | None:
        """Attach an operator divergence review to a paper/shadow order fact."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if row is None:
                return None
            if row["execution_mode"] != "paper_shadow":
                return dict(row)
            payload = _json_dict(row["payload_json"])
            payload.update(
                {
                    "divergence_status": divergence_status,
                    "divergence_reviewed_at": reviewed_at,
                    "divergence_review_notes": review_notes,
                    "divergence_reviewer": reviewer,
                }
            )
            conn.execute(
                """
                UPDATE orders
                SET payload_json = ?, updated_at = ?
                WHERE order_id = ?
                """,
                (
                    _serialize_metadata_json(payload),
                    datetime.now().isoformat(),
                    order_id,
                ),
            )
            updated = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if updated is not None:
                _insert_event_sync(
                    conn,
                    event_type="order.shadow_divergence_reviewed",
                    timestamp=reviewed_at,
                    entity_type="order",
                    entity_id=updated["order_id"],
                    source="shadow_reviews",
                    source_ref=updated["order_id"],
                    payload=_order_event_payload(updated),
                )
            conn.commit()
            return dict(updated) if updated is not None else None

    def list_orders_sync(
        self,
        *,
        status: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List shared order facts newest first."""
        conditions: list[str] = []
        params: list[Any] = []
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if symbol is not None:
            conditions.append("symbol = ?")
            params.append(symbol)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM orders
                {where_clause}
                ORDER BY timestamp DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_order_status_sync(
        self, *, order_id: str, status: str, note: str = ""
    ) -> dict[str, Any] | None:
        """Update shared order status and append an order status event."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                UPDATE orders
                SET status = ?, updated_at = ?
                WHERE order_id = ?
                """,
                (status, datetime.now().isoformat(), order_id),
            )
            row = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if row is not None:
                payload = _order_event_payload(row)
                payload["note"] = note
                _insert_event_sync(
                    conn,
                    event_type="order.status_changed",
                    timestamp=datetime.now().isoformat(),
                    entity_type="order",
                    entity_id=row["order_id"],
                    source="orders",
                    source_ref=row["order_id"],
                    payload=payload,
                )
            conn.commit()
            return dict(row) if row else None

    # ---------- Manual Orders ----------

    def save_manual_order_sync(
        self,
        *,
        order_id: str,
        timestamp: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None,
        intent_id: str | None,
        risk_decision_id: str | None,
        execution_mode: str,
        status: str,
        payload: dict[str, Any],
    ) -> int:
        """Persist an order waiting for manual confirmation."""
        now = datetime.now().isoformat()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                INSERT INTO manual_orders (
                    order_id, timestamp, symbol, side, order_type, quantity, price,
                    intent_id, risk_decision_id, execution_mode, status, payload_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    timestamp = excluded.timestamp,
                    symbol = excluded.symbol,
                    side = excluded.side,
                    order_type = excluded.order_type,
                    quantity = excluded.quantity,
                    price = excluded.price,
                    intent_id = excluded.intent_id,
                    risk_decision_id = excluded.risk_decision_id,
                    execution_mode = excluded.execution_mode,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    order_id,
                    timestamp,
                    symbol,
                    side,
                    order_type,
                    quantity,
                    price,
                    intent_id,
                    risk_decision_id,
                    execution_mode,
                    status,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM manual_orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if row is not None:
                _insert_event_sync(
                    conn,
                    event_type="order.submitted",
                    timestamp=row["timestamp"],
                    entity_type="order",
                    entity_id=row["order_id"],
                    source="manual_orders",
                    source_ref=row["order_id"],
                    payload=_manual_order_event_payload(row),
                )
            conn.commit()
            return cursor.lastrowid or 0

    def get_manual_order_sync(self, order_id: str) -> dict[str, Any] | None:
        """Read one manual order by ID."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM manual_orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_manual_orders_sync(
        self, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List manual orders, latest first."""
        query = "SELECT * FROM manual_orders"
        params: list[Any] = []
        if status is not None:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, tuple(params)).fetchall()
            return [dict(row) for row in rows]

    def update_manual_order_status_sync(
        self, *, order_id: str, status: str, note: str = ""
    ) -> dict[str, Any] | None:
        """Update manual order status and return the updated row."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                UPDATE manual_orders
                SET status = ?, note = ?, updated_at = ?
                WHERE order_id = ?
                """,
                (status, note, datetime.now().isoformat(), order_id),
            )
            row = conn.execute(
                "SELECT * FROM manual_orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if row is not None:
                _insert_event_sync(
                    conn,
                    event_type="order.status_changed",
                    timestamp=datetime.now().isoformat(),
                    entity_type="order",
                    entity_id=row["order_id"],
                    source="manual_orders",
                    source_ref=row["order_id"],
                    payload=_manual_order_event_payload(row),
                )
            conn.commit()
            return dict(row) if row else None

    # ---------- Fills ----------

    def record_fill_sync(
        self,
        *,
        fill_id: str,
        order_id: str,
        timestamp: str,
        symbol: str,
        side: str,
        fill_price: float,
        fill_quantity: float,
        commission: float = 0.0,
        slippage: float = 0.0,
        asset_class: str = "stock",
        execution_mode: str = "paper",
        provider_name: str | None = None,
        broker_order_id: str | None = None,
        source: str = "execution",
        source_ref: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> int:
        """Persist a fill from paper/live execution and append an event."""
        now = datetime.now().isoformat()
        metadata_json = _serialize_metadata_json(metadata)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO fills (
                    fill_id, order_id, timestamp, symbol, side, fill_price,
                    fill_quantity, commission, slippage, asset_class,
                    execution_mode, provider_name, broker_order_id, source,
                    source_ref, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fill_id) DO UPDATE SET
                    order_id = excluded.order_id,
                    timestamp = excluded.timestamp,
                    symbol = excluded.symbol,
                    side = excluded.side,
                    fill_price = excluded.fill_price,
                    fill_quantity = excluded.fill_quantity,
                    commission = excluded.commission,
                    slippage = excluded.slippage,
                    asset_class = excluded.asset_class,
                    execution_mode = excluded.execution_mode,
                    provider_name = excluded.provider_name,
                    broker_order_id = excluded.broker_order_id,
                    source = excluded.source,
                    source_ref = excluded.source_ref,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    fill_id,
                    order_id,
                    timestamp,
                    symbol,
                    side,
                    fill_price,
                    fill_quantity,
                    commission,
                    slippage,
                    asset_class,
                    execution_mode,
                    provider_name,
                    broker_order_id,
                    source,
                    source_ref,
                    metadata_json,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM fills WHERE fill_id = ?",
                (fill_id,),
            ).fetchone()
            if row is not None:
                _insert_event_sync(
                    conn,
                    event_type="order.fill.recorded",
                    timestamp=row["timestamp"],
                    entity_type="fill",
                    entity_id=row["fill_id"],
                    source="fills",
                    source_ref=row["fill_id"],
                    payload=_fill_event_payload(row),
                )
            conn.commit()
            return int(row["id"]) if row is not None else 0

    def get_fill_sync(self, fill_id: str) -> dict[str, Any] | None:
        """Read one persisted execution fill by ID."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM fills WHERE fill_id = ?",
                (fill_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_fills_sync(
        self,
        *,
        order_id: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List persisted execution fills newest first."""
        conditions: list[str] = []
        params: list[Any] = []
        if order_id is not None:
            conditions.append("order_id = ?")
            params.append(order_id)
        if symbol is not None:
            conditions.append("symbol = ?")
            params.append(symbol)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM fills
                {where_clause}
                ORDER BY timestamp DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(row) for row in rows]

    # ---------- Backtest Results ----------

    async def save_backtest_result(
        self,
        config_json: str,
        initial_cash: float,
        final_equity: float,
        total_return: float,
        sharpe: float,
        max_dd: float,
        equity_curve_json: str,
        annual_return: float = 0.0,
        sortino: float = 0.0,
        win_rate: float = 0.0,
        duration_days: int = 0,
        metrics_json: str = "{}",
        cost_summary_json: str = "{}",
    ) -> int:
        """保存回测结果，返回 ID。"""
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                """INSERT INTO backtest_results
                   (created_at, config_json, initial_cash, final_equity, total_return,
                    sharpe, sortino, max_drawdown, win_rate, duration_days,
                    equity_curve_json, metrics_json, cost_summary_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now().isoformat(),
                    config_json,
                    initial_cash,
                    final_equity,
                    total_return,
                    sharpe,
                    sortino,
                    max_dd,
                    win_rate,
                    duration_days,
                    equity_curve_json,
                    metrics_json,
                    cost_summary_json,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    async def get_backtest_results(self) -> list[dict[str, Any]]:
        """获取所有回测结果摘要。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""SELECT id, created_at, config_json, initial_cash,
                          final_equity, total_return, sharpe, max_drawdown,
                          equity_curve_json, metrics_json, cost_summary_json
                   FROM backtest_results ORDER BY id DESC""").fetchall()
            return [dict(row) for row in rows]

    async def get_backtest_result(self, result_id: int) -> dict[str, Any] | None:
        """获取单个回测结果详情。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM backtest_results WHERE id = ?", (result_id,)
            ).fetchone()
            return dict(row) if row else None

    # ---------- Quote Fetch Runs ----------

    def save_valuation_snapshot_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist one immutable, content-addressed valuation snapshot."""
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT OR IGNORE INTO valuation_snapshots (
                    snapshot_id, as_of, trade_date, valuation_policy,
                    ledger_cutoff_id, ledger_fingerprint, quote_set_fingerprint,
                    status, quotes_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["snapshot_id"],
                    payload["as_of"],
                    payload["trade_date"],
                    payload["valuation_policy"],
                    int(payload.get("ledger_cutoff_id") or 0),
                    payload["ledger_fingerprint"],
                    payload["quote_set_fingerprint"],
                    payload["status"],
                    _serialize_metadata_json(payload.get("quotes") or []),
                    _serialize_metadata_json(payload.get("metadata") or {}),
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM valuation_snapshots WHERE snapshot_id = ?",
                (payload["snapshot_id"],),
            ).fetchone()
            if row is None:
                raise RuntimeError("valuation snapshot persistence failed")
            return dict(row)

    def publish_current_valuation_snapshot_sync(self) -> dict[str, Any]:
        """Build and persist the immutable snapshot for committed facts."""
        from server.services.valuation_snapshot import build_current_valuation_snapshot

        snapshot = build_current_valuation_snapshot(self, persist=True)
        self.set_runtime_control_sync(
            "valuation_snapshot_publication",
            {
                "status": "ready",
                "snapshot_id": snapshot["snapshot_id"],
                "as_of": snapshot["as_of"],
            },
        )
        return snapshot

    def get_valuation_snapshot_sync(self, snapshot_id: str) -> dict[str, Any] | None:
        """Read one immutable valuation snapshot by content id."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM valuation_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            return dict(row) if row else None

    # ---------- Quote Fetch Runs ----------

    def create_quote_fetch_run(
        self,
        *,
        run_id: str,
        started_at: str,
        trigger: str,
        status: str,
        provider: str | None = None,
        asset_type: str | None = None,
        symbol_count: int = 0,
        success_count: int = 0,
        failure_count: int = 0,
        cache_hit_count: int = 0,
        error_message: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> int:
        """Create one quote fetch run audit row."""
        payload = {
            "run_id": run_id,
            "started_at": started_at,
            "trigger": trigger,
            "provider": provider,
            "asset_type": asset_type,
            "symbol_count": symbol_count,
            "success_count": success_count,
            "failure_count": failure_count,
            "cache_hit_count": cache_hit_count,
            "status": status,
            "error_message": error_message,
            "metadata": _metadata_payload_value(metadata),
        }
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO quote_fetch_runs (
                    run_id, started_at, trigger, provider, asset_type, symbol_count,
                    success_count, failure_count, cache_hit_count, status,
                    error_message, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    started_at,
                    trigger,
                    provider,
                    asset_type,
                    symbol_count,
                    success_count,
                    failure_count,
                    cache_hit_count,
                    status,
                    error_message,
                    _serialize_metadata_json(metadata),
                ),
            )
            _insert_event_sync(
                conn,
                event_type="task_run.started",
                timestamp=started_at,
                entity_type="task_run",
                entity_id=run_id,
                source="quote_fetch_runs",
                source_ref=run_id,
                payload=payload,
            )
            conn.commit()
            return cursor.lastrowid or 0

    def finish_quote_fetch_run(
        self,
        *,
        run_id: str,
        finished_at: str,
        status: str,
        success_count: int = 0,
        failure_count: int = 0,
        cache_hit_count: int = 0,
        error_message: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> dict[str, Any] | None:
        """Mark a quote fetch run as finished and return the updated row."""
        successful_statuses = {"success", "partial", "partial_success"}
        if success_count > 0 and status in successful_statuses:
            try:
                valuation_snapshot = self.publish_current_valuation_snapshot_sync()
                metadata_value = _metadata_payload_value(metadata)
                if isinstance(metadata_value, dict):
                    metadata = {
                        **metadata_value,
                        "valuation_snapshot_id": valuation_snapshot["snapshot_id"],
                    }
            except Exception as exc:
                logger.exception(
                    "Failed to publish valuation snapshot for quote run %s", run_id
                )
                status = "failed"
                error_message = (
                    f"valuation snapshot publication failed: {type(exc).__name__}"
                )
                metadata_value = _metadata_payload_value(metadata)
                if isinstance(metadata_value, dict):
                    metadata = {
                        **metadata_value,
                        "valuation_snapshot_publication": "failed",
                    }
        metadata_json = _serialize_metadata_json(metadata)
        metadata_payload = _metadata_payload_value(metadata)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            if metadata_json is None:
                conn.execute(
                    """
                    UPDATE quote_fetch_runs
                    SET finished_at = ?,
                        status = ?,
                        success_count = ?,
                        failure_count = ?,
                        cache_hit_count = ?,
                        error_message = ?
                    WHERE run_id = ?
                    """,
                    (
                        finished_at,
                        status,
                        success_count,
                        failure_count,
                        cache_hit_count,
                        error_message,
                        run_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE quote_fetch_runs
                    SET finished_at = ?,
                        status = ?,
                        success_count = ?,
                        failure_count = ?,
                        cache_hit_count = ?,
                        error_message = ?,
                        metadata_json = ?
                    WHERE run_id = ?
                    """,
                    (
                        finished_at,
                        status,
                        success_count,
                        failure_count,
                        cache_hit_count,
                        error_message,
                        metadata_json,
                        run_id,
                    ),
                )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM quote_fetch_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is not None:
                _insert_event_sync(
                    conn,
                    event_type="task_run.completed",
                    timestamp=finished_at,
                    entity_type="task_run",
                    entity_id=run_id,
                    source="quote_fetch_runs",
                    source_ref=run_id,
                    payload={
                        "run_id": row["run_id"],
                        "started_at": row["started_at"],
                        "finished_at": row["finished_at"],
                        "trigger": row["trigger"],
                        "provider": row["provider"],
                        "asset_type": row["asset_type"],
                        "symbol_count": row["symbol_count"],
                        "success_count": row["success_count"],
                        "failure_count": row["failure_count"],
                        "cache_hit_count": row["cache_hit_count"],
                        "status": row["status"],
                        "error_message": row["error_message"],
                        "metadata": metadata_payload,
                    },
                )
                conn.commit()
            return dict(row) if row else None

    def get_quote_fetch_run(self, run_id: str) -> dict[str, Any] | None:
        """Read one quote fetch run by run_id."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM quote_fetch_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_quote_fetch_runs(
        self,
        limit: int = 50,
        trigger: str | None = None,
        status: str | None = None,
        provider: str | None = None,
    ) -> list[dict[str, Any]]:
        """List quote fetch runs, newest first."""
        conditions: list[str] = []
        params: list[Any] = []
        if trigger is not None:
            conditions.append("trigger = ?")
            params.append(trigger)
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if provider is not None:
            conditions.append("provider = ?")
            params.append(provider)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM quote_fetch_runs
                {where_clause}
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    # ---------- Event Log ----------

    def append_event_sync(
        self,
        *,
        event_type: str,
        timestamp: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        source: str = "app",
        source_ref: str | None = None,
        payload: dict[str, Any] | str | None = None,
    ) -> int:
        """Append one normalized domain event to the shared event stream."""
        with sqlite3.connect(self._path) as conn:
            cursor = _insert_event_sync(
                conn,
                event_type=event_type,
                timestamp=timestamp,
                entity_type=entity_type,
                entity_id=entity_id,
                source=source,
                source_ref=source_ref,
                payload=payload,
            )
            conn.commit()
            return cursor.lastrowid or 0

    def list_events_sync(
        self,
        *,
        event_type: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        source: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List normalized domain events newest first."""
        conditions: list[str] = []
        params: list[Any] = []
        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)
        if entity_type is not None:
            conditions.append("entity_type = ?")
            params.append(entity_type)
        if entity_id is not None:
            conditions.append("entity_id = ?")
            params.append(entity_id)
        if source is not None:
            conditions.append("source = ?")
            params.append(source)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM event_log
                {where_clause}
                ORDER BY timestamp DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(row) for row in rows]

    # ---------- Controlled Session Budget Reservations ----------

    def reserve_controlled_session_budget_sync(
        self,
        *,
        reservation: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically reserve bounded capital without issuing execution authority."""
        requested = dict(reservation)
        money_fields = (
            "reserved_gross_units",
            "reserved_buy_units",
            "reserved_turnover_units",
            "capital_capacity_units",
            "cash_capacity_units",
            "turnover_capacity_units",
        )
        count_fields = ("reserved_order_count", "order_count_capacity")
        try:
            requested_by_symbol = {
                str(symbol): int(value)
                for symbol, value in (
                    requested.get("reserved_by_symbol_units") or {}
                ).items()
            }
            symbol_capacities = {
                str(symbol): int(value)
                for symbol, value in (
                    requested.get("symbol_capacity_units") or {}
                ).items()
            }
            invalid_money_units = any(
                int(requested.get(field) or 0) < 0 for field in money_fields
            )
            invalid_count_units = any(
                int(requested.get(field) or 0) <= 0 for field in count_fields
            )
        except (AttributeError, TypeError, ValueError):
            return _controlled_session_budget_rejection(
                requested,
                ["budget_reservation_units_invalid"],
            )
        if invalid_money_units:
            return _controlled_session_budget_rejection(
                requested,
                ["budget_reservation_money_units_invalid"],
            )
        if invalid_count_units:
            return _controlled_session_budget_rejection(
                requested,
                ["budget_reservation_order_count_invalid"],
            )
        if (
            not requested_by_symbol
            or set(requested_by_symbol) != set(symbol_capacities)
            or any(value < 0 for value in requested_by_symbol.values())
            or any(value <= 0 for value in symbol_capacities.values())
        ):
            return _controlled_session_budget_rejection(
                requested,
                ["budget_reservation_symbol_units_invalid"],
            )
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                    SELECT * FROM controlled_session_budget_reservations
                    WHERE reservation_id = ?
                    LIMIT 1
                    """,
                    (requested["reservation_id"],),
                ).fetchone()
                if existing is not None:
                    conn.commit()
                    return {
                        "status": "reserved",
                        "blockers": [],
                        "reused": True,
                        "reservation": dict(existing),
                    }
                attestation_conflict = conn.execute(
                    """
                    SELECT reservation_id
                    FROM controlled_session_budget_reservations
                    WHERE attestation_id = ?
                    LIMIT 1
                    """,
                    (requested["attestation_id"],),
                ).fetchone()
                if attestation_conflict is not None:
                    conn.rollback()
                    return _controlled_session_budget_rejection(
                        requested,
                        ["budget_reservation_attestation_already_reserved"],
                    )

                scope = (
                    requested["authorization_id"],
                    requested["account_alias"],
                )
                overlap = conn.execute(
                    """
                    SELECT
                        COALESCE(SUM(reserved_gross_units), 0) AS gross_units,
                        COALESCE(SUM(reserved_buy_units), 0) AS buy_units,
                        COALESCE(SUM(reserved_order_count), 0) AS order_count,
                        MIN(order_count_capacity) AS minimum_order_capacity
                    FROM controlled_session_budget_reservations
                    WHERE authorization_id = ?
                      AND account_alias = ?
                      AND status = 'reserved'
                      AND requested_start_at < ?
                      AND requested_expires_at > ?
                    """,
                    (
                        *scope,
                        requested["requested_expires_at"],
                        requested["requested_start_at"],
                    ),
                ).fetchone()
                overlap_symbol_rows = conn.execute(
                    """
                    SELECT reserved_by_symbol_json, symbol_capacity_json
                    FROM controlled_session_budget_reservations
                    WHERE authorization_id = ?
                      AND account_alias = ?
                      AND status = 'reserved'
                      AND requested_start_at < ?
                      AND requested_expires_at > ?
                    """,
                    (
                        *scope,
                        requested["requested_expires_at"],
                        requested["requested_start_at"],
                    ),
                ).fetchall()
                daily = conn.execute(
                    """
                    SELECT COALESCE(SUM(reserved_turnover_units), 0) AS turnover_units
                    FROM controlled_session_budget_reservations
                    WHERE authorization_id = ?
                      AND account_alias = ?
                      AND trading_day = ?
                      AND status = 'reserved'
                    """,
                    (*scope, requested["trading_day"]),
                ).fetchone()
                before = {
                    "overlapping_gross_units": int(overlap["gross_units"] or 0),
                    "overlapping_buy_units": int(overlap["buy_units"] or 0),
                    "overlapping_order_count": int(overlap["order_count"] or 0),
                    "daily_turnover_units": int(daily["turnover_units"] or 0),
                    "overlapping_by_symbol_units": {
                        symbol: 0 for symbol in sorted(requested_by_symbol)
                    },
                }
                effective_symbol_capacities = dict(symbol_capacities)
                symbol_evidence_blockers: list[str] = []
                for row in overlap_symbol_rows:
                    existing_reserved = _json_dict(row["reserved_by_symbol_json"])
                    existing_capacities = _json_dict(row["symbol_capacity_json"])
                    if not existing_reserved or not existing_capacities:
                        symbol_evidence_blockers.extend(
                            f"atomic_existing_symbol_budget_evidence_missing:{symbol}"
                            for symbol in requested_by_symbol
                        )
                        continue
                    for symbol in requested_by_symbol:
                        reserved_present = symbol in existing_reserved
                        capacity_present = symbol in existing_capacities
                        if reserved_present != capacity_present:
                            symbol_evidence_blockers.append(
                                f"atomic_existing_symbol_budget_evidence_missing:{symbol}"
                            )
                            continue
                        if not reserved_present:
                            continue
                        before["overlapping_by_symbol_units"][symbol] += int(
                            existing_reserved[symbol]
                        )
                        effective_symbol_capacities[symbol] = min(
                            effective_symbol_capacities[symbol],
                            int(existing_capacities[symbol]),
                        )
                minimum_order_capacity = min(
                    int(requested["order_count_capacity"]),
                    int(
                        overlap["minimum_order_capacity"]
                        or requested["order_count_capacity"]
                    ),
                )
                after = {
                    "overlapping_gross_units": before["overlapping_gross_units"]
                    + int(requested["reserved_gross_units"]),
                    "overlapping_buy_units": before["overlapping_buy_units"]
                    + int(requested["reserved_buy_units"]),
                    "overlapping_order_count": before["overlapping_order_count"]
                    + int(requested["reserved_order_count"]),
                    "daily_turnover_units": before["daily_turnover_units"]
                    + int(requested["reserved_turnover_units"]),
                    "overlapping_by_symbol_units": {
                        symbol: before["overlapping_by_symbol_units"][symbol]
                        + requested_by_symbol[symbol]
                        for symbol in sorted(requested_by_symbol)
                    },
                }
                blockers: list[str] = list(dict.fromkeys(symbol_evidence_blockers))
                if after["overlapping_gross_units"] > int(
                    requested["capital_capacity_units"]
                ):
                    blockers.append("atomic_capital_budget_unavailable")
                if after["overlapping_buy_units"] > int(
                    requested["cash_capacity_units"]
                ):
                    blockers.append("atomic_cash_budget_unavailable")
                if after["daily_turnover_units"] > int(
                    requested["turnover_capacity_units"]
                ):
                    blockers.append("atomic_daily_turnover_budget_unavailable")
                if after["overlapping_order_count"] > minimum_order_capacity:
                    blockers.append("atomic_order_count_budget_unavailable")
                for symbol, after_units in after["overlapping_by_symbol_units"].items():
                    if after_units > effective_symbol_capacities[symbol]:
                        blockers.append(f"atomic_symbol_budget_unavailable:{symbol}")
                if blockers:
                    conn.rollback()
                    return _controlled_session_budget_rejection(
                        requested,
                        blockers,
                        before=before,
                        after=after,
                    )

                created_at = str(requested["created_at"])
                conn.execute(
                    """
                    INSERT INTO controlled_session_budget_reservations (
                        reservation_id, attestation_id, envelope_fingerprint,
                        capital_evaluation_input_fingerprint, authorization_id,
                        policy_version, account_alias, strategy_id, trading_day,
                        requested_start_at, requested_expires_at,
                        reserved_gross_units, reserved_buy_units,
                        reserved_turnover_units, reserved_order_count,
                        capital_capacity_units, cash_capacity_units,
                        turnover_capacity_units, order_count_capacity,
                        reserved_by_symbol_json, symbol_capacity_json,
                        status, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["reservation_id"],
                        requested["attestation_id"],
                        requested["envelope_fingerprint"],
                        requested["capital_evaluation_input_fingerprint"],
                        requested["authorization_id"],
                        requested["policy_version"],
                        requested["account_alias"],
                        requested["strategy_id"],
                        requested["trading_day"],
                        requested["requested_start_at"],
                        requested["requested_expires_at"],
                        int(requested["reserved_gross_units"]),
                        int(requested["reserved_buy_units"]),
                        int(requested["reserved_turnover_units"]),
                        int(requested["reserved_order_count"]),
                        int(requested["capital_capacity_units"]),
                        int(requested["cash_capacity_units"]),
                        int(requested["turnover_capacity_units"]),
                        int(requested["order_count_capacity"]),
                        _serialize_event_payload_json(requested_by_symbol),
                        _serialize_event_payload_json(symbol_capacities),
                        "reserved",
                        _serialize_event_payload_json(requested["payload"]),
                        created_at,
                    ),
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_session_budget_reservations
                    WHERE reservation_id = ?
                    LIMIT 1
                    """,
                    (requested["reservation_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "reserved",
                    "blockers": [],
                    "reused": False,
                    "reservation": dict(saved) if saved is not None else {},
                    "aggregate_before": before,
                    "aggregate_after": after,
                }
            except (sqlite3.OperationalError, TypeError, ValueError):
                conn.rollback()
                return _controlled_session_budget_rejection(
                    requested,
                    ["budget_reservation_transaction_unavailable"],
                )

    def list_controlled_session_budget_reservations_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable reservation records newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_session_budget_reservations
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_controlled_session_budget_reservation_sync(
        self,
        reservation_id: str,
    ) -> dict[str, Any] | None:
        """Read one reservation by its deterministic id."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_session_budget_reservations
                WHERE reservation_id = ?
                LIMIT 1
                """,
                (reservation_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    # ---------- Controlled Session Runtime Authority ----------

    def issue_controlled_session_sync(
        self,
        *,
        session: dict[str, Any],
    ) -> dict[str, Any]:
        """Issue one persisted bounded session for one exact reservation."""
        requested = dict(session)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ? OR reservation_id = ?
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (requested["session_id"], requested["reservation_id"]),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["session_id"] == requested["session_id"]
                        and existing["session_fingerprint"]
                        == requested["session_fingerprint"]
                        and existing["issuance_fingerprint"]
                        == requested["issuance_fingerprint"]
                        and existing["reservation_id"] == requested["reservation_id"]
                    ):
                        conn.commit()
                        return {
                            "status": str(existing["status"]),
                            "blockers": [],
                            "reused": True,
                            "session": dict(existing),
                        }
                    conn.rollback()
                    return _controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_reservation_or_identity_conflict"],
                    )

                reservation = conn.execute(
                    """
                    SELECT * FROM controlled_session_budget_reservations
                    WHERE reservation_id = ?
                    LIMIT 1
                    """,
                    (requested["reservation_id"],),
                ).fetchone()
                if reservation is None:
                    conn.rollback()
                    return _controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_reservation_not_found"],
                    )
                reservation_blockers: list[str] = []
                for field in (
                    "attestation_id",
                    "envelope_fingerprint",
                    "authorization_id",
                    "account_alias",
                    "strategy_id",
                    "requested_start_at",
                    "requested_expires_at",
                ):
                    if str(reservation[field] or "") != str(requested[field] or ""):
                        reservation_blockers.append(
                            f"runtime_session_reservation_{field}_mismatch"
                        )
                if str(reservation["status"] or "") != "reserved":
                    reservation_blockers.append(
                        "runtime_session_reservation_not_reserved"
                    )
                if reservation_blockers:
                    conn.rollback()
                    return _controlled_session_authority_rejection(
                        requested,
                        reservation_blockers,
                    )

                conn.execute(
                    """
                    INSERT INTO controlled_session_runtime_sessions (
                        session_id, session_fingerprint, issuance_fingerprint,
                        reservation_id, attestation_id, envelope_fingerprint,
                        authorization_id, account_alias, strategy_id,
                        operator_id, operator_approval_id, order_ids_json,
                        effective_at_epoch_ms, expires_at_epoch_ms,
                        effective_at, expires_at, max_order_rate_per_minute,
                        token_salt, token_hash, status, payload_json, created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["issuance_fingerprint"],
                        requested["reservation_id"],
                        requested["attestation_id"],
                        requested["envelope_fingerprint"],
                        requested["authorization_id"],
                        requested["account_alias"],
                        requested["strategy_id"],
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        _serialize_event_payload_json(requested["order_ids"]),
                        int(requested["effective_at_epoch_ms"]),
                        int(requested["expires_at_epoch_ms"]),
                        requested["requested_start_at"],
                        requested["requested_expires_at"],
                        int(requested["max_order_rate_per_minute"]),
                        requested["token_salt"],
                        requested["token_hash"],
                        "enabled",
                        _serialize_event_payload_json(requested["payload"]),
                        requested["created_at"],
                        requested["created_at"],
                    ),
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "enabled",
                    "blockers": [],
                    "reused": False,
                    "session": dict(saved) if saved is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()
                return _controlled_session_authority_rejection(
                    requested,
                    ["runtime_session_issuance_transaction_unavailable"],
                )

    def replace_paused_controlled_session_sync(
        self,
        *,
        replacement: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically retire one paused session and issue one bounded replacement."""
        requested = dict(replacement)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing_event = conn.execute(
                    """
                    SELECT * FROM controlled_session_replacement_events
                    WHERE replacement_id = ? OR predecessor_session_id = ?
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (
                        requested["replacement_id"],
                        requested["predecessor_session_id"],
                    ),
                ).fetchone()
                if existing_event is not None:
                    if (
                        existing_event["replacement_id"] == requested["replacement_id"]
                        and existing_event["replacement_fingerprint"]
                        == requested["replacement_fingerprint"]
                        and existing_event["replacement_session_id"]
                        == requested["session_id"]
                    ):
                        existing_session = conn.execute(
                            """
                            SELECT * FROM controlled_session_runtime_sessions
                            WHERE session_id = ?
                            LIMIT 1
                            """,
                            (requested["session_id"],),
                        ).fetchone()
                        conn.commit()
                        return {
                            "status": str(existing_session["status"]),
                            "blockers": [],
                            "reused": True,
                            "session": (
                                dict(existing_session)
                                if existing_session is not None
                                else {}
                            ),
                            "replacement": dict(existing_event),
                        }
                    conn.rollback()
                    return _controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_replacement_conflict"],
                    )

                predecessor = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["predecessor_session_id"],),
                ).fetchone()
                pause_state = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_states
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["predecessor_session_id"],),
                ).fetchone()
                if predecessor is None or pause_state is None:
                    conn.rollback()
                    return _controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_replacement_paused_predecessor_missing"],
                    )
                predecessor_blockers: list[str] = []
                if predecessor["status"] != "enabled":
                    predecessor_blockers.append(
                        "runtime_session_replacement_predecessor_not_enabled"
                    )
                if (
                    predecessor["session_fingerprint"]
                    != requested["predecessor_session_fingerprint"]
                ):
                    predecessor_blockers.append(
                        "runtime_session_replacement_predecessor_identity_mismatch"
                    )
                if (
                    pause_state["status"] != "paused"
                    or pause_state["pause_event_id"] != requested["pause_event_id"]
                ):
                    predecessor_blockers.append(
                        "runtime_session_replacement_pause_identity_mismatch"
                    )
                if predecessor_blockers:
                    conn.rollback()
                    return _controlled_session_authority_rejection(
                        requested,
                        predecessor_blockers,
                    )

                existing_session = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ? OR reservation_id = ?
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (requested["session_id"], requested["reservation_id"]),
                ).fetchone()
                if existing_session is not None:
                    conn.rollback()
                    return _controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_replacement_target_conflict"],
                    )

                old_reservation = conn.execute(
                    """
                    SELECT * FROM controlled_session_budget_reservations
                    WHERE reservation_id = ?
                    LIMIT 1
                    """,
                    (predecessor["reservation_id"],),
                ).fetchone()
                reservation = conn.execute(
                    """
                    SELECT * FROM controlled_session_budget_reservations
                    WHERE reservation_id = ?
                    LIMIT 1
                    """,
                    (requested["reservation_id"],),
                ).fetchone()
                if old_reservation is None or reservation is None:
                    conn.rollback()
                    return _controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_replacement_reservation_missing"],
                    )
                reservation_blockers: list[str] = []
                for field in (
                    "attestation_id",
                    "envelope_fingerprint",
                    "authorization_id",
                    "account_alias",
                    "strategy_id",
                    "requested_start_at",
                    "requested_expires_at",
                ):
                    if str(reservation[field] or "") != str(requested[field] or ""):
                        reservation_blockers.append(
                            f"runtime_session_replacement_reservation_{field}_mismatch"
                        )
                if reservation["status"] != "reserved":
                    reservation_blockers.append(
                        "runtime_session_replacement_reservation_not_reserved"
                    )
                for field in ("authorization_id", "account_alias", "strategy_id"):
                    if str(old_reservation[field] or "") != str(
                        reservation[field] or ""
                    ):
                        reservation_blockers.append(
                            f"runtime_session_replacement_scope_widened:{field}"
                        )
                for field in (
                    "reserved_gross_units",
                    "reserved_buy_units",
                    "reserved_turnover_units",
                    "reserved_order_count",
                ):
                    if int(reservation[field]) > int(old_reservation[field]):
                        reservation_blockers.append(
                            f"runtime_session_replacement_budget_widened:{field}"
                        )
                old_symbols = {
                    str(key): int(value)
                    for key, value in _json_dict(
                        old_reservation["reserved_by_symbol_json"]
                    ).items()
                }
                replacement_symbols = {
                    str(key): int(value)
                    for key, value in _json_dict(
                        reservation["reserved_by_symbol_json"]
                    ).items()
                }
                if not replacement_symbols or not set(replacement_symbols).issubset(
                    old_symbols
                ):
                    reservation_blockers.append(
                        "runtime_session_replacement_symbol_scope_widened"
                    )
                elif any(
                    value > old_symbols[symbol]
                    for symbol, value in replacement_symbols.items()
                ):
                    reservation_blockers.append(
                        "runtime_session_replacement_symbol_budget_widened"
                    )
                old_order_ids = set(_json_list(predecessor["order_ids_json"]))
                if not set(requested["order_ids"]).issubset(old_order_ids):
                    reservation_blockers.append(
                        "runtime_session_replacement_order_scope_widened"
                    )
                if int(requested["max_order_rate_per_minute"]) > int(
                    predecessor["max_order_rate_per_minute"]
                ):
                    reservation_blockers.append(
                        "runtime_session_replacement_rate_widened"
                    )
                old_duration = int(predecessor["expires_at_epoch_ms"]) - int(
                    predecessor["effective_at_epoch_ms"]
                )
                new_duration = int(requested["expires_at_epoch_ms"]) - int(
                    requested["effective_at_epoch_ms"]
                )
                if new_duration <= 0 or new_duration > old_duration:
                    reservation_blockers.append(
                        "runtime_session_replacement_duration_widened"
                    )
                if int(requested["effective_at_epoch_ms"]) < int(
                    pause_state["paused_at_epoch_ms"]
                ):
                    reservation_blockers.append(
                        "runtime_session_replacement_starts_before_pause"
                    )
                now_epoch_ms = int(requested["reviewed_at_epoch_ms"])
                if not (
                    int(requested["effective_at_epoch_ms"])
                    <= now_epoch_ms
                    < int(requested["expires_at_epoch_ms"])
                ):
                    reservation_blockers.append(
                        "runtime_session_replacement_window_not_current"
                    )
                if reservation_blockers:
                    conn.rollback()
                    return _controlled_session_authority_rejection(
                        requested,
                        reservation_blockers,
                    )

                snapshots = conn.execute(
                    """
                    SELECT * FROM controlled_session_gate_snapshots
                    WHERE snapshot_id IN (?, ?)
                    ORDER BY observed_at_epoch_ms ASC, id ASC
                    """,
                    tuple(requested["recovery_snapshot_ids"]),
                ).fetchall()
                snapshot_blockers: list[str] = []
                if len(snapshots) != 2:
                    snapshot_blockers.append(
                        "runtime_session_replacement_recovery_snapshots_missing"
                    )
                else:
                    for snapshot in snapshots:
                        if (
                            snapshot["session_id"]
                            != requested["predecessor_session_id"]
                            or snapshot["status"] != "clear"
                            or _json_list(snapshot["blockers_json"])
                        ):
                            snapshot_blockers.append(
                                "runtime_session_replacement_recovery_snapshot_not_clear"
                            )
                    first_ms = int(snapshots[0]["observed_at_epoch_ms"])
                    last_ms = int(snapshots[-1]["observed_at_epoch_ms"])
                    latest_snapshot = conn.execute(
                        """
                        SELECT * FROM controlled_session_gate_snapshots
                        WHERE session_id = ? AND observed_at_epoch_ms > ?
                        ORDER BY observed_at_epoch_ms DESC, id DESC
                        LIMIT 1
                        """,
                        (
                            requested["predecessor_session_id"],
                            int(pause_state["paused_at_epoch_ms"]),
                        ),
                    ).fetchone()
                    if (
                        latest_snapshot is None
                        or latest_snapshot["snapshot_id"]
                        != snapshots[-1]["snapshot_id"]
                    ):
                        snapshot_blockers.append(
                            "runtime_session_replacement_recovery_snapshot_superseded"
                        )
                    blocked_during_recovery = conn.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM controlled_session_gate_snapshots
                        WHERE session_id = ?
                          AND observed_at_epoch_ms >= ?
                          AND observed_at_epoch_ms <= ?
                          AND status != 'clear'
                        """,
                        (
                            requested["predecessor_session_id"],
                            first_ms,
                            now_epoch_ms,
                        ),
                    ).fetchone()
                    if int(blocked_during_recovery["count"] or 0) > 0:
                        snapshot_blockers.append(
                            "runtime_session_replacement_recovery_interrupted"
                        )
                    if first_ms <= int(pause_state["paused_at_epoch_ms"]):
                        snapshot_blockers.append(
                            "runtime_session_replacement_recovery_not_post_pause"
                        )
                    if last_ms - first_ms < int(
                        requested["minimum_recovery_stability_ms"]
                    ):
                        snapshot_blockers.append(
                            "runtime_session_replacement_recovery_not_stable"
                        )
                    if last_ms > now_epoch_ms or now_epoch_ms - last_ms > int(
                        requested["maximum_snapshot_age_ms"]
                    ):
                        snapshot_blockers.append(
                            "runtime_session_replacement_recovery_snapshot_stale"
                        )
                if snapshot_blockers:
                    conn.rollback()
                    return _controlled_session_authority_rejection(
                        requested,
                        snapshot_blockers,
                    )

                conn.execute(
                    """
                    INSERT INTO controlled_session_revocation_events (
                        revocation_id, revocation_fingerprint, session_id,
                        session_fingerprint, reason_code, operator_id,
                        operator_approval_id, revoked_at_epoch_ms, revoked_at,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["retirement_revocation_id"],
                        requested["retirement_revocation_fingerprint"],
                        requested["predecessor_session_id"],
                        requested["predecessor_session_fingerprint"],
                        "signed_replacement_after_pause_review",
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        now_epoch_ms,
                        requested["reviewed_at"],
                        _serialize_event_payload_json(requested["retirement_payload"]),
                        requested["created_at"],
                    ),
                )
                conn.execute(
                    """
                    UPDATE controlled_session_runtime_sessions
                    SET status = 'revoked', updated_at = ?
                    WHERE session_id = ? AND status = 'enabled'
                    """,
                    (requested["created_at"], requested["predecessor_session_id"]),
                )
                conn.execute(
                    """
                    INSERT INTO controlled_session_runtime_sessions (
                        session_id, session_fingerprint, issuance_fingerprint,
                        reservation_id, attestation_id, envelope_fingerprint,
                        authorization_id, account_alias, strategy_id,
                        operator_id, operator_approval_id, order_ids_json,
                        effective_at_epoch_ms, expires_at_epoch_ms,
                        effective_at, expires_at, max_order_rate_per_minute,
                        token_salt, token_hash, status, payload_json, created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["issuance_fingerprint"],
                        requested["reservation_id"],
                        requested["attestation_id"],
                        requested["envelope_fingerprint"],
                        requested["authorization_id"],
                        requested["account_alias"],
                        requested["strategy_id"],
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        _serialize_event_payload_json(requested["order_ids"]),
                        int(requested["effective_at_epoch_ms"]),
                        int(requested["expires_at_epoch_ms"]),
                        requested["requested_start_at"],
                        requested["requested_expires_at"],
                        int(requested["max_order_rate_per_minute"]),
                        requested["token_salt"],
                        requested["token_hash"],
                        "enabled",
                        _serialize_event_payload_json(requested["session_payload"]),
                        requested["created_at"],
                        requested["created_at"],
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO controlled_session_replacement_events (
                        replacement_id, replacement_fingerprint,
                        predecessor_session_id, predecessor_session_fingerprint,
                        pause_event_id, recovery_snapshot_ids_json,
                        replacement_session_id, replacement_session_fingerprint,
                        replacement_reservation_id, operator_id,
                        operator_approval_id, reviewed_at_epoch_ms, reviewed_at,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["replacement_id"],
                        requested["replacement_fingerprint"],
                        requested["predecessor_session_id"],
                        requested["predecessor_session_fingerprint"],
                        requested["pause_event_id"],
                        _serialize_event_payload_json(
                            requested["recovery_snapshot_ids"]
                        ),
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["reservation_id"],
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        now_epoch_ms,
                        requested["reviewed_at"],
                        _serialize_event_payload_json(requested["replacement_payload"]),
                        requested["created_at"],
                    ),
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                event = conn.execute(
                    """
                    SELECT * FROM controlled_session_replacement_events
                    WHERE replacement_id = ?
                    LIMIT 1
                    """,
                    (requested["replacement_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "enabled",
                    "blockers": [],
                    "reused": False,
                    "session": dict(saved) if saved is not None else {},
                    "replacement": dict(event) if event is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()
                return _controlled_session_authority_rejection(
                    requested,
                    ["runtime_session_replacement_transaction_unavailable"],
                )

    def revoke_controlled_session_sync(
        self,
        *,
        revocation: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist an operator-signed one-way session revocation."""
        requested = dict(revocation)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                session = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                if session is None:
                    conn.rollback()
                    return _controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_not_found"],
                    )
                if session["session_fingerprint"] != requested["session_fingerprint"]:
                    conn.rollback()
                    return _controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_revocation_identity_mismatch"],
                    )
                existing = conn.execute(
                    """
                    SELECT * FROM controlled_session_revocation_events
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                if session["status"] == "revoked":
                    if (
                        existing is None
                        or existing["revocation_id"] != requested["revocation_id"]
                        or existing["revocation_fingerprint"]
                        != requested["revocation_fingerprint"]
                        or existing["reason_code"] != requested["reason_code"]
                    ):
                        conn.rollback()
                        return _controlled_session_authority_rejection(
                            requested,
                            ["runtime_session_revocation_conflict"],
                        )
                    conn.commit()
                    return {
                        "status": "revoked",
                        "blockers": [],
                        "reused": True,
                        "session": dict(session),
                        "revocation": dict(existing) if existing is not None else {},
                    }
                if session["status"] != "enabled":
                    conn.rollback()
                    return _controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_not_enabled"],
                    )
                conn.execute(
                    """
                    INSERT INTO controlled_session_revocation_events (
                        revocation_id, revocation_fingerprint, session_id,
                        session_fingerprint, reason_code, operator_id,
                        operator_approval_id, revoked_at_epoch_ms, revoked_at,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["revocation_id"],
                        requested["revocation_fingerprint"],
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["reason_code"],
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        int(requested["revoked_at_epoch_ms"]),
                        requested["revoked_at"],
                        _serialize_event_payload_json(requested["payload"]),
                        requested["created_at"],
                    ),
                )
                conn.execute(
                    """
                    UPDATE controlled_session_runtime_sessions
                    SET status = 'revoked', updated_at = ?
                    WHERE session_id = ? AND status = 'enabled'
                    """,
                    (requested["created_at"], requested["session_id"]),
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                event = conn.execute(
                    """
                    SELECT * FROM controlled_session_revocation_events
                    WHERE revocation_id = ?
                    LIMIT 1
                    """,
                    (requested["revocation_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "revoked",
                    "blockers": [],
                    "reused": False,
                    "session": dict(saved) if saved is not None else {},
                    "revocation": dict(event) if event is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()
                return _controlled_session_authority_rejection(
                    requested,
                    ["runtime_session_revocation_transaction_unavailable"],
                )

    def get_controlled_session_runtime_session_sync(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Read one runtime session including private hash fields for verification."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_session_runtime_sessions
                WHERE session_id = ?
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_session_runtime_sessions_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List runtime sessions without interpreting current authority."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_session_runtime_sessions
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def find_enabled_paused_controlled_session_sync(
        self,
        *,
        authorization_id: str,
        account_alias: str,
        strategy_id: str,
        now_epoch_ms: int,
    ) -> dict[str, Any] | None:
        """Find active paused authority that requires signed replacement review."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT s.*, rs.pause_event_id, rs.paused_at_epoch_ms, rs.paused_at
                FROM controlled_session_runtime_sessions s
                JOIN controlled_session_runtime_states rs
                  ON rs.session_id = s.session_id
                WHERE s.authorization_id = ?
                  AND s.account_alias = ?
                  AND s.strategy_id = ?
                  AND s.status = 'enabled'
                  AND rs.status = 'paused'
                  AND s.expires_at_epoch_ms > ?
                ORDER BY rs.paused_at_epoch_ms DESC, s.id DESC
                LIMIT 1
                """,
                (
                    authorization_id,
                    account_alias,
                    strategy_id,
                    int(now_epoch_ms),
                ),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_session_replacements_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable signed replacement evidence newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_session_replacement_events
                ORDER BY reviewed_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_controlled_session_replacement_for_predecessor_sync(
        self,
        predecessor_session_id: str,
    ) -> dict[str, Any] | None:
        """Read immutable replacement evidence for one retired predecessor."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_session_replacement_events
                WHERE predecessor_session_id = ?
                LIMIT 1
                """,
                (predecessor_session_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_session_revocations_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable signed revocation evidence newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_session_revocation_events
                ORDER BY revoked_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    # ---------- Controlled Session Live Gate Snapshots ----------

    def record_controlled_session_gate_snapshot_sync(
        self,
        *,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one sanitized runtime-gate observation idempotently."""
        requested = dict(snapshot)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                session = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                if session is None:
                    conn.rollback()
                    return _controlled_session_gate_snapshot_rejection(
                        requested,
                        ["live_gate_session_not_found"],
                    )
                if session["session_fingerprint"] != requested["session_fingerprint"]:
                    conn.rollback()
                    return _controlled_session_gate_snapshot_rejection(
                        requested,
                        ["live_gate_session_identity_mismatch"],
                    )
                if session["status"] != "enabled":
                    conn.rollback()
                    return _controlled_session_gate_snapshot_rejection(
                        requested,
                        ["live_gate_session_not_enabled"],
                    )
                existing = conn.execute(
                    """
                    SELECT * FROM controlled_session_gate_snapshots
                    WHERE snapshot_id = ?
                    LIMIT 1
                    """,
                    (requested["snapshot_id"],),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["snapshot_fingerprint"]
                        != requested["snapshot_fingerprint"]
                        or existing["session_id"] != requested["session_id"]
                    ):
                        conn.rollback()
                        return _controlled_session_gate_snapshot_rejection(
                            requested,
                            ["live_gate_snapshot_identity_conflict"],
                        )
                    conn.commit()
                    return {
                        "status": str(existing["status"]),
                        "blockers": [],
                        "reused": True,
                        "snapshot": dict(existing),
                    }
                conn.execute(
                    """
                    INSERT INTO controlled_session_gate_snapshots (
                        snapshot_id, snapshot_fingerprint, session_id,
                        session_fingerprint, source_fingerprint,
                        observed_at_epoch_ms, observed_at, status,
                        gate_snapshot_json, source_evidence_json,
                        blockers_json, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["snapshot_id"],
                        requested["snapshot_fingerprint"],
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["source_fingerprint"],
                        int(requested["observed_at_epoch_ms"]),
                        requested["observed_at"],
                        requested["status"],
                        _serialize_event_payload_json(requested["gate_snapshot"]),
                        _serialize_event_payload_json(requested["source_evidence"]),
                        _serialize_event_payload_json(requested["blockers"]),
                        _serialize_event_payload_json(requested["payload"]),
                        requested["created_at"],
                    ),
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_session_gate_snapshots
                    WHERE snapshot_id = ?
                    LIMIT 1
                    """,
                    (requested["snapshot_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": requested["status"],
                    "blockers": [],
                    "reused": False,
                    "snapshot": dict(saved) if saved is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()
                return _controlled_session_gate_snapshot_rejection(
                    requested,
                    ["live_gate_snapshot_transaction_unavailable"],
                )

    def latest_controlled_session_gate_snapshot_sync(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Read the newest persisted gate snapshot for one session."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_session_gate_snapshots
                WHERE session_id = ?
                ORDER BY observed_at_epoch_ms DESC, id DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_session_gate_snapshots_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List sanitized runtime-gate snapshots newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_session_gate_snapshots
                ORDER BY observed_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_controlled_session_gate_snapshots_for_session_sync(
        self,
        *,
        session_id: str,
        since_epoch_ms: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List one session's persisted gate snapshots oldest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_session_gate_snapshots
                WHERE session_id = ? AND observed_at_epoch_ms >= ?
                ORDER BY observed_at_epoch_ms ASC, id ASC
                LIMIT ?
                """,
                (
                    session_id,
                    max(0, int(since_epoch_ms)),
                    max(1, min(int(limit), 500)),
                ),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_controlled_session_runtime_metrics_sync(
        self,
        *,
        session_id: str,
        window_start_epoch_ms: int,
        observed_at_epoch_ms: int,
    ) -> dict[str, Any]:
        """Read admission counters and the exact reserved order capacity."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT
                    s.session_id,
                    s.reservation_id,
                    s.max_order_rate_per_minute,
                    r.reserved_order_count,
                    COUNT(a.id) AS admitted_total,
                    SUM(
                        CASE
                            WHEN a.admitted_at_epoch_ms > ?
                             AND a.admitted_at_epoch_ms <= ?
                            THEN 1 ELSE 0
                        END
                    ) AS admitted_in_window,
                    MAX(a.admitted_at_epoch_ms) AS latest_admitted_at_epoch_ms
                FROM controlled_session_runtime_sessions s
                LEFT JOIN controlled_session_budget_reservations r
                  ON r.reservation_id = s.reservation_id
                LEFT JOIN controlled_session_rate_admissions a
                  ON a.session_id = s.session_id
                WHERE s.session_id = ?
                GROUP BY s.session_id, s.reservation_id,
                         s.max_order_rate_per_minute, r.reserved_order_count
                """,
                (
                    int(window_start_epoch_ms),
                    int(observed_at_epoch_ms),
                    session_id,
                ),
            ).fetchone()
            return dict(row) if row is not None else {}

    # ---------- Controlled Session Runtime Rate Admissions ----------

    def admit_controlled_session_order_sync(
        self,
        *,
        admission: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically admit one order under fresh gates and a shared rate window."""
        requested = dict(admission)
        try:
            now_epoch_ms = int(requested["admitted_at_epoch_ms"])
            requested_rate = int(requested["max_order_rate_per_minute"])
            gate_snapshot_max_age_ms = (
                int(requested["gate_snapshot_max_age_seconds"]) * 1000
            )
        except (KeyError, TypeError, ValueError):
            return _controlled_session_rate_admission_rejection(
                requested,
                ["runtime_rate_admission_input_invalid"],
            )
        if (
            now_epoch_ms < 0
            or requested_rate <= 0
            or gate_snapshot_max_age_ms <= 0
            or gate_snapshot_max_age_ms > 60_000
        ):
            return _controlled_session_rate_admission_rejection(
                requested,
                ["runtime_rate_admission_limit_invalid"],
            )
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                runtime_session = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                session_blockers: list[str] = []
                if runtime_session is None:
                    session_blockers.append("runtime_session_persistent_state_missing")
                else:
                    if runtime_session["status"] != "enabled":
                        session_blockers.append("runtime_session_not_enabled")
                    if (
                        runtime_session["session_fingerprint"]
                        != requested["session_fingerprint"]
                    ):
                        session_blockers.append("runtime_session_fingerprint_changed")
                    if runtime_session["reservation_id"] != requested["reservation_id"]:
                        session_blockers.append("runtime_session_reservation_changed")
                    if int(runtime_session["effective_at_epoch_ms"]) > now_epoch_ms:
                        session_blockers.append("runtime_session_not_yet_effective")
                    if int(runtime_session["expires_at_epoch_ms"]) <= now_epoch_ms:
                        session_blockers.append("runtime_session_expired")
                if session_blockers:
                    conn.rollback()
                    return _controlled_session_rate_admission_rejection(
                        requested,
                        session_blockers,
                    )
                pause_state = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_states
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                if pause_state is not None and pause_state["status"] == "paused":
                    conn.rollback()
                    return _controlled_session_rate_admission_rejection(
                        requested,
                        ["runtime_session_paused"],
                        pause_event_id=str(pause_state["pause_event_id"] or ""),
                    )
                latest_gate_snapshot = conn.execute(
                    """
                    SELECT * FROM controlled_session_gate_snapshots
                    WHERE session_id = ?
                    ORDER BY observed_at_epoch_ms DESC, id DESC
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                gate_blockers: list[str] = []
                if latest_gate_snapshot is None:
                    gate_blockers.append("runtime_live_gate_snapshot_missing")
                else:
                    if latest_gate_snapshot["status"] != "clear":
                        gate_blockers.append("runtime_live_gate_snapshot_not_clear")
                    if (
                        latest_gate_snapshot["session_fingerprint"]
                        != requested["session_fingerprint"]
                    ):
                        gate_blockers.append(
                            "runtime_live_gate_snapshot_session_identity_changed"
                        )
                    if (
                        latest_gate_snapshot["snapshot_id"]
                        != requested["gate_snapshot_id"]
                        or latest_gate_snapshot["snapshot_fingerprint"]
                        != requested["gate_snapshot_fingerprint"]
                        or latest_gate_snapshot["observed_at"]
                        != requested["gate_snapshot_observed_at"]
                    ):
                        gate_blockers.append(
                            "runtime_live_gate_snapshot_changed_before_admission"
                        )
                    gate_observed_at_epoch_ms = int(
                        latest_gate_snapshot["observed_at_epoch_ms"]
                    )
                    if gate_observed_at_epoch_ms > now_epoch_ms:
                        gate_blockers.append("runtime_live_gate_snapshot_in_future")
                    elif now_epoch_ms - gate_observed_at_epoch_ms > (
                        gate_snapshot_max_age_ms
                    ):
                        gate_blockers.append("runtime_live_gate_snapshot_stale")
                if gate_blockers:
                    conn.rollback()
                    return _controlled_session_rate_admission_rejection(
                        requested,
                        gate_blockers,
                    )
                existing = conn.execute(
                    """
                    SELECT * FROM controlled_session_rate_admissions
                    WHERE admission_id = ?
                    LIMIT 1
                    """,
                    (requested["admission_id"],),
                ).fetchone()
                if existing is not None:
                    conn.commit()
                    return {
                        "status": "admitted",
                        "blockers": [],
                        "reused": True,
                        "admission": dict(existing),
                    }
                order_conflict = conn.execute(
                    """
                    SELECT admission_id FROM controlled_session_rate_admissions
                    WHERE session_id = ? AND order_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"], requested["order_id"]),
                ).fetchone()
                request_conflict = conn.execute(
                    """
                    SELECT admission_id FROM controlled_session_rate_admissions
                    WHERE session_id = ? AND request_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"], requested["request_id"]),
                ).fetchone()
                conflict_blockers: list[str] = []
                if order_conflict is not None:
                    conflict_blockers.append("runtime_rate_order_already_admitted")
                if request_conflict is not None:
                    conflict_blockers.append("runtime_rate_request_id_reused")
                if conflict_blockers:
                    conn.rollback()
                    return _controlled_session_rate_admission_rejection(
                        requested,
                        conflict_blockers,
                    )

                window_start_epoch_ms = now_epoch_ms - 60_000
                window = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS admitted_count,
                        MIN(max_order_rate_per_minute) AS minimum_rate
                    FROM controlled_session_rate_admissions
                    WHERE authorization_id = ?
                      AND account_alias = ?
                      AND admitted_at_epoch_ms > ?
                      AND admitted_at_epoch_ms <= ?
                    """,
                    (
                        requested["authorization_id"],
                        requested["account_alias"],
                        window_start_epoch_ms,
                        now_epoch_ms,
                    ),
                ).fetchone()
                admitted_before = int(window["admitted_count"] or 0)
                effective_rate = min(
                    requested_rate,
                    int(window["minimum_rate"] or requested_rate),
                )
                if admitted_before >= effective_rate:
                    conn.rollback()
                    return _controlled_session_rate_admission_rejection(
                        requested,
                        ["runtime_order_rate_limit_reached"],
                        admitted_before=admitted_before,
                        admitted_after=admitted_before,
                        effective_rate=effective_rate,
                    )

                conn.execute(
                    """
                    INSERT INTO controlled_session_rate_admissions (
                        admission_id, session_id, session_fingerprint,
                        reservation_id, authorization_id, account_alias,
                        strategy_id, order_id, request_id,
                        max_order_rate_per_minute, admitted_at_epoch_ms,
                        admitted_at, status, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["admission_id"],
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["reservation_id"],
                        requested["authorization_id"],
                        requested["account_alias"],
                        requested["strategy_id"],
                        requested["order_id"],
                        requested["request_id"],
                        requested_rate,
                        now_epoch_ms,
                        requested["admitted_at"],
                        "admitted",
                        _serialize_event_payload_json(requested["payload"]),
                        requested["created_at"],
                    ),
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_session_rate_admissions
                    WHERE admission_id = ?
                    LIMIT 1
                    """,
                    (requested["admission_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "admitted",
                    "blockers": [],
                    "reused": False,
                    "admission": dict(saved) if saved is not None else {},
                    "admitted_before": admitted_before,
                    "admitted_after": admitted_before + 1,
                    "effective_rate": effective_rate,
                    "window_start_epoch_ms": window_start_epoch_ms,
                }
            except (sqlite3.IntegrityError, sqlite3.OperationalError, KeyError):
                conn.rollback()
                return _controlled_session_rate_admission_rejection(
                    requested,
                    ["runtime_rate_admission_transaction_unavailable"],
                )

    def list_controlled_session_rate_admissions_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable runtime rate-admission evidence newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_session_rate_admissions
                ORDER BY admitted_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    # ---------- Controlled Session Automatic Pause ----------

    def pause_controlled_session_sync(
        self,
        *,
        pause: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist the first automatic pause; no automatic resume path exists."""
        requested = dict(pause)
        reasons = [str(item) for item in requested.get("reasons") or [] if str(item)]
        if not reasons:
            return _controlled_session_pause_rejection(
                requested,
                ["automatic_pause_reason_missing"],
            )
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing_state = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_states
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                if existing_state is not None:
                    if (
                        existing_state["session_fingerprint"]
                        != requested["session_fingerprint"]
                    ):
                        conn.rollback()
                        return _controlled_session_pause_rejection(
                            requested,
                            ["automatic_pause_session_identity_conflict"],
                        )
                    existing_event = conn.execute(
                        """
                        SELECT * FROM controlled_session_pause_events
                        WHERE pause_event_id = ?
                        LIMIT 1
                        """,
                        (existing_state["pause_event_id"],),
                    ).fetchone()
                    conn.commit()
                    return {
                        "status": "paused",
                        "blockers": [],
                        "reused": True,
                        "state": dict(existing_state),
                        "event": (
                            dict(existing_event) if existing_event is not None else {}
                        ),
                    }

                conn.execute(
                    """
                    INSERT INTO controlled_session_pause_events (
                        pause_event_id, session_id, session_fingerprint,
                        reservation_id, gate_fingerprint, reason_fingerprint,
                        reasons_json, gate_snapshot_json, paused_at_epoch_ms,
                        paused_at, status, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["pause_event_id"],
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["reservation_id"],
                        requested["gate_fingerprint"],
                        requested["reason_fingerprint"],
                        _serialize_event_payload_json(reasons),
                        _serialize_event_payload_json(requested["gate_snapshot"]),
                        int(requested["paused_at_epoch_ms"]),
                        requested["paused_at"],
                        "paused",
                        _serialize_event_payload_json(requested["payload"]),
                        requested["created_at"],
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO controlled_session_runtime_states (
                        session_id, session_fingerprint, reservation_id,
                        status, pause_event_id, reason_fingerprint,
                        reasons_json, paused_at_epoch_ms, paused_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["reservation_id"],
                        "paused",
                        requested["pause_event_id"],
                        requested["reason_fingerprint"],
                        _serialize_event_payload_json(reasons),
                        int(requested["paused_at_epoch_ms"]),
                        requested["paused_at"],
                        requested["created_at"],
                    ),
                )
                state = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_states
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                event = conn.execute(
                    """
                    SELECT * FROM controlled_session_pause_events
                    WHERE pause_event_id = ?
                    LIMIT 1
                    """,
                    (requested["pause_event_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "paused",
                    "blockers": [],
                    "reused": False,
                    "state": dict(state) if state is not None else {},
                    "event": dict(event) if event is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()
                return _controlled_session_pause_rejection(
                    requested,
                    ["automatic_pause_transaction_unavailable"],
                )

    def get_controlled_session_runtime_state_sync(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Read the durable pause state for one session."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_session_runtime_states
                WHERE session_id = ?
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_controlled_session_pause_event_sync(
        self,
        pause_event_id: str,
    ) -> dict[str, Any] | None:
        """Read one immutable automatic-pause event by fingerprint."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_session_pause_events
                WHERE pause_event_id = ?
                LIMIT 1
                """,
                (pause_event_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_session_pause_events_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable automatic-pause evidence newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_session_pause_events
                ORDER BY paused_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    # ---------- Latest Quotes ----------

    def upsert_latest_quote_sync(
        self,
        *,
        symbol: str,
        asset_type: str = "stock",
        price: float,
        quote_timestamp: str,
        captured_at: str | None = None,
        previous_close: float | None = None,
        change: float | None = None,
        change_percent: float | None = None,
        volume: float | None = None,
        turnover: float | None = None,
        quote_source: str | None = None,
        provider_name: str | None = None,
        provider_status: str | None = None,
        quote_status: str = "live",
        stale_reason: str | None = None,
        captured_reason: str | None = None,
        nav_date: str | None = None,
        fetch_run_id: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> dict[str, Any] | None:
        """Upsert the current materialized quote for one instrument."""
        now = datetime.now().isoformat()
        captured_at_value = captured_at or now
        metadata_json = _serialize_metadata_json(metadata)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO latest_quotes (
                    symbol, asset_type, price, previous_close, change,
                    change_percent, volume, turnover, quote_timestamp,
                    quote_source, provider_name, provider_status, quote_status,
                    stale_reason, captured_at, captured_reason, nav_date,
                    fetch_run_id, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, asset_type) DO UPDATE SET
                    price = excluded.price,
                    previous_close = excluded.previous_close,
                    change = excluded.change,
                    change_percent = excluded.change_percent,
                    volume = excluded.volume,
                    turnover = excluded.turnover,
                    quote_timestamp = excluded.quote_timestamp,
                    quote_source = excluded.quote_source,
                    provider_name = excluded.provider_name,
                    provider_status = excluded.provider_status,
                    quote_status = excluded.quote_status,
                    stale_reason = excluded.stale_reason,
                    captured_at = excluded.captured_at,
                    captured_reason = excluded.captured_reason,
                    nav_date = excluded.nav_date,
                    fetch_run_id = excluded.fetch_run_id,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    symbol,
                    asset_type,
                    price,
                    previous_close,
                    change,
                    change_percent,
                    volume,
                    turnover,
                    quote_timestamp,
                    quote_source,
                    provider_name,
                    provider_status,
                    quote_status,
                    stale_reason,
                    captured_at_value,
                    captured_reason,
                    nav_date,
                    fetch_run_id,
                    metadata_json,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM latest_quotes
                WHERE symbol = ? AND asset_type = ?
                """,
                (symbol, asset_type),
            ).fetchone()
            if row is not None:
                _insert_event_sync(
                    conn,
                    event_type="market.quote.refreshed",
                    timestamp=row["quote_timestamp"],
                    entity_type="instrument",
                    entity_id=row["symbol"],
                    source="latest_quotes",
                    source_ref=str(row["id"]),
                    payload=_latest_quote_event_payload(row),
                )
            conn.commit()
            return dict(row) if row else None

    def get_latest_quote_sync(
        self, symbol: str, asset_type: str | None = None
    ) -> dict[str, Any] | None:
        """Read the materialized latest quote for one symbol."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            if asset_type is None:
                row = conn.execute(
                    """
                    SELECT *
                    FROM latest_quotes
                    WHERE symbol = ?
                    ORDER BY quote_timestamp DESC, updated_at DESC, id DESC
                    LIMIT 1
                    """,
                    (symbol,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT *
                    FROM latest_quotes
                    WHERE symbol = ? AND asset_type = ?
                    LIMIT 1
                    """,
                    (symbol, asset_type),
                ).fetchone()
            return dict(row) if row else None

    def list_latest_quotes_sync(self) -> list[dict[str, Any]]:
        """List materialized latest quotes newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT *
                FROM latest_quotes
                ORDER BY quote_timestamp DESC, updated_at DESC, id DESC
                """).fetchall()
            return [dict(row) for row in rows]

    # ---------- Quote Snapshots ----------

    def save_quote_snapshot_sync(
        self,
        symbol: str,
        asset_class: str,
        price: float,
        volume: float | None,
        timestamp: str,
        quote_source: str | None = None,
        provider_name: str | None = None,
        quote_status: str | None = None,
        stale_reason: str | None = None,
        provider_status: str | None = None,
        captured_reason: str | None = None,
        nav_date: str | None = None,
        fetch_run_id: str | None = None,
    ) -> None:
        """同步写入实时行情快照（后台线程调用）。"""
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                """INSERT INTO quote_snapshots
                   (
                       symbol, asset_class, price, volume, timestamp, created_at,
                       quote_source, provider_name, quote_status, stale_reason,
                       provider_status, captured_reason, nav_date, fetch_run_id
                   )
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    symbol,
                    asset_class,
                    price,
                    volume,
                    timestamp,
                    datetime.now().isoformat(),
                    quote_source,
                    provider_name,
                    quote_status,
                    stale_reason,
                    provider_status,
                    captured_reason,
                    nav_date,
                    fetch_run_id,
                ),
            )
            snapshot_id = cursor.lastrowid or 0
            _insert_event_sync(
                conn,
                event_type="market.quote.snapshot.recorded",
                timestamp=timestamp,
                entity_type="instrument",
                entity_id=symbol,
                source="quote_snapshots",
                source_ref=str(snapshot_id),
                payload={
                    "snapshot_id": snapshot_id,
                    "symbol": symbol,
                    "asset_class": asset_class,
                    "price": price,
                    "volume": volume,
                    "timestamp": timestamp,
                    "quote_source": quote_source,
                    "provider_name": provider_name,
                    "quote_status": quote_status,
                    "stale_reason": stale_reason,
                    "provider_status": provider_status,
                    "captured_reason": captured_reason,
                    "nav_date": nav_date,
                    "fetch_run_id": fetch_run_id,
                },
            )
            conn.commit()

    async def get_latest_quote(self, symbol: str) -> dict[str, Any] | None:
        """获取单个标的最新行情快照。"""
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT
                        id, symbol, asset_class, price, volume, timestamp,
                        quote_source, provider_name, quote_status, stale_reason,
                        provider_status, captured_reason, nav_date, fetch_run_id
                   FROM quote_snapshots
                   WHERE symbol = ?
                   ORDER BY id DESC""",
                (symbol,),
            )
            rows = [dict(row) for row in await cursor.fetchall()]
            return max(rows, key=_quote_observation_rank) if rows else None

    def get_latest_quotes_sync(self) -> list[dict[str, Any]]:
        """同步获取各标的最新行情快照，供启动恢复使用。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT
                    id, symbol, asset_class, price, volume, timestamp,
                    quote_source, provider_name, quote_status, stale_reason,
                    provider_status, captured_reason, nav_date, fetch_run_id,
                    created_at
                FROM quote_snapshots
                ORDER BY id
                """).fetchall()
            selected: dict[str, dict[str, Any]] = {}
            for raw_row in rows:
                row = dict(raw_row)
                existing = selected.get(str(row["symbol"]))
                if existing is None or _quote_observation_rank(
                    row
                ) > _quote_observation_rank(existing):
                    selected[str(row["symbol"])] = row
            return [selected[symbol] for symbol in sorted(selected)]

    def list_quote_snapshots_sync(self) -> list[dict[str, Any]]:
        """List append-only quote observations for canonical snapshot selection."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM quote_snapshots ORDER BY id").fetchall()
            return [dict(row) for row in rows]

    def get_recent_quote_snapshots_sync(
        self, symbol: str, limit: int = 2
    ) -> list[dict[str, Any]]:
        """同步获取单个标的最近的行情快照序列。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    id, symbol, asset_class, price, volume, timestamp,
                    quote_source, provider_name, quote_status, stale_reason,
                    provider_status, captured_reason, nav_date, fetch_run_id,
                    created_at
                FROM quote_snapshots
                WHERE symbol = ?
                ORDER BY id DESC
                """,
                (symbol,),
            ).fetchall()
            ordered = sorted(
                (dict(row) for row in rows),
                key=_quote_observation_rank,
                reverse=True,
            )
            return ordered[:limit]

    def save_daily_close_snapshot_sync(
        self,
        *,
        symbol: str,
        asset_class: str,
        trade_date: str,
        close_price: float,
        source: str,
    ) -> None:
        """同步写入日收盘基准。"""
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """
                INSERT INTO daily_close_snapshots
                    (symbol, asset_class, trade_date, close_price, source, captured_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, trade_date) DO UPDATE SET
                    asset_class = excluded.asset_class,
                    close_price = excluded.close_price,
                    source = excluded.source,
                    captured_at = excluded.captured_at
                """,
                (
                    symbol,
                    asset_class,
                    trade_date,
                    close_price,
                    source,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

    def get_latest_daily_close_before_sync(
        self, symbol: str, trade_date: str
    ) -> dict[str, Any] | None:
        """获取某日之前最近一个交易日收盘基准。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT symbol, asset_class, trade_date, close_price, source, captured_at
                FROM daily_close_snapshots
                WHERE symbol = ? AND trade_date < ?
                ORDER BY trade_date DESC, id DESC
                LIMIT 1
                """,
                (symbol, trade_date),
            ).fetchone()
            return dict(row) if row else None

    def get_latest_market_bar_before_date_sync(
        self, symbol: str, trade_date: str, frequency: str = "1d"
    ) -> dict[str, Any] | None:
        """Read the latest daily OHLC bar before trade_date from the data store."""
        meta_path = self._path.parent / "meta.db"
        if not meta_path.exists():
            return None
        try:
            with sqlite3.connect(meta_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT
                        symbol, frequency, timestamp, open, high, low, close,
                        volume, amount, created_at, updated_at
                    FROM market_bars
                    WHERE symbol = ? AND frequency = ? AND substr(timestamp, 1, 10) < ?
                    ORDER BY substr(timestamp, 1, 10) DESC, timestamp DESC
                    LIMIT 1
                    """,
                    (symbol, frequency, trade_date),
                ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        result = dict(row)
        result["trade_date"] = str(result["timestamp"])[:10]
        result["price"] = result["close"]
        result["source"] = "market_bars"
        return result

    def get_market_bar_on_date_sync(
        self, symbol: str, trade_date: str, frequency: str = "1d"
    ) -> dict[str, Any] | None:
        """Read the daily OHLC bar on trade_date from the data store."""
        meta_path = self._path.parent / "meta.db"
        if not meta_path.exists():
            return None
        try:
            with sqlite3.connect(meta_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT
                        symbol, frequency, timestamp, open, high, low, close,
                        volume, amount, created_at, updated_at
                    FROM market_bars
                    WHERE symbol = ? AND frequency = ? AND substr(timestamp, 1, 10) = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (symbol, frequency, trade_date),
                ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        result = dict(row)
        result["trade_date"] = str(result["timestamp"])[:10]
        result["price"] = result["close"]
        result["source"] = "market_bars"
        return result

    def get_latest_quote_before_date_sync(
        self, symbol: str, trade_date: str
    ) -> dict[str, Any] | None:
        """获取某日之前最近一个交易日的最后一条报价快照。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT
                    symbol, asset_class, price, volume, timestamp,
                    quote_source, provider_name, quote_status, stale_reason,
                    provider_status, captured_reason, nav_date
                FROM quote_snapshots
                WHERE symbol = ? AND substr(timestamp, 1, 10) < ?
                ORDER BY timestamp DESC, id DESC
                LIMIT 1
                """,
                (symbol, trade_date),
            ).fetchone()
            return dict(row) if row else None

    # ---------- Portfolio Snapshots ----------

    def save_portfolio_snapshot_sync(
        self,
        cash: float,
        total_equity: float,
        positions_json: str,
        allocation_json: str,
    ) -> None:
        """同步写入组合快照（后台线程调用）。"""
        timestamp = datetime.now().isoformat()
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                """INSERT INTO portfolio_snapshots
                   (timestamp, cash, total_equity, positions_json, allocation_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    timestamp,
                    cash,
                    total_equity,
                    positions_json,
                    allocation_json,
                ),
            )
            snapshot_id = cursor.lastrowid or 0
            _insert_event_sync(
                conn,
                event_type="portfolio.snapshot.created",
                timestamp=timestamp,
                entity_type="portfolio",
                entity_id="default",
                source="portfolio_snapshots",
                source_ref=str(snapshot_id),
                payload={
                    "snapshot_id": snapshot_id,
                    "portfolio_id": "default",
                    "timestamp": timestamp,
                    "cash": cash,
                    "total_equity": total_equity,
                    "positions": _metadata_payload_value(positions_json),
                    "allocation": _metadata_payload_value(allocation_json),
                },
            )
            conn.commit()

    # ---------- Cash Flows ----------

    async def add_cash_flow(
        self,
        timestamp: str,
        amount: float,
        flow_type: str = "deposit",
        note: str = "",
    ) -> int:
        """添加资金流水记录，返回 ID。"""
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                """INSERT INTO cash_flows (timestamp, amount, flow_type, note, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (timestamp, amount, flow_type, note, datetime.now().isoformat()),
            )
            await db.commit()
            return cursor.lastrowid or 0

    async def get_cash_flows(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """列出资金流水，最新优先。"""
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM cash_flows ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    def get_cash_flows_sync(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """同步列出资金流水，最新优先。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM cash_flows ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(row) for row in rows]

    async def delete_cash_flow(self, flow_id: int) -> bool:
        """删除资金流水记录。"""
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute("DELETE FROM cash_flows WHERE id = ?", (flow_id,))
            await db.commit()
            return cursor.rowcount > 0

    # ---------- Trades ----------

    async def add_trade(
        self,
        timestamp: str,
        symbol: str,
        direction: str,
        quantity: float,
        price: float,
        commission: float = 0.0,
        asset_class: str = "stock",
        note: str = "",
    ) -> int:
        """添加交易记录，返回 ID。"""
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                """INSERT INTO trades
                   (timestamp, symbol, direction, quantity, price, commission, asset_class, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    timestamp,
                    symbol,
                    direction,
                    quantity,
                    price,
                    commission,
                    asset_class,
                    note,
                    datetime.now().isoformat(),
                ),
            )
            await db.commit()
            return cursor.lastrowid or 0

    def add_trade_sync(
        self,
        *,
        timestamp: str,
        symbol: str,
        direction: str,
        quantity: float,
        price: float,
        commission: float = 0.0,
        asset_class: str = "stock",
        note: str = "",
    ) -> int:
        """同步添加交易记录，供后台确认任务使用。"""
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                """INSERT INTO trades
                   (timestamp, symbol, direction, quantity, price, commission, asset_class, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    timestamp,
                    symbol,
                    direction,
                    quantity,
                    price,
                    commission,
                    asset_class,
                    note,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    async def get_trades(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """列出交易记录，最新优先。"""
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    def get_trades_sync(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """同步列出交易记录，最新优先。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(row) for row in rows]

    async def delete_trade(self, trade_id: int) -> bool:
        """删除交易记录。"""
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
            await db.commit()
            return cursor.rowcount > 0

    # ---------- Pending Fund Orders ----------

    def add_pending_fund_order_sync(
        self,
        *,
        submitted_at: str,
        symbol: str,
        display_name: str,
        amount: float,
        commission: float = 0.0,
        asset_class: str = "fund",
        target_trade_date: str,
        status: str = "pending",
        note: str = "",
    ) -> int:
        """同步写入待确认基金申购，等待确认净值发布后转交易。"""
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO pending_fund_orders
                    (submitted_at, symbol, display_name, amount, commission, asset_class,
                     target_trade_date, status, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submitted_at,
                    symbol,
                    display_name,
                    amount,
                    commission,
                    asset_class,
                    target_trade_date,
                    status,
                    note,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def get_pending_fund_orders_sync(
        self, status: str = "pending"
    ) -> list[dict[str, Any]]:
        """同步读取待确认基金申购。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM pending_fund_orders
                WHERE status = ?
                ORDER BY submitted_at ASC, id ASC
                """,
                (status,),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_pending_fund_order_confirmed_sync(
        self,
        *,
        order_id: int,
        trade_id: int,
        confirmed_nav: float,
        confirmed_quantity: float,
        confirmed_trade_date: str,
    ) -> None:
        """标记待确认基金申购已转正式交易。"""
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """
                UPDATE pending_fund_orders
                SET status = 'confirmed',
                    confirmed_nav = ?,
                    confirmed_quantity = ?,
                    confirmed_trade_date = ?,
                    trade_id = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    confirmed_nav,
                    confirmed_quantity,
                    confirmed_trade_date,
                    trade_id,
                    datetime.now().isoformat(),
                    order_id,
                ),
            )
            conn.commit()

    async def get_total_deposits(self) -> float:
        """所有入金总额（deposit - withdraw）。"""
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                "SELECT COALESCE(SUM(CASE WHEN flow_type='deposit' THEN amount ELSE -amount END), 0) FROM cash_flows"
            )
            row = await cursor.fetchone()
            return float(row[0]) if row else 0.0

    def get_total_deposits_sync(self) -> float:
        """同步版本，供后台线程调用。"""
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN flow_type='deposit' THEN amount ELSE -amount END), 0) FROM cash_flows"
            )
            row = cursor.fetchone()
            return float(row[0]) if row else 0.0

    # ---------- Ledger Entries ----------

    def insert_ledger_entry_sync(
        self,
        *,
        entry_type: str,
        timestamp: str,
        amount: float | None = None,
        symbol: str | None = None,
        direction: str | None = None,
        quantity: float | None = None,
        price: float | None = None,
        commission: float = 0.0,
        gross_amount: float | None = None,
        net_cash_impact: float | None = None,
        fee_breakdown_json: str | None = None,
        fee_rule_id: str | None = None,
        fee_rule_version: str | None = None,
        cost_basis_method: str | None = None,
        asset_class: str = "stock",
        note: str = "",
        source: str = "manual",
        source_ref: str | None = None,
        created_at: str | None = None,
    ) -> int:
        """同步写入账本事件。"""
        normalized_timestamp = _normalize_timestamp(timestamp)
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                """INSERT INTO ledger_entries
                   (entry_type, timestamp, amount, symbol, direction, quantity,
                    price, commission, gross_amount, net_cash_impact,
                    fee_breakdown_json, fee_rule_id, fee_rule_version,
                    cost_basis_method, asset_class, note, source, source_ref,
                    created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry_type,
                    normalized_timestamp,
                    amount,
                    symbol,
                    direction,
                    quantity,
                    price,
                    commission,
                    gross_amount,
                    net_cash_impact,
                    fee_breakdown_json,
                    fee_rule_id,
                    fee_rule_version,
                    cost_basis_method,
                    asset_class,
                    note,
                    source,
                    source_ref,
                    created_at or datetime.now().isoformat(),
                ),
            )
            row_id = cursor.lastrowid or 0
            event_payload = {
                "entry_id": row_id,
                "entry_type": entry_type,
                "timestamp": normalized_timestamp,
                "amount": amount,
                "symbol": symbol,
                "direction": direction,
                "quantity": quantity,
                "price": price,
                "commission": commission,
                "asset_class": asset_class,
                "note": note,
                "source": source,
                "source_ref": source_ref,
            }
            event_payload.update(
                {
                    key: value
                    for key, value in {
                        "gross_amount": gross_amount,
                        "net_cash_impact": net_cash_impact,
                        "fee_breakdown_json": fee_breakdown_json,
                        "fee_rule_id": fee_rule_id,
                        "fee_rule_version": fee_rule_version,
                        "cost_basis_method": cost_basis_method,
                    }.items()
                    if value is not None
                }
            )
            _insert_event_sync(
                conn,
                event_type="portfolio.ledger_entry.recorded",
                timestamp=normalized_timestamp,
                entity_type="portfolio",
                entity_id="default",
                source="ledger_entries",
                source_ref=str(row_id),
                payload=event_payload,
            )
            conn.commit()
        try:
            self.publish_current_valuation_snapshot_sync()
        except Exception:
            logger.exception(
                "Ledger entry %s committed but valuation snapshot publication failed",
                row_id,
            )
        return row_id

    def get_ledger_entries_sync(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """同步列出账本事件，最新优先。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT *
                   FROM ledger_entries
                   ORDER BY timestamp DESC, id DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_ledger_entry_sync(self, entry_id: int) -> dict[str, Any] | None:
        """Read one ledger event by id."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM ledger_entries WHERE id = ? LIMIT 1",
                (entry_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def confirm_ledger_trade_settlement_sync(
        self,
        *,
        entry_id: int,
        commission: float,
        net_cash_impact: float,
        fee_breakdown_json: str,
        settled_at: str,
        settlement_source: str,
        settlement_source_ref: str,
        settlement_note: str = "",
        fee_rule_id: str = "broker_settlement_confirmation",
        fee_rule_version: str = "broker_settlement_confirmation.v1",
    ) -> dict[str, Any]:
        """Confirm broker-settled trade costs while preserving the estimate."""
        normalized_settled_at = _normalize_timestamp(settled_at)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            current_row = conn.execute(
                "SELECT * FROM ledger_entries WHERE id = ? LIMIT 1",
                (entry_id,),
            ).fetchone()
            if current_row is None:
                raise KeyError(f"ledger entry not found: {entry_id}")

            current = dict(current_row)
            if str(current.get("entry_type") or "") not in {
                "trade_buy",
                "trade_sell",
            }:
                raise ValueError("only trade ledger entries can be settled")

            evidence_owner = conn.execute(
                """
                SELECT id
                FROM ledger_entries
                WHERE settlement_source = ?
                  AND settlement_source_ref = ?
                  AND id != ?
                LIMIT 1
                """,
                (settlement_source, settlement_source_ref, entry_id),
            ).fetchone()
            if evidence_owner is not None:
                raise ValueError(
                    "settlement evidence reference already confirms another ledger entry"
                )

            same_evidence = (
                current.get("settlement_status") == "confirmed"
                and current.get("settlement_source") == settlement_source
                and current.get("settlement_source_ref") == settlement_source_ref
            )
            same_values = (
                float(current.get("commission") or 0.0) == float(commission)
                and float(current.get("net_cash_impact") or 0.0)
                == float(net_cash_impact)
                and str(current.get("fee_breakdown_json") or "") == fee_breakdown_json
            )
            if same_evidence:
                if not same_values:
                    raise ValueError(
                        "settlement evidence reference already confirmed with different values"
                    )
                return current

            estimated_commission = current.get("estimated_commission")
            if estimated_commission is None:
                estimated_commission = current.get("commission")
            estimated_net_cash_impact = current.get("estimated_net_cash_impact")
            if estimated_net_cash_impact is None:
                estimated_net_cash_impact = current.get("net_cash_impact")
            estimated_fee_breakdown_json = current.get("estimated_fee_breakdown_json")
            if estimated_fee_breakdown_json is None:
                estimated_fee_breakdown_json = current.get("fee_breakdown_json")
            estimated_fee_rule_id = current.get("estimated_fee_rule_id")
            if estimated_fee_rule_id is None:
                estimated_fee_rule_id = current.get("fee_rule_id")
            estimated_fee_rule_version = current.get("estimated_fee_rule_version")
            if estimated_fee_rule_version is None:
                estimated_fee_rule_version = current.get("fee_rule_version")

            conn.execute(
                """
                UPDATE ledger_entries
                SET commission = ?, net_cash_impact = ?, fee_breakdown_json = ?,
                    fee_rule_id = ?, fee_rule_version = ?,
                    estimated_commission = ?, estimated_net_cash_impact = ?,
                    estimated_fee_breakdown_json = ?, estimated_fee_rule_id = ?,
                    estimated_fee_rule_version = ?, settlement_status = 'confirmed',
                    settled_at = ?, settlement_source = ?, settlement_source_ref = ?,
                    settlement_note = ?
                WHERE id = ?
                """,
                (
                    commission,
                    net_cash_impact,
                    fee_breakdown_json,
                    fee_rule_id,
                    fee_rule_version,
                    estimated_commission,
                    estimated_net_cash_impact,
                    estimated_fee_breakdown_json,
                    estimated_fee_rule_id,
                    estimated_fee_rule_version,
                    normalized_settled_at,
                    settlement_source,
                    settlement_source_ref,
                    settlement_note,
                    entry_id,
                ),
            )
            updated_row = conn.execute(
                "SELECT * FROM ledger_entries WHERE id = ? LIMIT 1",
                (entry_id,),
            ).fetchone()
            if updated_row is None:
                raise RuntimeError("settled ledger entry could not be reloaded")
            updated = dict(updated_row)
            _insert_event_sync(
                conn,
                event_type="portfolio.trade_settlement.confirmed",
                timestamp=normalized_settled_at,
                entity_type="ledger_entry",
                entity_id=str(entry_id),
                source=settlement_source,
                source_ref=settlement_source_ref,
                payload={
                    "entry_id": entry_id,
                    "symbol": current.get("symbol"),
                    "direction": current.get("direction"),
                    "estimated": {
                        "commission": estimated_commission,
                        "net_cash_impact": estimated_net_cash_impact,
                        "fee_breakdown": _json_dict(estimated_fee_breakdown_json),
                        "fee_rule_id": estimated_fee_rule_id,
                        "fee_rule_version": estimated_fee_rule_version,
                    },
                    "settled": {
                        "commission": commission,
                        "net_cash_impact": net_cash_impact,
                        "fee_breakdown": _json_dict(fee_breakdown_json),
                        "fee_rule_id": fee_rule_id,
                        "fee_rule_version": fee_rule_version,
                    },
                    "cash_adjustment": (
                        None
                        if estimated_net_cash_impact is None
                        else float(
                            Decimal(str(net_cash_impact))
                            - Decimal(str(estimated_net_cash_impact))
                        )
                    ),
                    "settlement_note": settlement_note,
                },
            )
            conn.commit()
        try:
            self.publish_current_valuation_snapshot_sync()
        except Exception:
            logger.exception(
                "Ledger settlement %s committed but valuation snapshot publication failed",
                entry_id,
            )
        return updated

    # ---------- Market Research ----------

    async def add_research_note(
        self,
        *,
        symbol: str,
        asset_class: str,
        entry_kind: str,
        title: str,
        content: str,
        priority: str = "normal",
        event_date: str | None = None,
    ) -> int:
        """新增研究记录，供市场研究工作台持久化使用。"""
        now = datetime.now().isoformat()
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                """INSERT INTO market_research_notes
                   (symbol, asset_class, entry_kind, title, content, priority, event_date, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    symbol,
                    asset_class,
                    entry_kind,
                    title,
                    content,
                    priority,
                    event_date,
                    now,
                    now,
                ),
            )
            note_id = cursor.lastrowid or 0
            _insert_event_sync(
                conn,
                event_type="research.note.created",
                timestamp=now,
                entity_type="instrument",
                entity_id=symbol,
                source="market_research_notes",
                source_ref=str(note_id),
                payload={
                    "note_id": note_id,
                    "symbol": symbol,
                    "asset_class": asset_class,
                    "entry_kind": entry_kind,
                    "title": title,
                    "content": content,
                    "priority": priority,
                    "event_date": event_date,
                },
            )
            conn.commit()
            return note_id

    async def get_research_notes(
        self,
        *,
        symbol: str | None = None,
        entry_kind: str | None = None,
        priority: str | None = None,
        event_date_from: str | None = None,
        event_date_to: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """异步读取研究记录，按更新时间倒序。"""
        import aiosqlite

        query = "SELECT * FROM market_research_notes"
        clauses: list[str] = []
        params: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if entry_kind:
            clauses.append("entry_kind = ?")
            params.append(entry_kind)
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        if event_date_from:
            clauses.append("COALESCE(event_date, '') >= ?")
            params.append(event_date_from)
        if event_date_to:
            clauses.append("COALESCE(event_date, '') <= ?")
            params.append(event_date_to)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, tuple(params))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    def get_research_notes_sync(
        self,
        *,
        symbol: str | None = None,
        entry_kind: str | None = None,
        priority: str | None = None,
        event_date_from: str | None = None,
        event_date_to: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """同步读取研究记录，供聚合看板快速汇总。"""
        query = "SELECT * FROM market_research_notes"
        clauses: list[str] = []
        params: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if entry_kind:
            clauses.append("entry_kind = ?")
            params.append(entry_kind)
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        if event_date_from:
            clauses.append("COALESCE(event_date, '') >= ?")
            params.append(event_date_from)
        if event_date_to:
            clauses.append("COALESCE(event_date, '') <= ?")
            params.append(event_date_to)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, tuple(params)).fetchall()
            return [dict(row) for row in rows]

    async def delete_research_note(self, note_id: int) -> bool:
        """删除研究记录。"""
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                "DELETE FROM market_research_notes WHERE id = ?",
                (note_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def update_research_note(
        self,
        *,
        note_id: int,
        entry_kind: str,
        title: str,
        content: str,
        priority: str,
        event_date: str | None = None,
    ) -> bool:
        """更新研究记录。"""
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                """UPDATE market_research_notes
                   SET entry_kind = ?, title = ?, content = ?, priority = ?, event_date = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    entry_kind,
                    title,
                    content,
                    priority,
                    event_date,
                    datetime.now().isoformat(),
                    note_id,
                ),
            )
            await db.commit()
            return cursor.rowcount > 0


def _controlled_session_budget_rejection(
    reservation: dict[str, Any],
    blockers: list[str],
    *,
    before: dict[str, int] | None = None,
    after: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "reservation": {},
        "reservation_id": str(reservation.get("reservation_id") or ""),
        "attestation_id": str(reservation.get("attestation_id") or ""),
        "aggregate_before": before or {},
        "aggregate_after": after or {},
    }


def _controlled_session_rate_admission_rejection(
    admission: dict[str, Any],
    blockers: list[str],
    *,
    admitted_before: int = 0,
    admitted_after: int = 0,
    effective_rate: int = 0,
    pause_event_id: str = "",
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "admission": {},
        "admission_id": str(admission.get("admission_id") or ""),
        "session_id": str(admission.get("session_id") or ""),
        "order_id": str(admission.get("order_id") or ""),
        "admitted_before": admitted_before,
        "admitted_after": admitted_after,
        "effective_rate": effective_rate,
        "pause_event_id": pause_event_id,
    }


def _controlled_session_pause_rejection(
    pause: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "state": {},
        "event": {},
        "pause_event_id": str(pause.get("pause_event_id") or ""),
        "session_id": str(pause.get("session_id") or ""),
    }


def _controlled_session_authority_rejection(
    payload: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "session": {},
        "revocation": {},
        "session_id": str(payload.get("session_id") or ""),
        "session_fingerprint": str(payload.get("session_fingerprint") or ""),
    }


def _controlled_session_gate_snapshot_rejection(
    snapshot: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "snapshot": {},
        "snapshot_id": str(snapshot.get("snapshot_id") or ""),
        "session_id": str(snapshot.get("session_id") or ""),
    }


def _controlled_broker_submit_rejection(
    intent: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "external_call_permitted": False,
        "submit_intent_id": str(intent.get("submit_intent_id") or ""),
        "order_id": str(intent.get("order_id") or ""),
        "intent": {},
    }


def _controlled_submission_clearance_rejection(
    clearance: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "clearance_id": str(clearance.get("clearance_id") or ""),
        "submit_intent_id": str(clearance.get("submit_intent_id") or ""),
        "order_id": str(clearance.get("order_id") or ""),
        "clearance": {},
        "production_ledger_mutated": False,
    }


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


def _normalize_timestamp(value: str) -> str:
    """Normalize timestamps to stable ISO-8601 text for ordering."""
    normalized_value = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized_value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="seconds")


def _serialize_metadata_json(value: dict[str, Any] | str | None) -> str | None:
    """Serialize optional metadata to stable JSON text."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _metadata_payload_value(value: dict[str, Any] | str | None) -> Any:
    """Return metadata as a structured event payload value when possible."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _order_event_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Build a stable event payload from a persisted shared order row."""
    return {
        "order_row_id": row["id"],
        "order_id": row["order_id"],
        "timestamp": row["timestamp"],
        "symbol": row["symbol"],
        "side": row["side"],
        "order_type": row["order_type"],
        "quantity": row["quantity"],
        "price": row["price"],
        "asset_class": row["asset_class"],
        "intent_id": row["intent_id"],
        "risk_decision_id": row["risk_decision_id"],
        "execution_mode": row["execution_mode"],
        "status": row["status"],
        "source": row["source"],
        "source_ref": row["source_ref"],
        "payload": _metadata_payload_value(row["payload_json"]),
    }


def _manual_order_event_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Build a stable event payload from a persisted manual order row."""
    return {
        "order_row_id": row["id"],
        "order_id": row["order_id"],
        "timestamp": row["timestamp"],
        "symbol": row["symbol"],
        "side": row["side"],
        "order_type": row["order_type"],
        "quantity": row["quantity"],
        "price": row["price"],
        "intent_id": row["intent_id"],
        "risk_decision_id": row["risk_decision_id"],
        "execution_mode": row["execution_mode"],
        "status": row["status"],
        "note": row["note"],
        "payload": _metadata_payload_value(row["payload_json"]),
    }


def _fill_event_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Build a stable event payload from a persisted execution fill row."""
    return {
        "fill_row_id": row["id"],
        "fill_id": row["fill_id"],
        "order_id": row["order_id"],
        "timestamp": row["timestamp"],
        "symbol": row["symbol"],
        "side": row["side"],
        "fill_price": row["fill_price"],
        "fill_quantity": row["fill_quantity"],
        "commission": row["commission"],
        "slippage": row["slippage"],
        "asset_class": row["asset_class"],
        "execution_mode": row["execution_mode"],
        "provider_name": row["provider_name"],
        "broker_order_id": row["broker_order_id"],
        "source": row["source"],
        "source_ref": row["source_ref"],
        "metadata": _metadata_payload_value(row["metadata_json"]),
    }


def _latest_quote_event_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Build a stable event payload from a materialized latest quote row."""
    return {
        "quote_id": row["id"],
        "symbol": row["symbol"],
        "asset_type": row["asset_type"],
        "price": row["price"],
        "previous_close": row["previous_close"],
        "change": row["change"],
        "change_percent": row["change_percent"],
        "volume": row["volume"],
        "turnover": row["turnover"],
        "quote_timestamp": row["quote_timestamp"],
        "quote_source": row["quote_source"],
        "provider_name": row["provider_name"],
        "provider_status": row["provider_status"],
        "quote_status": row["quote_status"],
        "stale_reason": row["stale_reason"],
        "captured_at": row["captured_at"],
        "captured_reason": row["captured_reason"],
        "nav_date": row["nav_date"],
        "fetch_run_id": row["fetch_run_id"],
        "metadata": _metadata_payload_value(row["metadata_json"]),
    }


def _action_task_event_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Build a stable event payload from a persisted action task row."""
    return {
        "task_id": row["id"],
        "source_signal_id": row["source_signal_id"],
        "symbol": row["symbol"],
        "title": row["title"],
        "detail": row["detail"],
        "direction": row["direction"],
        "urgency": row["urgency"],
        "target_weight": row["target_weight"],
        "price": row["price"],
        "strategy_id": row["strategy_id"],
        "timestamp": row["timestamp"],
        "asset_class": row["asset_class"],
        "status": row["status"],
    }


def _risk_decision_journal_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "decision_id": row["decision_id"],
        "intent_id": row["intent_id"],
        "timestamp": row["timestamp"],
        "passed": bool(row["passed"]),
        "symbol": row["symbol"],
        "side": row["side"],
        "reasons": row.get("reasons") or _json_list(row.get("reasons_json")),
        "resulting_order_id": row["resulting_order_id"],
        "severity": row["severity"],
        "payload": row.get("payload") or _json_dict(row.get("payload_json")),
        "created_at": row["created_at"],
    }


def _event_log_response(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    event = dict(row)
    event["payload"] = _json_dict(event.get("payload_json"))
    return event


def _latest_signal_journal_event(
    *,
    signal_id: int,
    action_task: dict[str, Any] | None,
    risk_decision: dict[str, Any] | None,
    events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    action_ref = str(action_task["id"]) if action_task is not None else None
    risk_ref = str(risk_decision["decision_id"]) if risk_decision is not None else None
    for event in events:
        if event["source"] == "signal_reviews" and event["source_ref"] == str(
            signal_id
        ):
            return event
    for event in events:
        if (
            event["source"] == "manual_orders"
            and event["event_type"] == "order.status_changed"
            and _event_matches_signal_journal_entry(
                event,
                signal_id=signal_id,
                action_ref=action_ref,
            )
        ):
            return event
    for event in events:
        if (
            event["source"] == "orders"
            and event["event_type"] == "order.status_changed"
            and _event_matches_signal_journal_entry(
                event,
                signal_id=signal_id,
                action_ref=action_ref,
            )
        ):
            return event
    for event in events:
        if event["source"] == "risk_decisions" and event["source_ref"] == risk_ref:
            return event
        if event["source"] == "action_tasks" and event["source_ref"] == action_ref:
            return event
        if _event_matches_signal_journal_entry(
            event,
            signal_id=signal_id,
            action_ref=action_ref,
        ):
            return event
    return None


def _event_matches_signal_journal_entry(
    event: dict[str, Any],
    *,
    signal_id: int,
    action_ref: str | None,
) -> bool:
    payload = event.get("payload", {})
    if payload.get("source_signal_id") == signal_id:
        return True
    nested_payload = payload.get("payload")
    if not isinstance(nested_payload, dict):
        return False
    if nested_payload.get("source_signal_id") == signal_id:
        return True
    return (
        action_ref is not None
        and nested_payload.get("action_id") is not None
        and str(nested_payload["action_id"]) == action_ref
    )


def _controlled_lifecycle_invalidated_clearance_rows(
    conn: sqlite3.Connection,
    *,
    exclude_order_id: str = "",
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Find cleared intents contradicted by newer persisted lifecycle facts."""

    from account_truth.broker_order_lifecycle import (
        broker_order_lifecycle_terminal_outcome,
        resolve_broker_order_lifecycle_from_connection,
    )

    rows = conn.execute(
        """
        SELECT intent.*, oms.status AS oms_status,
               oms.symbol AS oms_symbol, oms.side AS oms_side,
               oms.quantity AS oms_quantity,
               clearance.terminal_status AS clearance_terminal_status,
               clearance.fill_quantity AS clearance_fill_quantity,
               clearance.cancelled_quantity AS clearance_cancelled_quantity,
               clearance.lifecycle_observation_id AS clearance_lifecycle_observation_id,
               clearance.lifecycle_evidence_fingerprint AS clearance_lifecycle_evidence_fingerprint
        FROM controlled_broker_submit_intents AS intent
        JOIN controlled_submission_reconciliation_clearances AS clearance
          ON clearance.submit_intent_id = intent.submit_intent_id
         AND clearance.status = 'cleared'
        JOIN oms_orders AS oms ON oms.order_id = intent.order_id
        WHERE intent.status = 'submitted'
          AND intent.order_id != ?
        ORDER BY intent.prepared_at_epoch_ms ASC, intent.id ASC
        LIMIT ?
        """,
        (
            str(exclude_order_id or ""),
            max(1, min(int(limit), 500)),
        ),
    ).fetchall()
    invalidated: list[dict[str, Any]] = []
    for row in rows:
        intent = dict(row)
        account_alias = str(
            _json_dict(intent.get("payload_json")).get("account_alias") or ""
        )
        if not account_alias:
            continue
        evidence = resolve_broker_order_lifecycle_from_connection(
            conn,
            gateway_id=str(intent.get("gateway_id") or ""),
            account_alias=account_alias,
            broker_order_id=str(intent.get("broker_order_id") or ""),
            client_order_id=str(intent.get("client_order_id") or ""),
        )
        terminal = broker_order_lifecycle_terminal_outcome(
            {
                "symbol": str(intent.get("oms_symbol") or ""),
                "side": str(intent.get("oms_side") or ""),
                "quantity": intent.get("oms_quantity"),
            },
            evidence,
        )
        lifecycle_blockers = list(terminal.get("blockers") or [])
        persisted_observation_id = str(
            intent.get("clearance_lifecycle_observation_id") or ""
        )
        persisted_evidence_fingerprint = str(
            intent.get("clearance_lifecycle_evidence_fingerprint") or ""
        )
        if terminal.get("status") == "non_terminal":
            lifecycle_blockers.append(
                "controlled_submission_terminal_clearance_lifecycle_not_terminal"
            )
        elif terminal.get("status") == "not_available" and persisted_observation_id:
            lifecycle_blockers.append(
                "controlled_submission_terminal_clearance_lifecycle_missing"
            )
        elif terminal.get("status") == "terminal":
            comparisons = {
                "terminal_status": intent.get("clearance_terminal_status"),
                "filled_quantity": intent.get("clearance_fill_quantity"),
                "cancelled_quantity": intent.get("clearance_cancelled_quantity"),
            }
            for field, expected in comparisons.items():
                if str(terminal.get(field) or "") != str(expected or ""):
                    lifecycle_blockers.append(
                        f"controlled_submission_terminal_clearance_{field}_changed"
                    )
            if persisted_observation_id and persisted_observation_id != str(
                terminal.get("observation_id") or ""
            ):
                lifecycle_blockers.append(
                    "controlled_submission_terminal_clearance_observation_changed"
                )
            if (
                persisted_evidence_fingerprint
                and persisted_evidence_fingerprint
                != str(terminal.get("evidence_fingerprint") or "")
            ):
                lifecycle_blockers.append(
                    "controlled_submission_terminal_clearance_evidence_changed"
                )
        expected_oms_status = str(intent.get("clearance_terminal_status") or "")
        if str(intent.get("oms_status") or "") != expected_oms_status and evidence.get(
            "status"
        ) in {"found", "blocked", "identity_conflict"}:
            lifecycle_blockers.append(
                "controlled_submission_terminal_clearance_oms_status_changed"
            )
        if lifecycle_blockers:
            observation = evidence.get("observation")
            observation = observation if isinstance(observation, dict) else {}
            intent["interlock_reason"] = "lifecycle_clearance_invalidated"
            intent["lifecycle_blocker"] = lifecycle_blockers[0]
            intent["lifecycle_observation_id"] = str(
                observation.get("observation_id") or ""
            )
            invalidated.append(intent)
    return invalidated


def _verify_controlled_ledger_entry(
    conn: sqlite3.Connection,
    *,
    entry: dict[str, Any],
    request: dict[str, Any],
) -> list[str]:
    """Re-check one proposed entry against immutable fill and broker evidence."""
    blockers: list[str] = []
    fill_id = str(entry.get("fill_id") or "")
    event_id = str(entry.get("broker_event_id") or "")
    row_fingerprint = str(entry.get("broker_row_fingerprint") or "")
    fill = conn.execute(
        "SELECT * FROM fills WHERE fill_id = ? LIMIT 1",
        (fill_id,),
    ).fetchone()
    event = conn.execute(
        """
        SELECT * FROM broker_evidence_events
        WHERE import_run_id = ? AND event_id = ? AND row_fingerprint = ?
        LIMIT 1
        """,
        (
            request["account_truth_import_run_id"],
            event_id,
            row_fingerprint,
        ),
    ).fetchone()
    if fill is None:
        blockers.append("controlled_ledger_posting_fill_missing")
    else:
        metadata = _json_dict(fill["metadata_json"])
        fill_fields = {
            "order_id": request["order_id"],
            "execution_mode": "controlled_live",
            "source": "controlled_submission_clearance",
            "fill_id": fill_id,
        }
        for field, expected in fill_fields.items():
            if str(fill[field] or "") != str(expected or ""):
                blockers.append(f"controlled_ledger_posting_fill_{field}_changed")
        if str(metadata.get("clearance_id") or "") != request["clearance_id"]:
            blockers.append("controlled_ledger_posting_fill_clearance_changed")
        if str(metadata.get("broker_event_id") or "") != event_id:
            blockers.append("controlled_ledger_posting_fill_event_changed")
        if str(metadata.get("broker_row_fingerprint") or "") != row_fingerprint:
            blockers.append("controlled_ledger_posting_fill_row_changed")
    if event is None:
        blockers.append("controlled_ledger_posting_broker_event_missing")
        return blockers

    direction = str(entry.get("direction") or "")
    if direction not in {"buy", "sell"}:
        blockers.append("controlled_ledger_posting_entry_direction_invalid")
    expected_entry_type = f"trade_{direction}"
    textual_expectations = {
        "entry_type": expected_entry_type,
        "symbol": str(event["symbol"] or ""),
        "asset_class": str(event["asset_class"] or "stock"),
        "source": "controlled_submission_ledger_posting",
        "source_ref": fill_id,
        "settlement_status": "confirmed",
        "settlement_source": "broker_statement",
        "settlement_source_ref": (
            f"{request['account_truth_import_run_id']}:{event_id}"
        ),
        "fee_rule_id": "broker_statement_exact",
        "fee_rule_version": "broker_statement_exact.v1",
        "cost_basis_method": "broker_remaining_cost",
    }
    for field, expected in textual_expectations.items():
        if str(entry.get(field) or "") != expected:
            blockers.append(f"controlled_ledger_posting_entry_{field}_changed")
    if str(event["broker_order_id"] or "") != request["broker_order_id"]:
        blockers.append("controlled_ledger_posting_event_broker_order_changed")
    if str(event["client_order_id"] or "") != request["client_order_id"]:
        blockers.append("controlled_ledger_posting_event_client_order_changed")
    if str(event["event_type"] or "") != expected_entry_type:
        blockers.append("controlled_ledger_posting_event_type_changed")

    numeric_expectations = {
        "quantity": event["quantity"],
        "price": event["price"],
        "amount": event["gross_amount"],
        "gross_amount": event["gross_amount"],
        "commission": event["fee"],
        "net_cash_impact": event["net_amount"],
    }
    for field, expected in numeric_expectations.items():
        if not _decimal_values_equal(entry.get(field), expected):
            blockers.append(f"controlled_ledger_posting_entry_{field}_changed")
    if fill is not None:
        for entry_field, fill_field in (
            ("quantity", "fill_quantity"),
            ("price", "fill_price"),
            ("commission", "commission"),
        ):
            if not _decimal_values_equal(entry.get(entry_field), fill[fill_field]):
                blockers.append(f"controlled_ledger_posting_fill_{fill_field}_changed")
    fee_breakdown = entry.get("fee_breakdown")
    fee_breakdown = fee_breakdown if isinstance(fee_breakdown, dict) else {}
    fee_expectations = {
        "commission": event["fee"],
        "stamp_tax": event["tax"],
        "transfer_fee": event["transfer_fee"],
        "other_fees": "0",
    }
    for field, expected in fee_expectations.items():
        if not _decimal_values_equal(fee_breakdown.get(field), expected):
            blockers.append(f"controlled_ledger_posting_fee_{field}_changed")
    expected_total_fee = sum(
        (Decimal(str(event[field] or "0")) for field in ("fee", "tax", "transfer_fee")),
        Decimal("0"),
    )
    if not _decimal_values_equal(fee_breakdown.get("total_fee"), expected_total_fee):
        blockers.append("controlled_ledger_posting_fee_total_changed")
    try:
        if _normalize_timestamp(str(entry.get("timestamp") or "")) != (
            _normalize_timestamp(str(event["occurred_at"] or ""))
        ):
            blockers.append("controlled_ledger_posting_entry_timestamp_changed")
        expected_settled_at = str(event["settled_at"] or event["occurred_at"] or "")
        if _normalize_timestamp(str(entry.get("settled_at") or "")) != (
            _normalize_timestamp(expected_settled_at)
        ):
            blockers.append("controlled_ledger_posting_entry_settlement_time_changed")
    except ValueError:
        blockers.append("controlled_ledger_posting_entry_timestamp_invalid")

    source_conflict = conn.execute(
        """
        SELECT id FROM ledger_entries
        WHERE (source = ? AND source_ref = ?)
           OR (settlement_source = ? AND settlement_source_ref = ?)
        LIMIT 1
        """,
        (
            entry.get("source"),
            entry.get("source_ref"),
            entry.get("settlement_source"),
            entry.get("settlement_source_ref"),
        ),
    ).fetchone()
    if source_conflict is not None:
        blockers.append("controlled_ledger_posting_entry_already_exists")
    return list(dict.fromkeys(blockers))


def _account_truth_review_identity_from_connection(
    conn: sqlite3.Connection,
    *,
    import_run_id: str,
) -> dict[str, Any]:
    """Build a stable identity for current Account Truth review decisions."""
    table_exists = conn.execute("""
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'reconciliation_review_decisions'
        """).fetchone()
    if table_exists is None:
        rows: list[dict[str, Any]] = []
    else:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT import_run_id, item_key, category, symbol,
                       review_status, evidence_fingerprint, schema_version,
                       created_at, updated_at
                FROM reconciliation_review_decisions
                WHERE import_run_id = ?
                ORDER BY item_key ASC, id ASC
                """,
                (import_run_id,),
            ).fetchall()
        ]
    return {
        "import_run_id": import_run_id,
        "decision_count": len(rows),
        "fingerprint": _stable_json_fingerprint(rows),
    }


def _decimal_values_equal(left: Any, right: Any) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (ArithmeticError, TypeError, ValueError):
        return False


def _stable_json_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _controlled_submission_ledger_posting_rejection(
    requested: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "posting_id": str(requested.get("posting_id") or ""),
        "clearance_id": str(requested.get("clearance_id") or ""),
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "production_ledger_mutated": False,
    }


def _controlled_submission_ledger_correction_rejection(
    requested: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "correction_id": str(requested.get("correction_id") or ""),
        "posting_id": str(requested.get("posting_id") or ""),
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "production_ledger_mutated": False,
    }


def _json_dict(value) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _paper_shadow_run_review_next_step(review_status: str) -> str:
    status = str(review_status or "").strip().lower()
    if status == "accepted_for_manual_confirmation":
        return "review_manual_confirmation"
    if status == "needs_rerun":
        return "run_paper_shadow_daily"
    return "resolve_shadow_divergence"


def _validate_paper_shadow_run_review_transition(
    *,
    run_status: str,
    review_status: str,
) -> None:
    normalized_run_status = str(run_status or "").strip().lower()
    normalized_review_status = str(review_status or "").strip().lower()
    if (
        normalized_run_status == "failed"
        and normalized_review_status == "accepted_for_manual_confirmation"
    ):
        raise ValueError(
            "failed paper/shadow run cannot be accepted for manual confirmation; "
            "inspect the failed run or rerun paper/shadow first"
        )


def _serialize_event_payload_json(value: dict[str, Any] | str | None) -> str:
    """Serialize event payloads with Decimal-safe stable JSON."""
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def _insert_event_sync(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    timestamp: str,
    entity_type: str | None,
    entity_id: str | None,
    source: str,
    source_ref: str | None,
    payload: dict[str, Any] | str | None,
) -> sqlite3.Cursor:
    now = datetime.now().isoformat()
    return conn.execute(
        """
        INSERT INTO event_log (
            event_type, timestamp, entity_type, entity_id, source,
            source_ref, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            timestamp,
            entity_type,
            entity_id,
            source,
            source_ref,
            _serialize_event_payload_json(payload),
            now,
        ),
    )
