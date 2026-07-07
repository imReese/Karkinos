from __future__ import annotations

import json
from decimal import Decimal

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
from server.db import AppDatabase
from server.services.automation_alerts import AutomationAlertService
from server.services.automation_cockpit import AutomationCockpitService
from server.services.market_session_automation import MarketSessionAutomationService
from server.services.trading_controls import TradingControlState


def test_automation_cockpit_summary_collects_controls_alerts_runs_and_gateways(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "automation-cockpit.db")
    db.init_sync()
    controls = TradingControlState(db=db)
    controls.set_kill_switch(True, "operator pause")
    MarketSessionAutomationService(db=db, trading_controls=controls).run_session(
        trading_plan={
            "schema_version": "karkinos.daily_trading_plan.v1",
            "plan_date": "2026-07-02",
            "order_intents": [],
        }
    )
    AutomationAlertService(db=db, trading_controls=controls).scan()

    summary = AutomationCockpitService(db=db, trading_controls=controls).summary()

    assert summary["broker_submission_enabled"] is False
    assert summary["automation_status"]["kill_switch_enabled"] is True
    assert summary["open_alert_count"] >= 1
    assert summary["recent_runs"][0]["run_type"] == "market_session"
    gateways = {item["gateway_id"]: item for item in summary["gateways"]}
    assert {"manual_ticket", "staged_broker_evidence", "live_disabled"}.issubset(
        gateways
    )
    assert gateways["staged_broker_evidence"]["can_read_account_facts"] is True
    assert gateways["staged_broker_evidence"]["can_submit_orders"] is False


def test_automation_cockpit_summary_includes_runtime_connector_snapshot_evidence(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "automation-cockpit.db")
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

    summary = AutomationCockpitService(
        db=db,
        trading_controls=None,
        broker_connectors=[connector],
    ).summary()

    snapshots = summary["runtime_connector_snapshots"]
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot["query_scope"] == "runtime_readonly_connector_snapshot"
    assert snapshot["connector_id"] == "fake-qmt-runtime"
    assert snapshot["account_alias"] == "local-review"
    assert snapshot["connector_health"]["status"] == "runtime_healthy"
    assert snapshot["cash_balance"]["currency"] == "CNY"
    assert snapshot["cash_balance"]["balance"] == "100000.00"
    assert snapshot["position_count"] == 1
    assert snapshot["order_count"] == 1
    assert snapshot["fill_count"] == 1
    assert snapshot["capabilities"]["can_submit_orders"] is False
    assert snapshot["capabilities"]["can_cancel_orders"] is False
    assert snapshot["submitted_to_broker"] is False
    assert snapshot["does_not_mutate_oms"] is True
    assert snapshot["does_not_mutate_production_ledger"] is True
    assert "private-account-id" not in json.dumps(summary, ensure_ascii=False)
    assert db.list_broker_gateway_events_sync() == []
