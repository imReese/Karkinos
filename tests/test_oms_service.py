from __future__ import annotations

import json

from server.db import AppDatabase
from server.services.oms import OmsService


def _service(tmp_path) -> OmsService:
    db = AppDatabase(tmp_path / "oms.db")
    db.init_sync()
    return OmsService(db=db)


def test_oms_creates_idempotent_manual_confirmation_order(tmp_path) -> None:
    service = _service(tmp_path)

    first = service.create_order_intent(
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
    second = service.create_order_intent(
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

    assert first["order_id"] == second["order_id"]
    assert first["status"] == "awaiting_manual_confirmation"
    assert first["broker_submission_enabled"] is False


def test_oms_records_allowed_manual_confirmation_transition(tmp_path) -> None:
    service = _service(tmp_path)
    order = service.create_order_intent(
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

    updated = service.transition_order(
        order["order_id"],
        to_status="manually_confirmed",
        reason="operator approved paper/shadow evidence",
        actor="test",
    )

    assert updated["status"] == "manually_confirmed"
    transitions = service.list_transitions(order["order_id"])
    assert transitions[-1]["from_status"] == "awaiting_manual_confirmation"
    assert transitions[-1]["to_status"] == "manually_confirmed"


def test_oms_rejects_submit_while_broker_submission_is_disabled(tmp_path) -> None:
    service = _service(tmp_path)
    order = service.create_order_intent(
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

    try:
        service.transition_order(
            order["order_id"],
            to_status="submitted",
            reason="should not be possible",
            actor="test",
        )
    except ValueError as exc:
        assert "broker submission is disabled" in str(exc)
    else:
        raise AssertionError("expected submitted transition to be rejected")


def test_oms_creates_idempotent_paper_shadow_order_lifecycle(tmp_path) -> None:
    service = _service(tmp_path)

    first = service.create_paper_shadow_order(
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
        evidence_refs=["strategy:dual_ma", "risk:risk-001"],
    )
    second = service.create_paper_shadow_order(
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
        evidence_refs=["strategy:dual_ma", "risk:risk-001"],
    )

    assert second["order_id"] == first["order_id"]
    assert first["status"] == "staged"
    assert first["broker_submission_enabled"] is False
    payload = json.loads(first["payload_json"])
    assert payload["execution_mode"] == "paper_shadow"
    assert payload["run_id"] == "shadow:2026-07-02:abc"
    assert payload["source_ref"] == "action:ACTION-1"
    assert payload["does_not_submit_broker_order"] is True
    assert payload["does_not_mutate_production_ledger"] is True


def test_oms_allows_paper_shadow_simulated_transitions_and_reconciliation(
    tmp_path,
) -> None:
    service = _service(tmp_path)
    order = service.create_paper_shadow_order(
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
        evidence_refs=["strategy:dual_ma", "risk:risk-001"],
    )

    for status, evidence in [
        ("submitted", {}),
        ("accepted", {}),
        ("partially_filled", {"filled_quantity": "40"}),
        ("filled", {"filled_quantity": "100"}),
        ("reconciled", {"reconciliation_ref": "paper-shadow-review:1"}),
    ]:
        order = service.transition_order(
            order["order_id"],
            to_status=status,
            reason=f"paper shadow {status}",
            actor="paper-shadow",
            source="paper_shadow_run",
            evidence=evidence,
        )

    assert order["status"] == "reconciled"
    transitions = service.list_transitions(order["order_id"])
    assert [item["to_status"] for item in transitions] == [
        "staged",
        "submitted",
        "accepted",
        "partially_filled",
        "filled",
        "reconciled",
    ]
    transition_payload = json.loads(transitions[-1]["payload_json"])
    assert transition_payload["execution_mode"] == "paper_shadow"
    assert transition_payload["source"] == "paper_shadow_run"
    assert transition_payload["does_not_submit_broker_order"] is True
    assert transition_payload["reconciliation_ref"] == "paper-shadow-review:1"


def test_oms_rejects_invalid_paper_shadow_state_move(tmp_path) -> None:
    service = _service(tmp_path)
    order = service.create_paper_shadow_order(
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

    try:
        service.transition_order(
            order["order_id"],
            to_status="filled",
            reason="cannot fill before simulated submission",
            actor="test",
            source="paper_shadow_run",
        )
    except ValueError as exc:
        assert "invalid OMS transition" in str(exc)
    else:
        raise AssertionError("expected invalid paper shadow transition")
