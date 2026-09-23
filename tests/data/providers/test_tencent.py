"""Tests for the dedicated Tencent market data provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.types import AssetClass, BarFrequency, Symbol
from data.providers.tencent import (
    TENCENT_DAILY_BAR_DESCRIPTOR,
    TencentDailyBarProvider,
    TencentSource,
    fetch_tencent_realtime_quote,
    resolve_tencent_market_prefix,
)


def test_resolve_tencent_market_prefix() -> None:
    # Stocks
    assert resolve_tencent_market_prefix("603659", AssetClass.STOCK) == "sh"
    assert resolve_tencent_market_prefix("688001", AssetClass.STOCK) == "sh"
    assert resolve_tencent_market_prefix("002594", AssetClass.STOCK) == "sz"
    assert resolve_tencent_market_prefix("300750", AssetClass.STOCK) == "sz"
    assert resolve_tencent_market_prefix("830896", AssetClass.STOCK) == "bj"
    assert resolve_tencent_market_prefix("920002", AssetClass.STOCK) == "bj"

    # ETFs
    assert resolve_tencent_market_prefix("510300", AssetClass.FUND) == "sh"
    assert resolve_tencent_market_prefix("159915", AssetClass.FUND) == "sz"

    # Indices
    assert resolve_tencent_market_prefix("000001", AssetClass.INDEX) == "sh"
    assert resolve_tencent_market_prefix("000300", AssetClass.INDEX) == "sh"
    assert resolve_tencent_market_prefix("399001", AssetClass.INDEX) == "sz"
    assert resolve_tencent_market_prefix("399006", AssetClass.INDEX) == "sz"


def test_fetch_tencent_realtime_quote_stock() -> None:
    parts = [""] * 60
    parts[1] = "璞泰来"
    parts[2] = "603659"
    parts[3] = "22.10"
    parts[4] = "21.80"
    parts[6] = "1500"  # 1500 手
    parts[30] = "20260923141500"
    parts[31] = "0.30"
    parts[32] = "1.38"
    parts[37] = "3300"  # 3300 万元
    raw_text = f'v_sh603659="{"~".join(parts)}";'

    mock_resp = MagicMock()
    mock_resp.text = raw_text
    mock_resp.encoding = "gbk"

    with patch("requests.get", return_value=mock_resp):
        quote = fetch_tencent_realtime_quote("603659", AssetClass.STOCK)

    assert quote is not None
    assert quote["symbol"] == "603659"
    assert quote["asset_class"] == "stock"
    assert quote["provider_name"] == "tencent"
    assert quote["provider_symbol"] == "sh603659"
    assert quote["quote_source"] == "tencent_realtime_quote"
    assert quote["price"] == 22.10
    assert quote["previous_close"] == 21.80
    assert quote["change"] == 0.30
    assert quote["change_percent"] == 0.0138
    assert quote["volume"] == 150000.0  # 1500 lots * 100
    assert quote["turnover"] == 33000000.0
    assert quote["display_name"] == "璞泰来"
    assert quote["timestamp"] == "2026-09-23T14:15:00+08:00"


def test_fetch_tencent_realtime_quote_index() -> None:
    parts = [""] * 60
    parts[1] = "上证指数"
    parts[2] = "000001"
    parts[3] = "3944.01"
    parts[4] = "3952.13"
    parts[6] = "2850000"
    parts[30] = "20260923150000"
    parts[31] = "-8.12"
    parts[32] = "-0.21"
    parts[37] = "540000"
    raw_text = f'v_sh000001="{"~".join(parts)}";'

    mock_resp = MagicMock()
    mock_resp.text = raw_text
    mock_resp.encoding = "gbk"

    with patch("requests.get", return_value=mock_resp):
        quote = fetch_tencent_realtime_quote("000001", AssetClass.INDEX)

    assert quote is not None
    assert quote["symbol"] == "000001"
    assert quote["asset_class"] == "index"
    assert quote["provider_name"] == "tencent"
    assert quote["provider_symbol"] == "sh000001"
    assert quote["price"] == 3944.01
    assert quote["display_name"] == "上证指数"
    assert quote["change"] == -8.12
    assert quote["change_percent"] == -0.0021


def test_fetch_tencent_realtime_quote_network_error_returns_none() -> None:
    with patch("requests.get", side_effect=Exception("connection refused")):
        quote = fetch_tencent_realtime_quote("603659", AssetClass.STOCK)
    assert quote is None


def test_tencent_source_interface() -> None:
    source = TencentSource()
    assert source.supports_bars(AssetClass.STOCK, BarFrequency.DAILY) is True
    assert source.supports_bars(AssetClass.FUND, BarFrequency.DAILY) is True
    assert source.supports_bars(AssetClass.BOND, BarFrequency.DAILY) is False
    assert source.supports_bars(AssetClass.STOCK, BarFrequency.MIN_1) is False

    parts = [""] * 60
    parts[1] = "中国核电"
    parts[2] = "601985"
    parts[3] = "8.85"
    parts[30] = "20260923141500"
    raw_text = f'v_sh601985="{"~".join(parts)}";'

    mock_resp = MagicMock()
    mock_resp.text = raw_text
    mock_resp.encoding = "gbk"

    with patch("requests.get", return_value=mock_resp):
        quote = source.fetch_latest(Symbol("601985"), AssetClass.STOCK)

    assert quote is not None
    assert quote["price"] == 8.85
    assert quote["provider_name"] == "tencent"


def test_tencent_daily_bar_provider_descriptor() -> None:
    provider = TencentDailyBarProvider()
    assert provider.descriptor == TENCENT_DAILY_BAR_DESCRIPTOR
    assert provider.descriptor.provider == "tencent"
    assert provider.descriptor.upstream_group == "tencent"
