"""Market Data Provider 边界契约测试。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import (
    DailyBarProvider,
    DailyBarRequest,
    ProviderDailyBarBatch,
    ProviderDailyBarRow,
)

_BASE_TIME = datetime(
    2026,
    9,
    15,
    7,
    0,
    tzinfo=timezone.utc,
)


def _instrument(
    symbol: str = "600000",
    instrument_type: InstrumentType = InstrumentType.STOCK,
) -> InstrumentKey:
    return InstrumentKey(
        symbol=symbol,
        instrument_type=instrument_type,
    )


def _row(
    *,
    symbol: str = "600000",
    instrument_type: InstrumentType = InstrumentType.STOCK,
    available_at: datetime | None = _BASE_TIME,
) -> ProviderDailyBarRow:
    return ProviderDailyBarRow(
        instrument=_instrument(
            symbol,
            instrument_type,
        ),
        session_date="2026-09-15",
        event_time=_BASE_TIME - timedelta(minutes=1),
        available_at=available_at,
        open_value="10.31",
        high_value="10.52",
        low_value="10.20",
        close_value="10.48",
        volume="123456",
        amount="1283912.42",
        suspended=False,
    )


def _batch(
    *,
    rows: tuple[ProviderDailyBarRow, ...] | None = None,
    started_at: datetime = _BASE_TIME,
    completed_at: datetime | None = None,
) -> ProviderDailyBarBatch:
    return ProviderDailyBarBatch(
        provider="tdx",
        adapter_version="karkinos.tdx.v1",
        payload_format="tdx.daily_bars.v1",
        started_at=started_at,
        completed_at=completed_at or started_at + timedelta(milliseconds=842),
        raw_payload=b"provider-response",
        rows=rows if rows is not None else (_row(),),
    )


def test_daily_bar_request_canonicalizes_instrument_order() -> None:
    request = DailyBarRequest(
        instruments=(
            _instrument("600000"),
            _instrument("000001"),
            _instrument(
                "510300",
                InstrumentType.ETF,
            ),
        ),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 15),
    )

    assert [instrument.storage_tuple() for instrument in request.instruments] == [
        ("510300", "etf"),
        ("000001", "stock"),
        ("600000", "stock"),
    ]


def test_daily_bar_request_identity_is_independent_of_input_order() -> None:
    first = DailyBarRequest(
        instruments=(
            _instrument("600000"),
            _instrument("000001"),
        ),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 15),
    )

    second = DailyBarRequest(
        instruments=(
            _instrument("000001"),
            _instrument("600000"),
        ),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 15),
    )

    assert first == second
    assert first.to_capture_request() == second.to_capture_request()


def test_daily_bar_request_capture_payload_is_provider_neutral() -> None:
    request = DailyBarRequest(
        instruments=(_instrument("600000"),),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 15),
    )

    assert request.to_capture_request() == {
        "kind": "daily_bars",
        "frequency": "1d",
        "start_date": "2026-09-01",
        "end_date": "2026-09-15",
        "instruments": [
            {
                "symbol": "600000",
                "instrument_type": "stock",
            }
        ],
    }


def test_daily_bar_request_rejects_empty_instruments() -> None:
    with pytest.raises(
        ValueError,
        match="daily_bar_request_instruments_empty",
    ):
        DailyBarRequest(
            instruments=(),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 15),
        )


def test_daily_bar_request_rejects_duplicate_instrument() -> None:
    instrument = _instrument("600000")

    with pytest.raises(
        ValueError,
        match="daily_bar_request_duplicate_instrument",
    ):
        DailyBarRequest(
            instruments=(
                instrument,
                instrument,
            ),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 15),
        )


def test_same_symbol_with_different_instrument_type_is_not_duplicate() -> None:
    request = DailyBarRequest(
        instruments=(
            _instrument(
                "510300",
                InstrumentType.STOCK,
            ),
            _instrument(
                "510300",
                InstrumentType.ETF,
            ),
        ),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 15),
    )

    assert len(request.instruments) == 2


def test_daily_bar_request_rejects_end_before_start() -> None:
    with pytest.raises(
        ValueError,
        match="daily_bar_request_end_before_start",
    ):
        DailyBarRequest(
            instruments=(_instrument(),),
            start_date=date(2026, 9, 15),
            end_date=date(2026, 9, 1),
        )


def test_daily_bar_request_rejects_datetime_as_date() -> None:
    with pytest.raises(
        TypeError,
        match="daily_bar_request_start_date_must_be_date",
    ):
        DailyBarRequest(
            instruments=(_instrument(),),
            start_date=datetime(
                2026,
                9,
                1,
                tzinfo=timezone.utc,
            ),
            end_date=date(2026, 9, 15),
        )


def test_provider_daily_bar_row_accepts_missing_availability() -> None:
    row = _row(
        available_at=None,
    )

    assert row.available_at is None


def test_provider_daily_bar_row_keeps_provider_numeric_types() -> None:
    row = ProviderDailyBarRow(
        instrument=_instrument(),
        session_date="2026-09-15",
        event_time=_BASE_TIME,
        available_at=None,
        open_value=10.31,
        high_value="10.52",
        low_value=Decimal("10.20"),
        close_value=10,
        volume="123456",
        amount=1283912.42,
        suspended=False,
    )

    # Provider boundary 只负责表达 Adapter 已解释出的字段，
    # 这些数值会在 normalize.py 中统一转换成 Decimal。
    assert row.open_value == 10.31
    assert row.high_value == "10.52"
    assert row.low_value == Decimal("10.20")
    assert row.close_value == 10


def test_provider_daily_bar_row_rejects_naive_event_time() -> None:
    with pytest.raises(
        ValueError,
        match=("provider_daily_bar_event_time" "_must_be_timezone_aware"),
    ):
        ProviderDailyBarRow(
            instrument=_instrument(),
            session_date="2026-09-15",
            event_time=datetime(
                2026,
                9,
                15,
                15,
                0,
            ),
            available_at=None,
            open_value="10.31",
            high_value="10.52",
            low_value="10.20",
            close_value="10.48",
            volume="123456",
            amount="1283912.42",
            suspended=False,
        )


def test_provider_daily_bar_row_rejects_naive_availability_time() -> None:
    with pytest.raises(
        ValueError,
        match=("provider_daily_bar_available_at" "_must_be_timezone_aware"),
    ):
        ProviderDailyBarRow(
            instrument=_instrument(),
            session_date="2026-09-15",
            event_time=_BASE_TIME,
            available_at=datetime(
                2026,
                9,
                15,
                15,
                1,
            ),
            open_value="10.31",
            high_value="10.52",
            low_value="10.20",
            close_value="10.48",
            volume="123456",
            amount="1283912.42",
            suspended=False,
        )


def test_provider_daily_bar_batch_normalizes_times_to_utc() -> None:
    shanghai = timezone(timedelta(hours=8))

    batch = _batch(
        started_at=datetime(
            2026,
            9,
            15,
            15,
            0,
            tzinfo=shanghai,
        ),
        completed_at=datetime(
            2026,
            9,
            15,
            15,
            0,
            1,
            tzinfo=shanghai,
        ),
    )

    assert batch.started_at == datetime(
        2026,
        9,
        15,
        7,
        0,
        tzinfo=timezone.utc,
    )

    assert batch.completed_at == datetime(
        2026,
        9,
        15,
        7,
        0,
        1,
        tzinfo=timezone.utc,
    )


def test_provider_daily_bar_batch_exposes_record_count() -> None:
    batch = _batch(
        rows=(
            _row(symbol="600000"),
            _row(symbol="000001"),
        )
    )

    assert batch.record_count == 2


def test_provider_daily_bar_batch_exposes_elapsed_ms() -> None:
    batch = _batch(
        started_at=_BASE_TIME,
        completed_at=(_BASE_TIME + timedelta(milliseconds=842)),
    )

    assert batch.elapsed_ms == 842


def test_provider_daily_bar_batch_accepts_empty_result() -> None:
    batch = _batch(
        rows=(),
    )

    assert batch.record_count == 0
    assert batch.rows == ()


def test_provider_daily_bar_batch_rejects_completion_before_start() -> None:
    with pytest.raises(
        ValueError,
        match="provider_daily_bar_completed_before_started",
    ):
        _batch(
            started_at=_BASE_TIME,
            completed_at=_BASE_TIME - timedelta(milliseconds=1),
        )


def test_provider_daily_bar_batch_requires_raw_bytes() -> None:
    with pytest.raises(
        TypeError,
        match="provider_daily_bar_raw_payload_must_be_bytes",
    ):
        ProviderDailyBarBatch(
            provider="tdx",
            adapter_version="karkinos.tdx.v1",
            payload_format="tdx.daily_bars.v1",
            started_at=_BASE_TIME,
            completed_at=_BASE_TIME + timedelta(seconds=1),
            raw_payload="provider-response",
            rows=(),
        )


def test_provider_daily_bar_batch_requires_tuple_rows() -> None:
    with pytest.raises(
        TypeError,
        match="provider_daily_bar_rows_must_be_tuple",
    ):
        ProviderDailyBarBatch(
            provider="tdx",
            adapter_version="karkinos.tdx.v1",
            payload_format="tdx.daily_bars.v1",
            started_at=_BASE_TIME,
            completed_at=_BASE_TIME + timedelta(seconds=1),
            raw_payload=b"provider-response",
            rows=[],
        )


def test_provider_daily_bar_batch_trims_text_metadata() -> None:
    batch = ProviderDailyBarBatch(
        provider="  tdx  ",
        adapter_version="  karkinos.tdx.v1  ",
        payload_format="  tdx.daily_bars.v1  ",
        started_at=_BASE_TIME,
        completed_at=_BASE_TIME + timedelta(seconds=1),
        raw_payload=b"provider-response",
        rows=(),
    )

    assert batch.provider == "tdx"
    assert batch.adapter_version == "karkinos.tdx.v1"
    assert batch.payload_format == "tdx.daily_bars.v1"


def test_daily_bar_provider_protocol_accepts_matching_adapter() -> None:
    class FakeProvider:
        def fetch_daily_bars(
            self,
            request: DailyBarRequest,
        ) -> ProviderDailyBarBatch:
            return _batch()

    provider = FakeProvider()

    assert isinstance(
        provider,
        DailyBarProvider,
    )


def test_daily_bar_provider_protocol_rejects_missing_capability() -> None:
    class NotAProvider:
        pass

    assert not isinstance(
        NotAProvider(),
        DailyBarProvider,
    )
