"""SQLite 持久化 — 信号历史、回测结果、组合快照。"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DB_DIR = Path("data/store")
_DB_PATH = _DB_DIR / "app.db"


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
            conn.commit()
        logger.info("Database initialized: %s", self._path)

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
    ) -> None:
        """同步写入信号（后台线程调用）。"""
        with sqlite3.connect(self._path) as conn:
            conn.execute(
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
        with sqlite3.connect(self._path) as conn:
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
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

    async def get_action_tasks(
        self, statuses: list[str] | None = None, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        """列出待执行任务。"""
        return self.get_action_tasks_sync(
            statuses=statuses, limit=limit, offset=offset
        )

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
            return [dict(row) for row in rows]

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
            conn.commit()
            row = conn.execute(
                """
                SELECT id, source_signal_id, symbol, title, detail, direction, urgency,
                       target_weight, price, strategy_id, timestamp, asset_class, status,
                       created_at, updated_at
                FROM action_tasks WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
            return dict(row) if row else None

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
    ) -> int:
        """保存回测结果，返回 ID。"""
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                """INSERT INTO backtest_results
                   (created_at, config_json, initial_cash, final_equity, total_return,
                    sharpe, sortino, max_drawdown, win_rate, duration_days, equity_curve_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                ),
            )
            await db.commit()
            return cursor.lastrowid or 0

    async def get_backtest_results(self) -> list[dict[str, Any]]:
        """获取所有回测结果摘要。"""
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT id, created_at, config_json, total_return, sharpe, max_drawdown
                   FROM backtest_results ORDER BY id DESC"""
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_backtest_result(self, result_id: int) -> dict[str, Any] | None:
        """获取单个回测结果详情。"""
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM backtest_results WHERE id = ?", (result_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    # ---------- Quote Snapshots ----------

    def save_quote_snapshot_sync(
        self,
        symbol: str,
        asset_class: str,
        price: float,
        volume: float | None,
        timestamp: str,
    ) -> None:
        """同步写入实时行情快照（后台线程调用）。"""
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """INSERT INTO quote_snapshots
                   (symbol, asset_class, price, volume, timestamp, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    symbol,
                    asset_class,
                    price,
                    volume,
                    timestamp,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

    async def get_latest_quote(self, symbol: str) -> dict[str, Any] | None:
        """获取单个标的最新行情快照。"""
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT symbol, asset_class, price, volume, timestamp
                   FROM quote_snapshots
                   WHERE symbol = ?
                   ORDER BY timestamp DESC, id DESC
                   LIMIT 1""",
                (symbol,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    def get_latest_quotes_sync(self) -> list[dict[str, Any]]:
        """同步获取各标的最新行情快照，供启动恢复使用。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT qs.symbol, qs.asset_class, qs.price, qs.volume, qs.timestamp
                FROM quote_snapshots qs
                JOIN (
                    SELECT symbol, MAX(timestamp) AS max_timestamp
                    FROM quote_snapshots
                    GROUP BY symbol
                ) latest
                ON qs.symbol = latest.symbol AND qs.timestamp = latest.max_timestamp
                ORDER BY qs.symbol
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_recent_quote_snapshots_sync(
        self, symbol: str, limit: int = 2
    ) -> list[dict[str, Any]]:
        """同步获取单个标的最近的行情快照序列。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT symbol, asset_class, price, volume, timestamp
                FROM quote_snapshots
                WHERE symbol = ?
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
            return [dict(row) for row in rows]

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

    def get_latest_quote_before_date_sync(
        self, symbol: str, trade_date: str
    ) -> dict[str, Any] | None:
        """获取某日之前最近一个交易日的最后一条报价快照。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT symbol, asset_class, price, volume, timestamp
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
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """INSERT INTO portfolio_snapshots
                   (timestamp, cash, total_equity, positions_json, allocation_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    datetime.now().isoformat(),
                    cash,
                    total_equity,
                    positions_json,
                    allocation_json,
                ),
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

    def get_trades_sync(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
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

    def get_pending_fund_orders_sync(self, status: str = "pending") -> list[dict[str, Any]]:
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
                    price, commission, asset_class, note, source, source_ref, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry_type,
                    normalized_timestamp,
                    amount,
                    symbol,
                    direction,
                    quantity,
                    price,
                    commission,
                    asset_class,
                    note,
                    source,
                    source_ref,
                    created_at or datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

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
        import aiosqlite

        now = datetime.now().isoformat()
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
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
            await db.commit()
            return cursor.lastrowid or 0

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
    equity_curve_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    cash REAL NOT NULL,
    total_equity REAL NOT NULL,
    positions_json TEXT NOT NULL,
    allocation_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quote_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    asset_class TEXT NOT NULL DEFAULT 'stock',
    price REAL NOT NULL,
    volume REAL,
    timestamp TEXT NOT NULL,
    created_at TEXT NOT NULL
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
CREATE INDEX IF NOT EXISTS idx_quote_snapshots_symbol_ts ON quote_snapshots(symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_daily_close_symbol_trade_date ON daily_close_snapshots(symbol, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_action_tasks_status_ts ON action_tasks(status, timestamp DESC);

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
