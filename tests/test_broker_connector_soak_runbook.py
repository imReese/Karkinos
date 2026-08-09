from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from account_truth.broker_connector import (
    BrokerCashFact,
    BrokerConnectorCapabilities,
    BrokerConnectorHealth,
    BrokerConnectorSnapshot,
    BrokerConnectorSourceContract,
    FakeReadOnlyBrokerConnector,
    LOCAL_JSON_SNAPSHOT_SCHEMA_VERSION,
    UnsupportedLocalJsonSnapshotSchema,
)
from data.market_calendar import build_static_market_calendar_snapshot
from server.db import AppDatabase
from server.services.broker_connector_soak import (
    BROKER_CONNECTOR_SOAK_EVENT_TYPE,
    BrokerConnectorSoakService,
)
from server.services.broker_connector_soak_runbook import (
    BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE,
    BROKER_CONNECTOR_SOAK_RESTART_CHECKPOINT_EVENT_TYPE,
    BROKER_CONNECTOR_SOAK_RUN_EVENT_TYPE,
    BrokerConnectorSoakRestartCheckpointNotFound,
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
        connector_id="fixture-readonly-runbook",
        source_name="synthetic deterministic readonly export",
        account_id="private-runbook-account-id-must-not-leak",
        account_alias="fixture-runbook",
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


class ContractRequiredReadOnlyConnector(FakeReadOnlyBrokerConnector):
    requires_source_contract = True


def _sequenced_snapshot(
    captured_at: datetime,
    *,
    cursor_previous: int,
    cursor_current: int,
    batch_id: str,
    complete: bool = True,
) -> BrokerConnectorSnapshot:
    return BrokerConnectorSnapshot(
        connector_id="fixture-readonly-runbook",
        source_name="synthetic sequenced readonly export",
        account_id="private-runbook-account-id-must-not-leak",
        account_alias="fixture-runbook",
        captured_at=captured_at.isoformat(),
        health=BrokerConnectorHealth(
            status="healthy" if complete else "incomplete",
            checked_at=captured_at.isoformat(),
        ),
        cash=BrokerCashFact(
            currency="CNY",
            balance=Decimal("100000"),
            available=Decimal("90000"),
        ),
        source_contract=BrokerConnectorSourceContract(
            schema_version=LOCAL_JSON_SNAPSHOT_SCHEMA_VERSION,
            connector_id="fixture-readonly-runbook",
            deployment_identity="synthetic-runbook-deployment",
            batch_id=batch_id,
            cursor_previous=cursor_previous,
            cursor_current=cursor_current,
            trading_day=TRADING_DAY,
            session_phase="intraday",
            heartbeat_at=captured_at.isoformat(),
            cash_complete=True,
            positions_complete=True,
            orders_complete=complete,
            fills_complete=True,
        ),
    )


def _capture_sequence_baseline(
    db: AppDatabase,
    *,
    captured_at: datetime,
    cursor_previous: int,
    cursor_current: int,
    batch_id: str,
) -> None:
    BrokerConnectorSoakService(
        db=db,
        connectors=[
            ContractRequiredReadOnlyConnector(
                _sequenced_snapshot(
                    captured_at,
                    cursor_previous=cursor_previous,
                    cursor_current=cursor_current,
                    batch_id=batch_id,
                )
            )
        ],
        clock=lambda: captured_at,
    ).capture()


def _service(
    db: AppDatabase,
    connector: object | None = None,
    *,
    process_instance_id: str = "runbook-process-default",
) -> BrokerConnectorSoakRunbookService:
    connectors = (
        [connector]
        if connector is not None
        else [
            ContractRequiredReadOnlyConnector(
                _sequenced_snapshot(
                    OBSERVED_AT,
                    cursor_previous=0,
                    cursor_current=1,
                    batch_id="runbook-default-batch-1",
                )
            )
        ]
    )
    return BrokerConnectorSoakRunbookService(
        db=db,
        connectors=connectors,
        clock=lambda: OBSERVED_AT,
        process_instance_id=process_instance_id,
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


def test_healthy_unsequenced_snapshot_cannot_pass_operational_phase(tmp_path) -> None:
    db = _db(tmp_path)
    connector = FakeReadOnlyBrokerConnector(_snapshot())

    result = _service(db, connector).run_phase(phase="startup")

    assert result["run_status"] == "blocked"
    assert result["blockers"] == [
        "source_sequence_not_accepted:fixture-readonly-runbook"
    ]
    assert result["observations"][0]["soak_status"] == "healthy"
    assert result["does_not_grant_capital_authority"] is True


def test_unsequenced_replay_cannot_pass_duplicate_drill(tmp_path) -> None:
    db = _db(tmp_path)
    connector = FakeReadOnlyBrokerConnector(_snapshot())

    result = _service(db, connector).run_drill(drill_type="duplicate_evidence")

    assert result["drill_status"] == "failed"
    assert result["blockers"] == [
        "source_sequence_not_accepted:fixture-readonly-runbook",
        "replay_source_sequence_not_accepted:fixture-readonly-runbook",
    ]
    assert result["second_observations"][0]["reused"] is True
    assert result["does_not_submit_broker_order"] is True


def test_end_of_day_run_blocks_without_clear_execution_reconciliation(
    tmp_path,
) -> None:
    db = _db(tmp_path)

    result = _service(db).run_phase(phase="end_of_day")

    assert result["run_status"] == "blocked"
    assert result["blockers"] == [
        "execution_reconciliation_not_clear:fixture-readonly-runbook"
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


def test_cursor_gap_drill_requires_observed_sequence_block_without_advance(
    tmp_path,
) -> None:
    db = _db(tmp_path)
    _capture_sequence_baseline(
        db,
        captured_at=OBSERVED_AT - timedelta(minutes=1),
        cursor_previous=0,
        cursor_current=1,
        batch_id="runbook-batch-1",
    )
    gap_connector = ContractRequiredReadOnlyConnector(
        _sequenced_snapshot(
            OBSERVED_AT,
            cursor_previous=2,
            cursor_current=3,
            batch_id="runbook-batch-3",
        )
    )

    result = _service(db, gap_connector).run_drill(drill_type="cursor_gap")

    assert result["drill_status"] == "passed"
    observation = result["first_observations"][0]
    assert "source_sequence_cursor_gap" in observation["blockers"]
    assert observation["source_sequence"]["state_advanced"] is False


def test_cursor_out_of_order_drill_requires_observed_sequence_block(
    tmp_path,
) -> None:
    db = _db(tmp_path)
    _capture_sequence_baseline(
        db,
        captured_at=OBSERVED_AT - timedelta(minutes=2),
        cursor_previous=0,
        cursor_current=1,
        batch_id="runbook-batch-1",
    )
    _capture_sequence_baseline(
        db,
        captured_at=OBSERVED_AT - timedelta(minutes=1),
        cursor_previous=1,
        cursor_current=2,
        batch_id="runbook-batch-2",
    )
    old_connector = ContractRequiredReadOnlyConnector(
        _sequenced_snapshot(
            OBSERVED_AT,
            cursor_previous=0,
            cursor_current=1,
            batch_id="runbook-old-batch",
        )
    )

    result = _service(db, old_connector).run_drill(drill_type="cursor_out_of_order")

    assert result["drill_status"] == "passed"
    assert "source_sequence_cursor_out_of_order" in (
        result["first_observations"][0]["blockers"]
    )


def test_partial_batch_drill_requires_block_without_initial_cursor_advance(
    tmp_path,
) -> None:
    db = _db(tmp_path)
    partial_connector = ContractRequiredReadOnlyConnector(
        _sequenced_snapshot(
            OBSERVED_AT,
            cursor_previous=0,
            cursor_current=1,
            batch_id="runbook-partial-batch-1",
            complete=False,
        )
    )

    result = _service(db, partial_connector).run_drill(drill_type="partial_batch")

    assert result["drill_status"] == "passed"
    observation = result["first_observations"][0]
    assert "source_sequence_partial_batch" in observation["blockers"]
    assert observation["source_sequence"]["state_advanced"] is False


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


def test_karkinos_restart_requires_changed_process_instance_and_exact_replay(
    tmp_path,
) -> None:
    db = _db(tmp_path)
    before_restart = _service(db, process_instance_id="process-before-restart")

    checkpoint = before_restart.prepare_karkinos_restart()
    same_process = before_restart.complete_karkinos_restart(
        checkpoint_id=checkpoint["checkpoint_id"]
    )
    after_restart = _service(db, process_instance_id="process-after-restart")
    completed = after_restart.complete_karkinos_restart(
        checkpoint_id=checkpoint["checkpoint_id"]
    )
    rerun = after_restart.complete_karkinos_restart(
        checkpoint_id=checkpoint["checkpoint_id"]
    )

    assert checkpoint["checkpoint_status"] == "prepared"
    assert checkpoint["blockers"] == []
    assert same_process["drill_status"] == "failed"
    assert "process_instance_unchanged" in same_process["blockers"]
    assert completed["drill_status"] == "passed"
    assert completed["drill_type"] == "karkinos_restart"
    assert completed["process_instance_changed"] is True
    assert completed["second_observations"][0]["reused"] is True
    assert (
        completed["first_observations"][0]["event_id"]
        == completed["second_observations"][0]["event_id"]
    )
    assert completed["does_not_grant_capital_authority"] is True
    assert rerun["event_id"] == completed["event_id"]
    assert rerun["reused"] is True
    assert len(before_restart.list_restart_checkpoints()) == 1
    assert (
        len(
            db.list_events_sync(
                event_type=BROKER_CONNECTOR_SOAK_RESTART_CHECKPOINT_EVENT_TYPE
            )
        )
        == 1
    )


def test_karkinos_restart_checkpoint_blocks_unsequenced_snapshot(tmp_path) -> None:
    db = _db(tmp_path)
    connector = FakeReadOnlyBrokerConnector(_snapshot())
    before_restart = _service(
        db,
        connector,
        process_instance_id="unsequenced-process-before",
    )

    checkpoint = before_restart.prepare_karkinos_restart()
    completed = _service(
        db,
        connector,
        process_instance_id="unsequenced-process-after",
    ).complete_karkinos_restart(checkpoint_id=checkpoint["checkpoint_id"])

    assert checkpoint["checkpoint_status"] == "blocked"
    assert checkpoint["blockers"] == [
        "source_sequence_not_accepted:fixture-readonly-runbook"
    ]
    assert completed["drill_status"] == "failed"
    assert "restart_checkpoint_not_prepared" in completed["blockers"]
    assert "source_sequence_not_accepted:fixture-readonly-runbook" in (
        completed["blockers"]
    )
    assert "replay_source_sequence_not_accepted:fixture-readonly-runbook" in (
        completed["blockers"]
    )


def test_karkinos_restart_completion_rejects_unknown_checkpoint(tmp_path) -> None:
    db = _db(tmp_path)

    with pytest.raises(BrokerConnectorSoakRestartCheckpointNotFound):
        _service(
            db, process_instance_id="process-after-restart"
        ).complete_karkinos_restart(checkpoint_id="f" * 64)

    assert db.list_events_sync(event_type=BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE) == []


def test_failed_drill_is_audited_and_alerted_without_execution_authority(
    tmp_path,
) -> None:
    db = _db(tmp_path)

    result = _service(db).run_drill(drill_type="disconnect")

    assert result["drill_status"] == "failed"
    assert result["blockers"] == [
        "expected_safe_degradation_not_observed:fixture-readonly-runbook"
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
