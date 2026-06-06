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


def _ensure_column(
    conn: sqlite3.Connection, table_name: str, column_name: str, column_type: str
) -> None:
    """Add a column to an existing SQLite table when it is missing."""
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    if any(row[1] == column_name for row in rows):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


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
            conn.commit()
        logger.info("Database initialized: %s", self._path)

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
            rows = conn.execute(
                """SELECT id, created_at, config_json, total_return, sharpe, max_drawdown
                   FROM backtest_results ORDER BY id DESC"""
            ).fetchall()
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
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    ) -> None:
        """同步写入实时行情快照（后台线程调用）。"""
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                """INSERT INTO quote_snapshots
                   (
                       symbol, asset_class, price, volume, timestamp, created_at,
                       quote_source, provider_name, quote_status, stale_reason,
                       provider_status, captured_reason, nav_date
                   )
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                        symbol, asset_class, price, volume, timestamp,
                        quote_source, provider_name, quote_status, stale_reason,
                        provider_status, captured_reason, nav_date
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
            rows = conn.execute("""
                SELECT
                    qs.symbol, qs.asset_class, qs.price, qs.volume, qs.timestamp,
                    qs.quote_source, qs.provider_name, qs.quote_status, qs.stale_reason,
                    qs.provider_status, qs.captured_reason, qs.nav_date
                FROM quote_snapshots qs
                JOIN (
                    SELECT symbol, MAX(timestamp) AS max_timestamp
                    FROM quote_snapshots
                    GROUP BY symbol
                ) latest
                ON qs.symbol = latest.symbol AND qs.timestamp = latest.max_timestamp
                ORDER BY qs.symbol
                """).fetchall()
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
                    symbol, asset_class, price, volume, timestamp,
                    quote_source, provider_name, quote_status, stale_reason,
                    provider_status, captured_reason, nav_date
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
            row_id = cursor.lastrowid or 0
            _insert_event_sync(
                conn,
                event_type="portfolio.ledger_entry.recorded",
                timestamp=normalized_timestamp,
                entity_type="portfolio",
                entity_id="default",
                source="ledger_entries",
                source_ref=str(row_id),
                payload={
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
                },
            )
            conn.commit()
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
    nav_date TEXT
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
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(symbol, asset_type)
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
