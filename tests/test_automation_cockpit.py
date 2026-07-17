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


def test_automation_cockpit_projects_current_per_order_reviews_without_authority(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "automation-cockpit.db")
    db.init_sync()
    reader_calls: list[str] = []

    def current_reviews():
        reader_calls.append("read")
        return {
            "schema_version": "karkinos.current_per_order_confirmation_candidates.v1",
            "candidate_count": 3,
            "candidates": [
                {
                    "order_id": "OMS-READY",
                    "symbol": "510300.SH",
                    "side": "buy",
                    "quantity": "100",
                    "review_status": "review_ready_non_submitting",
                    "review_ready": True,
                    "review_blockers": [],
                    "authorizes_execution": False,
                },
                {
                    "order_id": "OMS-BLOCKED-1",
                    "symbol": "600519.SH",
                    "side": "sell",
                    "quantity": "10",
                    "review_status": "blocked_review",
                    "review_ready": False,
                    "review_blockers": ["current_capital_evaluation_not_found"],
                    "authorizes_execution": False,
                },
                {
                    "order_id": "OMS-BLOCKED-2",
                    "symbol": "000001.SZ",
                    "side": "buy",
                    "quantity": "200",
                    "review_status": "blocked_review",
                    "review_ready": False,
                    "review_blockers": ["verification_expired"],
                    "authorizes_execution": False,
                },
            ],
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

    summary = AutomationCockpitService(
        db=db,
        trading_controls=None,
        current_per_order_dossier_reader=current_reviews,
    ).summary()

    current = summary["current_per_order_reviews"]
    assert reader_calls == ["read"]
    assert current["status"] == "review_ready"
    assert current["candidate_count"] == 3
    assert current["review_ready_count"] == 1
    assert current["blocked_review_count"] == 2
    assert current["primary_candidate"]["order_id"] == "OMS-READY"
    assert current["next_operator_action"] == ("open_trading_current_per_order_review")
    assert current["reads_persisted_facts_only"] is True
    assert current["provider_contact_performed"] is False
    assert current["broker_submission_enabled"] is False
    assert current["broker_cancel_enabled"] is False
    assert current["authorizes_execution"] is False


def test_automation_cockpit_fails_closed_on_current_review_source_drift(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "automation-cockpit.db")
    db.init_sync()

    summary = AutomationCockpitService(
        db=db,
        trading_controls=None,
        current_per_order_dossier_reader=lambda: {
            "schema_version": "karkinos.current_per_order_confirmation_candidates.v0",
            "candidate_count": 1,
            "candidates": [],
            "truncated": True,
            "reads_persisted_facts_only": True,
            "provider_contact_performed": True,
            "runtime_connector_query_performed": False,
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
            "does_not_mutate_risk": True,
            "does_not_mutate_kill_switch": True,
            "does_not_change_capital_authority": True,
            "broker_submission_enabled": False,
            "broker_cancel_enabled": False,
            "authorizes_execution": False,
        },
    ).summary()

    current = summary["current_per_order_reviews"]
    assert current["status"] == "blocked_source"
    assert current["primary_candidate"] is None
    assert set(current["source_blockers"]) == {
        "current_per_order_source_schema_invalid",
        "current_per_order_candidate_count_mismatch",
        "current_per_order_candidate_source_truncated",
        "current_per_order_source_boundary_invalid",
    }
    assert current["provider_contact_performed"] is False
    assert current["authorizes_execution"] is False


def test_automation_cockpit_fails_closed_when_current_review_reader_raises(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "automation-cockpit.db")
    db.init_sync()

    def failed_reader():
        raise RuntimeError("persisted review projection failed")

    summary = AutomationCockpitService(
        db=db,
        trading_controls=None,
        current_per_order_dossier_reader=failed_reader,
    ).summary()

    current = summary["current_per_order_reviews"]
    assert current["status"] == "blocked_source"
    assert current["candidate_count"] == 0
    assert current["primary_candidate"] is None
    assert current["source_blockers"] == ["current_per_order_dossier_source_failed"]
    assert current["reads_persisted_facts_only"] is True
    assert current["provider_contact_performed"] is False
    assert current["authorizes_execution"] is False
