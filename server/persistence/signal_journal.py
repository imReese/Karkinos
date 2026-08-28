"""SQLite repository for signals, action tasks, reviews, and persisted risk decisions."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from server.persistence.connection import SQLiteRepository
from server.persistence.database_normalization import json_dict, json_list
from server.persistence.event_log import (
    insert_event_sync,
)
from server.persistence.financial_fact_event_payloads import action_task_event_payload
from server.persistence.signal_journal_projection import (
    apply_manual_confirmation_readiness,
    event_log_response,
    index_signal_journal_events,
    latest_signal_journal_event,
    risk_decision_journal_response,
)

logger = logging.getLogger(__name__)


class SignalJournalRepository(SQLiteRepository):
    """Own signals, action tasks, reviews, and persisted risk decisions."""

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

    def find_signal_id_sync(
        self,
        *,
        timestamp: str,
        strategy_id: str,
        symbol: str,
        direction: str,
    ) -> int | None:
        """Return the canonical persisted identity for one exact signal."""

        with sqlite3.connect(self._path) as conn:
            row = conn.execute(
                """
                SELECT id FROM signals
                WHERE timestamp = ? AND strategy_id = ? AND symbol = ? AND direction = ?
                ORDER BY id LIMIT 1
                """,
                (timestamp, strategy_id, symbol, direction),
            ).fetchone()
        return int(row[0]) if row is not None else None

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
                    'decision_outcome_reviews',
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
            payload = json_dict(risk.get("payload_json"))
            source_signal_id = payload.get("intent", {}).get("source_signal_id")
            if source_signal_id is None:
                continue
            signal_id = int(source_signal_id)
            if signal_id not in risks_by_signal:
                risk["payload"] = payload
                risk["reasons"] = json_list(risk.get("reasons_json"))
                risk["passed"] = bool(risk.get("passed"))
                risks_by_signal[signal_id] = risk

        latest_events = [event_log_response(row) for row in event_rows]
        latest_event_index = index_signal_journal_events(latest_events)
        reviews_by_signal: dict[int, dict[str, Any]] = {}
        for event in latest_events:
            if event["source"] != "decision_outcome_reviews":
                continue
            payload = event.get("payload", {})
            source_signal_id = payload.get("signal_id")
            if source_signal_id is None:
                continue
            signal_id = int(source_signal_id)
            if signal_id not in reviews_by_signal:
                reviews_by_signal[signal_id] = payload
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
                        risk_decision_journal_response(risk)
                        if risk is not None
                        else None
                    ),
                    "review": reviews_by_signal.get(signal_id),
                    "latest_event": latest_signal_journal_event(
                        signal_id=signal_id,
                        action_task=action,
                        risk_decision=risk,
                        events=latest_events,
                        event_index=latest_event_index,
                    ),
                }
            )
        return entries

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
        now = self._now().isoformat()
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
                insert_event_sync(
                    conn,
                    event_type="task.action.created",
                    timestamp=row["timestamp"],
                    entity_type="action_task",
                    entity_id=str(row["id"]),
                    source="action_tasks",
                    source_ref=str(row["id"]),
                    payload=action_task_event_payload(row),
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
                apply_manual_confirmation_readiness(
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
            payload = json_dict(risk.get("payload_json"))
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
                apply_manual_confirmation_readiness(
                    task,
                    risk_gate_status="not_checked",
                )
                continue
            task["risk_decision_id"] = risk["decision_id"]
            task["risk_gate_passed"] = bool(risk["passed"])
            task["risk_gate_status"] = "passed" if bool(risk["passed"]) else "blocked"
            task["risk_gate_severity"] = risk["severity"]
            task["risk_gate_reasons"] = json_list(risk.get("reasons_json"))
            apply_manual_confirmation_readiness(
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
                (status, self._now().isoformat(), task_id),
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
                insert_event_sync(
                    conn,
                    event_type="task.action.status_changed",
                    timestamp=self._now().isoformat(),
                    entity_type="action_task",
                    entity_id=str(row["id"]),
                    source="action_tasks",
                    source_ref=str(row["id"]),
                    payload=action_task_event_payload(row),
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
            cursor = insert_event_sync(
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
            return event_log_response(row) if row is not None else None

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
                    self._now().isoformat(),
                ),
            )
            row_id = cursor.lastrowid or 0
            insert_event_sync(
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
