from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from account_truth.broker_order_lifecycle import (
    BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleEvidenceRepository,
    preview_broker_order_lifecycle_export,
)
from server.db import AppDatabase
from server.services.manual_broker_cancellation_evidence import (
    MANUAL_BROKER_CANCELLATION_ACKNOWLEDGEMENT,
    ManualBrokerCancellationEvidenceRejected,
    ManualBrokerCancellationEvidenceService,
)
from server.services.oms import OmsService
from server.services.per_order_confirmation import build_order_fingerprint

NOW = datetime(2026, 7, 16, 3, 0, tzinfo=timezone.utc)


def _environment(tmp_path: Path) -> dict:
    db = AppDatabase(tmp_path / "manual-cancel.db")
    db.init_sync()
    oms = OmsService(db=db)
    order = oms.create_order_intent(
        intent_key="manual-cancel-order-1",
        symbol="600519",
        side="buy",
        asset_class="stock",
        quantity=100,
        order_type="limit",
        limit_price=10,
        source="manual_cancel_test",
        source_ref="decision-1",
    )
    order = oms.transition_order(
        order["order_id"],
        to_status="manually_confirmed",
        reason="operator confirmed exact order",
        actor="fixture-owner",
    )
    submit_intent_id = hashlib.sha256(b"manual-cancel-submit-intent").hexdigest()
    submit_fingerprint = hashlib.sha256(b"manual-cancel-submit").hexdigest()
    prepared = db.prepare_controlled_broker_submit_intent_sync(
        intent={
            "submit_intent_id": submit_intent_id,
            "submit_fingerprint": submit_fingerprint,
            "order_id": order["order_id"],
            "order_fingerprint": build_order_fingerprint(order),
            "confirmation_id": "c" * 64,
            "dossier_fingerprint": "d" * 64,
            "gateway_id": "fixture-controlled-gateway-1",
            "gateway_verification_fingerprint": "e" * 64,
            "release_evidence_id": "f" * 64,
            "release_evidence_fingerprint": "a" * 64,
            "client_order_id": "KARK-manual-cancel-client-1",
            "operator_id": "fixture-owner",
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
        broker_order_id="BROKER-MANUAL-CANCEL-1",
        broker_status="accepted",
        result={
            "status": "accepted",
            "submitted": True,
            "definitive": True,
            "client_order_id": "KARK-manual-cancel-client-1",
            "order_fingerprint": build_order_fingerprint(order),
            "broker_order_id": "BROKER-MANUAL-CANCEL-1",
        },
        actor="controlled-broker-submission",
        finalized_at_epoch_ms=int(NOW.timestamp() * 1000) + 1,
        finalized_at=(NOW + timedelta(milliseconds=1)).isoformat(),
    )
    assert finalized["status"] == "submitted"
    return {
        "db": db,
        "order_id": order["order_id"],
        "submit_intent_id": submit_intent_id,
    }


def _record_lifecycle(
    env: dict,
    *,
    status: str = "partially_filled",
    filled: int = 40,
    cancelled: int = 0,
    source_sequence: int = 1,
    captured_at: datetime = NOW,
) -> dict:
    fills = []
    if filled:
        fills.append(
            {
                "broker_trade_id": f"FIXTURE-MANUAL-CANCEL-{source_sequence}",
                "broker_order_id": "BROKER-MANUAL-CANCEL-1",
                "client_order_id": "KARK-manual-cancel-client-1",
                "symbol": "600519",
                "side": "buy",
                "quantity": str(filled),
                "price": "10",
                "fee": "1",
                "tax": "0",
                "transfer_fee": "0",
                "net_amount": str(-(filled * 10 + 1)),
                "filled_at": (captured_at - timedelta(seconds=2)).isoformat(),
            }
        )
    payload = {
        "schema_version": "karkinos.broker_order_lifecycle_export.v1",
        "provider": "fixture_broker",
        "snapshot_kind": "exact_order_lifecycle",
        "gateway_id": "fixture-controlled-gateway-1",
        "account_id": "private-fixture-account-001",
        "account_alias": "main-cn-account",
        "captured_at": captured_at.isoformat(),
        "source_sequence": source_sequence,
        "orders": [
            {
                "broker_order_id": "BROKER-MANUAL-CANCEL-1",
                "client_order_id": "KARK-manual-cancel-client-1",
                "symbol": "600519",
                "side": "buy",
                "status": status,
                "order_quantity": "100",
                "cumulative_filled_quantity": str(filled),
                "cancelled_quantity": str(cancelled),
                "average_fill_price": "10" if filled else None,
                "submitted_at": (captured_at - timedelta(seconds=5)).isoformat(),
                "updated_at": (captured_at - timedelta(seconds=1)).isoformat(),
            }
        ],
        "fills": fills,
    }
    preview = preview_broker_order_lifecycle_export(
        json.dumps(payload),
        source_name="deterministic manual cancellation fixture",
        clock=lambda: captured_at,
    )
    assert preview["ready_to_record"] is True, preview["blockers"]
    return BrokerOrderLifecycleEvidenceRepository(Path(env["db"]._path)).record(
        preview,
        acknowledgement=BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    )


def _protected_counts(db: AppDatabase) -> dict[str, int]:
    tables = (
        "oms_orders",
        "oms_transitions",
        "fills",
        "ledger_entries",
        "risk_decisions",
        "runtime_controls",
        "event_log",
        "broker_gateway_events",
    )
    with sqlite3.connect(db._path) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }


def test_preview_and_export_bind_exact_partial_fill_without_mutation(tmp_path) -> None:
    env = _environment(tmp_path)
    lifecycle = _record_lifecycle(env)
    service = ManualBrokerCancellationEvidenceService(
        db=env["db"],
        clock=lambda: NOW,
    )
    before = _protected_counts(env["db"])

    preview = service.preview(submit_intent_id=env["submit_intent_id"])

    assert preview["status"] == "ready_for_manual_broker_action"
    assert preview["ready"] is True
    assert preview["provider"] == "fixture_broker"
    assert preview["identity"] == {
        "gateway_id": "fixture-controlled-gateway-1",
        "account_alias": "main-cn-account",
        "broker_order_id": "BROKER-MANUAL-CANCEL-1",
        "client_order_id": "KARK-manual-cancel-client-1",
    }
    assert preview["order"]["lifecycle_status"] == "partially_filled"
    assert preview["order"]["filled_quantity"] == "40"
    assert preview["order"]["remaining_quantity"] == "60"
    assert preview["lifecycle_evidence"]["observation_id"] == (
        lifecycle["observation_id"]
    )
    assert preview["safety"]["provider_contact_performed"] is False
    assert preview["safety"]["broker_cancel_performed"] is False
    assert preview["safety"]["oms_mutated"] is False

    exported = service.export(
        submit_intent_id=env["submit_intent_id"],
        ticket_fingerprint=preview["ticket_fingerprint"],
        acknowledgement=MANUAL_BROKER_CANCELLATION_ACKNOWLEDGEMENT,
    )
    duplicate = service.export(
        submit_intent_id=env["submit_intent_id"],
        ticket_fingerprint=preview["ticket_fingerprint"],
        acknowledgement=MANUAL_BROKER_CANCELLATION_ACKNOWLEDGEMENT,
    )

    assert exported["status"] == "export_ready"
    assert exported["export_fingerprint"] == duplicate["export_fingerprint"]
    assert exported["content"] == duplicate["content"]
    assert exported["artifact"]["broker_cancel_performed"] is False
    assert exported["artifact"]["cancellation_proven"] is False
    assert _protected_counts(env["db"]) == before


def test_restart_preserves_ticket_fingerprint_and_export_is_copy_safe(tmp_path) -> None:
    env = _environment(tmp_path)
    _record_lifecycle(env)
    first = ManualBrokerCancellationEvidenceService(
        db=env["db"], clock=lambda: NOW
    ).preview(submit_intent_id=env["submit_intent_id"])
    restarted_db = AppDatabase(env["db"]._path)
    restarted_db.init_sync()
    restarted = ManualBrokerCancellationEvidenceService(
        db=restarted_db,
        clock=lambda: NOW + timedelta(minutes=1),
    ).preview(submit_intent_id=env["submit_intent_id"])

    assert restarted["ticket_fingerprint"] == first["ticket_fingerprint"]
    assert restarted["generated_at"] != first["generated_at"]
    first_export = ManualBrokerCancellationEvidenceService(
        db=env["db"], clock=lambda: NOW
    ).export(
        submit_intent_id=env["submit_intent_id"],
        ticket_fingerprint=first["ticket_fingerprint"],
        acknowledgement=MANUAL_BROKER_CANCELLATION_ACKNOWLEDGEMENT,
    )
    restarted_export = ManualBrokerCancellationEvidenceService(
        db=restarted_db, clock=lambda: NOW + timedelta(minutes=1)
    ).export(
        submit_intent_id=env["submit_intent_id"],
        ticket_fingerprint=restarted["ticket_fingerprint"],
        acknowledgement=MANUAL_BROKER_CANCELLATION_ACKNOWLEDGEMENT,
    )
    assert restarted_export["content"] == first_export["content"]


def test_newer_lifecycle_evidence_invalidates_reviewed_ticket(tmp_path) -> None:
    env = _environment(tmp_path)
    _record_lifecycle(env, filled=40, source_sequence=1)
    service = ManualBrokerCancellationEvidenceService(db=env["db"], clock=lambda: NOW)
    preview = service.preview(submit_intent_id=env["submit_intent_id"])
    _record_lifecycle(
        env,
        filled=50,
        source_sequence=2,
        captured_at=NOW + timedelta(seconds=10),
    )

    with pytest.raises(ManualBrokerCancellationEvidenceRejected) as exc_info:
        service.export(
            submit_intent_id=env["submit_intent_id"],
            ticket_fingerprint=preview["ticket_fingerprint"],
            acknowledgement=MANUAL_BROKER_CANCELLATION_ACKNOWLEDGEMENT,
        )

    assert "manual_broker_cancel_ticket_fingerprint_mismatch" in (
        exc_info.value.evidence["blockers"]
    )
    assert exc_info.value.evidence["export_performed"] is False


@pytest.mark.parametrize(
    ("status", "filled", "cancelled"),
    (("filled", 100, 0), ("cancelled", 40, 60), ("rejected", 0, 0)),
)
def test_terminal_lifecycle_cannot_prepare_manual_cancel_ticket(
    tmp_path,
    status: str,
    filled: int,
    cancelled: int,
) -> None:
    env = _environment(tmp_path)
    _record_lifecycle(
        env,
        status=status,
        filled=filled,
        cancelled=cancelled,
    )

    preview = ManualBrokerCancellationEvidenceService(
        db=env["db"], clock=lambda: NOW
    ).preview(submit_intent_id=env["submit_intent_id"])

    assert preview["ready"] is False
    assert "manual_broker_cancel_lifecycle_not_cancellable" in preview["blockers"]
    assert preview["safety"]["authorizes_cancellation"] is False


def test_export_requires_exact_acknowledgement(tmp_path) -> None:
    env = _environment(tmp_path)
    _record_lifecycle(env)
    service = ManualBrokerCancellationEvidenceService(db=env["db"], clock=lambda: NOW)
    preview = service.preview(submit_intent_id=env["submit_intent_id"])

    with pytest.raises(ManualBrokerCancellationEvidenceRejected) as exc_info:
        service.export(
            submit_intent_id=env["submit_intent_id"],
            ticket_fingerprint=preview["ticket_fingerprint"],
            acknowledgement="cancel_it",
        )

    assert exc_info.value.evidence["blockers"] == [
        "manual_broker_cancel_acknowledgement_mismatch"
    ]
