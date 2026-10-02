"""Real-store coverage for observed universe timing and bound research replay."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from data.store import DataStore
from server.contracts.ai_shadow_research_automation import ShadowResearchRejected
from server.db import AppDatabase
from server.services.ai_shadow_research_baseline import _load_baseline_universe
from server.services.market_universe_automation import MarketUniverseAutomationService
from server.services.market_universe_truth import (
    MarketUniversePolicy,
    MarketUniverseRejected,
    normalize_a_share_members,
    require_complete_market_universe_snapshot,
)
from tests.server.test_market_universe_automation import _verified_calendar

TRADE_DATE = "2026-08-21"
CAPTURE_START = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)
CAPTURE_END = CAPTURE_START + timedelta(seconds=2)
POLICY = MarketUniversePolicy(minimum_master_member_count=40, minimum_history_rows=2)
DATASET_ID = "sha256:" + "d" * 64


def _members(offset: int = 0):
    return normalize_a_share_members(
        [f"{600000 + offset + index:06d}" for index in range(40)]
    )


def _observe(store, *, offset: int = 0, completed_at=CAPTURE_END):
    return store.save_market_universe_snapshot(
        trade_date=TRADE_DATE,
        provider_name="observation_fixture",
        members=_members(offset),
        capture_started_at=completed_at - timedelta(seconds=2),
        capture_completed_at=completed_at,
    )


class _DelayedMasterSource:
    def __init__(self):
        self.master_calls = 0
        self.daily_calls = []
        self.symbols = [item["symbol"] for item in _members(100)]

    def list_symbol_metadata(self):
        self.master_calls += 1
        return [
            {"symbol": symbol, "display_name": f"合成股票{symbol}"}
            for symbol in self.symbols
        ]

    def fetch_market_daily_bars(self, trade_date):
        self.daily_calls.append(trade_date)
        return pd.DataFrame(
            {
                "symbol": self.symbols,
                "timestamp": pd.Timestamp(trade_date),
                "open": 10.0,
                "high": 10.1,
                "low": 9.9,
                "close": 10.0,
                "volume": 1_000_000,
                "amount": 10_000_000,
            }
        )


def test_delayed_adapter_observation_keeps_legacy_and_actual_capture_time(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    legacy = store.save_market_universe_snapshot(
        trade_date=TRADE_DATE,
        provider_name="observation_fixture",
        members=_members(),
    )
    source = _DelayedMasterSource()
    clock = iter((CAPTURE_START, CAPTURE_END))
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="observation_fixture",
            tushare_token="",
            start_date="2026-08-20",
        ),
        data_store=store,
        source=source,
        policy=POLICY,
        throttle_seconds=0,
        capture_clock=lambda: next(clock),
    )
    historical_run_date = datetime(2026, 8, 23, 2, tzinfo=timezone.utc)

    run = service.run_due(now=historical_run_date)

    assert run["status"] == "completed"
    payload = json.loads(run["payload_json"])
    assert payload["schema_version"] == "karkinos.market_universe_automation.v4"
    observed = store.get_market_universe_snapshot(
        snapshot_id=payload["market_universe_snapshot_id"]
    )
    assert observed["snapshot_id"] != legacy["snapshot_id"]
    assert observed["schema_version"] == "karkinos.market_universe_snapshot.v2"
    assert observed["trade_date"] == TRADE_DATE
    assert datetime.fromisoformat(observed["capture_started_at"]) == CAPTURE_START
    assert datetime.fromisoformat(observed["capture_completed_at"]) == CAPTURE_END
    assert datetime.fromisoformat(observed["available_at"]) == CAPTURE_END
    assert observed["members"] == _members(100)
    assert observed["historical_membership_verified"] is False
    assert (
        store.get_market_universe_snapshot(snapshot_id=legacy["snapshot_id"]) == legacy
    )
    assert store.get_market_universe_snapshot(as_of=historical_run_date) is None
    with pytest.raises(MarketUniverseRejected, match="observation_unavailable"):
        require_complete_market_universe_snapshot(
            observed, policy=POLICY, available_as_of=historical_run_date
        )
    assert source.master_calls == 1
    assert source.daily_calls == ["2026-08-20", TRADE_DATE]
    assert service.run_due(now=historical_run_date) == run
    assert source.master_calls == 1
    assert source.daily_calls == ["2026-08-20", TRADE_DATE]


@pytest.mark.parametrize("legacy", [False, True], ids=["observed", "time-unknown"])
def test_baseline_replays_exact_universe_after_same_day_revision_and_restart(
    tmp_path, legacy
):
    store = DataStore(tmp_path / "market")
    original = (
        store.save_market_universe_snapshot(
            trade_date=TRADE_DATE,
            provider_name="observation_fixture",
            members=_members(),
        )
        if legacy
        else _observe(store)
    )
    seed = {
        "metrics_json": json.dumps(
            {
                "dataset_snapshot": {"snapshot_id": DATASET_ID},
                "market_universe_truth": {
                    "market_universe_snapshot_id": original["snapshot_id"]
                },
            }
        )
    }
    revised = _observe(
        store, offset=100, completed_at=CAPTURE_END + timedelta(minutes=1)
    )
    reopened = DataStore(tmp_path / "market")

    replayed = _load_baseline_universe(
        store=reopened,
        seed=seed,
        expected_dataset_snapshot_id=DATASET_ID,
        expected_market_date=TRADE_DATE,
    )

    assert replayed == original
    assert replayed["members"] != revised["members"]
    assert reopened.get_market_universe_snapshot(trade_date=TRADE_DATE) == revised
    assert (
        _load_baseline_universe(
            store=reopened,
            seed=seed,
            expected_dataset_snapshot_id=None,
            expected_market_date=TRADE_DATE,
        )
        == revised
    )


@pytest.mark.parametrize(
    ("truth", "error"),
    [
        ({}, "baseline_universe_replay_binding_missing"),
        (
            {"market_universe_snapshot_id": "sha256:" + "0" * 64},
            "baseline_universe_replay_missing",
        ),
    ],
)
def test_bound_baseline_never_falls_back_to_latest_membership(tmp_path, truth, error):
    store = DataStore(tmp_path / "market")
    _observe(store)
    with pytest.raises(ShadowResearchRejected, match=error):
        _load_baseline_universe(
            store=store,
            seed={
                "metrics_json": {
                    "dataset_snapshot": {"snapshot_id": DATASET_ID},
                    "market_universe_truth": truth,
                }
            },
            expected_dataset_snapshot_id=DATASET_ID,
            expected_market_date=TRADE_DATE,
        )


def test_observation_available_as_of_is_inclusive_and_rejects_unknown_time(tmp_path):
    store = DataStore(tmp_path / "market")
    legacy = store.save_market_universe_snapshot(
        trade_date=TRADE_DATE,
        provider_name="observation_fixture",
        members=_members(),
    )
    observed = _observe(store)
    before = CAPTURE_END - timedelta(microseconds=1)

    assert store.get_market_universe_snapshot(as_of=before) is None
    with pytest.raises(MarketUniverseRejected, match="observation_unavailable"):
        require_complete_market_universe_snapshot(
            observed, policy=POLICY, available_as_of=before
        )
    for as_of in (CAPTURE_END, CAPTURE_END.astimezone(timezone(timedelta(hours=8)))):
        assert store.get_market_universe_snapshot(as_of=as_of) == observed
        assert (
            require_complete_market_universe_snapshot(
                observed,
                policy=POLICY,
                expected_trade_date=TRADE_DATE,
                available_as_of=as_of,
            )
            == observed
        )
        assert (
            store.get_market_universe_snapshot(
                snapshot_id=legacy["snapshot_id"], as_of=as_of
            )
            is None
        )
        with pytest.raises(MarketUniverseRejected, match="observation_time_unknown"):
            require_complete_market_universe_snapshot(
                legacy, policy=POLICY, available_as_of=as_of
            )
    assert require_complete_market_universe_snapshot(legacy, policy=POLICY) == legacy
    with pytest.raises(MarketUniverseRejected, match="as_of_timezone_required"):
        require_complete_market_universe_snapshot(
            observed, policy=POLICY, available_as_of=CAPTURE_END.replace(tzinfo=None)
        )
