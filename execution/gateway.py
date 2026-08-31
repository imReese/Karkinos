"""Execution gateways."""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol

from core.event_bus import EventBus
from core.events import OrderEvent

logger = logging.getLogger(__name__)


class ManualOrderTicketPort(Protocol):
    """Application-owned persistence boundary used by the execution gateway."""

    def create(
        self, order: OrderEvent, *, payload: dict[str, Any]
    ) -> dict[str, Any]: ...

    def get(self, order_id: str) -> dict[str, Any] | None: ...

    def transition(
        self,
        order_id: str,
        *,
        to_status: str,
        note: str,
        action_id: int | None,
    ) -> dict[str, Any]: ...


class ManualConfirmGateway:
    """Persist approved orders for human confirmation before execution."""

    PENDING_CONFIRM = "pending_confirm"

    def __init__(
        self,
        event_bus: EventBus,
        *,
        ticket_port: ManualOrderTicketPort | None = None,
    ) -> None:
        self.event_bus = event_bus
        self._ticket_port = ticket_port
        event_bus.subscribe(OrderEvent, self.on_order, priority=-5)

    def on_order(self, order: OrderEvent) -> None:
        if order.execution_mode != "manual":
            return
        if self._ticket_port is None:
            logger.warning("Manual order %s has no database sink", order.order_id)
            return

        intent_id = str(order.intent_id or "").strip()
        risk_decision_id = str(order.risk_decision_id or "").strip()
        if not intent_id or not risk_decision_id:
            raise ValueError(
                "runtime manual order requires persisted intent and risk decision"
            )
        payload = {
            **self._serialize_order(order),
            "manual_confirmation_required": True,
            "broker_submission_enabled": False,
            "scheduler_runtime_order": True,
        }
        self._ticket_port.create(order, payload=payload)
        logger.info("Manual order pending confirmation: %s", order.order_id)

    def confirm_order(self, order_id: str) -> dict[str, Any] | None:
        if self._ticket_port is None:
            return None
        current = self._ticket_port.get(order_id)
        action_id = self._action_id(current)
        if action_id is None:
            logger.warning(
                "Manual order %s confirmation blocked without action evidence",
                order_id,
            )
            return None
        logger.info("Manual order confirmed, simulated downstream submit: %s", order_id)
        return self._ticket_port.transition(
            order_id,
            to_status="confirmed",
            note="confirmed by operator; downstream execution simulated",
            action_id=action_id,
        )

    def reject_order(self, order_id: str, reason: str = "") -> dict[str, Any] | None:
        if self._ticket_port is None:
            return None
        logger.info("Manual order rejected: %s reason=%s", order_id, reason)
        current = self._ticket_port.get(order_id)
        action_id = self._action_id(current)
        return self._ticket_port.transition(
            order_id,
            to_status="rejected",
            note=reason,
            action_id=action_id,
        )

    @staticmethod
    def _action_id(order: dict[str, Any] | None) -> int | None:
        if not order:
            return None
        try:
            payload = json.loads(str(order.get("payload_json") or ""))
        except (TypeError, json.JSONDecodeError):
            return None
        action_id = payload.get("action_id") if isinstance(payload, dict) else None
        return int(action_id) if action_id is not None else None

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
