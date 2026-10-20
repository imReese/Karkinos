"""Historical status keeps its own capture, date and exploratory boundary."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import (
    DailyBarDatasetMembership,
    DailyBarDatasetPartition,
    DailyBarDatasetSnapshot,
)
from data.dataset.reader import (
    DatasetReaderIntegrityError,
    daily_bar_dataset_read_scope,
    dataset_session_nontrading_instruments,
    read_daily_bar_dataset,
)
from data.market.capture import capture_provider_payload
from data.market.contracts import DailyBarRequest
from data.providers.tdx import TDX_PROVIDER_DESCRIPTOR
from data.storage.objects import ContentAddressedObjectStore
from tests.server.test_verified_interval_dataset import _side

DAYS = (date(2020, 1, 15), date(2020, 1, 16))
KEYS = tuple(
    InstrumentKey(symbol, InstrumentType.STOCK) for symbol in ("600000", "600001")
)
MASTER_AT = datetime(2026, 10, 16, 8, tzinfo=timezone.utc)
CAPTURED_AT = MASTER_AT + timedelta(days=2)
FIELDS = [
    "date",
    "code",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "adjustflag",
    "tradestatus",
]


def _inputs(tmp_path, *, mutate=None, capture_overrides=None):
    objects = ContentAddressedObjectStore(tmp_path / "objects")
    master = {
        "schema_version": "karkinos.market_universe_snapshot.v2",
        "trade_date": "2026-10-16",
        "membership_basis": "current_active_stock_master",
        "availability_basis": "capture_completed_at",
        "observation_basis": "adapter_response",
        "capture_started_at": MASTER_AT.isoformat(),
        "capture_completed_at": MASTER_AT.isoformat(),
        "available_at": MASTER_AT.isoformat(),
        "members": [{"symbol": key.symbol} for key in KEYS],
    }
    master_ref = objects.put_bytes(json.dumps(master).encode())
    request = DailyBarRequest(KEYS, *DAYS).to_capture_request()
    payload = {
        "schema": "baostock.history_k_data_plus.rows.v2",
        "request": {
            "frequency": "d",
            "adjustflag": "3",
            "start_date": str(DAYS[0]),
            "end_date": str(DAYS[-1]),
            "fields": FIELDS,
        },
        "calls": [
            {
                "code": "sh." + key.symbol,
                "fields": FIELDS,
                "rows": [
                    [
                        str(day),
                        "sh." + key.symbol,
                        "10",
                        "10",
                        "10",
                        "10",
                        "" if index == 0 and day == DAYS[-1] else "100",
                        "0.0000" if index == 0 and day == DAYS[-1] else "1000",
                        "3",
                        "0" if index == 0 and day == DAYS[-1] else "1",
                    ]
                    for day in DAYS
                ],
            }
            for index, key in enumerate(KEYS)
        ],
    }
    if mutate is not None:
        mutate(request, payload)
    capture_kwargs = {
        "provider": "baostock",
        "operation": "daily_bars",
        "request": request,
        "raw_payload": json.dumps(payload).encode(),
        "payload_format": "baostock.history_k_data_plus.rows.v2",
        "adapter_version": "karkinos.baostock.daily_bar.v2",
        "started_at": CAPTURED_AT - timedelta(seconds=1),
        "completed_at": CAPTURED_AT,
        "record_count": 3,
        **(capture_overrides or {}),
    }
    capture = capture_provider_payload(objects, **capture_kwargs)
    partitions = []
    for day in DAYS:
        keys = KEYS if day == DAYS[0] else KEYS[1:]
        revision, materialization, _ = _side(
            objects, day, TDX_PROVIDER_DESCRIPTOR, instruments=keys
        )
        partitions.append(
            DailyBarDatasetPartition(
                day,
                revision.provider,
                revision.ref.revision_id,
                materialization.materialization_id,
                instruments=keys,
            )
        )
    snapshot = DailyBarDatasetSnapshot(
        start_date=DAYS[0],
        end_date=DAYS[-1],
        cutoff=CAPTURED_AT,
        instruments=KEYS,
        resolver_policy_id="fixture.exploratory.v1",
        market_schema_version=revision.market_schema_version,
        partitions=tuple(partitions),
        session_memberships=tuple(
            DailyBarDatasetMembership(
                day,
                KEYS if day == DAYS[0] else KEYS[1:],
                CAPTURED_AT,
                (master_ref.object_id, capture.capture_id),
            )
            for day in DAYS
        ),
        universe_policy_id="fixture.current_survivor_ipo_minus_explicit_halt.v1",
    )
    return objects, snapshot, master_ref, capture


def test_historical_halt_replays_separately_from_unchanged_current_master(tmp_path):
    objects, snapshot, master_ref, capture = _inputs(tmp_path)
    original_master = objects.read_bytes(master_ref)
    ref = publish_daily_bar_dataset_manifest(objects, snapshot)
    restored = read_daily_bar_dataset(objects, ref)
    assert restored.row_count == 3
    assert restored.snapshot.membership_evidence_bound is False
    assert dataset_session_nontrading_instruments(objects, restored.snapshot) == {
        DAYS[-1]: KEYS[:1]
    }
    assert objects.read_bytes(master_ref) == original_master
    assert json.loads(original_master)["trade_date"] == "2026-10-16"
    assert capture.record_count == 3  # Four raw rows include one explicit halt.


def test_absent_status_row_remains_unknown(tmp_path):
    objects, snapshot, _, _ = _inputs(
        tmp_path, mutate=lambda request, raw: raw["calls"][0]["rows"].pop()
    )
    assert dataset_session_nontrading_instruments(objects, snapshot) == {}


@pytest.mark.parametrize(
    "case",
    [
        "raw_only",
        "decision",
        "availability",
        "wrong_day",
        "traded_halt",
        "provider",
        "operation",
        "adapter",
        "format",
        "count",
        "request",
        "fields",
        "code",
        "date",
        "adjustment",
        "status",
        "duplicate",
        "missing_call",
        "active_volume",
        "active_amount",
    ],
)
def test_historical_status_rejects_unbound_or_malformed_evidence(tmp_path, case):
    overrides = {
        "provider": {"provider": "tencent"},
        "operation": {"operation": "query_all_stock"},
        "adapter": {"adapter_version": "karkinos.baostock.daily_bar.v1"},
        "format": {"payload_format": "unknown"},
        "count": {"record_count": 4},
    }.get(case)

    def mutate(request, raw):
        row = raw["calls"][0]["rows"][-1]
        if case == "request":
            request["frequency"] = "1m"
        elif case == "fields":
            raw["calls"][0]["fields"] = FIELDS[:-1]
        elif case == "code":
            row[1] = "sz.600000"
        elif case == "date":
            row[0] = "2020-01-17"
        elif case == "adjustment":
            row[-2] = "1"
        elif case == "status":
            row[-1] = "unknown"
        elif case == "duplicate":
            raw["calls"][0]["rows"][-1] = raw["calls"][0]["rows"][0]
        elif case == "missing_call":
            raw["calls"].pop()
        elif case in {"active_volume", "active_amount"}:
            row[6 if case == "active_volume" else 7] = "1"

    objects, snapshot, _, capture = _inputs(
        tmp_path, mutate=mutate, capture_overrides=overrides
    )
    if case in {"raw_only", "decision", "availability", "wrong_day", "traded_halt"}:
        membership = snapshot.session_memberships[-1]
        if case == "raw_only":
            membership = replace(
                membership, source_observation_ids=(capture.capture_id,)
            )
        elif case == "decision":
            membership = replace(membership, decision_at=CAPTURED_AT)
        elif case == "availability":
            membership = replace(membership, available_at=MASTER_AT)
        elif case == "wrong_day":
            membership = replace(membership, partition_date=date(2020, 1, 14))
        elif case == "traded_halt":
            membership = replace(membership, instruments=KEYS)
        # Exercise evidence validation independently of the already strict
        # partition/date shape validation in the immutable snapshot value.
        from types import SimpleNamespace

        snapshot = SimpleNamespace(session_memberships=(membership,))
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ):
        dataset_session_nontrading_instruments(objects, snapshot)


def test_status_bytes_are_reused_only_within_one_read_and_cold_tamper_fails(
    tmp_path, monkeypatch
):
    objects, snapshot, _, capture = _inputs(tmp_path)
    counts = Counter()
    read_bytes = objects.read_bytes

    def counted(ref):
        counts[ref.object_id] += 1
        return read_bytes(ref)

    monkeypatch.setattr(objects, "read_bytes", counted)
    assert (
        dataset_session_nontrading_instruments(objects, snapshot)[DAYS[-1]] == KEYS[:1]
    )
    assert counts[capture.raw_object_ref.object_id] == 1
    dataset_session_nontrading_instruments(objects, snapshot)
    assert counts[capture.raw_object_ref.object_id] == 2
    ref = publish_daily_bar_dataset_manifest(objects, snapshot)
    with daily_bar_dataset_read_scope():
        restored = read_daily_bar_dataset(objects, ref)
        assert counts[capture.raw_object_ref.object_id] == 3
        projected = dataset_session_nontrading_instruments(objects, restored.snapshot)
        projected.clear()
        assert dataset_session_nontrading_instruments(objects, restored.snapshot) == {
            DAYS[-1]: KEYS[:1]
        }
        assert (
            dataset_session_nontrading_instruments(
                objects, restored.snapshot, session_date=DAYS[0]
            )
            == {}
        )
        assert counts[capture.raw_object_ref.object_id] == 3
        changed = replace(
            restored.snapshot,
            session_memberships=(
                replace(
                    restored.snapshot.session_memberships[0], available_at=MASTER_AT
                ),
                *restored.snapshot.session_memberships[1:],
            ),
        )
        with pytest.raises(
            DatasetReaderIntegrityError, match="membership_evidence_invalid"
        ):
            dataset_session_nontrading_instruments(objects, changed)
    digest = capture.raw_object_ref.digest
    raw_path = objects.root / "sha256" / digest[:2] / digest[2:]
    raw_path.chmod(0o644)
    raw_path.write_bytes(b"tampered")
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ):
        dataset_session_nontrading_instruments(objects, snapshot)


def test_mutable_membership_dto_cannot_reuse_verified_status_projection(tmp_path):
    objects, snapshot, _, _ = _inputs(tmp_path)
    original = snapshot.session_memberships[-1]
    mutable = SimpleNamespace(
        partition_date=original.partition_date,
        instruments=original.instruments,
        available_at=original.available_at,
        source_observation_ids=original.source_observation_ids,
        decision_at=original.decision_at,
        maintenance_instruments=original.maintenance_instruments,
    )
    snapshot = replace(
        snapshot,
        session_memberships=(*snapshot.session_memberships[:-1], mutable),
    )
    with daily_bar_dataset_read_scope():
        assert dataset_session_nontrading_instruments(objects, snapshot) == {
            DAYS[-1]: KEYS[:1]
        }
        mutable.available_at = MASTER_AT
        with pytest.raises(
            DatasetReaderIntegrityError, match="membership_evidence_invalid"
        ):
            dataset_session_nontrading_instruments(objects, snapshot)


def test_mutable_empty_maintenance_list_cannot_hide_halted_member(tmp_path):
    objects, snapshot, _, _ = _inputs(tmp_path)
    maintenance = []
    membership = replace(
        snapshot.session_memberships[-1], maintenance_instruments=maintenance
    )
    snapshot = replace(
        snapshot,
        session_memberships=(*snapshot.session_memberships[:-1], membership),
    )
    with daily_bar_dataset_read_scope():
        assert dataset_session_nontrading_instruments(objects, snapshot) == {
            DAYS[-1]: KEYS[:1]
        }
        maintenance.append(KEYS[0])
        with pytest.raises(
            DatasetReaderIntegrityError, match="membership_evidence_invalid"
        ):
            dataset_session_nontrading_instruments(objects, snapshot)
