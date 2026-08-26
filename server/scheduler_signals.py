"""Signal persistence and notification projection for the trading scheduler."""

from __future__ import annotations

from core.events import SignalEvent
from core.types import AssetClass, Symbol
from domain.portfolio import Portfolio
from notification.notifier import format_signal_message
from server.scheduler_contracts import SchedulerNotifier, SchedulerSignalDatabase
from server.services.recommendation_flow import build_recommendation_cycle


def handle_scheduler_signal(
    event: SignalEvent,
    *,
    watchlist: list[tuple[Symbol, AssetClass]],
    database: SchedulerSignalDatabase | None,
    portfolio: Portfolio | None,
    notifier: SchedulerNotifier | None,
) -> None:
    """Persist a signal candidate and optionally notify without adding authority."""

    direction = "买入" if event.target_weight > 0 else "卖出"
    action_direction = "buy" if event.target_weight > 0 else "sell"
    asset_class = "stock"
    for symbol, configured_asset_class in watchlist:
        if symbol == event.symbol:
            asset_class = configured_asset_class.value
            break

    if database is not None:
        signal_id = database.save_signal_sync(
            timestamp=str(event.timestamp),
            strategy_id=event.strategy_id,
            symbol=str(event.symbol),
            direction=action_direction,
            target_weight=float(event.target_weight),
            price=float(event.price) if event.price else None,
            asset_class=asset_class,
        )
        cycle = build_recommendation_cycle(
            signals=[
                {
                    "id": signal_id,
                    "timestamp": str(event.timestamp),
                    "strategy_id": event.strategy_id,
                    "symbol": str(event.symbol),
                    "direction": action_direction,
                    "target_weight": float(event.target_weight),
                    "price": float(event.price) if event.price else None,
                    "asset_class": asset_class,
                }
            ],
            available_cash=(0.0 if portfolio is None else float(portfolio.cash)),
            existing_positions=(
                {}
                if portfolio is None
                else {
                    str(symbol): position
                    for symbol, position in portfolio.positions.items()
                }
            ),
        )
        for task in cycle.tasks:
            database.upsert_action_task_sync(
                source_signal_id=task.source_signal_id,
                symbol=task.symbol,
                title=task.title,
                detail=task.detail,
                direction=task.direction,
                urgency=(
                    "high"
                    if task.direction == "buy" and task.target_weight > 0
                    else "medium"
                ),
                target_weight=task.target_weight,
                price=task.price,
                strategy_id=task.strategy_id,
                timestamp=task.timestamp,
                asset_class=task.asset_class,
            )

    if notifier is None:
        return
    message = format_signal_message(
        symbol=str(event.symbol),
        direction=direction,
        target_weight=float(event.target_weight),
        price=float(event.price) if event.price else None,
        strategy_id=event.strategy_id,
        asset_class=asset_class,
        timestamp=str(event.timestamp),
    )
    notifier.send(title=f"Karkinos 信号: {event.symbol}", message=message)
