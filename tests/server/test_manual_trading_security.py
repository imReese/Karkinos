"""Security, concurrency, and tamper-resistance tests for manual trading."""

from __future__ import annotations

import concurrent.futures
import json
from decimal import Decimal
from typing import Any

import pytest

from domain.manual_trading import (
    compute_execution_cash_impact,
    compute_preview_fingerprint,
    verify_preview_fingerprint,
)
from server.services.manual_trading import ManualTradingService
from server.services.risk.trading_controls import (
    TradingControlSnapshot,
    TradingControlState,
)
from tests.server.test_manual_trading_service import _make_passing_evidence


class FakeDb:
    def __init__(
        self, order_id: str = "ORD-SEC-01", order: dict[str, Any] | None = None
    ) -> None:
        self.evidence = _make_passing_evidence(order_id)
        self.order = order or {
            "order_id": order_id,
            "symbol": "600519.SH",
            "side": "buy",
            "quantity": 100,
            "order_type": "limit",
            "price": 1700.0,
            "status": "manual_ticket_created",
            "broker_submission_enabled": False,
            "payload_json": json.dumps({"gateway_evidence": self.evidence}),
        }
        self.events: list[dict[str, Any]] = []

    def get_oms_order_sync(self, order_id: str) -> dict[str, Any] | None:
        if self.order and self.order.get("order_id") == order_id:
            return dict(self.order)
        return None

    def record_broker_gateway_event_sync(
        self,
        *,
        gateway_id: str,
        event_type: str,
        order_id: str | None = None,
        status: str = "recorded",
        actor: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "id": f"EVT-{len(self.events) + 1}",
            "gateway_id": gateway_id,
            "event_type": event_type,
            "order_id": order_id,
            "status": status,
            "actor": actor,
            "payload": payload or {},
        }
        self.events.append(event)
        return event

    def list_broker_gateway_events_sync(
        self,
        *,
        order_id: str | None = None,
        gateway_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return [
            e
            for e in self.events
            if (order_id is None or e["order_id"] == order_id)
            and (gateway_id is None or e["gateway_id"] == gateway_id)
        ]


def _passing_confirmation(order_id: str) -> dict[str, Any]:
    return _make_passing_evidence(order_id)["current_per_order_confirmation"]


def _passing_trading_controls() -> Any:
    class FakeTradingControls:
        def snapshot(self) -> TradingControlSnapshot:
            return TradingControlSnapshot(
                kill_switch_enabled=False,
                reason="",
                updated_at="2026-11-15T00:00:00Z",
            )

    return FakeTradingControls()


def test_preview_fingerprint_tamper_resistance() -> None:
    db = FakeDb()
    service = ManualTradingService(
        db=db,
        trading_controls=_passing_trading_controls(),
        current_per_order_confirmation_provider=_passing_confirmation,
    )

    preview = service.preview_manual_execution_record(
        "ORD-SEC-01",
        fill_price="1720.50",
        quantity="100",
        fee="5.00",
        tax="0.00",
        transfer_fee="0.50",
    )
    valid_fp = preview["preview_fingerprint"]

    # 1. Tamper fill_price
    with pytest.raises(ValueError, match="preview_fingerprint does not match"):
        service.record_manual_execution_evidence(
            "ORD-SEC-01",
            fill_price="1721.00",  # tampered
            quantity="100",
            fee="5.00",
            tax="0.00",
            transfer_fee="0.50",
            preview_fingerprint=valid_fp,
        )

    # 2. Tamper quantity
    with pytest.raises(ValueError, match="preview_fingerprint does not match"):
        service.record_manual_execution_evidence(
            "ORD-SEC-01",
            fill_price="1720.50",
            quantity="200",  # tampered
            fee="5.00",
            tax="0.00",
            transfer_fee="0.50",
            preview_fingerprint=valid_fp,
        )

    # 3. Tamper fee
    with pytest.raises(ValueError, match="preview_fingerprint does not match"):
        service.record_manual_execution_evidence(
            "ORD-SEC-01",
            fill_price="1720.50",
            quantity="100",
            fee="0.00",  # tampered
            tax="0.00",
            transfer_fee="0.50",
            preview_fingerprint=valid_fp,
        )

    # 4. Tamper fingerprint string itself
    with pytest.raises(ValueError, match="preview_fingerprint does not match"):
        service.record_manual_execution_evidence(
            "ORD-SEC-01",
            fill_price="1720.50",
            quantity="100",
            fee="5.00",
            tax="0.00",
            transfer_fee="0.50",
            preview_fingerprint="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        )


def test_order_status_boundary_fails_closed() -> None:
    db = FakeDb()
    db.order["status"] = "pending_submission"  # not manual_ticket_created
    service = ManualTradingService(
        db=db,
        trading_controls=_passing_trading_controls(),
        current_per_order_confirmation_provider=_passing_confirmation,
    )

    with pytest.raises(ValueError, match="OMS order must be manual_ticket_created"):
        service.preview_manual_execution_record(
            "ORD-SEC-01",
            fill_price="1720.50",
            quantity="100",
        )


def test_kill_switch_fails_closed() -> None:
    class BlockedTradingControls:
        def snapshot(self) -> TradingControlSnapshot:
            return TradingControlSnapshot(
                kill_switch_enabled=True,
                reason="Market wide circuit breaker",
                updated_at="2026-11-15T00:00:00Z",
            )

    db = FakeDb()
    db.order["status"] = "manually_confirmed"
    service = ManualTradingService(
        db=db,
        trading_controls=BlockedTradingControls(),
        current_per_order_confirmation_provider=_passing_confirmation,
    )

    with pytest.raises(ValueError, match="kill switch is enabled"):
        service.preview_manual_ticket("ORD-SEC-01")

    with pytest.raises(ValueError, match="kill switch is enabled"):
        service.create_manual_ticket("ORD-SEC-01")


def test_ledger_and_oms_isolation() -> None:
    db = FakeDb()
    service = ManualTradingService(
        db=db,
        trading_controls=_passing_trading_controls(),
        current_per_order_confirmation_provider=_passing_confirmation,
    )

    preview = service.preview_manual_execution_record(
        "ORD-SEC-01",
        fill_price="1720.50",
        quantity="100",
        fee="5.00",
    )
    result = service.record_manual_execution_evidence(
        "ORD-SEC-01",
        fill_price="1720.50",
        quantity="100",
        fee="5.00",
        preview_fingerprint=preview["preview_fingerprint"],
        operator_note="testing ledger isolation",
    )

    # Verify that order was NOT mutated in DB
    assert db.order["status"] == "manual_ticket_created"
    assert db.order["broker_submission_enabled"] is False

    # Verify audit evidence properties
    assert result["status"] == "manual_execution_recorded"
    assert result["does_not_mutate_oms"] is True
    assert result["does_not_mutate_production_ledger"] is True
    assert result["submitted_to_broker"] is False
    assert len(db.events) == 1
    assert db.events[0]["event_type"] == "manual_execution_recorded"
    assert db.events[0]["payload"]["operator_note"] == "testing ledger isolation"


def test_concurrent_recording_submissions() -> None:
    db = FakeDb()
    service = ManualTradingService(
        db=db,
        trading_controls=_passing_trading_controls(),
        current_per_order_confirmation_provider=_passing_confirmation,
    )

    preview = service.preview_manual_execution_record(
        "ORD-SEC-01",
        fill_price="1720.50",
        quantity="100",
        fee="5.00",
    )
    fp = preview["preview_fingerprint"]

    def submit_record(i: int) -> dict[str, Any]:
        return service.record_manual_execution_evidence(
            "ORD-SEC-01",
            fill_price="1720.50",
            quantity="100",
            fee="5.00",
            preview_fingerprint=fp,
            actor=f"operator-{i}",
        )

    # 10 concurrent submissions
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(submit_record, i) for i in range(10)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 10
    assert all(r["status"] == "manual_execution_recorded" for r in results)
    assert len(db.events) == 10


def test_preview_fingerprint_canonical_determinism() -> None:
    # Keys in different order must yield identical fingerprint (canonical JSON)
    d1 = {"a": 1, "b": {"x": 10, "y": 20}, "c": [1, 2, 3]}
    d2 = {"c": [1, 2, 3], "a": 1, "b": {"y": 20, "x": 10}}
    assert compute_preview_fingerprint(d1) == compute_preview_fingerprint(d2)

    # Any modification produces completely different SHA-256
    d3 = {"a": 1, "b": {"x": 10, "y": 21}, "c": [1, 2, 3]}
    assert compute_preview_fingerprint(d1) != compute_preview_fingerprint(d3)
    assert (
        verify_preview_fingerprint(
            compute_preview_fingerprint(d1), compute_preview_fingerprint(d3)
        )
        is False
    )


def test_manual_execution_record_audit_immutability() -> None:
    db = FakeDb()
    service = ManualTradingService(
        db=db,
        trading_controls=_passing_trading_controls(),
        current_per_order_confirmation_provider=_passing_confirmation,
    )

    preview = service.preview_manual_execution_record(
        "ORD-SEC-01",
        fill_price="1720.50",
        quantity="100",
    )
    fp = preview["preview_fingerprint"]

    # First record
    r1 = service.record_manual_execution_evidence(
        "ORD-SEC-01",
        fill_price="1720.50",
        quantity="100",
        preview_fingerprint=fp,
    )
    # Second record (same fingerprint)
    r2 = service.record_manual_execution_evidence(
        "ORD-SEC-01",
        fill_price="1720.50",
        quantity="100",
        preview_fingerprint=fp,
    )

    # Both are recorded as distinct append-only audit events
    assert r1["event_id"] != r2["event_id"]
    assert len(db.events) == 2
    assert db.events[0]["payload"]["preview_fingerprint"] == fp
    assert db.events[1]["payload"]["preview_fingerprint"] == fp
    # Neither mutates OMS order state or production ledger
    assert db.order["status"] == "manual_ticket_created"
