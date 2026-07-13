from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_order_lifecycle import (
    BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleEvidenceRepository,
    broker_order_lifecycle_clearance_blockers,
    preview_qmt_order_lifecycle_export,
)
from account_truth.broker_statement import parse_broker_statement_csv
from server.db import AppDatabase
from server.services.execution_reconciliation import ExecutionReconciliationService
from server.services.oms import OmsService
from server.services.per_order_confirmation import build_order_fingerprint

NOW = datetime(2026, 7, 13, 4, 0, 0, tzinfo=UTC)


def _environment(tmp_path) -> tuple[AppDatabase, dict, dict]:
    db = AppDatabase(tmp_path / "execution-lifecycle.db")
    db.init_sync()
    oms = OmsService(db=db)
    order = oms.create_order_intent(
        intent_key="daily:2026-07-13:600519:buy",
        symbol="600519",
        side="buy",
        asset_class="stock",
        quantity=100,
        order_type="limit",
        limit_price=10.5,
        source="daily_trading_plan",
        source_ref="shadow:2026-07-13:abc",
    )
    order = oms.transition_order(
        order["order_id"],
        to_status="manually_confirmed",
        reason="operator confirmed exact test order",
        actor="test",
    )
    submit_intent_id = hashlib.sha256(
        f"intent:{order['order_id']}".encode()
    ).hexdigest()
    submit_fingerprint = hashlib.sha256(
        f"submit:{order['order_id']}".encode()
    ).hexdigest()
    client_order_id = f"KARK-{submit_fingerprint[:32]}"
    prepared = db.prepare_controlled_broker_submit_intent_sync(
        intent={
            "submit_intent_id": submit_intent_id,
            "submit_fingerprint": submit_fingerprint,
            "order_id": order["order_id"],
            "order_fingerprint": build_order_fingerprint(order),
            "confirmation_id": "c" * 64,
            "dossier_fingerprint": "d" * 64,
            "gateway_id": "qmt-controlled-write-1",
            "gateway_verification_fingerprint": "e" * 64,
            "release_evidence_id": "f" * 64,
            "release_evidence_fingerprint": "a" * 64,
            "client_order_id": client_order_id,
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
            "prepared_at_epoch_ms": int(NOW.timestamp() * 1000),
            "prepared_at": NOW.isoformat(),
            "payload": {
                "submit_intent_id": submit_intent_id,
                "submit_fingerprint": submit_fingerprint,
                "order_id": order["order_id"],
                "account_alias": "main-cn-account",
            },
            "created_at": NOW.isoformat(),
        }
    )
    assert prepared["external_call_permitted"] is True
    finalized = db.finalize_controlled_broker_submit_intent_sync(
        submit_intent_id=submit_intent_id,
        status="submitted",
        broker_order_id="QMT-ORDER-1",
        broker_status="accepted",
        result={
            "status": "accepted",
            "client_order_id": client_order_id,
            "order_fingerprint": build_order_fingerprint(order),
            "broker_order_id": "QMT-ORDER-1",
            "submitted": True,
        },
        actor="controlled-broker-submission",
        finalized_at_epoch_ms=int(NOW.timestamp() * 1000) + 1000,
        finalized_at=(NOW + timedelta(seconds=1)).isoformat(),
    )
    return db, db.get_oms_order_sync(order["order_id"]), finalized["intent"]


def _lifecycle_export(
    intent: dict,
    *,
    source_sequence: int,
    status: str,
    filled_quantity: str,
    cancelled_quantity: str,
    captured_at: datetime,
    client_order_id: str | None = None,
) -> dict:
    effective_client_order_id = client_order_id or intent["client_order_id"]
    fills = []
    if filled_quantity != "0":
        fills.append(
            {
                "broker_trade_id": "QMT-TRADE-1",
                "broker_order_id": intent["broker_order_id"],
                "client_order_id": effective_client_order_id,
                "symbol": "600519",
                "side": "buy",
                "quantity": filled_quantity,
                "price": "10.5",
                "fee": "1.2",
                "tax": "0",
                "transfer_fee": "0.02",
                "net_amount": "-421.22",
                "filled_at": (captured_at - timedelta(seconds=2)).isoformat(),
            }
        )
    return {
        "schema_version": "karkinos.qmt_order_lifecycle_export.v1",
        "provider": "qmt",
        "snapshot_kind": "exact_order_lifecycle",
        "gateway_id": intent["gateway_id"],
        "account_id": "private-qmt-account-001",
        "account_alias": "main-cn-account",
        "captured_at": captured_at.isoformat(),
        "source_sequence": source_sequence,
        "orders": [
            {
                "broker_order_id": intent["broker_order_id"],
                "client_order_id": effective_client_order_id,
                "symbol": "600519",
                "side": "buy",
                "status": status,
                "order_quantity": "100",
                "cumulative_filled_quantity": filled_quantity,
                "cancelled_quantity": cancelled_quantity,
                "average_fill_price": "10.5" if filled_quantity != "0" else None,
                "submitted_at": (captured_at - timedelta(seconds=5)).isoformat(),
                "updated_at": (captured_at - timedelta(seconds=1)).isoformat(),
            }
        ],
        "fills": fills,
    }


def _record_lifecycle(
    db: AppDatabase,
    intent: dict,
    **overrides,
) -> dict:
    captured_at = overrides["captured_at"]
    preview = preview_qmt_order_lifecycle_export(
        json.dumps(_lifecycle_export(intent, **overrides)),
        source_name="qmt local exact-order lifecycle export",
        clock=lambda: captured_at,
    )
    return BrokerOrderLifecycleEvidenceRepository(Path(db._path)).record(
        preview,
        acknowledgement=BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    )


def _run_item(db: AppDatabase, order_id: str, run_date: str) -> tuple[dict, dict]:
    run = ExecutionReconciliationService(db=db).run_reconciliation(run_date=run_date)
    item = next(item for item in run["items"] if item["order_id"] == order_id)
    return item, json.loads(item["payload_json"])


def _import_full_broker_statement(db: AppDatabase, intent: dict) -> None:
    content = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,broker_order_id,client_order_id
qmt-trade-1,trade_buy,2026-07-13T12:00:00+08:00,2026-07-14,600519,贵州茅台,stock,CNY,100,10.5,1050,1.2,0,-1051.22,100000,100,10.5122,exact identity,0.02,{broker_order_id},{client_order_id}
""".format(
        broker_order_id=intent["broker_order_id"],
        client_order_id=intent["client_order_id"],
    )
    preview = parse_broker_statement_csv(content)
    assert preview.validation_status == "pass"
    BrokerEvidenceRepository(Path(db._path)).save_preview(
        preview,
        source_name="independent broker statement",
    )


def test_partial_fill_and_partial_cancel_are_explicit_non_mutating_states(
    tmp_path,
) -> None:
    db, order, intent = _environment(tmp_path)
    _record_lifecycle(
        db,
        intent,
        source_sequence=1,
        status="partially_filled",
        filled_quantity="40",
        cancelled_quantity="0",
        captured_at=NOW,
    )

    partial_item, partial_payload = _run_item(db, order["order_id"], "2026-07-13")

    assert partial_item["item_status"] == (
        "controlled_submission_partial_fill_evidence_available"
    )
    partial_summary = partial_payload["controlled_submission_evidence_summary"]
    assert partial_summary["new_submissions_blocked"] is True
    assert partial_summary["broker_order_lifecycle_evidence"]["order_status"] == (
        "partially_filled"
    )
    assert db.get_oms_order_sync(order["order_id"])["status"] == "submitted"
    assert db.list_fills_sync(order_id=order["order_id"]) == []
    assert db.get_ledger_entries_sync() == []

    _import_full_broker_statement(db, intent)
    still_partial, _ = _run_item(db, order["order_id"], "2026-07-14")
    assert still_partial["item_status"] == (
        "controlled_submission_partial_fill_evidence_available"
    )

    _record_lifecycle(
        db,
        intent,
        source_sequence=2,
        status="cancelled",
        filled_quantity="40",
        cancelled_quantity="60",
        captured_at=NOW + timedelta(seconds=1),
    )
    cancelled_item, cancelled_payload = _run_item(db, order["order_id"], "2026-07-15")

    assert cancelled_item["item_status"] == (
        "controlled_submission_partial_fill_cancel_evidence_available"
    )
    cancelled_summary = cancelled_payload["controlled_submission_evidence_summary"]
    assert cancelled_summary["new_submissions_blocked"] is True
    assert cancelled_summary["does_not_mutate_oms"] is True
    assert cancelled_summary["does_not_mutate_production_ledger"] is True
    assert db.get_oms_order_sync(order["order_id"])["status"] == "submitted"
    assert db.list_fills_sync(order_id=order["order_id"]) == []
    assert db.get_ledger_entries_sync() == []


def test_lifecycle_full_fill_still_requires_independent_statement_and_account_truth(
    tmp_path,
) -> None:
    db, order, intent = _environment(tmp_path)
    _record_lifecycle(
        db,
        intent,
        source_sequence=1,
        status="filled",
        filled_quantity="100",
        cancelled_quantity="0",
        captured_at=NOW,
    )

    lifecycle_only, payload = _run_item(db, order["order_id"], "2026-07-13")

    assert lifecycle_only["item_status"] == (
        "controlled_submission_filled_lifecycle_evidence_available"
    )
    assert lifecycle_only["suggested_action"] == (
        "import_order_linked_broker_statement_and_account_truth"
    )
    assert payload["controlled_submission_evidence_summary"]["new_submissions_blocked"]
    assert db.get_oms_order_sync(order["order_id"])["status"] == "submitted"

    _import_full_broker_statement(db, intent)
    independent_evidence, _ = _run_item(db, order["order_id"], "2026-07-14")

    assert independent_evidence["item_status"] == (
        "controlled_submission_broker_evidence_available"
    )
    assert db.get_oms_order_sync(order["order_id"])["status"] == "submitted"
    assert db.get_ledger_entries_sync() == []


def test_newer_identity_drift_blocks_reconciliation_and_cannot_clear(
    tmp_path,
) -> None:
    db, order, intent = _environment(tmp_path)
    _record_lifecycle(
        db,
        intent,
        source_sequence=1,
        status="partially_filled",
        filled_quantity="40",
        cancelled_quantity="0",
        captured_at=NOW,
    )
    drifted = _record_lifecycle(
        db,
        intent,
        source_sequence=2,
        status="partially_filled",
        filled_quantity="40",
        cancelled_quantity="0",
        captured_at=NOW + timedelta(seconds=1),
        client_order_id="KARK-drifted-client-order",
    )

    item, payload = _run_item(db, order["order_id"], "2026-07-13")

    assert drifted["validation_status"] == "blocked"
    assert item["item_status"] == (
        "controlled_submission_order_lifecycle_evidence_blocked"
    )
    summary = payload["controlled_submission_evidence_summary"]
    assert "qmt_order_lifecycle_order_identity_drift" in (
        summary["broker_order_lifecycle_evidence"]["blockers"]
    )
    assert summary["new_submissions_blocked"] is True
    assert db.get_oms_order_sync(order["order_id"])["status"] == "submitted"
    assert db.list_fills_sync(order_id=order["order_id"]) == []
    assert db.get_ledger_entries_sync() == []


def test_conflicting_partial_lifecycle_invalidates_apparent_full_fill_clearance(
    tmp_path,
) -> None:
    db, order, intent = _environment(tmp_path)
    _record_lifecycle(
        db,
        intent,
        source_sequence=1,
        status="partially_filled",
        filled_quantity="40",
        cancelled_quantity="0",
        captured_at=NOW,
    )
    evidence = BrokerOrderLifecycleEvidenceRepository(
        Path(db._path), ensure_schema=False
    ).resolve_order(
        gateway_id=intent["gateway_id"],
        account_alias="main-cn-account",
        broker_order_id=intent["broker_order_id"],
        client_order_id=intent["client_order_id"],
    )

    blockers = broker_order_lifecycle_clearance_blockers(order, evidence)

    assert blockers == ["controlled_submission_clearance_lifecycle_evidence_mismatch"]
    assert db.get_oms_order_sync(order["order_id"])["status"] == "submitted"
    assert db.get_ledger_entries_sync() == []
