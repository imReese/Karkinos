from __future__ import annotations

from types import SimpleNamespace
import sys

import pandas as pd
import pytest

from core.types import AssetClass, Symbol
from data.providers.tushare_source import TushareSource


def test_tushare_fetch_latest_stock_uses_realtime_quote(monkeypatch):
    calls: dict[str, object] = {}

    def set_token(token):
        raise AssertionError("fetch_latest must not write the token file")

    def realtime_quote(ts_code, src="dc"):
        calls["realtime"] = (ts_code, src)
        return pd.DataFrame(
            {
                "NAME": ["中国核电"],
                "TS_CODE": ["601985.SH"],
                "DATE": ["20260605"],
                "TIME": ["11:22:00"],
                "PRICE": [8.76],
                "PRE_CLOSE": [8.65],
                "VOLUME": [123456.0],
                "AMOUNT": [1081488.0],
            }
        )

    monkeypatch.setitem(
        sys.modules,
        "tushare",
        SimpleNamespace(set_token=set_token, realtime_quote=realtime_quote),
    )

    result = TushareSource(token="token-1234").fetch_latest(
        Symbol("601985"), AssetClass.STOCK
    )

    assert result == {
        "price": 8.76,
        "volume": 123456.0,
        "turnover": 1081488.0,
        "timestamp": "2026-06-05T11:22:00",
        "source": "tushare",
        "quote_source": "tushare_realtime_quote",
        "display_name": "中国核电",
        "previous_close": 8.65,
        "change": pytest.approx(0.11),
        "change_percent": pytest.approx(0.012716763),
        "previous_close_date": "2026-06-05",
    }
    assert calls["realtime"] == ("601985.SH", "dc")


def test_tushare_fetch_latest_stock_falls_back_to_daily(monkeypatch):
    calls: dict[str, object] = {}

    class FakePro:
        def daily(self, ts_code, start_date, end_date):
            assert ts_code == "603659.SH"
            assert start_date <= "20260605" <= end_date
            return pd.DataFrame(
                {
                    "trade_date": ["20260605", "20260604"],
                    "close": [29.98, 29.12],
                    "pre_close": [29.12, 29.55],
                    "change": [0.86, -0.43],
                    "pct_chg": [2.9533, -1.4552],
                    "vol": [1000.0, 2000.0],
                    "amount": [29980.0, 58240.0],
                }
            )

    def realtime_quote(ts_code, src="dc"):
        raise AttributeError("'dict' object has no attribute 'text'")

    def pro_api(token=None):
        calls["pro_api_token"] = token
        return FakePro()

    monkeypatch.setitem(
        sys.modules,
        "tushare",
        SimpleNamespace(
            set_token=lambda token: (_ for _ in ()).throw(
                AssertionError("fetch_latest must not write the token file")
            ),
            realtime_quote=realtime_quote,
            pro_api=pro_api,
        ),
    )

    result = TushareSource(token="token-1234").fetch_latest(
        Symbol("603659"), AssetClass.STOCK
    )

    assert result is not None
    assert result["price"] == 29.98
    assert result["previous_close"] == 29.12
    assert result["change"] == 0.86
    assert result["change_percent"] == pytest.approx(0.029533)
    assert result["timestamp"] == "2026-06-05"
    assert result["quote_source"] == "tushare_daily"
    assert calls["pro_api_token"] == "token-1234"


def test_tushare_fetch_latest_fund_uses_fund_nav(monkeypatch):
    calls: dict[str, object] = {}

    class FakePro:
        def fund_nav(self, ts_code, start_date, end_date):
            calls["fund_nav"] = (ts_code, start_date, end_date)
            return pd.DataFrame(
                {
                    "ts_code": ["018125.OF", "018125.OF"],
                    "nav_date": ["20260604", "20260603"],
                    "unit_nav": [2.5123, 2.5],
                    "accum_nav": [2.5123, 2.5],
                }
            )

    def pro_api(token=None):
        calls["pro_api_token"] = token
        return FakePro()

    monkeypatch.setitem(
        sys.modules,
        "tushare",
        SimpleNamespace(pro_api=pro_api),
    )

    result = TushareSource(token="token-1234").fetch_latest(
        Symbol("018125"), AssetClass.FUND
    )

    assert result is not None
    assert result["price"] == 2.5123
    assert result["timestamp"] == "2026-06-04"
    assert result["quote_source"] == "tushare_fund_nav"
    assert result["previous_close"] == 2.5
    assert result["previous_close_date"] == "2026-06-03"
    assert result["day_change_value"] == pytest.approx(0.0123)
    assert result["day_change_pct"] == pytest.approx(0.00492)
    assert calls["pro_api_token"] == "token-1234"
    assert calls["fund_nav"][0] == "018125.OF"


def test_tushare_fetch_latest_unsupported_asset_returns_none():
    assert (
        TushareSource(token="token-1234").fetch_latest(
            Symbol("Au99.99"), AssetClass.GOLD
        )
        is None
    )
