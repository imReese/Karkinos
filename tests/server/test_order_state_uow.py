"""Atomicity, replay, conflict, and race tests for order-state UoWs."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from server.contracts.order_state import (
    ManualOrderStateCommand,
    ManualOrderTicketCommand,
    OmsOrderCommand,
)
from server.db import AppDatabase
from server.services.oms import OmsService

pytestmark = pytest.mark.unit


def _database(tmp_path) -> AppDatabase:
    database = AppDatabase(tmp_path / "order-state.db")
    database.init_sync()
    return database


def _manual_ticket_command(database: AppDatabase) -> ManualOrderTicketCommand:
    database.save_signal_sync(
        timestamp="2026-08-26T09:35:00+08:00",
        strategy_id="fixture-strategy",
        symbol="600519",
        direction="buy",
        target_weight=0.1,
        price=100.0,
        asset_class="stock",
    )
    database.upsert_action_task_sync(
        source_signal_id=1,
        symbol="600519",
        title="fixture action",
        detail="atomic manual-ticket fixture",
        direction="buy",
        urgency="normal",
        target_weight=0.1,
        price=100.0,
        strategy_id="fixture-strategy",
        timestamp="2026-08-26T09:35:00+08:00",
        asset_class="stock",
    )
    action = database.get_action_tasks_sync(limit=1)[0]
    return ManualOrderTicketCommand(
        idempotency_key=f"manual-ticket:action:{action['id']}",
        action_id=int(action["id"]),
        expected_action_status="pending",
        order_id=f"ACTION-{action['id']}-MANUAL",
        timestamp="2026-08-26T09:36:00+08:00",
        symbol="600519",
        side="buy",
        order_type="limit",
        quantity=100,
        price=100.0,
        asset_class="stock",
        intent_id=f"ACTION-{action['id']}",
        risk_decision_id="RISK-FIXTURE",
        source_ref=str(action["id"]),
        payload={
            "action_id": int(action["id"]),
            "manual_confirmation_required": True,
            "broker_submission_enabled": False,
        },
    )


def _confirm_command(command: ManualOrderTicketCommand) -> ManualOrderStateCommand:
    return ManualOrderStateCommand(
        idempotency_key=f"manual-order:{command.order_id}:confirm",
        order_id=command.order_id,
        expected_from="pending_confirm",
        to_status="confirmed",
        note="operator confirmed fixture",
        action_id=command.action_id,
        expected_action_status="pending_manual_confirmation",
        action_to_status="acted",
    )


def _count(database: AppDatabase, table: str) -> int:
    with sqlite3.connect(database.path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_manual_ticket_replay_is_one_atomic_projection(tmp_path) -> None:
    database = _database(tmp_path)
    command = _manual_ticket_command(database)

    first = database.create_manual_order_ticket_sync(command)
    second = database.create_manual_order_ticket_sync(command)

    assert second["order_id"] == first["order_id"]
    assert _count(database, "manual_orders") == 1
    assert _count(database, "orders") == 1
    assert _count(database, "order_state_command_claims") == 1
    assert database.get_action_task_sync(command.action_id)["status"] == (
        "pending_manual_confirmation"
    )


def test_manual_ticket_same_key_different_payload_conflicts(tmp_path) -> None:
    database = _database(tmp_path)
    command = _manual_ticket_command(database)
    database.create_manual_order_ticket_sync(command)

    with pytest.raises(ValueError, match="payload fingerprint changed"):
        database.create_manual_order_ticket_sync(replace(command, quantity=200))

    assert database.get_manual_order_sync(command.order_id)["quantity"] == 100
    assert database.get_order_sync(command.order_id)["quantity"] == 100


def test_manual_ticket_audit_failure_rolls_back_every_projection(tmp_path) -> None:
    database = _database(tmp_path)
    command = _manual_ticket_command(database)
    with sqlite3.connect(database.path) as conn:
        conn.execute("""
            CREATE TRIGGER fail_manual_ticket_audit
            BEFORE INSERT ON event_log
            WHEN NEW.event_type = 'order.submitted'
            BEGIN
                SELECT RAISE(ABORT, 'injected manual ticket audit failure');
            END
            """)
        conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        database.create_manual_order_ticket_sync(command)

    assert _count(database, "manual_orders") == 0
    assert _count(database, "orders") == 0
    assert _count(database, "order_state_command_claims") == 0
    assert database.get_action_task_sync(command.action_id)["status"] == "pending"


def test_manual_transition_replay_and_payload_conflict(tmp_path) -> None:
    database = _database(tmp_path)
    ticket = _manual_ticket_command(database)
    database.create_manual_order_ticket_sync(ticket)
    command = _confirm_command(ticket)

    first = database.transition_manual_order_sync(command)
    second = database.transition_manual_order_sync(command)

    assert first["status"] == second["status"] == "confirmed"
    assert database.get_order_sync(ticket.order_id)["status"] == "confirmed"
    assert database.get_action_task_sync(ticket.action_id)["status"] == "acted"
    with pytest.raises(ValueError, match="payload fingerprint changed"):
        database.transition_manual_order_sync(
            replace(command, note="same key with changed operator note")
        )


def test_manual_transition_audit_failure_rolls_back_cas_and_events(tmp_path) -> None:
    database = _database(tmp_path)
    ticket = _manual_ticket_command(database)
    database.create_manual_order_ticket_sync(ticket)
    event_count = _count(database, "event_log")
    with sqlite3.connect(database.path) as conn:
        conn.execute("""
            CREATE TRIGGER fail_manual_transition_audit
            BEFORE INSERT ON event_log
            WHEN NEW.event_type = 'order.status_changed'
            BEGIN
                SELECT RAISE(ABORT, 'injected manual transition audit failure');
            END
            """)
        conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        database.transition_manual_order_sync(_confirm_command(ticket))

    assert database.get_manual_order_sync(ticket.order_id)["status"] == (
        "pending_confirm"
    )
    assert database.get_order_sync(ticket.order_id)["status"] == "pending_confirm"
    assert database.get_action_task_sync(ticket.action_id)["status"] == (
        "pending_manual_confirmation"
    )
    assert _count(database, "event_log") == event_count
    assert _count(database, "order_state_command_claims") == 1


def test_manual_ticket_concurrent_replay_creates_one_fact_set(tmp_path) -> None:
    database = _database(tmp_path)
    command = _manual_ticket_command(database)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: database.create_manual_order_ticket_sync(command),
                range(2),
            )
        )

    assert {result["order_id"] for result in results} == {command.order_id}
    assert _count(database, "manual_orders") == 1
    assert _count(database, "orders") == 1
    assert _count(database, "order_state_command_claims") == 1


def test_manual_transition_compare_and_set_allows_one_concurrent_disposition(
    tmp_path,
) -> None:
    database = _database(tmp_path)
    ticket = _manual_ticket_command(database)
    database.create_manual_order_ticket_sync(ticket)
    commands = (
        _confirm_command(ticket),
        ManualOrderStateCommand(
            idempotency_key=f"manual-order:{ticket.order_id}:reject",
            order_id=ticket.order_id,
            expected_from="pending_confirm",
            to_status="rejected",
            note="operator rejected fixture",
            action_id=ticket.action_id,
            expected_action_status="pending_manual_confirmation",
            action_to_status="ignored",
        ),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(database.transition_manual_order_sync, command)
            for command in commands
        ]
        outcomes = []
        errors = []
        for future in futures:
            try:
                outcomes.append(future.result()["status"])
            except RuntimeError as exc:
                errors.append(str(exc))

    assert len(outcomes) == 1
    assert len(errors) == 1
    assert "compare-and-set conflict" in errors[0]
    expected_action_status = "acted" if outcomes == ["confirmed"] else "ignored"
    assert database.get_manual_order_sync(ticket.order_id)["status"] == outcomes[0]
    assert database.get_order_sync(ticket.order_id)["status"] == outcomes[0]
    assert database.get_action_task_sync(ticket.action_id)["status"] == (
        expected_action_status
    )
    assert _count(database, "order_state_command_claims") == 2


def test_oms_create_replay_conflict_and_atomic_fault(tmp_path) -> None:
    database = _database(tmp_path)
    service = OmsService(db=database)
    create = {
        "intent_key": "oms-fixture-intent",
        "symbol": "600519",
        "side": "buy",
        "asset_class": "stock",
        "quantity": 100,
        "order_type": "limit",
        "limit_price": 100.0,
        "source": "fixture",
        "source_ref": "fixture:1",
    }

    first = service.create_order_intent(**create)
    second = service.create_order_intent(**create)
    assert first["order_id"] == second["order_id"]
    assert len(service.list_transitions(first["order_id"])) == 1
    with pytest.raises(ValueError, match="payload fingerprint changed"):
        service.create_order_intent(**{**create, "quantity": 200})

    advanced = service.transition_order(
        first["order_id"],
        to_status="manually_confirmed",
        reason="operator confirmed fixture",
        actor="fixture-operator",
        expected_from="awaiting_manual_confirmation",
        idempotency_key="oms-fixture:confirm",
    )
    replay_after_transition = service.create_order_intent(**create)
    assert (
        advanced["status"]
        == replay_after_transition["status"]
        == ("manually_confirmed")
    )

    fault_database = AppDatabase(tmp_path / "oms-fault.db")
    fault_database.init_sync()
    with sqlite3.connect(fault_database.path) as conn:
        conn.execute("""
            CREATE TRIGGER fail_oms_create_audit
            BEFORE INSERT ON event_log
            WHEN NEW.event_type = 'oms.order.created'
            BEGIN
                SELECT RAISE(ABORT, 'injected OMS create audit failure');
            END
            """)
        conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        OmsService(db=fault_database).create_order_intent(**create)
    assert _count(fault_database, "oms_orders") == 0
    assert _count(fault_database, "oms_transitions") == 0
    assert _count(fault_database, "order_state_command_claims") == 0


def test_oms_transition_replay_conflict_cas_and_atomic_fault(tmp_path) -> None:
    database = _database(tmp_path)
    service = OmsService(db=database)
    order = service.create_order_intent(
        intent_key="oms-transition-fixture",
        symbol="600519",
        side="buy",
        asset_class="stock",
        quantity=100,
        order_type="limit",
        limit_price=100.0,
        source="fixture",
    )
    command = {
        "to_status": "manually_confirmed",
        "reason": "operator confirmed fixture",
        "actor": "operator",
        "expected_from": "awaiting_manual_confirmation",
        "idempotency_key": "oms-transition:fixture:confirm",
    }
    first = service.transition_order(order["order_id"], **command)
    second = service.transition_order(order["order_id"], **command)
    assert first["status"] == second["status"] == "manually_confirmed"
    assert len(service.list_transitions(order["order_id"])) == 2
    with pytest.raises(ValueError, match="payload fingerprint changed"):
        service.transition_order(
            order["order_id"],
            **{**command, "reason": "same key with changed reason"},
        )

    race_database = AppDatabase(tmp_path / "oms-race.db")
    race_database.init_sync()
    race_service = OmsService(db=race_database)
    race_order = race_service.create_order_intent(
        intent_key="oms-race-fixture",
        symbol="600519",
        side="buy",
        asset_class="stock",
        quantity=100,
        order_type="limit",
        limit_price=100.0,
        source="fixture",
    )

    def transition(to_status: str) -> str:
        return race_service.transition_order(
            race_order["order_id"],
            to_status=to_status,
            reason=f"race to {to_status}",
            actor="fixture-operator",
            expected_from="awaiting_manual_confirmation",
            idempotency_key=f"oms-race:{to_status}",
        )["status"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(transition, status)
            for status in ("cancelled", "manually_confirmed")
        ]
        outcomes = []
        errors = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except RuntimeError as exc:
                errors.append(str(exc))
    assert len(outcomes) == 1
    assert len(errors) == 1
    assert "compare-and-set conflict" in errors[0]
    assert len(race_service.list_transitions(race_order["order_id"])) == 2

    fault_database = AppDatabase(tmp_path / "oms-transition-fault.db")
    fault_database.init_sync()
    fault_service = OmsService(db=fault_database)
    fault_order = fault_service.create_order_intent(
        intent_key="oms-transition-fault",
        symbol="600519",
        side="buy",
        asset_class="stock",
        quantity=100,
        order_type="limit",
        limit_price=100.0,
        source="fixture",
    )
    before_transitions = len(fault_service.list_transitions(fault_order["order_id"]))
    with sqlite3.connect(fault_database.path) as conn:
        conn.execute("""
            CREATE TRIGGER fail_oms_transition_audit
            BEFORE INSERT ON event_log
            WHEN NEW.event_type = 'oms.order.transitioned'
            BEGIN
                SELECT RAISE(ABORT, 'injected OMS transition audit failure');
            END
            """)
        conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        fault_service.transition_order(
            fault_order["order_id"],
            to_status="manually_confirmed",
            reason="operator confirmed fixture",
            actor="fixture-operator",
            expected_from="awaiting_manual_confirmation",
            idempotency_key="oms-transition:fault:confirm",
        )
    assert fault_database.get_oms_order_sync(fault_order["order_id"])["status"] == (
        "awaiting_manual_confirmation"
    )
    assert len(fault_service.list_transitions(fault_order["order_id"])) == (
        before_transitions
    )
    assert _count(fault_database, "order_state_command_claims") == 1


def test_oms_order_id_collision_cannot_overwrite_existing_order(tmp_path) -> None:
    database = _database(tmp_path)
    order = OmsService(db=database).create_order_intent(
        intent_key="oms-no-overwrite",
        symbol="600519",
        side="buy",
        asset_class="stock",
        quantity=100,
        order_type="limit",
        limit_price=100.0,
        source="fixture",
    )

    with pytest.raises(ValueError, match="order_id already exists"):
        database.create_oms_order_sync(
            OmsOrderCommand(
                idempotency_key="different-key-same-order-id",
                order_id=order["order_id"],
                symbol="600519",
                side="buy",
                asset_class="stock",
                quantity=200,
                order_type="limit",
                limit_price=100.0,
                initial_status="awaiting_manual_confirmation",
                broker_submission_enabled=False,
                source="fixture",
                source_ref=None,
            )
        )

    assert database.get_oms_order_sync(order["order_id"])["quantity"] == 100
