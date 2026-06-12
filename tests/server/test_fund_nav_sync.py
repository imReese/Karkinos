from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from core.types import AssetClass, Symbol
from server.db import AppDatabase


class FakeFundSource:
    def __init__(self, snapshot: dict | None = None) -> None:
        self.snapshot = snapshot or {
            "price": 2.2527,
            "volume": None,
            "timestamp": "2026-06-12 15:00",
            "source": "eastmoney_fund_estimate",
            "quote_source": "eastmoney_fund_estimate",
            "provider_name": "akshare",
            "provider_symbol": "018125",
            "nav_date": "2026-06-12",
            "display_name": "永赢先进制造智选混合C",
        }
        self.calls: list[tuple[Symbol, AssetClass]] = []

    def fetch_latest(self, symbol: Symbol, asset_class: AssetClass = AssetClass.STOCK):
        self.calls.append((symbol, asset_class))
        return dict(self.snapshot)


def test_refresh_fund_nav_quotes_persists_only_fund_symbols(monkeypatch, tmp_path):
    from server.services import fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    source = FakeFundSource()
    monkeypatch.setattr(
        fund_nav_sync,
        "build_sources",
        lambda data_source, tushare_token: {
            "akshare": source,
            "tushare": object(),
        },
    )

    result = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="tushare", tushare_token="unit-token"),
        db,
        watchlist=[
            (Symbol("018125"), AssetClass.FUND),
            (Symbol("603659"), AssetClass.STOCK),
        ],
        latest_quotes={},
        now=datetime(2026, 6, 12, 15, 5),
        ttl_seconds=900,
    )

    latest = db.get_latest_quote_sync("018125", asset_type="fund")
    stock_latest = db.get_latest_quote_sync("603659", asset_type="stock")

    assert result.refreshed == ["018125"]
    assert result.skipped == []
    assert result.failed == {}
    assert source.calls == [(Symbol("018125"), AssetClass.FUND)]
    assert latest is not None
    assert latest["price"] == 2.2527
    assert latest["quote_source"] == "eastmoney_fund_estimate"
    assert latest["provider_name"] == "akshare"
    assert latest["provider_status"] == "live"
    assert latest["quote_status"] == "live"
    assert latest["captured_reason"] == "fund_nav_sync"
    assert latest["nav_date"] == "2026-06-12"
    assert stock_latest is None


def test_refresh_fund_nav_quotes_skips_fresh_cached_fund(monkeypatch, tmp_path):
    from server.services import fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    source = FakeFundSource()
    monkeypatch.setattr(
        fund_nav_sync,
        "build_sources",
        lambda data_source, tushare_token: {"akshare": source},
    )

    result = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="akshare", tushare_token=""),
        db,
        watchlist=[(Symbol("018125"), AssetClass.FUND)],
        latest_quotes={
            "018125": {
                "price": 2.20,
                "timestamp": "2026-06-12T15:04:00",
                "asset_class": "fund",
                "quote_source": "eastmoney_fund_estimate",
            }
        },
        now=datetime(2026, 6, 12, 15, 5),
        ttl_seconds=900,
    )

    assert result.refreshed == []
    assert result.skipped == ["018125"]
    assert result.failed == {}
    assert source.calls == []
    assert db.get_latest_quote_sync("018125", asset_type="fund") is None
