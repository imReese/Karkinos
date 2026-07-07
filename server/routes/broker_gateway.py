"""Broker gateway routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from server.services.broker_connector_runtime import build_broker_connectors
from server.services.broker_gateway import BrokerGatewayService


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
    r = APIRouter(prefix="/api/broker-gateway", tags=["broker-gateway"])

    @r.get("/status")
    async def get_broker_gateway_status() -> dict[str, Any]:
        service = _service()
        return service.get_status()

    @r.get("/connectors/health")
    async def get_broker_connector_health() -> dict[str, Any]:
        service = _service()
        return {
            "schema_version": "karkinos.broker_connector_health_list.v1",
            "broker_submission_enabled": False,
            "connectors": service.list_connector_health(),
        }

    @r.get("/connectors/{connector_id}/snapshot")
    async def get_broker_connector_snapshot(connector_id: str) -> dict[str, Any]:
        service = _service()
        try:
            return {
                "schema_version": "karkinos.broker_connector_snapshot_query.v1",
                "broker_submission_enabled": False,
                "snapshot": service.query_connector_snapshot(connector_id),
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @r.get("/account-facts")
    async def get_staged_account_facts() -> dict[str, Any]:
        service = _service()
        return service.query_staged_account_facts()

    @r.get("/fills/query")
    async def query_staged_broker_fills(
        symbol: str | None = None,
        limit: int = Query(50, ge=1, le=500),
    ) -> dict[str, Any]:
        service = _service()
        return service.query_staged_fills(symbol=symbol, limit=limit)

    @r.get("/orders/{order_id}/query")
    async def query_manual_ticket_order(order_id: str) -> dict[str, Any]:
        service = _service()
        try:
            return service.query_order(order_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @r.post("/orders/{order_id}/broker-cancel")
    async def cancel_live_broker_order(
        order_id: str,
        request: ManualTicketRequest,
    ) -> dict[str, Any]:
        service = _service()
        try:
            return service.cancel_live_disabled(order_id, actor=request.actor)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

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


def _service() -> BrokerGatewayService:
    from server.app import get_app_state

    state = get_app_state()
    config = getattr(state, "config", None)
    return BrokerGatewayService(
        db=state.db,
        broker_connectors=build_broker_connectors(
            getattr(config, "broker_connectors", [])
        ),
        controlled_bridge_policy=getattr(config, "controlled_bridge_policy", None),
        trading_controls=getattr(state, "trading_controls", None),
    )
