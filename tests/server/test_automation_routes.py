from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.db import AppDatabase
from server.routes.automation import create_router
from server.services.execution_reconciliation import ExecutionReconciliationService
from server.services.oms import OmsService
from server.services.trading_controls import TradingControlState


class _ConnectorWouldFailIfQueried:
    connector_id = "fixture-readonly-edge"
    connector_type = "deterministic_fixture"

    def read_account_snapshot(self):
        raise AssertionError("cockpit GET must not call an edge adapter")


class _RunningTask:
    def done(self) -> bool:
        return False

    def cancelled(self) -> bool:
        return False

    def exception(self):
        return None


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
    assert payload["schema_version"] == "karkinos.automation_status.v1"
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
    connector = _ConnectorWouldFailIfQueried()
    client = _client_for_db(monkeypatch, db, broker_connectors=[connector])
    with sqlite3.connect(db._path) as conn:
        before = list(conn.iterdump())

    response = client.get("/api/automation/cockpit")

    with sqlite3.connect(db._path) as conn:
        after = list(conn.iterdump())
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "karkinos.automation_cockpit.v4"
    assert "runtime_connector_snapshots" not in payload
    assert "runtime_connector_snapshot_status" not in payload
    registration = payload["connector_registrations"][0]
    assert registration["connector_id"] == "fixture-readonly-edge"
    assert registration["provider_contact_performed"] is False
    assert registration["explicit_ingestion_required"] is True
    assert registration["can_submit_orders"] is False
    assert registration["can_cancel_orders"] is False
    assert payload["controlled_execution"]["provider_contact_performed"] is False
    assert payload["daily_candidate_trial"]["status"] == (
        "collecting_forward_operating_evidence"
    )
    assert payload["daily_candidate_trial"]["broker_submission_enabled"] is False
    assert payload["daily_candidate_trial"]["authorizes_execution"] is False
    runtime = payload["daily_candidate_runtime"]
    assert runtime["status"] == "monitor_failed_closed"
    assert runtime["financial_readiness_claimed"] is False
    assert runtime["broker_submission_enabled"] is False
    preflight = payload["daily_candidate_financial_preflight"]
    assert preflight["status"] == "no_action"
    assert preflight["eligible_to_create_manual_ticket"] is False
    assert preflight["provider_contact_performed"] is False
    assert preflight["database_writes_performed"] is False
    assert preflight["broker_submission_enabled"] is False
    assert preflight["authorizes_execution"] is False
    assert "qmt" not in response.text.lower()
    assert db.list_broker_gateway_events_sync() == []
    assert before == after


def test_automation_cockpit_route_reports_exact_running_daily_candidate_task(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    fake_state = SimpleNamespace(
        db=db,
        config=SimpleNamespace(broker_connectors=[], live_auto_start=True),
        trading_controls=TradingControlState(db=db),
        daily_decision_evidence_task=_RunningTask(),
        hub=None,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    app = FastAPI()
    app.include_router(create_router())

    response = TestClient(app).get("/api/automation/cockpit")

    assert response.status_code == 200
    runtime = response.json()["daily_candidate_runtime"]
    assert runtime["background_monitor_configured"] is True
    assert runtime["background_monitor_running"] is True
    assert runtime["monitor_task_state"] == "running"
    assert runtime["financial_readiness_claimed"] is False
    assert runtime["provider_contact_performed"] is False
    assert runtime["database_writes_performed"] is False
    assert runtime["broker_submission_enabled"] is False
    assert runtime["authorizes_execution"] is False


def test_automation_cockpit_route_projects_current_financial_preflight(
    tmp_path,
    monkeypatch,
) -> None:
    from server.services.daily_decision_evidence_automation import (
        unavailable_daily_candidate_financial_preflight,
    )

    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    calls: list[str] = []

    async def read_current_plan(_state):
        calls.append("plan")
        return {"decision_date": "2026-07-17"}, {"plan_date": "2026-07-17"}

    def reviewed_fees(_state, *, as_of_date):
        calls.append(f"fees:{as_of_date}")
        return {"status": "missing"}

    def execution_closure(_db):
        calls.append("closure")
        return {"status": "not_required"}

    projected = unavailable_daily_candidate_financial_preflight(
        blocker="fixture_financial_preflight_blocker"
    )

    def financial_preflight(**kwargs):
        calls.append("project")
        assert kwargs["reviewed_fee_schedule"] == {"status": "missing"}
        assert kwargs["execution_closure"] == {"status": "not_required"}
        return projected

    monkeypatch.setattr(
        "server.routes.operations._current_decision_and_trading_plan",
        read_current_plan,
    )
    monkeypatch.setattr(
        "server.services.reviewed_fee_schedule."
        "build_reviewed_fee_schedule_review_status",
        reviewed_fees,
    )
    monkeypatch.setattr(
        "server.services.daily_candidate_execution_closure."
        "build_daily_candidate_execution_closure",
        execution_closure,
    )
    monkeypatch.setattr(
        "server.services.daily_decision_evidence_automation."
        "project_daily_candidate_financial_preflight",
        financial_preflight,
    )

    response = _client_for_db(monkeypatch, db).get("/api/automation/cockpit")

    assert response.status_code == 200
    payload = response.json()
    runtime_date = payload["daily_candidate_runtime"]["run_date"]
    assert calls == ["plan", f"fees:{runtime_date}", "closure", "project"]
    preflight = payload["daily_candidate_financial_preflight"]
    assert preflight["financial_blockers"] == ["fixture_financial_preflight_blocker"]
    assert preflight["eligible_to_create_manual_ticket"] is False
    assert preflight["authorizes_execution"] is False


def test_automation_cockpit_get_projects_blocked_current_review_without_alert_write(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)
    oms = OmsService(db=db)
    order = oms.create_order_intent(
        intent_key="daily:2026-07-17:510300:buy",
        symbol="510300.SH",
        side="buy",
        asset_class="fund",
        quantity=100,
        order_type="market",
        limit_price=None,
        source="daily_trading_plan",
        source_ref="shadow:2026-07-17:fixture",
    )
    oms.transition_order(
        order["order_id"],
        to_status="manually_confirmed",
        reason="operator confirmed fixture evidence",
        actor="test",
    )

    response = client.get("/api/automation/cockpit")

    assert response.status_code == 200
    current = response.json()["current_per_order_reviews"]
    assert current["status"] == "blocked_review"
    assert current["candidate_count"] == 1
    assert current["blocked_review_count"] == 1
    assert current["provider_contact_performed"] is False
    assert current["authorizes_execution"] is False
    assert db.list_automation_alerts_sync() == []


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


def test_daily_candidate_trial_routes_are_evidence_only(tmp_path, monkeypatch) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    status_response = client.get("/api/automation/daily-candidate/trial")

    assert status_response.status_code == 200
    status = status_response.json()
    assert status["eligible_for_human_go_no_go_review"] is False
    assert status["qualifying_trading_day_count"] == 0
    assert status["simulated_order_count"] == 0
    assert status["automatic_order_submission_enabled"] is False
    assert status["automatic_capital_scaling_enabled"] is False

    review_response = client.post(
        "/api/automation/daily-candidate/trial/reviews",
        json={
            "expected_trial_fingerprint": status["trial_fingerprint"],
            "decision": "continue_paper_shadow",
            "reviewed_by": "owner",
            "note": "Continue collecting forward evidence.",
            "confirmation": (
                "record_daily_candidate_trial_review_without_trade_or_capital_authority"
            ),
        },
    )

    assert review_response.status_code == 200
    review = review_response.json()
    assert review["status"] == "recorded"
    assert review["authorizes_execution"] is False
    assert review["changes_capital_authority"] is False
    listed = client.get("/api/automation/daily-candidate/trial/reviews")
    assert listed.status_code == 200
    assert listed.json()[0]["review_id"] == review["review_id"]


def test_daily_candidate_run_rejects_caller_supplied_trade_facts(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    response = client.post(
        "/api/automation/run/daily-candidate",
        json={
            "trading_plan": {"symbol": "600519", "quantity": 100},
            "account_equity": 20000,
        },
    )

    assert response.status_code == 422
    assert "extra_forbidden" in response.text


def test_daily_candidate_run_uses_canonical_bound_service(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    class _Service:
        async def run_once(self):
            return {
                "schema_version": "karkinos.daily_decision_evidence_automation.v3",
                "decision_outcome": "no_action",
                "no_action_reasons": ["no_strategy_action"],
                "broker_submission_enabled": False,
                "does_not_submit_broker_order": True,
            }

    monkeypatch.setattr(
        "server.services.daily_decision_evidence_automation."
        "build_daily_decision_evidence_automation_service",
        lambda state: _Service(),
    )

    response = client.post("/api/automation/run/daily-candidate", json={})

    assert response.status_code == 200
    assert response.json()["decision_outcome"] == "no_action"
    assert response.json()["does_not_submit_broker_order"] is True


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
    assert scan.json()["open_alert_count"] == 3
    current_alert = next(
        alert
        for alert in scan.json()["alerts"]
        if alert["category"] == "per_order_evidence_review"
    )
    assert current_alert["source_ref"] == order["order_id"]
    assert current_alert["payload"]["provider_contact_performed"] is False
    assert current_alert["payload"]["does_not_submit_broker_order"] is True
    assert current_alert["payload"]["does_not_cancel_broker_order"] is True
    assert current_alert["payload"]["does_not_mutate_oms"] is True
    assert current_alert["payload"]["does_not_mutate_production_ledger"] is True
    assert current_alert["payload"]["authorizes_execution"] is False

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
                        connector_id="fixture-readonly-edge",
                        connector_type="deterministic_fixture",
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
        "broker_connector:fixture-readonly-edge:collector_evidence_missing"
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
                    "connector_id": "local-fixture-readonly",
                    "connector_type": "deterministic_readonly",
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
        "broker_connector:local-fixture-readonly:runtime_degraded"
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
    assert payload["schema_version"] == "karkinos.automation_cockpit.v4"
    assert payload["broker_submission_enabled"] is False
    assert payload["automation_status"]["kill_switch_enabled"] is True
    gateways = {item["gateway_id"]: item for item in payload["gateways"]}
    assert {"manual_ticket", "staged_broker_evidence", "live_disabled"}.issubset(
        gateways
    )
    assert gateways["staged_broker_evidence"]["can_read_account_facts"] is True
    assert gateways["staged_broker_evidence"]["can_submit_orders"] is False
    assert "runtime_connector_snapshots" not in payload
    assert "runtime_connector_snapshot_status" not in payload
    assert payload["controlled_execution"]["reads_persisted_facts_only"] is True
    assert payload["controlled_execution"]["provider_contact_performed"] is False
    current_reviews = payload["current_per_order_reviews"]
    assert current_reviews["status"] == "no_current_candidates"
    assert current_reviews["candidate_count"] == 0
    assert current_reviews["review_ready_count"] == 0
    assert current_reviews["blocked_review_count"] == 0
    assert current_reviews["reads_persisted_facts_only"] is True
    assert current_reviews["provider_contact_performed"] is False
    assert current_reviews["broker_submission_enabled"] is False
    assert current_reviews["broker_cancel_enabled"] is False
    assert current_reviews["authorizes_execution"] is False
