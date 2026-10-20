"""Serialized recommendation-task persistence for promoted-strategy scans."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from server.persistence.signal_journal import SignalJournalRepository
from server.services.decision.recommendation_flow import build_recommendation_cycle
from server.services.strategy_scan.universe.evaluation import (
    DECISION_WINDOW_START,
    SHANGHAI_TIME_ZONE,
)

_WRITE_LOCK = threading.Lock()


def persist_recommendation_tasks(
    *,
    db: Any,
    decision_date: str,
    signals: list[dict[str, Any]],
    current_authority_validator: Callable[[], None],
) -> list[dict[str, Any]]:
    """Persist the exact signals and tasks with their current source authority."""
    with _WRITE_LOCK:
        base = datetime.combine(
            date.fromisoformat(decision_date),
            DECISION_WINDOW_START,
            tzinfo=SHANGHAI_TIME_ZONE,
        )
        recommendations: list[dict[str, Any]] = []
        for index, signal in enumerate(signals):
            timestamp = (
                base + timedelta(microseconds=len(signals) - index)
            ).isoformat()
            task = build_recommendation_cycle(
                signals=[
                    {
                        "id": 0,
                        "timestamp": timestamp,
                        "strategy_id": signal["strategy_id"],
                        "symbol": signal["symbol"],
                        "direction": signal["direction"],
                        "target_weight": signal["target_weight"],
                        "price": signal["frozen_close"],
                        "asset_class": "stock",
                    }
                ],
            ).tasks[0]
            recommendations.append(
                {
                    "symbol": task.symbol,
                    "title": task.title,
                    "detail": task.detail,
                    "direction": task.direction,
                    "urgency": "high" if task.direction == "sell" else "medium",
                    "target_weight": task.target_weight,
                    "price": task.price,
                    "strategy_id": task.strategy_id,
                    "timestamp": timestamp,
                    "asset_class": task.asset_class,
                }
            )
        return SignalJournalRepository(db.path).persist_recommendation_tasks_sync(
            recommendations,
            current_authority_validator=current_authority_validator,
        )
