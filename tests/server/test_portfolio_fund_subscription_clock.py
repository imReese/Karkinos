"""Fund-subscription cutoff uses Shanghai time for UI and direct callers."""

from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from server.db import AppDatabase
from server.services.portfolio.trades import (
    CreatedPendingFundOrder,
    ManualTradeRequest,
    PortfolioTradeCommandService,
    fund_target_trade_date,
)
from tests.server.test_portfolio_trade_uow import _persist_nav_evidence


@pytest.mark.parametrize("clock", ["naive", "shanghai", "utc", "utc_z"])
@pytest.mark.parametrize(
    ("local_time", "target_date"),
    [
        ("14:59:59", "2026-08-26"),
        ("15:00:00", "2026-08-27"),
        ("16:00:00", "2026-08-27"),
    ],
)
def test_subscription_cutoff_is_independent_of_input_timezone(
    local_time, target_date, clock
) -> None:
    local = datetime.fromisoformat(f"2026-08-26T{local_time}")
    if clock == "naive":
        timestamp = local.isoformat()
    else:
        localized = local.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        if clock == "shanghai":
            timestamp = localized.isoformat()
        else:
            timestamp = localized.astimezone(timezone.utc).isoformat()
            if clock == "utc_z":
                timestamp = timestamp.replace("+00:00", "Z")

    assert fund_target_trade_date(timestamp) == target_date


@pytest.mark.parametrize(
    ("timestamp", "target_date"),
    [
        ("2026-08-26T16:30:00Z", "2026-08-27"),
        ("2026-08-26T23:30:00Z", "2026-08-27"),
        # Preserve the existing next-calendar-day policy after Friday's cutoff.
        ("2026-08-28T08:00:00Z", "2026-08-29"),
    ],
)
def test_subscription_target_uses_the_shanghai_date(timestamp, target_date) -> None:
    assert fund_target_trade_date(timestamp) == target_date


@pytest.fixture
def subscription_service(tmp_path):
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    service = PortfolioTradeCommandService(
        SimpleNamespace(db=database, config=SimpleNamespace(assets=[]), scheduler=None)
    )
    return service, database


def _subscription(timestamp: str) -> ManualTradeRequest:
    return ManualTradeRequest(
        command_id="synthetic-subscription-command",
        operator_id="synthetic-owner",
        timestamp=timestamp,
        symbol="012999",
        direction="buy",
        amount=200.0,
        asset_class="fund",
    )


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-08-26T15:00:00",
        "2026-08-26T15:00:00+08:00",
        "2026-08-26T07:00:00.000Z",
    ],
)
def test_subscription_create_persists_the_local_cutoff_date(
    subscription_service, timestamp
) -> None:
    service, database = subscription_service
    created = service.create(_subscription(timestamp))
    assert isinstance(created, CreatedPendingFundOrder)
    rows = database.get_pending_fund_orders_sync(status="pending")

    assert len(rows) == 1
    assert created.order["target_trade_date"] == "2026-08-27"
    assert rows[0]["target_trade_date"] == "2026-08-27"
    assert rows[0]["submitted_at"] == timestamp
    assert database.get_ledger_entries_sync(limit=10) == []


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-08-26T15:00:00",
        "2026-08-26T15:00:00+08:00",
        "2026-08-26T07:00:00.000Z",
    ],
)
def test_after_cutoff_subscription_rejects_same_day_confirmed_nav(
    subscription_service, timestamp, tmp_path
) -> None:
    service, database = subscription_service
    created = service.create(_subscription(timestamp))
    assert isinstance(created, CreatedPendingFundOrder)
    _persist_nav_evidence(tmp_path / "app.db", nav_date="2026-08-26")

    with pytest.raises(RuntimeError, match="NAV evidence predates target trade date"):
        service.confirm_pending(
            order_id=int(created.order["id"]),
            command_id="synthetic-confirmation-command",
            operator_id="synthetic-owner",
            evidence_fetch_run_id="manual-nav-run-1",
        )

    assert len(database.get_pending_fund_orders_sync(status="pending")) == 1
    assert database.get_ledger_entries_sync(limit=10) == []
