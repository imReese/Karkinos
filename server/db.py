"""SQLite 持久化 — 信号历史、回测结果、组合快照。"""

from __future__ import annotations

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
                SELECT *
                FROM execution_reconciliation_items
                WHERE suggested_action != 'no_action'
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (int(limit), int(offset)),
            ).fetchall()
            return [dict(row) for row in rows]

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
        if any(int(requested.get(field) or 0) < 0 for field in money_fields):
            return _controlled_session_budget_rejection(
                requested,
                ["budget_reservation_money_units_invalid"],
            )
        if any(int(requested.get(field) or 0) <= 0 for field in count_fields):
            return _controlled_session_budget_rejection(
                requested,
                ["budget_reservation_order_count_invalid"],
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
                }
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
                }
                blockers: list[str] = []
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
                        status, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            except sqlite3.OperationalError:
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
