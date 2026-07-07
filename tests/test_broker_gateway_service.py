from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from account_truth.broker_connector import (
    BrokerCashFact,
    BrokerConnectorCapabilities,
    BrokerConnectorHealth,
    BrokerConnectorSnapshot,
    BrokerFillFact,
    BrokerOrderFact,
    BrokerPositionFact,
    FakeReadOnlyBrokerConnector,
)
from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from server.config import BrokerConnectorConfig
from server.db import AppDatabase
from server.services.broker_gateway import BrokerGatewayService
from server.services.oms import OmsService
from server.services.trading_controls import TradingControlState


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
        allowed_connector_ids=["local-qmt-readonly"],
        allowed_account_aliases=["local-review"],
        allowed_strategy_ids=["dual_ma"],
        allowed_symbols=["600519"],
        per_order_confirmation_required=True,
        automation_allowed=False,
    )


def _confirmed_order(
    tmp_path,
    *,
    gateway_evidence: bool = True,
    order_intent_payload: dict | None = None,
) -> tuple[AppDatabase, dict]:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
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
    confirmed = oms.transition_order(
        order["order_id"],
        to_status="manually_confirmed",
        reason="operator approved paper/shadow evidence",
        actor="test",
    )
    return db, confirmed


def test_gateway_status_exposes_manual_ticket_and_disabled_live_gateway(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    service = BrokerGatewayService(db=db)

    gateways = {item["gateway_id"]: item for item in service.list_gateways()}

    assert gateways["manual_ticket"]["status"] == "available"
    assert gateways["manual_ticket"]["can_submit_orders"] is False
    assert gateways["manual_ticket"]["can_preview_orders"] is True
    assert gateways["manual_ticket"]["can_export_tickets"] is True
    assert gateways["manual_ticket"]["can_dry_run_orders"] is True
    assert gateways["manual_ticket"]["can_query_orders"] is True
    assert gateways["manual_ticket"]["can_query_fills"] is True
    assert gateways["manual_ticket"]["can_read_account_facts"] is False
    assert gateways["manual_ticket"]["requires_human_broker_entry"] is True
    assert gateways["staged_broker_evidence"]["status"] == "available"
    assert gateways["staged_broker_evidence"]["can_read_account_facts"] is True
    assert gateways["staged_broker_evidence"]["can_query_cash"] is True
    assert gateways["staged_broker_evidence"]["can_query_positions"] is True
    assert gateways["staged_broker_evidence"]["can_query_fills"] is True
    assert gateways["staged_broker_evidence"]["can_submit_orders"] is False
    assert gateways["staged_broker_evidence"]["can_export_tickets"] is False
    assert gateways["live_disabled"]["status"] == "disabled"
    assert gateways["live_disabled"]["can_submit_orders"] is False
    assert gateways["live_disabled"]["can_preview_orders"] is False
    assert gateways["live_disabled"]["can_export_tickets"] is False
    assert gateways["live_disabled"]["can_dry_run_orders"] is False


def test_gateway_status_marks_manual_ticket_blocked_by_kill_switch(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    controls = TradingControlState(db=db)
    controls.set_kill_switch(True, "operator pause")
    service = BrokerGatewayService(db=db, trading_controls=controls)

    status = service.get_status()
    gateways = {item["gateway_id"]: item for item in status["gateways"]}

    assert status["broker_submission_enabled"] is False
    assert status["kill_switch_enabled"] is True
    assert status["kill_switch_reason"] == "operator pause"
    manual_ticket = gateways["manual_ticket"]
    assert manual_ticket["status"] == "blocked_by_kill_switch"
    assert manual_ticket["can_preview_orders"] is False
    assert manual_ticket["can_export_tickets"] is False
    assert manual_ticket["can_dry_run_orders"] is False
    assert manual_ticket["can_submit_orders"] is False
    assert manual_ticket["blockers"] == ["kill_switch"]
    assert manual_ticket["blocked_reason"] == "operator pause"
    assert gateways["staged_broker_evidence"]["status"] == "available"


def test_gateway_status_exposes_disabled_controlled_bridge_policy(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    service = BrokerGatewayService(db=db)

    status = service.get_status()

    policy = status["controlled_bridge_policy"]
    assert status["broker_submission_enabled"] is False
    assert policy["schema_version"] == "karkinos.controlled_broker_bridge_policy.v1"
    assert policy["status"] == "disabled"
    assert policy["enabled"] is False
    assert policy["broker_submission_enabled"] is False
    assert policy["live_submission_available"] is False
    assert policy["automation_allowed"] is False
    assert policy["per_order_confirmation_required"] is True
    assert policy["allowed_connector_ids"] == []
    assert policy["allowed_account_aliases"] == []
    assert policy["allowed_strategy_ids"] == []
    assert policy["allowed_symbols"] == []
    assert policy["required_gates"] == [
        "account_truth",
        "research_evidence",
        "risk",
        "paper_shadow",
        "manual_confirmation",
        "kill_switch_clear",
        "connector_health",
        "execution_reconciliation",
    ]
    assert policy["blockers"] == [
        "controlled_bridge_policy_disabled",
        "controlled_bridge_whitelist_empty",
        "live_gateway_not_implemented",
    ]


def test_gateway_status_keeps_configured_bridge_policy_non_submitting(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    service = BrokerGatewayService(
        db=db,
        controlled_bridge_policy=_controlled_bridge_policy(),
    )

    status = service.get_status()
    gateways = {item["gateway_id"]: item for item in status["gateways"]}

    assert status["broker_submission_enabled"] is False
    policy = status["controlled_bridge_policy"]
    assert policy["policy_id"] == "local-controlled-bridge-review"
    assert policy["status"] == "configured_non_submitting"
    assert policy["enabled"] is True
    assert policy["broker_submission_enabled"] is False
    assert policy["live_submission_available"] is False
    assert policy["automation_allowed"] is False
    assert policy["per_order_confirmation_required"] is True
    assert policy["allowed_connector_ids"] == ["local-qmt-readonly"]
    assert policy["allowed_account_aliases"] == ["local-review"]
    assert policy["allowed_strategy_ids"] == ["dual_ma"]
    assert policy["allowed_symbols"] == ["600519"]
    assert policy["blockers"] == ["live_gateway_not_implemented"]
    assert gateways["live_disabled"]["status"] == "disabled"
    assert gateways["live_disabled"]["can_submit_orders"] is False
    assert gateways["live_disabled"]["controlled_bridge_policy_status"] == (
        "configured_non_submitting"
    )


def test_connector_health_contract_is_read_only_and_non_submitting(tmp_path) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    service = BrokerGatewayService(
        db=db,
        broker_connectors=[
            BrokerConnectorConfig(
                connector_id="local-qmt-readonly",
                connector_type="qmt_readonly",
                enabled=True,
                client_path="/Applications/QMT",
                account_alias="local-review",
            ),
            BrokerConnectorConfig(
                connector_id="local-ptrade-readonly",
                connector_type="ptrade_readonly",
                enabled=False,
            ),
        ],
    )

    health = {item["connector_id"]: item for item in service.list_connector_health()}

    qmt = health["local-qmt-readonly"]
    assert qmt["status"] == "configured_readonly_unverified"
    assert qmt["capability_scope"] == "local_readonly_connector_contract"
    assert qmt["capabilities"]["can_read_account"] is True
    assert qmt["capabilities"]["can_read_orders"] is True
    assert qmt["capabilities"]["can_read_fills"] is True
    assert qmt["capabilities"]["can_preview_orders"] is False
    assert qmt["capabilities"]["can_export_tickets"] is False
    assert qmt["capabilities"]["can_dry_run_orders"] is False
    assert qmt["capabilities"]["can_submit_orders"] is False
    assert qmt["capabilities"]["can_cancel_orders"] is False
    assert qmt["stores_credentials"] is False
    assert qmt["requires_credentials"] is False
    assert "client_path" not in qmt

    ptrade = health["local-ptrade-readonly"]
    assert ptrade["status"] == "disabled"
    assert ptrade["capability_scope"] == "local_readonly_connector_contract"
    assert ptrade["capabilities"]["can_read_account"] is False
    assert ptrade["capabilities"]["can_preview_orders"] is False
    assert ptrade["capabilities"]["can_export_tickets"] is False
    assert ptrade["capabilities"]["can_dry_run_orders"] is False
    assert ptrade["capabilities"]["can_submit_orders"] is False


def test_runtime_readonly_connector_health_uses_snapshot_without_submission(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    connector = FakeReadOnlyBrokerConnector(
        BrokerConnectorSnapshot(
            connector_id="fake-qmt-runtime",
            source_name="synthetic qmt readonly runtime",
            account_id="private-account-id",
            account_alias="local-review",
            captured_at="2026-07-02T09:31:00+08:00",
            health=BrokerConnectorHealth(
                status="stale",
                checked_at="2026-07-02T09:30:00+08:00",
                message="Read-only connector heartbeat is stale.",
                limitations=["Runtime connector fixture is stale."],
            ),
            cash=BrokerCashFact(
                currency="CNY",
                balance=Decimal("100000.00"),
                available=Decimal("88000.00"),
            ),
            limitations=["Synthetic runtime snapshot; no broker client submitted."],
        ),
        capabilities=BrokerConnectorCapabilities(can_submit_orders=True),
    )
    service = BrokerGatewayService(db=db, broker_connectors=[connector])

    health = service.list_connector_health()

    assert len(health) == 1
    payload = health[0]
    assert payload["connector_id"] == "fake-qmt-runtime"
    assert payload["connector_type"] == "read_only_snapshot"
    assert payload["status"] == "runtime_degraded"
    assert payload["message"] == "Read-only connector heartbeat is stale."
    assert payload["account_alias"] == "local-review"
    assert payload["capability_scope"] == "runtime_readonly_connector_snapshot"
    assert payload["last_heartbeat_at"] == "2026-07-02T09:30:00+08:00"
    assert payload["last_error"] == "Read-only connector heartbeat is stale."
    assert payload["capabilities"]["can_read_account"] is True
    assert payload["capabilities"]["can_read_cash"] is True
    assert payload["capabilities"]["can_preview_orders"] is False
    assert payload["capabilities"]["can_export_tickets"] is False
    assert payload["capabilities"]["can_dry_run_orders"] is False
    assert payload["capabilities"]["can_submit_orders"] is False
    assert payload["capabilities"]["can_cancel_orders"] is False
    assert payload["requires_credentials"] is False
    assert payload["stores_credentials"] is False
    assert payload["submitted_to_broker"] is False
    assert "account_id" not in payload
    assert "private-account-id" not in json.dumps(payload, ensure_ascii=False)
    assert (
        "Read-only connector snapshot is runtime evidence only."
        in payload["limitations"]
    )
    assert db.list_broker_gateway_events_sync() == []


def test_runtime_readonly_connector_snapshot_query_is_non_mutating(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    connector = FakeReadOnlyBrokerConnector(
        BrokerConnectorSnapshot(
            connector_id="fake-qmt-runtime",
            source_name="synthetic qmt readonly runtime",
            account_id="private-account-id",
            account_alias="local-review",
            captured_at="2026-07-02T09:31:00+08:00",
            health=BrokerConnectorHealth(
                status="healthy",
                checked_at="2026-07-02T09:30:00+08:00",
                message="Read-only connector heartbeat is healthy.",
            ),
            cash=BrokerCashFact(
                currency="CNY",
                balance=Decimal("100000.00"),
                available=Decimal("88000.00"),
            ),
            positions=[
                BrokerPositionFact(
                    symbol="600519",
                    instrument_name="贵州茅台",
                    asset_class="stock",
                    quantity=Decimal("200"),
                    available_quantity=Decimal("100"),
                    cost_basis=Decimal("1600.00"),
                    market_price=Decimal("1688.00"),
                )
            ],
            orders=[
                BrokerOrderFact(
                    order_id="broker-order-private",
                    symbol="600519",
                    side="buy",
                    status="filled",
                    quantity=Decimal("100"),
                    price=Decimal("1688.00"),
                    submitted_at="2026-07-02T09:31:10+08:00",
                )
            ],
            fills=[
                BrokerFillFact(
                    fill_id="fill-001",
                    order_id="broker-order-private",
                    symbol="600519",
                    side="buy",
                    quantity=Decimal("100"),
                    price=Decimal("1688.00"),
                    fee=Decimal("5.10"),
                    tax=Decimal("0"),
                    net_amount=Decimal("-168805.10"),
                    filled_at="2026-07-02T09:31:20+08:00",
                )
            ],
        ),
        capabilities=BrokerConnectorCapabilities(can_submit_orders=True),
    )
    service = BrokerGatewayService(db=db, broker_connectors=[connector])

    result = service.query_connector_snapshot("fake-qmt-runtime")

    assert result["gateway_id"] == "read_only_connector"
    assert result["query_scope"] == "runtime_readonly_connector_snapshot"
    assert result["status"] == "snapshot_ready"
    assert result["connector_id"] == "fake-qmt-runtime"
    assert result["account_alias"] == "local-review"
    assert result["captured_at"] == "2026-07-02T09:31:00+08:00"
    assert result["connector_health"]["status"] == "runtime_healthy"
    assert result["cash_balance"]["currency"] == "CNY"
    assert result["cash_balance"]["balance"] == "100000.00"
    assert result["position_count"] == 1
    assert result["positions"][0]["symbol"] == "600519"
    assert result["positions"][0]["quantity"] == "200"
    assert result["order_count"] == 1
    assert result["orders"][0]["order_id"] == "broker-order-private"
    assert result["fill_count"] == 1
    assert result["fills"][0]["net_amount"] == "-168805.10"
    assert result["capabilities"]["can_read_account"] is True
    assert result["capabilities"]["can_preview_orders"] is False
    assert result["capabilities"]["can_export_tickets"] is False
    assert result["capabilities"]["can_dry_run_orders"] is False
    assert result["capabilities"]["can_submit_orders"] is False
    assert result["capabilities"]["can_cancel_orders"] is False
    assert result["stores_credentials"] is False
    assert result["submitted_to_broker"] is False
    assert result["does_not_mutate_oms"] is True
    assert result["does_not_mutate_production_ledger"] is True
    assert "account_id" not in result
    assert "private-account-id" not in json.dumps(result, ensure_ascii=False)
    assert db.list_broker_gateway_events_sync() == []


def test_manual_ticket_gateway_creates_ticket_without_broker_submission(
    tmp_path,
) -> None:
    db, order = _confirmed_order(tmp_path)
    service = BrokerGatewayService(
        db=db,
        controlled_bridge_policy=_controlled_bridge_policy(),
    )

    result = service.create_manual_ticket(order["order_id"], actor="test")

    assert result["gateway_id"] == "manual_ticket"
    assert result["submitted_to_broker"] is False
    assert result["controlled_bridge_policy"]["status"] == ("configured_non_submitting")
    assert result["controlled_bridge_policy"]["broker_submission_enabled"] is False
    assert result["ticket"]["symbol"] == "600519"
    assert result["ticket"]["side"] == "buy"
    assert result["ticket"]["quantity"] == 100
    assert result["ticket"]["limit_price"] == 1688.0
    updated = db.get_oms_order_sync(order["order_id"])
    assert updated["status"] == "manual_ticket_created"
    events = db.list_broker_gateway_events_sync(order_id=order["order_id"])
    assert events[-1]["gateway_id"] == "manual_ticket"
    assert events[-1]["event_type"] == "manual_ticket_created"
    payload = json.loads(events[-1]["payload_json"])
    assert payload["controlled_bridge_policy"]["policy_id"] == (
        "local-controlled-bridge-review"
    )
    assert payload["controlled_bridge_policy"]["live_submission_available"] is False


def test_manual_ticket_preview_is_dry_run_and_does_not_mutate_oms(
    tmp_path,
) -> None:
    db, order = _confirmed_order(tmp_path)
    service = BrokerGatewayService(
        db=db,
        controlled_bridge_policy=_controlled_bridge_policy(),
    )

    result = service.preview_manual_ticket(order["order_id"], actor="test")

    assert result["gateway_id"] == "manual_ticket"
    assert result["status"] == "preview_ready"
    assert result["dry_run"] is True
    assert result["submitted_to_broker"] is False
    assert result["validation"]["manual_confirmation_status"] == "pass"
    assert result["validation"]["controlled_bridge_policy"]["policy_id"] == (
        "local-controlled-bridge-review"
    )
    assert (
        result["validation"]["controlled_bridge_policy"]["broker_submission_enabled"]
        is False
    )
    assert result["ticket"]["copy_text"].startswith("BUY 600519 100")
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    assert db.list_broker_gateway_events_sync(order_id=order["order_id"]) == []


def test_manual_ticket_export_is_read_only_and_copy_safe(tmp_path) -> None:
    db, order = _confirmed_order(tmp_path)
    service = BrokerGatewayService(
        db=db,
        controlled_bridge_policy=_controlled_bridge_policy(),
    )

    result = service.export_manual_ticket(order["order_id"], actor="test")

    assert result["gateway_id"] == "manual_ticket"
    assert result["status"] == "export_ready"
    assert result["dry_run"] is True
    assert result["submitted_to_broker"] is False
    assert result["ticket"]["copy_text"] == "BUY 600519 100 LIMIT 1688"
    assert result["validation"]["controlled_bridge_policy"]["status"] == (
        "configured_non_submitting"
    )
    assert result["export"]["schema_version"] == "karkinos.manual_ticket_export.v1"
    assert result["export"]["format"] == "json"
    assert result["export"]["mime_type"] == "application/json"
    assert result["export"]["file_name"].startswith("karkinos-manual-ticket-")
    assert result["export"]["copy_text"] == "BUY 600519 100 LIMIT 1688"
    form = result["ticket"]["operator_form"]
    assert form["schema_version"] == "karkinos.manual_ticket_operator_form.v1"
    assert form["account_alias"] == "local-review"
    assert form["field_labels"] == {
        "account_alias": "Account alias",
        "symbol": "Symbol",
        "side": "Side",
        "quantity": "Quantity",
        "order_type": "Order type",
        "limit_price": "Limit price",
        "copy_text": "Broker copy text",
    }
    assert form["fields"][0] == {
        "key": "account_alias",
        "label": "Account alias",
        "value": "local-review",
    }
    assert form["fee_tax_assumptions"]["source"] == "oms_order_payload_or_fee_rule"
    assert form["fee_tax_assumptions"]["estimated_total_fee"] is None
    assert form["fee_tax_assumptions"]["fee_components"] == {}
    assert form["trading_session_constraints"]["timezone"] == "Asia/Shanghai"
    assert form["trading_session_constraints"]["allowed_session"] == (
        "regular_exchange_session_only"
    )
    assert form["safety"]["submitted_to_broker"] is False
    assert form["safety"]["requires_human_broker_entry"] is True
    content = json.loads(result["export"]["content_json"])
    assert content["submitted_to_broker"] is False
    assert content["requires_human_broker_entry"] is True
    assert content["operator_form"]["account_alias"] == "local-review"
    assert content["operator_form"]["field_labels"]["limit_price"] == "Limit price"
    assert (
        content["operator_form"]["trading_session_constraints"]["allowed_session"]
        == "regular_exchange_session_only"
    )
    assert content["controlled_bridge_policy"]["policy_id"] == (
        "local-controlled-bridge-review"
    )
    assert content["controlled_bridge_policy"]["allowed_symbols"] == ["600519"]
    assert content["controlled_bridge_policy"]["live_submission_available"] is False
    assert content["ticket"]["symbol"] == "600519"
    assert content["gateway_evidence_refs"] == {
        "account_truth": "account-truth:1",
        "paper_shadow": "paper_shadow:run-001",
        "research_evidence": "research:1",
        "risk": "risk:risk-001",
    }
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    assert db.list_broker_gateway_events_sync(order_id=order["order_id"]) == []


def test_manual_ticket_operator_form_preserves_cash_and_position_preview(
    tmp_path,
) -> None:
    db, order = _confirmed_order(
        tmp_path,
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
    service = BrokerGatewayService(
        db=db,
        controlled_bridge_policy=_controlled_bridge_policy(),
    )

    result = service.export_manual_ticket(order["order_id"], actor="test")

    form = result["ticket"]["operator_form"]
    assert form["fee_tax_assumptions"]["estimated_total_fee"] == 5.1
    assert form["cash_impact_preview"] == {
        "source": "oms_order_payload_or_order_intent",
        "estimated_gross_amount": 168800,
        "estimated_total_fee": 5.1,
        "estimated_net_cash_impact": -168805.1,
        "available_cash_before": 200000,
        "available_cash_after": 31194.9,
        "cash_status": "sufficient",
        "cash_shortfall": 0,
    }
    assert form["position_cost_preview"] == {
        "source": "daily_trading_plan_position_effect",
        "current_quantity": 100,
        "current_avg_cost": 1600,
        "current_market_value": 168800,
        "estimated_quantity_after": 200,
        "estimated_avg_cost_after": 1644,
        "cost_basis_method": "weighted_average_preview",
    }
    content = json.loads(result["export"]["content_json"])
    assert (
        content["operator_form"]["cash_impact_preview"]["estimated_net_cash_impact"]
        == -168805.1
    )
    assert (
        content["operator_form"]["position_cost_preview"]["estimated_quantity_after"]
        == 200
    )
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    assert db.list_broker_gateway_events_sync(order_id=order["order_id"]) == []


def test_manual_ticket_dry_run_records_accepted_event_without_oms_mutation(
    tmp_path,
) -> None:
    db, order = _confirmed_order(tmp_path)
    service = BrokerGatewayService(
        db=db,
        controlled_bridge_policy=_controlled_bridge_policy(),
    )

    result = service.dry_run_manual_ticket(order["order_id"], actor="test")

    assert result["gateway_id"] == "manual_ticket"
    assert result["status"] == "dry_run_accepted"
    assert result["dry_run"] is True
    assert result["submitted_to_broker"] is False
    assert result["ticket"]["copy_text"].startswith("BUY 600519 100")
    assert result["validation"]["gateway_evidence_status"] == "pass"
    assert result["validation"]["controlled_bridge_policy"]["status"] == (
        "configured_non_submitting"
    )
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    events = db.list_broker_gateway_events_sync(order_id=order["order_id"])
    assert len(events) == 1
    assert events[0]["event_type"] == "manual_ticket_dry_run_accepted"
    assert events[0]["status"] == "accepted"
    payload = json.loads(events[0]["payload_json"])
    assert payload["dry_run"] is True
    assert payload["submitted_to_broker"] is False
    assert payload["validation_result"] == "accepted"
    assert payload["controlled_bridge_policy"]["policy_id"] == (
        "local-controlled-bridge-review"
    )
    assert payload["controlled_bridge_policy"]["automation_allowed"] is False


def test_manual_ticket_dry_run_records_rejected_event_without_oms_mutation(
    tmp_path,
) -> None:
    db, order = _confirmed_order(tmp_path, gateway_evidence=False)
    service = BrokerGatewayService(db=db)

    try:
        service.dry_run_manual_ticket(order["order_id"], actor="test")
    except ValueError as exc:
        assert "missing gateway evidence" in str(exc)
    else:
        raise AssertionError("expected missing gateway evidence to reject dry-run")

    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    events = db.list_broker_gateway_events_sync(order_id=order["order_id"])
    assert len(events) == 1
    assert events[0]["event_type"] == "manual_ticket_dry_run_rejected"
    assert events[0]["status"] == "rejected"
    payload = json.loads(events[0]["payload_json"])
    assert payload["dry_run"] is True
    assert payload["submitted_to_broker"] is False
    assert payload["validation_result"] == "rejected"
    assert "account_truth" in payload["rejection_reason"]


def test_manual_ticket_preview_blocks_when_kill_switch_enabled(tmp_path) -> None:
    db, order = _confirmed_order(tmp_path)
    controls = TradingControlState(db=db)
    controls.set_kill_switch(True, "operator pause")
    service = BrokerGatewayService(db=db, trading_controls=controls)

    try:
        service.preview_manual_ticket(order["order_id"], actor="test")
    except ValueError as exc:
        assert "kill switch is enabled" in str(exc)
        assert "operator pause" in str(exc)
    else:
        raise AssertionError("expected kill switch to block manual-ticket preview")

    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    assert db.list_broker_gateway_events_sync(order_id=order["order_id"]) == []


def test_manual_ticket_dry_run_records_kill_switch_rejection_without_oms_mutation(
    tmp_path,
) -> None:
    db, order = _confirmed_order(tmp_path)
    controls = TradingControlState(db=db)
    controls.set_kill_switch(True, "operator pause")
    service = BrokerGatewayService(db=db, trading_controls=controls)

    try:
        service.dry_run_manual_ticket(order["order_id"], actor="test")
    except ValueError as exc:
        assert "kill switch is enabled" in str(exc)
    else:
        raise AssertionError("expected kill switch to reject dry-run")

    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    events = db.list_broker_gateway_events_sync(order_id=order["order_id"])
    assert len(events) == 1
    assert events[0]["event_type"] == "manual_ticket_dry_run_rejected"
    assert events[0]["status"] == "rejected"
    payload = json.loads(events[0]["payload_json"])
    assert payload["dry_run"] is True
    assert payload["submitted_to_broker"] is False
    assert payload["validation_result"] == "rejected"
    assert "kill switch is enabled" in payload["rejection_reason"]


def test_manual_ticket_query_returns_local_audit_and_staged_broker_evidence(
    tmp_path,
) -> None:
    db, order = _confirmed_order(tmp_path)
    service = BrokerGatewayService(db=db)
    service.dry_run_manual_ticket(order["order_id"], actor="test")
    service.create_manual_ticket(order["order_id"], actor="test")
    _import_broker_trade(Path(db._path), event_id="broker-buy-600519", quantity=100)
    event_count_before = len(
        db.list_broker_gateway_events_sync(order_id=order["order_id"])
    )

    result = service.query_order(order["order_id"])

    assert result["gateway_id"] == "manual_ticket"
    assert result["query_scope"] == "local_audit_and_staged_broker_evidence"
    assert result["submitted_to_broker"] is False
    assert result["can_submit_orders"] is False
    assert result["oms_order"]["status"] == "manual_ticket_created"
    assert result["gateway_event_count"] == 2
    assert result["staged_broker_fill_count"] == 1
    assert result["staged_broker_fills"][0]["event_id"] == "broker-buy-600519"
    assert result["staged_broker_fills"][0]["match_status"] == "matched"
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manual_ticket_created"
    assert (
        len(db.list_broker_gateway_events_sync(order_id=order["order_id"]))
        == event_count_before
    )


def test_manual_execution_preview_calculates_ledger_draft_without_mutation(
    tmp_path,
) -> None:
    db, order = _confirmed_order(
        tmp_path,
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
    service = BrokerGatewayService(
        db=db,
        controlled_bridge_policy=_controlled_bridge_policy(),
    )
    service.create_manual_ticket(order["order_id"], actor="test")
    event_count_before = len(
        db.list_broker_gateway_events_sync(order_id=order["order_id"])
    )

    result = service.preview_manual_execution_record(
        order["order_id"],
        fill_price="1688.00",
        quantity="100",
        fee="5.00",
        tax="0.00",
        transfer_fee="0.10",
        actor="test",
    )

    assert result["schema_version"] == "karkinos.broker_gateway.v1"
    assert result["gateway_id"] == "manual_ticket"
    assert result["status"] == "manual_execution_preview_ready"
    assert result["dry_run"] is True
    assert result["submitted_to_broker"] is False
    assert result["does_not_mutate_production_ledger"] is True
    assert result["order_id"] == order["order_id"]
    assert result["execution_preview"]["source"] == "manual_ticket_operator_entry"
    assert result["execution_preview"]["symbol"] == "600519"
    assert result["execution_preview"]["side"] == "buy"
    assert result["execution_preview"]["quantity"] == "100"
    assert result["execution_preview"]["fill_price"] == "1688.00"
    assert result["execution_preview"]["gross_amount"] == "168800.00"
    assert result["execution_preview"]["fee"] == "5.00"
    assert result["execution_preview"]["tax"] == "0.00"
    assert result["execution_preview"]["transfer_fee"] == "0.10"
    assert result["execution_preview"]["total_cost"] == "5.10"
    assert result["execution_preview"]["net_cash_impact"] == "-168805.10"
    assert result["ledger_entry_draft"]["entry_type"] == "trade"
    assert result["ledger_entry_draft"]["amount"] == "-168805.10"
    assert result["ledger_entry_draft"]["source_order_id"] == order["order_id"]
    assert result["ledger_entry_draft"]["requires_operator_save"] is True
    assert result["ledger_entry_draft"]["does_not_mutate_production_ledger"] is True
    assert result["position_cost_preview"]["current_quantity"] == 100
    assert result["position_cost_preview"]["estimated_quantity_after"] == 200
    assert result["safety"]["requires_human_broker_entry"] is True
    assert result["safety"]["requires_operator_save"] is True
    assert result["safety"]["submitted_to_broker"] is False
    assert result["safety"]["does_not_mutate_production_ledger"] is True
    gate_summary = result["validation"]["required_gate_summary"]
    assert (
        gate_summary["schema_version"] == "karkinos.controlled_bridge_gate_summary.v1"
    )
    assert gate_summary["status"] == "pass"
    assert gate_summary["submitted_to_broker"] is False
    assert gate_summary["does_not_authorize_execution"] is True
    assert gate_summary["required_gates"] == [
        "account_truth",
        "research_evidence",
        "risk",
        "paper_shadow",
        "manual_confirmation",
        "kill_switch_clear",
        "connector_health",
        "execution_reconciliation",
    ]
    assert gate_summary["gates"]["account_truth"] == {
        "status": "pass",
        "evidence_ref": "account-truth:1",
        "source": "oms_gateway_evidence",
    }
    assert gate_summary["gates"]["research_evidence"] == {
        "status": "pass",
        "evidence_ref": "research:1",
        "source": "oms_gateway_evidence",
    }
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
    assert gate_summary["gates"]["manual_confirmation"] == {
        "status": "pass",
        "evidence_ref": f"oms_order:{order['order_id']}:manual_ticket_created",
        "source": "oms_status",
    }
    assert gate_summary["gates"]["kill_switch_clear"] == {
        "status": "pass",
        "evidence_ref": "trading_controls:kill_switch_clear",
        "source": "trading_controls_snapshot",
    }
    assert gate_summary["gates"]["connector_health"] == {
        "status": "not_applicable_manual_ticket",
        "evidence_ref": "manual_ticket:local_operator_entry",
        "source": "manual_ticket_gateway",
    }
    assert gate_summary["gates"]["execution_reconciliation"] == {
        "status": "pending_after_manual_execution",
        "evidence_ref": f"execution_reconciliation:pending:{order['order_id']}",
        "source": "execution_reconciliation_runbook",
    }
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manual_ticket_created"
    assert (
        len(db.list_broker_gateway_events_sync(order_id=order["order_id"]))
        == event_count_before
    )


def test_manual_execution_preview_fingerprint_is_stable_and_input_sensitive(
    tmp_path,
) -> None:
    db, order = _confirmed_order(
        tmp_path,
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
    service = BrokerGatewayService(
        db=db,
        controlled_bridge_policy=_controlled_bridge_policy(),
    )
    service.create_manual_ticket(order["order_id"], actor="test")

    first = service.preview_manual_execution_record(
        order["order_id"],
        fill_price="1688.00",
        quantity="100",
        fee="5.00",
        tax="0.00",
        transfer_fee="0.10",
        actor="operator-a",
    )
    same_inputs = service.preview_manual_execution_record(
        order["order_id"],
        fill_price="1688.00",
        quantity="100",
        fee="5.00",
        tax="0.00",
        transfer_fee="0.10",
        actor="operator-b",
    )
    changed_fee = service.preview_manual_execution_record(
        order["order_id"],
        fill_price="1688.00",
        quantity="100",
        fee="5.01",
        tax="0.00",
        transfer_fee="0.10",
        actor="operator-a",
    )

    assert first["preview_fingerprint"].startswith("sha256:")
    assert len(first["preview_fingerprint"]) == len("sha256:") + 64
    assert same_inputs["preview_fingerprint"] == first["preview_fingerprint"]
    assert changed_fee["preview_fingerprint"] != first["preview_fingerprint"]
    assert first["fingerprint_scope"] == (
        "order_id, execution_preview, ledger_entry_draft, "
        "position_cost_preview, controlled_bridge_policy"
    )
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manual_ticket_created"
    assert len(db.list_broker_gateway_events_sync(order_id=order["order_id"])) == 1


def test_manual_execution_evidence_record_requires_matching_preview_fingerprint(
    tmp_path,
) -> None:
    db, order = _confirmed_order(
        tmp_path,
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
    service = BrokerGatewayService(
        db=db,
        controlled_bridge_policy=_controlled_bridge_policy(),
    )
    service.create_manual_ticket(order["order_id"], actor="test")
    preview = service.preview_manual_execution_record(
        order["order_id"],
        fill_price="1688.00",
        quantity="100",
        fee="5.00",
        tax="0.00",
        transfer_fee="0.10",
        actor="operator-a",
    )
    event_count_before = len(
        db.list_broker_gateway_events_sync(order_id=order["order_id"])
    )

    result = service.record_manual_execution_evidence(
        order["order_id"],
        preview_fingerprint=preview["preview_fingerprint"],
        fill_price="1688.00",
        quantity="100",
        fee="5.00",
        tax="0.00",
        transfer_fee="0.10",
        actor="operator-a",
        operator_note="broker client fill reviewed",
    )

    assert result["status"] == "manual_execution_recorded"
    assert result["submitted_to_broker"] is False
    assert result["does_not_mutate_oms"] is True
    assert result["does_not_mutate_production_ledger"] is True
    assert result["preview_fingerprint"] == preview["preview_fingerprint"]
    assert result["execution_preview"]["net_cash_impact"] == "-168805.10"
    assert result["ledger_entry_draft"]["amount"] == "-168805.10"
    assert result["event_id"] is not None
    assert db.get_oms_order_sync(order["order_id"])["status"] == "manual_ticket_created"
    events = db.list_broker_gateway_events_sync(order_id=order["order_id"])
    assert len(events) == event_count_before + 1
    assert events[-1]["event_type"] == "manual_execution_recorded"
    payload = json.loads(events[-1]["payload_json"])
    assert payload["preview_fingerprint"] == preview["preview_fingerprint"]
    assert payload["operator_note"] == "broker client fill reviewed"
    assert payload["submitted_to_broker"] is False
    assert payload["does_not_mutate_oms"] is True
    assert payload["does_not_mutate_production_ledger"] is True
    assert payload["validation"]["required_gate_summary"] == (
        result["validation"]["required_gate_summary"]
    )
    assert payload["validation"]["required_gate_summary"]["gates"]["risk"] == {
        "status": "pass",
        "evidence_ref": "risk:risk-001",
        "source": "oms_gateway_evidence",
    }


def test_manual_execution_evidence_rejects_mismatched_preview_fingerprint(
    tmp_path,
) -> None:
    db, order = _confirmed_order(tmp_path)
    service = BrokerGatewayService(
        db=db,
        controlled_bridge_policy=_controlled_bridge_policy(),
    )
    service.create_manual_ticket(order["order_id"], actor="test")
    event_count_before = len(
        db.list_broker_gateway_events_sync(order_id=order["order_id"])
    )

    try:
        service.record_manual_execution_evidence(
            order["order_id"],
            preview_fingerprint="sha256:not-the-preview",
            fill_price="1688.00",
            quantity="100",
            fee="5.00",
            tax="0.00",
            transfer_fee="0.10",
            actor="operator-a",
        )
    except ValueError as exc:
        assert "preview_fingerprint" in str(exc)
    else:
        raise AssertionError("expected mismatched preview fingerprint rejection")

    assert db.get_oms_order_sync(order["order_id"])["status"] == "manual_ticket_created"
    assert (
        len(db.list_broker_gateway_events_sync(order_id=order["order_id"]))
        == event_count_before
    )


def test_manual_execution_preview_requires_created_manual_ticket(tmp_path) -> None:
    db, order = _confirmed_order(tmp_path)
    service = BrokerGatewayService(db=db)

    try:
        service.preview_manual_execution_record(
            order["order_id"],
            fill_price="1688.00",
            quantity="100",
        )
    except ValueError as exc:
        assert "manual_ticket_created" in str(exc)
    else:
        raise AssertionError("expected manual execution preview to require ticket")

    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    assert db.list_broker_gateway_events_sync(order_id=order["order_id"]) == []


def test_staged_account_facts_query_reads_cash_positions_and_fills_without_mutation(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    service = BrokerGatewayService(db=db)
    _import_broker_trade(Path(db._path), event_id="broker-buy-600519", quantity=100)
    events_before = db.list_broker_gateway_events_sync()

    result = service.query_staged_account_facts()

    assert result["gateway_id"] == "staged_broker_evidence"
    assert result["status"] == "available"
    assert result["query_scope"] == "staged_broker_evidence"
    assert result["submitted_to_broker"] is False
    assert result["can_submit_orders"] is False
    assert result["broker_event_count"] == 1
    assert result["cash_balances"][0]["currency"] == "CNY"
    assert result["cash_balances"][0]["cash_balance"] == "100000.00"
    assert result["positions"][0]["symbol"] == "600519"
    assert result["positions"][0]["quantity"] == "100"
    assert result["positions"][0]["cost_basis"] == "1688.05"
    assert result["fills"][0]["event_id"] == "broker-buy-600519"
    assert result["fills"][0]["side"] == "buy"
    assert db.list_broker_gateway_events_sync() == events_before


def test_staged_fill_query_filters_trade_evidence_without_mutation(tmp_path) -> None:
    db = AppDatabase(tmp_path / "broker-gateway.db")
    db.init_sync()
    service = BrokerGatewayService(db=db)
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
    events_before = db.list_broker_gateway_events_sync()

    result = service.query_staged_fills(symbol="600519", limit=10)

    assert result["schema_version"] == "karkinos.broker_gateway.v1"
    assert result["gateway_id"] == "staged_broker_evidence"
    assert result["status"] == "available"
    assert result["query_scope"] == "staged_broker_fills"
    assert result["submitted_to_broker"] is False
    assert result["can_submit_orders"] is False
    assert result["symbol"] == "600519"
    assert result["fill_count"] == 1
    assert result["fills"][0]["event_id"] == "broker-buy-600519"
    assert result["fills"][0]["symbol"] == "600519"
    assert result["fills"][0]["side"] == "buy"
    assert "This query reads staged broker fill evidence only." in result["limitations"]
    assert db.list_broker_gateway_events_sync() == events_before


def test_manual_ticket_preview_requires_gateway_evidence(tmp_path) -> None:
    db, order = _confirmed_order(tmp_path, gateway_evidence=False)
    service = BrokerGatewayService(db=db)

    try:
        service.preview_manual_ticket(order["order_id"], actor="test")
    except ValueError as exc:
        assert "missing gateway evidence" in str(exc)
        assert "account_truth" in str(exc)
        assert "paper_shadow" in str(exc)
    else:
        raise AssertionError("expected missing gateway evidence to block preview")

    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    assert db.list_broker_gateway_events_sync(order_id=order["order_id"]) == []


def test_manual_ticket_creation_requires_gateway_evidence(tmp_path) -> None:
    db, order = _confirmed_order(tmp_path, gateway_evidence=False)
    service = BrokerGatewayService(db=db)

    try:
        service.create_manual_ticket(order["order_id"], actor="test")
    except ValueError as exc:
        assert "missing gateway evidence" in str(exc)
        assert "account_truth" in str(exc)
        assert "paper_shadow" in str(exc)
    else:
        raise AssertionError(
            "expected missing gateway evidence to block ticket creation"
        )

    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    assert db.list_broker_gateway_events_sync(order_id=order["order_id"]) == []


def test_live_gateway_rejects_submission_by_default(tmp_path) -> None:
    db, order = _confirmed_order(tmp_path)
    service = BrokerGatewayService(db=db)

    try:
        service.submit_live_disabled(order["order_id"], actor="test")
    except ValueError as exc:
        assert "live broker submission is disabled" in str(exc)
    else:
        raise AssertionError("expected live broker submission to be rejected")


def test_live_gateway_rejects_broker_cancel_by_default_without_oms_mutation(
    tmp_path,
) -> None:
    db, order = _confirmed_order(tmp_path)
    service = BrokerGatewayService(db=db)

    try:
        service.cancel_live_disabled(order["order_id"], actor="test")
    except ValueError as exc:
        assert "live broker cancellation is disabled" in str(exc)
    else:
        raise AssertionError("expected live broker cancellation to be rejected")

    assert db.get_oms_order_sync(order["order_id"])["status"] == "manually_confirmed"
    events = db.list_broker_gateway_events_sync(order_id=order["order_id"])
    assert events[-1]["gateway_id"] == "live_disabled"
    assert events[-1]["event_type"] == "live_cancel_rejected"
    assert events[-1]["status"] == "rejected"
    payload = json.loads(events[-1]["payload_json"])
    assert payload["submitted_to_broker"] is False
    assert payload["cancelled_at_broker"] is False
    assert payload["order_status"] == "manually_confirmed"


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
