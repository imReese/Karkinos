"""Market data reconciliation tests."""

from __future__ import annotations

import pandas as pd
import pytest

from core.types import BarFrequency, InstrumentType, Symbol
from data.market_data_reconciliation import (
    reconcile_market_bars,
    reconcile_store_with_provider,
)
from data.store import DataStore


def _intraday_frame():
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-06-15 09:30", "2026-06-15 09:35"]),
            "open": [10.0, 11.0],
            "high": [10.0, 11.0],
            "low": [10.0, 11.0],
            "close": [10.0, 11.0],
            "volume": [1000.0, 1100.0],
        }
    )


@pytest.mark.parametrize("frequency", [BarFrequency.MIN_1, BarFrequency.MIN_5])
def test_intraday_reconciliation_detects_earlier_bar_mismatch(frequency):
    local = _intraday_frame()
    provider = local.copy()
    provider.loc[0, "close"] = 99.0

    report = reconcile_market_bars(
        Symbol("600001"), frequency, local, provider, provider_name="synthetic"
    )

    assert report.status == "mismatched"
    assert report.local_rows == report.provider_rows == report.checked_rows == 2
    assert report.mismatch_count == 1
    assert report.mismatches[0].timestamp == "2026-06-15T09:30:00"
    assert report.mismatches[0].field == "close"
    assert report.mismatches[0].local_value == 10.0
    assert report.mismatches[0].provider_value == 99.0


@pytest.mark.parametrize("frequency", [BarFrequency.MIN_1, BarFrequency.MIN_5])
def test_intraday_reconciliation_reports_missing_minute(frequency):
    local = _intraday_frame()
    report = reconcile_market_bars(
        Symbol("600001"),
        frequency,
        local,
        local.iloc[1:],
        provider_name="synthetic",
    )

    assert report.status == "mismatched"
    assert report.local_rows == 2
    assert report.provider_rows == report.checked_rows == 1
    assert report.mismatch_count == 1
    assert report.mismatches[0].timestamp == "2026-06-15T09:30:00"
    assert report.mismatches[0].issue_type == "missing_provider_row"


@pytest.mark.parametrize("frequency", [BarFrequency.MIN_1, BarFrequency.MIN_5])
def test_intraday_reconciliation_matches_all_bars_and_deduplicates_only_exact_key(
    frequency,
):
    local = _intraday_frame()
    earlier_version = local.iloc[:1].copy()
    earlier_version.loc[0, "close"] = 99.0
    provider = pd.concat([earlier_version, local], ignore_index=True)
    original = provider.copy(deep=True)

    report = reconcile_market_bars(
        Symbol("600001"), frequency, local, provider, provider_name="synthetic"
    )

    assert report.status == "matched"
    assert report.local_rows == report.provider_rows == report.checked_rows == 2
    assert report.mismatch_count == 0
    pd.testing.assert_frame_equal(provider, original)


def test_intraday_reconciliation_matches_equivalent_timezone_instants():
    local = _intraday_frame()
    local["timestamp"] = local["timestamp"].dt.tz_localize("Asia/Shanghai")
    provider = local.copy()
    provider["timestamp"] = provider["timestamp"].dt.tz_convert("UTC")

    report = reconcile_market_bars(
        Symbol("600001"),
        BarFrequency.MIN_1,
        local,
        provider,
        provider_name="synthetic",
    )

    assert report.status == "matched"
    assert report.checked_rows == 2
    assert report.mismatches == []


@pytest.mark.parametrize("frame", [None, pd.DataFrame()])
def test_reconciliation_with_no_evidence_is_missing_both(frame):
    report = reconcile_market_bars(
        Symbol("600001"),
        BarFrequency.DAILY,
        frame,
        frame,
        provider_name="synthetic",
    )

    assert report.status == "missing_both"
    assert report.checked_rows == report.local_rows == report.provider_rows == 0
    assert report.mismatch_count == 0
    assert report.mismatches == []


def test_reconcile_market_bars_reports_matched_provider_rows():
    local = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-06-12", "2026-06-15"]),
            "open": [9.0, 9.2],
            "high": [9.3, 9.4],
            "low": [8.9, 9.1],
            "close": [9.13, 9.25],
            "volume": [1000.0, 1200.0],
        }
    )
    provider = local.copy()

    report = reconcile_market_bars(
        Symbol("600001"),
        BarFrequency.DAILY,
        local,
        provider,
        provider_name="fixture_provider",
    )

    assert report.status == "matched"
    assert report.symbol == "600001"
    assert report.frequency == "1d"
    assert report.provider_name == "fixture_provider"
    assert report.checked_rows == 2
    assert report.mismatch_count == 0
    assert report.mismatches == []


def test_reconcile_market_bars_reports_price_and_missing_row_differences():
    local = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-06-12", "2026-06-15"]),
            "open": [9.0, 9.2],
            "high": [9.3, 9.4],
            "low": [8.9, 9.1],
            "close": [9.13, 9.25],
            "volume": [1000.0, 1200.0],
        }
    )
    provider = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-06-12", "2026-01-15"]),
            "open": [9.0, 9.5],
            "high": [9.3, 9.8],
            "low": [8.9, 9.4],
            "close": [9.21, 9.7],
            "volume": [1000.0, 1500.0],
        }
    )

    report = reconcile_market_bars(
        Symbol("600001"),
        BarFrequency.DAILY,
        local,
        provider,
        provider_name="fixture_provider",
        price_tolerance=0.01,
    )

    assert report.status == "mismatched"
    assert report.checked_rows == 1
    assert report.mismatch_count == 3
    assert [item.issue_type for item in report.mismatches] == [
        "value_mismatch",
        "missing_provider_row",
        "missing_local_row",
    ]
    assert report.mismatches[0].timestamp == "2026-06-12"
    assert report.mismatches[0].field == "close"
    assert report.mismatches[0].local_value == 9.13
    assert report.mismatches[0].provider_value == 9.21
    assert report.mismatches[1].timestamp == "2026-06-15"
    assert report.mismatches[2].timestamp == "2026-01-15"


def test_reconcile_store_with_provider_fetches_requested_range(tmp_path):
    store = DataStore(tmp_path / "store")
    symbol = Symbol("600001")
    local = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-06-12", "2026-06-15"]),
            "open": [9.0, 9.2],
            "high": [9.3, 9.4],
            "low": [8.9, 9.1],
            "close": [9.13, 9.25],
            "volume": [1000.0, 1200.0],
        }
    )
    store.save_bars(
        symbol,
        BarFrequency.DAILY,
        local,
        instrument_type=InstrumentType.STOCK,
    )
    provider = _FakeSource(local.copy())

    report = reconcile_store_with_provider(
        store,
        provider,
        symbol,
        pd.Timestamp("2026-06-12").to_pydatetime(),
        pd.Timestamp("2026-06-15").to_pydatetime(),
        BarFrequency.DAILY,
        provider_name="fixture_provider",
    )

    assert report.status == "matched"
    assert report.checked_rows == 2
    assert provider.calls == [("600001", "2026-06-12", "2026-06-15", "1d", "stock")]


class _FakeSource:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls: list[tuple[str, str, str, str, str]] = []

    def fetch_bars(self, symbol, start, end, frequency, asset_class):
        self.calls.append(
            (
                str(symbol),
                start.date().isoformat(),
                end.date().isoformat(),
                frequency.value,
                asset_class.value,
            )
        )
        return self.frame
