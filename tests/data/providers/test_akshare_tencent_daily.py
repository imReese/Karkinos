from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarProvider, DailyBarRequest
from data.providers.akshare_tencent_daily import (
    AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR,
    AkshareTencentDailyBarProvider,
    AkshareTencentDailyBarRequestError,
    AkshareTencentDailyBarResponseError,
)

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
    assert payload["schema"] == "akshare.tencent.stock_zh_a_hist_tx.dataframe.v1"
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
