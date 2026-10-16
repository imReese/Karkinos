"""A same-call verified prefix never changes old inputs or their time bounds."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from shutil import copytree
from types import SimpleNamespace

import pandas as pd
import pytest

from data.dataset import reader
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.reader import DatasetReaderIntegrityError
from data.market.capture import read_provider_capture
from data.market.corporate_actions import read_corporate_action_observation
from data.market.revision import read_market_revision_materialization
from data.providers.tushare_corporate_actions import (
    collect_tushare_dividend_observation,
)
from data.storage.objects import ContentAddressedObjectStore
from tests.data.dataset.test_reader import _AVAILABLE_AT, _publish_dataset, _revision
from tests.server.test_deployment_scope_datasets import _composed
from tests.server.test_research_observation_dynamic_inputs import forward_dataset
from tests.server.test_verified_interval_dataset import DAYS, STOCK, _verified_day


def _prefix(objects, current):
    snapshot = current.snapshot
    old = replace(
        snapshot,
        end_date=DAYS[0],
        cutoff=snapshot.session_memberships[0].available_at,
        instruments=(STOCK,),
        partitions=snapshot.partitions[:1],
        session_memberships=snapshot.session_memberships[:1],
        corporate_action_observation_ids=(),
    )
    return publish_daily_bar_dataset_manifest(objects, old), old


def test_same_call_prefix_reuses_verified_bars_without_reopening_parquet(
    tmp_path, monkeypatch
):
    objects, current = _composed(tmp_path)
    ref, _ = _prefix(objects, current)
    cold = reader.read_daily_bar_dataset(objects, ref)

    def forbidden_partition(*_args, **_kwargs):
        raise AssertionError("an unchanged verified prefix must not revalidate parquet")

    monkeypatch.setattr(reader, "_read_partition", forbidden_partition)
    assert (
        reader.read_daily_bar_dataset_prefix(objects, ref, verified_parent=current)
        == cold
    )


def test_parent_bars_are_indexed_once_per_operation_with_join_and_nested_scopes(
    tmp_path,
):
    objects, current = _composed(tmp_path)
    ref, _ = _prefix(objects, current)
    expected = reader.read_daily_bar_dataset(objects, ref)
    iterations = []

    class CountedBars(tuple):
        def __iter__(self):
            iterations.append(1)
            return super().__iter__()

    parent = replace(current, bars=CountedBars(current.bars))

    def read():
        assert (
            reader.read_daily_bar_dataset_prefix(objects, ref, verified_parent=parent)
            == expected
        )

    with reader.daily_bar_dataset_read_scope():
        read()
        read()
        assert len(iterations) == 1
        with reader.daily_bar_dataset_read_scope(join_existing=True):
            read()
        assert len(iterations) == 1
        with reader.daily_bar_dataset_read_scope():
            read()
        assert len(iterations) == 2
        read()
        assert len(iterations) == 2
    with reader.daily_bar_dataset_read_scope():
        read()
    assert len(iterations) == 3
    read()
    read()
    assert len(iterations) == 5


def test_parent_bar_index_is_bound_to_the_store_and_actual_parent_tuple(tmp_path):
    objects, current = _composed(tmp_path)
    ref, _ = _prefix(objects, current)
    expected = reader.read_daily_bar_dataset(objects, ref)
    iterations = []

    class CountedBars(tuple):
        def __iter__(self):
            iterations.append(1)
            return super().__iter__()

    parent = replace(current, bars=CountedBars(current.bars))
    other = ContentAddressedObjectStore(tmp_path / "other-objects")
    copytree(objects.root, other.root, dirs_exist_ok=True)
    with reader.daily_bar_dataset_read_scope():
        for store in (objects, other):
            assert (
                reader.read_daily_bar_dataset_prefix(store, ref, verified_parent=parent)
                == expected
            )
        assert len(iterations) == 2
        # Same content identity from another genuine read is not permission to
        # index a different tuple using a prior caller-supplied value.
        independently_read = reader._read_daily_bar_dataset(objects, current.ref)
        assert independently_read.bars == current.bars
        assert independently_read.bars is not current.bars
        independent_parent = replace(
            independently_read, bars=CountedBars(independently_read.bars)
        )
        assert (
            reader.read_daily_bar_dataset_prefix(
                objects, ref, verified_parent=independent_parent
            )
            == expected
        )
        assert len(iterations) == 3


@reader.daily_bar_dataset_read_scope()
def test_changed_lineage_falls_back_to_a_real_complete_read(tmp_path, monkeypatch):
    objects, current = _composed(tmp_path)
    original_ref, old = _prefix(objects, current)
    reader.read_daily_bar_dataset_prefix(objects, original_ref, verified_parent=current)
    alternate_ref = _verified_day(tmp_path / "research", DAYS[0], close="10.50")
    alternate = reader.read_daily_bar_dataset(objects, alternate_ref).snapshot
    changed = replace(
        old, partitions=(replace(alternate.partitions[0], instruments=(STOCK,)),)
    )
    ref = publish_daily_bar_dataset_manifest(objects, changed)
    full_read = reader._read_partition
    calls = []

    def tracked(*args, **kwargs):
        calls.append(kwargs["partition"])
        return full_read(*args, **kwargs)

    monkeypatch.setattr(reader, "_read_partition", tracked)
    restored = reader.read_daily_bar_dataset_prefix(
        objects, ref, verified_parent=current
    )
    assert calls == list(changed.partitions)
    assert restored.bars[0].close == Decimal("10.50")
    assert restored.bars[0].close != current.bars[0].close


@reader.daily_bar_dataset_read_scope()
def test_changed_prefixes_are_not_retained_and_still_detect_corrupt_raw(
    tmp_path, monkeypatch
):
    objects, current = _composed(tmp_path)
    _, old = _prefix(objects, current)
    references = []
    for close in ("10.50", "10.51", "10.52"):
        alternate_ref = _verified_day(tmp_path / "research", DAYS[0], close=close)
        alternate = reader.read_daily_bar_dataset(objects, alternate_ref).snapshot
        references.append(
            publish_daily_bar_dataset_manifest(
                objects,
                replace(
                    old,
                    partitions=(
                        replace(alternate.partitions[0], instruments=(STOCK,)),
                    ),
                ),
            )
        )
    retained = set(reader._CALL_VERIFIED_DATASETS.get())
    cold_read = reader._read_daily_bar_dataset
    calls = []

    def counted(store, ref):
        calls.append(ref)
        return cold_read(store, ref)

    monkeypatch.setattr(reader, "_read_daily_bar_dataset", counted)
    for ref in (*references, references[0]):
        result = reader.read_daily_bar_dataset_prefix(
            objects, ref, verified_parent=current
        )
        assert result.snapshot != current.snapshot
        assert set(reader._CALL_VERIFIED_DATASETS.get()) == retained
    assert calls == [*references, references[0]]
    materialization = read_market_revision_materialization(
        objects, objects.resolve_ref(result.snapshot.partitions[0].materialization_id)
    )
    capture = read_provider_capture(objects, materialization.capture_ref)
    raw = objects._path_for(capture.raw_object_ref.object_id)
    raw.chmod(0o644)
    raw.write_bytes(b"corrupt alternate prefix raw capture")
    with pytest.raises(DatasetReaderIntegrityError, match="materialization_unreadable"):
        reader.read_daily_bar_dataset_prefix(
            objects, references[0], verified_parent=current
        )


@reader.daily_bar_dataset_read_scope()
def test_reuse_rechecks_the_old_cutoff_against_verification(tmp_path):
    objects, current = _composed(tmp_path)
    memberships = (
        replace(
            current.snapshot.session_memberships[0],
            available_at=datetime(2026, 9, 17, 8, tzinfo=timezone.utc),
        ),
        *current.snapshot.session_memberships[1:],
    )
    parent_ref = publish_daily_bar_dataset_manifest(
        objects, replace(current.snapshot, session_memberships=memberships)
    )
    current = reader.read_daily_bar_dataset(objects, parent_ref)
    reader.read_daily_bar_dataset_prefix(objects, current.ref, verified_parent=current)
    _, old = _prefix(objects, current)
    ref = publish_daily_bar_dataset_manifest(
        objects, replace(old, cutoff=datetime(2026, 9, 17, 8, 4, tzinfo=timezone.utc))
    )
    with pytest.raises(DatasetReaderIntegrityError, match="verification_after_cutoff"):
        reader.read_daily_bar_dataset_prefix(objects, ref, verified_parent=current)


@reader.daily_bar_dataset_read_scope()
def test_reuse_rechecks_the_old_cutoff_against_bar_availability(tmp_path):
    objects = ContentAddressedObjectStore(tmp_path / "objects")
    revision, materialization = _revision(objects)
    ref = _publish_dataset(objects, revision=revision, materialization=materialization)
    current = reader.read_daily_bar_dataset(objects, ref)
    reader.read_daily_bar_dataset_prefix(objects, ref, verified_parent=current)
    old_ref = publish_daily_bar_dataset_manifest(
        objects, replace(current.snapshot, cutoff=_AVAILABLE_AT - timedelta(seconds=1))
    )
    with pytest.raises(DatasetReaderIntegrityError, match="bar_after_cutoff"):
        reader.read_daily_bar_dataset_prefix(objects, old_ref, verified_parent=current)


@pytest.mark.parametrize("target", ["manifest", "membership"])
@reader.daily_bar_dataset_read_scope()
def test_reuse_reopens_old_manifest_and_raw_membership_objects(tmp_path, target):
    objects, ref, _, _ = forward_dataset(tmp_path)
    current = reader.read_daily_bar_dataset(objects, ref)
    old_ref, old = _prefix(objects, current)
    reader.read_daily_bar_dataset_prefix(objects, old_ref, verified_parent=current)
    identity = (
        old_ref.manifest_ref.object_id
        if target == "manifest"
        else old.session_memberships[0].source_observation_ids[0]
    )
    path = objects._path_for(identity)
    path.chmod(0o644)
    path.write_bytes(b"corrupt synthetic fixture")
    with pytest.raises(
        DatasetReaderIntegrityError,
        match="manifest_invalid"
        if target == "manifest"
        else "membership_evidence_invalid",
    ):
        reader.read_daily_bar_dataset_prefix(objects, old_ref, verified_parent=current)


@reader.daily_bar_dataset_read_scope()
def test_reuse_reopens_original_corporate_action_capture(tmp_path):
    objects, current = _composed(tmp_path)

    def actions(instruments, captured):
        return tuple(
            collect_tushare_dividend_observation(
                objects,
                instrument=key,
                client=SimpleNamespace(dividend=lambda **_kwargs: pd.DataFrame()),
                clock=lambda: captured,
            ).object_id
            for key in instruments
        )

    original_actions = actions(
        (STOCK,), datetime(2026, 9, 17, 8, 5, tzinfo=timezone.utc)
    )
    current_actions = actions(
        current.snapshot.instruments, datetime(2026, 9, 18, 8, 5, tzinfo=timezone.utc)
    )
    parent_ref = publish_daily_bar_dataset_manifest(
        objects,
        replace(current.snapshot, corporate_action_observation_ids=current_actions),
    )
    current = reader.read_daily_bar_dataset(objects, parent_ref)
    _, old = _prefix(objects, current)
    old_ref = publish_daily_bar_dataset_manifest(
        objects, replace(old, corporate_action_observation_ids=original_actions)
    )
    restored = reader.read_daily_bar_dataset_prefix(
        objects, old_ref, verified_parent=current
    )
    assert restored.corporate_action_evidence["observation_ids"] == list(
        original_actions
    )
    observation = read_corporate_action_observation(
        objects, objects.resolve_ref(original_actions[0])
    )
    capture = read_provider_capture(
        objects, objects.resolve_ref(observation["capture_id"])
    )
    raw = objects._path_for(capture.raw_object_ref.object_id)
    raw.chmod(0o644)
    raw.write_bytes(b"corrupt original response")
    with pytest.raises(
        DatasetReaderIntegrityError, match="corporate_action_unreadable"
    ):
        reader.read_daily_bar_dataset_prefix(objects, old_ref, verified_parent=current)
