"""Call-owned reuse preserves cold-request and content-addressed boundaries."""

from dataclasses import replace
from datetime import date, timedelta
from shutil import copytree
from types import SimpleNamespace

import pandas as pd
import pytest

from data.dataset.manifest import (
    publish_daily_bar_dataset_manifest,
    read_daily_bar_dataset_manifest,
)
from data.dataset.model import DailyBarDatasetMembership, DatasetRef
from data.dataset.reader import (
    DatasetReaderIntegrityError,
    daily_bar_dataset_read_scope,
    read_daily_bar_dataset,
)
from data.providers.tushare_corporate_actions import (
    collect_tushare_dividend_observation,
)
from data.storage.objects import ContentAddressedObjectStore
from tests.server.test_verified_interval_dataset import _verified_day


@pytest.fixture
def verified(tmp_path):
    root = tmp_path / "research"
    ref = _verified_day(root, date(2026, 8, 21))
    objects = ContentAddressedObjectStore(root / "objects")
    snapshot = read_daily_bar_dataset_manifest(objects, ref)
    captures = tuple(
        collect_tushare_dividend_observation(
            objects,
            instrument=instrument,
            client=SimpleNamespace(dividend=lambda **_: pd.DataFrame()),
            clock=lambda: snapshot.cutoff - timedelta(minutes=1),
        ).object_id
        for instrument in snapshot.instruments
    )
    snapshot = replace(snapshot, corporate_action_observation_ids=captures)
    ref = publish_daily_bar_dataset_manifest(objects, snapshot)
    return objects, ref, snapshot


def _track_cold_reads(monkeypatch):
    import data.dataset.reader as reader

    cold = reader._read_daily_bar_dataset
    calls = []

    def tracked(objects, ref):
        calls.append((objects.root, ref))
        return cold(objects, ref)

    monkeypatch.setattr(reader, "_read_daily_bar_dataset", tracked)
    return calls


def test_call_scope_reuses_verified_bars_and_isolates_mutable_actions(
    verified, monkeypatch
):
    objects, ref, _ = verified
    calls = _track_cold_reads(monkeypatch)
    with daily_bar_dataset_read_scope():
        first = read_daily_bar_dataset(objects, ref)
        first.corporate_action_evidence["events"].append({"caller_mutation": True})
        second = read_daily_bar_dataset(objects, ref)
        assert second.bars is first.bars
        assert second.corporate_action_evidence["events"] == []
        second.corporate_action_evidence["observation_ids"].clear()
        assert read_daily_bar_dataset(objects, ref).corporate_action_evidence[
            "observation_ids"
        ]
        assert len(calls) == 1
    with daily_bar_dataset_read_scope():
        assert (
            read_daily_bar_dataset(objects, ref).corporate_action_evidence["events"]
            == []
        )
    assert len(calls) == 2
    read_daily_bar_dataset(objects, ref)
    read_daily_bar_dataset(objects, ref)
    assert len(calls) == 4


def test_new_scope_and_other_root_reject_corruption_after_a_verified_read(
    tmp_path, verified
):
    objects, ref, _ = verified
    other = ContentAddressedObjectStore(tmp_path / "other" / "objects")
    copytree(objects.root, other.root)
    path = other._path_for(ref.dataset_id)
    path.chmod(0o600)
    path.write_bytes(b"corrupt")
    with daily_bar_dataset_read_scope():
        read_daily_bar_dataset(objects, ref)
        with pytest.raises(DatasetReaderIntegrityError, match="manifest_invalid"):
            read_daily_bar_dataset(other, ref)
    original = objects._path_for(ref.dataset_id)
    original.chmod(0o600)
    original.write_bytes(b"corrupt")
    with daily_bar_dataset_read_scope():
        with pytest.raises(DatasetReaderIntegrityError, match="manifest_invalid"):
            read_daily_bar_dataset(objects, ref)


def test_scope_and_exact_ref_size_remain_independent(verified, monkeypatch):
    objects, ref, snapshot = verified
    membership = DailyBarDatasetMembership(
        snapshot.start_date, snapshot.instruments, snapshot.cutoff
    )
    scoped = replace(
        snapshot,
        partitions=tuple(
            replace(part, instruments=snapshot.instruments)
            for part in snapshot.partitions
        ),
        session_memberships=(membership,),
        universe_policy_id="declared-scope-one",
    )
    first = publish_daily_bar_dataset_manifest(objects, scoped)
    second = publish_daily_bar_dataset_manifest(
        objects, replace(scoped, universe_policy_id="declared-scope-two")
    )
    calls = _track_cold_reads(monkeypatch)
    with daily_bar_dataset_read_scope():
        assert read_daily_bar_dataset(objects, first).snapshot.universe_policy_id == (
            "declared-scope-one"
        )
        assert read_daily_bar_dataset(objects, second).snapshot.universe_policy_id == (
            "declared-scope-two"
        )
        wrong_size = DatasetRef(
            replace(first.manifest_ref, size_bytes=first.manifest_ref.size_bytes + 1)
        )
        with pytest.raises(DatasetReaderIntegrityError, match="manifest_invalid"):
            read_daily_bar_dataset(objects, wrong_size)
    assert len(calls) == 3


def test_explicit_join_reuses_parent_while_default_nested_scope_is_independent(
    verified, monkeypatch
):
    objects, ref, _ = verified
    calls = _track_cold_reads(monkeypatch)
    with daily_bar_dataset_read_scope():
        original = read_daily_bar_dataset(objects, ref)
        with daily_bar_dataset_read_scope(join_existing=True):
            assert read_daily_bar_dataset(objects, ref).bars is original.bars
        assert len(calls) == 1
        with daily_bar_dataset_read_scope():
            read_daily_bar_dataset(objects, ref)
        assert len(calls) == 2
        assert read_daily_bar_dataset(objects, ref).bars is original.bars
    with daily_bar_dataset_read_scope(join_existing=True):
        read_daily_bar_dataset(objects, ref)
    assert len(calls) == 3
