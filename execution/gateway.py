"""Execution gateways."""

from __future__ import annotations

import dataclasses
import logging
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from core.event_bus import EventBus
from core.events import OrderEvent

logger = logging.getLogger(__name__)


class ManualConfirmGateway:
    """Persist approved orders for human confirmation before execution."""

    PENDING_CONFIRM = "pending_confirm"

    def __init__(self, event_bus: EventBus, *, db=None) -> None:
        self.event_bus = event_bus
        self.db = db
        event_bus.subscribe(OrderEvent, self.on_order, priority=-5)

    def on_order(self, order: OrderEvent) -> None:
        if order.execution_mode != "manual":
            return
        if self.db is None:
            logger.warning("Manual order %s has no database sink", order.order_id)
            return

        self.db.save_manual_order_sync(
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
            status=self.PENDING_CONFIRM,
            payload=self._serialize_order(order),
        )
        logger.info("Manual order pending confirmation: %s", order.order_id)

    def confirm_order(self, order_id: str) -> dict[str, Any] | None:
        if self.db is None:
            return None
        logger.info("Manual order confirmed, simulated downstream submit: %s", order_id)
        return self.db.update_manual_order_status_sync(
            order_id=order_id,
            status="confirmed",
            note="confirmed by operator; downstream execution simulated",
        )

    def reject_order(self, order_id: str, reason: str = "") -> dict[str, Any] | None:
        if self.db is None:
            return None
        logger.info("Manual order rejected: %s reason=%s", order_id, reason)
        return self.db.update_manual_order_status_sync(
            order_id=order_id,
            status="rejected",
            note=reason,
        )

    def _serialize_order(self, order: OrderEvent) -> dict[str, Any]:
        return self._convert(dataclasses.asdict(order))

    def _convert(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._convert(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._convert(item) for item in value]
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, datetime):
            return value.isoformat()
        return value
