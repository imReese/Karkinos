"""Execution order tracking primitives for paper and live connectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from core.event_bus import EventBus
from core.events import FillEvent
from core.types import AssetClass, OrderSide, Symbol


@dataclass(frozen=True)
class BrokerFillReport:
    """Normalized fill report emitted by simulated or broker connectors."""

    fill_id: str
    order_id: str
    timestamp: datetime
    symbol: Symbol
    side: OrderSide
    fill_price: Decimal
    fill_quantity: Decimal
    commission: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    asset_class: AssetClass = AssetClass.STOCK
    execution_mode: str = "paper"
    provider_name: str | None = None
    broker_order_id: str | None = None
    source: str = "execution"
    source_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_fill_event(self) -> FillEvent:
        """Convert the broker report into the shared fill domain event."""
        return FillEvent(
            timestamp=self.timestamp,
            fill_id=self.fill_id,
            order_id=self.order_id,
            symbol=self.symbol,
            side=self.side,
            fill_price=self.fill_price,
            fill_quantity=self.fill_quantity,
            commission=self.commission,
            slippage=self.slippage,
        )


class ExecutionOrderTracker:
    """Persist connector fill reports and publish shared fill events."""

    def __init__(self, *, event_bus: EventBus, db=None) -> None:
        self.event_bus = event_bus
        self.db = db

    def record_fill(self, report: BrokerFillReport) -> FillEvent:
        """Record one connector fill report and publish its FillEvent."""
        if self.db is not None and hasattr(self.db, "record_fill_sync"):
            self.db.record_fill_sync(
                fill_id=report.fill_id,
                order_id=report.order_id,
                timestamp=report.timestamp.isoformat(),
                symbol=str(report.symbol),
                side=report.side.value,
                fill_price=float(report.fill_price),
                fill_quantity=float(report.fill_quantity),
                commission=float(report.commission),
                slippage=float(report.slippage),
                asset_class=report.asset_class.value,
                execution_mode=report.execution_mode,
                provider_name=report.provider_name,
                broker_order_id=report.broker_order_id,
                source=report.source,
                source_ref=report.source_ref,
                metadata=report.metadata,
            )
        event = report.to_fill_event()
        self.event_bus.publish(event)
        return event
