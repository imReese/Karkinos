"""The reviewed SDK's 689 bug is corrected only by a new capture version."""

from __future__ import annotations

import json
from dataclasses import fields, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.market import reconciliation as recon
from data.market.capture import (
    capture_provider_payload,
    read_provider_capture,
    read_provider_raw_payload,
)
from data.market.normalize import normalize_daily_bar
from data.market.revision import publish_daily_bar_revision
from data.providers import tencent
from data.storage.objects import ContentAddressedObjectStore

DAY = date(2020, 10, 29)
CAPTURED = datetime(2026, 10, 21, 0, tzinfo=timezone.utc)
INSTRUMENT = InstrumentKey("689009", InstrumentType.STOCK)
V4 = "karkinos.akshare_tencent.daily_bar.v4"
V5 = "karkinos.akshare_tencent.daily_bar.v5"


def test_capture_version_is_necessary_for_689_scale():
    assert tencent._sdk_volume_scale(INSTRUMENT, "1.18.97") == 1
    for version in (
        "karkinos.akshare_tencent.daily_bar.v1",
        "karkinos.akshare_tencent.daily_bar.v3",
        V4,
    ):
        assert (
            tencent._sdk_volume_scale(INSTRUMENT, "1.18.97", adapter_version=version)
            == 1
        )
    assert tencent._sdk_volume_scale(
        INSTRUMENT, "1.18.97", adapter_version=V5
    ) == Decimal("0.01")
    with pytest.raises(tencent.AkshareTencentDailyBarRequestError, match="unreviewed"):
        tencent._sdk_volume_scale(INSTRUMENT, "1.18.98", adapter_version=V5)
    assert tencent._sdk_volume_scale(INSTRUMENT, "1.18.98", adapter_version=V4) == 1


@pytest.mark.parametrize(
    "symbol,kind,scale",
    [
        ("689009", InstrumentType.INDEX, "1"),
        ("689009", InstrumentType.ETF, "1"),
        ("688001", InstrumentType.STOCK, "1"),
        ("600000", InstrumentType.STOCK, "1"),
        ("000001", InstrumentType.STOCK, "100"),
        ("000001", InstrumentType.INDEX, "1"),
    ],
)
def test_other_typed_units_unchanged(symbol, kind, scale):
    key = InstrumentKey(symbol, kind)
    for version in (V4, V5):
        assert tencent._sdk_volume_scale(
            key, "1.18.97", adapter_version=version
        ) == Decimal(scale)


class FakeSDK:
    __version__ = "1.18.97"

    def __init__(self, sdk_version="1.18.97"):
        self.__version__ = sdk_version
        self.calls = []

    def stock_zh_a_hist_tx(self, **kwargs):
        self.calls.append(kwargs)
        return pd.DataFrame(
            [[DAY, 33.0, 38.5, 49.8, 33.0, 4095492200.0, 0.7102, 1584100700.0]],
            columns=[
                "date",
                "open",
                "close",
                "high",
                "low",
                "volume",
                "turnover",
                "amount",
            ],
        )


def test_new_fetch_labels_v5_without_rewriting_native_frame():
    from data.market.contracts import DailyBarRequest

    client = FakeSDK()
    batch = tencent.AkshareTencentDailyBarProvider(
        client, clock=lambda: CAPTURED
    ).fetch_daily_bars(DailyBarRequest((INSTRUMENT,), DAY, DAY))
    payload = json.loads(batch.raw_payload)
    assert batch.adapter_version == V5
    assert payload["schema"] == "akshare.tencent.stock_zh_a_hist_tx.dataframe.v5"
    assert payload["calls"][0]["volume_scale_to_shares"] == "0.01"
    assert payload["calls"][0]["frame"]["data"][0][5] == 4095492200.0
    assert batch.rows[0].volume == Decimal("40954922")
    assert batch.rows[0].amount == Decimal("1584100700")
    assert len(client.calls) == 1
    unknown = FakeSDK("1.18.98")
    with pytest.raises(tencent.AkshareTencentDailyBarRequestError, match="unreviewed"):
        tencent.AkshareTencentDailyBarProvider(
            unknown, clock=lambda: CAPTURED
        ).fetch_daily_bars(DailyBarRequest((INSTRUMENT,), DAY, DAY))
    assert unknown.calls == []


def native_fixture(store, version, *, metadata_scale=None, marker=True, sdk="1.18.97"):
    scale = Decimal("1") if version == 4 else Decimal("0.01")
    payload = {
        "schema": f"akshare.tencent.stock_zh_a_hist_tx.dataframe.v{version}",
        "sdk_version": sdk,
        "calls": [
            {
                "symbol": "sh689009",
                "request": {
                    "symbol": "sh689009",
                    "start_date": "20201029",
                    "end_date": "20201029",
                    "adjust": "",
                },
                "volume_scale_to_shares": metadata_scale or str(scale),
                "volume_normalization": tencent._VOLUME_FLOAT_NORMALIZATION
                if marker
                else None,
                "amount_normalization": tencent._AMOUNT_FLOAT_NORMALIZATION,
                "frame": {
                    "columns": [
                        "date",
                        "open",
                        "close",
                        "high",
                        "low",
                        "volume",
                        "amount",
                    ],
                    "data": [
                        [
                            "2020-10-29",
                            33.0,
                            38.5,
                            49.8,
                            33.0,
                            4095492200.0,
                            1584100700.0,
                        ]
                    ],
                },
            }
        ],
    }
    capture = capture_provider_payload(
        store,
        provider="akshare_tencent",
        operation="daily_bars",
        request={
            "kind": "daily_bars",
            "frequency": "1d",
            "start_date": "2020-10-29",
            "end_date": "2020-10-29",
            "instruments": [{"symbol": "689009", "instrument_type": "stock"}],
        },
        raw_payload=json.dumps(payload).encode(),
        payload_format=payload["schema"],
        adapter_version=f"karkinos.akshare_tencent.daily_bar.v{version}",
        started_at=CAPTURED,
        completed_at=CAPTURED,
    )
    bar = normalize_daily_bar(
        instrument=INSTRUMENT,
        session_date=DAY,
        event_time=datetime(2020, 10, 29, 7, tzinfo=timezone.utc),
        available_at=CAPTURED,
        captured_at=CAPTURED,
        open_value=33,
        high_value=49.8,
        low_value=33,
        close_value=38.5,
        volume=Decimal("4095492200") * scale,
        amount=1584100700,
        suspended=False,
    )
    revision, mat = publish_daily_bar_revision(
        store, capture=capture, bars=(bar,), normalizer_version="fixture.native.v1"
    )
    return capture, revision, mat, bar


def test_old_v4_retains_original_interpretation_and_new_v5_replays(tmp_path):
    store = ContentAddressedObjectStore(tmp_path / "objects")
    old = native_fixture(store, 4)
    new = native_fixture(store, 5)
    with recon.tencent_tushare_native_read_scope():
        for capture, _, mat, bar in (old, new):
            recon._validate_tencent_tushare_reported_amount(store, mat, (bar,))
            assert read_provider_capture(store, mat.capture_ref) == capture
        assert len(recon._TENCENT_TUSHARE_NATIVE_INDEXES.get()) == 2
        assert old[3].volume == new[3].volume * 100
        # Reinterpreting an old v4 bar as fixed is not permitted.
        with pytest.raises(ValueError, match="evidence_invalid"):
            recon._validate_tencent_tushare_reported_amount(
                store, old[2], (replace(old[3], volume=new[3].volume),)
            )
    assert read_provider_raw_payload(store, old[0]) != read_provider_raw_payload(
        store, new[0]
    )


@pytest.mark.parametrize(
    "version,scale,marker,sdk",
    [
        (4, "0.01", True, "1.18.97"),
        (5, "1", True, "1.18.97"),
        (5, "0.01", False, "1.18.97"),
        (5, "0.01", True, "1.18.98"),
    ],
)
def test_wrong_native_metadata_never_gets_accepted(
    tmp_path, version, scale, marker, sdk
):
    store = ContentAddressedObjectStore(tmp_path / "objects")
    _, _, mat, bar = native_fixture(
        store, version, metadata_scale=scale, marker=marker, sdk=sdk
    )
    with recon.tencent_tushare_native_read_scope():
        with pytest.raises(ValueError, match="evidence_invalid"):
            recon._validate_tencent_tushare_reported_amount(store, mat, (bar,))
        assert recon._TENCENT_TUSHARE_NATIVE_INDEXES.get() == {}


@pytest.mark.parametrize("version", [4, 5])
@pytest.mark.parametrize("part", ["raw", "capture"])
def test_both_versions_rehash_warm_raw_and_capture(tmp_path, version, part):
    store = ContentAddressedObjectStore(tmp_path / "objects")
    capture, _, mat, bar = native_fixture(store, version)
    ref = capture.raw_object_ref if part == "raw" else capture.capture_ref
    path = store._path_for(ref.object_id)
    original = path.read_bytes()
    with recon.tencent_tushare_native_read_scope():
        recon._validate_tencent_tushare_reported_amount(store, mat, (bar,))
        path.chmod(0o600)
        path.write_bytes(original + b" ")
        with pytest.raises(Exception, match="mismatch"):
            recon._validate_tencent_tushare_reported_amount(store, mat, (bar,))
        assert recon._TENCENT_TUSHARE_NATIVE_INDEXES.get() == {}
        path.write_bytes(original)
        recon._validate_tencent_tushare_reported_amount(store, mat, (bar,))


@pytest.mark.parametrize(
    "field,value",
    [
        ("open", Decimal("33.01")),
        ("volume", Decimal("40954923")),
        ("amount", Decimal("1584100800")),
        ("event_time", CAPTURED),
        ("available_at", datetime(2020, 10, 29, 7, tzinfo=timezone.utc)),
        ("captured_at", datetime(2020, 10, 29, 7, tzinfo=timezone.utc)),
        ("suspended", True),
    ],
)
def test_v5_warm_index_never_replaces_selected_bar_validation(tmp_path, field, value):
    store = ContentAddressedObjectStore(tmp_path / "objects")
    _, _, mat, bar = native_fixture(store, 5)
    with recon.tencent_tushare_native_read_scope():
        recon._validate_tencent_tushare_reported_amount(store, mat, (bar,))
        with pytest.raises(ValueError, match="evidence_invalid"):
            recon._validate_tencent_tushare_reported_amount(
                store,
                mat,
                (
                    SimpleNamespace(
                        **(
                            {item.name: getattr(bar, item.name) for item in fields(bar)}
                            | {field: value}
                        )
                    ),
                ),
            )
        assert recon._TENCENT_TUSHARE_NATIVE_INDEXES.get() == {}
