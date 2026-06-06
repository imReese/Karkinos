"""Execution connector layer for shared paper/live order handling."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol

from core.event_bus import EventBus
from core.events import FillEvent, OrderEvent
from core.types import AssetClass
from execution.engine import ExecutionEngine
from execution.simulator import SimulatedExecution
from execution.tracker import BrokerFillReport, ExecutionOrderTracker


class ExecutionConnector(Protocol):
    """Connector contract for execution venues."""

    def submit_order(self, order: OrderEvent) -> FillEvent | None:
        """Submit one order to the execution venue."""
        ...


class PaperExecutionConnector:
    """Execute paper orders through the shared simulated execution path."""

    SOURCE = "paper_execution"

    def __init__(
        self,
        *,
        event_bus: EventBus,
        db=None,
        execution: ExecutionEngine | None = None,
        tracker: ExecutionOrderTracker | None = None,
        provider_name: str = "simulated",
    ) -> None:
        self.event_bus = event_bus
        self.db = db
        self.execution = execution or SimulatedExecution()
        self.tracker = tracker or ExecutionOrderTracker(event_bus=event_bus, db=db)
        self.provider_name = provider_name
        event_bus.subscribe(OrderEvent, self.on_order)

    def on_order(self, order: OrderEvent) -> None:
        """Handle a published order event."""
        self.submit_order(order)

    def submit_order(self, order: OrderEvent) -> FillEvent | None:
        """Persist, execute, and track one paper order."""
        if order.execution_mode != "paper":
            return None

        self._record_order(order, status="submitted")
        fill = self.execution.execute(order)
        if fill is None:
            self._update_order_status(order.order_id, status="unfilled")
            return None

        recorded = self.tracker.record_fill(
            BrokerFillReport(
                fill_id=fill.fill_id,
                order_id=fill.order_id,
                timestamp=fill.timestamp,
                symbol=fill.symbol,
                side=fill.side,
                fill_price=fill.fill_price,
                fill_quantity=fill.fill_quantity,
                commission=fill.commission,
                slippage=fill.slippage,
                asset_class=AssetClass.STOCK,
                execution_mode=order.execution_mode,
                provider_name=self.provider_name,
                broker_order_id=order.order_id,
                source=self.SOURCE,
                source_ref=fill.fill_id,
                metadata={"order_type": order.order_type.value},
            )
        )
        self._update_order_status(order.order_id, status="filled")
        return recorded

    def _record_order(self, order: OrderEvent, *, status: str) -> None:
        if self.db is None or not hasattr(self.db, "record_order_sync"):
            return
        self.db.record_order_sync(
            order_id=order.order_id,
            timestamp=order.timestamp.isoformat(),
            symbol=str(order.symbol),
            side=order.side.value,
            order_type=order.order_type.value,
            quantity=float(order.quantity),
            price=float(order.price) if order.price is not None else None,
            intent_id=order.intent_id,
            risk_decision_id=order.risk_decision_id,
            execution_mode=order.execution_mode,
            status=status,
            source=self.SOURCE,
            source_ref=order.order_id,
            payload=_serialize_order(order),
        )

    def _update_order_status(self, order_id: str, *, status: str) -> None:
        if self.db is None or not hasattr(self.db, "update_order_status_sync"):
            return
        self.db.update_order_status_sync(
            order_id=order_id,
            status=status,
            note=f"{status} by {self.SOURCE}",
        )


def _serialize_order(order: OrderEvent) -> dict[str, Any]:
    return _convert(dataclasses.asdict(order))


def _convert(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _convert(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_convert(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    return value
