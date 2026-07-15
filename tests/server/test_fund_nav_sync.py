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
            "provider_symbol": "019999",
            "nav_date": "2026-06-12",
            "display_name": "示例成长混合C",
        }
        self.calls: list[tuple[Symbol, AssetClass]] = []

    def fetch_latest(self, symbol: Symbol, asset_class: AssetClass = AssetClass.STOCK):
        self.calls.append((symbol, asset_class))
        return dict(self.snapshot)


class BatchInspectingFundSource:
    def __init__(self, db: AppDatabase) -> None:
        self.db = db
        self.calls: list[str] = []

    def fetch_latest(self, symbol: Symbol, asset_class: AssetClass = AssetClass.STOCK):
        value = str(symbol)
        self.calls.append(value)
        assert self.db.get_latest_quote_sync(value, asset_type="fund") is None
        if value == "019998":
            assert self.db.get_latest_quote_sync("019999", asset_type="fund") is None
        return {
            "price": 2.0 if value == "019999" else 3.0,
            "timestamp": "2026-06-12 15:00",
            "source": "deterministic_fixture",
            "quote_source": "deterministic_fixture",
            "provider_name": "fixture",
            "nav_date": "2026-06-12",
        }


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
            (Symbol("019999"), AssetClass.FUND),
            (Symbol("600002"), AssetClass.STOCK),
        ],
        latest_quotes={},
        now=datetime(2026, 6, 12, 15, 5),
        ttl_seconds=900,
    )

    latest = db.get_latest_quote_sync("019999", asset_type="fund")
    stock_latest = db.get_latest_quote_sync("600002", asset_type="stock")

    assert result.refreshed == ["019999"]
    assert result.skipped == []
    assert result.failed == {}
    assert source.calls == [(Symbol("019999"), AssetClass.FUND)]
    assert latest is not None
    assert latest["price"] == 2.2527
    assert latest["quote_source"] == "eastmoney_fund_estimate"
    assert latest["provider_name"] == "akshare"
    assert latest["provider_status"] == "live"
    assert latest["quote_status"] == "live"
    assert latest["captured_reason"] == "fund_nav_sync"
    assert latest["nav_date"] == "2026-06-12"
    assert result.run_id is not None
    assert latest["fetch_run_id"] == result.run_id
    snapshots = db.get_recent_quote_snapshots_sync("019999", limit=10)
    assert snapshots[0]["fetch_run_id"] == result.run_id
    run = db.list_quote_fetch_runs(trigger="fund_nav_sync")[0]
    assert run["run_id"] == result.run_id
    assert run["status"] == "success"
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
        watchlist=[(Symbol("019999"), AssetClass.FUND)],
        latest_quotes={
            "019999": {
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
    assert result.skipped == ["019999"]
    assert result.failed == {}
    assert source.calls == []
    assert db.get_latest_quote_sync("019999", asset_type="fund") is None


def test_refresh_fund_nav_quotes_fetches_complete_batch_before_persisting(
    monkeypatch, tmp_path
):
    from server.services import fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    source = BatchInspectingFundSource(db)
    monkeypatch.setattr(
        fund_nav_sync,
        "build_sources",
        lambda data_source, tushare_token: {"akshare": source},
    )

    result = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="akshare", tushare_token=""),
        db,
        watchlist=[
            (Symbol("019999"), AssetClass.FUND),
            (Symbol("019998"), AssetClass.FUND),
        ],
        latest_quotes={},
        now=datetime(2026, 6, 12, 15, 5),
        ttl_seconds=0,
    )

    assert source.calls == ["019999", "019998"]
    assert result.refreshed == ["019999", "019998"]
    assert db.get_latest_quote_sync("019999", asset_type="fund") is not None
    assert db.get_latest_quote_sync("019998", asset_type="fund") is not None
    publication = db.get_runtime_control_sync("valuation_snapshot_publication")
    assert publication["status"] == "ready"
