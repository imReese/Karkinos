from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarProvider, DailyBarRequest
from data.market.ingestion import DailyBarIngestionCapturedFailure, ingest_daily_bars
from data.market.quality import RESEARCH_STRICT_DAILY
from data.market.revision import validate_daily_bar_materialization
from data.providers.tencent import (
    AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR,
    AkshareTencentDailyBarProvider,
    AkshareTencentDailyBarRequestError,
    AkshareTencentDailyBarResponseError,
)
from data.storage.objects import ContentAddressedObjectStore

DAY = date(2026, 9, 17)
AFTER_CLOSE = datetime(2026, 9, 17, 8, 0, tzinfo=timezone.utc)


class FakeTencent:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.frames: dict[str, pd.DataFrame] = {}

    def stock_zh_a_hist_tx(
        self,
        symbol="sz000001",
        start_date="19000101",
        end_date="20500101",
        adjust="",
        timeout=None,
    ):
        self.calls.append(
            {
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "adjust": adjust,
            }
        )
        return self.frames.get(symbol, pd.DataFrame())


def _frame(
    *,
    close: float,
    volume: float,
    amount: float,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [DAY],
            "open": [close + 0.04],
            "close": [close],
            "high": [close + 0.08],
            "low": [close - 0.03],
            "volume": [volume],
            "turnover": [0.0014],
            "amount": [amount],
        }
    )


def _request(*items: InstrumentKey) -> DailyBarRequest:
    return DailyBarRequest(tuple(items), DAY, DAY)


def test_tencent_provider_satisfies_canonical_protocol() -> None:
    provider = AkshareTencentDailyBarProvider(FakeTencent(), clock=lambda: AFTER_CLOSE)
    assert isinstance(provider, DailyBarProvider)
    assert provider.descriptor == AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR
    assert provider.descriptor.provider == "akshare_tencent"
    assert provider.descriptor.upstream_group == "tencent"
    assert provider.descriptor.supports_daily_bars(
        InstrumentType.STOCK, price_basis="unadjusted"
    )
    assert provider.descriptor.supports_daily_bars(
        InstrumentType.ETF, price_basis="unadjusted"
    )


def test_tencent_fetches_stock_and_etf_with_bounded_date_range() -> None:
    client = FakeTencent()
    client.frames["sh510300"] = _frame(
        close=4.532,
        volume=507_546_100,
        amount=2_304_178_600,
    )
    client.frames["sh600000"] = _frame(
        close=9.06,
        volume=45_671_100,
        amount=414_887_100,
    )

    result = AkshareTencentDailyBarProvider(
        client, clock=lambda: AFTER_CLOSE
    ).fetch_daily_bars(
        _request(
            InstrumentKey("600000", InstrumentType.STOCK),
            InstrumentKey("510300", InstrumentType.ETF),
        )
    )

    assert [call["symbol"] for call in client.calls] == ["sh510300", "sh600000"]
    for call in client.calls:
        assert call["start_date"] == "20260917"
        assert call["end_date"] == "20260917"
        assert call["adjust"] == ""

    etf, stock = result.rows
    assert etf.instrument == InstrumentKey("510300", InstrumentType.ETF)
    assert etf.volume == Decimal("507546100.0")
    assert etf.amount == Decimal("2304178600.0")
    assert stock.instrument == InstrumentKey("600000", InstrumentType.STOCK)
    assert stock.volume == Decimal("45671100.0")
    assert stock.amount == Decimal("414887100.0")


def test_tencent_preserves_sdk_dataframe_as_stable_raw_evidence() -> None:
    client = FakeTencent()
    client.frames["sh600000"] = _frame(
        close=9.06,
        volume=45_671_100,
        amount=414_887_100,
    )

    result = AkshareTencentDailyBarProvider(
        client, clock=lambda: AFTER_CLOSE
    ).fetch_daily_bars(_request(InstrumentKey("600000", InstrumentType.STOCK)))

    payload = json.loads(result.raw_payload)
    assert payload["schema"] == "akshare.tencent.stock_zh_a_hist_tx.dataframe.v5"
    assert payload["sdk_version"] == "1.18.97"
    assert payload["calls"][0]["volume_scale_to_shares"] == "1"
    assert payload["calls"][0]["symbol"] == "sh600000"
    assert payload["calls"][0]["request"] == {
        "symbol": "sh600000",
        "start_date": "20260917",
        "end_date": "20260917",
        "adjust": "",
    }
    assert payload["calls"][0]["frame"]["columns"] == [
        "date",
        "open",
        "close",
        "high",
        "low",
        "volume",
        "turnover",
        "amount",
    ]


@pytest.mark.parametrize(
    "symbol,sdk_volume,shares",
    [
        ("000001", 969082, Decimal("96908200")),
        ("600000", 45671100, Decimal("45671100")),
        ("688001", 1234567, Decimal("1234567")),
    ],
)
def test_tencent_v2_binds_reviewed_typed_volume_correction(symbol, sdk_volume, shares):
    client = FakeTencent()
    client.__version__ = "1.18.97"
    prefix = "sz" if symbol.startswith("000") else "sh"
    client.frames[prefix + symbol] = _frame(close=10, volume=sdk_volume, amount=1000000)
    batch = AkshareTencentDailyBarProvider(
        client, clock=lambda: AFTER_CLOSE
    ).fetch_daily_bars(_request(InstrumentKey(symbol, InstrumentType.STOCK)))
    assert batch.adapter_version == "karkinos.akshare_tencent.daily_bar.v5"
    assert batch.rows[0].volume == shares
    payload = json.loads(batch.raw_payload)
    # The response stays exactly as captured; only canonical normalization
    # applies the explicit, version-bound lot-to-share conversion.
    captured_frame = payload["calls"][0]["frame"]
    assert (
        captured_frame["data"][0][captured_frame["columns"].index("volume")]
        == sdk_volume
    )
    assert payload["calls"][0]["volume_scale_to_shares"] == (
        "100" if symbol.startswith("000") else "1"
    )


def test_tencent_rejects_unknown_sdk_before_guessing_zero_prefix_volume_units():
    client = FakeTencent()
    client.__version__ = "1.18.98"
    with pytest.raises(AkshareTencentDailyBarRequestError, match="unreviewed_sdk"):
        AkshareTencentDailyBarProvider(
            client, clock=lambda: AFTER_CLOSE
        ).fetch_daily_bars(_request(InstrumentKey("000001", InstrumentType.STOCK)))
    assert client.calls == []


def test_tencent_v1_materialization_replays_its_original_volume_after_v2_fix(tmp_path):
    from dataclasses import replace

    from data.market.ingestion import ingest_daily_bars
    from data.market.quality import RESEARCH_STRICT_DAILY
    from data.market.revision import validate_daily_bar_materialization
    from data.storage.objects import ContentAddressedObjectStore

    client = FakeTencent()
    client.__version__ = "1.18.97"
    client.frames["sz000001"] = _frame(close=10, volume=969082, amount=1000000)
    provider = AkshareTencentDailyBarProvider(client, clock=lambda: AFTER_CLOSE)
    request = _request(InstrumentKey("000001", InstrumentType.STOCK))
    corrected = provider.fetch_daily_bars(request)
    raw = json.loads(corrected.raw_payload)
    raw["schema"] = "akshare.tencent.stock_zh_a_hist_tx.dataframe.v1"
    raw.pop("sdk_version")
    raw["calls"][0].pop("volume_scale_to_shares")
    legacy = replace(
        corrected,
        adapter_version="karkinos.akshare_tencent.daily_bar.v1",
        payload_format=raw["schema"],
        raw_payload=json.dumps(raw, sort_keys=True, separators=(",", ":")).encode(),
        rows=(replace(corrected.rows[0], volume=Decimal("969082")),),
    )

    class LegacyProvider:
        descriptor = replace(
            provider.descriptor, adapter_version=legacy.adapter_version
        )

        def fetch_daily_bars(self, _request):
            return legacy

    objects = ContentAddressedObjectStore(tmp_path)
    result = ingest_daily_bars(
        LegacyProvider(),
        objects,
        request=request,
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version="fixture.original.v1",
        checked_at=AFTER_CLOSE,
    )
    before = objects.read_bytes(result.capture.raw_object_ref)
    original = validate_daily_bar_materialization(
        objects, revision=result.revision, materialization=result.materialization
    )
    assert original[0].volume == Decimal("969082")
    assert corrected.rows[0].volume == Decimal("96908200")
    assert objects.read_bytes(result.capture.raw_object_ref) == before


def test_tencent_empty_result_is_preserved_as_empty_batch() -> None:
    result = AkshareTencentDailyBarProvider(
        FakeTencent(), clock=lambda: AFTER_CLOSE
    ).fetch_daily_bars(_request(InstrumentKey("600000", InstrumentType.STOCK)))
    assert result.rows == ()
    assert result.record_count == 0


def test_tencent_rejects_session_before_close_without_provider_call() -> None:
    client = FakeTencent()
    provider = AkshareTencentDailyBarProvider(
        client,
        clock=lambda: datetime(2026, 9, 17, 6, 59, tzinfo=timezone.utc),
    )
    with pytest.raises(
        AkshareTencentDailyBarRequestError,
        match="akshare_tencent_daily_bar_session_not_closed",
    ):
        provider.fetch_daily_bars(
            _request(InstrumentKey("600000", InstrumentType.STOCK))
        )
    assert client.calls == []


def test_tencent_rejects_beijing_exchange_until_upstream_supports_it() -> None:
    with pytest.raises(
        AkshareTencentDailyBarRequestError,
        match="akshare_tencent_beijing_exchange_unsupported",
    ):
        AkshareTencentDailyBarProvider(
            FakeTencent(), clock=lambda: AFTER_CLOSE
        ).fetch_daily_bars(_request(InstrumentKey("920001", InstrumentType.STOCK)))


def test_tencent_rejects_nonfinite_values() -> None:
    client = FakeTencent()
    client.frames["sh600000"] = _frame(
        close=float("inf"),
        volume=45_671_100,
        amount=414_887_100,
    )

    with pytest.raises(
        AkshareTencentDailyBarResponseError,
        match="akshare_tencent_response_number_invalid:open",
    ):
        AkshareTencentDailyBarProvider(
            client, clock=lambda: AFTER_CLOSE
        ).fetch_daily_bars(_request(InstrumentKey("600000", InstrumentType.STOCK)))


def _amount_provider(amount, *, sdk="1.18.97"):
    client = FakeTencent()
    client.__version__ = sdk
    client.frames["sh600000"] = _frame(close=10, volume=10000, amount=amount)
    return AkshareTencentDailyBarProvider(client, clock=lambda: AFTER_CLOSE)


def _ingest_amount(provider, objects):
    return ingest_daily_bars(
        provider,
        objects,
        request=_request(InstrumentKey("600000", InstrumentType.STOCK)),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version="karkinos.market.normalize.v1",
        checked_at=AFTER_CLOSE,
    )


@pytest.mark.parametrize(
    "captured,expected",
    [
        (30047800.000000004, "30047800"),
        (29202199.999999996, "29202200"),
        (239516699.99999997, "239516700"),
    ],
)
def test_v4_retains_reviewed_sdk_one_ulp_amount_recovery_and_preserves_raw(
    tmp_path, captured, expected
):
    """Sanitized public-market values reproduce the actual SDK multiplication tail."""
    from data.market.capture import read_provider_capture, read_provider_raw_payload

    objects = ContentAddressedObjectStore(tmp_path / "objects")
    result = _ingest_amount(_amount_provider(captured), objects)
    reopened = ContentAddressedObjectStore(tmp_path / "objects")
    capture = read_provider_capture(reopened, result.capture.capture_ref)
    raw = json.loads(read_provider_raw_payload(reopened, capture))
    call = raw["calls"][0]
    assert (
        call["frame"]["data"][0][call["frame"]["columns"].index("amount")] == captured
    )
    assert call["amount_normalization"] == (
        "karkinos.akshare.1.18.97.tencent.amount_10000_one_binary_ulp.v1"
    )
    bars = validate_daily_bar_materialization(
        reopened, revision=result.revision, materialization=result.materialization
    )
    assert bars[0].amount == Decimal(expected)
    assert capture.adapter_version == "karkinos.akshare_tencent.daily_bar.v5"
    assert result.eligible_for_dataset_publication


@pytest.mark.parametrize(
    "amount,sdk,cause",
    [
        (30047800.000000004, "1.18.98", "daily_bar_amount_exceeds_storage_scale"),
        (30047800.000000026, "1.18.97", "daily_bar_amount_exceeds_storage_scale"),
        (
            Decimal("30047800.000000004"),
            "1.18.97",
            "daily_bar_amount_exceeds_storage_scale",
        ),
        (-5e-324, "1.18.97", "daily_bar_amount_must_be_non_negative"),
    ],
)
def test_v4_does_not_round_unreviewed_or_non_binary_amount_precision_loss(
    tmp_path, amount, sdk, cause
):
    objects = ContentAddressedObjectStore(tmp_path / "objects")
    with pytest.raises(DailyBarIngestionCapturedFailure) as failure:
        _ingest_amount(_amount_provider(amount, sdk=sdk), objects)
    assert isinstance(failure.value.__cause__, ValueError)
    assert str(failure.value.__cause__) == cause
    assert objects.verify(failure.value.capture.raw_object_ref)


@pytest.mark.parametrize(
    "version,expected",
    [
        ("v1", "239516699.99999997"),
        ("v2", "239516699.99999997"),
        ("v3", "239516700"),
    ],
)
def test_legacy_capture_reopens_its_original_amount_normalization(
    tmp_path, version, expected
):
    from data.market.capture import read_provider_capture, read_provider_raw_payload
    from data.providers.tencent import _rows_from_frame

    amount = 239516699.99999997
    current = _amount_provider(amount)
    frame = current._client.frames["sh600000"]
    legacy_version = "karkinos.akshare_tencent.daily_bar." + version
    legacy_format = "akshare.tencent.stock_zh_a_hist_tx.dataframe." + version

    class LegacyProvider:
        descriptor = replace(current.descriptor, adapter_version=legacy_version)

        def fetch_daily_bars(self, request):
            batch = current.fetch_daily_bars(request)
            raw = json.loads(batch.raw_payload)
            raw["schema"] = legacy_format
            for call in raw["calls"]:
                call.pop("volume_normalization")
                if version != "v3":
                    call.pop("amount_normalization")
            rows = _rows_from_frame(
                frame,
                instrument=request.instruments[0],
                expected_session=DAY,
                sdk_version="1.18.97",
                adapter_version=legacy_version,
            )
            return replace(
                batch,
                adapter_version=legacy_version,
                payload_format=legacy_format,
                rows=tuple(rows),
                raw_payload=json.dumps(raw, sort_keys=True).encode(),
            )

    objects = ContentAddressedObjectStore(tmp_path / "objects")
    result = _ingest_amount(LegacyProvider(), objects)
    reopened = ContentAddressedObjectStore(tmp_path / "objects")
    capture = read_provider_capture(reopened, result.capture.capture_ref)
    raw = json.loads(read_provider_raw_payload(reopened, capture))
    assert raw["schema"] == legacy_format and capture.adapter_version == legacy_version
    bars = validate_daily_bar_materialization(
        reopened, revision=result.revision, materialization=result.materialization
    )
    assert bars[0].amount == Decimal(expected)
    assert result.eligible_for_dataset_publication


def _volume_provider(volume, instrument, *, sdk="1.18.97"):
    client = FakeTencent()
    client.__version__ = sdk
    prefix = "sh" if instrument.symbol.startswith(("6", "5")) else "sz"
    client.frames[prefix + instrument.symbol] = _frame(
        close=10, volume=volume, amount=1000000
    )
    return AkshareTencentDailyBarProvider(client, clock=lambda: AFTER_CLOSE)


@pytest.mark.parametrize(
    "symbol,kind,captured,expected",
    [
        ("002244", InstrumentType.STOCK, 33359009.000000004, "33359009"),
        ("600000", InstrumentType.STOCK, 33359008.999999996, "33359009"),
        ("300001", InstrumentType.STOCK, 67108863.99999999, "67108864"),
        ("689001", InstrumentType.STOCK, 33359009.000000004, "333590.09"),
        ("510300", InstrumentType.ETF, 33359009.000000004, "33359009"),
        ("159915", InstrumentType.ETF, 33359009.000000004, "33359009"),
    ],
)
def test_v5_recovers_reviewed_sdk_one_ulp_volume_and_preserves_raw(
    tmp_path, symbol, kind, captured, expected
):
    from data.market.capture import read_provider_capture, read_provider_raw_payload

    instrument = InstrumentKey(symbol, kind)
    objects = ContentAddressedObjectStore(tmp_path / "objects")
    result = ingest_daily_bars(
        _volume_provider(captured, instrument),
        objects,
        request=_request(instrument),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version="karkinos.market.normalize.v1",
        checked_at=AFTER_CLOSE,
    )
    reopened = ContentAddressedObjectStore(tmp_path / "objects")
    capture = read_provider_capture(reopened, result.capture.capture_ref)
    raw = json.loads(read_provider_raw_payload(reopened, capture))
    call = raw["calls"][0]
    assert (
        call["frame"]["data"][0][call["frame"]["columns"].index("volume")] == captured
    )
    assert call["volume_normalization"] == (
        "karkinos.akshare.1.18.97.tencent.volume_100_one_binary_ulp.v1"
    )
    assert call["volume_scale_to_shares"] == (
        "0.01" if symbol.startswith("689") else "1"
    )
    assert capture.adapter_version == "karkinos.akshare_tencent.daily_bar.v5"
    assert raw["schema"] == "akshare.tencent.stock_zh_a_hist_tx.dataframe.v5"
    bars = validate_daily_bar_materialization(
        reopened, revision=result.revision, materialization=result.materialization
    )
    assert bars[0].volume == Decimal(expected)
    assert result.eligible_for_dataset_publication


@pytest.mark.parametrize(
    "volume,sdk,symbol,cause",
    [
        (33359009.000000004, "1.18.98", "600000", "exceeds_storage_scale"),
        (
            math.nextafter(33359009.000000004, math.inf),
            "1.18.97",
            "600000",
            "exceeds_storage_scale",
        ),
        (
            Decimal("33359009.000000004"),
            "1.18.97",
            "600000",
            "exceeds_storage_scale",
        ),
        ("33359009.000000004", "1.18.97", "600000", "exceeds_storage_scale"),
        (33359009.000000004, "1.18.97", "688001", "exceeds_storage_scale"),
        (-5e-324, "1.18.97", "600000", "must_be_non_negative"),
    ],
)
def test_v4_volume_recovery_keeps_sdk_prefix_and_storage_boundaries(
    tmp_path, volume, sdk, symbol, cause
):
    instrument = InstrumentKey(symbol, InstrumentType.STOCK)
    objects = ContentAddressedObjectStore(tmp_path / "objects")
    with pytest.raises(DailyBarIngestionCapturedFailure) as failure:
        ingest_daily_bars(
            _volume_provider(volume, instrument, sdk=sdk),
            objects,
            request=_request(instrument),
            quality_policy=RESEARCH_STRICT_DAILY,
            normalizer_version="karkinos.market.normalize.v1",
            checked_at=AFTER_CLOSE,
        )
    assert isinstance(failure.value.__cause__, ValueError)
    assert str(failure.value.__cause__) == "daily_bar_volume_" + cause
    assert objects.verify(failure.value.capture.raw_object_ref)


@pytest.mark.parametrize("volume", [100.25, math.nextafter(float(2**51), math.inf)])
def test_v4_does_not_recover_fractional_or_ambiguous_integer_volume(volume):
    instrument = InstrumentKey("600000", InstrumentType.STOCK)
    batch = _volume_provider(volume, instrument).fetch_daily_bars(_request(instrument))
    assert batch.rows[0].volume == Decimal(str(volume))


@pytest.mark.parametrize("symbol,scale", [("000001", 100), ("688001", 1)])
def test_v4_preserves_volume_from_sdk_branches_without_binary_multiplication(
    symbol, scale
):
    instrument = InstrumentKey(symbol, InstrumentType.STOCK)
    volume = 33359009.000000004
    batch = _volume_provider(volume, instrument).fetch_daily_bars(_request(instrument))
    assert batch.rows[0].volume == Decimal(str(volume)) * scale
    call = json.loads(batch.raw_payload)["calls"][0]
    assert call["volume_scale_to_shares"] == str(scale)
    assert call["volume_normalization"] is None


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
def test_legacy_volume_capture_replays_original_tail_without_v4_recalculation(
    tmp_path, version
):
    from data.market.capture import read_provider_raw_payload
    from data.providers.tencent import _rows_from_frame

    instrument = InstrumentKey("600000", InstrumentType.STOCK)
    volume = 67108863.99999999
    current = _volume_provider(volume, instrument)
    frame = current._client.frames["sh600000"]
    legacy_version = "karkinos.akshare_tencent.daily_bar." + version
    legacy_format = "akshare.tencent.stock_zh_a_hist_tx.dataframe." + version

    class LegacyProvider:
        descriptor = replace(current.descriptor, adapter_version=legacy_version)

        def fetch_daily_bars(self, request):
            batch = current.fetch_daily_bars(request)
            assert batch.rows[0].volume == Decimal("67108864")
            raw = json.loads(batch.raw_payload)
            raw["schema"] = legacy_format
            for call in raw["calls"]:
                call.pop("volume_normalization")
                if version != "v3":
                    call.pop("amount_normalization")
            rows = _rows_from_frame(
                frame,
                instrument=instrument,
                expected_session=DAY,
                sdk_version="1.18.97",
                adapter_version=legacy_version,
            )
            return replace(
                batch,
                adapter_version=legacy_version,
                payload_format=legacy_format,
                rows=tuple(rows),
                raw_payload=json.dumps(raw, sort_keys=True).encode(),
            )

    objects = ContentAddressedObjectStore(tmp_path / "objects")
    result = _ingest_amount(LegacyProvider(), objects)
    reopened = ContentAddressedObjectStore(tmp_path / "objects")
    raw_before = read_provider_raw_payload(reopened, result.capture)
    bars = validate_daily_bar_materialization(
        reopened, revision=result.revision, materialization=result.materialization
    )
    assert bars[0].volume == Decimal("67108863.99999999")
    assert read_provider_raw_payload(reopened, result.capture) == raw_before
    assert result.capture.adapter_version == legacy_version
    assert result.eligible_for_dataset_publication
