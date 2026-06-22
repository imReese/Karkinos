"""Market data reliability contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

from core.types import AssetClass, BarFrequency, Symbol
from data.market_data import (
    MarketDataAdapter,
    MarketDataEventKind,
    MarketDataRecord,
    MarketDataRecordMetadata,
    MarketDataStatus,
    normalize_market_data_status,
)


def test_market_data_status_vocabulary_is_stable_and_user_readable() -> None:
    assert [status.value for status in MarketDataStatus] == [
        "confirmed",
        "live",
        "cache",
        "estimated",
        "missing",
        "stale",
        "confirmed_nav_missing",
    ]
    assert MarketDataStatus.CONFIRMED.label_zh == "已确认"
    assert MarketDataStatus.CONFIRMED_NAV_MISSING.label_zh == "确认净值缺失"
    assert MarketDataStatus.CONFIRMED.is_confirmed is True
    assert MarketDataStatus.LIVE.is_confirmed is False
    assert MarketDataStatus.ESTIMATED.can_be_presented_as_confirmed is False


def test_normalize_market_data_status_maps_legacy_and_provider_status_values() -> None:
    assert normalize_market_data_status("fresh") == MarketDataStatus.CONFIRMED
    assert normalize_market_data_status("cache_only") == MarketDataStatus.CACHE
    assert normalize_market_data_status("confirmed NAV missing") == (
        MarketDataStatus.CONFIRMED_NAV_MISSING
    )
    assert normalize_market_data_status("quote_older_than_expected_session") == (
        MarketDataStatus.STALE
    )
    assert normalize_market_data_status(None) == MarketDataStatus.MISSING


def test_market_data_record_serializes_shared_status_metadata_for_all_event_kinds() -> (
    None
):
    observed_at = datetime(2026, 6, 18, 15, 0, tzinfo=UTC)
    records = [
        _record(kind, observed_at=observed_at)
        for kind in (
            MarketDataEventKind.DAILY_BAR,
            MarketDataEventKind.INTRADAY_BAR,
            MarketDataEventKind.SNAPSHOT,
            MarketDataEventKind.TICK,
            MarketDataEventKind.REPLAY,
        )
    ]

    for record in records:
        payload = record.to_payload()
        assert payload["kind"] == record.kind.value
        assert payload["symbol"] == "600519"
        assert payload["asset_class"] == "stock"
        assert payload["frequency"] == "1d"
        assert payload["timestamp"] == "2026-06-18T15:00:00+00:00"
        assert payload["source"] == "fixture_provider"
        assert payload["source_symbol"] == "600519.SH"
        assert payload["status"] == "confirmed"
        assert payload["status_label_zh"] == "已确认"
        assert payload["trading_session"] == "2026-06-18"
        assert payload["adjustment_mode"] == "qfq"
        assert payload["freshness"] == {"age_seconds": 30}
        assert payload["limitations"] == ["synthetic fixture"]
        assert payload["values"] == {"close": 1688.0}


def test_market_data_adapter_protocol_covers_daily_intraday_snapshot_tick_and_replay() -> (
    None
):
    adapter: MarketDataAdapter = _FixtureMarketDataAdapter()
    start = datetime(2026, 6, 18, 9, 30, tzinfo=UTC)
    end = datetime(2026, 6, 18, 15, 0, tzinfo=UTC)

    records = [
        adapter.fetch_daily_bars(Symbol("600519"), start, end)[0],
        adapter.fetch_intraday_bars(Symbol("600519"), start, end, BarFrequency.MIN_1)[
            0
        ],
        adapter.fetch_snapshot(Symbol("600519"))[0],
        adapter.fetch_ticks(Symbol("600519"), start, end)[0],
        adapter.replay(Symbol("600519"), start, end)[0],
    ]

    assert {record.kind for record in records} == {
        MarketDataEventKind.DAILY_BAR,
        MarketDataEventKind.INTRADAY_BAR,
        MarketDataEventKind.SNAPSHOT,
        MarketDataEventKind.TICK,
        MarketDataEventKind.REPLAY,
    }
    assert all(
        isinstance(record.metadata.status, MarketDataStatus) for record in records
    )


def _record(
    kind: MarketDataEventKind,
    *,
    observed_at: datetime,
    status: MarketDataStatus = MarketDataStatus.CONFIRMED,
) -> MarketDataRecord:
    return MarketDataRecord(
        kind=kind,
        symbol=Symbol("600519"),
        asset_class=AssetClass.STOCK,
        frequency=BarFrequency.DAILY,
        timestamp=observed_at,
        values={"close": 1688.0},
        metadata=MarketDataRecordMetadata(
            source="fixture_provider",
            source_symbol="600519.SH",
            status=status,
            observed_at=observed_at,
            trading_session="2026-06-18",
            adjustment_mode="qfq",
            freshness={"age_seconds": 30},
            limitations=("synthetic fixture",),
        ),
    )


class _FixtureMarketDataAdapter:
    def fetch_daily_bars(self, symbol, start, end, asset_class=AssetClass.STOCK):
        return [
            _record(MarketDataEventKind.DAILY_BAR, observed_at=end),
        ]

    def fetch_intraday_bars(
        self,
        symbol,
        start,
        end,
        frequency=BarFrequency.MIN_1,
        asset_class=AssetClass.STOCK,
    ):
        return [
            _record(MarketDataEventKind.INTRADAY_BAR, observed_at=end),
        ]

    def fetch_snapshot(self, symbol, asset_class=AssetClass.STOCK):
        return [
            _record(
                MarketDataEventKind.SNAPSHOT,
                observed_at=datetime(2026, 6, 18, 15, 0, tzinfo=UTC),
            ),
        ]

    def fetch_ticks(self, symbol, start, end, asset_class=AssetClass.STOCK):
        return [
            _record(MarketDataEventKind.TICK, observed_at=end),
        ]

    def replay(self, symbol, start, end, asset_class=AssetClass.STOCK):
        return [
            _record(MarketDataEventKind.REPLAY, observed_at=end),
        ]
