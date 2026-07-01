"""Operations center API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from server.routes.decision import _today_decision_payload, _trading_plan_positions
from server.services.daily_operations import build_daily_operations_summary
from server.services.daily_trading_plan import build_daily_trading_plan
from server.services.operations_today import build_operations_today_summary


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/operations", tags=["operations"])

    @router.get("/today")
    async def today_operations() -> dict[str, Any]:
        from server.app import get_app_state

        state = get_app_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="Database is not initialized")

        decision_payload = await _today_decision_payload(state)
        trading_plan = build_daily_trading_plan(
            decision_payload=decision_payload,
            config=state.config,
            positions=_trading_plan_positions(state),
        )
        pending_manual_orders = _call_list(
            state.db,
            "list_manual_orders_sync",
            status="pending_confirm",
            limit=50,
            offset=0,
        )
        order_facts = _call_list(
            state.db,
            "list_orders_sync",
            limit=100,
            offset=0,
        )
        fill_facts = _call_list(
            state.db,
            "list_fills_sync",
            limit=100,
            offset=0,
        )
        ledger_review_count = len(
            _call_list(
                state.db,
                "get_ledger_entries_sync",
                limit=50,
                offset=0,
            )
        )
        daily_operations = build_daily_operations_summary(
            decision_summary=decision_payload.get("summary"),
            candidates=decision_payload.get("candidates", []),
            pending_manual_orders=pending_manual_orders,
            order_facts=order_facts,
            fill_facts=fill_facts,
            ledger_review_count=ledger_review_count,
        )
        return build_operations_today_summary(
            decision_payload=decision_payload,
            trading_plan=trading_plan,
            daily_operations=daily_operations,
            order_facts=order_facts,
            fill_facts=fill_facts,
        )

    return router


def _call_list(db: Any, name: str, **kwargs: Any) -> list[dict[str, Any]]:
    reader = getattr(db, name, None)
    if not callable(reader):
        return []
    try:
        rows = reader(**kwargs)
    except TypeError:
        rows = reader()
    return list(rows or [])
