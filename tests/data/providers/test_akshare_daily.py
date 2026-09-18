from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarProvider, DailyBarRequest
from data.providers.akshare_daily import (
    AKSHARE_DAILY_BAR_DESCRIPTOR,
    AkshareDailyBarProvider,
    AkshareDailyBarRequestError,
    AkshareDailyBarResponseError,
)

DAY = date(2026, 9, 15)
AFTER_CLOSE = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)


class FakeAkshare:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def stock_zh_a_hist(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("stock_zh_a_hist", kwargs))
        return _frame(close=10.48)

    def fund_etf_hist_em(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(("fund_etf_hist_em", kwargs))
        return _frame(close=4.017)


def _frame(*, close: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "日期": ["2026-09-15"],
            "开盘": [close - 0.1],
            "最高": [close + 0.1],
            "最低": [close - 0.2],
            "收盘": [close],
            "成交量": [1234.5],
            "成交额": [6789250.0],
        }
    )


def _request(*items: InstrumentKey) -> DailyBarRequest:
    return DailyBarRequest(tuple(items), DAY, DAY)


def test_akshare_daily_provider_satisfies_canonical_protocol() -> None:
    provider = AkshareDailyBarProvider(FakeAkshare(), clock=lambda: AFTER_CLOSE)
    assert isinstance(provider, DailyBarProvider)
    assert provider.descriptor == AKSHARE_DAILY_BAR_DESCRIPTOR
    assert provider.descriptor.upstream_group == "eastmoney"


def test_akshare_daily_provider_forces_unadjusted_stock_and_etf_calls() -> None:
    client = FakeAkshare()
    result = AkshareDailyBarProvider(
        client, clock=lambda: AFTER_CLOSE
    ).fetch_daily_bars(
        _request(
            InstrumentKey("600000", InstrumentType.STOCK),
            InstrumentKey("510300", InstrumentType.ETF),
        )
    )
    assert [item[0] for item in client.calls] == ["fund_etf_hist_em", "stock_zh_a_hist"]
    for _, kwargs in client.calls:
        assert kwargs["period"] == "daily"
        assert kwargs["start_date"] == "20260915"
        assert kwargs["end_date"] == "20260915"
        assert kwargs["adjust"] == ""

    assert [row.instrument for row in result.rows] == [
        InstrumentKey("510300", InstrumentType.ETF),
        InstrumentKey("600000", InstrumentType.STOCK),
    ]
    for row in result.rows:
        assert row.volume == Decimal("123450.0")
        assert row.amount == Decimal("6789250.0")
        assert row.available_at is None
        assert row.event_time == datetime(2026, 9, 15, 7, 0, tzinfo=timezone.utc)


def test_akshare_daily_provider_preserves_stable_sdk_response_evidence() -> None:
    result = AkshareDailyBarProvider(
        FakeAkshare(), clock=lambda: AFTER_CLOSE
    ).fetch_daily_bars(_request(InstrumentKey("600000", InstrumentType.STOCK)))
    payload = json.loads(result.raw_payload)
    assert payload["schema"] == "akshare.eastmoney.daily_bar.dataframe.v1"
    assert payload["calls"][0]["endpoint"] == "stock_zh_a_hist"
    assert payload["calls"][0]["request"]["adjust"] == ""
    assert payload["calls"][0]["frame"]["columns"] == [
        "日期",
        "开盘",
        "最高",
        "最低",
        "收盘",
        "成交量",
        "成交额",
    ]


def test_akshare_daily_provider_keeps_empty_result_as_empty_batch() -> None:
    class EmptyAkshare(FakeAkshare):
        def stock_zh_a_hist(self, **kwargs: object) -> pd.DataFrame:
            self.calls.append(("stock_zh_a_hist", kwargs))
            return pd.DataFrame()

    result = AkshareDailyBarProvider(
        EmptyAkshare(), clock=lambda: AFTER_CLOSE
    ).fetch_daily_bars(_request(InstrumentKey("600000", InstrumentType.STOCK)))
    assert result.rows == ()


def test_akshare_daily_provider_rejects_session_before_close() -> None:
    provider = AkshareDailyBarProvider(
        FakeAkshare(),
        clock=lambda: datetime(2026, 9, 15, 6, 59, tzinfo=timezone.utc),
    )
    with pytest.raises(
        AkshareDailyBarRequestError, match="akshare_daily_bar_session_not_closed"
    ):
        provider.fetch_daily_bars(
            _request(InstrumentKey("600000", InstrumentType.STOCK))
        )


def test_akshare_daily_provider_rejects_unreviewed_instrument_type() -> None:
    provider = AkshareDailyBarProvider(FakeAkshare(), clock=lambda: AFTER_CLOSE)
    with pytest.raises(
        AkshareDailyBarRequestError, match="akshare_instrument_type_unsupported"
    ):
        provider.fetch_daily_bars(
            _request(InstrumentKey("Au9999", InstrumentType.GOLD))
        )


def test_akshare_daily_provider_rejects_nonfinite_values() -> None:
    class BadAkshare(FakeAkshare):
        def stock_zh_a_hist(self, **kwargs: object) -> pd.DataFrame:
            frame = _frame(close=10.48)
            frame.loc[0, "收盘"] = float("inf")
            return frame

    provider = AkshareDailyBarProvider(BadAkshare(), clock=lambda: AFTER_CLOSE)
    with pytest.raises(
        AkshareDailyBarResponseError,
        match="akshare_response_number_invalid:收盘",
    ):
        provider.fetch_daily_bars(
            _request(InstrumentKey("600000", InstrumentType.STOCK))
        )
