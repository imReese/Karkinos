from __future__ import annotations

from decimal import Decimal
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
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.db import AppDatabase
from server.routes.automation import create_router
from server.services.execution_reconciliation import ExecutionReconciliationService
from server.services.oms import OmsService
from server.services.trading_controls import TradingControlState


def _client_for_db(
    monkeypatch,
    db: AppDatabase,
    *,
    broker_connectors: list[object] | None = None,
) -> TestClient:
    fake_state = SimpleNamespace(
        db=db,
        config=SimpleNamespace(broker_connectors=broker_connectors or []),
        trading_controls=TradingControlState(db=db),
        hub=None,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def test_automation_status_route_uses_safe_defaults(tmp_path, monkeypatch) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    response = client.get("/api/automation/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["broker_submission_enabled"] is False
    assert payload["default_execution_mode"] == "manual_confirmation"
    assert payload["manual_confirmation_required"] is True
    assert payload["automation_ready"] is True


def test_automation_cockpit_route_includes_runtime_connector_snapshot(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "automation.db")
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
    client = _client_for_db(monkeypatch, db, broker_connectors=[connector])

    response = client.get("/api/automation/cockpit")

    assert response.status_code == 200
    payload = response.json()
    snapshots = payload["runtime_connector_snapshots"]
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot["connector_id"] == "fake-qmt-runtime"
    assert snapshot["query_scope"] == "runtime_readonly_connector_snapshot"
    assert snapshot["position_count"] == 1
    assert snapshot["order_count"] == 1
    assert snapshot["fill_count"] == 1
    assert snapshot["capabilities"]["can_submit_orders"] is False
    assert snapshot["submitted_to_broker"] is False
    assert snapshot["does_not_mutate_production_ledger"] is True
    assert "private-account-id" not in response.text
    assert db.list_broker_gateway_events_sync() == []


def test_automation_policy_route_rejects_live_mode(tmp_path, monkeypatch) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    response = client.put(
        "/api/automation/policies/default",
        json={"broker_submission_enabled": True},
    )

    assert response.status_code == 400
    assert "broker submission is disabled by default" in response.json()["detail"]


def test_market_session_route_runs_explicit_paper_shadow_plan(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    response = client.post(
        "/api/automation/run/market-session",
        json={
            "now": "2026-07-02T10:00:00+08:00",
            "trading_plan": {
                "schema_version": "karkinos.daily_trading_plan.v1",
                "plan_date": "2026-07-02",
                "generated_at": "2026-07-02T09:35:00+08:00",
                "order_intents": [
                    {
                        "intent_id": "intent-1",
                        "strategy_id": "dual_ma",
                        "symbol": "600519",
                        "side": "buy",
                        "asset_class": "stock",
                        "estimated_quantity": 100,
                        "estimated_price": 1688.0,
                    }
                ],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "paper_shadow_completed"
    assert payload["broker_submission_enabled"] is False
    assert payload["does_not_submit_broker_order"] is True


def test_automation_alert_routes_scan_list_and_ack(tmp_path, monkeypatch) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    controls = TradingControlState(db=db)
    controls.set_kill_switch(True, "operator pause")
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=db, trading_controls=controls, hub=None),
    )
    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app)

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
    oms.transition_order(
        order["order_id"],
        to_status="manually_confirmed",
        reason="operator approved paper/shadow evidence",
        actor="test",
    )
    ExecutionReconciliationService(db=db).run_reconciliation(run_date="2026-07-02")

    scan = client.post("/api/automation/alerts/scan")
    assert scan.status_code == 200
    assert scan.json()["open_alert_count"] == 2

    listed = client.get("/api/automation/alerts")
    assert listed.status_code == 200
    first_alert = listed.json()[0]

    ack = client.post(
        f"/api/automation/alerts/{first_alert['id']}/ack",
        json={"actor": "test"},
    )
    assert ack.status_code == 200
    assert ack.json()["status"] == "acknowledged"


def test_automation_alert_scan_route_records_connector_health_alert(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    controls = TradingControlState(db=db)
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(
            db=db,
            config=SimpleNamespace(
                broker_connectors=[
                    SimpleNamespace(
                        connector_id="local-qmt-readonly",
                        connector_type="qmt_readonly",
                        enabled=True,
                        client_path="",
                        account_alias="",
                    )
                ]
            ),
            trading_controls=controls,
            hub=None,
        ),
    )
    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app)

    scan = client.post("/api/automation/alerts/scan")

    assert scan.status_code == 200
    payload = scan.json()
    assert payload["open_alert_count"] == 1
    alert = payload["alerts"][0]
    assert alert["alert_key"] == (
        "broker_connector:local-qmt-readonly:configuration_incomplete"
    )
    assert alert["payload"]["can_submit_orders"] is False
    assert alert["payload"]["submitted_to_broker"] is False


def test_automation_alert_scan_route_records_runtime_connector_degradation_alert(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    scan = client.post(
        "/api/automation/alerts/scan",
        json={
            "connector_health": [
                {
                    "connector_id": "local-ptrade-readonly",
                    "connector_type": "ptrade_readonly",
                    "status": "runtime_degraded",
                    "enabled": True,
                    "message": "Read-only connector heartbeat is stale.",
                    "capabilities": {
                        "can_read_health": True,
                        "can_read_account": True,
                        "can_read_cash": True,
                        "can_read_positions": True,
                        "can_read_orders": True,
                        "can_read_fills": True,
                        "can_submit_orders": False,
                        "can_cancel_orders": False,
                    },
                    "stores_credentials": False,
                    "submitted_to_broker": False,
                    "last_heartbeat_at": "2026-07-02T09:20:00+08:00",
                    "last_error": "heartbeat timeout",
                    "limitations": [
                        "Connector heartbeat is stale; verify local client session manually."
                    ],
                }
            ]
        },
    )

    assert scan.status_code == 200
    payload = scan.json()
    assert payload["open_alert_count"] == 1
    alert = payload["alerts"][0]
    assert alert["alert_key"] == (
        "broker_connector:local-ptrade-readonly:runtime_degraded"
    )
    assert alert["category"] == "broker_connector_health"
    assert alert["payload"]["connector_status"] == "runtime_degraded"
    assert alert["payload"]["last_error"] == "heartbeat timeout"
    assert alert["payload"]["can_submit_orders"] is False
    assert alert["payload"]["submitted_to_broker"] is False
    assert alert["payload"]["does_not_submit_broker_order"] is True


def test_automation_alert_scan_route_records_risk_blocker_alert(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    scan = client.post(
        "/api/automation/alerts/scan",
        json={
            "trading_plan": {
                "schema_version": "karkinos.daily_trading_plan.v1",
                "plan_date": "2026-07-02",
                "conclusion_status": "risk_blocked",
                "blocked_count": 1,
                "blocker_summary": [
                    {
                        "category": "risk",
                        "target": "risk",
                        "count": 1,
                        "reasons": ["cash reserve would fall below min_cash_reserve"],
                    }
                ],
                "broker_submission_enabled": False,
            }
        },
    )

    assert scan.status_code == 200
    payload = scan.json()
    assert payload["open_alert_count"] == 1
    alert = payload["alerts"][0]
    assert alert["alert_key"] == "daily_trading_plan:2026-07-02:risk_blocked"
    assert alert["category"] == "risk_gate"
    assert alert["payload"]["risk_blocker_count"] == 1
    assert alert["payload"]["does_not_submit_broker_order"] is True


def test_automation_alert_scan_route_records_stale_market_data_alert(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    scan = client.post(
        "/api/automation/alerts/scan",
        json={
            "market_health": {
                "source_health": "stale",
                "latest_quote_timestamp": "2026-07-02T09:25:00+08:00",
                "stale_symbols_count": 1,
                "stale_symbols_sample": ["600519"],
                "provider_name": "akshare",
                "provider_status": "stale",
                "persistent_cache_status": "available",
                "next_action": "refresh_quotes",
            }
        },
    )

    assert scan.status_code == 200
    payload = scan.json()
    assert payload["open_alert_count"] == 1
    alert = payload["alerts"][0]
    assert alert["alert_key"] == "market_data:2026-07-02T09:25:00+08:00:stale"
    assert alert["category"] == "market_data"
    assert alert["payload"]["stale_symbols_count"] == 1
    assert alert["payload"]["does_not_submit_broker_order"] is True


def test_automation_alert_scan_route_records_account_truth_mismatch_alert(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    scan = client.post(
        "/api/automation/alerts/scan",
        json={
            "account_truth": {
                "schema_version": "karkinos.account_truth.score.v1",
                "gate_status": "degraded",
                "score": 65,
                "latest_report_id": "acct-report-2026-07-02",
                "cash_status": "warning",
                "position_status": "pass",
                "data_freshness_status": "stale",
                "unresolved_mismatch_count": 1,
                "required_actions": ["provide_cash_snapshot"],
                "blocking_reasons": [],
                "limitations": [
                    "Account truth is degraded by stale account or market evidence."
                ],
            }
        },
    )

    assert scan.status_code == 200
    payload = scan.json()
    assert payload["open_alert_count"] == 1
    alert = payload["alerts"][0]
    assert alert["alert_key"] == "account_truth:acct-report-2026-07-02:degraded"
    assert alert["category"] == "account_truth"
    assert alert["payload"]["unresolved_mismatch_count"] == 1
    assert alert["payload"]["requires_manual_review"] is True
    assert alert["payload"]["does_not_mutate_production_ledger"] is True


def test_automation_alert_scan_route_records_paper_shadow_divergence_alert(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    scan = client.post(
        "/api/automation/alerts/scan",
        json={
            "paper_shadow_run": {
                "schema_version": "karkinos.paper_shadow_run.v1",
                "run_id": "shadow:2026-07-02:diverged",
                "plan_date": "2026-07-02",
                "status": "review_required",
                "divergence_status": "review_required",
                "order_intent_count": 1,
                "simulated_order_count": 0,
                "simulated_fill_count": 0,
                "next_manual_review_step": "review_shadow_divergence",
                "divergence_summary": {
                    "missing_simulation_count": 1,
                    "diverged_order_count": 0,
                },
                "limitations": ["order_intent[1] missing estimated_price"],
                "does_not_submit_broker_order": True,
                "does_not_mutate_production_ledger": True,
            }
        },
    )

    assert scan.status_code == 200
    payload = scan.json()
    assert payload["open_alert_count"] == 1
    alert = payload["alerts"][0]
    assert alert["alert_key"] == (
        "paper_shadow_run:shadow:2026-07-02:diverged:review_required"
    )
    assert alert["category"] == "paper_shadow_divergence"
    assert alert["payload"]["missing_simulation_count"] == 1
    assert alert["payload"]["requires_manual_review"] is True
    assert alert["payload"]["does_not_submit_broker_order"] is True


def test_automation_cockpit_route_returns_read_only_summary(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    controls = TradingControlState(db=db)
    controls.set_kill_switch(True, "operator pause")
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=db, trading_controls=controls, hub=None),
    )
    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app)

    response = client.get("/api/automation/cockpit")

    assert response.status_code == 200
    payload = response.json()
    assert payload["broker_submission_enabled"] is False
    assert payload["automation_status"]["kill_switch_enabled"] is True
    gateways = {item["gateway_id"]: item for item in payload["gateways"]}
    assert {"manual_ticket", "staged_broker_evidence", "live_disabled"}.issubset(
        gateways
    )
    assert gateways["staged_broker_evidence"]["can_read_account_facts"] is True
    assert gateways["staged_broker_evidence"]["can_submit_orders"] is False
