"""Portfolio trades HTTP delivery adapter."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from server.contracts.http.ledger_models import (
    ManualTradeCreate,
    PendingFundConfirmationRequest,
    PendingFundConfirmationResponse,
    PendingFundOrderResponse,
    PortfolioCorrectionRequest,
    PortfolioCorrectionResponse,
    TradeResponse,
)
from server.contracts.portfolio_mutations import PortfolioMutationConflict
from server.http.portfolio_endpoints.dependencies import PortfolioTradeDependencies
from server.services.portfolio_trade_commands import (
    CreatedPendingFundOrder,
    ManualTradeRequest,
)


def create_router(dependencies: PortfolioTradeDependencies) -> APIRouter:
    """Register thin HTTP mappings over the typed trade command service."""

    router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

    @router.post("/trade", response_model=TradeResponse)
    async def create_trade(body: ManualTradeCreate) -> TradeResponse:
        """Record one ledger-owned manual trade or pending fund intent."""

        service = dependencies.command_service_factory(dependencies.get_state())
        try:
            result = service.create(
                ManualTradeRequest(
                    command_id=body.command_id,
                    operator_id=body.operator_id,
                    timestamp=body.timestamp,
                    symbol=body.symbol,
                    direction=body.direction,
                    quantity=body.quantity,
                    price=body.price,
                    amount=body.amount,
                    commission=body.commission,
                    asset_class=body.asset_class,
                    note=body.note,
                )
            )
        except PortfolioMutationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if isinstance(result, CreatedPendingFundOrder):
            order = result.order
            return JSONResponse(
                status_code=202,
                content={
                    "status": order["status"],
                    "id": order["id"],
                    "symbol": order["symbol"],
                    "display_name": order["display_name"],
                    "amount": order["amount"],
                    "commission": order["commission"],
                    "asset_class": order["asset_class"],
                    "target_trade_date": order["target_trade_date"],
                    "replayed": result.replayed,
                    "detail": result.detail,
                },
            )
        return TradeResponse(**result.trade, replayed=result.replayed)

    @router.get("/trades", response_model=list[TradeResponse])
    async def list_trades(limit: int = 50, offset: int = 0) -> list[TradeResponse]:
        """List ledger-validated compatibility projections."""

        state = dependencies.get_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="database unavailable")
        trades = await state.db.get_trades(limit, offset)
        return [TradeResponse(**trade) for trade in trades]

    @router.get(
        "/pending-fund-orders",
        response_model=list[PendingFundOrderResponse],
    )
    async def list_pending_fund_orders() -> list[PendingFundOrderResponse]:
        """List persisted pending fund-subscription facts."""

        state = dependencies.get_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="database unavailable")
        rows = state.db.get_pending_fund_orders_sync(status="pending")
        return [PendingFundOrderResponse(**row) for row in rows]

    @router.post(
        "/pending-fund-orders/{order_id}/confirm",
        response_model=PendingFundConfirmationResponse,
    )
    async def confirm_pending_fund_order(
        order_id: int,
        body: PendingFundConfirmationRequest,
    ) -> PendingFundConfirmationResponse:
        """Apply a human-selected, already persisted confirmed-NAV run."""

        service = dependencies.command_service_factory(dependencies.get_state())
        try:
            result = service.confirm_pending(
                order_id=order_id,
                command_id=body.command_id,
                operator_id=body.operator_id,
                evidence_fetch_run_id=body.evidence_fetch_run_id,
                confirmation_note=body.confirmation_note,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PortfolioMutationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return PendingFundConfirmationResponse(
            order=PendingFundOrderResponse(**result.order),
            trade=TradeResponse(**result.trade),
            ledger_entry_id=result.ledger_entry_id,
            replayed=result.replayed,
        )

    @router.post(
        "/trade/{trade_id}/corrections",
        response_model=PortfolioCorrectionResponse,
    )
    async def correct_trade(
        trade_id: int,
        body: PortfolioCorrectionRequest,
    ) -> PortfolioCorrectionResponse:
        """Append an exact correction while preserving immutable trade history."""

        service = dependencies.command_service_factory(dependencies.get_state())
        try:
            result = service.correct(
                trade_id=trade_id,
                command_id=body.command_id,
                operator_id=body.operator_id,
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

    return router


__all__ = ["create_router"]
