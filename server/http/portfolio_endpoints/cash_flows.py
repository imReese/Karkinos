"""Portfolio cash flows HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from server.contracts.http.ledger_models import (
    CashFlowCreate,
    CashFlowResponse,
    PortfolioCorrectionRequest,
    PortfolioCorrectionResponse,
    TradeCreate,
    TradePreviewResponse,
)
from server.contracts.portfolio_cash_flows import (
    CashFlowCorrectionWrite,
    CashFlowWrite,
)
from server.contracts.portfolio_mutations import PortfolioMutationConflict
from server.http.portfolio_endpoints.dependencies import (
    PortfolioCashFlowDependencies,
)


def create_router(dependencies: PortfolioCashFlowDependencies) -> APIRouter:
    r = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

    _manual_trade_preview_payload = dependencies.manual_trade_preview_payload

    @r.post("/cash-flow", response_model=CashFlowResponse)
    async def create_cash_flow(body: CashFlowCreate) -> CashFlowResponse:
        """记录入金/出金。"""
        service = dependencies.command_service_factory(dependencies.get_state())
        try:
            result = service.record(
                CashFlowWrite(
                    command_id=body.command_id,
                    operator_id=body.operator_id,
                    timestamp=body.timestamp,
                    amount=body.amount,
                    flow_type=body.flow_type,
                    note=body.note,
                )
            )
        except PortfolioMutationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return CashFlowResponse(**result.cash_flow, replayed=result.replayed)

    @r.get("/cash-flows", response_model=list[CashFlowResponse])
    async def list_cash_flows(
        limit: int = 50, offset: int = 0
    ) -> list[CashFlowResponse]:
        """列出资金流水。"""
        state = dependencies.get_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="database unavailable")
        flows = await state.db.get_cash_flows(limit, offset)
        return [CashFlowResponse(**f) for f in flows]

    @r.post(
        "/cash-flow/{flow_id}/corrections",
        response_model=PortfolioCorrectionResponse,
    )
    async def correct_cash_flow(
        flow_id: int,
        body: PortfolioCorrectionRequest,
    ) -> PortfolioCorrectionResponse:
        """Append an idempotent correction without deleting source history."""
        service = dependencies.command_service_factory(dependencies.get_state())
        try:
            result = service.correct(
                CashFlowCorrectionWrite(
                    command_id=body.command_id,
                    operator_id=body.operator_id,
                    cash_flow_id=flow_id,
                )
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return PortfolioCorrectionResponse(
            corrected=True,
            replayed=result.replayed,
            correction_ledger_entry_id=result.correction_ledger_entry_id,
        )

    @r.post("/trade/preview", response_model=TradePreviewResponse)
    async def preview_trade(body: TradeCreate) -> TradePreviewResponse:
        """Preview manual trade fees and cash impact without writing ledger facts."""
        state = dependencies.get_state()
        return TradePreviewResponse(**_manual_trade_preview_payload(state.config, body))

    return r


__all__ = ["create_router"]
