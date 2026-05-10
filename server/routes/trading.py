"""Trading control routes."""

from __future__ import annotations

from dataclasses import asdict
from inspect import isawaitable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.services.trading_controls import TradingControlSnapshot


class KillSwitchRequest(BaseModel):
    enabled: bool
    reason: str = ""


class OrderRejectRequest(BaseModel):
    reason: str = ""


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/trading", tags=["trading"])

    @r.get("/kill-switch", response_model=TradingControlSnapshot)
    async def get_kill_switch() -> TradingControlSnapshot:
        from server.app import get_app_state

        return get_app_state().trading_controls.snapshot()

    @r.put("/kill-switch", response_model=TradingControlSnapshot)
    async def set_kill_switch(payload: KillSwitchRequest) -> TradingControlSnapshot:
        from server.app import get_app_state

        state = get_app_state()
        snapshot = state.trading_controls.set_kill_switch(
            payload.enabled,
            payload.reason,
        )
        if state.hub is not None:
            result = state.hub.broadcast(
                {
                    "event_type": "TradingControlEvent",
                    "control": "kill_switch",
                    "payload": asdict(snapshot),
                }
            )
            if isawaitable(result):
                await result
        return snapshot

    @r.get("/orders")
    async def list_manual_orders(status: str | None = None) -> list[dict]:
        from server.app import get_app_state

        state = get_app_state()
        return state.db.list_manual_orders_sync(status=status)

    @r.post("/orders/{order_id}/confirm")
    async def confirm_manual_order(order_id: str) -> dict:
        from server.app import get_app_state

        state = get_app_state()
        updated = state.db.update_manual_order_status_sync(
            order_id=order_id,
            status="confirmed",
            note="confirmed by operator; downstream execution simulated",
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="manual order not found")
        await _broadcast_if_possible(state, "ManualOrderConfirmed", updated)
        return updated

    @r.post("/orders/{order_id}/reject")
    async def reject_manual_order(order_id: str, payload: OrderRejectRequest) -> dict:
        from server.app import get_app_state

        state = get_app_state()
        updated = state.db.update_manual_order_status_sync(
            order_id=order_id,
            status="rejected",
            note=payload.reason,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="manual order not found")
        await _broadcast_if_possible(state, "ManualOrderRejected", updated)
        return updated

    return r


async def _broadcast_if_possible(state, event_type: str, payload: dict) -> None:
    if state.hub is None:
        return
    result = state.hub.broadcast({"event_type": event_type, "payload": payload})
    if isawaitable(result):
        await result
