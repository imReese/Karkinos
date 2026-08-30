from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from core.types import AssetClass, BarFrequency, Symbol
from data.providers.tushare_source import TushareSource


def test_tushare_bars_capability_is_stock_daily_only():
    source = TushareSource(token="token-1234")

    assert source.supports_bars(AssetClass.STOCK, BarFrequency.DAILY) is True
    assert source.supports_bars(AssetClass.FUND, BarFrequency.DAILY) is False
    assert source.supports_bars(AssetClass.STOCK, BarFrequency.MIN_1) is False


def test_tushare_stock_master_preserves_names_with_symbols(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakePro:
        def stock_basic(self, *, exchange, list_status):
            calls.append((exchange, list_status))
            return pd.DataFrame(
                {
                    "ts_code": ["600001.SH", "000001.SZ", "920001.BJ"],
                    "name": ["示例能源", "示例银行", "示例北交所"],
                    "exchange": ["SSE", "SZSE", "BSE"],
                }
            )

    monkeypatch.setattr(TushareSource, "_get_pro", lambda self: FakePro())

    rows = TushareSource(token="token-1234").list_symbol_metadata()

    assert calls == [("", "L")]
    assert [(row["symbol"], row["display_name"]) for row in rows] == [
        ("600001", "示例能源"),
        ("000001", "示例银行"),
        ("920001", "示例北交所"),
    ]
    assert [row["provider_symbol"] for row in rows] == [
        "600001.SH",
        "000001.SZ",
        "920001.BJ",
    ]
    assert [row["exchange"] for row in rows] == ["SSE", "SZSE", "BSE"]


def test_tushare_fetches_one_full_market_daily_cross_section(monkeypatch):
    calls: dict[str, object] = {}

    class FakePro:
        def daily(self, *, trade_date):
            calls["trade_date"] = trade_date
            return pd.DataFrame(
                {
                    "ts_code": ["600001.SH", "000001.SZ", "430001.BJ"],
                    "trade_date": [trade_date] * 3,
                    "open": [10.0, 20.0, 30.0],
                    "high": [10.2, 20.2, 30.2],
                    "low": [9.8, 19.8, 29.8],
                    "close": [10.1, 20.1, 30.1],
                    "vol": [100.0, 200.0, 300.0],
                    "amount": [1_000.0, 4_000.0, 9_000.0],
                }
            )

    monkeypatch.setattr(TushareSource, "_get_pro", lambda self: FakePro())

    frame = TushareSource(token="token-1234").fetch_market_daily_bars("2026-08-21")

    assert calls["trade_date"] == "20260821"
    assert frame["symbol"].tolist() == ["600001", "000001", "430001"]
    assert frame["timestamp"].dt.date.astype(str).unique().tolist() == ["2026-08-21"]
    assert frame["volume"].tolist() == [100.0, 200.0, 300.0]


def test_tushare_fetch_bars_uses_beijing_exchange_symbol(monkeypatch):
    calls: dict[str, object] = {}

    class FakePro:
        def daily(self, *, ts_code, start_date, end_date):
            calls.update(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
            return pd.DataFrame(
                {
                    "trade_date": ["20260821"],
                    "open": [10.0],
                    "high": [10.2],
                    "low": [9.8],
                    "close": [10.1],
                    "vol": [100.0],
                    "amount": [1010.0],
                }
            )

    monkeypatch.setattr(TushareSource, "_get_pro", lambda self: FakePro())

    frame = TushareSource(token="token-1234").fetch_bars(
        Symbol("430001"),
        pd.Timestamp("2026-08-01").to_pydatetime(),
        pd.Timestamp("2026-08-21").to_pydatetime(),
    )

    assert calls == {
        "ts_code": "430001.BJ",
        "start_date": "20260801",
        "end_date": "20260821",
    }
    assert frame.iloc[0]["close"] == 10.1


def test_tushare_maps_new_beijing_92_prefix_to_bj_exchange() -> None:
    assert TushareSource._stock_ts_code(Symbol("920001")) == "920001.BJ"


def test_tushare_fetch_latest_stock_uses_realtime_quote(monkeypatch):
    calls: dict[str, object] = {}

    def set_token(token):
        raise AssertionError("fetch_latest must not write the token file")

    def realtime_quote(ts_code, src="dc"):
        calls["realtime"] = (ts_code, src)
        return pd.DataFrame(
            {
                "NAME": ["示例能源"],
                "TS_CODE": ["600001.SH"],
                "DATE": ["20260112"],
                "TIME": [" 11:22:00"],
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
        Symbol("600001"), AssetClass.STOCK
    )

    assert result == {
        "asset_class": "stock",
        "change": pytest.approx(0.11),
        "change_percent": pytest.approx(0.012716763),
        "display_name": "示例能源",
        "previous_close": 8.65,
        "previous_close_date": "2026-01-12",
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
    assert calls["realtime"] == ("600001.SH", "dc")


def test_tushare_fetch_latest_stock_falls_back_to_daily(monkeypatch):
    calls: dict[str, object] = {}

    class FakePro:
        def daily(self, ts_code, start_date, end_date):
            assert ts_code == "600002.SH"
            latest_trade_date = end_date
            previous_trade_date = (
                pd.Timestamp(end_date) - pd.Timedelta(days=1)
            ).strftime("%Y%m%d")
            assert start_date <= latest_trade_date <= end_date
            calls["daily_range"] = (start_date, end_date, latest_trade_date)
            return pd.DataFrame(
                {
                    "trade_date": [latest_trade_date, previous_trade_date],
                    "close": [19.80, 29.12],
                    "pre_close": [29.12, 29.55],
                    "change": [0.86, -0.43],
                    "pct_chg": [2.9533, -1.4552],
                    "vol": [1000.0, 2000.0],
                    "amount": [19800.0, 58240.0],
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
        Symbol("600002"), AssetClass.STOCK
    )

    assert result is not None
    assert result["price"] == 19.80
    assert result["previous_close"] == 29.12
    assert result["change"] == 0.86
    assert result["change_percent"] == pytest.approx(0.029533)
    assert result["timestamp"] == _trade_date_iso(calls["daily_range"][2])
    assert result["quote_source"] == "tushare_daily"
    assert result["provider_name"] == "tushare"
    assert result["provider_symbol"] == "600002.SH"
    assert result["symbol"] == "600002"
    assert result["asset_class"] == "stock"
    assert calls["pro_api_token"] == "token-1234"


def _trade_date_iso(value: object) -> str:
    timestamp = pd.Timestamp(str(value))
    return timestamp.date().isoformat()


def test_tushare_fetch_latest_stock_times_out_realtime_and_falls_back_to_daily(
    monkeypatch,
):
    source = TushareSource(token="token-1234", realtime_timeout_seconds=0.001)

    def slow_realtime(ts_code):
        time.sleep(0.05)
        return {
            "price": 9.25,
            "timestamp": "2026-01-12T10:00:00",
            "quote_source": "tushare_realtime_quote",
        }

    monkeypatch.setattr(source, "_fetch_realtime_quote", slow_realtime)
    monkeypatch.setattr(
        source,
        "_fetch_daily_latest",
        lambda ts_code: {
            "price": 8.99,
            "timestamp": "2026-01-12",
            "quote_source": "tushare_daily",
            "previous_close": 9.25,
        },
    )

    result = source.fetch_latest(Symbol("600001"), AssetClass.STOCK)

    assert result is not None
    assert result["price"] == 8.99
    assert result["quote_source"] == "tushare_daily"
    assert result["provider_name"] == "tushare"
    assert result["provider_symbol"] == "600001.SH"
    assert result["symbol"] == "600001"


def test_tushare_default_realtime_timeout_waits_for_slow_valid_quote(monkeypatch):
    source = TushareSource(token="token-1234")

    def slow_realtime(ts_code):
        time.sleep(1.0)
        return {
            "price": 26.08,
            "timestamp": "2026-01-15T13:12:13",
            "quote_source": "tushare_realtime_quote",
            "display_name": "示例制造",
            "previous_close": 28.26,
        }

    monkeypatch.setattr(source, "_fetch_realtime_quote", slow_realtime)
    monkeypatch.setattr(
        source,
        "_fetch_daily_latest",
        lambda ts_code: {
            "price": 28.26,
            "timestamp": "2026-06-15",
            "quote_source": "tushare_daily",
            "previous_close": 28.85,
        },
    )

    result = source.fetch_latest(Symbol("600003"), AssetClass.STOCK)

    assert result is not None
    assert result["price"] == 26.08
    assert result["timestamp"] == "2026-01-15T13:12:13"
    assert result["quote_source"] == "tushare_realtime_quote"
    assert result["display_name"] == "示例制造"


def test_tushare_fetch_latest_fund_uses_fund_nav(monkeypatch):
    calls: dict[str, object] = {}

    class FakePro:
        def fund_nav(self, ts_code, start_date, end_date):
            calls["fund_nav"] = (ts_code, start_date, end_date)
            return pd.DataFrame(
                {
                    "ts_code": ["019999.OF", "019999.OF"],
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
        Symbol("019999"), AssetClass.FUND
    )

    assert result is not None
    assert result["price"] == 2.5123
    assert result["timestamp"] == "2026-06-04"
    assert result["quote_source"] == "tushare_fund_nav"
    assert result["provider_name"] == "tushare"
    assert result["provider_symbol"] == "019999.OF"
    assert result["symbol"] == "019999"
    assert result["asset_class"] == "fund"
    assert result["previous_close"] == 2.5
    assert result["previous_close_date"] == "2026-06-03"
    assert result["day_change_value"] == pytest.approx(0.0123)
    assert result["day_change_pct"] == pytest.approx(0.00492)
    assert calls["pro_api_token"] == "token-1234"
    assert calls["fund_nav"][0] == "019999.OF"


def test_tushare_fetch_latest_unsupported_asset_returns_none():
    assert (
        TushareSource(token="token-1234").fetch_latest(
            Symbol("Au99.99"), AssetClass.GOLD
        )
        is None
    )
