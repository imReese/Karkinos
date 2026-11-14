"""Application boundary for atomic manual-order ticket state changes."""

from __future__ import annotations

from typing import Any, Protocol

from core.events import OrderEvent
from server.contracts.order_state import (
    ManualOrderStateCommand,
    ManualOrderTicketCommand,
)


class ManualOrderTicketPersistence(Protocol):
    def create_manual_order_ticket_sync(
        self,
        command: ManualOrderTicketCommand,
    ) -> dict[str, Any]: ...

    def transition_manual_order_sync(
        self,
        command: ManualOrderStateCommand,
    ) -> dict[str, Any]: ...

    def get_manual_order_sync(self, order_id: str) -> dict[str, Any] | None: ...


class ManualOrderTicketService:
    """Expose one typed application command per manual-ticket transaction."""

    def __init__(self, *, persistence: ManualOrderTicketPersistence) -> None:
        self._persistence = persistence

    def create(self, command: ManualOrderTicketCommand) -> dict[str, Any]:
        return self._persistence.create_manual_order_ticket_sync(command)

    def transition(self, command: ManualOrderStateCommand) -> dict[str, Any]:
        return self._persistence.transition_manual_order_sync(command)


class RuntimeManualOrderTicketAdapter:
    """Translate execution events into atomic application commands."""

    def __init__(self, *, persistence: ManualOrderTicketPersistence) -> None:
        self._persistence = persistence
        self._service = ManualOrderTicketService(persistence=persistence)

    def create(
        self,
        order: OrderEvent,
        *,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        risk_decision_id = str(order.risk_decision_id or "").strip()
        return self._service.create(
            ManualOrderTicketCommand(
                idempotency_key=(
                    f"manual-ticket:risk:{risk_decision_id}:{order.order_id}"
                ),
                order_id=order.order_id,
                timestamp=order.timestamp.isoformat(),
                symbol=str(order.symbol),
                side=order.side.value,
                order_type=order.order_type.value,
                quantity=float(order.quantity),
                price=float(order.price) if order.price is not None else None,
                asset_class=(
                    order.asset_class.value
                    if order.asset_class is not None
                    else "stock"
                ),
                intent_id=str(order.intent_id or "").strip(),
                risk_decision_id=risk_decision_id,
                source="risk_gate",
                source_ref=risk_decision_id,
                payload=payload,
            )
        )

    def get(self, order_id: str) -> dict[str, Any] | None:
        return self._persistence.get_manual_order_sync(order_id)

    def transition(
        self,
        order_id: str,
        *,
        to_status: str,
        note: str,
        action_id: int | None,
    ) -> dict[str, Any]:
        action_fields: dict[str, Any] = {}
        if action_id is not None:
            action_fields = {
                "action_id": action_id,
                "expected_action_status": "pending_manual_confirmation",
                "action_to_status": (
                    "acted" if to_status == "confirmed" else "ignored"
                ),
            }
        return self._service.transition(
            ManualOrderStateCommand(
                idempotency_key=f"manual-order:{order_id}:{to_status}",
                order_id=order_id,
                expected_from="pending_confirm",
                to_status=to_status,
                note=note,
                **action_fields,
            )
        )


__all__ = [
    "ManualOrderTicketPersistence",
    "ManualOrderTicketService",
    "RuntimeManualOrderTicketAdapter",
]
