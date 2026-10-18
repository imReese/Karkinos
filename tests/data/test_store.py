"""DataStore 单元测试。"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from core.types import BarFrequency, InstrumentType, Symbol
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


@pytest.mark.parametrize("failure_stage", ["write", "replace"])
def test_mirror_failure_keeps_committed_bars_and_metadata_consistent(
    store, sample_df, monkeypatch, caplog, failure_stage
):
    symbol = Symbol("600519")
    store.save_bars(
        symbol, BarFrequency.DAILY, sample_df.iloc[:1], instrument_type="stock"
    )
    mirror = store._root / "bars/1d/stock/600519.parquet"
    previous_mirror = mirror.read_bytes()

    def fail_write(frame, path, **kwargs):
        Path(path).write_bytes(b"partial parquet bytes")
        raise OSError("synthetic mirror write failure")

    def fail_replace(path, target):
        raise OSError("synthetic mirror replace failure")

    if failure_stage == "write":
        monkeypatch.setattr(pd.DataFrame, "to_parquet", fail_write)
    else:
        monkeypatch.setattr(Path, "replace", fail_replace)

    store.append_bars(
        symbol,
        BarFrequency.DAILY,
        sample_df.iloc[1:],
        instrument_type="stock",
    )

    loaded = store.load_bars(symbol, BarFrequency.DAILY, instrument_type="stock")
    metadata = store.get_meta(symbol, BarFrequency.DAILY, instrument_type="stock")
    assert loaded is not None and metadata is not None
    assert len(loaded) == metadata["row_count"] == len(sample_df)
    assert loaded["close"].tolist() == sample_df["close"].tolist()
    assert metadata["end_date"] == str(sample_df["timestamp"].max())
    assert mirror.read_bytes() == previous_mirror
    assert list(mirror.parent.iterdir()) == [mirror]
    assert "mirror" in caplog.text.lower()


@pytest.mark.parametrize("writer", ["append", "parquet_import"])
def test_metadata_failure_rolls_back_bars_and_preserves_existing_metadata(
    store, sample_df, monkeypatch, writer
):
    symbol = Symbol("600519")
    store.save_bars(
        symbol, BarFrequency.DAILY, sample_df.iloc[:1], instrument_type="stock"
    )
    before = store.get_meta(symbol, BarFrequency.DAILY, instrument_type="stock")
    mirror = store._root / "bars/1d/stock/600519.parquet"
    if writer == "parquet_import":
        sample_df.to_parquet(mirror, index=False)
    previous_mirror = mirror.read_bytes()
    save_metadata = store._save_bar_meta

    def fail_metadata(*args, **kwargs):
        save_metadata(*args, **kwargs)
        raise sqlite3.OperationalError("synthetic metadata write failure")

    monkeypatch.setattr(store, "_save_bar_meta", fail_metadata)
    with pytest.raises(sqlite3.OperationalError, match="metadata write failure"):
        if writer == "append":
            store.append_bars(
                symbol,
                BarFrequency.DAILY,
                sample_df.iloc[1:],
                instrument_type="stock",
            )
        else:
            store.sync_parquet_bars_to_database(instrument_type="stock")

    loaded = store.load_bars(symbol, BarFrequency.DAILY, instrument_type="stock")
    assert loaded is not None
    assert loaded["close"].tolist() == sample_df.iloc[:1]["close"].tolist()
    assert store.get_meta(symbol, BarFrequency.DAILY, instrument_type="stock") == before
    assert mirror.read_bytes() == previous_mirror


def test_interrupted_mirror_is_not_imported_as_a_new_instrument(
    store, sample_df, monkeypatch
):
    symbol = Symbol("600519")
    store.save_bars(symbol, BarFrequency.DAILY, sample_df, instrument_type="stock")
    directory = store._root / "bars/1d/stock"

    def fail_publication(*args, **kwargs):
        raise OSError("synthetic interrupted mirror publication")

    with monkeypatch.context() as failure:
        failure.setattr(Path, "replace", fail_publication)
        failure.setattr(Path, "unlink", fail_publication)
        store.save_bars(symbol, BarFrequency.DAILY, sample_df, instrument_type="stock")

    leftovers = [path for path in directory.iterdir() if path.name != "600519.parquet"]
    assert len(leftovers) == 1
    assert len(pd.read_parquet(leftovers[0])) == len(sample_df)
    imported = store.sync_parquet_bars_to_database(instrument_type="stock")
    assert [row["symbol"] for row in imported["files"]] == ["600519"]
    assert (
        store.get_meta(
            Symbol(leftovers[0].stem), BarFrequency.DAILY, instrument_type="stock"
        )
        is None
    )


class TestDataStore:
    def test_save_and_load_bars(self, store: DataStore, sample_df: pd.DataFrame):
        symbol = Symbol("600519")
        store.save_bars(
            symbol,
            BarFrequency.DAILY,
            sample_df,
            instrument_type=InstrumentType.STOCK,
        )

        loaded = store.load_bars(
            symbol,
            BarFrequency.DAILY,
            instrument_type=InstrumentType.STOCK,
        )
        assert loaded is not None
        assert len(loaded) == 3
        assert list(loaded["close"]) == list(sample_df["close"])

    def test_save_bars_persists_rows_to_sqlite(
        self, store: DataStore, sample_df: pd.DataFrame
    ):
        symbol = Symbol("600519")
        store.save_bars(
            symbol,
            BarFrequency.DAILY,
            sample_df,
            instrument_type=InstrumentType.STOCK,
        )

        with sqlite3.connect(store._meta_path) as conn:
            count = conn.execute(
                """
                SELECT COUNT(*)
                FROM market_bars
                WHERE symbol = ? AND instrument_type = 'stock' AND frequency = ?
                """,
                ("600519", BarFrequency.DAILY.value),
            ).fetchone()[0]

        assert count == 3

    def test_load_bars_can_read_from_sqlite_without_parquet(
        self, store: DataStore, sample_df: pd.DataFrame
    ):
        symbol = Symbol("600519")
        store.save_bars(
            symbol,
            BarFrequency.DAILY,
            sample_df,
            instrument_type=InstrumentType.STOCK,
        )
        parquet_path = (
            store._root
            / "bars"
            / BarFrequency.DAILY.value
            / "stock"
            / f"{symbol}.parquet"
        )
        parquet_path.unlink()

        loaded = store.load_bars(
            symbol,
            BarFrequency.DAILY,
            instrument_type=InstrumentType.STOCK,
        )

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
        parquet_path = parquet_path.parent / "stock" / parquet_path.name
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        sample_df.to_parquet(parquet_path, index=False)

        summary = store.sync_parquet_bars_to_database(
            instrument_type=InstrumentType.STOCK
        )

        assert summary["synced_files"] == 1
        assert summary["synced_rows"] == 3
        with sqlite3.connect(store._meta_path) as conn:
            count = conn.execute(
                """
                SELECT COUNT(*)
                FROM market_bars
                WHERE symbol = ? AND instrument_type = 'stock' AND frequency = ?
                """,
                ("600519", BarFrequency.DAILY.value),
            ).fetchone()[0]
        assert count == 3
        meta = store.get_meta(
            symbol,
            BarFrequency.DAILY,
            instrument_type=InstrumentType.STOCK,
        )
        assert meta is not None
        assert meta["row_count"] == 3
        assert meta["data_source"] == "local_parquet_sync"

        parquet_path.unlink()
        loaded = store.load_bars(
            symbol,
            BarFrequency.DAILY,
            instrument_type=InstrumentType.STOCK,
        )
        assert loaded is not None
        assert list(loaded["close"]) == list(sample_df["close"])

    def test_load_nonexistent_returns_none(self, store: DataStore):
        result = store.load_bars(Symbol("999999"), BarFrequency.DAILY)
        assert result is None

    def test_get_meta(self, store: DataStore, sample_df: pd.DataFrame):
        symbol = Symbol("600519")
        store.save_bars(
            symbol,
            BarFrequency.DAILY,
            sample_df,
            instrument_type=InstrumentType.STOCK,
        )

        meta = store.get_meta(
            symbol,
            BarFrequency.DAILY,
            instrument_type=InstrumentType.STOCK,
        )
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
            instrument_type=InstrumentType.STOCK,
        )
        meta = store.get_meta(
            symbol,
            BarFrequency.DAILY,
            instrument_type=InstrumentType.STOCK,
        )
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
            instrument_type=InstrumentType.STOCK,
        )
        meta_after_resave = store.get_meta(
            symbol,
            BarFrequency.DAILY,
            instrument_type=InstrumentType.STOCK,
        )
        assert meta_after_resave is not None
        assert meta_after_resave["dataset_id"] == first_dataset_id

    def test_list_symbols(self, store: DataStore, sample_df: pd.DataFrame):
        store.save_bars(
            Symbol("600519"),
            BarFrequency.DAILY,
            sample_df,
            instrument_type=InstrumentType.STOCK,
        )
        store.save_bars(
            Symbol("000001"),
            BarFrequency.DAILY,
            sample_df,
            instrument_type=InstrumentType.STOCK,
        )

        symbols = store.list_symbols(
            BarFrequency.DAILY,
            instrument_type=InstrumentType.STOCK,
        )
        assert len(symbols) == 2
        assert Symbol("600519") in symbols
        assert Symbol("000001") in symbols

    def test_full_market_daily_receipt_is_idempotent_and_detects_bar_drift(
        self, store: DataStore
    ) -> None:
        bars = pd.DataFrame(
            {
                "symbol": ["000001", "600519"],
                "timestamp": pd.to_datetime(["2026-08-21", "2026-08-21"]),
                "open": [10.0, 20.0],
                "high": [10.2, 20.2],
                "low": [9.8, 19.8],
                "close": [10.1, 20.1],
                "volume": [1000.0, 2000.0],
                "amount": [10100.0, 40200.0],
            }
        )

        first = store.ingest_market_daily_batch(
            trade_date="2026-08-21",
            provider_name="fixture",
            bars=bars,
        )
        second = store.ingest_market_daily_batch(
            trade_date="2026-08-21",
            provider_name="fixture",
            bars=bars,
        )

        assert second == first
        assert first["row_count"] == 2
        assert store.list_market_daily_ingestion_receipts(
            start_date="2026-08-21",
            end_date="2026-08-21",
            provider_name="fixture",
        ) == [first]

        with sqlite3.connect(store._meta_path) as conn:
            conn.execute("""
                UPDATE market_bars SET close = 99
                WHERE symbol = '000001' AND instrument_type = 'stock'
                  AND frequency = '1d'
                  AND substr(timestamp, 1, 10) = '2026-08-21'
                """)
            conn.commit()

        with pytest.raises(ValueError, match="market_daily_ingestion_receipt_drift"):
            store.get_market_daily_ingestion_receipt(
                trade_date="2026-08-21",
                provider_name="fixture",
            )
        with pytest.raises(ValueError, match="market_daily_ingestion_receipt_conflict"):
            store.ingest_market_daily_batch(
                trade_date="2026-08-21",
                provider_name="fixture",
                bars=bars,
            )


def test_market_universe_snapshot_reads_are_provider_bound(store: DataStore) -> None:
    trade_date = "2026-09-18"
    akshare = store.save_market_universe_snapshot(
        trade_date=trade_date,
        provider_name="akshare",
        members=[{"symbol": "600000", "instrument_type": "stock"}],
    )
    tushare = store.save_market_universe_snapshot(
        trade_date=trade_date,
        provider_name="tushare",
        members=[{"symbol": "000001", "instrument_type": "stock"}],
    )

    assert (
        store.get_market_universe_snapshot(
            trade_date=trade_date,
            provider_name="akshare",
        )
        == akshare
    )
    assert (
        store.get_market_universe_snapshot(
            trade_date=trade_date,
            provider_name="tushare",
        )
        == tushare
    )
    assert akshare["snapshot_id"] != tushare["snapshot_id"]


@pytest.mark.parametrize("writer", ["cache", "daily_batch"])
def test_provider_refresh_cannot_overwrite_frozen_daily_values(store, writer):
    frame = pd.DataFrame(
        {
            "symbol": ["600519"],
            "timestamp": pd.to_datetime(["2026-09-14"]),
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "amount": [10500.0],
        }
    )
    receipt = store.ingest_market_daily_batch(
        trade_date="2026-09-14",
        provider_name="fixture",
        bars=frame,
    )
    store.save_bars(
        Symbol("600519"),
        BarFrequency.DAILY,
        frame.drop(columns="symbol"),
        instrument_type="stock",
    )
    mirror = store._root / "bars" / "1d" / "stock" / "600519.parquet"
    mirror_before = mirror.read_bytes()
    drifted = frame.copy()
    drifted["volume"] = 999.0
    drifted["amount"] = 9990.0
    with pytest.raises(ValueError, match="frozen_market_bar_conflict"):
        if writer == "cache":
            store.save_bars(
                Symbol("600519"),
                BarFrequency.DAILY,
                drifted.drop(columns="symbol"),
                instrument_type="stock",
                provider_name="another_provider",
            )
        else:
            store.ingest_market_daily_batch(
                trade_date="2026-09-14", provider_name="another_provider", bars=drifted
            )
    assert (
        store.get_market_daily_ingestion_receipt(
            trade_date="2026-09-14", provider_name="fixture"
        )
        == receipt
    )
    assert mirror.read_bytes() == mirror_before
    assert (
        store.get_market_daily_ingestion_receipt(
            trade_date="2026-09-14", provider_name="another_provider"
        )
        is None
    )
