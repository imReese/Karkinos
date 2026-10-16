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
    VERIFIED_SUPPLEMENT_NORMALIZATION,
    complete_research_market_binding,
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
        conn.execute("UPDATE market_bars SET amount=amount+1 WHERE symbol='600001'")
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


def test_missing_history_binds_exact_verified_dataset_without_rewriting_receipts(
    tmp_path,
):
    from datetime import timedelta

    from tests.server.test_deployment_scope_datasets import _composed
    from tests.server.test_verified_interval_dataset import (
        DAYS,
        NOW,
        STOCK,
        _verified_day,
    )

    objects, canonical = _composed(tmp_path)
    market = DataStore(tmp_path)
    receipts = [
        market.ingest_market_daily_batch(
            trade_date=day.isoformat(), provider_name="fixture", bars=_batch(day)
        )
        for day in DAYS
    ]
    original = research_market_binding(receipts)
    # A newer one-session result must not shadow a complete historical range.
    _verified_day(tmp_path / "research", DAYS[-1], instruments=(STOCK,))
    arguments = dict(
        symbols=["600000", "600001"],
        start_date=DAYS[0].isoformat(),
        end_date=DAYS[-1].isoformat(),
    )
    binding, frames = complete_research_market_binding(
        tmp_path, binding=original, as_of=NOW, **arguments
    )
    assert binding["normalizer_version"] == VERIFIED_SUPPLEMENT_NORMALIZATION
    assert binding["point_in_time_verified"] is False
    assert binding["verified_dataset_supplements"] == [
        {
            "dataset_id": canonical.ref.dataset_id,
            "symbols": ["600000"],
            "session_memberships": [
                {"trade_date": day.isoformat(), "symbols": ["600000"]} for day in DAYS
            ],
        }
    ]
    assert frames["600000"]["volume"].tolist() == [123456, 123456]
    assert frames["600001"]["volume"].tolist() == [100, 100]
    assert (
        market.list_market_daily_ingestion_receipts(
            start_date=arguments["start_date"], end_date=arguments["end_date"]
        )
        == receipts
    )
    replayed = load_research_market_frames(tmp_path, binding=binding, **arguments)
    pd.testing.assert_frame_equal(frames["600000"], replayed["600000"])
    too_early = {
        **binding,
        "verified_supplement_as_of": (
            canonical.snapshot.cutoff - timedelta(seconds=1)
        ).isoformat(),
    }
    with pytest.raises(ValueError, match="supplement_unverified"):
        load_research_market_frames(tmp_path, binding=too_early, **arguments)
    overlapping = {
        **binding,
        "verified_dataset_supplements": [
            {"dataset_id": canonical.ref.dataset_id, "symbols": ["600001"]}
        ],
    }
    with pytest.raises(ValueError, match="supplement_overlap"):
        load_research_market_frames(tmp_path, binding=overlapping, **arguments)
    damaged = objects._path_for(canonical.ref.manifest_ref.object_id)
    damaged.chmod(0o644)
    damaged.write_bytes(b"corrupt")
    with pytest.raises(Exception, match="object_integrity_mismatch"):
        load_research_market_frames(tmp_path, binding=binding, **arguments)


def test_partial_symbol_history_adds_only_bound_missing_sessions(tmp_path):
    from tests.server.test_deployment_scope_datasets import _composed
    from tests.server.test_verified_interval_dataset import DAYS, NOW

    _, canonical = _composed(tmp_path)
    market = DataStore(tmp_path)
    first = _batch(DAYS[0])
    partial = first.copy()
    partial["symbol"] = "600000"
    partial["close"] = 10.25
    receipts = [
        market.ingest_market_daily_batch(
            trade_date=DAYS[0].isoformat(),
            provider_name="fixture",
            bars=pd.concat([first, partial], ignore_index=True),
        ),
        market.ingest_market_daily_batch(
            trade_date=DAYS[1].isoformat(),
            provider_name="fixture",
            bars=_batch(DAYS[1]),
        ),
    ]
    args = dict(
        symbols=["600000", "600001"],
        start_date=DAYS[0].isoformat(),
        end_date=DAYS[-1].isoformat(),
    )
    binding, frames = complete_research_market_binding(
        tmp_path, binding=research_market_binding(receipts), as_of=NOW, **args
    )
    assert frames["600000"]["close"].tolist() == [10.25, 10.48]
    supplement = binding["verified_dataset_supplements"][0]
    assert supplement == {
        "dataset_id": canonical.ref.dataset_id,
        "symbols": ["600000"],
        "session_memberships": [
            {"trade_date": DAYS[-1].isoformat(), "symbols": ["600000"]}
        ],
    }
    replayed = load_research_market_frames(tmp_path, binding=binding, **args)
    for symbol in frames:
        pd.testing.assert_frame_equal(frames[symbol], replayed[symbol])
    bad = {
        **binding,
        "verified_dataset_supplements": [
            {
                **supplement,
                "session_memberships": [
                    {"trade_date": day.isoformat(), "symbols": ["600000"]}
                    for day in DAYS
                ],
            }
        ],
    }
    with pytest.raises(ValueError, match="supplement_overlap"):
        load_research_market_frames(tmp_path, binding=bad, **args)


def test_research_reuses_each_verified_receipt_read_and_keeps_typed_date_bounds(
    tmp_path, monkeypatch
):
    store = DataStore(tmp_path)
    receipts = [
        store.ingest_market_daily_batch(
            trade_date=day, provider_name="fixture", bars=_batch(day, amount=amount)
        )
        for day, amount in (("2026-01-05", 1000), ("2026-01-06", 2000))
    ]
    store.save_bars(
        Symbol("600001"),
        BarFrequency.DAILY,
        _batch("2026-01-05", amount=999999).drop(columns="symbol"),
        instrument_type="etf",
    )
    store.save_bars(
        Symbol("600001"),
        BarFrequency.DAILY,
        _batch("2026-01-07", amount=777777).drop(columns="symbol"),
        instrument_type="stock",
    )
    queries = []
    connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connection.set_trace_callback(queries.append)
        return connection

    monkeypatch.setattr("data.research_market_data.sqlite3.connect", traced_connect)
    frames = load_research_market_frames(
        tmp_path,
        binding=research_market_binding(receipts),
        symbols=["600001"],
        start_date="2026-01-05",
        end_date="2026-01-06",
    )
    assert frames["600001"]["amount"].tolist() == [1000, 2000]
    assert len(
        [
            query
            for query in queries
            if query.lstrip().upper().startswith("SELECT")
            and "FROM main.market_bars" in query
        ]
    ) == len(receipts)

    # Reusing rows from the same transaction must still replay the complete
    # receipt, even when the caller requests only a subset of its members.
    with connect(store._meta_path) as connection:
        connection.execute(
            "UPDATE market_bars SET amount=amount+1 "
            "WHERE instrument_type='stock' AND timestamp<'2026-01-06'"
        )
    with pytest.raises(ValueError, match="research_market_receipt_drift"):
        load_research_market_frames(
            tmp_path,
            binding=research_market_binding(receipts),
            symbols=["600099"],
            start_date="2026-01-05",
            end_date="2026-01-06",
        )
