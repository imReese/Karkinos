from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from account_truth.broker_connector import (
    LOCAL_JSON_SNAPSHOT_SCHEMA_VERSION,
    BrokerCashFact,
    BrokerConnectorCapabilities,
    BrokerConnectorHealth,
    BrokerConnectorSnapshot,
    BrokerConnectorSourceContract,
    BrokerFillFact,
    BrokerOrderFact,
    BrokerPositionFact,
    FakeReadOnlyBrokerConnector,
)
from data.market_calendar import build_static_market_calendar_snapshot
from server.db import AppDatabase
from server.services.broker_connector_soak import (
    BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
    BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
    BROKER_CONNECTOR_SOAK_EVENT_TYPE,
    BrokerConnectorSoakService,
)


def _snapshot(captured_at: datetime) -> BrokerConnectorSnapshot:
    return BrokerConnectorSnapshot(
        connector_id="fixture-readonly-soak",
        source_name="synthetic deterministic readonly export",
        account_id="private-account-id-must-not-leak",
        account_alias="fixture-primary",
        captured_at=captured_at.isoformat(),
        health=BrokerConnectorHealth(
            status="healthy",
            checked_at=captured_at.isoformat(),
            message="read-only export available",
        ),
        cash=BrokerCashFact(
            currency="CNY",
            balance=Decimal("100000"),
            available=Decimal("88000"),
        ),
        positions=[
            BrokerPositionFact(
                symbol="510300.SH",
                instrument_name="沪深300ETF",
                asset_class="fund",
                quantity=Decimal("1000"),
                available_quantity=Decimal("1000"),
                cost_basis=Decimal("3.5"),
                market_price=Decimal("3.6"),
            )
        ],
        orders=[
            BrokerOrderFact(
                order_id="broker-order-1",
                symbol="510300.SH",
                side="buy",
                status="filled",
                quantity=Decimal("100"),
                price=Decimal("3.6"),
                submitted_at=captured_at.isoformat(),
            )
        ],
        fills=[
            BrokerFillFact(
                fill_id="broker-fill-1",
                order_id="broker-order-1",
                symbol="510300.SH",
                side="buy",
                quantity=Decimal("100"),
                price=Decimal("3.6"),
                fee=Decimal("5"),
                tax=Decimal("0"),
                net_amount=Decimal("365"),
                filled_at=captured_at.isoformat(),
            )
        ],
        limitations=["synthetic fixture"],
    )


class ContractRequiredReadOnlyConnector(FakeReadOnlyBrokerConnector):
    requires_source_contract = True


def _sequenced_snapshot(
    captured_at: datetime,
    *,
    cursor_previous: int,
    cursor_current: int,
    batch_id: str,
    deployment_identity: str = "synthetic-reviewed-deployment",
    complete: bool = True,
    balance: str = "100000",
) -> BrokerConnectorSnapshot:
    return replace(
        _snapshot(captured_at),
        health=BrokerConnectorHealth(
            status="healthy" if complete else "incomplete",
            checked_at=captured_at.isoformat(),
            message="sequenced read-only export",
        ),
        cash=BrokerCashFact(
            currency="CNY",
            balance=Decimal(balance),
            available=Decimal("88000"),
        ),
        source_contract=BrokerConnectorSourceContract(
            schema_version=LOCAL_JSON_SNAPSHOT_SCHEMA_VERSION,
            connector_id="fixture-readonly-soak",
            deployment_identity=deployment_identity,
            batch_id=batch_id,
            cursor_previous=cursor_previous,
            cursor_current=cursor_current,
            trading_day=captured_at.astimezone(timezone(timedelta(hours=8)))
            .date()
            .isoformat(),
            session_phase="intraday",
            heartbeat_at=captured_at.isoformat(),
            cash_complete=True,
            positions_complete=True,
            orders_complete=complete,
            fills_complete=True,
        ),
    )


def _capture_sequenced(
    db: AppDatabase,
    snapshot: BrokerConnectorSnapshot,
    *,
    observed_at: datetime,
) -> dict:
    return BrokerConnectorSoakService(
        db=db,
        connectors=[ContractRequiredReadOnlyConnector(snapshot)],
        clock=lambda: observed_at,
    ).capture()["observations"][0]


def _seed_trading_days(db: AppDatabase, days: list[str]) -> None:
    by_year: dict[int, list[str]] = {}
    for day in days:
        by_year.setdefault(int(day[:4]), []).append(day)
    for year, open_dates in by_year.items():
        db.upsert_market_calendar_snapshot_sync(
            build_static_market_calendar_snapshot(
                exchange="SSE",
                year=year,
                provider="synthetic_test_calendar",
                open_dates=open_dates,
                fetched_at=f"{year}-01-01T00:00:00+08:00",
            )
        )


def test_healthy_snapshot_is_sanitized_persisted_and_reused(tmp_path) -> None:
    observed_at = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    _seed_trading_days(db, ["2026-07-10"])
    connector = FakeReadOnlyBrokerConnector(_snapshot(observed_at))
    service = BrokerConnectorSoakService(
        db=db,
        connectors=[connector],
        clock=lambda: observed_at,
    )

    first = service.capture()
    rerun = service.capture()

    observation = first["observations"][0]
    assert observation["soak_status"] == "healthy"
    assert observation["qualifies_for_healthy_soak_day"] is False
    assert observation["account_ref_hash"]
    assert observation["snapshot"]["account_ref_hash"]
    assert "account_id" not in observation["snapshot"]
    assert "private-account-id-must-not-leak" not in json.dumps(first)
    assert observation["broker_submission_enabled"] is False
    assert observation["does_not_submit_broker_order"] is True
    assert rerun["observations"][0]["event_id"] == observation["event_id"]
    assert rerun["observations"][0]["reused"] is True
    assert len(db.list_events_sync(event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE)) == 1
    assert db.list_automation_alerts_sync(status="open") == []

    status = service.get_status()
    summary = status["connectors"][0]
    assert summary["observed_healthy_trading_day_count"] == 1
    assert summary["healthy_trading_day_count"] == 0
    assert summary["sequence_accepted_trading_day_count"] == 0
    assert summary["latest_source_sequence_accepted"] is False
    assert summary["remaining_trading_days"] == 20
    assert status["promotion_ready"] is False
    assert status["healthy_day_evidence_requirement"] == ("accepted_v2_source_sequence")
    assert "latest_source_sequence_not_accepted:fixture-readonly-soak" in (
        status["promotion_blockers"]
    )
    assert "account_truth_reconciliation_not_linked" in status["promotion_blockers"]


def test_stale_snapshot_is_degraded_and_does_not_count_as_healthy_day(
    tmp_path,
) -> None:
    observed_at = datetime(2026, 7, 10, 8, 30, tzinfo=timezone.utc)
    captured_at = observed_at - timedelta(minutes=20)
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    _seed_trading_days(db, ["2026-07-10"])
    service = BrokerConnectorSoakService(
        db=db,
        connectors=[FakeReadOnlyBrokerConnector(_snapshot(captured_at))],
        clock=lambda: observed_at,
    )

    capture = service.capture(max_snapshot_age_seconds=900)

    observation = capture["observations"][0]
    assert observation["soak_status"] == "degraded"
    assert "snapshot_stale" in observation["blockers"]
    assert observation["qualifies_for_healthy_soak_day"] is False
    assert capture["status"]["connectors"][0]["healthy_trading_day_count"] == 0
    alerts = db.list_automation_alerts_sync(status="open")
    assert len(alerts) == 1
    assert alerts[0]["category"] == "broker_connector_soak"
    assert alerts[0]["severity"] == "warning"


def test_missing_market_calendar_does_not_count_calendar_day_as_trading_day(
    tmp_path,
) -> None:
    observed_at = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    service = BrokerConnectorSoakService(
        db=db,
        connectors=[FakeReadOnlyBrokerConnector(_snapshot(observed_at))],
        clock=lambda: observed_at,
    )

    observation = service.capture()["observations"][0]

    assert observation["soak_status"] == "degraded"
    assert "market_calendar_missing" in observation["blockers"]
    assert observation["market_calendar"]["status"] == "not_available"
    assert observation["qualifies_for_healthy_soak_day"] is False
    alerts = db.list_automation_alerts_sync(status="open")
    assert len(alerts) == 1
    assert alerts[0]["category"] == "broker_connector_soak"


def test_submit_capability_blocks_readonly_soak_observation(tmp_path) -> None:
    observed_at = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    _seed_trading_days(db, ["2026-07-10"])
    connector = FakeReadOnlyBrokerConnector(
        _snapshot(observed_at),
        capabilities=BrokerConnectorCapabilities(can_submit_orders=True),
    )
    service = BrokerConnectorSoakService(
        db=db,
        connectors=[connector],
        clock=lambda: observed_at,
    )

    observation = service.capture()["observations"][0]

    assert observation["soak_status"] == "blocked"
    assert "connector_exposes_submit_capability" in observation["blockers"]
    assert observation["broker_submission_enabled"] is False


def test_required_source_contract_missing_blocks_soak_observation(tmp_path) -> None:
    observed_at = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    _seed_trading_days(db, ["2026-07-10"])

    class ContractRequiredReadOnlyConnector(FakeReadOnlyBrokerConnector):
        requires_source_contract = True

    service = BrokerConnectorSoakService(
        db=db,
        connectors=[ContractRequiredReadOnlyConnector(_snapshot(observed_at))],
        clock=lambda: observed_at,
    )

    observation = service.capture()["observations"][0]

    assert observation["soak_status"] == "blocked"
    assert "source_contract_missing" in observation["blockers"]
    assert observation["qualifies_for_healthy_soak_day"] is False
    assert observation["broker_submission_enabled"] is False


def test_incomplete_required_source_scope_blocks_soak_observation(tmp_path) -> None:
    observed_at = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    _seed_trading_days(db, ["2026-07-10"])

    class ContractRequiredReadOnlyConnector(FakeReadOnlyBrokerConnector):
        requires_source_contract = True

    snapshot = replace(
        _snapshot(observed_at),
        source_contract=BrokerConnectorSourceContract(
            schema_version="karkinos.readonly_broker_snapshot_export.v2",
            connector_id="fixture-readonly-soak",
            deployment_identity="synthetic-reviewed-deployment",
            batch_id="synthetic-batch",
            cursor_previous=0,
            cursor_current=1,
            trading_day="2026-07-10",
            session_phase="intraday",
            heartbeat_at=observed_at.isoformat(),
            cash_complete=True,
            positions_complete=True,
            orders_complete=False,
            fills_complete=True,
        ),
    )
    service = BrokerConnectorSoakService(
        db=db,
        connectors=[ContractRequiredReadOnlyConnector(snapshot)],
        clock=lambda: observed_at,
    )

    observation = service.capture()["observations"][0]

    assert observation["soak_status"] == "blocked"
    assert "source_scope_incomplete:orders" in observation["blockers"]
    assert observation["source_contract"]["orders_complete"] is False
    assert observation["qualifies_for_healthy_soak_day"] is False
    assert observation["broker_submission_enabled"] is False


def test_source_sequence_advances_atomically_and_exact_replay_is_reused(
    tmp_path,
) -> None:
    first_at = datetime(2026, 7, 10, 8, 1, tzinfo=timezone.utc)
    second_at = first_at + timedelta(minutes=1)
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    _seed_trading_days(db, ["2026-07-10"])

    first_snapshot = _sequenced_snapshot(
        first_at,
        cursor_previous=0,
        cursor_current=1,
        batch_id="batch-1",
    )
    first = _capture_sequenced(db, first_snapshot, observed_at=first_at)
    second_snapshot = _sequenced_snapshot(
        second_at,
        cursor_previous=1,
        cursor_current=2,
        batch_id="batch-2",
    )
    second = _capture_sequenced(db, second_snapshot, observed_at=second_at)
    replay = _capture_sequenced(db, second_snapshot, observed_at=second_at)
    historical_replay = _capture_sequenced(
        db,
        first_snapshot,
        observed_at=second_at,
    )

    assert first["soak_status"] == "healthy"
    assert first["source_sequence"]["status"] == "initial"
    assert first["source_sequence"]["state_advanced"] is True
    assert second["soak_status"] == "healthy"
    assert second["source_sequence"]["status"] == "advanced"
    assert second["source_sequence"]["expected_previous_cursor"] == 1
    assert replay["event_id"] == second["event_id"]
    assert replay["reused"] is True
    assert historical_replay["event_id"] == first["event_id"]
    assert historical_replay["reused"] is True
    with sqlite3.connect(db._path) as conn:
        state = conn.execute(
            "SELECT last_cursor FROM broker_connector_soak_sequence_state"
        ).fetchone()
        batch_count = conn.execute(
            "SELECT COUNT(*) FROM broker_connector_soak_sequence_batches"
        ).fetchone()[0]
    assert state == (2,)
    assert batch_count == 2


def test_cursor_gap_does_not_advance_and_missing_batch_can_recover(tmp_path) -> None:
    first_at = datetime(2026, 7, 10, 8, 1, tzinfo=timezone.utc)
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    _seed_trading_days(db, ["2026-07-10"])
    _capture_sequenced(
        db,
        _sequenced_snapshot(
            first_at,
            cursor_previous=0,
            cursor_current=1,
            batch_id="batch-1",
        ),
        observed_at=first_at,
    )

    gap_at = first_at + timedelta(minutes=2)
    gap = _capture_sequenced(
        db,
        _sequenced_snapshot(
            gap_at,
            cursor_previous=2,
            cursor_current=3,
            batch_id="batch-3",
        ),
        observed_at=gap_at,
    )
    recovered_at = first_at + timedelta(minutes=1)
    recovered = _capture_sequenced(
        db,
        _sequenced_snapshot(
            recovered_at,
            cursor_previous=1,
            cursor_current=2,
            batch_id="batch-2",
        ),
        observed_at=recovered_at,
    )

    assert gap["soak_status"] == "blocked"
    assert "source_sequence_cursor_gap" in gap["blockers"]
    assert gap["source_sequence"]["state_advanced"] is False
    assert recovered["soak_status"] == "healthy"
    assert recovered["source_sequence"]["status"] == "advanced"


def test_out_of_order_conflict_deployment_drift_and_time_regression_block(
    tmp_path,
) -> None:
    first_at = datetime(2026, 7, 10, 8, 1, tzinfo=timezone.utc)
    second_at = first_at + timedelta(minutes=1)
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    _seed_trading_days(db, ["2026-07-10"])
    _capture_sequenced(
        db,
        _sequenced_snapshot(
            first_at,
            cursor_previous=0,
            cursor_current=1,
            batch_id="batch-1",
        ),
        observed_at=first_at,
    )
    _capture_sequenced(
        db,
        _sequenced_snapshot(
            second_at,
            cursor_previous=1,
            cursor_current=2,
            batch_id="batch-2",
        ),
        observed_at=second_at,
    )

    out_of_order = _capture_sequenced(
        db,
        _sequenced_snapshot(
            first_at,
            cursor_previous=0,
            cursor_current=1,
            batch_id="older-batch",
        ),
        observed_at=second_at,
    )
    conflict = _capture_sequenced(
        db,
        _sequenced_snapshot(
            second_at,
            cursor_previous=1,
            cursor_current=2,
            batch_id="conflicting-batch",
            balance="100001",
        ),
        observed_at=second_at,
    )
    deployment_drift = _capture_sequenced(
        db,
        _sequenced_snapshot(
            second_at + timedelta(minutes=1),
            cursor_previous=2,
            cursor_current=3,
            batch_id="batch-3-new-deployment",
            deployment_identity="unexpected-deployment",
        ),
        observed_at=second_at + timedelta(minutes=1),
    )
    time_regression = _capture_sequenced(
        db,
        _sequenced_snapshot(
            second_at,
            cursor_previous=2,
            cursor_current=3,
            batch_id="batch-3-time-regression",
        ),
        observed_at=second_at,
    )

    assert "source_sequence_cursor_out_of_order" in out_of_order["blockers"]
    assert "source_sequence_cursor_evidence_conflict" in conflict["blockers"]
    assert "source_sequence_deployment_drift" in deployment_drift["blockers"]
    assert "source_sequence_time_out_of_order" in time_regression["blockers"]
    assert all(
        item["soak_status"] == "blocked"
        for item in (out_of_order, conflict, deployment_drift, time_regression)
    )


def test_partial_batch_does_not_advance_initial_cursor(tmp_path) -> None:
    first_at = datetime(2026, 7, 10, 8, 1, tzinfo=timezone.utc)
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    _seed_trading_days(db, ["2026-07-10"])

    partial = _capture_sequenced(
        db,
        _sequenced_snapshot(
            first_at,
            cursor_previous=0,
            cursor_current=1,
            batch_id="partial-batch-1",
            complete=False,
        ),
        observed_at=first_at,
    )
    skipped = _capture_sequenced(
        db,
        _sequenced_snapshot(
            first_at + timedelta(minutes=1),
            cursor_previous=1,
            cursor_current=2,
            batch_id="batch-2",
        ),
        observed_at=first_at + timedelta(minutes=1),
    )
    corrected = _capture_sequenced(
        db,
        _sequenced_snapshot(
            first_at + timedelta(seconds=30),
            cursor_previous=0,
            cursor_current=1,
            batch_id="batch-1-corrected",
        ),
        observed_at=first_at + timedelta(seconds=30),
    )

    assert partial["soak_status"] == "blocked"
    assert "source_sequence_partial_batch" in partial["blockers"]
    assert skipped["soak_status"] == "blocked"
    assert "source_sequence_cursor_gap" in skipped["blockers"]
    assert corrected["soak_status"] == "healthy"
    assert corrected["source_sequence"]["status"] == "initial"


def test_concurrent_conflicting_initial_batches_cannot_both_advance(tmp_path) -> None:
    observed_at = datetime(2026, 7, 10, 8, 1, tzinfo=timezone.utc)
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    _seed_trading_days(db, ["2026-07-10"])
    snapshots = [
        _sequenced_snapshot(
            observed_at,
            cursor_previous=0,
            cursor_current=1,
            batch_id=f"concurrent-batch-{index}",
            balance=str(100000 + index),
        )
        for index in (1, 2)
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda snapshot: _capture_sequenced(
                    db,
                    snapshot,
                    observed_at=observed_at,
                ),
                snapshots,
            )
        )

    assert sorted(result["soak_status"] for result in results) == [
        "blocked",
        "healthy",
    ]
    blocked = next(result for result in results if result["soak_status"] == "blocked")
    assert "source_sequence_cursor_evidence_conflict" in blocked["blockers"]
    with sqlite3.connect(db._path) as conn:
        state_count = conn.execute(
            "SELECT COUNT(*) FROM broker_connector_soak_sequence_state"
        ).fetchone()[0]
        batch_count = conn.execute(
            "SELECT COUNT(*) FROM broker_connector_soak_sequence_batches"
        ).fetchone()[0]
    assert state_count == 1
    assert batch_count == 1


def test_sequence_event_and_cursor_state_roll_back_together(
    tmp_path,
    monkeypatch,
) -> None:
    observed_at = datetime(2026, 7, 10, 8, 1, tzinfo=timezone.utc)
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    _seed_trading_days(db, ["2026-07-10"])

    def fail_after_event_insert(*args, **kwargs):
        raise RuntimeError("synthetic state advance failure")

    monkeypatch.setattr(
        "server.services.broker_connector_soak._advance_source_sequence_state",
        fail_after_event_insert,
    )

    with pytest.raises(RuntimeError, match="synthetic state advance failure"):
        _capture_sequenced(
            db,
            _sequenced_snapshot(
                observed_at,
                cursor_previous=0,
                cursor_current=1,
                batch_id="rollback-batch-1",
            ),
            observed_at=observed_at,
        )

    assert db.list_events_sync(event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE) == []
    with sqlite3.connect(db._path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        for table in tables & {
            "broker_connector_soak_sequence_state",
            "broker_connector_soak_sequence_batches",
        }:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_soak_reads_do_not_initialize_sequence_schema(tmp_path) -> None:
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    service = BrokerConnectorSoakService(db=db, connectors=[])

    assert service.list_observations() == []
    assert service.get_status()["observation_count"] == 0

    with sqlite3.connect(db._path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "broker_connector_soak_sequence_state" not in tables
    assert "broker_connector_soak_sequence_batches" not in tables


def test_legacy_boolean_healthy_record_is_observed_but_never_qualified(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    observed_at = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)
    db.append_event_sync(
        event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
        timestamp=observed_at.isoformat(),
        entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
        entity_id="legacy-boolean-healthy-observation",
        source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
        source_ref="legacy-readonly-soak",
        payload={
            "observation_id": "legacy-boolean-healthy-observation",
            "connector_id": "legacy-readonly-soak",
            "trading_day": "2026-07-10",
            "soak_status": "healthy",
            "qualifies_for_healthy_soak_day": True,
            "blockers": [],
            "broker_submission_enabled": False,
        },
    )

    status = BrokerConnectorSoakService(db=db, connectors=[]).get_status()

    summary = status["connectors"][0]
    assert summary["observed_healthy_trading_day_count"] == 1
    assert summary["healthy_trading_day_count"] == 0
    assert summary["latest_source_sequence_accepted"] is False
    assert summary["operational_soak_complete"] is False
    assert "latest_source_sequence_not_accepted:legacy-readonly-soak" in (
        status["promotion_blockers"]
    )


def test_twenty_unsequenced_healthy_days_cannot_complete_operations_soak(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    start = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
    trading_datetimes: list[datetime] = []
    candidate = start
    while len(trading_datetimes) < 20:
        if candidate.astimezone(timezone(timedelta(hours=8))).weekday() < 5:
            trading_datetimes.append(candidate)
        candidate += timedelta(days=1)
    _seed_trading_days(
        db,
        [
            value.astimezone(timezone(timedelta(hours=8))).date().isoformat()
            for value in trading_datetimes
        ],
    )
    status = None

    for captured_at in trading_datetimes:
        observed_at = captured_at + timedelta(minutes=5)
        service = BrokerConnectorSoakService(
            db=db,
            connectors=[FakeReadOnlyBrokerConnector(_snapshot(captured_at))],
            clock=lambda value=observed_at: value,
        )
        service.capture()
        status = service.get_status()

    assert status is not None
    summary = status["connectors"][0]
    assert summary["observed_healthy_trading_day_count"] == 20
    assert summary["healthy_trading_day_count"] == 0
    assert summary["remaining_trading_days"] == 20
    assert summary["operational_soak_complete"] is False
    assert status["operational_soak_complete"] is False
    assert "latest_source_sequence_not_accepted:fixture-readonly-soak" in (
        status["promotion_blockers"]
    )
    assert status["promotion_ready"] is False
    assert status["owner_acceptance_recorded"] is False
    assert status["account_truth_reconciliation_linked"] is False


def test_twenty_sequence_accepted_days_complete_operations_soak_only(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    start = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
    trading_datetimes: list[datetime] = []
    candidate = start
    while len(trading_datetimes) < 20:
        if candidate.astimezone(timezone(timedelta(hours=8))).weekday() < 5:
            trading_datetimes.append(candidate)
        candidate += timedelta(days=1)
    _seed_trading_days(
        db,
        [
            value.astimezone(timezone(timedelta(hours=8))).date().isoformat()
            for value in trading_datetimes
        ],
    )
    status = None

    for index, captured_at in enumerate(trading_datetimes, start=1):
        observed_at = captured_at + timedelta(minutes=5)
        service = BrokerConnectorSoakService(
            db=db,
            connectors=[
                ContractRequiredReadOnlyConnector(
                    _sequenced_snapshot(
                        captured_at,
                        cursor_previous=index - 1,
                        cursor_current=index,
                        batch_id=f"accepted-soak-batch-{index}",
                    )
                )
            ],
            clock=lambda value=observed_at: value,
        )
        status = service.capture()["status"]

    assert status is not None
    summary = status["connectors"][0]
    assert summary["observed_healthy_trading_day_count"] == 20
    assert summary["healthy_trading_day_count"] == 20
    assert summary["sequence_accepted_trading_day_count"] == 20
    assert summary["remaining_trading_days"] == 0
    assert summary["latest_source_sequence_accepted"] is True
    assert summary["operational_soak_complete"] is True
    assert status["operational_soak_complete"] is True
    assert status["promotion_ready"] is False
    assert status["owner_acceptance_recorded"] is False
    assert status["account_truth_reconciliation_linked"] is False


def test_connector_exception_records_blocked_observation_without_write_authority(
    tmp_path,
) -> None:
    observed_at = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    _seed_trading_days(db, ["2026-07-10"])

    class FailingReadOnlyConnector:
        connector_id = "failing-readonly"
        capabilities = BrokerConnectorCapabilities()

        def read_account_snapshot(self):
            raise RuntimeError("synthetic read failure")

    service = BrokerConnectorSoakService(
        db=db,
        connectors=[FailingReadOnlyConnector()],
        clock=lambda: observed_at,
    )

    observation = service.capture()["observations"][0]

    assert observation["soak_status"] == "blocked"
    assert observation["blockers"] == ["connector_read_failed:RuntimeError"]
    assert observation["does_not_submit_broker_order"] is True
    assert observation["does_not_mutate_oms"] is True
    assert observation["does_not_mutate_production_ledger"] is True
