from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from account_truth.broker_connector import (
    BrokerCashFact,
    BrokerConnectorCapabilities,
    BrokerConnectorHealth,
    BrokerConnectorSnapshot,
    FakeReadOnlyBrokerConnector,
    UnsupportedLocalJsonSnapshotSchema,
)
from data.market_calendar import build_static_market_calendar_snapshot
from server.db import AppDatabase
from server.services.broker_connector_soak import (
    BROKER_CONNECTOR_SOAK_EVENT_TYPE,
)
from server.services.broker_connector_soak_runbook import (
    BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE,
    BROKER_CONNECTOR_SOAK_RUN_EVENT_TYPE,
    BrokerConnectorSoakRunbookService,
)

OBSERVED_AT = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)
TRADING_DAY = "2026-07-10"


def _db(tmp_path) -> AppDatabase:
    db = AppDatabase(tmp_path / "broker-soak-runbook.db")
    db.init_sync()
    db.upsert_market_calendar_snapshot_sync(
        build_static_market_calendar_snapshot(
            exchange="SSE",
            year=2026,
            provider="synthetic_test_calendar",
            open_dates=[TRADING_DAY],
            fetched_at="2026-01-01T00:00:00+08:00",
        )
    )
    return db


def _snapshot(captured_at: datetime = OBSERVED_AT) -> BrokerConnectorSnapshot:
    return BrokerConnectorSnapshot(
        connector_id="qmt-readonly-runbook",
        source_name="synthetic QMT readonly export",
        account_id="private-runbook-account-id-must-not-leak",
        account_alias="qmt-runbook",
        captured_at=captured_at.isoformat(),
        health=BrokerConnectorHealth(
            status="healthy",
            checked_at=captured_at.isoformat(),
        ),
        cash=BrokerCashFact(
            currency="CNY",
            balance=Decimal("100000"),
            available=Decimal("90000"),
        ),
    )


def _service(
    db: AppDatabase,
    connector: object | None = None,
) -> BrokerConnectorSoakRunbookService:
    connectors = (
        [connector]
        if connector is not None
        else [FakeReadOnlyBrokerConnector(_snapshot())]
    )
    return BrokerConnectorSoakRunbookService(
        db=db,
        connectors=connectors,
        clock=lambda: OBSERVED_AT,
    )


def test_startup_run_is_persisted_deterministic_and_readonly(tmp_path) -> None:
    db = _db(tmp_path)
    service = _service(db)

    first = service.run_phase(phase="startup")
    rerun = service.run_phase(phase="startup")

    assert first["run_status"] == "passed"
    assert first["blockers"] == []
    assert first["broker_submission_enabled"] is False
    assert first["does_not_mutate_oms"] is True
    assert first["does_not_mutate_production_ledger"] is True
    assert first["does_not_grant_capital_authority"] is True
    assert rerun["event_id"] == first["event_id"]
    assert rerun["reused"] is True
    assert (
        len(db.list_events_sync(event_type=BROKER_CONNECTOR_SOAK_RUN_EVENT_TYPE)) == 1
    )
    assert "private-runbook-account-id-must-not-leak" not in json.dumps(first)


def test_end_of_day_run_blocks_without_clear_execution_reconciliation(
    tmp_path,
) -> None:
    db = _db(tmp_path)

    result = _service(db).run_phase(phase="end_of_day")

    assert result["run_status"] == "blocked"
    assert result["blockers"] == [
        "execution_reconciliation_not_clear:qmt-readonly-runbook"
    ]
    alerts = db.list_automation_alerts_sync(status="open")
    assert any(alert["category"] == "broker_connector_soak_runbook" for alert in alerts)


def test_end_of_day_run_passes_only_with_clear_execution_reconciliation(
    tmp_path,
) -> None:
    db = _db(tmp_path)
    db.upsert_execution_reconciliation_run_sync(
        run_id="execution-reconciliation:2026-07-10",
        run_date=TRADING_DAY,
        status="clear",
        item_count=0,
        open_item_count=0,
        payload={"source": "synthetic-test"},
        items=[],
    )

    result = _service(db).run_phase(phase="end_of_day")

    assert result["run_status"] == "passed"
    assert result["requires_clear_execution_reconciliation"] is True
    assert result["observations"][0]["execution_reconciliation_status"] == "clear"


def test_disconnect_drill_passes_on_fail_closed_connector_read_error(
    tmp_path,
) -> None:
    db = _db(tmp_path)

    class DisconnectedReadOnlyConnector:
        connector_id = "disconnected-readonly"
        capabilities = BrokerConnectorCapabilities()

        def read_account_snapshot(self):
            raise ConnectionError("synthetic disconnect")

    result = _service(db, DisconnectedReadOnlyConnector()).run_drill(
        drill_type="disconnect"
    )

    assert result["drill_status"] == "passed"
    assert result["blockers"] == []
    assert result["first_observations"][0]["soak_status"] == "blocked"
    assert result["does_not_submit_broker_order"] is True


def test_stale_data_drill_passes_on_safe_degradation(tmp_path) -> None:
    db = _db(tmp_path)
    stale_connector = FakeReadOnlyBrokerConnector(
        _snapshot(OBSERVED_AT - timedelta(minutes=20))
    )

    result = _service(db, stale_connector).run_drill(drill_type="stale_data")

    assert result["drill_status"] == "passed"
    assert result["blockers"] == []
    assert "snapshot_stale" in result["first_observations"][0]["blockers"]


def test_schema_drift_drill_passes_on_unsupported_snapshot_schema_block(
    tmp_path,
) -> None:
    db = _db(tmp_path)

    class SchemaDriftReadOnlyConnector:
        connector_id = "schema-drift-readonly"
        capabilities = BrokerConnectorCapabilities()

        def read_account_snapshot(self):
            raise UnsupportedLocalJsonSnapshotSchema("synthetic schema drift")

    result = _service(db, SchemaDriftReadOnlyConnector()).run_drill(
        drill_type="schema_drift"
    )

    assert result["drill_status"] == "passed"
    assert result["blockers"] == []
    assert result["first_observations"][0]["soak_status"] == "blocked"


def test_duplicate_evidence_drill_reuses_one_observation_event(tmp_path) -> None:
    db = _db(tmp_path)

    result = _service(db).run_drill(drill_type="duplicate_evidence")

    assert result["drill_status"] == "passed"
    assert (
        result["first_observations"][0]["event_id"]
        == result["second_observations"][0]["event_id"]
    )
    assert result["second_observations"][0]["reused"] is True
    assert len(db.list_events_sync(event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE)) == 1


def test_restart_recovery_drill_reuses_persisted_evidence(tmp_path) -> None:
    db = _db(tmp_path)
    service = _service(db)

    first = service.run_drill(drill_type="restart_recovery")
    rerun = service.run_drill(drill_type="restart_recovery")

    assert first["drill_status"] == "passed"
    assert first["second_observations"][0]["reused"] is True
    assert rerun["event_id"] == first["event_id"]
    assert rerun["reused"] is True
    assert (
        len(db.list_events_sync(event_type=BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE)) == 1
    )


def test_failed_drill_is_audited_and_alerted_without_execution_authority(
    tmp_path,
) -> None:
    db = _db(tmp_path)

    result = _service(db).run_drill(drill_type="disconnect")

    assert result["drill_status"] == "failed"
    assert result["blockers"] == [
        "expected_safe_degradation_not_observed:qmt-readonly-runbook"
    ]
    assert result["does_not_grant_capital_authority"] is True
    alerts = db.list_automation_alerts_sync(status="open")
    runbook_alert = next(
        alert
        for alert in alerts
        if alert["category"] == "broker_connector_soak_runbook"
    )
    assert (
        "private-runbook-account-id-must-not-leak" not in runbook_alert["payload_json"]
    )


def test_run_with_no_configured_connector_blocks_fail_closed(tmp_path) -> None:
    db = _db(tmp_path)
    service = BrokerConnectorSoakRunbookService(
        db=db,
        connectors=[],
        clock=lambda: OBSERVED_AT,
    )

    result = service.run_phase(phase="intraday")

    assert result["run_status"] == "blocked"
    assert result["blockers"] == ["no_configured_readonly_connector"]
