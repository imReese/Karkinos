"""DataStore 单元测试。"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from core.types import BarFrequency, Symbol
from data.store import DataStore


@pytest.fixture
def store(tmp_path: Path) -> DataStore:
    return DataStore(root=tmp_path / "store")


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
            "open": [1800.0, 1820.0, 1830.0],
            "high": [1850.0, 1840.0, 1860.0],
            "low": [1790.0, 1810.0, 1820.0],
            "close": [1830.0, 1835.0, 1850.0],
            "volume": [10000.0, 12000.0, 11000.0],
        }
    )


class TestDataStore:
    def test_save_and_load_bars(self, store: DataStore, sample_df: pd.DataFrame):
        symbol = Symbol("600519")
        store.save_bars(symbol, BarFrequency.DAILY, sample_df)

        loaded = store.load_bars(symbol, BarFrequency.DAILY)
        assert loaded is not None
        assert len(loaded) == 3
        assert list(loaded["close"]) == list(sample_df["close"])

    def test_save_bars_persists_rows_to_sqlite(
        self, store: DataStore, sample_df: pd.DataFrame
    ):
        symbol = Symbol("600519")
        store.save_bars(symbol, BarFrequency.DAILY, sample_df)

        with sqlite3.connect(store._meta_path) as conn:
            count = conn.execute(
                """
                SELECT COUNT(*)
                FROM market_bars
                WHERE symbol = ? AND frequency = ?
                """,
                ("600519", BarFrequency.DAILY.value),
            ).fetchone()[0]

        assert count == 3

    def test_load_bars_can_read_from_sqlite_without_parquet(
        self, store: DataStore, sample_df: pd.DataFrame
    ):
        symbol = Symbol("600519")
        store.save_bars(symbol, BarFrequency.DAILY, sample_df)
        parquet_path = (
            store._root / "bars" / BarFrequency.DAILY.value / f"{symbol}.parquet"
        )
        parquet_path.unlink()

        loaded = store.load_bars(symbol, BarFrequency.DAILY)

        assert loaded is not None
        assert len(loaded) == 3
        assert list(loaded["close"]) == list(sample_df["close"])

    def test_sync_parquet_bars_to_database_imports_existing_cache(
        self, store: DataStore, sample_df: pd.DataFrame
    ):
        symbol = Symbol("600519")
        parquet_path = (
            store._root / "bars" / BarFrequency.DAILY.value / f"{symbol}.parquet"
        )
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        sample_df.to_parquet(parquet_path, index=False)

        summary = store.sync_parquet_bars_to_database()

        assert summary["synced_files"] == 1
        assert summary["synced_rows"] == 3
        with sqlite3.connect(store._meta_path) as conn:
            count = conn.execute(
                """
                SELECT COUNT(*)
                FROM market_bars
                WHERE symbol = ? AND frequency = ?
                """,
                ("600519", BarFrequency.DAILY.value),
            ).fetchone()[0]
        assert count == 3
        meta = store.get_meta(symbol, BarFrequency.DAILY)
        assert meta is not None
        assert meta["row_count"] == 3
        assert meta["data_source"] == "local_parquet_sync"

        parquet_path.unlink()
        loaded = store.load_bars(symbol, BarFrequency.DAILY)
        assert loaded is not None
        assert list(loaded["close"]) == list(sample_df["close"])

    def test_load_nonexistent_returns_none(self, store: DataStore):
        result = store.load_bars(Symbol("999999"), BarFrequency.DAILY)
        assert result is None

    def test_get_meta(self, store: DataStore, sample_df: pd.DataFrame):
        symbol = Symbol("600519")
        store.save_bars(symbol, BarFrequency.DAILY, sample_df)

        meta = store.get_meta(symbol, BarFrequency.DAILY)
        assert meta is not None
        assert meta["symbol"] == "600519"
        assert meta["frequency"] == "1d"
        assert meta["row_count"] == 3

    def test_save_bars_persists_dataset_snapshot_audit_metadata(self, store: DataStore):
        symbol = Symbol("600519")
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2024-01-03", "2024-01-02", "2024-01-03"]),
                "open": [1800.0, None, 1830.0],
                "high": [1850.0, 1840.0, 1860.0],
                "low": [1790.0, 1810.0, 1820.0],
                "close": [1830.0, 1835.0, 1850.0],
                "volume": [10000.0, 12000.0, None],
            }
        )

        store.save_bars(
            symbol,
            BarFrequency.DAILY,
            df,
            provider_name="mock_provider",
            data_source="unit_fixture",
            adjustment_mode="qfq",
        )
        meta = store.get_meta(symbol, BarFrequency.DAILY)
        assert meta is not None
        first_dataset_id = meta["dataset_id"]

        assert meta["provider_name"] == "mock_provider"
        assert meta["data_source"] == "unit_fixture"
        assert meta["adjustment_mode"] == "qfq"
        assert meta["duplicate_timestamp_count"] == 1
        assert meta["missing_ohlcv_count"] == 2
        assert meta["is_monotonic"] == 0
        assert meta["diagnostics"] == {
            "duplicate_timestamp_count": 1,
            "missing_ohlcv_count": 2,
            "is_monotonic": False,
            "row_count": 3,
        }

        store.save_bars(
            symbol,
            BarFrequency.DAILY,
            df,
            provider_name="mock_provider",
            data_source="unit_fixture",
            adjustment_mode="qfq",
        )
        meta_after_resave = store.get_meta(symbol, BarFrequency.DAILY)
        assert meta_after_resave is not None
        assert meta_after_resave["dataset_id"] == first_dataset_id

    def test_list_symbols(self, store: DataStore, sample_df: pd.DataFrame):
        store.save_bars(Symbol("600519"), BarFrequency.DAILY, sample_df)
        store.save_bars(Symbol("000001"), BarFrequency.DAILY, sample_df)

        symbols = store.list_symbols(BarFrequency.DAILY)
        assert len(symbols) == 2
        assert Symbol("600519") in symbols
        assert Symbol("000001") in symbols
