from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from account_truth.broker_connector import (
    BrokerCashFact,
    BrokerConnectorCapabilities,
    BrokerConnectorHealth,
    BrokerConnectorSnapshot,
    FakeReadOnlyBrokerConnector,
)
from server.db import AppDatabase
from server.services.automation_alerts import AutomationAlertService
from server.services.broker_gateway import BrokerGatewayService
from server.services.execution_reconciliation import ExecutionReconciliationService
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


def _confirmed_order(
    db: AppDatabase,
    *,
    gateway_evidence: bool = False,
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


def test_alert_scan_records_kill_switch_and_reconciliation_gap(tmp_path) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
    db.init_sync()
    controls = TradingControlState(db=db)
    controls.set_kill_switch(True, "operator pause")
    order = _confirmed_order(db)
    ExecutionReconciliationService(db=db).run_reconciliation(run_date="2026-07-02")
    service = AutomationAlertService(db=db, trading_controls=controls)

    result = service.scan()

    assert result["open_alert_count"] == 2
    by_key = {alert["alert_key"]: alert for alert in result["alerts"]}
    assert by_key["kill_switch:enabled"]["severity"] == "critical"
    gap_key = f"execution_reconciliation:{order['order_id']}:gateway_action_missing"
    assert by_key[gap_key]["severity"] == "warning"
    assert by_key[gap_key]["status"] == "open"


def test_alert_scan_preserves_manual_execution_reconciliation_evidence(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
    db.init_sync()
    order = _confirmed_order(db, gateway_evidence=True)
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
    ExecutionReconciliationService(db=db).run_reconciliation(run_date="2026-07-02")
    service = AutomationAlertService(db=db, trading_controls=None)

    result = service.scan()

    assert result["open_alert_count"] == 1
    alert = result["alerts"][0]
    assert alert["alert_key"] == (
        f"execution_reconciliation:{order['order_id']}:manual_execution_recorded"
    )
    assert alert["severity"] == "warning"
    assert alert["category"] == "execution_reconciliation"
    assert alert["title"] == "Manual execution evidence requires reconciliation review"
    assert "Manual execution evidence is recorded" in alert["detail"]
    assert "no broker order was submitted" in alert["detail"]
    assert alert["payload"]["item_status"] == "manual_execution_recorded"
    assert (
        alert["payload"]["suggested_action"]
        == "review_manual_execution_and_import_broker_statement"
    )
    assert alert["payload"]["gateway_event_count"] == 2
    summary = alert["payload"]["manual_execution_evidence_summary"]
    assert summary["event_ids"] == [record["event_id"]]
    assert summary["preview_fingerprint"] == preview["preview_fingerprint"]
    assert summary["gross_amount"] == "168800.00"
    assert summary["fee"] == "5.00"
    assert summary["tax"] == "0.00"
    assert summary["net_cash_impact"] == "-168805.00"
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
    assert alert["payload"]["requires_manual_review"] is True
    assert alert["payload"]["does_not_submit_broker_order"] is True
    assert alert["payload"]["does_not_mutate_oms"] is True
    assert alert["payload"]["does_not_mutate_production_ledger"] is True


def test_alert_scan_records_failed_paper_shadow_automation_run(tmp_path) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
    db.init_sync()
    db.upsert_automation_run_sync(
        {
            "run_id": "automation:daily-paper-shadow:2026-07-02",
            "run_type": "daily_paper_shadow",
            "run_date": "2026-07-02",
            "status": "paper_shadow_failed",
            "execution_mode": "paper_shadow",
            "started_at": "2026-07-02T09:35:00+08:00",
            "finished_at": "2026-07-02T09:36:00+08:00",
            "source_ref": "shadow:2026-07-02:abc",
            "payload": {
                "schema_version": "karkinos.automation_run.v1",
                "paper_shadow_run_id": "shadow:2026-07-02:abc",
                "paper_shadow_status": "failed",
                "retry_state": {
                    "attempt": 1,
                    "max_attempts": 2,
                    "retryable": True,
                },
                "limitations": [
                    "Paper/shadow run failed; no broker order was submitted."
                ],
                "does_not_submit_broker_order": True,
                "does_not_mutate_production_ledger": True,
            },
        }
    )
    service = AutomationAlertService(db=db, trading_controls=None)

    result = service.scan()

    assert result["open_alert_count"] == 1
    alert = result["alerts"][0]
    assert alert["alert_key"] == (
        "automation_run:automation:daily-paper-shadow:2026-07-02:" "paper_shadow_failed"
    )
    assert alert["severity"] == "warning"
    assert alert["category"] == "automation_run"
    assert alert["title"] == "Paper/shadow automation run failed"
    assert alert["source"] == "automation_runs"
    assert alert["source_ref"] == "automation:daily-paper-shadow:2026-07-02"
    assert "no broker order was submitted" in alert["detail"]
    assert alert["payload"]["run_status"] == "paper_shadow_failed"
    assert alert["payload"]["execution_mode"] == "paper_shadow"
    assert alert["payload"]["retry_state"] == {
        "attempt": 1,
        "max_attempts": 2,
        "retryable": True,
    }
    assert alert["payload"]["does_not_submit_broker_order"] is True
    assert alert["payload"]["does_not_mutate_production_ledger"] is True


def test_alert_scan_records_incomplete_readonly_connector_health(tmp_path) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
    db.init_sync()
    connector = SimpleNamespace(
        connector_id="local-qmt-readonly",
        connector_type="qmt_readonly",
        enabled=True,
        client_path="",
        account_alias="",
    )
    service = AutomationAlertService(
        db=db,
        trading_controls=None,
        broker_connectors=[connector],
    )

    result = service.scan()

    assert result["open_alert_count"] == 1
    alert = result["alerts"][0]
    assert alert["alert_key"] == (
        "broker_connector:local-qmt-readonly:configuration_incomplete"
    )
    assert alert["severity"] == "warning"
    assert alert["category"] == "broker_connector_health"
    assert alert["title"] == "Broker connector health requires review"
    assert alert["source"] == "broker_gateway"
    assert alert["source_ref"] == "local-qmt-readonly"
    assert "requires local client path and account alias" in alert["detail"]
    assert alert["payload"]["connector_id"] == "local-qmt-readonly"
    assert alert["payload"]["connector_status"] == "configuration_incomplete"
    assert alert["payload"]["capability_scope"] == ("local_readonly_connector_contract")
    assert alert["payload"]["can_preview_orders"] is False
    assert alert["payload"]["can_export_tickets"] is False
    assert alert["payload"]["can_dry_run_orders"] is False
    assert alert["payload"]["can_submit_orders"] is False
    assert alert["payload"]["can_cancel_orders"] is False
    assert alert["payload"]["stores_credentials"] is False
    assert alert["payload"]["submitted_to_broker"] is False


def test_alert_scan_records_runtime_connector_degradation(tmp_path) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
    db.init_sync()
    service = AutomationAlertService(
        db=db,
        trading_controls=None,
        connector_health=[
            {
                "connector_id": "local-qmt-readonly",
                "connector_type": "qmt_readonly",
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
                    "can_preview_orders": False,
                    "can_export_tickets": False,
                    "can_dry_run_orders": False,
                    "can_submit_orders": False,
                    "can_cancel_orders": False,
                },
                "capability_scope": "local_readonly_connector_contract",
                "stores_credentials": False,
                "submitted_to_broker": False,
                "last_heartbeat_at": "2026-07-02T09:20:00+08:00",
                "last_error": "heartbeat timeout",
                "limitations": [
                    "Connector heartbeat is stale; verify local client session manually."
                ],
            }
        ],
    )

    result = service.scan()

    assert result["open_alert_count"] == 1
    alert = result["alerts"][0]
    assert alert["alert_key"] == "broker_connector:local-qmt-readonly:runtime_degraded"
    assert alert["severity"] == "warning"
    assert alert["category"] == "broker_connector_health"
    assert alert["title"] == "Broker connector health requires review"
    assert alert["source"] == "broker_gateway"
    assert alert["source_ref"] == "local-qmt-readonly"
    assert "heartbeat is stale" in alert["detail"]
    assert alert["payload"]["connector_id"] == "local-qmt-readonly"
    assert alert["payload"]["connector_status"] == "runtime_degraded"
    assert alert["payload"]["last_heartbeat_at"] == "2026-07-02T09:20:00+08:00"
    assert alert["payload"]["last_error"] == "heartbeat timeout"
    assert alert["payload"]["capability_scope"] == ("local_readonly_connector_contract")
    assert alert["payload"]["can_read_account"] is True
    assert alert["payload"]["can_preview_orders"] is False
    assert alert["payload"]["can_export_tickets"] is False
    assert alert["payload"]["can_dry_run_orders"] is False
    assert alert["payload"]["can_submit_orders"] is False
    assert alert["payload"]["can_cancel_orders"] is False
    assert alert["payload"]["stores_credentials"] is False
    assert alert["payload"]["submitted_to_broker"] is False
    assert alert["payload"]["requires_manual_review"] is True
    assert alert["payload"]["does_not_submit_broker_order"] is True


def test_alert_scan_polls_runtime_readonly_connector_snapshot(tmp_path) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
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
    service = AutomationAlertService(
        db=db,
        trading_controls=None,
        broker_connectors=[connector],
    )

    result = service.scan()

    assert result["open_alert_count"] == 1
    alert = result["alerts"][0]
    assert alert["alert_key"] == "broker_connector:fake-qmt-runtime:runtime_degraded"
    assert alert["category"] == "broker_connector_health"
    assert alert["source"] == "broker_gateway"
    assert alert["source_ref"] == "fake-qmt-runtime"
    assert "heartbeat is stale" in alert["detail"]
    assert alert["payload"]["connector_id"] == "fake-qmt-runtime"
    assert alert["payload"]["connector_status"] == "runtime_degraded"
    assert alert["payload"]["capability_scope"] == (
        "runtime_readonly_connector_snapshot"
    )
    assert alert["payload"]["last_heartbeat_at"] == "2026-07-02T09:30:00+08:00"
    assert alert["payload"]["last_error"] == "Read-only connector heartbeat is stale."
    assert alert["payload"]["can_read_account"] is True
    assert alert["payload"]["can_read_cash"] is True
    assert alert["payload"]["can_preview_orders"] is False
    assert alert["payload"]["can_export_tickets"] is False
    assert alert["payload"]["can_dry_run_orders"] is False
    assert alert["payload"]["can_submit_orders"] is False
    assert alert["payload"]["can_cancel_orders"] is False
    assert alert["payload"]["stores_credentials"] is False
    assert alert["payload"]["submitted_to_broker"] is False
    assert alert["payload"]["does_not_submit_broker_order"] is True
    assert "private-account-id" not in alert["payload_json"]


def test_alert_scan_records_daily_plan_risk_blockers(tmp_path) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
    db.init_sync()
    service = AutomationAlertService(
        db=db,
        trading_controls=None,
        trading_plan={
            "schema_version": "karkinos.daily_trading_plan.v1",
            "plan_date": "2026-07-02",
            "conclusion_status": "risk_blocked",
            "blocked_count": 2,
            "blocker_summary": [
                {
                    "category": "risk",
                    "target": "risk",
                    "count": 2,
                    "reasons": [
                        "cash reserve would fall below min_cash_reserve",
                        "concentration limit exceeded",
                    ],
                }
            ],
            "broker_submission_enabled": False,
        },
    )

    result = service.scan()

    assert result["open_alert_count"] == 1
    alert = result["alerts"][0]
    assert alert["alert_key"] == "daily_trading_plan:2026-07-02:risk_blocked"
    assert alert["severity"] == "warning"
    assert alert["category"] == "risk_gate"
    assert alert["title"] == "Daily trading plan is blocked by risk"
    assert alert["source"] == "daily_trading_plan"
    assert alert["source_ref"] == "2026-07-02"
    assert "cash reserve would fall below min_cash_reserve" in alert["detail"]
    assert alert["payload"]["blocked_count"] == 2
    assert alert["payload"]["risk_blocker_count"] == 2
    assert alert["payload"]["risk_reasons"] == [
        "cash reserve would fall below min_cash_reserve",
        "concentration limit exceeded",
    ]
    assert alert["payload"]["broker_submission_enabled"] is False
    assert alert["payload"]["does_not_submit_broker_order"] is True
    assert alert["payload"]["requires_manual_review"] is True


def test_alert_scan_records_stale_market_data_health(tmp_path) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
    db.init_sync()
    service = AutomationAlertService(
        db=db,
        trading_controls=None,
        market_health={
            "source_health": "stale",
            "latest_quote_timestamp": "2026-07-02T09:25:00+08:00",
            "stale_symbols_count": 2,
            "stale_symbols_sample": ["600519", "510300"],
            "provider_name": "akshare",
            "provider_status": "stale",
            "provider_last_error": None,
            "next_action": "refresh_quotes",
            "persistent_cache_status": "available",
        },
    )

    result = service.scan()

    assert result["open_alert_count"] == 1
    alert = result["alerts"][0]
    assert alert["alert_key"] == "market_data:2026-07-02T09:25:00+08:00:stale"
    assert alert["severity"] == "warning"
    assert alert["category"] == "market_data"
    assert alert["title"] == "Market data freshness requires review"
    assert alert["source"] == "market_data"
    assert alert["source_ref"] == "2026-07-02T09:25:00+08:00"
    assert "600519" in alert["detail"]
    assert alert["payload"]["source_health"] == "stale"
    assert alert["payload"]["stale_symbols_count"] == 2
    assert alert["payload"]["stale_symbols_sample"] == ["600519", "510300"]
    assert alert["payload"]["provider_name"] == "akshare"
    assert alert["payload"]["persistent_cache_status"] == "available"
    assert alert["payload"]["next_action"] == "refresh_quotes"
    assert alert["payload"]["does_not_submit_broker_order"] is True
    assert alert["payload"]["requires_manual_review"] is True


def test_alert_scan_records_account_truth_mismatch(tmp_path) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
    db.init_sync()
    service = AutomationAlertService(
        db=db,
        trading_controls=None,
        account_truth={
            "schema_version": "karkinos.account_truth.score.v1",
            "gate_status": "blocked",
            "score": 40,
            "latest_report_id": "acct-report-2026-07-02",
            "cash_status": "pass",
            "position_status": "mismatch",
            "fee_status": "pass",
            "cost_basis_status": "mismatch",
            "data_freshness_status": "fresh",
            "unresolved_mismatch_count": 2,
            "required_actions": [
                "review_position_difference",
                "review_cost_basis_difference",
            ],
            "blocking_reasons": [
                "unresolved_position_difference",
                "unresolved_cost_basis_difference",
            ],
            "limitations": [
                "Unresolved reconciliation items require review before trusted use."
            ],
        },
    )

    result = service.scan()

    assert result["open_alert_count"] == 1
    alert = result["alerts"][0]
    assert alert["alert_key"] == "account_truth:acct-report-2026-07-02:blocked"
    assert alert["severity"] == "warning"
    assert alert["category"] == "account_truth"
    assert alert["title"] == "Account truth requires review"
    assert alert["source"] == "account_truth"
    assert alert["source_ref"] == "acct-report-2026-07-02"
    assert "unresolved_position_difference" in alert["detail"]
    assert alert["payload"]["gate_status"] == "blocked"
    assert alert["payload"]["score"] == 40
    assert alert["payload"]["unresolved_mismatch_count"] == 2
    assert alert["payload"]["required_actions"] == [
        "review_position_difference",
        "review_cost_basis_difference",
    ]
    assert alert["payload"]["blocking_reasons"] == [
        "unresolved_position_difference",
        "unresolved_cost_basis_difference",
    ]
    assert alert["payload"]["does_not_submit_broker_order"] is True
    assert alert["payload"]["does_not_mutate_production_ledger"] is True
    assert alert["payload"]["requires_manual_review"] is True


def test_alert_scan_records_paper_shadow_order_divergence(tmp_path) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
    db.init_sync()
    service = AutomationAlertService(
        db=db,
        trading_controls=None,
        paper_shadow_run={
            "schema_version": "karkinos.paper_shadow_run.v1",
            "run_id": "shadow:2026-07-02:diverged",
            "plan_date": "2026-07-02",
            "status": "diverged",
            "divergence_status": "diverged",
            "order_intent_count": 2,
            "simulated_order_count": 2,
            "simulated_fill_count": 1,
            "next_manual_review_step": "resolve_shadow_divergence",
            "limitations": ["Paper/shadow rejected one order in simulation."],
            "evidence_refs": [
                "paper_order:SHADOW-1",
                "paper_fill:SHADOW-1-FILL-1",
            ],
            "divergence_summary": {
                "missing_simulation_count": 0,
                "diverged_order_count": 1,
                "next_manual_review_step": "resolve_shadow_divergence",
            },
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        },
    )

    result = service.scan()

    assert result["open_alert_count"] == 1
    alert = result["alerts"][0]
    assert alert["alert_key"] == "paper_shadow_run:shadow:2026-07-02:diverged:diverged"
    assert alert["severity"] == "warning"
    assert alert["category"] == "paper_shadow_divergence"
    assert alert["title"] == "Paper/shadow divergence requires review"
    assert alert["source"] == "paper_shadow_run"
    assert alert["source_ref"] == "shadow:2026-07-02:diverged"
    assert "resolve_shadow_divergence" in alert["detail"]
    assert alert["payload"]["run_id"] == "shadow:2026-07-02:diverged"
    assert alert["payload"]["divergence_status"] == "diverged"
    assert alert["payload"]["diverged_order_count"] == 1
    assert alert["payload"]["missing_simulation_count"] == 0
    assert alert["payload"]["next_manual_review_step"] == "resolve_shadow_divergence"
    assert alert["payload"]["evidence_refs"] == [
        "paper_order:SHADOW-1",
        "paper_fill:SHADOW-1-FILL-1",
    ]
    assert alert["payload"]["does_not_submit_broker_order"] is True
    assert alert["payload"]["does_not_mutate_production_ledger"] is True
    assert alert["payload"]["requires_manual_review"] is True


def test_alert_acknowledgement_marks_alert_acknowledged(tmp_path) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
    db.init_sync()
    controls = TradingControlState(db=db)
    controls.set_kill_switch(True, "operator pause")
    service = AutomationAlertService(db=db, trading_controls=controls)
    alert = service.scan()["alerts"][0]

    acknowledged = service.acknowledge(alert["id"], actor="test")

    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["acknowledged_by"] == "test"
    assert service.list_alerts(status="open") == []
