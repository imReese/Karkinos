from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from analytics.dataset_snapshot import build_backtest_dataset_snapshot
from core.types import AssetClass, BarFrequency, Symbol
from data.handler import DataHandler


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
