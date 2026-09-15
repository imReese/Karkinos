"""TDX DailyBarProvider 测试。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarRequest
from data.providers.tdx import (
    TDX_DAILY_BAR_ADAPTER_VERSION,
    TDX_DAILY_BAR_PAYLOAD_FORMAT,
    TDX_PROVIDER_NAME,
    TdxDailyBarProvider,
    TdxProviderRequestError,
    TdxProviderResponseError,
)

_SESSION_DATE = date(2026, 9, 15)


def _instrument(
    symbol: str,
    instrument_type: InstrumentType = InstrumentType.STOCK,
) -> InstrumentKey:
    return InstrumentKey(
        symbol=symbol,
        instrument_type=instrument_type,
    )


def _request(
    *instruments: InstrumentKey,
) -> DailyBarRequest:
    return DailyBarRequest(
        instruments=tuple(instruments),
        start_date=_SESSION_DATE,
        end_date=_SESSION_DATE,
    )


def _clock_after_close() -> datetime:
    return datetime(
        2026,
        9,
        15,
        8,
        0,
        tzinfo=timezone.utc,
    )


def _clock_before_close() -> datetime:
    return datetime(
        2026,
        9,
        15,
        6,
        59,
        tzinfo=timezone.utc,
    )


def _response_dates_by_rows():
    index = [
        pd.Timestamp("2026-09-15"),
    ]

    columns = [
        "000001.SZ",
        "600000.SH",
    ]

    return {
        "Open": pd.DataFrame(
            [[12.10, 10.31]],
            index=index,
            columns=columns,
        ),
        "High": pd.DataFrame(
            [[12.50, 10.52]],
            index=index,
            columns=columns,
        ),
        "Low": pd.DataFrame(
            [[12.00, 10.20]],
            index=index,
            columns=columns,
        ),
        "Close": pd.DataFrame(
            [[12.34, 10.48]],
            index=index,
            columns=columns,
        ),
        "Volume": pd.DataFrame(
            [[100000, 123456]],
            index=index,
            columns=columns,
        ),
        "Amount": pd.DataFrame(
            [[123.4, 128.391242]],
            index=index,
            columns=columns,
        ),
    }


def _response_codes_by_rows():
    index = [
        "000001.SZ",
        "600000.SH",
    ]

    columns = [
        pd.Timestamp("2026-09-15"),
    ]

    return {
        "Open": pd.DataFrame(
            [[12.10], [10.31]],
            index=index,
            columns=columns,
        ),
        "High": pd.DataFrame(
            [[12.50], [10.52]],
            index=index,
            columns=columns,
        ),
        "Low": pd.DataFrame(
            [[12.00], [10.20]],
            index=index,
            columns=columns,
        ),
        "Close": pd.DataFrame(
            [[12.34], [10.48]],
            index=index,
            columns=columns,
        ),
        "Volume": pd.DataFrame(
            [[100000], [123456]],
            index=index,
            columns=columns,
        ),
        "Amount": pd.DataFrame(
            [[123.4], [128.391242]],
            index=index,
            columns=columns,
        ),
    }


class FakeTdxClient:
    def __init__(
        self,
        response,
    ) -> None:
        self.response = response
        self.calls = []

    def get_market_data(
        self,
        **kwargs,
    ):
        self.calls.append(kwargs)
        return self.response


def test_fetch_daily_bars_uses_expected_tdx_arguments() -> None:
    client = FakeTdxClient(_response_dates_by_rows())

    provider = TdxDailyBarProvider(
        client,
        clock=_clock_after_close,
    )

    batch = provider.fetch_daily_bars(
        _request(
            _instrument("000001"),
            _instrument("600000"),
        )
    )

    assert len(client.calls) == 1

    call = client.calls[0]

    assert call["field_list"] == [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "Amount",
    ]

    assert call["stock_list"] == [
        "000001.SZ",
        "600000.SH",
    ]

    assert call["period"] == "1d"
    assert call["start_time"] == "20260915"
    assert call["end_time"] == "20260915"
    assert call["count"] == -1

    assert call["dividend_type"] == "none"
    assert call["fill_data"] is False

    assert batch.provider == TDX_PROVIDER_NAME
    assert batch.adapter_version == TDX_DAILY_BAR_ADAPTER_VERSION
    assert batch.payload_format == TDX_DAILY_BAR_PAYLOAD_FORMAT


def test_fetch_daily_bars_maps_canonical_rows() -> None:
    provider = TdxDailyBarProvider(
        FakeTdxClient(_response_dates_by_rows()),
        clock=_clock_after_close,
    )

    batch = provider.fetch_daily_bars(
        _request(
            _instrument("000001"),
            _instrument("600000"),
        )
    )

    assert len(batch.rows) == 2

    first, second = batch.rows

    assert first.instrument == _instrument("000001")
    assert second.instrument == _instrument("600000")

    assert first.session_date == _SESSION_DATE
    assert second.session_date == _SESSION_DATE

    assert first.open_value == Decimal("12.1")
    assert first.high_value == Decimal("12.5")
    assert first.low_value == Decimal("12.0")
    assert first.close_value == Decimal("12.34")

    assert second.close_value == Decimal("10.48")


def test_amount_is_converted_from_wan_yuan_to_yuan() -> None:
    provider = TdxDailyBarProvider(
        FakeTdxClient(_response_dates_by_rows()),
        clock=_clock_after_close,
    )

    batch = provider.fetch_daily_bars(
        _request(
            _instrument("000001"),
            _instrument("600000"),
        )
    )

    by_symbol = {row.instrument.symbol: row for row in batch.rows}

    assert by_symbol["000001"].amount == Decimal("1234000.0")

    assert by_symbol["600000"].amount == Decimal("1283912.420000")


def test_provider_does_not_invent_available_at() -> None:
    provider = TdxDailyBarProvider(
        FakeTdxClient(_response_dates_by_rows()),
        clock=_clock_after_close,
    )

    batch = provider.fetch_daily_bars(
        _request(
            _instrument("600000"),
        )
    )

    assert batch.rows[0].available_at is None


def test_event_time_is_shanghai_market_close() -> None:
    provider = TdxDailyBarProvider(
        FakeTdxClient(_response_dates_by_rows()),
        clock=_clock_after_close,
    )

    batch = provider.fetch_daily_bars(
        _request(
            _instrument("600000"),
        )
    )

    assert batch.rows[0].event_time == datetime(
        2026,
        9,
        15,
        7,
        0,
        tzinfo=timezone.utc,
    )


def test_response_with_instruments_on_index_is_supported() -> None:
    provider = TdxDailyBarProvider(
        FakeTdxClient(_response_codes_by_rows()),
        clock=_clock_after_close,
    )

    batch = provider.fetch_daily_bars(
        _request(
            _instrument("000001"),
            _instrument("600000"),
        )
    )

    assert [row.instrument.symbol for row in batch.rows] == [
        "000001",
        "600000",
    ]


@pytest.mark.parametrize(
    "instrument,expected",
    [
        (
            _instrument("600000"),
            "600000.SH",
        ),
        (
            _instrument("000001"),
            "000001.SZ",
        ),
        (
            _instrument("300750"),
            "300750.SZ",
        ),
        (
            _instrument("688981"),
            "688981.SH",
        ),
        (
            _instrument("920001"),
            "920001.BJ",
        ),
        (
            _instrument(
                "510300",
                InstrumentType.ETF,
            ),
            "510300.SH",
        ),
        (
            _instrument(
                "159919",
                InstrumentType.ETF,
            ),
            "159919.SZ",
        ),
    ],
)
def test_instrument_mapping(
    instrument,
    expected,
) -> None:
    response = {
        field: pd.DataFrame(
            [[1.0]],
            index=[pd.Timestamp("2026-09-15")],
            columns=[
                expected,
            ],
        )
        for field in (
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "Amount",
        )
    }

    provider = TdxDailyBarProvider(
        FakeTdxClient(response),
        clock=_clock_after_close,
    )

    provider.fetch_daily_bars(_request(instrument))


def test_unsupported_instrument_type_is_rejected() -> None:
    provider = TdxDailyBarProvider(
        FakeTdxClient({}),
        clock=_clock_after_close,
    )

    with pytest.raises(
        TdxProviderRequestError,
        match=("tdx_instrument_type_unsupported"),
    ):
        provider.fetch_daily_bars(
            _request(
                _instrument(
                    "000001",
                    InstrumentType.INDEX,
                )
            )
        )


def test_unknown_stock_exchange_is_rejected() -> None:
    provider = TdxDailyBarProvider(
        FakeTdxClient({}),
        clock=_clock_after_close,
    )

    with pytest.raises(
        TdxProviderRequestError,
        match="tdx_stock_exchange_unknown",
    ):
        provider.fetch_daily_bars(_request(_instrument("999999")))


def test_request_must_be_single_session() -> None:
    provider = TdxDailyBarProvider(
        FakeTdxClient({}),
        clock=_clock_after_close,
    )

    request = DailyBarRequest(
        instruments=(_instrument("600000"),),
        start_date=date(
            2026,
            9,
            14,
        ),
        end_date=date(
            2026,
            9,
            15,
        ),
    )

    with pytest.raises(
        TdxProviderRequestError,
        match=("tdx_daily_bar_request_must_be_single_session"),
    ):
        provider.fetch_daily_bars(request)


def test_session_must_be_closed_before_daily_fetch() -> None:
    provider = TdxDailyBarProvider(
        FakeTdxClient({}),
        clock=_clock_before_close,
    )

    with pytest.raises(
        TdxProviderRequestError,
        match=("tdx_daily_bar_session_not_closed"),
    ):
        provider.fetch_daily_bars(_request(_instrument("600000")))


def test_empty_field_frames_produce_empty_batch() -> None:
    response = {
        field: pd.DataFrame()
        for field in (
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "Amount",
        )
    }

    provider = TdxDailyBarProvider(
        FakeTdxClient(response),
        clock=_clock_after_close,
    )

    batch = provider.fetch_daily_bars(_request(_instrument("600000")))

    assert batch.rows == ()
    assert batch.record_count == 0


def test_missing_required_field_is_rejected() -> None:
    response = _response_dates_by_rows()

    del response["Close"]

    provider = TdxDailyBarProvider(
        FakeTdxClient(response),
        clock=_clock_after_close,
    )

    with pytest.raises(
        TdxProviderResponseError,
        match="tdx_response_field_missing:Close",
    ):
        provider.fetch_daily_bars(
            _request(
                _instrument("000001"),
                _instrument("600000"),
            )
        )


def test_non_dataframe_field_is_rejected() -> None:
    response = _response_dates_by_rows()

    response["Close"] = [
        12.34,
        10.48,
    ]

    provider = TdxDailyBarProvider(
        FakeTdxClient(response),
        clock=_clock_after_close,
    )

    with pytest.raises(
        TdxProviderResponseError,
        match=("tdx_response_field_must_be_dataframe"),
    ):
        provider.fetch_daily_bars(
            _request(
                _instrument("000001"),
                _instrument("600000"),
            )
        )


def test_incomplete_row_is_rejected() -> None:
    response = _response_dates_by_rows()

    response["Close"] = pd.DataFrame(
        [[12.34]],
        index=[pd.Timestamp("2026-09-15")],
        columns=[
            "000001.SZ",
        ],
    )

    provider = TdxDailyBarProvider(
        FakeTdxClient(response),
        clock=_clock_after_close,
    )

    with pytest.raises(
        TdxProviderResponseError,
        match="tdx_response_row_incomplete",
    ):
        provider.fetch_daily_bars(
            _request(
                _instrument("000001"),
                _instrument("600000"),
            )
        )


def test_unexpected_session_is_rejected() -> None:
    response = _response_dates_by_rows()

    response["Close"].index = [pd.Timestamp("2026-09-14")]

    provider = TdxDailyBarProvider(
        FakeTdxClient(response),
        clock=_clock_after_close,
    )

    with pytest.raises(
        TdxProviderResponseError,
        match=("tdx_response_session_unexpected"),
    ):
        provider.fetch_daily_bars(
            _request(
                _instrument("000001"),
                _instrument("600000"),
            )
        )


def test_non_finite_numeric_value_is_rejected() -> None:
    response = _response_dates_by_rows()

    response["Close"].loc[
        pd.Timestamp("2026-09-15"),
        "600000.SH",
    ] = float("inf")

    provider = TdxDailyBarProvider(
        FakeTdxClient(response),
        clock=_clock_after_close,
    )

    with pytest.raises(
        TdxProviderResponseError,
        match="tdx_response_number_invalid:Close",
    ):
        provider.fetch_daily_bars(
            _request(
                _instrument("000001"),
                _instrument("600000"),
            )
        )


def test_raw_payload_is_deterministic() -> None:
    response = _response_dates_by_rows()

    first = TdxDailyBarProvider(
        FakeTdxClient(response),
        clock=_clock_after_close,
    ).fetch_daily_bars(
        _request(
            _instrument("000001"),
            _instrument("600000"),
        )
    )

    second = TdxDailyBarProvider(
        FakeTdxClient(response),
        clock=_clock_after_close,
    ).fetch_daily_bars(
        _request(
            _instrument("000001"),
            _instrument("600000"),
        )
    )

    assert first.raw_payload == second.raw_payload


def test_raw_payload_contains_provider_observation() -> None:
    provider = TdxDailyBarProvider(
        FakeTdxClient(_response_dates_by_rows()),
        clock=_clock_after_close,
    )

    batch = provider.fetch_daily_bars(
        _request(
            _instrument("000001"),
            _instrument("600000"),
        )
    )

    text = batch.raw_payload.decode("utf-8")

    assert TDX_DAILY_BAR_PAYLOAD_FORMAT in text
    assert "000001.SZ" in text
    assert "600000.SH" in text
    assert "Close" in text
