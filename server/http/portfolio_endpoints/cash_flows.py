"""Portfolio cash flows HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def create_router(facade: Any, endpoints: dict[str, Any]) -> APIRouter:
    r = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    CashFlowCreate = dependency("CashFlowCreate")
    CashFlowResponse = dependency("CashFlowResponse")
    Decimal = dependency("Decimal")
    TradeCreate = dependency("TradeCreate")
    TradePreviewResponse = dependency("TradePreviewResponse")
    _manual_trade_preview_payload = dependency("_manual_trade_preview_payload")

    @r.post("/cash-flow", response_model=CashFlowResponse)
    async def create_cash_flow(body: CashFlowCreate) -> CashFlowResponse:
        """记录入金/出金。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        db = state.db

        flow_id = await db.add_cash_flow(
            timestamp=body.timestamp,
            amount=body.amount,
            flow_type=body.flow_type,
            note=body.note,
        )

        # 更新 live portfolio 的 cash
        scheduler = state.scheduler
        if scheduler and scheduler.is_running:
            with scheduler._lock:
                portfolio = scheduler._portfolio
                if portfolio is not None:
                    if body.flow_type == "deposit":
                        portfolio.deposit(Decimal(str(body.amount)))
                    elif body.flow_type == "withdraw":
                        portfolio.withdraw(Decimal(str(body.amount)))

        flows = await db.get_cash_flows(limit=1)
        return CashFlowResponse(**flows[0])

    @r.get("/cash-flows", response_model=list[CashFlowResponse])
    async def list_cash_flows(
        limit: int = 50, offset: int = 0
    ) -> list[CashFlowResponse]:
        """列出资金流水。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        flows = await state.db.get_cash_flows(limit, offset)
        return [CashFlowResponse(**f) for f in flows]

    @r.delete("/cash-flow/{flow_id}")
    async def delete_cash_flow(flow_id: int) -> dict:
        """删除资金流水记录。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        deleted = await state.db.delete_cash_flow(flow_id)
        return {"deleted": deleted}

    @r.post("/trade/preview", response_model=TradePreviewResponse)
    async def preview_trade(body: TradeCreate) -> TradePreviewResponse:
        """Preview manual trade fees and cash impact without writing ledger facts."""
        from server.dependencies import get_app_state

        state = get_app_state()
        return TradePreviewResponse(**_manual_trade_preview_payload(state.config, body))

    return r
