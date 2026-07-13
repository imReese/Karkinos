from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from server.db import AppDatabase
from server.services.broker_gateway import BrokerGatewayService
from server.services.execution_reconciliation import ExecutionReconciliationService
from server.services.oms import OmsService
from server.services.per_order_confirmation import build_order_fingerprint


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


def _record_controlled_intent(
    db: AppDatabase,
    order: dict,
    *,
    status: str,
) -> dict:
    seed = str(order["order_id"])
    submit_intent_id = hashlib.sha256(f"intent:{seed}".encode()).hexdigest()
    submit_fingerprint = hashlib.sha256(f"submit:{seed}".encode()).hexdigest()
    order_fingerprint = build_order_fingerprint(order)
    prepared = db.prepare_controlled_broker_submit_intent_sync(
        intent={
            "submit_intent_id": submit_intent_id,
            "submit_fingerprint": submit_fingerprint,
            "order_id": order["order_id"],
            "order_fingerprint": order_fingerprint,
            "confirmation_id": "c" * 64,
            "dossier_fingerprint": "d" * 64,
            "gateway_id": "qmt-controlled-write-1",
            "gateway_verification_fingerprint": "e" * 64,
            "release_evidence_id": "f" * 64,
            "release_evidence_fingerprint": "a" * 64,
            "client_order_id": f"KARK-{submit_fingerprint[:32]}",
            "operator_id": "local-owner",
            "operator_approval_id": "b" * 64,
            "order_snapshot": {
                key: order.get(key)
                for key in (
                    "symbol",
                    "side",
                    "asset_class",
                    "quantity",
                    "order_type",
                    "limit_price",
                )
            },
            "prepared_at_epoch_ms": 1782957600000,
            "prepared_at": "2026-07-02T02:00:00+00:00",
            "payload": {
                "submit_intent_id": submit_intent_id,
                "submit_fingerprint": submit_fingerprint,
                "order_id": order["order_id"],
            },
            "created_at": "2026-07-02T02:00:00+00:00",
        }
    )
    assert prepared["external_call_permitted"] is True
    finalized = db.finalize_controlled_broker_submit_intent_sync(
        submit_intent_id=submit_intent_id,
        status=status,
        broker_order_id="BROKER-ORDER-1" if status == "submitted" else "",
        broker_status=(
            "accepted"
            if status == "submitted"
            else "rejected" if status == "rejected" else "gateway_submit_exception"
        ),
        result={
            "status": (
                "accepted"
                if status == "submitted"
                else "rejected" if status == "rejected" else "gateway_submit_exception"
            ),
            "client_order_id": f"KARK-{submit_fingerprint[:32]}",
            "order_fingerprint": order_fingerprint,
            "broker_order_id": ("BROKER-ORDER-1" if status == "submitted" else ""),
            "submitted": (
                True
                if status == "submitted"
                else False if status == "rejected" else None
            ),
        },
        actor="controlled-broker-submission",
        finalized_at_epoch_ms=1782957601000,
        finalized_at="2026-07-02T02:00:01+00:00",
    )
    return finalized["intent"]


def test_reconciliation_blocks_unknown_controlled_submission_without_mutation(
    tmp_path,
) -> None:
    db, oms = _db_and_oms(tmp_path)
    order = _confirmed_order(db, oms)
    intent = _record_controlled_intent(db, order, status="submission_unknown")

    run = ExecutionReconciliationService(db=db).run_reconciliation(
        run_date="2026-07-02"
    )

    item = next(row for row in run["items"] if row["order_id"] == order["order_id"])
    payload = json.loads(item["payload_json"])
    summary = payload["controlled_submission_evidence_summary"]
    assert run["status"] == "open_items"
    assert item["item_status"] == "controlled_submission_unknown"
    assert item["suggested_action"] == "recover_controlled_submission_by_query"
    assert summary["submit_intent_id"] == intent["submit_intent_id"]
    assert summary["new_submissions_blocked"] is True
    assert summary["recovery_resubmission_enabled"] is False
    assert summary["does_not_mutate_production_ledger"] is True
    assert db.get_ledger_entries_sync() == []

    db.upsert_execution_reconciliation_run_sync(
        run_id="execution-reconciliation:ordinary-review",
        run_date="2026-07-02",
        status="open_items",
        item_count=1,
        open_item_count=1,
        payload={"schema_version": "karkinos.execution_reconciliation.v1"},
        items=[
            {
                "order_id": "MANUAL-LATER",
                "item_status": "manual_execution_recorded",
                "suggested_action": (
                    "review_manual_execution_and_import_broker_statement"
                ),
                "detail": "Ordinary review inserted after controlled unknown.",
                "payload": {},
            }
        ],
    )
    prioritized = db.list_execution_reconciliation_open_items_sync()
    assert [row["order_id"] for row in prioritized] == [
        order["order_id"],
        "MANUAL-LATER",
    ]

    db.finalize_controlled_broker_submit_intent_sync(
        submit_intent_id=intent["submit_intent_id"],
        status="rejected",
        broker_order_id="",
        broker_status="not_found",
        result={
            "status": "not_found",
            "submitted": False,
            "definitive": True,
        },
        actor="controlled-broker-submission",
        finalized_at_epoch_ms=1782957631000,
        finalized_at="2026-07-02T02:00:31+00:00",
        recovered=True,
    )
    ExecutionReconciliationService(db=db).run_reconciliation(run_date="2026-07-03")

    current_open = db.list_execution_reconciliation_open_items_sync()
    assert [row["order_id"] for row in current_open] == ["MANUAL-LATER"]
    historical = db.list_execution_reconciliation_items_sync(
        "execution-reconciliation:2026-07-02"
    )
    assert historical[0]["item_status"] == "controlled_submission_unknown"


def test_reconciliation_requires_review_for_submitted_controlled_broker_evidence(
    tmp_path,
) -> None:
    db, oms = _db_and_oms(tmp_path)
    order = _confirmed_order(db, oms)
    intent = _record_controlled_intent(db, order, status="submitted")
    _import_matching_broker_trade(
        Path(db._path),
        broker_order_id=intent["broker_order_id"],
        client_order_id=intent["client_order_id"],
    )

    run = ExecutionReconciliationService(db=db).run_reconciliation(
        run_date="2026-07-02"
    )

    item = next(row for row in run["items"] if row["order_id"] == order["order_id"])
    payload = json.loads(item["payload_json"])
    assert item["item_status"] == ("controlled_submission_broker_evidence_available")
    assert item["suggested_action"] == ("review_controlled_submission_broker_evidence")
    assert item["broker_event_count"] == 1
    assert (
        payload["controlled_submission_evidence_summary"]["new_submissions_blocked"]
        is True
    )
    assert db.get_oms_order_sync(order["order_id"])["status"] == "submitted"
    assert db.get_ledger_entries_sync() == []


def test_reconciliation_blocks_conflicting_controlled_order_identity(tmp_path) -> None:
    db, oms = _db_and_oms(tmp_path)
    order = _confirmed_order(db, oms)
    intent = _record_controlled_intent(db, order, status="submitted")
    _import_broker_trade(
        Path(db._path),
        event_id="broker-buy-conflicting-client-id",
        quantity=100,
        broker_order_id=intent["broker_order_id"],
        client_order_id="KARK-conflicting-client-order",
    )

    run = ExecutionReconciliationService(db=db).run_reconciliation(
        run_date="2026-07-02"
    )

    item = next(row for row in run["items"] if row["order_id"] == order["order_id"])
    payload = json.loads(item["payload_json"])
    summary = payload["controlled_submission_evidence_summary"]
    assert run["status"] == "open_items"
    assert item["item_status"] == "controlled_submission_broker_identity_conflict"
    assert item["suggested_action"] == (
        "enable_kill_switch_and_review_controlled_submission"
    )
    assert "controlled_submission_order_identity_conflict" in (
        payload["mismatch_reasons"]
    )
    assert summary["broker_order_identity_match_count"] == 0
    assert summary["broker_order_identity_conflict_count"] == 1
    assert summary["new_submissions_blocked"] is True
    assert db.list_fills_sync(order_id=order["order_id"]) == []
    assert db.get_ledger_entries_sync() == []


def test_reconciliation_treats_definitive_controlled_rejection_as_terminal(
    tmp_path,
) -> None:
    db, oms = _db_and_oms(tmp_path)
    order = _confirmed_order(db, oms)
    _record_controlled_intent(db, order, status="rejected")

    run = ExecutionReconciliationService(db=db).run_reconciliation(
        run_date="2026-07-02"
    )

    item = next(row for row in run["items"] if row["order_id"] == order["order_id"])
    assert run["status"] == "clear"
    assert item["item_status"] == "controlled_submission_rejected"
    assert item["suggested_action"] == "no_action"
    assert db.get_oms_order_sync(order["order_id"])["status"] == "rejected"
    assert db.get_ledger_entries_sync() == []


def test_reconciliation_flags_any_broker_trade_after_controlled_rejection(
    tmp_path,
) -> None:
    db, oms = _db_and_oms(tmp_path)
    order = _confirmed_order(db, oms)
    _record_controlled_intent(db, order, status="rejected")
    _import_broker_trade(
        Path(db._path),
        event_id="broker-buy-after-rejection",
        quantity=50,
        gross_amount="84400.00",
        net_amount="-84405.00",
    )

    run = ExecutionReconciliationService(db=db).run_reconciliation(
        run_date="2026-07-02"
    )

    item = next(row for row in run["items"] if row["order_id"] == order["order_id"])
    payload = json.loads(item["payload_json"])
    assert run["status"] == "open_items"
    assert item["item_status"] == "controlled_rejection_broker_evidence_conflict"
    assert item["suggested_action"] == (
        "enable_kill_switch_and_review_controlled_submission"
    )
    assert (
        "controlled_rejection_has_broker_trade_evidence" in payload["mismatch_reasons"]
    )
    assert db.get_ledger_entries_sync() == []


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


def test_manual_ticket_execution_and_broker_import_form_a_non_mutating_audit_chain(
    tmp_path,
) -> None:
    db, oms = _db_and_oms(tmp_path)
    order = _confirmed_order(db, oms, gateway_evidence=True)
    gateway = BrokerGatewayService(db=db)
    ledger_count_before = _ledger_entry_count(Path(db._path))

    ticket = gateway.create_manual_ticket(order["order_id"], actor="test")
    preview = gateway.preview_manual_execution_record(
        order["order_id"],
        actor="test",
        fill_price="1688.00",
        quantity="100",
        fee="5.00",
        tax="0.00",
        transfer_fee="0.20",
    )
    recorded = gateway.record_manual_execution_evidence(
        order["order_id"],
        actor="test",
        preview_fingerprint=preview["preview_fingerprint"],
        fill_price="1688.00",
        quantity="100",
        fee="5.00",
        tax="0.00",
        transfer_fee="0.20",
        operator_note="manually entered at broker terminal",
    )
    _import_broker_trade(
        Path(db._path),
        event_id="broker-buy-600519-audit-chain",
        quantity=100,
        transfer_fee="0.20",
        net_amount="-168805.20",
    )

    run = ExecutionReconciliationService(db=db).run_reconciliation(
        run_date="2026-07-02"
    )

    item = next(row for row in run["items"] if row["order_id"] == order["order_id"])
    payload = json.loads(item["payload_json"])
    comparison = payload["manual_broker_comparison"]
    persisted_order = db.get_oms_order_sync(order["order_id"])
    assert ticket["submitted_to_broker"] is False
    assert recorded["submitted_to_broker"] is False
    assert recorded["does_not_mutate_oms"] is True
    assert recorded["does_not_mutate_production_ledger"] is True
    assert item["item_status"] == "broker_evidence_available"
    assert item["suggested_action"] == "review_broker_evidence_match"
    assert comparison["status"] == "match"
    assert comparison["mismatch_reasons"] == []
    assert comparison["compared_values"]["fill_price"] == {
        "manual": "1688.00",
        "broker": "1688.00",
    }
    assert comparison["compared_values"]["transfer_fee"] == {
        "manual": "0.20",
        "broker": "0.20",
    }
    assert comparison["compared_values"]["net_amount"] == {
        "manual": "-168805.20",
        "broker": "-168805.20",
    }
    assert comparison["review_required_before_ledger_update"] is True
    assert comparison["does_not_recommend_automatic_ledger_update"] is True
    assert comparison["does_not_mutate_oms"] is True
    assert comparison["does_not_mutate_production_ledger"] is True
    assert persisted_order is not None
    assert persisted_order["status"] == "manual_ticket_created"
    assert _ledger_entry_count(Path(db._path)) == ledger_count_before


def test_reconciliation_queues_manual_execution_cost_mismatch_without_mutation(
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
        transfer_fee="0.20",
    )
    gateway.record_manual_execution_evidence(
        order["order_id"],
        actor="test",
        preview_fingerprint=preview["preview_fingerprint"],
        fill_price="1688.00",
        quantity="100",
        fee="5.00",
        tax="0.00",
        transfer_fee="0.20",
    )
    ledger_count_before = _ledger_entry_count(Path(db._path))
    _import_broker_trade(
        Path(db._path),
        event_id="broker-buy-600519-price-mismatch",
        quantity=100,
        price="1689.00",
        gross_amount="168900.00",
        fee="6.00",
        transfer_fee="0.20",
        net_amount="-168906.20",
    )

    run = ExecutionReconciliationService(db=db).run_reconciliation(
        run_date="2026-07-02"
    )

    item = next(row for row in run["items"] if row["order_id"] == order["order_id"])
    payload = json.loads(item["payload_json"])
    comparison = payload["manual_broker_comparison"]
    assert item["item_status"] == "broker_evidence_mismatch"
    assert item["suggested_action"] == "review_broker_evidence_mismatch"
    assert comparison["status"] == "mismatch"
    assert set(comparison["mismatch_reasons"]) >= {
        "manual_execution_fill_price_mismatch",
        "manual_execution_gross_amount_mismatch",
        "manual_execution_fee_mismatch",
        "manual_execution_net_amount_mismatch",
    }
    assert payload["mismatch_reasons"] == comparison["mismatch_reasons"]
    assert comparison["does_not_mutate_oms"] is True
    assert comparison["does_not_mutate_production_ledger"] is True
    assert db.get_oms_order_sync(order["order_id"])["status"] == (
        "manual_ticket_created"
    )
    assert _ledger_entry_count(Path(db._path)) == ledger_count_before


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


def _import_matching_broker_trade(
    db_path: Path,
    *,
    broker_order_id: str = "",
    client_order_id: str = "",
) -> None:
    _import_broker_trade(
        db_path,
        event_id="broker-buy-600519",
        quantity=100,
        broker_order_id=broker_order_id,
        client_order_id=client_order_id,
    )


def _import_broker_trade(
    db_path: Path,
    *,
    event_id: str,
    quantity: int,
    price: str = "1688.00",
    gross_amount: str = "168800.00",
    fee: str = "5.00",
    tax: str = "0.00",
    transfer_fee: str = "0.00",
    net_amount: str = "-168805.00",
    broker_order_id: str = "",
    client_order_id: str = "",
) -> None:
    content = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,broker_order_id,client_order_id
{event_id},trade_buy,2026-07-02T10:05:00+08:00,2026-07-03,600519,贵州茅台,stock,CNY,{quantity},{price},{gross_amount},{fee},{tax},{net_amount},100000.00,{quantity},1688.05,manual ticket match,{transfer_fee},{broker_order_id},{client_order_id}
""".format(
        event_id=event_id,
        quantity=quantity,
        price=price,
        gross_amount=gross_amount,
        fee=fee,
        tax=tax,
        transfer_fee=transfer_fee,
        net_amount=net_amount,
        broker_order_id=broker_order_id,
        client_order_id=client_order_id,
    )
    repository = BrokerEvidenceRepository(db_path)
    repository.save_preview(
        parse_broker_statement_csv(content),
        source_name="broker_statement.csv",
    )


def _ledger_entry_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0])
