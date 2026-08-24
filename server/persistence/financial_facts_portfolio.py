"""Portfolio snapshot, cash-flow, trade, and pending-order facts."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.persistence.database_support import metadata_payload_value
from server.persistence.event_log import insert_event_sync


class PortfolioFactsRepositoryMixin:
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


__all__ = ["PortfolioFactsRepositoryMixin"]
