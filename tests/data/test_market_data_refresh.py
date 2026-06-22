"""Market data refresh boundary tests."""

from __future__ import annotations

from datetime import UTC, datetime

from core.types import AssetClass, BarFrequency, Symbol
from data.market_data import (
    MarketDataEventKind,
    MarketDataRecord,
    MarketDataRecordMetadata,
    MarketDataStatus,
)
from data.market_data_refresh import (
    MarketDataRefreshTaskKind,
    MarketDataRefreshTrigger,
    build_market_data_refresh_tasks,
    run_market_data_refresh,
)


def test_manual_refresh_plan_covers_intraday_close_and_fund_nav_without_trading_effects() -> (
    None
):
    requested_at = datetime(2026, 6, 18, 15, 45, tzinfo=UTC)

    tasks = build_market_data_refresh_tasks(
        trigger=MarketDataRefreshTrigger.MANUAL,
        requested_at=requested_at,
        symbols_by_asset_class={
            AssetClass.STOCK: (Symbol("600519"),),
            AssetClass.FUND: (Symbol("018125"),),
        },
    )
    result = run_market_data_refresh(_FixtureRefreshAdapter(), tasks)

    assert [task.kind for task in result.tasks] == [
        MarketDataRefreshTaskKind.INTRADAY_QUOTE,
        MarketDataRefreshTaskKind.CLOSE_PRICE_BAR,
        MarketDataRefreshTaskKind.FUND_NAV_CONFIRMATION,
    ]
    assert result.trigger == MarketDataRefreshTrigger.MANUAL
    assert result.trading_behavior_changed is False
    assert result.broker_order_submission_enabled is False
    assert result.manual_confirmation_required_unchanged is True
    assert result.total_records == 3
    assert result.to_payload()["safety"] == {
        "trading_behavior_changed": False,
        "broker_order_submission_enabled": False,
        "manual_confirmation_required_unchanged": True,
    }


def test_scheduled_refresh_dispatches_adapter_methods_for_expected_asset_groups() -> (
    None
):
    requested_at = datetime(2026, 6, 18, 16, 0, tzinfo=UTC)
    adapter = _FixtureRefreshAdapter()
    tasks = build_market_data_refresh_tasks(
        trigger=MarketDataRefreshTrigger.SCHEDULED,
        requested_at=requested_at,
        symbols_by_asset_class={
            AssetClass.STOCK: (Symbol("600519"), Symbol("601985")),
            AssetClass.FUND: (Symbol("018125"),),
        },
    )

    result = run_market_data_refresh(adapter, tasks)

    assert adapter.calls == [
        ("snapshot", Symbol("600519"), AssetClass.STOCK),
        ("snapshot", Symbol("601985"), AssetClass.STOCK),
        ("daily", Symbol("600519"), AssetClass.STOCK),
        ("daily", Symbol("601985"), AssetClass.STOCK),
        ("snapshot", Symbol("018125"), AssetClass.FUND),
    ]
    assert result.trigger == MarketDataRefreshTrigger.SCHEDULED
    assert result.status == "success"
    assert result.failed_symbols == []
    assert result.refreshed_symbols == ["018125", "600519", "601985"]


class _FixtureRefreshAdapter:
    def __init__(self) -> None:
        self.calls = []

    def fetch_daily_bars(self, symbol, start, end, asset_class=AssetClass.STOCK):
        self.calls.append(("daily", symbol, asset_class))
        return [_record(MarketDataEventKind.DAILY_BAR, symbol, asset_class)]

    def fetch_intraday_bars(
        self,
        symbol,
        start,
        end,
        frequency=BarFrequency.MIN_1,
        asset_class=AssetClass.STOCK,
    ):
        self.calls.append(("intraday", symbol, asset_class))
        return [_record(MarketDataEventKind.INTRADAY_BAR, symbol, asset_class)]

    def fetch_snapshot(self, symbol, asset_class=AssetClass.STOCK):
        self.calls.append(("snapshot", symbol, asset_class))
        status = (
            MarketDataStatus.CONFIRMED
            if asset_class is AssetClass.FUND
            else MarketDataStatus.LIVE
        )
        return [_record(MarketDataEventKind.SNAPSHOT, symbol, asset_class, status)]

    def fetch_ticks(self, symbol, start, end, asset_class=AssetClass.STOCK):
        return []

    def replay(self, symbol, start, end, asset_class=AssetClass.STOCK):
        return []


def _record(
    kind: MarketDataEventKind,
    symbol: Symbol,
    asset_class: AssetClass,
    status: MarketDataStatus = MarketDataStatus.CONFIRMED,
) -> MarketDataRecord:
    observed_at = datetime(2026, 6, 18, 15, 0, tzinfo=UTC)
    return MarketDataRecord(
        kind=kind,
        symbol=symbol,
        asset_class=asset_class,
        timestamp=observed_at,
        values={"close": 10.0},
        frequency=BarFrequency.DAILY,
        metadata=MarketDataRecordMetadata(
            source="fixture_provider",
            status=status,
            observed_at=observed_at,
            trading_session="2026-06-18",
        ),
    )
