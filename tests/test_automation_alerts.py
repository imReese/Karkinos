from __future__ import annotations

from types import SimpleNamespace

from server.db import AppDatabase
from server.services.automation_alerts import AutomationAlertService
from server.services.broker_gateway import BrokerGatewayService
from server.services.execution_reconciliation import ExecutionReconciliationService
from server.services.oms import OmsService
from server.services.trading_controls import TradingControlState


class _ConnectorWouldFailIfQueried:
    connector_id = "fixture-readonly-edge"
    connector_type = "deterministic_fixture"
    enabled = True

    def read_account_snapshot(self):
        raise AssertionError("alert scan must not call an edge adapter")


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


def _current_per_order_source(candidates: list[dict]) -> dict:
    return {
        "schema_version": "karkinos.current_per_order_confirmation_candidates.v1",
        "candidate_count": len(candidates),
        "candidates": candidates,
        "truncated": False,
        "reads_persisted_facts_only": True,
        "provider_contact_performed": False,
        "runtime_connector_query_performed": False,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_mutate_risk": True,
        "does_not_mutate_kill_switch": True,
        "does_not_change_capital_authority": True,
        "broker_submission_enabled": False,
        "broker_cancel_enabled": False,
        "authorizes_execution": False,
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


def test_alert_scan_escalates_unknown_controlled_submission_to_critical(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
    db.init_sync()
    db.upsert_execution_reconciliation_run_sync(
        run_id="execution-reconciliation:2026-07-13",
        run_date="2026-07-13",
        status="open_items",
        item_count=1,
        open_item_count=1,
        payload={"schema_version": "karkinos.execution_reconciliation.v1"},
        items=[
            {
                "order_id": "OMS-CONTROLLED-1",
                "item_status": "controlled_submission_unknown",
                "suggested_action": "recover_controlled_submission_by_query",
                "gateway_event_count": 0,
                "broker_event_count": 0,
                "detail": "Outcome unknown; query only and never resubmit.",
                "payload": {
                    "controlled_submission_evidence_summary": {
                        "schema_version": (
                            "karkinos.controlled_submission_reconciliation.v1"
                        ),
                        "submit_intent_id": "a" * 64,
                        "client_order_id": "KARK-unknown-1",
                        "intent_status": "submission_unknown",
                        "new_submissions_blocked": True,
                        "recovery_resubmission_enabled": False,
                        "does_not_mutate_production_ledger": True,
                    }
                },
            }
        ],
    )

    result = AutomationAlertService(
        db=db,
        trading_controls=None,
    ).scan()

    assert result["open_alert_count"] == 1
    alert = result["alerts"][0]
    assert alert["severity"] == "critical"
    assert alert["title"] == "Controlled broker submission outcome is unknown"
    assert alert["payload"]["blocks_new_submissions"] is True
    assert alert["payload"]["recovery_resubmission_enabled"] is False
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
                "input_fingerprint": "abc123def456",
                "idempotency_key": "market_session:2026-07-02:abc123def456",
                "input_snapshot": {
                    "schema_version": "karkinos.daily_trading_plan.v1",
                    "plan_date": "2026-07-02",
                    "generated_at": "2026-07-02T09:35:00+08:00",
                    "order_intent_count": 1,
                    "source_decision": "buy",
                    "input_fingerprint": "abc123def456",
                },
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
    assert alert["payload"]["input_fingerprint"] == "abc123def456"
    assert alert["payload"]["idempotency_key"] == (
        "market_session:2026-07-02:abc123def456"
    )
    assert alert["payload"]["input_snapshot"] == {
        "schema_version": "karkinos.daily_trading_plan.v1",
        "plan_date": "2026-07-02",
        "generated_at": "2026-07-02T09:35:00+08:00",
        "order_intent_count": 1,
        "source_decision": "buy",
        "input_fingerprint": "abc123def456",
    }
    assert alert["payload"]["retry_state"] == {
        "attempt": 1,
        "max_attempts": 2,
        "retryable": True,
    }
    assert alert["payload"]["requires_manual_review"] is True
    assert alert["payload"]["suggested_action"] == "inspect_failed_paper_shadow_run"
    assert alert["payload"]["retry_recommended"] is True
    assert alert["payload"]["does_not_submit_broker_order"] is True
    assert alert["payload"]["does_not_mutate_production_ledger"] is True


def test_alert_scan_records_missing_persisted_collector_evidence(tmp_path) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
    db.init_sync()
    connector = SimpleNamespace(
        connector_id="fixture-readonly-edge",
        connector_type="deterministic_fixture",
        enabled=True,
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
        "broker_connector:fixture-readonly-edge:collector_evidence_missing"
    )
    assert alert["severity"] == "warning"
    assert alert["category"] == "broker_connector_health"
    assert alert["title"] == "Broker connector health requires review"
    assert alert["source"] == "broker_gateway"
    assert alert["source_ref"] == "fixture-readonly-edge"
    assert "explicit ingestion" in alert["detail"]
    assert alert["payload"]["connector_id"] == "fixture-readonly-edge"
    assert alert["payload"]["connector_status"] == "collector_evidence_missing"
    assert alert["payload"]["capability_scope"] == (
        "persisted_broker_order_lifecycle_evidence"
    )
    assert alert["payload"]["evidence_source"] == (
        "persisted_broker_order_lifecycle_collector_runs"
    )
    assert alert["payload"]["evidence_store_status"] == "empty"
    assert alert["payload"]["evidence_blockers"] == [
        "broker_lifecycle_collector_evidence_missing"
    ]
    assert alert["payload"]["provider_contact_performed"] is False
    assert alert["payload"]["reads_persisted_facts_only"] is True
    assert alert["payload"]["explicit_ingestion_required"] is True
    assert alert["payload"]["third_party_adapter_review_required"] is True
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
                "connector_id": "fixture-readonly-edge",
                "connector_type": "deterministic_fixture",
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
    assert alert["alert_key"] == (
        "broker_connector:fixture-readonly-edge:runtime_degraded"
    )
    assert alert["severity"] == "warning"
    assert alert["category"] == "broker_connector_health"
    assert alert["title"] == "Broker connector health requires review"
    assert alert["source"] == "broker_gateway"
    assert alert["source_ref"] == "fixture-readonly-edge"
    assert "heartbeat is stale" in alert["detail"]
    assert alert["payload"]["connector_id"] == "fixture-readonly-edge"
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


def test_alert_scan_does_not_poll_registered_edge_adapter(tmp_path) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
    db.init_sync()
    connector = _ConnectorWouldFailIfQueried()
    service = AutomationAlertService(
        db=db,
        trading_controls=None,
        broker_connectors=[connector],
    )

    result = service.scan()

    assert result["open_alert_count"] == 1
    alert = result["alerts"][0]
    assert alert["alert_key"] == (
        "broker_connector:fixture-readonly-edge:collector_evidence_missing"
    )
    assert alert["category"] == "broker_connector_health"
    assert alert["source"] == "broker_gateway"
    assert alert["source_ref"] == "fixture-readonly-edge"
    assert "explicit ingestion" in alert["detail"]
    assert alert["payload"]["connector_id"] == "fixture-readonly-edge"
    assert alert["payload"]["connector_status"] == "collector_evidence_missing"
    assert alert["payload"]["capability_scope"] == (
        "persisted_broker_order_lifecycle_evidence"
    )
    assert alert["payload"]["provider_contact_performed"] is False
    assert alert["payload"]["reads_persisted_facts_only"] is True
    assert alert["payload"]["explicit_ingestion_required"] is True
    assert alert["payload"]["third_party_adapter_review_required"] is True
    assert alert["payload"]["last_heartbeat_at"] is None
    assert alert["payload"]["can_read_account"] is False
    assert alert["payload"]["can_read_cash"] is False
    assert alert["payload"]["can_preview_orders"] is False
    assert alert["payload"]["can_export_tickets"] is False
    assert alert["payload"]["can_dry_run_orders"] is False
    assert alert["payload"]["can_submit_orders"] is False
    assert alert["payload"]["can_cancel_orders"] is False
    assert alert["payload"]["stores_credentials"] is False
    assert alert["payload"]["submitted_to_broker"] is False
    assert alert["payload"]["does_not_submit_broker_order"] is True
    assert "qmt" not in alert["payload_json"].lower()


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


def test_alert_scan_records_blocked_current_per_order_evidence_once_after_restart(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
    db.init_sync()
    reader_calls: list[str] = []
    source = _current_per_order_source(
        [
            {
                "order_id": "OMS-READY-1",
                "symbol": "510300.SH",
                "side": "buy",
                "quantity": "100",
                "order_fingerprint": "a" * 64,
                "dossier_fingerprint": "b" * 64,
                "review_status": "review_ready_non_submitting",
                "review_ready": True,
                "review_blockers": [],
                "evidence_resolution_status": "resolved",
                "confirmation_status": "missing",
                "authorizes_execution": False,
            },
            {
                "order_id": "OMS-BLOCKED-1",
                "symbol": "600519.SH",
                "side": "sell",
                "quantity": "10",
                "order_fingerprint": "c" * 64,
                "dossier_fingerprint": "d" * 64,
                "review_status": "blocked_review",
                "review_ready": False,
                "review_blockers": ["current_capital_evaluation_not_found"],
                "evidence_resolution_status": "missing",
                "confirmation_status": "missing",
                "authorizes_execution": False,
            },
        ]
    )

    def reader() -> dict:
        reader_calls.append("read")
        return source

    first = AutomationAlertService(
        db=db,
        trading_controls=None,
        current_per_order_dossier_reader=reader,
    ).scan()
    restarted = AutomationAlertService(
        db=db,
        trading_controls=None,
        current_per_order_dossier_reader=reader,
    ).scan()

    assert reader_calls == ["read", "read"]
    assert first["generated_alert_count"] == 1
    assert restarted["generated_alert_count"] == 1
    assert first["open_alert_count"] == 1
    assert restarted["open_alert_count"] == 1
    assert first["alerts"][0]["id"] == restarted["alerts"][0]["id"]
    alert = restarted["alerts"][0]
    assert alert["category"] == "per_order_evidence_review"
    assert alert["source_ref"] == "OMS-BLOCKED-1"
    assert alert["payload"]["order_id"] == "OMS-BLOCKED-1"
    assert alert["payload"]["suggested_action"] == (
        "resolve_current_per_order_evidence_blockers"
    )
    assert alert["payload"]["review_blockers"] == [
        "current_capital_evaluation_not_found"
    ]
    assert alert["payload"]["reads_persisted_facts_only"] is True
    assert alert["payload"]["provider_contact_performed"] is False
    assert alert["payload"]["runtime_connector_query_performed"] is False
    assert alert["payload"]["does_not_submit_broker_order"] is True
    assert alert["payload"]["does_not_cancel_broker_order"] is True
    assert alert["payload"]["does_not_mutate_oms"] is True
    assert alert["payload"]["does_not_mutate_production_ledger"] is True
    assert alert["payload"]["does_not_change_capital_authority"] is True
    assert alert["payload"]["authorizes_execution"] is False
    assert db.list_oms_orders_sync(limit=10) == []

    AutomationAlertService(db=db, trading_controls=None).acknowledge(
        alert["id"], actor="operator-review"
    )
    after_acknowledgement = AutomationAlertService(
        db=db,
        trading_controls=None,
        current_per_order_dossier_reader=reader,
    ).scan()
    assert reader_calls == ["read", "read", "read"]
    assert after_acknowledgement["generated_alert_count"] == 1
    assert after_acknowledgement["open_alert_count"] == 0
    assert after_acknowledgement["alerts"] == []
    acknowledged = db.list_automation_alerts_sync(status="acknowledged")
    assert len(acknowledged) == 1
    assert acknowledged[0]["acknowledged_by"] == "operator-review"


def test_alert_scan_blocks_untrusted_current_per_order_source_without_candidates(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
    db.init_sync()
    source = _current_per_order_source(
        [
            {
                "order_id": "OMS-UNTRUSTED-1",
                "symbol": "510300.SH",
                "side": "buy",
                "quantity": "100",
                "review_status": "review_ready_non_submitting",
                "review_ready": True,
                "review_blockers": [],
                "authorizes_execution": False,
            }
        ]
    )
    source["schema_version"] = "karkinos.current_per_order_confirmation_candidates.v0"

    result = AutomationAlertService(
        db=db,
        trading_controls=None,
        current_per_order_dossier_reader=lambda: source,
    ).scan()

    assert result["open_alert_count"] == 1
    alert = result["alerts"][0]
    assert alert["alert_key"].startswith("current_per_order_review:source:")
    assert alert["source_ref"] == "current_per_order_source"
    assert alert["payload"]["source_blockers"] == [
        "current_per_order_source_schema_invalid"
    ]
    assert alert["payload"]["suggested_action"] == (
        "review_current_per_order_source_blockers"
    )
    assert "order_id" not in alert["payload"]
    assert alert["payload"]["provider_contact_performed"] is False
    assert alert["payload"]["authorizes_execution"] is False


def test_alert_scan_does_not_alert_for_ready_current_per_order_review(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "alerts.db")
    db.init_sync()
    source = _current_per_order_source(
        [
            {
                "order_id": "OMS-READY-1",
                "symbol": "510300.SH",
                "side": "buy",
                "quantity": "100",
                "review_status": "review_ready_non_submitting",
                "review_ready": True,
                "review_blockers": [],
                "authorizes_execution": False,
            }
        ]
    )

    result = AutomationAlertService(
        db=db,
        trading_controls=None,
        current_per_order_dossier_reader=lambda: source,
    ).scan()

    assert result["generated_alert_count"] == 0
    assert result["open_alert_count"] == 0
    assert result["alerts"] == []


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
