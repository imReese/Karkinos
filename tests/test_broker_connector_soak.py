from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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
from data.market_calendar import build_static_market_calendar_snapshot
from server.db import AppDatabase
from server.services.broker_connector_soak import (
    BROKER_CONNECTOR_SOAK_EVENT_TYPE,
    BrokerConnectorSoakService,
)


def _snapshot(captured_at: datetime) -> BrokerConnectorSnapshot:
    return BrokerConnectorSnapshot(
        connector_id="qmt-readonly-soak",
        source_name="synthetic QMT readonly export",
        account_id="private-account-id-must-not-leak",
        account_alias="qmt-primary",
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
    assert observation["qualifies_for_healthy_soak_day"] is True
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
    assert summary["healthy_trading_day_count"] == 1
    assert summary["remaining_trading_days"] == 19
    assert status["promotion_ready"] is False
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


def test_twenty_healthy_days_complete_operations_soak_but_not_promotion(
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
    assert summary["healthy_trading_day_count"] == 20
    assert summary["remaining_trading_days"] == 0
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
