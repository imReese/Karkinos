from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pandas as pd

from analytics.dataset_snapshot import (
    build_backtest_dataset_snapshot,
    verify_backtest_dataset_snapshot_replay,
)
from core.types import AssetClass, BarFrequency, Symbol
from data.handler import DataHandler
from data.store import DataStore


def _snapshot(frame: pd.DataFrame) -> dict:
    symbol = Symbol("600000")
    handler = DataHandler(
        frame,
        symbol,
        BarFrequency.DAILY,
        AssetClass.STOCK,
    )
    return build_backtest_dataset_snapshot(
        start_date="2025-01-02",
        end_date="2025-01-04",
        configured_source="deterministic_fixture",
        data_handlers={symbol: handler},
        store=None,
        source_names=["deterministic_fixture"],
    )


def _bars() -> pd.DataFrame:
    start = datetime(2025, 1, 2)
    return pd.DataFrame(
        {
            "timestamp": [start + timedelta(days=index) for index in range(3)],
            "open": [10, 11, 12],
            "high": [11, 12, 13],
            "low": [9, 10, 11],
            "close": [10, 11, 12],
            "volume": [1000, 1100, 1200],
        }
    )


def test_dataset_snapshot_identity_hashes_exact_ordered_ohlcv_content() -> None:
    original = _bars()
    replay = original.copy()
    drifted = original.copy()
    drifted.loc[1, "close"] = 99

    first = _snapshot(original)
    second = _snapshot(replay)
    changed = _snapshot(drifted)

    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["snapshot_id"] != changed["snapshot_id"]
    assert first["content_identity"] == {
        "algorithm": "sha256",
        "row_contract": "timestamp_ohlcv.v1",
        "complete": True,
    }
    assert first["symbol_universe"][0]["content_digest"].startswith("sha256:")
    assert (
        first["symbol_universe"][0]["content_digest"]
        != changed["symbol_universe"][0]["content_digest"]
    )


def test_dataset_snapshot_fails_quality_when_content_cannot_be_hashed() -> None:
    incomplete = _bars().drop(columns=["volume"])

    snapshot = _snapshot(incomplete)

    assert snapshot["content_identity"]["complete"] is False
    assert snapshot["data_quality"]["status"] == "warning"
    assert snapshot["data_quality"]["issues"] == [
        {
            "symbol": "600000",
            "code": "dataset_content_digest_unavailable",
            "message": (
                "The exact ordered timestamp/OHLCV rows could not be hashed; this "
                "dataset cannot be treated as frozen evidence."
            ),
        }
    ]


def test_dataset_snapshot_replay_uses_exact_persisted_window_and_detects_drift(
    tmp_path,
) -> None:
    symbol = Symbol("600000")
    original = _bars()
    store = DataStore(tmp_path)
    store.save_bars(
        symbol,
        BarFrequency.DAILY,
        original,
        provider_name="fixture_provider",
        data_source="fixture_provider",
        adjustment_mode="qfq",
    )
    snapshot = build_backtest_dataset_snapshot(
        start_date="2025-01-02",
        end_date="2025-01-04",
        configured_source="fixture_provider",
        data_handlers={
            symbol: DataHandler(
                original,
                symbol,
                BarFrequency.DAILY,
                AssetClass.STOCK,
            )
        },
        store=store,
        source_names=["fixture_provider"],
    )

    first = verify_backtest_dataset_snapshot_replay(snapshot, store_root=tmp_path)
    future = _bars().iloc[:1].copy()
    future["timestamp"] = pd.to_datetime(["2025-02-03"])
    store.append_bars(
        symbol,
        BarFrequency.DAILY,
        future,
        provider_name="fixture_provider",
        data_source="fixture_provider",
        adjustment_mode="qfq",
    )
    after_append = verify_backtest_dataset_snapshot_replay(
        snapshot,
        store_root=tmp_path,
    )

    assert first["status"] == "pass"
    assert first["verified_symbol_count"] == 1
    assert first["provider_contacted"] is False
    assert after_append["status"] == "pass"

    with sqlite3.connect(tmp_path / "meta.db") as conn:
        conn.execute(
            "UPDATE market_bars SET close = 99 WHERE symbol = ? AND timestamp = ?",
            ("600000", "2025-01-03T00:00:00"),
        )
    drifted = verify_backtest_dataset_snapshot_replay(snapshot, store_root=tmp_path)

    assert drifted["status"] == "blocked"
    assert any(
        blocker.startswith("dataset_replay_content_drift:600000:")
        for blocker in drifted["blockers"]
    )
    assert drifted["parquet_fallback_used"] is False
    assert drifted["does_not_authorize_execution"] is True


def test_dataset_snapshot_replay_rejects_tampered_manifest_identity(
    tmp_path,
) -> None:
    forged = _snapshot(_bars())
    forged["symbol_universe"][0]["content_digest"] = "sha256:" + "f" * 64

    evidence = verify_backtest_dataset_snapshot_replay(
        forged,
        store_root=tmp_path,
    )

    assert evidence["status"] == "blocked"
    assert "dataset_snapshot_identity_mismatch" in evidence["blockers"]
    assert "dataset_replay_store_missing" not in evidence["blockers"]
