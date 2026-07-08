from __future__ import annotations

import json
from pathlib import Path

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from server.db import AppDatabase
from server.services.broker_gateway import BrokerGatewayService
from server.services.execution_reconciliation import ExecutionReconciliationService
from server.services.oms import OmsService


def _db_and_oms(tmp_path) -> tuple[AppDatabase, OmsService]:
    db = AppDatabase(tmp_path / "execution-reconciliation.db")
    db.init_sync()
    return db, OmsService(db=db)


def _required_gateway_evidence() -> dict:
    return {
        "account_truth": {"gate_status": "pass", "evidence_ref": "account-truth:1"},
        "research_evidence": {"gate_status": "pass", "evidence_ref": "research:1"},
        "risk": {"gate_status": "passed", "evidence_ref": "risk:risk-001"},
        "paper_shadow": {
            "divergence_status": "within_expectations",
            "evidence_ref": "paper_shadow:run-001",
        },
    }


def _confirmed_order(
    db: AppDatabase,
    oms: OmsService,
    *,
    gateway_evidence: bool = False,
) -> dict:
    order = oms.create_order_intent(
        intent_key="daily:2026-07-02:600519:buy",
        symbol="600519",
        side="buy",
        asset_class="stock",
        quantity=100,
        order_type="limit",
        limit_price=1688.0,
        source="daily_trading_plan",
        source_ref="shadow:2026-07-02:abc",
    )
    if gateway_evidence:
        order = db.upsert_oms_order_sync(
            {
                **order,
                "payload": {
                    "schema_version": "karkinos.oms_order.v1",
                    "manual_confirmation_required": True,
                    "does_not_submit_broker_order": True,
                    "gateway_evidence": _required_gateway_evidence(),
                },
            }
        )
    return oms.transition_order(
        order["order_id"],
        to_status="manually_confirmed",
        reason="operator approved paper/shadow evidence",
        actor="test",
    )


def test_reconciliation_flags_confirmed_order_without_gateway_action(tmp_path) -> None:
    db, oms = _db_and_oms(tmp_path)
    order = _confirmed_order(db, oms)
    service = ExecutionReconciliationService(db=db)

    run = service.run_reconciliation(run_date="2026-07-02")

    assert run["status"] == "open_items"
    by_order = {item["order_id"]: item for item in run["items"]}
    assert by_order[order["order_id"]]["item_status"] == "gateway_action_missing"
    assert (
        by_order[order["order_id"]]["suggested_action"]
        == "create_manual_ticket_or_cancel"
    )


def test_reconciliation_treats_paper_shadow_oms_order_as_simulation_evidence(
    tmp_path,
) -> None:
    db, oms = _db_and_oms(tmp_path)
    order = oms.create_paper_shadow_order(
        intent_key="paper-shadow:shadow:2026-07-02:abc:action:ACTION-1",
        order_id="SHADOW-2026-07-02-001-600519-buy-abcdef1234",
        run_id="shadow:2026-07-02:abc",
        symbol="600519",
        side="buy",
        asset_class="stock",
        quantity=100,
        order_type="limit",
        limit_price=1688.0,
        source_ref="action:ACTION-1",
    )
    for status in ("submitted", "accepted", "filled"):
        order = oms.transition_order(
            order["order_id"],
            to_status=status,
            reason=f"paper shadow {status}",
            actor="paper-shadow",
            source="paper_shadow_daily",
        )
    service = ExecutionReconciliationService(db=db)

    run = service.run_reconciliation(run_date="2026-07-02")

    assert run["status"] == "clear"
    assert run["open_item_count"] == 0
    by_order = {item["order_id"]: item for item in run["items"]}
    item = by_order[order["order_id"]]
    assert item["item_status"] == "paper_shadow_simulation"
    assert item["suggested_action"] == "no_action"
    assert json.loads(item["payload_json"])["execution_mode"] == "paper_shadow"


def test_reconciliation_flags_manual_ticket_waiting_for_broker_evidence(
    tmp_path,
) -> None:
    db, oms = _db_and_oms(tmp_path)
    order = _confirmed_order(db, oms, gateway_evidence=True)
    BrokerGatewayService(db=db).create_manual_ticket(order["order_id"], actor="test")
    service = ExecutionReconciliationService(db=db)

    run = service.run_reconciliation(run_date="2026-07-02")

    by_order = {item["order_id"]: item for item in run["items"]}
    item = by_order[order["order_id"]]
    assert item["item_status"] == "awaiting_broker_evidence"
    assert item["suggested_action"] == "import_broker_statement_or_update_order"
    assert item["gateway_event_count"] == 1


def test_reconciliation_surfaces_manual_execution_record_without_ledger_mutation(
    tmp_path,
) -> None:
    db, oms = _db_and_oms(tmp_path)
    order = _confirmed_order(db, oms, gateway_evidence=True)
    gateway = BrokerGatewayService(db=db)
    gateway.create_manual_ticket(order["order_id"], actor="test")
    preview = gateway.preview_manual_execution_record(
        order["order_id"],
        actor="test",
        fill_price="1688.00",
        quantity="100",
        fee="5.00",
        tax="0.00",
        transfer_fee="0.00",
    )
    record = gateway.record_manual_execution_evidence(
        order["order_id"],
        actor="test",
        preview_fingerprint=preview["preview_fingerprint"],
        fill_price="1688.00",
        quantity="100",
        fee="5.00",
        tax="0.00",
        transfer_fee="0.00",
        operator_note="broker terminal filled manually",
    )
    service = ExecutionReconciliationService(db=db)

    run = service.run_reconciliation(run_date="2026-07-02")

    assert run["status"] == "open_items"
    by_order = {item["order_id"]: item for item in run["items"]}
    item = by_order[order["order_id"]]
    assert item["item_status"] == "manual_execution_recorded"
    assert (
        item["suggested_action"]
        == "review_manual_execution_and_import_broker_statement"
    )
    assert item["gateway_event_count"] == 2
    assert item["broker_event_count"] == 0
    payload = json.loads(item["payload_json"])
    summary = payload["manual_execution_evidence_summary"]
    assert summary["source"] == "broker_gateway_event"
    assert summary["event_count"] == 1
    assert summary["event_ids"] == [record["event_id"]]
    assert summary["preview_fingerprint"] == preview["preview_fingerprint"]
    assert summary["fill_price"] == "1688.00"
    assert summary["quantity"] == "100"
    assert summary["gross_amount"] == "168800.00"
    assert summary["fee"] == "5.00"
    assert summary["tax"] == "0.00"
    assert summary["transfer_fee"] == "0.00"
    assert summary["net_cash_impact"] == "-168805.00"
    assert summary["ledger_entry_amount"] == "-168805.00"
    assert summary["review_required_before_ledger_update"] is True
    assert summary["requires_operator_ledger_save"] is True
    assert summary["submitted_to_broker"] is False
    assert summary["does_not_mutate_oms"] is True
    assert summary["does_not_mutate_production_ledger"] is True
    gate_summary = summary["required_gate_summary"]
    assert gate_summary == record["validation"]["required_gate_summary"]
    assert (
        gate_summary["schema_version"] == "karkinos.controlled_bridge_gate_summary.v1"
    )
    assert gate_summary["status"] == "pass"
    assert gate_summary["submitted_to_broker"] is False
    assert gate_summary["does_not_authorize_execution"] is True
    assert gate_summary["gates"]["risk"] == {
        "status": "pass",
        "evidence_ref": "risk:risk-001",
        "source": "oms_gateway_evidence",
    }
    assert gate_summary["gates"]["paper_shadow"] == {
        "status": "pass",
        "evidence_ref": "paper_shadow:run-001",
        "source": "oms_gateway_evidence",
    }
    assert gate_summary["gates"]["execution_reconciliation"] == {
        "status": "pending_after_manual_execution",
        "evidence_ref": f"execution_reconciliation:pending:{order['order_id']}",
        "source": "execution_reconciliation_runbook",
    }


def test_reconciliation_marks_manual_ticket_with_matching_broker_evidence_available(
    tmp_path,
) -> None:
    db, oms = _db_and_oms(tmp_path)
    order = _confirmed_order(db, oms, gateway_evidence=True)
    BrokerGatewayService(db=db).create_manual_ticket(order["order_id"], actor="test")
    _import_matching_broker_trade(Path(db._path))
    service = ExecutionReconciliationService(db=db)

    run = service.run_reconciliation(run_date="2026-07-02")

    by_order = {item["order_id"]: item for item in run["items"]}
    item = by_order[order["order_id"]]
    assert item["item_status"] == "broker_evidence_available"
    assert item["suggested_action"] == "review_broker_evidence_match"
    assert item["gateway_event_count"] == 1
    assert item["broker_event_count"] == 1
    payload = json.loads(item["payload_json"])
    assert payload["broker_trade_cost_summary"] == {
        "source": "staged_broker_evidence",
        "event_count": 1,
        "event_ids": ["broker-buy-600519"],
        "currency": "CNY",
        "gross_amount": "168800.00",
        "fee": "5.00",
        "tax": "0",
        "transfer_fee": "0",
        "net_amount": "-168805.00",
        "review_required_before_ledger_update": True,
        "requires_reconciliation_before_ledger_update": True,
        "ledger_update_status": "review_required",
        "suggested_ledger_action": "review_staged_broker_evidence",
        "does_not_recommend_automatic_ledger_update": True,
        "does_not_mutate_production_ledger": True,
    }


def test_reconciliation_flags_broker_evidence_quantity_mismatch(tmp_path) -> None:
    db, oms = _db_and_oms(tmp_path)
    order = _confirmed_order(db, oms, gateway_evidence=True)
    BrokerGatewayService(db=db).create_manual_ticket(order["order_id"], actor="test")
    _import_broker_trade(
        Path(db._path),
        event_id="broker-buy-600519-mismatch",
        quantity=200,
    )
    service = ExecutionReconciliationService(db=db)

    run = service.run_reconciliation(run_date="2026-07-02")

    by_order = {item["order_id"]: item for item in run["items"]}
    item = by_order[order["order_id"]]
    assert item["item_status"] == "broker_evidence_mismatch"
    assert item["suggested_action"] == "review_broker_evidence_mismatch"
    assert item["gateway_event_count"] == 1
    assert item["broker_event_count"] == 1
    assert "quantity mismatch" in item["detail"]
    payload = json.loads(item["payload_json"])
    assert (
        payload["broker_trade_cost_summary"][
            "requires_reconciliation_before_ledger_update"
        ]
        is True
    )
    assert payload["broker_trade_cost_summary"]["ledger_update_status"] == (
        "review_required"
    )
    assert payload["broker_trade_cost_summary"]["suggested_ledger_action"] == (
        "review_staged_broker_evidence"
    )
    assert (
        payload["broker_trade_cost_summary"][
            "does_not_recommend_automatic_ledger_update"
        ]
        is True
    )


def _import_matching_broker_trade(db_path: Path) -> None:
    _import_broker_trade(db_path, event_id="broker-buy-600519", quantity=100)


def _import_broker_trade(
    db_path: Path,
    *,
    event_id: str,
    quantity: int,
) -> None:
    content = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note
{event_id},trade_buy,2026-07-02T10:05:00+08:00,2026-07-03,600519,贵州茅台,stock,CNY,{quantity},1688.00,168800.00,5.00,0.00,-168805.00,100000.00,{quantity},1688.05,manual ticket match
""".format(
        event_id=event_id,
        quantity=quantity,
    )
    repository = BrokerEvidenceRepository(db_path)
    repository.save_preview(
        parse_broker_statement_csv(content),
        source_name="broker_statement.csv",
    )
