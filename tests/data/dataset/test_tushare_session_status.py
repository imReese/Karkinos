"""TuShare status is dated backfill evidence, separate from master and prices."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.reader import (
    DatasetReaderIntegrityError,
    daily_bar_dataset_read_scope,
    dataset_session_nontrading_instruments,
    read_daily_bar_dataset,
)
from data.market.capture import capture_provider_payload
from data.providers.tushare_status import (
    TUSHARE_STATUS_ADAPTER_VERSION,
    TUSHARE_STATUS_FIELDS,
    TUSHARE_STATUS_PAYLOAD_FORMAT,
    TUSHARE_STATUS_SDK_VERSION,
    serialize_tushare_status_frame,
)
from tests.data.dataset.test_historical_session_status import (
    CAPTURED_AT,
    DAYS,
    KEYS,
    MASTER_AT,
    _inputs,
)


def _tushare_inputs(
    tmp_path, *, operation="suspend_d", day=None, status="S", timing=None
):
    objects, snapshot, master, bao = _inputs(tmp_path)
    request = {
        "ts_code": "600000.SH",
        "start_date": DAYS[0].strftime("%Y%m%d"),
        "end_date": DAYS[-1].strftime("%Y%m%d"),
        "fields": TUSHARE_STATUS_FIELDS,
    }
    frame = pd.DataFrame(
        [["600000.SH", (day or DAYS[-1]).strftime("%Y%m%d"), timing, status]],
        columns=TUSHARE_STATUS_FIELDS.split(","),
    )
    available = CAPTURED_AT + timedelta(minutes=1)
    capture = capture_provider_payload(
        objects,
        provider="tushare",
        operation=operation,
        request=request,
        raw_payload=json.dumps(
            {
                "schema": TUSHARE_STATUS_PAYLOAD_FORMAT,
                "sdk_version": TUSHARE_STATUS_SDK_VERSION,
                "request": request,
                "frame": serialize_tushare_status_frame(frame),
            },
            allow_nan=False,
        ).encode(),
        adapter_version=TUSHARE_STATUS_ADAPTER_VERSION,
        payload_format=TUSHARE_STATUS_PAYLOAD_FORMAT,
        started_at=available - timedelta(seconds=1),
        completed_at=available,
        record_count=1,
    )
    snapshot = replace(
        snapshot,
        cutoff=available,
        session_memberships=tuple(
            replace(
                membership,
                available_at=available,
                source_observation_ids=(master.object_id, capture.capture_id),
            )
            for membership in snapshot.session_memberships
        ),
    )
    return objects, snapshot, master, capture, bao


def test_native_cold_dataset_replays_tushare_halt_and_unchanged_current_master(
    tmp_path,
):
    objects, snapshot, master, capture, _ = _tushare_inputs(tmp_path)
    master_bytes = objects.read_bytes(master)
    ref = publish_daily_bar_dataset_manifest(objects, snapshot)
    restored = read_daily_bar_dataset(objects, ref)
    assert restored.row_count == 3
    assert dataset_session_nontrading_instruments(objects, restored.snapshot) == {
        DAYS[-1]: KEYS[:1]
    }
    assert restored.snapshot.membership_evidence_bound is False
    assert all(
        item.decision_at is None for item in restored.snapshot.session_memberships
    )
    assert all(
        item.available_at == capture.completed_at
        for item in restored.snapshot.session_memberships
    )
    assert objects.read_bytes(master) == master_bytes
    assert json.loads(master_bytes)["trade_date"] == "2026-10-16"
    assert json.loads(master_bytes)["available_at"] == MASTER_AT.isoformat()


@pytest.mark.parametrize(
    "case", ["decision", "availability", "missing_master", "traded", "maintenance"]
)
def test_existing_membership_safety_checks_apply_to_tushare_backfill(tmp_path, case):
    objects, snapshot, _, capture, _ = _tushare_inputs(tmp_path)
    membership = snapshot.session_memberships[-1]
    changes = {
        "decision": {"decision_at": capture.completed_at},
        "availability": {"available_at": MASTER_AT},
        "missing_master": {"source_observation_ids": (capture.capture_id,)},
        "traded": {"instruments": KEYS},
        "maintenance": {"maintenance_instruments": KEYS[:1]},
    }[case]
    snapshot = SimpleNamespace(session_memberships=(replace(membership, **changes),))
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ):
        dataset_session_nontrading_instruments(objects, snapshot)


def test_tushare_price_capture_never_becomes_status_evidence(tmp_path):
    objects, snapshot, _, _, _ = _tushare_inputs(tmp_path, operation="daily_bars")
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ):
        dataset_session_nontrading_instruments(objects, snapshot)


def test_tushare_halt_conflicting_with_explicit_bao_trading_status_is_rejected(
    tmp_path,
):
    objects, snapshot, master, capture, bao = _tushare_inputs(tmp_path, day=DAYS[0])
    membership = replace(
        snapshot.session_memberships[0],
        instruments=KEYS[1:],
        source_observation_ids=(master.object_id, bao.capture_id, capture.capture_id),
    )
    snapshot = SimpleNamespace(session_memberships=(membership,))
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ):
        dataset_session_nontrading_instruments(objects, snapshot)


def test_tushare_raw_status_is_decoded_once_in_scope_then_cold_tamper_rejected(
    tmp_path, monkeypatch
):
    objects, snapshot, _, capture, _ = _tushare_inputs(tmp_path)
    counts = Counter()
    original = objects.read_bytes

    def counted(ref):
        counts[ref.object_id] += 1
        return original(ref)

    monkeypatch.setattr(objects, "read_bytes", counted)
    with daily_bar_dataset_read_scope():
        expected = {DAYS[-1]: KEYS[:1]}
        assert dataset_session_nontrading_instruments(objects, snapshot) == expected
        assert dataset_session_nontrading_instruments(objects, snapshot) == expected
        assert counts[capture.raw_object_ref.object_id] == 1
    assert dataset_session_nontrading_instruments(objects, snapshot) == expected
    assert counts[capture.raw_object_ref.object_id] == 2
    digest = capture.raw_object_ref.digest
    raw_path = objects.root / "sha256" / digest[:2] / digest[2:]
    raw_path.chmod(0o644)
    raw_path.write_bytes(b"tampered")
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ):
        dataset_session_nontrading_instruments(objects, snapshot)


@pytest.mark.parametrize("status,timing", [("R", None), ("S", "09:30-10:30")])
@pytest.mark.parametrize("reverse", [False, True])
def test_bao_full_day_halt_cannot_hide_tushare_counterevidence(
    tmp_path, status, timing, reverse
):
    objects, snapshot, master, capture, bao = _tushare_inputs(
        tmp_path, status=status, timing=timing
    )
    status_ids = (bao.capture_id, capture.capture_id)
    if reverse:
        status_ids = status_ids[::-1]
    membership = replace(
        snapshot.session_memberships[-1],
        source_observation_ids=(master.object_id, *status_ids),
    )
    snapshot = SimpleNamespace(session_memberships=(membership,))
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ):
        dataset_session_nontrading_instruments(objects, snapshot)


@pytest.mark.parametrize("reverse", [False, True])
def test_bao_explicit_activity_and_tushare_resumption_are_compatible(tmp_path, reverse):
    objects, snapshot, master, capture, bao = _tushare_inputs(
        tmp_path, status="R", day=DAYS[0]
    )
    status_ids = (bao.capture_id, capture.capture_id)
    if reverse:
        status_ids = status_ids[::-1]
    membership = replace(
        snapshot.session_memberships[0],
        source_observation_ids=(master.object_id, *status_ids),
    )
    snapshot = SimpleNamespace(session_memberships=(membership,))
    assert dataset_session_nontrading_instruments(objects, snapshot) == {}


@pytest.mark.parametrize("status,timing", [("R", None), ("S", "09:30-10:30")])
def test_tushare_counterevidence_alone_never_excludes_instruments(
    tmp_path, status, timing
):
    objects, snapshot, _, _, _ = _tushare_inputs(tmp_path, status=status, timing=timing)
    assert dataset_session_nontrading_instruments(objects, snapshot) == {}


@pytest.mark.parametrize("reverse", [False, True])
def test_actual_dated_master_halt_and_tushare_resumption_conflict(tmp_path, reverse):
    from data.dataset.model import DailyBarDatasetMembership
    from data.store import normalize_stock_master_metadata
    from server.services.market_universe_truth import normalize_a_share_members
    from tests.data.providers.test_official_stock_master import (
        _capture as official_capture,
    )
    from tests.data.providers.test_tushare_status import _capture as status_capture
    from tests.server.test_verified_interval_dataset import DAYS as OFFICIAL_DAYS

    day = OFFICIAL_DAYS[-1]
    objects, capture = status_capture(
        tmp_path,
        code="000001.SZ",
        rows=[["000001.SZ", day.strftime("%Y%m%d"), None, "R"]],
    )
    rows, refs, started, completed = official_capture(objects)
    members = normalize_a_share_members([row["symbol"] for row in rows])
    master = {
        "schema_version": "karkinos.market_universe_snapshot.v3",
        "trade_date": str(day),
        "membership_basis": "current_active_stock_master",
        "availability_basis": "capture_completed_at",
        "observation_basis": "adapter_response",
        "capture_started_at": started.isoformat(),
        "capture_completed_at": completed.isoformat(),
        "available_at": completed.isoformat(),
        "members": members,
        "member_metadata": normalize_stock_master_metadata(rows, members),
        "source_capture_ids": sorted(refs),
    }
    master_ref = objects.put_bytes(json.dumps(master).encode())
    identities = (master_ref.object_id, capture.capture_id)
    if reverse:
        identities = identities[::-1]
    membership = DailyBarDatasetMembership(
        day, KEYS[1:], capture.completed_at, identities, decision_at=None
    )
    snapshot = SimpleNamespace(session_memberships=(membership,))
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ) as error:
        dataset_session_nontrading_instruments(objects, snapshot)
    assert str(error.value.__cause__) == "historical_status_sources_conflict"
