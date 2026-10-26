"""Official PDF status enters the existing membership/time/conflict owner."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.reader import (
    DatasetReaderIntegrityError,
    dataset_session_nontrading_instruments,
    read_daily_bar_dataset,
)
from data.providers.szse_suspension import (
    SSE_SUSPENSION_ADAPTER_VERSION,
    SZSE_SUSPENSION_V2_ADAPTER_VERSION,
)
from tests.data.dataset import test_historical_session_status as historical
from tests.data.providers.test_szse_suspension import TEXT, _capture


def _inputs(tmp_path, monkeypatch, source="szse_v1"):
    symbols = ("688981", "688982") if source == "sse" else ("001212", "001213")
    keys = tuple(InstrumentKey(symbol, InstrumentType.STOCK) for symbol in symbols)
    days = (date(2025, 3, 27), date(2025, 3, 28))
    monkeypatch.setattr(historical, "KEYS", keys)
    monkeypatch.setattr(historical, "DAYS", days)
    objects, snapshot, master, _ = historical._inputs(tmp_path)
    if source == "sse":
        _, capture = _capture(
            tmp_path,
            text=TEXT.replace("001212", symbols[0]),
            provider="sse_disclosure",
            adapter_version=SSE_SUSPENSION_ADAPTER_VERSION,
            request={
                "symbol": symbols[0],
                "url": (
                    "https://star.sse.com.cn/disclosure/listedinfo/announcement/c/new/"
                    "2025-04-01/688981_20250401_fixture.pdf"
                ),
            },
        )
    elif source == "szse_v2":
        _, capture = _capture(
            tmp_path, adapter_version=SZSE_SUSPENSION_V2_ADAPTER_VERSION
        )
    else:
        _, capture = _capture(tmp_path)
    snapshot = replace(
        snapshot,
        cutoff=capture.completed_at,
        session_memberships=tuple(
            replace(
                m,
                available_at=(
                    capture.completed_at
                    if m.partition_date == days[-1]
                    else historical.MASTER_AT
                ),
                source_observation_ids=(
                    (master.object_id, capture.capture_id)
                    if m.partition_date == days[-1]
                    else (master.object_id,)
                ),
            )
            for m in snapshot.session_memberships
        ),
    )
    return objects, snapshot, master, capture, keys, days


@pytest.mark.parametrize("source", ["szse_v1", "szse_v2", "sse"])
def test_real_unicode_pdf_full_canonical_dataset_and_public_nontrading(
    tmp_path, monkeypatch, source
):
    objects, snapshot, master, capture, keys, days = _inputs(
        tmp_path, monkeypatch, source
    )
    original_master = objects.read_bytes(master)
    ref = publish_daily_bar_dataset_manifest(objects, snapshot)
    actual = read_daily_bar_dataset(objects, ref)
    assert actual.row_count == 3
    assert dataset_session_nontrading_instruments(objects, actual.snapshot) == {
        days[-1]: keys[:1]
    }
    assert actual.snapshot.membership_evidence_bound is False
    assert all(m.decision_at is None for m in actual.snapshot.session_memberships)
    assert actual.snapshot.session_memberships[-1].available_at == capture.completed_at
    assert objects.read_bytes(master) == original_master


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
@pytest.mark.parametrize("source", ["szse_v1", "szse_v2", "sse"])
def test_existing_membership_fences_apply_to_official_pdf(
    tmp_path, monkeypatch, case, source
):
    objects, snapshot, _, capture, keys, _ = _inputs(tmp_path, monkeypatch, source)
    membership = snapshot.session_memberships[-1]
    changes = {
        "decision": {"decision_at": capture.completed_at},
        "availability": {"available_at": historical.MASTER_AT},
        "missing_master": {"source_observation_ids": (capture.capture_id,)},
        "traded": {"instruments": keys},
        "maintenance": {"maintenance_instruments": keys[:1]},
        "after_cutoff": {},
    }[case]
    if case == "after_cutoff":
        with pytest.raises((DatasetReaderIntegrityError, ValueError)):
            snapshot = replace(snapshot, cutoff=historical.MASTER_AT)
            read_daily_bar_dataset(
                objects, publish_daily_bar_dataset_manifest(objects, snapshot)
            )
    else:
        with pytest.raises(
            DatasetReaderIntegrityError, match="membership_evidence_invalid"
        ):
            dataset_session_nontrading_instruments(
                objects,
                SimpleNamespace(session_memberships=(replace(membership, **changes),)),
            )


def test_explicit_resumption_cannot_be_hidden_by_other_full_day_status(
    tmp_path, monkeypatch
):
    objects, snapshot, master, capture, _, _ = _inputs(tmp_path, monkeypatch)
    _, resume = _capture(
        tmp_path,
        text=(
            "证券代码：001212。公司股票自2025年3月27日开市起停牌。"
            "公司股票自2025年3月28日开市起复牌。"
        ),
    )
    membership = replace(
        snapshot.session_memberships[-1],
        source_observation_ids=(
            master.object_id,
            capture.capture_id,
            resume.capture_id,
        ),
    )
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ):
        dataset_session_nontrading_instruments(
            objects, SimpleNamespace(session_memberships=(membership,))
        )
