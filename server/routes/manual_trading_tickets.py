"""Manual trading tickets and execution routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.services.manual_trading import (
    ManualTradingService,
    build_manual_trading_service,
)


class ManualTicketRequest(BaseModel):
    actor: str | None = None


class ManualExecutionPreviewRequest(BaseModel):
    actor: str | None = None
    fill_price: str
    quantity: str
    fee: str | None = None
    tax: str | None = None
    transfer_fee: str | None = None


class ManualExecutionRecordRequest(ManualExecutionPreviewRequest):
    preview_fingerprint: str
    operator_note: str | None = None


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/manual-trading", tags=["manual-trading"])

    @r.get("/orders/{order_id}/query")
    async def query_manual_ticket_order(order_id: str) -> dict[str, Any]:
        service = _service()
        try:
            return service.query_order(order_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @r.post("/orders/{order_id}/manual-ticket")
    async def create_manual_ticket(
        order_id: str,
        request: ManualTicketRequest,
    ) -> dict[str, Any]:
        service = _service()
        try:
            return service.create_manual_ticket(order_id, actor=request.actor)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @r.post("/orders/{order_id}/manual-ticket/dry-run")
    async def dry_run_manual_ticket(
        order_id: str,
        request: ManualTicketRequest,
    ) -> dict[str, Any]:
        service = _service()
        try:
            return service.dry_run_manual_ticket(order_id, actor=request.actor)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @r.post("/orders/{order_id}/manual-ticket/export")
    async def export_manual_ticket(
        order_id: str,
        request: ManualTicketRequest,
    ) -> dict[str, Any]:
        service = _service()
        try:
            return service.export_manual_ticket(order_id, actor=request.actor)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @r.post("/orders/{order_id}/manual-ticket/preview")
    async def preview_manual_ticket(
        order_id: str,
        request: ManualTicketRequest,
    ) -> dict[str, Any]:
        service = _service()
        try:
            return service.preview_manual_ticket(order_id, actor=request.actor)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @r.post("/orders/{order_id}/manual-execution/preview")
    async def preview_manual_execution(
        order_id: str,
        request: ManualExecutionPreviewRequest,
    ) -> dict[str, Any]:
        service = _service()
        try:
            return service.preview_manual_execution_record(
                order_id,
                actor=request.actor,
                fill_price=request.fill_price,
                quantity=request.quantity,
                fee=request.fee,
                tax=request.tax,
                transfer_fee=request.transfer_fee,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @r.post("/orders/{order_id}/manual-execution")
    async def record_manual_execution(
        order_id: str,
        request: ManualExecutionRecordRequest,
    ) -> dict[str, Any]:
        service = _service()
        try:
            return service.record_manual_execution_evidence(
                order_id,
                actor=request.actor,
                preview_fingerprint=request.preview_fingerprint,
                fill_price=request.fill_price,
                quantity=request.quantity,
                fee=request.fee,
                tax=request.tax,
                transfer_fee=request.transfer_fee,
                operator_note=request.operator_note,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return r


def _service() -> ManualTradingService:
    from server.dependencies import get_app_state

    return build_manual_trading_service(get_app_state())


__all__ = [
    "ManualExecutionPreviewRequest",
    "ManualExecutionRecordRequest",
    "ManualTicketRequest",
    "create_router",
]
