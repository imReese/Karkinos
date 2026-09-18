from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarProvider, DailyBarRequest
from data.providers.tushare_daily import (
    TUSHARE_DAILY_BAR_DESCRIPTOR,
    TushareDailyBarProvider,
    TushareDailyBarRequestError,
    TushareDailyBarResponseError,
)

DAY = date(2026, 9, 15)
AFTER_CLOSE = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)


class FakePro:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def daily(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("daily", kwargs))
        return _frame("20260915", close=10.48)

    def fund_daily(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("fund_daily", kwargs))
        return _frame("20260915", close=4.017)


def _frame(trade_date: str, *, close: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": [trade_date],
            "open": [close - 0.1],
            "high": [close + 0.1],
            "low": [close - 0.2],
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
