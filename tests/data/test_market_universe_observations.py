"""Immutable stock-pool observations and their actual availability boundaries."""

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from data.store import DataStore

UTC = timezone.utc
START = datetime(2026, 9, 22, 8, tzinfo=UTC)
END = START + timedelta(seconds=2)


@pytest.fixture
def store(tmp_path):
    return DataStore(tmp_path)


def _save(store, *, start=START, end=END, symbols=("600001",), provider="fixture"):
    return store.save_market_universe_snapshot(
        trade_date="2026-08-21",
        provider_name=provider,
        members=[{"symbol": symbol, "instrument_type": "stock"} for symbol in symbols],
        capture_started_at=start,
        capture_completed_at=end,
    )


def test_repeated_capture_and_revision_preserve_exact_observation_ids(store):
    original = _save(store)
    repeated = _save(
        store, start=START + timedelta(minutes=1), end=END + timedelta(minutes=1)
    )
    revision = _save(
        store,
        start=START + timedelta(minutes=2),
        end=END + timedelta(minutes=2),
        symbols=("600002",),
    )
    assert len({row["snapshot_id"] for row in (original, repeated, revision)}) == 3
    assert original["members"] == repeated["members"]
    assert original["trade_date"] == "2026-08-21"
    assert original["available_at"] == "2026-09-22T08:00:02.000000+00:00"
    assert original["trade_date_role"] == "daily_bar_window_end"
    assert original["membership_basis"] == "current_active_stock_master"
    assert original["observation_basis"] == "adapter_response"
    assert original["historical_membership_verified"] is False
    assert _save(store) == original
    for snapshot in (original, repeated, revision):
        assert (
            store.get_market_universe_snapshot(snapshot_id=snapshot["snapshot_id"])
            == snapshot
        )
    assert (
        store.get_market_universe_snapshot(
            trade_date="2026-08-21", provider_name="fixture"
        )
        == revision
    )


def test_as_of_uses_real_capture_time_and_equivalent_timezone(store):
    original = _save(store)
    later = _save(
        store, start=START + timedelta(minutes=1), end=END + timedelta(minutes=1)
    )
    assert (
        store.get_market_universe_snapshot(as_of=END - timedelta(microseconds=1))
        is None
    )
    assert store.get_market_universe_snapshot(as_of=END) == original
    assert (
        store.get_market_universe_snapshot(
            as_of=END.astimezone(timezone(timedelta(hours=8)))
        )
        == original
    )
    assert store.get_market_universe_snapshot(as_of=END + timedelta(minutes=1)) == later
    assert (
        store.get_market_universe_snapshot(snapshot_id=later["snapshot_id"], as_of=END)
        is None
    )
    assert (
        store.get_market_universe_snapshot(
            snapshot_id=original["snapshot_id"], provider_name="other"
        )
        is None
    )
    assert (
        store.get_market_universe_snapshot(
            snapshot_id=original["snapshot_id"], trade_date="2026-08-20"
        )
        is None
    )
    assert (
        _save(
            store,
            start=START.astimezone(timezone(timedelta(hours=8))),
            end=END.astimezone(timezone(timedelta(hours=8))),
        )
        == original
    )


def test_latest_observation_order_does_not_depend_on_insert_order(store):
    later = _save(
        store, start=START + timedelta(minutes=1), end=END + timedelta(minutes=1)
    )
    original = _save(store)
    assert store.get_market_universe_snapshot() == later
    tied = _save(
        store,
        start=START + timedelta(minutes=1),
        end=END + timedelta(minutes=1),
        symbols=("600002",),
    )
    with pytest.raises(ValueError, match="market_universe_observation_ambiguous"):
        store.get_market_universe_snapshot()
    with pytest.raises(ValueError, match="market_universe_observation_ambiguous"):
        store.get_market_universe_snapshot(as_of=END + timedelta(minutes=1))
    assert store.get_market_universe_snapshot(as_of=END) == original
    for row in (later, tied):
        assert store.get_market_universe_snapshot(snapshot_id=row["snapshot_id"]) == row
    newer = _save(
        store, start=START + timedelta(minutes=2), end=END + timedelta(minutes=2)
    )
    assert store.get_market_universe_snapshot() == newer
    assert store.get_market_universe_snapshot(as_of=END + timedelta(minutes=2)) == newer


def test_legacy_availability_stays_unknown_even_after_new_observation(store):
    legacy = _save(store, start=None, end=None)
    current = _save(store, symbols=("600002",))
    assert "available_at" not in legacy
    assert _save(store, start=None, end=None) == legacy
    with pytest.raises(ValueError, match="market_universe_snapshot_conflict"):
        _save(store, start=None, end=None, symbols=("600003",))
    assert (
        store.get_market_universe_snapshot(snapshot_id=legacy["snapshot_id"]) == legacy
    )
    assert (
        store.get_market_universe_snapshot(snapshot_id=legacy["snapshot_id"], as_of=END)
        is None
    )
    assert store.get_market_universe_snapshot(as_of=END - timedelta(seconds=1)) is None
    assert store.get_market_universe_snapshot(as_of=END) == current


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (START, None),
        (None, END),
        (START.replace(tzinfo=None), END),
        (START, END.replace(tzinfo=None)),
        (END, START),
    ],
)
def test_capture_requires_complete_aware_ordered_instants(store, start, end):
    with pytest.raises(ValueError, match="market_universe_capture_"):
        _save(store, start=start, end=end)
    assert store.get_market_universe_snapshot() is None


def test_as_of_requires_an_aware_instant_and_remains_provider_bound(store):
    expected = _save(store)
    _save(
        store,
        provider="other",
        start=START + timedelta(minutes=1),
        end=END + timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="market_universe_as_of_timezone_required"):
        store.get_market_universe_snapshot(as_of=END.replace(tzinfo=None))
    assert (
        store.get_market_universe_snapshot(
            provider_name="fixture", as_of=END + timedelta(days=1)
        )
        == expected
    )


def test_backdated_lookup_columns_cannot_make_future_payload_available(store):
    snapshot = _save(store)
    backdated = (START - timedelta(hours=1)).isoformat(timespec="microseconds")
    with sqlite3.connect(store._meta_path) as connection:
        connection.execute(
            "UPDATE market_universe_snapshots SET capture_started_at = ?, "
            "capture_completed_at = ?, available_at = ? WHERE snapshot_id = ?",
            (backdated, backdated, backdated, snapshot["snapshot_id"]),
        )
    with pytest.raises(ValueError, match="market_universe_snapshot_integrity_invalid"):
        store.get_market_universe_snapshot(as_of=START)
    with pytest.raises(ValueError, match="market_universe_snapshot_integrity_invalid"):
        _save(store)


def test_v1_cannot_gain_availability_from_lookup_columns(store):
    snapshot = _save(store, start=None, end=None)
    instant = END.isoformat(timespec="microseconds")
    with sqlite3.connect(store._meta_path) as connection:
        connection.execute(
            "UPDATE market_universe_snapshots SET capture_started_at = ?, "
            "capture_completed_at = ?, available_at = ? WHERE snapshot_id = ?",
            (instant, instant, instant, snapshot["snapshot_id"]),
        )
    with pytest.raises(ValueError, match="market_universe_snapshot_integrity_invalid"):
        store.get_market_universe_snapshot(as_of=END)


@pytest.mark.parametrize("rehash", [False, True])
def test_payload_time_tamper_is_rejected_even_with_recomputed_identity(store, rehash):
    snapshot = _save(store)
    changed = {**snapshot, "available_at": START.isoformat(timespec="microseconds")}
    if rehash:
        core = dict(changed)
        core.pop("snapshot_id")
        changed["snapshot_id"] = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
    with sqlite3.connect(store._meta_path) as connection:
        connection.execute(
            "UPDATE market_universe_snapshots SET snapshot_id = ?, snapshot_json = ? WHERE snapshot_id = ?",
            (changed["snapshot_id"], json.dumps(changed), snapshot["snapshot_id"]),
        )
    with pytest.raises(ValueError, match="market_universe_snapshot_integrity_invalid"):
        store.get_market_universe_snapshot(snapshot_id=changed["snapshot_id"])
