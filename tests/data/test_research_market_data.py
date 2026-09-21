from __future__ import annotations

import hashlib
import json
import sqlite3

import pandas as pd
import pytest

from analytics.dataset_snapshot import (
    build_backtest_dataset_snapshot,
    verify_backtest_dataset_snapshot_replay,
)
from core.types import AssetClass, BarFrequency, Symbol
from data.handler import DataHandler
from data.research_market_data import (
    load_research_market_frames,
    research_market_binding,
)
from data.store import DataStore


def _batch(day, volume=100, amount=1000):
    return pd.DataFrame(
        {
            "symbol": ["600001"],
            "timestamp": [pd.Timestamp(day)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.0],
            "volume": [volume],
            "amount": [amount],
        }
    )


def _legacy_receipt(store, provider="tushare"):
    receipt = store.ingest_market_daily_batch(
        trade_date="2026-01-05", provider_name=provider, bars=_batch("2026-01-05")
    )
    receipt.pop("units")
    receipt.pop("price_basis")
    receipt.pop("receipt_fingerprint")
    receipt["schema_version"] = "karkinos.market_daily_ingestion_receipt.v2"
    receipt["receipt_fingerprint"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    )
    with sqlite3.connect(store._meta_path) as conn:
        conn.execute(
            "UPDATE market_daily_ingestion_receipts SET receipt_json=?",
            (json.dumps(receipt),),
        )
    return receipt


def test_research_normalizes_only_bound_legacy_units_and_replays_both_versions(
    tmp_path,
):
    store = DataStore(tmp_path)
    old = _legacy_receipt(store)
    new = store.ingest_market_daily_batch(
        trade_date="2026-01-06",
        provider_name="tushare",
        bars=_batch("2026-01-06", 10000, 1000000),
    )
    binding = research_market_binding([old, new])
    args = dict(
        binding=binding,
        symbols=["600001"],
        start_date="2026-01-05",
        end_date="2026-01-06",
    )
    frames = load_research_market_frames(tmp_path, **args)
    assert frames["600001"]["volume"].tolist() == [10000, 10000]
    assert frames["600001"]["amount"].tolist() == [1000000, 1000000]
    assert (
        store.get_market_daily_ingestion_receipt(
            trade_date="2026-01-05", provider_name="tushare"
        )
        == old
    )
    raw = store.load_bars(Symbol("600001"), instrument_type="stock")
    assert raw["volume"].tolist() == [100, 10000]
    snapshots = []
    for frame, provenance in [(raw, None), (frames["600001"], binding)]:
        snapshots.append(
            build_backtest_dataset_snapshot(
                start_date=args["start_date"],
                end_date=args["end_date"],
                configured_source=None,
                data_handlers={
                    Symbol("600001"): DataHandler(
                        frame, Symbol("600001"), asset_class=AssetClass.STOCK
                    )
                },
                store=store,
                source_names=[],
                market_data_binding=provenance,
            )
        )
    assert snapshots[0]["snapshot_id"] != snapshots[1]["snapshot_id"]
    for snapshot in snapshots:
        assert (
            verify_backtest_dataset_snapshot_replay(snapshot, store_root=tmp_path)[
                "status"
            ]
            == "pass"
        )
    with sqlite3.connect(store._meta_path) as conn:
        conn.execute("UPDATE market_bars_v2 SET amount=amount+1 WHERE symbol='600001'")
    assert (
        verify_backtest_dataset_snapshot_replay(snapshots[1], store_root=tmp_path)[
            "status"
        ]
        == "blocked"
    )


def test_unknown_legacy_units_are_not_guessed(tmp_path):
    store = DataStore(tmp_path)
    old = _legacy_receipt(store, "akshare")
    with pytest.raises(ValueError, match="legacy_units_unknown"):
        load_research_market_frames(
            tmp_path,
            binding=research_market_binding([old]),
            symbols=["600001"],
            start_date="2026-01-05",
            end_date="2026-01-05",
        )


def test_receipt_membership_excludes_unbound_rows(tmp_path):
    store = DataStore(tmp_path)
    receipt = store.ingest_market_daily_batch(
        trade_date="2026-01-05", provider_name="fixture", bars=_batch("2026-01-05")
    )
    store.save_bars(
        Symbol("600002"),
        BarFrequency.DAILY,
        _batch("2026-01-05").drop(columns="symbol"),
        instrument_type="stock",
    )
    frames = load_research_market_frames(
        tmp_path,
        binding=research_market_binding([receipt]),
        symbols=["600001", "600002"],
        start_date="2026-01-05",
        end_date="2026-01-05",
    )
    assert set(frames) == {"600001"}
