from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RecommendationTask:
    source_signal_id: int
    symbol: str
    direction: str
    title: str
    detail: str
    target_weight: float
    price: float | None
    strategy_id: str
    asset_class: str
    timestamp: str


@dataclass(slots=True)
class RecommendationCycle:
    tasks: list[RecommendationTask]
    summary: dict[str, int]


def build_recommendation_cycle(
    signals: list[dict[str, Any]],
    available_cash: float,
    existing_positions: dict[str, Any],
) -> RecommendationCycle:
    tasks: list[RecommendationTask] = []

    for row in signals:
        direction = str(row.get("direction", "")).lower()
        symbol = str(row["symbol"])
        target_weight = float(row.get("target_weight", 0.0) or 0.0)
        strategy_id = str(row.get("strategy_id", ""))
        asset_class = str(row.get("asset_class", "stock") or "stock")
        title_prefix = (
            "建议增持"
            if direction == "buy"
            else "建议减仓"
            if direction == "sell"
            else "继续观察"
        )

        tasks.append(
            RecommendationTask(
                source_signal_id=int(row["id"]),
                symbol=symbol,
                direction=direction,
                title=f"{title_prefix} {symbol}",
                detail=f"{strategy_id} 触发，目标仓位 {target_weight * 100:.0f}%",
                target_weight=target_weight,
                price=row.get("price"),
                strategy_id=strategy_id,
                asset_class=asset_class,
                timestamp=str(row["timestamp"]),
            )
        )

    return RecommendationCycle(
        tasks=tasks,
        summary={
            "task_count": len(tasks),
            "buy_count": sum(1 for task in tasks if task.direction == "buy"),
            "sell_count": sum(1 for task in tasks if task.direction == "sell"),
        },
    )
