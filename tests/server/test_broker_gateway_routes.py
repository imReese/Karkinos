from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from server.config import BrokerConnectorConfig
from server.db import AppDatabase
from server.routes.broker_gateway import create_router
from server.services.oms import OmsService
from server.services.trading_controls import TradingControlState


class _ConnectorWouldFailIfQueried:
    connector_id = "fixture-readonly-edge"
    connector_type = "deterministic_fixture"
    enabled = True

    def read_account_snapshot(self):
        raise AssertionError("GET routes must not call an edge adapter")


def _client_for_db(
    monkeypatch,
    db: AppDatabase,
    *,
    broker_connectors: list[BrokerConnectorConfig] | None = None,
    controlled_bridge_policy=None,
    trading_controls=None,
) -> TestClient:
    fake_state = SimpleNamespace(
        db=db,
        config=SimpleNamespace(
            broker_connectors=broker_connectors or [],
            controlled_bridge_policy=controlled_bridge_policy,
        ),
        trading_controls=trading_controls,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


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


def _controlled_bridge_policy() -> SimpleNamespace:
    return SimpleNamespace(
        policy_id="local-controlled-bridge-review",
        enabled=True,
        allowed_connector_ids=["local-fixture-readonly"],
        allowed_account_aliases=["local-review"],
        allowed_strategy_ids=["dual_ma"],
        allowed_symbols=["600519"],
        per_order_confirmation_required=True,
        automation_allowed=False,
    )


def _confirmed_order(
    db: AppDatabase,
    *,
    gateway_evidence: bool = True,
    order_intent_payload: dict | None = None,
) -> dict:
    oms = OmsService(db=db)
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
        payload: dict = {
            "schema_version": "karkinos.oms_order.v1",
            "manual_confirmation_required": True,
            "does_not_submit_broker_order": True,
            "gateway_evidence": _required_gateway_evidence(),
        }
        if order_intent_payload is not None:
            payload["order_intent"] = order_intent_payload
        order = db.upsert_oms_order_sync(
            {
                **order,
                "payload": payload,
            }
        )
    return oms.transition_order(
        order["order_id"],
        to_status="manually_confirmed",
        reason="operator approved paper/shadow evidence",
        actor="test",
    )


def test_broker_gateway_status_route_lists_safe_gateways(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    response = client.get("/api/broker-gateway/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["broker_submission_enabled"] is False
    gateway_ids = {item["gateway_id"] for item in payload["gateways"]}
    assert {"manual_ticket", "staged_broker_evidence", "live_disabled"}.issubset(
        gateway_ids
    )
    manual_ticket = next(
        item for item in payload["gateways"] if item["gateway_id"] == "manual_ticket"
    )
    staged_evidence = next(
        item
        for item in payload["gateways"]
        if item["gateway_id"] == "staged_broker_evidence"
    )
    assert manual_ticket["can_preview_orders"] is True
    assert manual_ticket["can_export_tickets"] is True
    assert manual_ticket["can_dry_run_orders"] is True
    assert manual_ticket["can_query_orders"] is True
    assert manual_ticket["can_query_fills"] is True
    assert manual_ticket["can_submit_orders"] is False
    assert staged_evidence["can_read_account_facts"] is True
    assert staged_evidence["can_query_cash"] is True
    assert staged_evidence["can_query_positions"] is True
    assert staged_evidence["can_submit_orders"] is False
    assert staged_evidence["can_export_tickets"] is False


def test_broker_gateway_status_route_exposes_controlled_bridge_policy(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    client = _client_for_db(
        monkeypatch,
        db,
        controlled_bridge_policy=SimpleNamespace(
            policy_id="local-controlled-bridge-review",
            enabled=True,
            allowed_connector_ids=["local-fixture-readonly"],
            allowed_account_aliases=["local-review"],
            allowed_strategy_ids=["dual_ma"],
            allowed_symbols=["600519"],
            per_order_confirmation_required=True,
            automation_allowed=False,
        ),
    )

    response = client.get("/api/broker-gateway/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["broker_submission_enabled"] is False
    policy = payload["controlled_bridge_policy"]
    assert policy["policy_id"] == "local-controlled-bridge-review"
    assert policy["status"] == "configured_non_submitting"
    assert policy["broker_submission_enabled"] is False
    assert policy["live_submission_available"] is False
    assert policy["automation_allowed"] is False
    assert policy["allowed_connector_ids"] == ["local-fixture-readonly"]
    assert policy["allowed_account_aliases"] == ["local-review"]
    assert policy["allowed_strategy_ids"] == ["dual_ma"]
    assert policy["allowed_symbols"] == ["600519"]
    assert policy["blockers"] == ["live_gateway_not_implemented"]


def test_broker_gateway_status_route_marks_manual_ticket_blocked_by_kill_switch(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    controls = TradingControlState(db=db)
    controls.set_kill_switch(True, "operator pause")
    client = _client_for_db(monkeypatch, db, trading_controls=controls)

    response = client.get("/api/broker-gateway/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["broker_submission_enabled"] is False
    assert payload["kill_switch_enabled"] is True
    assert payload["kill_switch_reason"] == "operator pause"
    gateways = {item["gateway_id"]: item for item in payload["gateways"]}
    manual_ticket = gateways["manual_ticket"]
    assert manual_ticket["status"] == "blocked_by_kill_switch"
    assert manual_ticket["can_preview_orders"] is False
    assert manual_ticket["can_export_tickets"] is False
    assert manual_ticket["can_dry_run_orders"] is False
    assert manual_ticket["can_submit_orders"] is False
    assert manual_ticket["blockers"] == ["kill_switch"]
    assert gateways["live_disabled"]["status"] == "disabled"


def test_broker_gateway_connector_health_route_is_read_only(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    client = _client_for_db(
        monkeypatch,
        db,
        broker_connectors=[
            BrokerConnectorConfig(
                connector_id="fixture-readonly-edge",
                connector_type="deterministic_fixture",
                enabled=True,
                client_path="/opt/fixture-edge",
                account_alias="fixture-review",
            )
        ],
    )

    response = client.get("/api/broker-gateway/connectors/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "karkinos.broker_connector_health_list.v2"
    assert payload["broker_submission_enabled"] is False
    assert payload["provider_contact_performed"] is False
    assert payload["reads_persisted_facts_only"] is True
    assert payload["connectors"][0]["connector_id"] == "fixture-readonly-edge"
    assert payload["connectors"][0]["status"] == "collector_evidence_missing"
    assert (
        payload["connectors"][0]["capability_scope"]
        == "persisted_broker_order_lifecycle_evidence"
    )
    assert payload["connectors"][0]["capabilities"]["can_read_account"] is False
    assert payload["connectors"][0]["capabilities"]["can_preview_orders"] is False
    assert payload["connectors"][0]["capabilities"]["can_export_tickets"] is False
    assert payload["connectors"][0]["capabilities"]["can_dry_run_orders"] is False
    assert payload["connectors"][0]["capabilities"]["can_submit_orders"] is False
    assert payload["connectors"][0]["capabilities"]["can_cancel_orders"] is False
    assert payload["connectors"][0]["stores_credentials"] is False
    assert "client_path" not in payload["connectors"][0]
    assert "qmt" not in response.text.lower()


def test_broker_gateway_connector_snapshot_route_is_migration_only(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    connector = _ConnectorWouldFailIfQueried()
    client = _client_for_db(monkeypatch, db, broker_connectors=[connector])

    response = client.get(
        "/api/broker-gateway/connectors/fixture-readonly-edge/snapshot"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == ("karkinos.broker_connector_snapshot_query.v2")
    assert payload["broker_submission_enabled"] is False
    assert payload["provider_contact_performed"] is False
    assert payload["deprecated_compatibility_entry"] is True
    snapshot = payload["snapshot"]
    assert snapshot["query_scope"] == "snapshot_compatibility_entry"
    assert snapshot["connector_id"] == "fixture-readonly-edge"
    assert snapshot["account_facts_included"] is False
    assert snapshot["provider_contact_performed"] is False
    assert snapshot["lifecycle_evidence"]["status"] == ("explicit_ingestion_required")
    assert snapshot["can_submit_orders"] is False
    assert snapshot["can_cancel_orders"] is False
    assert snapshot["does_not_mutate_production_ledger"] is True
    assert snapshot["migration"]["legacy_runtime_snapshot_supported"] is False
    assert "qmt" not in response.text.lower()
    assert db.list_broker_gateway_events_sync() == []


def test_local_export_registration_is_not_read_by_get_routes(
    tmp_path,
    monkeypatch,
) -> None:
    snapshot_path = tmp_path / "edge-snapshot.json"
    snapshot_path.write_text("private-account-id:not-valid-json", encoding="utf-8")
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    client = _client_for_db(
        monkeypatch,
        db,
        broker_connectors=[
            BrokerConnectorConfig(
                connector_id="fixture-local-export",
                connector_type="local_export_readonly",
                enabled=True,
                client_path=str(snapshot_path),
                account_alias="fixture-review",
            )
        ],
    )

    health_response = client.get("/api/broker-gateway/connectors/health")
    snapshot_response = client.get(
        "/api/broker-gateway/connectors/fixture-local-export/snapshot"
    )

    assert health_response.status_code == 200
    health = health_response.json()["connectors"][0]
    assert health["connector_id"] == "fixture-local-export"
    assert health["status"] == "collector_evidence_missing"
    assert health["capability_scope"] == ("persisted_broker_order_lifecycle_evidence")
    assert health["provider_contact_performed"] is False
    assert health["capabilities"]["can_submit_orders"] is False
    assert "private-account-id" not in health_response.text
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()["snapshot"]
    assert snapshot["connector_id"] == "fixture-local-export"
    assert snapshot["status"] == "migrated_to_persisted_lifecycle_evidence"
    assert snapshot["provider_contact_performed"] is False
    assert snapshot["lifecycle_evidence"]["status"] == ("explicit_ingestion_required")
    assert snapshot["does_not_mutate_oms"] is True
    assert snapshot["does_not_mutate_production_ledger"] is True
    assert "private-account-id" not in snapshot_response.text
    assert "qmt" not in snapshot_response.text.lower()
    assert db.list_broker_gateway_events_sync() == []


def test_missing_local_export_is_not_read_by_get_routes(
    tmp_path,
    monkeypatch,
) -> None:
    snapshot_path = tmp_path / "missing-edge-snapshot.json"
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    client = _client_for_db(
        monkeypatch,
        db,
        broker_connectors=[
            BrokerConnectorConfig(
                connector_id="fixture-local-export",
                connector_type="local_export_readonly",
                enabled=True,
                client_path=str(snapshot_path),
                account_alias="fixture-review",
            )
        ],
    )

    health_response = client.get("/api/broker-gateway/connectors/health")
    snapshot_response = client.get(
        "/api/broker-gateway/connectors/fixture-local-export/snapshot"
    )

    assert health_response.status_code == 200
    health = health_response.json()["connectors"][0]
    assert health["connector_id"] == "fixture-local-export"
    assert health["status"] == "collector_evidence_missing"
    assert health["provider_contact_performed"] is False
    assert health["capabilities"]["can_submit_orders"] is False
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()["snapshot"]
    assert snapshot["status"] == "migrated_to_persisted_lifecycle_evidence"
    assert snapshot["provider_contact_performed"] is False
    assert snapshot["lifecycle_evidence"]["status"] == ("explicit_ingestion_required")
    assert snapshot["does_not_mutate_oms"] is True
    assert snapshot["does_not_mutate_production_ledger"] is True
    assert db.list_broker_gateway_events_sync() == []


def test_unregistered_third_party_export_type_never_reads_file(
    tmp_path,
    monkeypatch,
) -> None:
    snapshot_path = tmp_path / "third-party-snapshot-wrong-schema.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "schema_version": "other.app.account_snapshot.v1",
                "source_name": "Third-party local readonly export",
                "account_id": "private-account-id",
                "captured_at": "2026-07-03T15:01:00+08:00",
                "health": {
                    "status": "healthy",
                    "checked_at": "2026-07-03T15:00:00+08:00",
                    "message": "Wrong local export parsed.",
                },
                "cash": {
                    "currency": "CNY",
                    "balance": "100000.00",
                    "available": "88000.00",
                },
            }
        ),
        encoding="utf-8",
    )
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    client = _client_for_db(
        monkeypatch,
        db,
        broker_connectors=[
            BrokerConnectorConfig(
                connector_id="fixture-third-party-export",
                connector_type="third_party_readonly_export",
                enabled=True,
                client_path=str(snapshot_path),
                account_alias="fixture-review",
            )
        ],
    )

    health_response = client.get("/api/broker-gateway/connectors/health")
    snapshot_response = client.get(
        "/api/broker-gateway/connectors/fixture-third-party-export/snapshot"
    )

    assert health_response.status_code == 200
    health = health_response.json()["connectors"][0]
    assert health["status"] == "collector_evidence_missing"
    assert health["provider_contact_performed"] is False
    assert health["explicit_ingestion_required"] is True
    assert health["capabilities"]["can_submit_orders"] is False
    assert "private-account-id" not in health_response.text
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()["snapshot"]
    assert snapshot["status"] == "migrated_to_persisted_lifecycle_evidence"
    assert snapshot["provider_contact_performed"] is False
    assert snapshot["lifecycle_evidence"]["status"] == ("explicit_ingestion_required")
    assert "private-account-id" not in snapshot_response.text
    assert "qmt" not in snapshot_response.text.lower()
    assert db.list_broker_gateway_events_sync() == []


def test_manual_ticket_route_returns_copyable_ticket(tmp_path, monkeypatch) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    order = _confirmed_order(
        db,
        order_intent_payload={
            "estimated_net_cash_impact": -168805.1,
            "position_effect": {
                "estimated_quantity_after": 200.0,
                "estimated_avg_cost_after": 1644.0,
                "cost_basis_method": "weighted_average_preview",
            },
        },
    )
    client = _client_for_db(monkeypatch, db)

    response = client.post(
        f"/api/broker-gateway/orders/{order['order_id']}/manual-ticket",
        json={"actor": "test"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["submitted_to_broker"] is False
    assert payload["ticket"]["symbol"] == "600519"
    assert payload["ticket"]["copy_text"].startswith("BUY 600519 100")
    gate_summary = payload["validation"]["required_gate_summary"]
    assert gate_summary["status"] == "pass"
    assert gate_summary["gates"]["manual_confirmation"] == {
        "status": "pass",
        "evidence_ref": f"oms_order:{order['order_id']}:manual_ticket_created",
        "source": "oms_status",
    }
    assert gate_summary["gates"]["account_truth"]["evidence_ref"] == ("account-truth:1")
    assert gate_summary["does_not_authorize_execution"] is True


def test_manual_ticket_preview_route_is_read_only(tmp_path, monkeypatch) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    order = _confirmed_order(
        db,
        order_intent_payload={
            "estimated_net_cash_impact": -168805.1,
            "position_effect": {
                "estimated_quantity_after": 200.0,
                "estimated_avg_cost_after": 1644.0,
                "cost_basis_method": "weighted_average_preview",
            },
        },
    )
    client = _client_for_db(monkeypatch, db)

    response = client.post(
        f"/api/broker-gateway/orders/{order['order_id']}/manual-ticket/preview",
        json={"actor": "test"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "preview_ready"
    assert payload["dry_run"] is True
    assert payload["submitted_to_broker"] is False
    gate_summary = payload["validation"]["required_gate_summary"]
    assert gate_summary["status"] == "pass"
    assert gate_summary["submitted_to_broker"] is False
    assert gate_summary["does_not_authorize_execution"] is True
    assert gate_summary["gates"]["account_truth"]["evidence_ref"] == "account-truth:1"
    assert gate_summary["gates"]["research_evidence"]["evidence_ref"] == "research:1"
    assert gate_summary["gates"]["risk"]["evidence_ref"] == "risk:risk-001"
    assert gate_summary["gates"]["paper_shadow"]["evidence_ref"] == (
        "paper_shadow:run-001"
    )
    assert gate_summary["gates"]["manual_confirmation"]["status"] == "pass"
    assert payload["ticket"]["copy_text"].startswith("BUY 600519 100")
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    assert db.list_broker_gateway_events_sync(order_id=order["order_id"]) == []


def test_manual_ticket_export_route_is_read_only(tmp_path, monkeypatch) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    order = _confirmed_order(
        db,
        order_intent_payload={
            "estimated_gross_amount": 168800.0,
            "estimated_total_fee": 5.1,
            "estimated_net_cash_impact": -168805.1,
            "available_cash_before": 200000.0,
            "available_cash_after": 31194.9,
            "cash_status": "sufficient",
            "cash_shortfall": 0.0,
            "fee_breakdown": {
                "commission": "5.00",
                "stamp_tax": "0.00",
                "transfer_fee": "0.10",
            },
            "fee_rule_id": "manual_configured_commission",
            "fee_rule_version": "broker_fee_schedule",
            "position_effect": {
                "current_quantity": 100.0,
                "current_avg_cost": 1600.0,
                "current_market_value": 168800.0,
                "estimated_quantity_after": 200.0,
                "estimated_avg_cost_after": 1644.0,
                "cost_basis_method": "weighted_average_preview",
            },
        },
    )
    client = _client_for_db(
        monkeypatch,
        db,
        controlled_bridge_policy=_controlled_bridge_policy(),
    )

    response = client.post(
        f"/api/broker-gateway/orders/{order['order_id']}/manual-ticket/export",
        json={"actor": "test"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "export_ready"
    assert payload["dry_run"] is True
    assert payload["submitted_to_broker"] is False
    assert payload["validation"]["controlled_bridge_policy"]["status"] == (
        "configured_non_submitting"
    )
    assert payload["ticket"]["copy_text"] == "BUY 600519 100 LIMIT 1688"
    assert payload["ticket"]["operator_form"]["account_alias"] == "local-review"
    assert payload["ticket"]["operator_form"]["field_labels"]["symbol"] == "Symbol"
    assert (
        payload["ticket"]["operator_form"]["fee_tax_assumptions"]["estimated_total_fee"]
        == 5.1
    )
    assert (
        payload["ticket"]["operator_form"]["trading_session_constraints"]["timezone"]
        == "Asia/Shanghai"
    )
    assert payload["ticket"]["operator_form"]["safety"]["submitted_to_broker"] is False
    assert (
        payload["ticket"]["operator_form"]["cash_impact_preview"][
            "estimated_net_cash_impact"
        ]
        == -168805.1
    )
    assert (
        payload["ticket"]["operator_form"]["position_cost_preview"][
            "estimated_quantity_after"
        ]
        == 200
    )
    assert payload["export"]["format"] == "json"
    assert payload["export"]["copy_text"] == "BUY 600519 100 LIMIT 1688"
    assert (
        payload["export"]["content"]["operator_form"]["field_labels"]["copy_text"]
        == "Broker copy text"
    )
    assert payload["export"]["content"]["controlled_bridge_policy"]["policy_id"] == (
        "local-controlled-bridge-review"
    )
    assert (
        payload["export"]["content"]["controlled_bridge_policy"][
            "broker_submission_enabled"
        ]
        is False
    )
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    assert db.list_broker_gateway_events_sync(order_id=order["order_id"]) == []


def test_manual_execution_preview_route_is_read_only(tmp_path, monkeypatch) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    order = _confirmed_order(
        db,
        order_intent_payload={
            "position_effect": {
                "current_quantity": 100.0,
                "current_avg_cost": 1600.0,
                "estimated_quantity_after": 200.0,
                "estimated_avg_cost_after": 1644.0,
                "cost_basis_method": "weighted_average_preview",
            },
        },
    )
    client = _client_for_db(
        monkeypatch,
        db,
        controlled_bridge_policy=_controlled_bridge_policy(),
    )
    client.post(
        f"/api/broker-gateway/orders/{order['order_id']}/manual-ticket",
        json={"actor": "test"},
    )
    event_count_before = len(
        db.list_broker_gateway_events_sync(order_id=order["order_id"])
    )

    response = client.post(
        f"/api/broker-gateway/orders/{order['order_id']}/manual-execution/preview",
        json={
            "actor": "test",
            "fill_price": "1688.00",
            "quantity": "100",
            "fee": "5.00",
            "tax": "0.00",
            "transfer_fee": "0.10",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "manual_execution_preview_ready"
    assert payload["dry_run"] is True
    assert payload["submitted_to_broker"] is False
    assert payload["does_not_mutate_production_ledger"] is True
    assert payload["execution_preview"]["gross_amount"] == "168800.00"
    assert payload["execution_preview"]["net_cash_impact"] == "-168805.10"
    assert payload["preview_fingerprint"].startswith("sha256:")
    assert len(payload["preview_fingerprint"]) == len("sha256:") + 64
    assert payload["fingerprint_scope"] == (
        "order_id, execution_preview, ledger_entry_draft, "
        "position_cost_preview, controlled_bridge_policy"
    )
    assert payload["ledger_entry_draft"]["amount"] == "-168805.10"
    assert payload["ledger_entry_draft"]["requires_operator_save"] is True
    assert payload["safety"]["requires_operator_save"] is True
    assert payload["safety"]["does_not_mutate_production_ledger"] is True
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manual_ticket_created"
    assert (
        len(db.list_broker_gateway_events_sync(order_id=order["order_id"]))
        == event_count_before
    )


def test_manual_execution_record_route_records_gateway_evidence_only(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    order = _confirmed_order(
        db,
        order_intent_payload={
            "position_effect": {
                "current_quantity": 100.0,
                "current_avg_cost": 1600.0,
                "estimated_quantity_after": 200.0,
                "estimated_avg_cost_after": 1644.0,
                "cost_basis_method": "weighted_average_preview",
            },
        },
    )
    client = _client_for_db(
        monkeypatch,
        db,
        controlled_bridge_policy=_controlled_bridge_policy(),
    )
    client.post(
        f"/api/broker-gateway/orders/{order['order_id']}/manual-ticket",
        json={"actor": "test"},
    )
    preview_response = client.post(
        f"/api/broker-gateway/orders/{order['order_id']}/manual-execution/preview",
        json={
            "actor": "test",
            "fill_price": "1688.00",
            "quantity": "100",
            "fee": "5.00",
            "tax": "0.00",
            "transfer_fee": "0.10",
        },
    )
    preview = preview_response.json()
    event_count_before = len(
        db.list_broker_gateway_events_sync(order_id=order["order_id"])
    )

    response = client.post(
        f"/api/broker-gateway/orders/{order['order_id']}/manual-execution",
        json={
            "actor": "test",
            "preview_fingerprint": preview["preview_fingerprint"],
            "fill_price": "1688.00",
            "quantity": "100",
            "fee": "5.00",
            "tax": "0.00",
            "transfer_fee": "0.10",
            "operator_note": "broker client fill reviewed",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "manual_execution_recorded"
    assert payload["submitted_to_broker"] is False
    assert payload["does_not_mutate_oms"] is True
    assert payload["does_not_mutate_production_ledger"] is True
    assert payload["preview_fingerprint"] == preview["preview_fingerprint"]
    assert payload["execution_preview"]["net_cash_impact"] == "-168805.10"
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manual_ticket_created"
    events = db.list_broker_gateway_events_sync(order_id=order["order_id"])
    assert len(events) == event_count_before + 1
    assert events[-1]["event_type"] == "manual_execution_recorded"


def test_manual_ticket_dry_run_route_records_accepted_event(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    order = _confirmed_order(db)
    client = _client_for_db(monkeypatch, db)

    response = client.post(
        f"/api/broker-gateway/orders/{order['order_id']}/manual-ticket/dry-run",
        json={"actor": "test"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "dry_run_accepted"
    assert payload["dry_run"] is True
    assert payload["submitted_to_broker"] is False
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    events = db.list_broker_gateway_events_sync(order_id=order["order_id"])
    assert events[-1]["event_type"] == "manual_ticket_dry_run_accepted"
    assert events[-1]["status"] == "accepted"


def test_manual_ticket_dry_run_route_records_rejected_event(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    order = _confirmed_order(db, gateway_evidence=False)
    client = _client_for_db(monkeypatch, db)

    response = client.post(
        f"/api/broker-gateway/orders/{order['order_id']}/manual-ticket/dry-run",
        json={"actor": "test"},
    )

    assert response.status_code == 409
    assert "missing gateway evidence" in response.json()["detail"]
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    events = db.list_broker_gateway_events_sync(order_id=order["order_id"])
    assert events[-1]["event_type"] == "manual_ticket_dry_run_rejected"
    assert events[-1]["status"] == "rejected"


def test_manual_ticket_query_route_is_read_only_and_returns_staged_fills(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    order = _confirmed_order(db)
    client = _client_for_db(monkeypatch, db)
    dry_run = client.post(
        f"/api/broker-gateway/orders/{order['order_id']}/manual-ticket/dry-run",
        json={"actor": "test"},
    )
    assert dry_run.status_code == 200
    created = client.post(
        f"/api/broker-gateway/orders/{order['order_id']}/manual-ticket",
        json={"actor": "test"},
    )
    assert created.status_code == 200
    _import_broker_trade(Path(db._path), event_id="broker-buy-600519", quantity=100)
    event_count_before = len(
        db.list_broker_gateway_events_sync(order_id=order["order_id"])
    )

    response = client.get(f"/api/broker-gateway/orders/{order['order_id']}/query")

    assert response.status_code == 200
    payload = response.json()
    assert payload["query_scope"] == "local_audit_and_staged_broker_evidence"
    assert payload["submitted_to_broker"] is False
    assert payload["can_submit_orders"] is False
    assert payload["oms_order"]["status"] == "manual_ticket_created"
    assert payload["gateway_event_count"] == 2
    assert payload["staged_broker_fill_count"] == 1
    assert payload["staged_broker_fills"][0]["event_id"] == "broker-buy-600519"
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manual_ticket_created"
    assert (
        len(db.list_broker_gateway_events_sync(order_id=order["order_id"]))
        == event_count_before
    )


def test_staged_account_facts_route_is_read_only(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    _import_broker_trade(Path(db._path), event_id="broker-buy-600519", quantity=100)
    client = _client_for_db(monkeypatch, db)
    events_before = db.list_broker_gateway_events_sync()

    response = client.get("/api/broker-gateway/account-facts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["gateway_id"] == "staged_broker_evidence"
    assert payload["query_scope"] == "staged_broker_evidence"
    assert payload["submitted_to_broker"] is False
    assert payload["can_submit_orders"] is False
    assert payload["broker_event_count"] == 1
    assert payload["cash_balances"][0]["currency"] == "CNY"
    assert payload["cash_balances"][0]["cash_balance"] == "100000.00"
    assert payload["positions"][0]["symbol"] == "600519"
    assert payload["positions"][0]["quantity"] == "100"
    assert payload["fills"][0]["event_id"] == "broker-buy-600519"
    assert db.list_broker_gateway_events_sync() == events_before


def test_staged_fill_query_route_is_read_only_and_filterable(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    _import_broker_trade(
        Path(db._path),
        event_id="broker-buy-600519",
        quantity=100,
        symbol="600519",
        instrument_name="贵州茅台",
    )
    _import_broker_trade(
        Path(db._path),
        event_id="broker-buy-000001",
        quantity=200,
        symbol="000001",
        instrument_name="平安银行",
    )
    client = _client_for_db(monkeypatch, db)
    events_before = db.list_broker_gateway_events_sync()

    response = client.get("/api/broker-gateway/fills/query?symbol=600519")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "karkinos.broker_gateway.v1"
    assert payload["gateway_id"] == "staged_broker_evidence"
    assert payload["query_scope"] == "staged_broker_fills"
    assert payload["submitted_to_broker"] is False
    assert payload["can_submit_orders"] is False
    assert payload["symbol"] == "600519"
    assert payload["fill_count"] == 1
    assert payload["fills"][0]["event_id"] == "broker-buy-600519"
    assert payload["fills"][0]["symbol"] == "600519"
    assert db.list_broker_gateway_events_sync() == events_before


def test_manual_ticket_preview_route_blocks_missing_gateway_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    order = _confirmed_order(db, gateway_evidence=False)
    client = _client_for_db(monkeypatch, db)

    response = client.post(
        f"/api/broker-gateway/orders/{order['order_id']}/manual-ticket/preview",
        json={"actor": "test"},
    )

    assert response.status_code == 409
    assert "missing gateway evidence" in response.json()["detail"]
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    assert db.list_broker_gateway_events_sync(order_id=order["order_id"]) == []


def test_manual_ticket_preview_route_blocks_kill_switch(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    order = _confirmed_order(db)
    controls = TradingControlState(db=db)
    controls.set_kill_switch(True, "operator pause")
    client = _client_for_db(monkeypatch, db, trading_controls=controls)

    response = client.post(
        f"/api/broker-gateway/orders/{order['order_id']}/manual-ticket/preview",
        json={"actor": "test"},
    )

    assert response.status_code == 409
    assert "kill switch is enabled" in response.json()["detail"]
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    assert db.list_broker_gateway_events_sync(order_id=order["order_id"]) == []


def test_manual_ticket_route_blocks_kill_switch_without_oms_mutation(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    order = _confirmed_order(db)
    controls = TradingControlState(db=db)
    controls.set_kill_switch(True, "operator pause")
    client = _client_for_db(monkeypatch, db, trading_controls=controls)

    response = client.post(
        f"/api/broker-gateway/orders/{order['order_id']}/manual-ticket",
        json={"actor": "test"},
    )

    assert response.status_code == 409
    assert "kill switch is enabled" in response.json()["detail"]
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    assert db.list_broker_gateway_events_sync(order_id=order["order_id"]) == []


def test_broker_cancel_route_is_disabled_and_audited(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    order = _confirmed_order(db)
    client = _client_for_db(monkeypatch, db)

    response = client.post(
        f"/api/broker-gateway/orders/{order['order_id']}/broker-cancel",
        json={"actor": "test"},
    )

    assert response.status_code == 409
    assert "live broker cancellation is disabled" in response.json()["detail"]
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    events = db.list_broker_gateway_events_sync(order_id=order["order_id"])
    assert events[-1]["gateway_id"] == "live_disabled"
    assert events[-1]["event_type"] == "live_cancel_rejected"
    assert events[-1]["status"] == "rejected"


def _import_broker_trade(
    db_path: Path,
    *,
    event_id: str,
    quantity: int,
    symbol: str = "600519",
    instrument_name: str = "贵州茅台",
    event_type: str = "trade_buy",
) -> None:
    side_net_amount = "-168805.00" if event_type == "trade_buy" else "168795.00"
    content = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note
{event_id},{event_type},2026-07-02T10:05:00+08:00,2026-07-03,{symbol},{instrument_name},stock,CNY,{quantity},1688.00,168800.00,5.00,0.00,{net_amount},100000.00,{quantity},1688.05,manual ticket match
""".format(
        event_id=event_id,
        event_type=event_type,
        symbol=symbol,
        instrument_name=instrument_name,
        quantity=quantity,
        net_amount=side_net_amount,
    )
    BrokerEvidenceRepository(db_path).save_preview(
        parse_broker_statement_csv(content),
        source_name="broker_statement.csv",
    )
