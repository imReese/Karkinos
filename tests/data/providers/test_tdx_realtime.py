"""Tests for TDX realtime quote and bar DataSource implementation."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from core.types import AssetClass, BarFrequency, Symbol
from data.providers.tdx import (
    TdxClientManager,
    TdxSource,
    fetch_tdx_realtime_quote,
    is_tdx_supported_symbol,
    resolve_tdx_market,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_resolve_tdx_market() -> None:
    # Stocks
    assert resolve_tdx_market("601985", AssetClass.STOCK) == 1
    assert resolve_tdx_market("688001", AssetClass.STOCK) == 1
    assert resolve_tdx_market("002594", AssetClass.STOCK) == 0
    assert resolve_tdx_market("300750", AssetClass.STOCK) == 0

    # ETFs
    assert resolve_tdx_market("510300", AssetClass.FUND) == 1
    assert resolve_tdx_market("159915", AssetClass.FUND) == 0

    # Indices
    assert resolve_tdx_market("000001", AssetClass.INDEX) == 1
    assert resolve_tdx_market("399001", AssetClass.INDEX) == 0
    assert resolve_tdx_market("399006", AssetClass.INDEX) == 0


def test_is_tdx_supported_symbol() -> None:
    assert is_tdx_supported_symbol("601985", AssetClass.STOCK) is True
    assert is_tdx_supported_symbol("002594", AssetClass.STOCK) is True
    assert is_tdx_supported_symbol("510050", AssetClass.FUND) is True
    assert is_tdx_supported_symbol("000001", AssetClass.INDEX) is True
    # Beijing exchange is not supported on Level 1 quote servers
    assert is_tdx_supported_symbol("430047", AssetClass.STOCK) is False
    assert is_tdx_supported_symbol("835185", AssetClass.STOCK) is False
    assert is_tdx_supported_symbol("920002", AssetClass.STOCK) is False
    # Invalid symbol length
    assert is_tdx_supported_symbol("600", AssetClass.STOCK) is False
    assert is_tdx_supported_symbol("", AssetClass.STOCK) is False


def test_fetch_tdx_realtime_quote_stock() -> None:
    mock_item = OrderedDict(
        {
            "market": 1,
            "code": "601985",
            "price": 9.17,
            "last_close": 9.11,
            "open": 9.15,
            "high": 9.22,
            "low": 9.10,
            "servertime": "15:29:55.404",
            "vol": 1058634,
            "amount": 1243459840.0,
        }
    )

    mock_mgr = MagicMock(spec=TdxClientManager)
    mock_mgr.execute.return_value = [mock_item]

    quote = fetch_tdx_realtime_quote(
        "601985",
        AssetClass.STOCK,
        client_manager=mock_mgr,
    )

    assert quote is not None
    assert quote["symbol"] == "601985"
    assert quote["asset_class"] == "stock"
    assert quote["provider_name"] == "tdx"
    assert quote["provider_symbol"] == "601985.SH"
    assert quote["quote_source"] == "tdx_realtime_quote"
    assert quote["price"] == 9.17
    assert quote["previous_close"] == 9.11
    assert quote["change"] == 0.06
    assert quote["change_percent"] == round(0.06 / 9.11, 6)
    assert quote["volume"] == 105863400.0  # lots * 100
    assert quote["turnover"] == 1243459840.0


def test_fetch_tdx_realtime_quote_etf_scale_factor() -> None:
    # TDX encodes ETFs in mills (1/1000 yuan), but pytdx hardcodes / 100.
    # So pytdx returns 29.32 for a 2.932 ETF price.
    mock_item = OrderedDict(
        {
            "market": 1,
            "code": "510050",
            "price": 29.32,
            "last_close": 29.19,
            "open": 29.19,
            "high": 29.47,
            "low": 29.15,
            "servertime": "152:59:49.445",  # pytdx timestamp format
            "vol": 3487494,
            "amount": 1022028288.0,
        }
    )

    mock_mgr = MagicMock(spec=TdxClientManager)
    mock_mgr.execute.return_value = [mock_item]

    quote = fetch_tdx_realtime_quote(
        "510050",
        AssetClass.FUND,
        client_manager=mock_mgr,
    )

    assert quote is not None
    assert quote["symbol"] == "510050"
    assert quote["asset_class"] == "fund"
    assert quote["provider_name"] == "tdx"
    assert quote["provider_symbol"] == "510050.SH"
    # Adjusted with 0.1 scale factor
    assert quote["price"] == 2.932
    assert quote["previous_close"] == 2.919
    assert quote["change"] == round(2.932 - 2.919, 4)
    assert quote["volume"] == 348749400.0


def test_fetch_tdx_realtime_quote_index() -> None:
    mock_item = OrderedDict(
        {
            "market": 1,
            "code": "000001",
            "price": 3797.24,
            "last_close": 3813.79,
            "open": 3806.98,
            "high": 3828.22,
            "low": 3791.0,
            "servertime": "14:55:32.797",
            "vol": 461448981,
            "amount": 714909941760.0,
        }
    )

    mock_mgr = MagicMock(spec=TdxClientManager)
    mock_mgr.execute.return_value = [mock_item]

    quote = fetch_tdx_realtime_quote(
        "000001",
        AssetClass.INDEX,
        client_manager=mock_mgr,
    )

    assert quote is not None
    assert quote["symbol"] == "000001"
    assert quote["asset_class"] == "index"
    assert quote["price"] == 3797.24
    assert quote["previous_close"] == 3813.79
    assert quote["volume"] == 461448981.0  # Index volume is not scaled by 100


def test_fetch_tdx_realtime_quote_error_returns_none() -> None:
    mock_mgr = MagicMock(spec=TdxClientManager)
    mock_mgr.execute.return_value = None

    quote = fetch_tdx_realtime_quote(
        "601985",
        AssetClass.STOCK,
        client_manager=mock_mgr,
    )
    assert quote is None


def test_tdx_source_capabilities() -> None:
    source = TdxSource()
    assert source.supports_bars(AssetClass.STOCK, BarFrequency.DAILY) is True
    assert source.supports_bars(AssetClass.FUND, BarFrequency.DAILY) is True
    assert source.supports_bars(AssetClass.INDEX, BarFrequency.DAILY) is True
    assert source.supports_bars(AssetClass.BOND, BarFrequency.DAILY) is False
    assert source.supports_bars(AssetClass.STOCK, BarFrequency.MIN_1) is False
    assert source.list_symbols() == []
    with pytest.raises(NotImplementedError):
        source.fetch_ticks(
            Symbol("601985"),
            datetime.now(),
            datetime.now(),
        )


def test_tdx_source_fetch_bars() -> None:
    mock_bars = [
        OrderedDict(
            {
                "open": 11.57,
                "close": 11.78,
                "high": 11.87,
                "low": 11.55,
                "vol": 1481685.0,
                "amount": 1743402496.0,
                "datetime": "2026-10-08 15:00",
            }
        ),
        OrderedDict(
            {
                "open": 11.78,
                "close": 11.59,
                "high": 11.89,
                "low": 11.53,
                "vol": 1078105.0,
                "amount": 1259717120.0,
                "datetime": "2026-10-09 15:00",
            }
        ),
        OrderedDict(
            {
                "open": 11.62,
                "close": 11.73,
                "high": 11.83,
                "low": 11.62,
                "vol": 1058634.0,
                "amount": 1243459840.0,
                "datetime": "2026-10-12 15:00",
            }
        ),
    ]

    mock_mgr = MagicMock(spec=TdxClientManager)
    mock_mgr.execute.return_value = mock_bars

    source = TdxSource(client_manager=mock_mgr)
    df = source.fetch_bars(
        Symbol("000001"),
        start=datetime(2026, 10, 8, tzinfo=_SHANGHAI),
        end=datetime(2026, 10, 12, tzinfo=_SHANGHAI),
        frequency=BarFrequency.DAILY,
        asset_class=AssetClass.STOCK,
    )

    assert not df.empty
    assert len(df) == 3
    assert list(df.columns) == [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    assert df.iloc[-1]["close"] == 11.73
    assert df.attrs["provider_name"] == "tdx"


def test_tdx_source_fetch_bars_pagination() -> None:
    base_date = datetime(2023, 1, 1)
    batch0 = [
        OrderedDict(
            {
                "open": 10.0,
                "close": 10.5,
                "high": 10.8,
                "low": 9.9,
                "vol": 1000.0,
                "amount": 10000.0,
                "datetime": (base_date + timedelta(days=i)).strftime("%Y-%m-%d 15:00"),
            }
        )
        for i in range(1, 801)
    ]
    batch1 = [
        OrderedDict(
            {
                "open": 8.0,
                "close": 8.5,
                "high": 8.8,
                "low": 7.9,
                "vol": 1000.0,
                "amount": 8000.0,
                "datetime": "2021-01-04 15:00",
            }
        )
    ]

    mock_api = MagicMock()
    mock_api.get_index_bars.side_effect = [batch0, batch1]

    mock_mgr = MagicMock(spec=TdxClientManager)
    # execute calls the inner _fetch callback with mock_api
    mock_mgr.execute.side_effect = lambda fn: fn(mock_api)

    source = TdxSource(client_manager=mock_mgr)
    df = source.fetch_bars(
        Symbol("000001"),
        start=datetime(2021, 1, 1, tzinfo=_SHANGHAI),
        end=datetime(2026, 10, 12, tzinfo=_SHANGHAI),
        frequency=BarFrequency.DAILY,
        asset_class=AssetClass.INDEX,
    )

    assert not df.empty
    assert len(df) == 801
    assert df.iloc[0]["timestamp"].strftime("%Y-%m-%d") == "2021-01-04"
