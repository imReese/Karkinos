from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarProvider, DailyBarRequest
from data.market.ingestion import ingest_daily_bars
from data.market.quality import RESEARCH_STRICT_DAILY
from data.market.revision import validate_daily_bar_materialization
from data.providers.tushare import (
    TUSHARE_DAILY_BAR_ADAPTER_VERSION,
    TUSHARE_DAILY_BAR_DESCRIPTOR,
    TUSHARE_MARKET_DAILY_PAYLOAD_FORMAT,
    TushareDailyBarProvider,
    TushareDailyBarRequestError,
    TushareDailyBarResponseError,
)
from data.storage.objects import ContentAddressedObjectStore

DAY = date(2026, 9, 15)
AFTER_CLOSE = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)


class FakePro:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def daily(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("daily", kwargs))
        return _frame("20260915", close=10.48, ts_code=str(kwargs["ts_code"]))

    def fund_daily(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("fund_daily", kwargs))
        return _frame("20260915", close=4.017, ts_code=str(kwargs["ts_code"]))


def _frame(
    trade_date: str, *, close: float, ts_code: str = "600000.SH"
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": [ts_code],
            "trade_date": [trade_date],
            "open": [round(close - 0.1, 2)],
            "high": [round(close + 0.1, 2)],
            "low": [round(close - 0.2, 2)],
            "close": [close],
            "vol": [1234.5],
            "amount": [6789.25],
        }
    )


def _request(*items: InstrumentKey) -> DailyBarRequest:
    return DailyBarRequest(tuple(items), DAY, DAY)


def test_tushare_daily_provider_satisfies_canonical_protocol() -> None:
    provider = TushareDailyBarProvider(FakePro(), clock=lambda: AFTER_CLOSE)
    assert isinstance(provider, DailyBarProvider)
    assert provider.descriptor == TUSHARE_DAILY_BAR_DESCRIPTOR


def test_tushare_daily_provider_maps_stock_and_etf_endpoints_and_units() -> None:
    client = FakePro()
    provider = TushareDailyBarProvider(client, clock=lambda: AFTER_CLOSE)
    result = provider.fetch_daily_bars(
        _request(
            InstrumentKey("600000", InstrumentType.STOCK),
            InstrumentKey("510300", InstrumentType.ETF),
        )
    )

    assert [item[0] for item in client.calls] == ["fund_daily", "daily"]
    assert client.calls[0][1]["ts_code"] == "510300.SH"
    assert client.calls[1][1]["ts_code"] == "600000.SH"
    assert [row.instrument for row in result.rows] == [
        InstrumentKey("510300", InstrumentType.ETF),
        InstrumentKey("600000", InstrumentType.STOCK),
    ]
    for row in result.rows:
        assert row.volume == Decimal("123450.0")
        assert row.amount == Decimal("6789250.00")
        assert row.available_at is None
        assert row.event_time == datetime(2026, 9, 15, 7, 0, tzinfo=timezone.utc)


def test_tushare_daily_provider_preserves_stable_sdk_response_evidence() -> None:
    provider = TushareDailyBarProvider(FakePro(), clock=lambda: AFTER_CLOSE)
    result = provider.fetch_daily_bars(
        _request(InstrumentKey("000001", InstrumentType.STOCK))
    )
    payload = json.loads(result.raw_payload)
    assert payload["schema"] == "tushare.pro.daily_bar.dataframe.v1"
    assert payload["calls"][0]["endpoint"] == "daily"
    assert payload["calls"][0]["ts_code"] == "000001.SZ"
    assert payload["calls"][0]["frame"]["columns"] == [
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
    ]


def test_tushare_daily_provider_keeps_empty_provider_result_as_empty_batch() -> None:
    class EmptyPro(FakePro):
        def daily(self, **kwargs: object) -> pd.DataFrame:
            self.calls.append(("daily", kwargs))
            return pd.DataFrame()

    result = TushareDailyBarProvider(
        EmptyPro(), clock=lambda: AFTER_CLOSE
    ).fetch_daily_bars(_request(InstrumentKey("600000", InstrumentType.STOCK)))
    assert result.rows == ()
    assert result.record_count == 0


def test_tushare_daily_provider_rejects_session_before_close() -> None:
    provider = TushareDailyBarProvider(
        FakePro(),
        clock=lambda: datetime(2026, 9, 15, 6, 59, tzinfo=timezone.utc),
    )
    with pytest.raises(
        TushareDailyBarRequestError, match="tushare_daily_bar_session_not_closed"
    ):
        provider.fetch_daily_bars(
            _request(InstrumentKey("600000", InstrumentType.STOCK))
        )


def test_tushare_daily_provider_rejects_unreviewed_instrument_type() -> None:
    provider = TushareDailyBarProvider(FakePro(), clock=lambda: AFTER_CLOSE)
    with pytest.raises(
        TushareDailyBarRequestError, match="tushare_instrument_type_unsupported"
    ):
        provider.fetch_daily_bars(
            _request(InstrumentKey("Au9999", InstrumentType.GOLD))
        )


def test_tushare_daily_provider_rejects_nonfinite_values() -> None:
    class BadPro(FakePro):
        def daily(self, **kwargs: object) -> pd.DataFrame:
            frame = _frame("20260915", close=10.48)
            frame.loc[0, "close"] = float("inf")
            return frame

    provider = TushareDailyBarProvider(BadPro(), clock=lambda: AFTER_CLOSE)
    with pytest.raises(
        TushareDailyBarResponseError,
        match="tushare_response_number_invalid:close",
    ):
        provider.fetch_daily_bars(
            _request(InstrumentKey("600000", InstrumentType.STOCK))
        )


@pytest.mark.parametrize("code", ["600001.SH", "600000.SZ", "600000.SH ", None, 600000])
def test_tushare_daily_rejects_returned_code_instead_of_relabeling(code):
    client = MarketPro(_frame("20260915", close=10.48).assign(ts_code=code))
    with pytest.raises(
        TushareDailyBarResponseError, match="tushare_response_code_mismatch"
    ):
        TushareDailyBarProvider(client, clock=lambda: AFTER_CLOSE).fetch_daily_bars(
            _request(InstrumentKey("600000", InstrumentType.STOCK))
        )
    assert len(client.calls) == 1


def test_tushare_daily_requires_returned_code_column():
    client = MarketPro(_frame("20260915", close=10.48).drop(columns="ts_code"))
    with pytest.raises(
        TushareDailyBarResponseError,
        match="tushare_response_columns_missing:daily:ts_code",
    ):
        TushareDailyBarProvider(client, clock=lambda: AFTER_CLOSE).fetch_daily_bars(
            _request(InstrumentKey("600000", InstrumentType.STOCK))
        )


@pytest.mark.parametrize("count", [6000, 6001])
@pytest.mark.parametrize("market_batch", [False, True])
def test_daily_row_cap_rejects_possible_truncation_before_partial_acceptance(
    count, market_batch
):
    frame = pd.concat([_frame("20260915", close=10.48)] * count, ignore_index=True)
    client = MarketPro(frame)
    instruments = (InstrumentKey("600000", InstrumentType.STOCK),)
    if market_batch:
        instruments += (InstrumentKey("600001", InstrumentType.STOCK),)
    with pytest.raises(
        TushareDailyBarResponseError, match="tushare_response_truncation_possible:daily"
    ):
        TushareDailyBarProvider(client, clock=lambda: AFTER_CLOSE).fetch_daily_bars(
            _request(*instruments)
        )
    assert len(client.calls) == 1


def test_daily_preserves_optional_after_hours_fields_without_inventing_a_total():
    frame = _frame("20260915", close=10.48).assign(ah_vol=200, ah_amount=321.5)
    client = MarketPro(frame)
    batch = TushareDailyBarProvider(client, clock=lambda: AFTER_CLOSE).fetch_daily_bars(
        _request(InstrumentKey("600000", InstrumentType.STOCK))
    )
    assert batch.rows[0].volume == Decimal("123450.0")
    assert batch.rows[0].amount == Decimal("6789250.00")
    evidence = json.loads(batch.raw_payload)["calls"][0]["frame"]
    assert evidence["columns"] == frame.columns.tolist()
    assert evidence["data"] == frame.values.tolist()


def _stock_batch():
    return tuple(
        InstrumentKey(f"{600000 + index}", InstrumentType.STOCK) for index in range(100)
    )


def _market_frame(keys):
    return pd.concat(
        [
            _frame("20260915", close=10.48).assign(ts_code=f"{key.symbol}.SH")
            for key in keys
        ],
        ignore_index=True,
    )


class MarketPro:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def daily(self, **kwargs):
        self.calls.append(kwargs)
        return self.frame


def test_stock_daily_batch_uses_one_market_call_and_preserves_complete_raw():
    keys = _stock_batch()
    frame = pd.concat(
        [_market_frame(keys), _frame("20260915", close=15).assign(ts_code="000001.SZ")],
        ignore_index=True,
    )
    client = MarketPro(frame)
    completed = AFTER_CLOSE + timedelta(seconds=2)
    ticks = iter((AFTER_CLOSE, completed))
    result = TushareDailyBarProvider(
        client, clock=lambda: next(ticks)
    ).fetch_daily_bars(_request(*keys))
    assert client.calls == [{"trade_date": "20260915"}]
    assert result.adapter_version == TUSHARE_DAILY_BAR_ADAPTER_VERSION
    assert result.payload_format == TUSHARE_MARKET_DAILY_PAYLOAD_FORMAT
    assert result.started_at == AFTER_CLOSE and result.completed_at == completed
    assert tuple(row.instrument for row in result.rows) == keys
    assert all(
        row.volume == Decimal("123450.0")
        and row.amount == Decimal("6789250.00")
        and row.available_at is None
        for row in result.rows
    )
    payload = json.loads(result.raw_payload)
    assert payload["schema"] == TUSHARE_MARKET_DAILY_PAYLOAD_FORMAT
    assert len(payload["calls"]) == 1
    call = payload["calls"][0]
    assert call["request"] == {"trade_date": "20260915"}
    assert call["frame"]["data"] == frame.values.tolist()
    assert len(call["frame"]["data"]) == 101


@pytest.mark.parametrize("wrong_exchange", [False, True])
def test_market_batch_missing_requested_member_remains_quality_blocked(
    tmp_path, wrong_exchange
):
    keys = _stock_batch()
    frame = _market_frame(keys[:-1])
    if wrong_exchange:
        frame = pd.concat(
            [
                frame,
                _frame("20260915", close=10.48).assign(ts_code=f"{keys[-1].symbol}.SZ"),
            ],
            ignore_index=True,
        )
    client = MarketPro(frame)
    objects = ContentAddressedObjectStore(tmp_path / "objects")
    result = ingest_daily_bars(
        TushareDailyBarProvider(client, clock=lambda: AFTER_CLOSE),
        objects,
        request=_request(*keys),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version="karkinos.market.normalize.v1",
        checked_at=AFTER_CLOSE,
    )
    assert client.calls == [{"trade_date": "20260915"}]
    assert result.revision.row_count == 99
    assert result.quality.blocks_publication
    assert not result.eligible_for_dataset_publication
    assert objects.verify(result.capture.raw_object_ref)


@pytest.mark.parametrize("failure", ["duplicate", "wrong_date"])
def test_market_batch_rejects_ambiguous_or_wrong_session_requested_rows(failure):
    keys = _stock_batch()
    frame = _market_frame(keys)
    if failure == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
    else:
        frame.loc[0, "trade_date"] = "20260914"
    client = MarketPro(frame)
    with pytest.raises(TushareDailyBarResponseError, match="tushare_response_"):
        TushareDailyBarProvider(client, clock=lambda: AFTER_CLOSE).fetch_daily_bars(
            _request(*keys)
        )
    assert len(client.calls) == 1


def test_legacy_v1_single_stock_capture_and_materialization_still_reopen(tmp_path):
    from data.market.capture import read_provider_capture, read_provider_raw_payload

    class LegacyV1Provider:
        descriptor = replace(
            TUSHARE_DAILY_BAR_DESCRIPTOR,
            adapter_version="karkinos.tushare.daily_bar.v1",
        )

        def fetch_daily_bars(self, request):
            batch = TushareDailyBarProvider(
                FakePro(), clock=lambda: AFTER_CLOSE
            ).fetch_daily_bars(request)
            return replace(batch, adapter_version=self.descriptor.adapter_version)

    objects = ContentAddressedObjectStore(tmp_path / "objects")
    result = ingest_daily_bars(
        LegacyV1Provider(),
        objects,
        request=_request(InstrumentKey("600000", InstrumentType.STOCK)),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version="karkinos.market.normalize.v1",
        checked_at=AFTER_CLOSE,
    )
    reopened = ContentAddressedObjectStore(tmp_path / "objects")
    capture = read_provider_capture(reopened, result.capture.capture_ref)
    assert capture.adapter_version == "karkinos.tushare.daily_bar.v1"
    assert capture.payload_format == "tushare.pro.daily_bar.dataframe.v1"
    raw = json.loads(read_provider_raw_payload(reopened, capture))
    assert raw["calls"][0]["ts_code"] == "600000.SH"
    bars = validate_daily_bar_materialization(
        reopened, revision=result.revision, materialization=result.materialization
    )
    assert len(bars) == 1 and bars[0].close == Decimal("10.48")
    assert result.eligible_for_dataset_publication


def test_market_batch_passes_strict_dual_source_adapter_identity_and_reopens(tmp_path):
    from data.market.cross_source import ingest_cross_source_daily_bars
    from data.market.verification_evidence import read_market_verification_evidence
    from data.providers.baostock import BaoStockDailyBarProvider
    from tests.data.providers.test_baostock_daily import FakeBaoStock, FakeResult

    keys = _stock_batch()
    client = MarketPro(_market_frame(keys))
    bao = FakeBaoStock()
    for key in keys:
        code = "sh." + key.symbol
        bao.results[code] = FakeResult(
            [
                [
                    DAY.isoformat(),
                    code,
                    "10.38",
                    "10.58",
                    "10.28",
                    "10.48",
                    "123450",
                    "6789250",
                    "3",
                    "1",
                ]
            ]
        )
    objects = ContentAddressedObjectStore(tmp_path / "objects")
    result = ingest_cross_source_daily_bars(
        BaoStockDailyBarProvider(bao, clock=lambda: AFTER_CLOSE),
        TushareDailyBarProvider(client, clock=lambda: AFTER_CLOSE),
        objects,
        request=_request(*keys),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version="karkinos.market.normalize.v1",
        checked_at=AFTER_CLOSE,
    )
    assert len(client.calls) == 1
    assert result.eligible_for_verified_dataset
    reopened = ContentAddressedObjectStore(tmp_path / "objects")
    verification = read_market_verification_evidence(reopened, result.verification.ref)
    assert verification.comparison_adapter_version == "karkinos.tushare.daily_bar.v2"
    assert (
        len(
            validate_daily_bar_materialization(
                reopened,
                revision=result.comparison.revision,
                materialization=result.comparison.materialization,
            )
        )
        == 100
    )
