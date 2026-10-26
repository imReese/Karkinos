"""The real Dataset owner binds selected roster, times, bars and halt conflicts."""

from __future__ import annotations

from dataclasses import replace

import pytest

from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.reader import (
    DatasetReaderIntegrityError,
    dataset_session_nontrading_instruments,
    read_daily_bar_dataset,
)
from tests.data.dataset import test_historical_session_status as historical
from tests.data.providers.test_sse_structured_suspension import _capture, _row


def _inputs(tmp_path, *, rows=None):
    objects, snapshot, master, bao = historical._inputs(tmp_path)
    _, cap = _capture(tmp_path, rows)
    snapshot = replace(
        snapshot,
        cutoff=cap.completed_at,
        session_memberships=tuple(
            replace(
                m,
                available_at=cap.completed_at,
                source_observation_ids=(master.object_id, cap.capture_id),
            )
            if m.partition_date == historical.DAYS[-1]
            else m
            for m in snapshot.session_memberships
        ),
    )
    return objects, snapshot, master, bao, cap


def test_fresh_manifest_full_canonical_bars_and_nontrading_scope(tmp_path):
    objects, snapshot, master, _, cap = _inputs(
        tmp_path,
        rows=[
            _row(),
            _row(productCode="600009"),
            _row(productCode="113001", controlType="GB"),
        ],
    )
    master_bytes = objects.read_bytes(master)
    native_bytes = objects.read_bytes(cap.raw_object_ref)
    actual = read_daily_bar_dataset(
        objects, publish_daily_bar_dataset_manifest(objects, snapshot)
    )
    assert actual.row_count == 3
    assert dataset_session_nontrading_instruments(objects, actual.snapshot) == {
        historical.DAYS[-1]: historical.KEYS[:1]
    }
    assert actual.snapshot.instruments == historical.KEYS
    assert actual.snapshot.membership_evidence_bound is False
    assert actual.snapshot.session_memberships[-1].available_at == cap.completed_at
    assert objects.read_bytes(master) == master_bytes
    assert objects.read_bytes(cap.raw_object_ref) == native_bytes


@pytest.mark.parametrize(
    "case",
    [
        "decision",
        "availability",
        "missing_master",
        "traded",
        "maintenance",
        "after_cutoff",
    ],
)
def test_existing_membership_fences_remain_the_owner(tmp_path, case):
    objects, snapshot, _, _, cap = _inputs(tmp_path)
    last = snapshot.session_memberships[-1]
    changes = {
        "decision": {"decision_at": cap.completed_at},
        "availability": {"available_at": historical.MASTER_AT},
        "missing_master": {"source_observation_ids": (cap.capture_id,)},
        "traded": {"instruments": historical.KEYS},
        "maintenance": {"maintenance_instruments": historical.KEYS[:1]},
    }
    with pytest.raises((DatasetReaderIntegrityError, ValueError)):
        if case == "after_cutoff":
            invalid = replace(snapshot, cutoff=historical.MASTER_AT)
            read_daily_bar_dataset(
                objects, publish_daily_bar_dataset_manifest(objects, invalid)
            )
        else:
            invalid = replace(
                snapshot,
                session_memberships=(
                    *snapshot.session_memberships[:-1],
                    replace(last, **changes[case]),
                ),
            )
            dataset_session_nontrading_instruments(objects, invalid)


def test_literal_partial_record_cannot_be_hidden_by_an_independent_Bao_full_day(
    tmp_path,
):
    objects, snapshot, master, bao, cap = _inputs(
        tmp_path, rows=[_row(type="LSTP", stopTime="PM")]
    )
    last = replace(
        snapshot.session_memberships[-1],
        source_observation_ids=(master.object_id, bao.capture_id, cap.capture_id),
    )
    snapshot = replace(
        snapshot, session_memberships=(*snapshot.session_memberships[:-1], last)
    )
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ) as error:
        dataset_session_nontrading_instruments(objects, snapshot)
    assert str(error.value.__cause__) == "historical_status_sources_conflict"


def test_two_original_captures_of_equal_native_intervals_keep_both_refs(tmp_path):
    objects, snapshot, master, _, cap = _inputs(tmp_path)
    _, second = _capture(tmp_path, [_row(stopReason="另一原始记录")])
    last = replace(
        snapshot.session_memberships[-1],
        source_observation_ids=(master.object_id, cap.capture_id, second.capture_id),
    )
    snapshot = replace(
        snapshot, session_memberships=(*snapshot.session_memberships[:-1], last)
    )
    actual = read_daily_bar_dataset(
        objects, publish_daily_bar_dataset_manifest(objects, snapshot)
    )
    assert dataset_session_nontrading_instruments(objects, actual.snapshot) == {
        historical.DAYS[-1]: historical.KEYS[:1]
    }
    assert set(actual.snapshot.session_memberships[-1].source_observation_ids) == {
        master.object_id,
        cap.capture_id,
        second.capture_id,
    }


@pytest.mark.parametrize(
    "unknown",
    [
        {"stopTime": "UNKNOWN"},
        {"type": "UNKNOWN"},
        {"endStopDate": ""},
        {"endStopDate": "20270101"},
        {"stopTime": "PM", "endStopDate": "20200117"},
    ],
)
def test_real_manifest_full_cold_rejects_unknown_and_zero_in_separate_captures(
    tmp_path, unknown
):
    objects, snapshot, master, _, cap = _inputs(tmp_path)
    _, uncertain = _capture(tmp_path, [_row(**unknown)])
    last = replace(
        snapshot.session_memberships[-1],
        source_observation_ids=(master.object_id, cap.capture_id, uncertain.capture_id),
    )
    snapshot = replace(
        snapshot, session_memberships=(*snapshot.session_memberships[:-1], last)
    )
    reference = publish_daily_bar_dataset_manifest(objects, snapshot)
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ) as error:
        read_daily_bar_dataset(objects, reference)
    assert str(error.value.__cause__) == "historical_status_sources_conflict"


@pytest.mark.parametrize("unknown", [{"stopTime": "UNKNOWN"}, {"type": "UNKNOWN"}])
def test_original_same_capture_unknown_plus_full_zero_public_dataset_counterexample(
    tmp_path, unknown
):
    objects, snapshot, _, _, _ = _inputs(tmp_path, rows=[_row(), _row(**unknown)])
    reference = publish_daily_bar_dataset_manifest(objects, snapshot)
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ) as error:
        read_daily_bar_dataset(objects, reference)
    assert str(error.value.__cause__) == "sse_suspension_conflicting_native_status"


def test_unknown_alone_does_not_become_nontrading_or_reject_existing_traded_roster(
    tmp_path,
):
    objects, snapshot, _, _, _ = _inputs(tmp_path, rows=[_row(stopTime="UNKNOWN")])
    last = replace(snapshot.session_memberships[-1], instruments=historical.KEYS)
    revision, materialization, _ = historical._side(
        objects,
        historical.DAYS[-1],
        historical.TDX_PROVIDER_DESCRIPTOR,
        instruments=historical.KEYS,
    )
    part = replace(
        snapshot.partitions[-1],
        provider=revision.provider,
        revision_id=revision.ref.revision_id,
        materialization_id=materialization.materialization_id,
        instruments=historical.KEYS,
    )
    snapshot = replace(
        snapshot,
        partitions=(*snapshot.partitions[:-1], part),
        session_memberships=(*snapshot.session_memberships[:-1], last),
    )
    actual = read_daily_bar_dataset(
        objects, publish_daily_bar_dataset_manifest(objects, snapshot)
    )
    assert actual.row_count == 4
    assert dataset_session_nontrading_instruments(objects, actual.snapshot) == {}
