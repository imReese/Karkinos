"""Canonical quote and market-close persistence capability."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.persistence.database_serialization import serialize_metadata_json
from server.persistence.event_log import insert_event_sync
from server.persistence.financial_fact_event_payloads import (
    latest_quote_event_payload,
    quote_observation_rank,
)


class QuoteFactsRepositoryMixin:
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


__all__ = ["QuoteFactsRepositoryMixin"]
