"""Paper broker evidence tests."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from decimal import Decimal

import pytest

from core.types import AssetClass, OrderSide, OrderType, Symbol
from execution.paper_broker import (
    PAPER_BROKER_SCHEMA_VERSION,
    PaperBroker,
    PaperOmsInvalidTransitionError,
    PaperOmsStateMachine,
    PaperOrderContext,
    PaperOrderRequest,
    PaperOrderStatus,
)
from server.db import AppDatabase


def test_paper_broker_persists_simulation_evidence_without_mutating_ledger(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.insert_ledger_entry_sync(
        entry_type="cash",
        timestamp="2026-06-22T09:00:00",
        amount=10000.0,
        note="opening fixture cash",
        source="fixture",
        source_ref="opening-cash",
    )
    ledger_count_before = _ledger_entry_count(db._path)

    broker = PaperBroker(db=db, provider_name="paper-sim")
    result = broker.submit_order(
        PaperOrderRequest(
            timestamp=datetime(2026, 6, 22, 10, 1, 5),
            order_id="PAPER-ORD-1",
            symbol=Symbol("600000"),
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("200"),
            price=Decimal("10.00"),
            asset_class=AssetClass.STOCK,
            context=PaperOrderContext(
                strategy_id="dual_ma",
                signal_id="signal-001",
                risk_decision_id="risk-001",
                dataset_id="dataset:sha256-fixture",
                cost_model_id="stock_a_commission_v1",
                account_truth_version="account-truth:fixture",
            ),
        ),
        fill_id="PAPER-FILL-1",
        fill_quantity=Decimal("200"),
        fill_price=Decimal("10.02"),
    )

    saved_order = db.get_order_sync("PAPER-ORD-1")
    saved_fill = db.get_fill_sync("PAPER-FILL-1")
    order_payload = json.loads(saved_order["payload_json"])
    fill_metadata = json.loads(saved_fill["metadata_json"])

    assert result.order.status is PaperOrderStatus.FILLED
    assert result.order.schema_version == PAPER_BROKER_SCHEMA_VERSION
    assert result.order.does_not_mutate_production_ledger is True
    assert result.fill is not None
    assert result.fill.does_not_mutate_production_ledger is True

    assert saved_order["source"] == "paper_broker"
    assert saved_order["execution_mode"] == "paper"
    assert saved_order["status"] == "filled"
    assert saved_fill["source"] == "paper_broker"
    assert saved_fill["execution_mode"] == "paper"
    assert saved_fill["provider_name"] == "paper-sim"
    assert saved_fill["fill_quantity"] == 200.0
    assert saved_fill["fill_price"] == 10.02

    expected_context = {
        "strategy_id": "dual_ma",
        "signal_id": "signal-001",
        "risk_decision_id": "risk-001",
        "dataset_id": "dataset:sha256-fixture",
        "cost_model_id": "stock_a_commission_v1",
        "account_truth_version": "account-truth:fixture",
    }
    assert order_payload["schema_version"] == PAPER_BROKER_SCHEMA_VERSION
    assert order_payload["context"] == expected_context
    assert order_payload["status_history"] == [
        "staged",
        "submitted",
        "accepted",
        "filled",
    ]
    assert order_payload["oms_transitions"][-1] == {
        "order_id": "PAPER-ORD-1",
        "sequence": 4,
        "from_status": "accepted",
        "to_status": "filled",
        "filled_quantity": "200",
        "reason": "",
    }
    assert order_payload["does_not_mutate_production_ledger"] is True
    assert fill_metadata["schema_version"] == PAPER_BROKER_SCHEMA_VERSION
    assert fill_metadata["context"] == expected_context
    assert fill_metadata["does_not_mutate_production_ledger"] is True

    assert _ledger_entry_count(db._path) == ledger_count_before


def test_paper_broker_records_partial_fill_as_simulation_evidence(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    broker = PaperBroker(db=db)

    result = broker.submit_order(
        PaperOrderRequest(
            timestamp=datetime(2026, 6, 22, 10, 3, 5),
            order_id="PAPER-ORD-PARTIAL",
            symbol=Symbol("600000"),
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("300"),
            price=Decimal("9.90"),
            context=PaperOrderContext(strategy_id="bollinger"),
        ),
        fill_id="PAPER-FILL-PARTIAL",
        fill_quantity=Decimal("100"),
        fill_price=Decimal("9.88"),
    )

    saved_order = db.get_order_sync("PAPER-ORD-PARTIAL")
    order_payload = json.loads(saved_order["payload_json"])

    assert result.order.status is PaperOrderStatus.PARTIALLY_FILLED
    assert result.order.filled_quantity == Decimal("100")
    assert result.order.remaining_quantity == Decimal("200")
    assert saved_order["status"] == "partially_filled"
    assert order_payload["status_history"] == [
        "staged",
        "submitted",
        "accepted",
        "partially_filled",
    ]
    assert order_payload["oms_transitions"][-1]["to_status"] == "partially_filled"
    assert order_payload["oms_transitions"][-1]["filled_quantity"] == "100"


def test_paper_oms_state_machine_covers_all_review_states() -> None:
    oms = PaperOmsStateMachine(order_id="PAPER-OMS-1")

    oms.mark_submitted()
    oms.mark_accepted()
    oms.mark_partially_filled(filled_quantity=Decimal("100"))
    oms.mark_filled(filled_quantity=Decimal("300"))
    oms.mark_reconciled()

    assert oms.current_status is PaperOrderStatus.RECONCILED
    assert oms.filled_quantity == Decimal("300")
    assert [transition.to_status.value for transition in oms.transitions] == [
        "staged",
        "submitted",
        "accepted",
        "partially_filled",
        "filled",
        "reconciled",
    ]

    rejection = PaperOmsStateMachine(order_id="PAPER-OMS-REJECT")
    rejection.mark_submitted()
    rejection.mark_accepted()
    rejection.mark_rejected(reason="price limit breached")
    assert rejection.current_status is PaperOrderStatus.REJECTED
    assert rejection.transitions[-1].reason == "price limit breached"

    cancellation = PaperOmsStateMachine(order_id="PAPER-OMS-CANCEL")
    cancellation.mark_submitted()
    cancellation.mark_cancelled(reason="operator cancelled paper review")
    assert cancellation.current_status is PaperOrderStatus.CANCELLED

    expiry = PaperOmsStateMachine(order_id="PAPER-OMS-EXPIRE")
    expiry.mark_submitted()
    expiry.mark_accepted()
    expiry.mark_expired(reason="paper session closed")
    assert expiry.current_status is PaperOrderStatus.EXPIRED


def test_paper_oms_state_machine_is_idempotent_and_rejects_invalid_paths() -> None:
    oms = PaperOmsStateMachine(order_id="PAPER-OMS-IDEMPOTENT")

    first = oms.mark_submitted()
    second = oms.mark_submitted()

    assert first is second
    assert [transition.to_status.value for transition in oms.transitions] == [
        "staged",
        "submitted",
    ]

    oms.mark_accepted()
    oms.mark_cancelled(reason="cancelled once")
    duplicate_cancel = oms.mark_cancelled(reason="cancelled once")

    assert duplicate_cancel.to_status is PaperOrderStatus.CANCELLED
    assert [transition.to_status.value for transition in oms.transitions] == [
        "staged",
        "submitted",
        "accepted",
        "cancelled",
    ]

    with pytest.raises(PaperOmsInvalidTransitionError) as exc_info:
        oms.mark_filled(filled_quantity=Decimal("100"))

    assert exc_info.value.order_id == "PAPER-OMS-IDEMPOTENT"
    assert exc_info.value.from_status is PaperOrderStatus.CANCELLED
    assert exc_info.value.to_status is PaperOrderStatus.FILLED


def _ledger_entry_count(db_path) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0])
