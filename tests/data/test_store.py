"""DataStore 单元测试。"""

from __future__ import annotations

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
    return pd.DataFrame({
        "timestamp": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
        "open": [1800.0, 1820.0, 1830.0],
        "high": [1850.0, 1840.0, 1860.0],
        "low": [1790.0, 1810.0, 1820.0],
        "close": [1830.0, 1835.0, 1850.0],
        "volume": [10000.0, 12000.0, 11000.0],
    })


class TestDataStore:
    def test_save_and_load_bars(self, store: DataStore, sample_df: pd.DataFrame):
        symbol = Symbol("600519")
        store.save_bars(symbol, BarFrequency.DAILY, sample_df)

        loaded = store.load_bars(symbol, BarFrequency.DAILY)
        assert loaded is not None
        assert len(loaded) == 3
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

    def test_list_symbols(self, store: DataStore, sample_df: pd.DataFrame):
        store.save_bars(Symbol("600519"), BarFrequency.DAILY, sample_df)
        store.save_bars(Symbol("000001"), BarFrequency.DAILY, sample_df)

        symbols = store.list_symbols(BarFrequency.DAILY)
        assert len(symbols) == 2
        assert Symbol("600519") in symbols
        assert Symbol("000001") in symbols
