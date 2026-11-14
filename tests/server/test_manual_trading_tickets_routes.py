"""Tests for manual trading tickets and manual execution routes."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.broker_gateway as broker_gateway_module
import server.routes.manual_trading_tickets as manual_trading_module
from server.composition.router_registry import router_factories
from server.routes.manual_trading_tickets import (
    ManualExecutionPreviewRequest,
    ManualExecutionRecordRequest,
    ManualTicketRequest,
    create_router,
)


class FakeBrokerGatewayService:
    """Mock service providing deterministic answers for manual tickets."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def query_order(self, order_id: str) -> dict[str, Any]:
        self.calls.append(("query_order", order_id))
        if order_id == "MISSING":
            raise KeyError("order_not_found")
        return {"order_id": order_id, "status": "confirmed"}

    def create_manual_ticket(
        self, order_id: str, *, actor: str | None = None
    ) -> dict[str, Any]:
        self.calls.append(("create_manual_ticket", (order_id, actor)))
        if order_id == "BLOCKED":
            raise ValueError("kill_switch_active")
        return {"order_id": order_id, "status": "ticket_created", "actor": actor}

    def dry_run_manual_ticket(
        self, order_id: str, *, actor: str | None = None
    ) -> dict[str, Any]:
        self.calls.append(("dry_run_manual_ticket", (order_id, actor)))
        return {"order_id": order_id, "status": "dry_run_ok", "actor": actor}

    def export_manual_ticket(
        self, order_id: str, *, actor: str | None = None
    ) -> dict[str, Any]:
        self.calls.append(("export_manual_ticket", (order_id, actor)))
        return {
            "schema_version": "karkinos.broker_gateway.v1",
            "gateway_id": "manual_ticket",
            "status": "export_ready",
            "dry_run": True,
            "order_id": order_id,
            "actor": actor,
            "ticket": {"symbol": "600519", "quantity": 100},
        }

    def preview_manual_ticket(
        self, order_id: str, *, actor: str | None = None
    ) -> dict[str, Any]:
        self.calls.append(("preview_manual_ticket", (order_id, actor)))
        return {"order_id": order_id, "status": "preview_ready", "actor": actor}

    def preview_manual_execution_record(
        self,
        order_id: str,
        *,
        actor: str | None = None,
        fill_price: str,
        quantity: str,
        fee: str | None = None,
        tax: str | None = None,
        transfer_fee: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "preview_manual_execution_record",
                {
                    "order_id": order_id,
                    "actor": actor,
                    "fill_price": fill_price,
                    "quantity": quantity,
                    "fee": fee,
                    "tax": tax,
                    "transfer_fee": transfer_fee,
                },
            )
        )
        if order_id == "INVALID_PRICE":
            raise ValueError("invalid_fill_price")
        return {
            "order_id": order_id,
            "status": "manual_execution_preview_ready",
            "preview_fingerprint": "fp_test_123",
            "fill_price": fill_price,
            "quantity": quantity,
        }

    def record_manual_execution_evidence(
        self,
        order_id: str,
        *,
        actor: str | None = None,
        preview_fingerprint: str,
        fill_price: str,
        quantity: str,
        fee: str | None = None,
        tax: str | None = None,
        transfer_fee: str | None = None,
        operator_note: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "record_manual_execution_evidence",
                {
                    "order_id": order_id,
                    "actor": actor,
                    "preview_fingerprint": preview_fingerprint,
                    "fill_price": fill_price,
                    "quantity": quantity,
                    "fee": fee,
                    "tax": tax,
                    "transfer_fee": transfer_fee,
                    "operator_note": operator_note,
                },
            )
        )
        return {
            "order_id": order_id,
            "status": "manual_execution_recorded",
            "event_id": 101,
            "preview_fingerprint": preview_fingerprint,
        }


def test_router_factories_registers_manual_trading_tickets() -> None:
    factories = router_factories()
    assert manual_trading_module.create_router in factories


def test_manual_trading_tickets_endpoints(monkeypatch) -> None:
    fake_service = FakeBrokerGatewayService()
    monkeypatch.setattr(manual_trading_module, "_service", lambda: fake_service)

    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app)

    # 1. query order
    res = client.get("/api/manual-trading/orders/ORD-1/query")
    assert res.status_code == 200
    assert res.json() == {"order_id": "ORD-1", "status": "confirmed"}

    res_404 = client.get("/api/manual-trading/orders/MISSING/query")
    assert res_404.status_code == 404

    # 2. preview ticket
    res = client.post(
        "/api/manual-trading/orders/ORD-1/manual-ticket/preview",
        json={"actor": "operator"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "preview_ready"

    # 3. create ticket
    res = client.post(
        "/api/manual-trading/orders/ORD-1/manual-ticket",
        json={"actor": "operator"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ticket_created"

    res_blocked = client.post(
        "/api/manual-trading/orders/BLOCKED/manual-ticket",
        json={"actor": "operator"},
    )
    assert res_blocked.status_code == 409

    # 4. dry-run ticket
    res = client.post(
        "/api/manual-trading/orders/ORD-1/manual-ticket/dry-run",
        json={"actor": "operator"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "dry_run_ok"

    # 5. export ticket
    res = client.post(
        "/api/manual-trading/orders/ORD-1/manual-ticket/export",
        json={"actor": "web"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "export_ready"
    assert res.json()["order_id"] == "ORD-1"

    # 6. preview execution
    res = client.post(
        "/api/manual-trading/orders/ORD-1/manual-execution/preview",
        json={
            "actor": "web",
            "fill_price": "1800.00",
            "quantity": "100",
            "fee": "5.00",
            "tax": "0.00",
            "transfer_fee": "0.20",
        },
    )
    assert res.status_code == 200
    assert res.json()["status"] == "manual_execution_preview_ready"
    assert res.json()["preview_fingerprint"] == "fp_test_123"

    res_err = client.post(
        "/api/manual-trading/orders/INVALID_PRICE/manual-execution/preview",
        json={"fill_price": "-1", "quantity": "100"},
    )
    assert res_err.status_code == 409

    # 7. record execution
    res = client.post(
        "/api/manual-trading/orders/ORD-1/manual-execution",
        json={
            "actor": "web",
            "fill_price": "1800.00",
            "quantity": "100",
            "preview_fingerprint": "fp_test_123",
            "operator_note": "executed via broker app",
        },
    )
    assert res.status_code == 200
    assert res.json()["status"] == "manual_execution_recorded"
    assert res.json()["event_id"] == 101


def test_backward_compatibility_broker_gateway_routes(monkeypatch) -> None:
    fake_service = FakeBrokerGatewayService()
    monkeypatch.setattr(broker_gateway_module, "_service", lambda: fake_service)

    app = FastAPI()
    app.include_router(broker_gateway_module.create_router())
    client = TestClient(app)

    # Verify that broker_gateway re-exports the exact request models
    assert broker_gateway_module.ManualTicketRequest is ManualTicketRequest
    assert (
        broker_gateway_module.ManualExecutionPreviewRequest
        is ManualExecutionPreviewRequest
    )
    assert (
        broker_gateway_module.ManualExecutionRecordRequest
        is ManualExecutionRecordRequest
    )

    # Test export
    res = client.post(
        "/api/broker-gateway/orders/ORD-COMPAT/manual-ticket/export",
        json={"actor": "web"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "export_ready"
    assert res.json()["order_id"] == "ORD-COMPAT"

    # Test execution preview
    res = client.post(
        "/api/broker-gateway/orders/ORD-COMPAT/manual-execution/preview",
        json={
            "actor": "web",
            "fill_price": "1720.25",
            "quantity": "100",
            "fee": "5.00",
        },
    )
    assert res.status_code == 200
    assert res.json()["status"] == "manual_execution_preview_ready"

    # Test execution record
    res = client.post(
        "/api/broker-gateway/orders/ORD-COMPAT/manual-execution",
        json={
            "actor": "web",
            "fill_price": "1720.25",
            "quantity": "100",
            "preview_fingerprint": "fp_test_123",
        },
    )
    assert res.status_code == 200
    assert res.json()["status"] == "manual_execution_recorded"
