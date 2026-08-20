from __future__ import annotations

import pytest

from core.types import AssetClass, Symbol
from data.source import normalize_provider_quote


def test_normalize_provider_quote_preserves_legacy_keys_and_adds_stable_identity():
    quote = normalize_provider_quote(
        Symbol("600001"),
        AssetClass.STOCK,
        {
            "price": "8.76",
            "volume": "123456",
            "turnover": "1081488",
            "timestamp": "2026-01-12T11:22:00",
            "quote_source": "tushare_realtime_quote",
            "display_name": "示例能源",
            "previous_close": "8.65",
            "change": "0.11",
            "change_percent": "0.012716763",
        },
        provider_name="tushare",
        provider_symbol="600001.SH",
    )

    assert quote is not None
    assert quote.to_payload() == {
        "asset_class": "stock",
        "change": pytest.approx(0.11),
        "change_percent": pytest.approx(0.012716763),
        "display_name": "示例能源",
        "previous_close": 8.65,
        "price": 8.76,
        "provider_name": "tushare",
        "provider_symbol": "600001.SH",
        "quote_source": "tushare_realtime_quote",
        "source": "tushare",
        "symbol": "600001",
        "timestamp": "2026-01-12T11:22:00",
        "turnover": 1081488.0,
        "volume": 123456.0,
    }


def test_normalize_provider_quote_rejects_payload_without_price():
    assert (
        normalize_provider_quote(
            Symbol("600001"),
            AssetClass.STOCK,
            {"timestamp": "2026-01-12"},
            provider_name="tushare",
        )
        is None
    )


def test_normalize_provider_quote_preserves_fund_nav_baseline_date():
    quote = normalize_provider_quote(
        Symbol("019999"),
        AssetClass.FUND,
        {
            "price": "2.5123",
            "timestamp": "2026-06-04T14:59:00+08:00",
            "quote_source": "sina_fund_estimate",
            "nav_date": "2026-06-03",
        },
        provider_name="sina",
    )

    assert quote is not None
    assert quote.to_payload()["nav_date"] == "2026-06-03"
