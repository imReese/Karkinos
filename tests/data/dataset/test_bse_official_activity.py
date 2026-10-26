"""Official no-transaction evidence stays separate from price bars and PIT."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
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
    dataset_session_nontrading_instruments,
    read_daily_bar_dataset,
)
from data.market.capture import capture_provider_payload
from data.providers.bse_official_activity import read_bse_official_historical_activity
from data.providers.tdx import TDX_PROVIDER_DESCRIPTOR
from data.storage.objects import ContentAddressedObjectStore
from tests.server.test_verified_interval_dataset import _side

DAYS = (date(2020, 1, 15), date(2020, 1, 16))
KEYS = tuple(
    InstrumentKey(symbol, InstrumentType.STOCK) for symbol in ("920058", "920123")
)
MASTER_AT = datetime(2026, 10, 16, 8, tzinfo=UTC)
CAPTURED_AT = MASTER_AT + timedelta(days=2)


def _row(day, *, traded=False):
    return {
        "jsrq": day.strftime("%Y%m%d"),
        "jrkp": 10 if traded else 0,
        "jrsp": 10 if traded else 0,
        "drzd": 10 if traded else 0,
        "drzx": 10 if traded else 0,
        "cjl": 100 if traded else 0,
        "cjje": 1000 if traded else 0,
        "zrsp": 10,
    }


def _capture(objects, *, rows=None, adapter=None):
    # The third raw date makes absence on the middle requested day unknown,
    # while keeping that day within the observed source range.
    rows = (
        rows
        if rows is not None
        else [
            _row(DAYS[0], traded=True),
            _row(DAYS[1]),
            _row(DAYS[1] + timedelta(days=1), traded=True),
        ]
    )
    return capture_provider_payload(
        objects,
        provider="bse_official_kline_probe",
        operation="public_kline_probe",
        request={
            "method": "GET",
            "url": "https://www.bse.cn/companyEchartsController/getKLine/list/920058.do",
            "params": {
                "begin": "0",
                "end": "-1",
                "type": "dayKline",
                "xxfcbj": "2",
                "callback": "karkinosHistoricalKlineRead",
            },
            "headers": {
                "Referer": "https://www.bse.cn/products/neeq_listed_companies/company_time_sharing.html",
                "User-Agent": "Mozilla/5.0",
            },
        },
        raw_payload=(
            "karkinosHistoricalKlineRead("
            + json.dumps({"data": rows, "status": 0, "msg": ""})
            + ")"
        ).encode(),
        payload_format="bse.companyEcharts.kline.raw_public_response.probe.v1",
        adapter_version=adapter or "operation.bse.official_kline.public_probe.v1",
        started_at=CAPTURED_AT - timedelta(seconds=1),
        completed_at=CAPTURED_AT,
        record_count=None,
    )


def _inputs(tmp_path, *, rows=None, adapter=None):
    objects = ContentAddressedObjectStore(tmp_path / "objects")
    master = objects.put_bytes(
        json.dumps(
            {
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
        ).encode()
    )
    capture = _capture(objects, rows=rows, adapter=adapter)
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
                (master.object_id, capture.capture_id),
            )
            for day in DAYS
        ),
        universe_policy_id="fixture.current_survivor_minus_explicit_nontrading.v1",
    )
    return objects, snapshot, master, capture


def test_native_dataset_replays_zero_activity_without_zero_price_bar(tmp_path):
    objects, snapshot, master, capture = _inputs(tmp_path)
    master_bytes = objects.read_bytes(master)
    restored = read_daily_bar_dataset(
        objects, publish_daily_bar_dataset_manifest(objects, snapshot)
    )
    assert restored.row_count == 3
    assert all(bar.open > 0 for bar in restored.bars)
    assert not any(
        bar.instrument == KEYS[0] and bar.session_date == DAYS[1]
        for bar in restored.bars
    )
    assert dataset_session_nontrading_instruments(objects, restored.snapshot) == {
        DAYS[1]: KEYS[:1]
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


def test_missing_middle_date_never_establishes_nontrading(tmp_path):
    objects, snapshot, _, _ = _inputs(
        tmp_path,
        rows=[
            _row(DAYS[0], traded=True),
            _row(DAYS[1] + timedelta(days=1), traded=True),
        ],
    )
    assert dataset_session_nontrading_instruments(objects, snapshot) == {}


@pytest.mark.parametrize("reverse", [False, True])
def test_positive_activity_conflicts_with_explicit_no_transaction_fact(
    tmp_path, reverse
):
    objects, snapshot, master, capture = _inputs(tmp_path)
    counter = _capture(objects, rows=[_row(day, traded=True) for day in DAYS])
    identities = (capture.capture_id, counter.capture_id)
    membership = replace(
        snapshot.session_memberships[1],
        source_observation_ids=(
            master.object_id,
            *(identities[::-1] if reverse else identities),
        ),
    )
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ):
        dataset_session_nontrading_instruments(
            objects, SimpleNamespace(session_memberships=(membership,))
        )


@pytest.mark.parametrize(
    "case", ["decision", "availability", "missing_master", "traded"]
)
def test_existing_membership_guards_keep_official_activity_exploratory(tmp_path, case):
    objects, snapshot, _, capture = _inputs(tmp_path)
    changes = {
        "decision": {"decision_at": capture.completed_at},
        "availability": {"available_at": MASTER_AT},
        "missing_master": {"source_observation_ids": (capture.capture_id,)},
        "traded": {"instruments": KEYS},
    }[case]
    membership = replace(snapshot.session_memberships[1], **changes)
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ):
        dataset_session_nontrading_instruments(
            objects, SimpleNamespace(session_memberships=(membership,))
        )


@pytest.mark.parametrize(
    "case", ["adapter", "shape", "nonfinite", "zero_pair", "zero_price_activity"]
)
def test_unreviewed_or_inconsistent_source_never_becomes_nontrading(tmp_path, case):
    rows = [_row(day, traded=day == DAYS[0]) for day in DAYS]
    if case == "shape":
        rows[1]["unexpected"] = 0
    elif case == "nonfinite":
        rows[1]["cjje"] = float("nan")
    elif case == "zero_pair":
        rows[1]["cjl"] = 1
    elif case == "zero_price_activity":
        rows[1].update(cjl=1, cjje=1)
    objects, snapshot, _, capture = _inputs(
        tmp_path, rows=rows, adapter="unknown" if case == "adapter" else None
    )
    with pytest.raises((ValueError, TypeError)):
        read_bse_official_historical_activity(
            objects, objects.resolve_ref(capture.capture_id)
        )
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ):
        dataset_session_nontrading_instruments(objects, snapshot)
