"""SQLite repository for valuation, quotes, portfolio snapshots, cash, trades, and ledger facts."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from server.persistence.connection import DateTimeNow, SQLiteRepository
from server.persistence.database_support import (
    account_truth_review_identity_from_connection,
    action_task_event_payload,
    apply_manual_confirmation_readiness,
    controlled_broker_submit_rejection,
    controlled_lifecycle_invalidated_clearance_rows,
    controlled_session_authority_rejection,
    controlled_session_budget_rejection,
    controlled_session_gate_snapshot_rejection,
    controlled_session_pause_rejection,
    controlled_session_rate_admission_rejection,
    controlled_submission_clearance_rejection,
    controlled_submission_ledger_correction_rejection,
    controlled_submission_ledger_posting_rejection,
    decimal_values_equal,
    event_log_response,
    event_matches_signal_journal_entry,
    fill_event_payload,
    json_dict,
    json_list,
    latest_quote_event_payload,
    latest_signal_journal_event,
    manual_order_event_payload,
    metadata_payload_value,
    normalize_timestamp,
    order_event_payload,
    paper_shadow_run_review_next_step,
    quote_observation_rank,
    risk_decision_journal_response,
    serialize_metadata_json,
    stable_json_fingerprint,
    validate_paper_shadow_run_review_transition,
    verify_controlled_ledger_entry,
)
from server.persistence.event_log import (
    insert_event_sync,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)
from server.persistence.runtime_controls import RuntimeControlRepository

logger = logging.getLogger(__name__)


class FinancialFactsRepository(SQLiteRepository):
    """Own valuation, quotes, portfolio snapshots, cash, trades, and ledger facts."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        runtime_controls: RuntimeControlRepository,
        valuation_publisher: Callable[[], dict[str, Any]],
        now: DateTimeNow | None = None,
    ) -> None:
        super().__init__(database_path, now=now)
        self._runtime_controls = runtime_controls
        self._valuation_publisher = valuation_publisher

    def save_valuation_snapshot_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist one immutable, content-addressed valuation snapshot."""
        now = self._now(timezone.utc).isoformat()
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
                    serialize_metadata_json(payload.get("quotes") or []),
                    serialize_metadata_json(payload.get("metadata") or {}),
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
        from server.projections.valuation_snapshot import (
            build_current_valuation_snapshot,
        )

        snapshot = build_current_valuation_snapshot(self, persist=True)
        self._runtime_controls.set_value(
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
            "metadata": metadata_payload_value(metadata),
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
                    serialize_metadata_json(metadata),
                ),
            )
            insert_event_sync(
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
                valuation_snapshot = self._valuation_publisher()
                metadata_value = metadata_payload_value(metadata)
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
                metadata_value = metadata_payload_value(metadata)
                if isinstance(metadata_value, dict):
                    metadata = {
                        **metadata_value,
                        "valuation_snapshot_publication": "failed",
                    }
        metadata_json = serialize_metadata_json(metadata)
        metadata_payload = metadata_payload_value(metadata)
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
                insert_event_sync(
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
        now = self._now().isoformat()
        captured_at_value = captured_at or now
        metadata_json = serialize_metadata_json(metadata)
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
                insert_event_sync(
                    conn,
                    event_type="market.quote.refreshed",
                    timestamp=row["quote_timestamp"],
                    entity_type="instrument",
                    entity_id=row["symbol"],
                    source="latest_quotes",
                    source_ref=str(row["id"]),
                    payload=latest_quote_event_payload(row),
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
                    self._now().isoformat(),
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
            insert_event_sync(
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
            return max(rows, key=quote_observation_rank) if rows else None

    def get_latest_quotes_sync(self) -> list[dict[str, Any]]:
        """同步获取各标的最新行情快照，供启动恢复使用。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.create_function(
                "karkinos_quote_instant",
                1,
                lambda value: quote_observation_rank({"timestamp": value})[0].isoformat(
                    timespec="microseconds"
                ),
                deterministic=True,
            )
            rows = conn.execute("""
                WITH ranked_quotes AS (
                    SELECT
                        id, symbol, asset_class, price, volume, timestamp,
                        quote_source, provider_name, quote_status, stale_reason,
                        provider_status, captured_reason, nav_date, fetch_run_id,
                        created_at,
                        ROW_NUMBER() OVER (
                            PARTITION BY symbol
                            ORDER BY
                                karkinos_quote_instant(timestamp) DESC,
                                id DESC
                        ) AS quote_rank
                    FROM quote_snapshots
                )
                SELECT
                    id, symbol, asset_class, price, volume, timestamp,
                    quote_source, provider_name, quote_status, stale_reason,
                    provider_status, captured_reason, nav_date, fetch_run_id,
                    created_at
                FROM ranked_quotes
                WHERE quote_rank = 1
                ORDER BY symbol
                """).fetchall()
            return [dict(row) for row in rows]

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
                key=quote_observation_rank,
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
                    self._now().isoformat(),
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

    def save_portfolio_snapshot_sync(
        self,
        cash: float,
        total_equity: float,
        positions_json: str,
        allocation_json: str,
    ) -> None:
        """同步写入组合快照（后台线程调用）。"""
        timestamp = self._now().isoformat()
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
            insert_event_sync(
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
                    "positions": metadata_payload_value(positions_json),
                    "allocation": metadata_payload_value(allocation_json),
                },
            )
            conn.commit()

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
                (timestamp, amount, flow_type, note, self._now().isoformat()),
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
                    self._now().isoformat(),
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
                    self._now().isoformat(),
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
                    self._now().isoformat(),
                    self._now().isoformat(),
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
                    self._now().isoformat(),
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
        normalized_timestamp = normalize_timestamp(timestamp)
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
                    created_at or self._now().isoformat(),
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
            insert_event_sync(
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
            self._valuation_publisher()
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
        normalized_settled_at = normalize_timestamp(settled_at)
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
            insert_event_sync(
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
                        "fee_breakdown": json_dict(estimated_fee_breakdown_json),
                        "fee_rule_id": estimated_fee_rule_id,
                        "fee_rule_version": estimated_fee_rule_version,
                    },
                    "settled": {
                        "commission": commission,
                        "net_cash_impact": net_cash_impact,
                        "fee_breakdown": json_dict(fee_breakdown_json),
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
            self._valuation_publisher()
        except Exception:
            logger.exception(
                "Ledger settlement %s committed but valuation snapshot publication failed",
                entry_id,
            )
        return updated
