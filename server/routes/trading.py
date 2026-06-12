"""Trading control routes."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from inspect import isawaitable
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.services.trading_controls import TradingControlSnapshot


class KillSwitchRequest(BaseModel):
    enabled: bool
    reason: str = ""


class OrderRejectRequest(BaseModel):
    reason: str = ""


class ActionManualOrderRequest(BaseModel):
    quantity: float
    order_type: str = "market"
    price: float | None = None
    note: str = ""


class ShadowRunRequest(BaseModel):
    run_date: str | None = None
    base_equity: float | None = None


class ShadowDivergenceReviewRequest(BaseModel):
    reviewed_at: str
    divergence_status: str
    review_notes: str
    reviewer: str | None = None


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

    @r.post("/actions/{action_id}/manual-order")
    async def create_manual_order_from_action(
        action_id: int,
        payload: ActionManualOrderRequest,
    ) -> dict:
        from server.app import get_app_state

        if payload.quantity <= 0:
            raise HTTPException(status_code=400, detail="quantity must be positive")
        state = get_app_state()
        action = state.db.get_action_task_sync(action_id)
        if action is None:
            raise HTTPException(status_code=404, detail="action task not found")
        manual_status = action.get("manual_confirmation_status")
        if manual_status != "ready_for_manual_confirmation":
            raise HTTPException(
                status_code=409,
                detail=(
                    "action is not ready for manual confirmation: " f"{manual_status}"
                ),
            )
        side = _manual_order_side(action["direction"])
        if side is None:
            raise HTTPException(
                status_code=400,
                detail=f"action direction is not orderable: {action['direction']}",
            )

        order_id = f"ACTION-{action_id}-MANUAL"
        timestamp = datetime.now().isoformat()
        order_type = payload.order_type or "market"
        price = payload.price if payload.price is not None else action.get("price")
        order_payload = {
            "action_id": action_id,
            "source_signal_id": action.get("source_signal_id"),
            "strategy_id": action.get("strategy_id"),
            "target_weight": action.get("target_weight"),
            "risk_gate_status": action.get("risk_gate_status"),
            "manual_confirmation_status": manual_status,
            "note": payload.note,
        }
        state.db.save_manual_order_sync(
            order_id=order_id,
            timestamp=timestamp,
            symbol=action["symbol"],
            side=side,
            order_type=order_type,
            quantity=payload.quantity,
            price=price,
            intent_id=f"ACTION-{action_id}",
            risk_decision_id=action.get("risk_decision_id"),
            execution_mode="manual",
            status="pending_confirm",
            payload=order_payload,
        )
        state.db.record_order_sync(
            order_id=order_id,
            timestamp=timestamp,
            symbol=action["symbol"],
            side=side,
            order_type=order_type,
            quantity=payload.quantity,
            price=price,
            asset_class=action.get("asset_class", "stock"),
            intent_id=f"ACTION-{action_id}",
            risk_decision_id=action.get("risk_decision_id"),
            execution_mode="manual",
            status="pending_confirm",
            source="manual_action",
            source_ref=str(action_id),
            payload=order_payload,
        )
        state.db.update_action_task_status_sync(
            action_id,
            "pending_manual_confirmation",
        )
        created = state.db.get_manual_order_sync(order_id)
        if created is None:
            raise HTTPException(status_code=500, detail="manual order was not saved")
        await _broadcast_if_possible(state, "ManualOrderPrepared", created)
        return created

    @r.post("/shadow-runs/daily")
    async def run_daily_shadow_orders(
        payload: ShadowRunRequest | None = None,
    ) -> dict:
        from server.app import get_app_state

        state = get_app_state()
        body = payload or ShadowRunRequest()
        run_date = body.run_date or date.today().isoformat()
        run_id = f"shadow:{run_date}"
        base_equity = body.base_equity or _shadow_base_equity(state)
        action_rows = state.db.get_action_tasks_sync(
            statuses=["pending", "deferred"],
            limit=1000,
        )
        recorded_orders: list[dict] = []
        reused_orders: list[dict] = []
        skipped: list[dict] = []
        data_quality_issues: list[dict] = []
        data_quality_passed = 0
        timestamp = datetime.now().isoformat()
        for action in action_rows:
            if (
                action.get("manual_confirmation_status")
                != "ready_for_manual_confirmation"
            ):
                skipped.append(
                    {
                        "action_id": action.get("id"),
                        "reason": action.get("manual_confirmation_status"),
                    }
                )
                continue
            side = _manual_order_side(action["direction"])
            price = float(action.get("price") or 0)
            if side is None or price <= 0 or base_equity <= 0:
                skipped.append(
                    {
                        "action_id": action.get("id"),
                        "reason": "insufficient_shadow_inputs",
                    }
                )
                continue
            quality_issue = _shadow_action_data_quality_issue(state, action)
            if quality_issue is not None:
                data_quality_issues.append(quality_issue)
                skipped.append(
                    {
                        "action_id": action.get("id"),
                        "reason": f"data_quality:{quality_issue['reason']}",
                    }
                )
                continue
            data_quality_passed += 1
            target_weight = float(action.get("target_weight") or 0)
            quantity = int((base_equity * target_weight) / price)
            if quantity <= 0:
                skipped.append(
                    {
                        "action_id": action.get("id"),
                        "reason": "shadow_quantity_zero",
                    }
                )
                continue
            order_id = f"SHADOW-{run_date}-{action['id']}"
            existing_order = (
                state.db.get_order_sync(order_id)
                if hasattr(state.db, "get_order_sync")
                else None
            )
            if existing_order is not None:
                reused_orders.append(
                    {
                        "order_id": existing_order["order_id"],
                        "source_action_id": action["id"],
                        "symbol": existing_order["symbol"],
                        "side": existing_order["side"],
                        "quantity": float(existing_order["quantity"]),
                        "price": existing_order["price"],
                        "reused": True,
                    }
                )
                continue
            order_payload = {
                "shadow_run_schema_version": 1,
                "run_id": run_id,
                "run_date": run_date,
                "shadow_run_idempotency_key": order_id,
                "action_id": action["id"],
                "source_signal_id": action.get("source_signal_id"),
                "strategy_id": action.get("strategy_id"),
                "target_weight": action.get("target_weight"),
                "risk_gate_status": action.get("risk_gate_status"),
                "manual_confirmation_status": action.get("manual_confirmation_status"),
                "shadow_base_equity": base_equity,
            }
            state.db.record_order_sync(
                order_id=order_id,
                timestamp=timestamp,
                symbol=action["symbol"],
                side=side,
                order_type="market",
                quantity=float(quantity),
                price=price,
                asset_class=action.get("asset_class", "stock"),
                intent_id=f"SHADOW-ACTION-{action['id']}",
                risk_decision_id=action.get("risk_decision_id"),
                execution_mode="paper_shadow",
                status="shadow_recorded",
                source="paper_shadow_daily",
                source_ref=run_id,
                payload=order_payload,
            )
            recorded_orders.append(
                {
                    "order_id": order_id,
                    "source_action_id": action["id"],
                    "symbol": action["symbol"],
                    "side": side,
                    "quantity": float(quantity),
                    "price": price,
                    "reused": False,
                }
            )
        result = {
            "shadow_run_schema_version": 1,
            "run_id": run_id,
            "run_date": run_date,
            "execution_mode": "paper_shadow",
            "base_equity": base_equity,
            "data_quality_status": _shadow_data_quality_status(
                passed_count=data_quality_passed,
                blocked_count=len(data_quality_issues),
            ),
            "data_quality": {
                "schema_version": 1,
                "passed_count": data_quality_passed,
                "blocked_count": len(data_quality_issues),
                "issues": data_quality_issues,
            },
            "processed_count": len(recorded_orders),
            "reused_count": len(reused_orders),
            "skipped_count": len(skipped),
            "orders": recorded_orders,
            "reused_orders": reused_orders,
            "skipped": skipped,
        }
        await _broadcast_if_possible(state, "DailyShadowRunRecorded", result)
        return result

    @r.get("/order-facts")
    async def list_order_facts(
        status: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        from server.app import get_app_state

        state = get_app_state()
        return state.db.list_orders_sync(
            status=status,
            symbol=symbol,
            limit=limit,
            offset=offset,
        )

    @r.get("/fills")
    async def list_fill_facts(
        order_id: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        from server.app import get_app_state

        state = get_app_state()
        return state.db.list_fills_sync(
            order_id=order_id,
            symbol=symbol,
            limit=limit,
            offset=offset,
        )

    @r.post("/order-facts/{order_id}/shadow-divergence-review")
    async def record_shadow_divergence_review(
        order_id: str,
        payload: ShadowDivergenceReviewRequest,
    ) -> dict:
        from server.app import get_app_state

        state = get_app_state()
        order = state.db.get_order_sync(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="order fact not found")
        if order.get("execution_mode") != "paper_shadow":
            raise HTTPException(
                status_code=409,
                detail="shadow divergence review requires a paper_shadow order fact",
            )
        updated = state.db.record_shadow_divergence_review_sync(
            order_id=order_id,
            reviewed_at=payload.reviewed_at,
            divergence_status=payload.divergence_status,
            review_notes=payload.review_notes,
            reviewer=payload.reviewer,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="order fact not found")
        await _broadcast_if_possible(state, "ShadowDivergenceReviewed", updated)
        return updated

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
        if hasattr(state.db, "update_order_status_sync"):
            state.db.update_order_status_sync(
                order_id=order_id,
                status="confirmed",
                note="confirmed by operator; downstream execution simulated",
            )
        action_id = _manual_order_action_id(updated)
        if action_id is not None and hasattr(
            state.db, "update_action_task_status_sync"
        ):
            state.db.update_action_task_status_sync(action_id, "acted")
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
        if hasattr(state.db, "update_order_status_sync"):
            state.db.update_order_status_sync(
                order_id=order_id,
                status="rejected",
                note=payload.reason,
            )
        action_id = _manual_order_action_id(updated)
        if action_id is not None and hasattr(
            state.db, "update_action_task_status_sync"
        ):
            state.db.update_action_task_status_sync(action_id, "ignored")
        await _broadcast_if_possible(state, "ManualOrderRejected", updated)
        return updated

    return r


def _manual_order_side(direction: str) -> str | None:
    if direction in {"buy", "sell"}:
        return direction
    return None


def _shadow_base_equity(state) -> float:
    scheduler = getattr(state, "scheduler", None)
    portfolio = getattr(scheduler, "portfolio", None) if scheduler is not None else None
    if portfolio is not None:
        cash = float(getattr(portfolio, "cash", 0.0) or 0.0)
        positions_value = sum(
            float(getattr(position, "market_value", 0.0) or 0.0)
            for position in getattr(portfolio, "positions", {}).values()
        )
        total = cash + positions_value
        if total > 0:
            return total
    config = getattr(state, "config", None)
    return float(getattr(config, "initial_cash", 0.0) or 0.0)


def _shadow_action_data_quality_issue(state, action: dict) -> dict | None:
    db = getattr(state, "db", None)
    get_latest_quote = getattr(db, "get_latest_quote_sync", None)
    if not callable(get_latest_quote):
        return None
    symbol = str(action.get("symbol") or "")
    asset_class = str(action.get("asset_class") or "stock")
    quote = get_latest_quote(symbol, asset_type=asset_class)
    if quote is None:
        quote = get_latest_quote(symbol)
    if quote is None:
        return {
            "action_id": action.get("id"),
            "symbol": symbol,
            "asset_class": asset_class,
            "reason": "missing_latest_quote",
        }
    quote_status = str(quote.get("quote_status") or "live")
    if quote_status != "live":
        return {
            "action_id": action.get("id"),
            "symbol": symbol,
            "asset_class": asset_class,
            "reason": f"quote_status_{quote_status}",
            "quote_status": quote_status,
            "stale_reason": quote.get("stale_reason"),
            "quote_timestamp": quote.get("quote_timestamp"),
        }
    try:
        price = float(quote.get("price"))
    except (TypeError, ValueError):
        price = 0.0
    if price <= 0:
        return {
            "action_id": action.get("id"),
            "symbol": symbol,
            "asset_class": asset_class,
            "reason": "invalid_quote_price",
            "quote_status": quote_status,
            "quote_timestamp": quote.get("quote_timestamp"),
        }
    return None


def _shadow_data_quality_status(*, passed_count: int, blocked_count: int) -> str:
    if blocked_count and not passed_count:
        return "blocked"
    if blocked_count:
        return "partial"
    return "passed"


def _manual_order_action_id(order: dict) -> int | None:
    payload_json = order.get("payload_json")
    if not payload_json:
        return None
    try:
        payload = json.loads(str(payload_json))
    except json.JSONDecodeError:
        return None
    action_id = payload.get("action_id")
    if action_id is None:
        return None
    return int(action_id)


async def _broadcast_if_possible(state, event_type: str, payload: dict) -> None:
    if state.hub is None:
        return
    result = state.hub.broadcast({"event_type": event_type, "payload": payload})
    if isawaitable(result):
        await result
