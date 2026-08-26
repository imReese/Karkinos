"""Serialized recommendation-task persistence for promoted-strategy scans."""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from typing import Any

from server.services.promoted_strategy_universe_scan_support import (
    DECISION_WINDOW_START,
    SHANGHAI_TIME_ZONE,
)
from server.services.recommendation_flow import build_recommendation_cycle

_WRITE_LOCK = threading.Lock()


def persist_recommendation_tasks(
    *,
    db: Any,
    decision_date: str,
    signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Persist the exact selected signals under one process-local write lock."""
    with _WRITE_LOCK:
        base = datetime.combine(
            date.fromisoformat(decision_date),
            DECISION_WINDOW_START,
            tzinfo=SHANGHAI_TIME_ZONE,
        )
        persisted: list[dict[str, Any]] = []
        for index, signal in enumerate(signals):
            timestamp = (
                base + timedelta(microseconds=len(signals) - index)
            ).isoformat()
            signal_id = db.find_signal_id_sync(
                timestamp=timestamp,
                strategy_id=str(signal["strategy_id"]),
                symbol=str(signal["symbol"]),
                direction=str(signal["direction"]),
            )
            if signal_id is None:
                signal_id = db.save_signal_sync(
                    timestamp=timestamp,
                    strategy_id=str(signal["strategy_id"]),
                    symbol=str(signal["symbol"]),
                    direction=str(signal["direction"]),
                    target_weight=float(signal["target_weight"]),
                    price=float(signal["frozen_close"]),
                    asset_class="stock",
                )
            task = build_recommendation_cycle(
                signals=[
                    {
                        "id": signal_id,
                        "timestamp": timestamp,
                        "strategy_id": signal["strategy_id"],
                        "symbol": signal["symbol"],
                        "direction": signal["direction"],
                        "target_weight": signal["target_weight"],
                        "price": signal["frozen_close"],
                        "asset_class": "stock",
                    }
                ],
                available_cash=0,
                existing_positions={},
            ).tasks[0]
            db.upsert_action_task_sync(
                source_signal_id=task.source_signal_id,
                symbol=task.symbol,
                title=task.title,
                detail=task.detail,
                direction=task.direction,
                urgency="high" if task.direction == "sell" else "medium",
                target_weight=task.target_weight,
                price=task.price,
                strategy_id=task.strategy_id,
                timestamp=task.timestamp,
                asset_class=task.asset_class,
            )
            persisted.append(
                {
                    "source_signal_id": signal_id,
                    "symbol": task.symbol,
                    "direction": task.direction,
                    "timestamp": timestamp,
                }
            )
        return persisted
