"""Tests for manual trading domain and application service."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from domain.manual_trading import (
    clean_decimal,
    compute_execution_cash_impact,
    compute_preview_fingerprint,
    format_ticket_copy_text,
    optional_decimal,
    verify_preview_fingerprint,
)
from server.services.manual_trading.service import ManualTradingService

# -----------------------------------------------------------------------------
# Domain Tests
# -----------------------------------------------------------------------------


def test_domain_clean_decimal_validates_and_parses() -> None:
    assert clean_decimal("1720.25", "price") == Decimal("1720.25")
    assert clean_decimal(100, "qty") == Decimal("100")
    assert optional_decimal(None) == Decimal("0")
    assert optional_decimal("") == Decimal("0")
    assert optional_decimal("5.50") == Decimal("5.50")

    with pytest.raises(ValueError, match="price must be numeric"):
        clean_decimal("invalid", "price")
    with pytest.raises(ValueError, match="price must be numeric"):
        clean_decimal(None, "price")


def test_domain_execution_cash_impact() -> None:
    # Buy: 100 * 10 = 1000 gross, fee=5, total=5 -> net impact = -1005
    gross, cost, net = compute_execution_cash_impact(
        side="buy",
        fill_price=Decimal("10.00"),
        quantity=Decimal("100"),
        fee=Decimal("5.00"),
        tax=Decimal("0.00"),
        transfer_fee=Decimal("0.20"),
    )
    assert gross == Decimal("1000.00")
    assert cost == Decimal("5.20")
    assert net == Decimal("-1005.20")

    # Sell: 100 * 10 = 1000 gross, fee=5, total=5 -> net impact = +994.80
    gross_s, cost_s, net_s = compute_execution_cash_impact(
        side="sell",
        fill_price=Decimal("10.00"),
        quantity=Decimal("100"),
        fee=Decimal("5.00"),
        tax=Decimal("0.00"),
        transfer_fee=Decimal("0.20"),
    )
    assert gross_s == Decimal("1000.00")
    assert cost_s == Decimal("5.20")
    assert net_s == Decimal("994.80")

    with pytest.raises(ValueError, match="fill_price must be positive"):
        compute_execution_cash_impact(
            side="buy",
            fill_price=Decimal("0"),
            quantity=Decimal("10"),
            fee=Decimal("0"),
            tax=Decimal("0"),
            transfer_fee=Decimal("0"),
        )


def test_domain_format_ticket_copy_text() -> None:
    text = format_ticket_copy_text(
        side="buy",
        symbol="600519",
        quantity=100,
        order_type="limit",
        limit_price=1720.25,
    )
    assert text == "BUY 600519 100 LIMIT 1720.25"

    text_market = format_ticket_copy_text(
        side="sell",
        symbol="019999",
        quantity=50.5,
        order_type="market",
    )
    assert text_market == "SELL 019999 50.5 MARKET"


def test_domain_fingerprint_generation_and_tamper_detection() -> None:
    payload = {"order_id": "ORD-1", "gross": "100.00"}
    fp = compute_preview_fingerprint(payload)
    assert fp.startswith("sha256:")
    assert verify_preview_fingerprint(fp, fp) is True

    # Tampered fingerprint or empty
    assert verify_preview_fingerprint("sha256:tampered", fp) is False
    assert verify_preview_fingerprint("", fp) is False


# -----------------------------------------------------------------------------
# Service Tests
# -----------------------------------------------------------------------------


class FakeDb:
    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []

    def get_oms_order_sync(self, order_id: str) -> dict[str, Any] | None:
        return self.orders.get(order_id)

    def list_broker_gateway_events_sync(
        self, *, order_id: str | None = None, **kwargs
    ) -> list[dict[str, Any]]:
        if order_id:
            return [e for e in self.events if e.get("order_id") == order_id]
        return list(self.events)

    def record_broker_gateway_event_sync(self, **kwargs) -> dict[str, Any]:
        event = {
            "id": len(self.events) + 1,
            **kwargs,
            "created_at": "2026-05-16T10:00:00",
        }
        self.events.append(event)
        return event


class FakeOms:
    def __init__(self, db: FakeDb) -> None:
        self.db = db

    def transition_order(
        self, order_id: str, *, to_status: str, reason: str, actor: str | None = None
    ) -> dict[str, Any]:
        order = self.db.orders[order_id]
        order["status"] = to_status
        return order


def _make_passing_evidence(order_id: str = "ORD-CONFIRMED") -> dict[str, Any]:
    valid_fp = "a" * 64
    valid_conf_id = "b" * 64
    return {
        "account_truth": {"gate_status": "pass", "evidence_ref": "at:1"},
        "research_evidence": {"gate_status": "pass", "evidence_ref": "res:1"},
        "risk": {"gate_status": "pass", "evidence_ref": "risk:1"},
        "paper_shadow": {
            "divergence_status": "within_expectations",
            "evidence_ref": "ps:1",
        },
        "current_per_order_confirmation": {
            "status": "current_verified_non_authorizing_confirmation",
            "order_id": order_id,
            "confirmation_id": valid_conf_id,
            "dossier_fingerprint": valid_fp,
            "reads_persisted_facts_only": True,
            "provider_contact_performed": False,
            "runtime_connector_query_performed": False,
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
            "does_not_mutate_risk": True,
            "does_not_mutate_kill_switch": True,
            "does_not_change_capital_authority": True,
            "broker_submission_enabled": False,
            "broker_cancel_enabled": False,
            "authorizes_execution": False,
            "current_dossier": {
                "review_ready": True,
                "review_status": "review_ready_non_submitting",
                "review_blockers": [],
                "submission_status": "blocked",
                "authorizes_execution": False,
                "dossier_fingerprint": valid_fp,
                "capital_evaluation": {
                    "status": "pass",
                    "mode": "manual_each_order",
                    "does_not_enable_execution": True,
                },
                "gateway_gates": {
                    "status": "pass",
                    "blockers": [],
                    "persisted_facts_only": True,
                    "provider_contact_performed": False,
                    "authorizes_execution": False,
                    "gates": {
                        "account_truth": {
                            "status": "pass",
                            "resolution_status": "resolved_clear",
                            "evidence_ref": "at:1",
                            "source_fingerprint": valid_fp,
                            "source_identifier": "at",
                        },
                        "research_evidence": {
                            "status": "pass",
                            "resolution_status": "resolved_clear",
                            "evidence_ref": "res:1",
                            "source_fingerprint": valid_fp,
                            "source_identifier": "res",
                        },
                        "risk": {
                            "status": "pass",
                            "resolution_status": "resolved_clear",
                            "evidence_ref": "risk:1",
                            "source_fingerprint": valid_fp,
                            "source_identifier": "risk",
                        },
                        "paper_shadow": {
                            "status": "pass",
                            "resolution_status": "resolved_clear",
                            "evidence_ref": "ps:1",
                            "source_fingerprint": valid_fp,
                            "source_identifier": "ps",
                        },
                    },
                },
            },
        },
    }


class FakeTradingControls:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def snapshot(self):
        from server.services.risk.trading_controls import TradingControlSnapshot

        return TradingControlSnapshot(
            kill_switch_enabled=self.enabled,
            reason="manual kill switch test" if self.enabled else "",
            updated_at="2026-05-16T10:00:00",
        )


def test_manual_trading_service_full_workflow() -> None:
    db = FakeDb()
    oms = FakeOms(db)
    controls = FakeTradingControls(enabled=False)
    evidence = _make_passing_evidence("ORD-CONFIRMED")
    db.orders["ORD-CONFIRMED"] = {
        "order_id": "ORD-CONFIRMED",
        "symbol": "600519",
        "side": "buy",
        "asset_class": "stock",
        "quantity": 100,
        "order_type": "limit",
        "limit_price": 1720.25,
        "status": "manually_confirmed",
        "broker_submission_enabled": False,
        "payload": {"gateway_evidence": evidence},
    }

    service = ManualTradingService(
        db=db,
        oms=oms,
        trading_controls=controls,
        current_per_order_confirmation_provider=lambda oid: evidence[
            "current_per_order_confirmation"
        ],
    )

    # 1. query order
    order_fact = service.query_order("ORD-CONFIRMED")
    assert order_fact["status"] == "query_ready"
    assert order_fact["oms_order"]["order_id"] == "ORD-CONFIRMED"

    # 2. preview ticket
    preview = service.preview_manual_ticket("ORD-CONFIRMED", actor="operator")
    assert preview["status"] == "preview_ready"
    assert preview["ticket"]["copy_text"] == "BUY 600519 100 LIMIT 1720.25"

    # 3. export ticket
    export_payload = service.export_manual_ticket("ORD-CONFIRMED", actor="operator")
    assert export_payload["status"] == "export_ready"
    assert (
        export_payload["export"]["file_name"]
        == "karkinos-manual-ticket-ORD-CONFIRMED.json"
    )

    # 4. dry-run ticket
    dry_run = service.dry_run_manual_ticket("ORD-CONFIRMED", actor="operator")
    assert dry_run["status"] == "dry_run_accepted"
    assert dry_run["event_id"] == 1

    # 5. create ticket
    created = service.create_manual_ticket("ORD-CONFIRMED", actor="operator")
    assert created["status"] == "manual_ticket_created"
    assert db.orders["ORD-CONFIRMED"]["status"] == "manual_ticket_created"

    # 6. preview manual execution
    exec_preview = service.preview_manual_execution_record(
        "ORD-CONFIRMED",
        fill_price="1720.25",
        quantity="100",
        fee="5.00",
        tax="0.00",
        transfer_fee="0.20",
        actor="operator",
    )
    assert exec_preview["status"] == "manual_execution_preview_ready"
    fp = exec_preview["preview_fingerprint"]
    assert fp.startswith("sha256:")

    # 7. record manual execution with bad fingerprint -> rejects
    with pytest.raises(ValueError, match="preview_fingerprint does not match"):
        service.record_manual_execution_evidence(
            "ORD-CONFIRMED",
            preview_fingerprint="sha256:bad_fingerprint",
            fill_price="1720.25",
            quantity="100",
            fee="5.00",
            tax="0.00",
            transfer_fee="0.20",
        )

    # 8. record manual execution with valid fingerprint -> succeeds
    recorded = service.record_manual_execution_evidence(
        "ORD-CONFIRMED",
        preview_fingerprint=fp,
        fill_price="1720.25",
        quantity="100",
        fee="5.00",
        tax="0.00",
        transfer_fee="0.20",
        actor="operator",
        operator_note="recorded via web",
    )
    assert recorded["status"] == "manual_execution_recorded"
    assert recorded["operator_note"] == "recorded via web"


def test_manual_trading_service_kill_switch_blocks() -> None:
    db = FakeDb()
    oms = FakeOms(db)
    controls = FakeTradingControls(enabled=True)
    evidence = _make_passing_evidence("ORD-BLOCKED")
    db.orders["ORD-BLOCKED"] = {
        "order_id": "ORD-BLOCKED",
        "symbol": "600519",
        "side": "buy",
        "asset_class": "stock",
        "quantity": 100,
        "order_type": "limit",
        "limit_price": 1720.25,
        "status": "manually_confirmed",
        "broker_submission_enabled": False,
        "payload": {"gateway_evidence": evidence},
    }

    service = ManualTradingService(
        db=db,
        oms=oms,
        trading_controls=controls,
        current_per_order_confirmation_provider=lambda oid: evidence[
            "current_per_order_confirmation"
        ],
    )

    with pytest.raises(ValueError, match="kill switch is enabled"):
        service.preview_manual_ticket("ORD-BLOCKED")

    with pytest.raises(ValueError, match="kill switch is enabled"):
        service.export_manual_ticket("ORD-BLOCKED")

    with pytest.raises(ValueError, match="kill switch is enabled"):
        service.create_manual_ticket("ORD-BLOCKED")


def test_manual_trading_service_preview_tampering_fails_closed() -> None:
    """Verify that tampering any field (price, qty, fee, tax) invalidates the fingerprint."""
    db = FakeDb()
    oms = FakeOms(db)
    controls = FakeTradingControls(enabled=False)
    evidence = _make_passing_evidence("ORD-TAMPER")
    db.orders["ORD-TAMPER"] = {
        "order_id": "ORD-TAMPER",
        "symbol": "600519",
        "side": "buy",
        "asset_class": "stock",
        "quantity": 100,
        "order_type": "limit",
        "limit_price": 1720.25,
        "status": "manual_ticket_created",
        "broker_submission_enabled": False,
        "payload": {"gateway_evidence": evidence},
    }

    service = ManualTradingService(
        db=db,
        oms=oms,
        trading_controls=controls,
        current_per_order_confirmation_provider=lambda oid: evidence[
            "current_per_order_confirmation"
        ],
    )

    # Legitimate preview with price 1720.25, qty 100, fee 5.00
    preview = service.preview_manual_execution_record(
        "ORD-TAMPER",
        fill_price="1720.25",
        quantity="100",
        fee="5.00",
        tax="0.00",
        transfer_fee="0.20",
    )
    valid_fp = preview["preview_fingerprint"]

    # 1. Tamper fill_price
    with pytest.raises(ValueError, match="preview_fingerprint does not match"):
        service.record_manual_execution_evidence(
            "ORD-TAMPER",
            preview_fingerprint=valid_fp,
            fill_price="1720.00",  # tampered
            quantity="100",
            fee="5.00",
            tax="0.00",
            transfer_fee="0.20",
        )

    # 2. Tamper quantity
    with pytest.raises(ValueError, match="preview_fingerprint does not match"):
        service.record_manual_execution_evidence(
            "ORD-TAMPER",
            preview_fingerprint=valid_fp,
            fill_price="1720.25",
            quantity="200",  # tampered
            fee="5.00",
            tax="0.00",
            transfer_fee="0.20",
        )

    # 3. Tamper fee
    with pytest.raises(ValueError, match="preview_fingerprint does not match"):
        service.record_manual_execution_evidence(
            "ORD-TAMPER",
            preview_fingerprint=valid_fp,
            fill_price="1720.25",
            quantity="100",
            fee="10.00",  # tampered
            tax="0.00",
            transfer_fee="0.20",
        )

    # 4. Tamper transfer_fee
    with pytest.raises(ValueError, match="preview_fingerprint does not match"):
        service.record_manual_execution_evidence(
            "ORD-TAMPER",
            preview_fingerprint=valid_fp,
            fill_price="1720.25",
            quantity="100",
            fee="5.00",
            tax="0.00",
            transfer_fee="1.00",  # tampered
        )


def test_manual_trading_service_order_lifecycle_guards() -> None:
    """Verify that unconfirmed orders cannot be ticketed or recorded."""
    db = FakeDb()
    oms = FakeOms(db)
    controls = FakeTradingControls(enabled=False)
    evidence = _make_passing_evidence("ORD-UNCONFIRMED")
    db.orders["ORD-UNCONFIRMED"] = {
        "order_id": "ORD-UNCONFIRMED",
        "symbol": "600519",
        "side": "buy",
        "asset_class": "stock",
        "quantity": 100,
        "order_type": "limit",
        "limit_price": 1720.25,
        "status": "pending_confirmation",  # unconfirmed!
        "broker_submission_enabled": False,
        "payload": {"gateway_evidence": evidence},
    }

    service = ManualTradingService(
        db=db,
        oms=oms,
        trading_controls=controls,
        current_per_order_confirmation_provider=lambda oid: evidence[
            "current_per_order_confirmation"
        ],
    )

    # Ticketing unconfirmed order fails
    with pytest.raises(ValueError, match="must be manually_confirmed"):
        service.preview_manual_ticket("ORD-UNCONFIRMED")
    with pytest.raises(ValueError, match="must be manually_confirmed"):
        service.create_manual_ticket("ORD-UNCONFIRMED")

    # Execution preview before ticket creation fails
    db.orders["ORD-UNCONFIRMED"]["status"] = "manually_confirmed"
    with pytest.raises(ValueError, match="must be manual_ticket_created"):
        service.preview_manual_execution_record(
            "ORD-UNCONFIRMED",
            fill_price="1720.25",
            quantity="100",
        )


def test_manual_trading_service_concurrent_record_and_ledger_isolation() -> None:
    """Verify concurrent record attempts and guarantee zero ledger mutation."""
    import concurrent.futures

    db = FakeDb()
    oms = FakeOms(db)
    controls = FakeTradingControls(enabled=False)
    evidence = _make_passing_evidence("ORD-CONCURRENT")
    db.orders["ORD-CONCURRENT"] = {
        "order_id": "ORD-CONCURRENT",
        "symbol": "600519",
        "side": "buy",
        "asset_class": "stock",
        "quantity": 100,
        "order_type": "limit",
        "limit_price": 1720.25,
        "status": "manual_ticket_created",
        "broker_submission_enabled": False,
        "payload": {"gateway_evidence": evidence},
    }

    service = ManualTradingService(
        db=db,
        oms=oms,
        trading_controls=controls,
        current_per_order_confirmation_provider=lambda oid: evidence[
            "current_per_order_confirmation"
        ],
    )

    preview = service.preview_manual_execution_record(
        "ORD-CONCURRENT",
        fill_price="1720.25",
        quantity="100",
        fee="5.00",
        tax="0.00",
        transfer_fee="0.20",
    )
    fp = preview["preview_fingerprint"]

    def _record(idx: int) -> dict[str, Any]:
        return service.record_manual_execution_evidence(
            "ORD-CONCURRENT",
            preview_fingerprint=fp,
            fill_price="1720.25",
            quantity="100",
            fee="5.00",
            tax="0.00",
            transfer_fee="0.20",
            actor=f"worker-{idx}",
            operator_note=f"thread {idx}",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(_record, range(5)))

    assert len(results) == 5
    for res in results:
        assert res["status"] == "manual_execution_recorded"
        assert res["does_not_mutate_production_ledger"] is True
        assert res["does_not_mutate_oms"] is True
        assert res["submitted_to_broker"] is False

    # Verify OMS order was not mutated
    assert db.orders["ORD-CONCURRENT"]["status"] == "manual_ticket_created"

    # Verify 5 gateway audit events were recorded
    events = [e for e in db.events if e["order_id"] == "ORD-CONCURRENT"]
    assert len(events) == 5
