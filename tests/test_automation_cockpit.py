from __future__ import annotations

import json

from server.db import AppDatabase
from server.services.automation_alerts import AutomationAlertService
from server.services.automation_cockpit import AutomationCockpitService
from server.services.market_session_automation import MarketSessionAutomationService
from server.services.trading_controls import TradingControlState


class _ConnectorWouldFailIfQueried:
    connector_id = "fixture-readonly-edge"
    connector_type = "deterministic_fixture"

    def read_account_snapshot(self):
        raise AssertionError("cockpit GET must not call an edge adapter")


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

    assert summary["schema_version"] == "karkinos.automation_cockpit.v2"
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
    assert summary["controlled_execution"]["status"] == "no_session_evidence"
    assert summary["controlled_execution"]["broker_submission_enabled"] is False


def test_automation_cockpit_summary_includes_runtime_connector_snapshot_evidence(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "automation-cockpit.db")
    db.init_sync()
    connector = _ConnectorWouldFailIfQueried()

    summary = AutomationCockpitService(
        db=db,
        trading_controls=None,
        broker_connectors=[connector],
    ).summary()

    assert summary["schema_version"] == "karkinos.automation_cockpit.v2"
    assert "runtime_connector_snapshots" not in summary
    assert "runtime_connector_snapshot_status" not in summary
    registration = summary["connector_registrations"][0]
    assert registration["connector_id"] == "fixture-readonly-edge"
    assert registration["registration_status"] == "registered_unqueried"
    assert registration["provider_contact_performed"] is False
    assert registration["explicit_ingestion_required"] is True
    assert registration["can_submit_orders"] is False
    assert registration["can_cancel_orders"] is False
    assert summary["controlled_execution"]["provider_contact_performed"] is False
    assert "qmt" not in json.dumps(summary, ensure_ascii=False).lower()
    assert db.list_broker_gateway_events_sync() == []
