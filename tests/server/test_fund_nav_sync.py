from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import pytest

from core.types import AssetClass, InstrumentType, Symbol
from server.contracts.quote_ingestion import QuoteIngestionCommand
from server.db import AppDatabase
from server.services.market.fund_nav import refresh_fund_nav_quotes


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


class ConfirmedFundSource:
    def __init__(self) -> None:
        self.calls: list[tuple[Symbol, AssetClass]] = []

    def fetch_latest(self, symbol: Symbol, asset_class: AssetClass = AssetClass.STOCK):
        self.calls.append((symbol, asset_class))
        return {
            "price": 2.5,
            "timestamp": "2026-06-12T15:00:00+08:00",
            "source": "tushare",
            "quote_source": "tushare_fund_nav",
            "provider_name": "tushare",
            "provider_symbol": "019999.OF",
        }


def test_fund_nav_sync_requires_canonical_fund_identity(tmp_path) -> None:
    from server.services.market import fund_nav as fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    with pytest.raises(
        ValueError,
        match="canonical fund instrument type is required for 510300",
    ):
        fund_nav_sync.refresh_fund_nav_quotes(
            SimpleNamespace(data_source="akshare", tushare_token=""),
            db,
            watchlist=[(Symbol("510300"), AssetClass.FUND)],
            latest_quotes={},
        )


def test_fund_nav_sync_does_not_fetch_etf(monkeypatch, tmp_path) -> None:
    from server.services.market import fund_nav as fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: pytest.fail("ETF must not enter the open-end NAV lane"),
    )

    result = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="akshare", tushare_token=""),
        db,
        watchlist=[(Symbol("510300"), InstrumentType.ETF)],
        latest_quotes={},
    )

    assert result.refreshed == []
    assert result.failed == {}


def test_refresh_fund_nav_quotes_persists_only_fund_symbols(monkeypatch, tmp_path):
    from server.services.market import fund_nav as fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    source = FakeFundSource()
    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: {
            "akshare": source,
            "tushare": object(),
        },
    )
    result = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="tushare", tushare_token="unit-token"),
        db,
        watchlist=[
            (Symbol("019999"), InstrumentType.OPEN_END_FUND),
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
    assert json.loads(run["metadata_json"])["manual_explicit_trigger"] is False
    assert stock_latest is None


def test_refresh_fund_nav_quotes_skips_fresh_cached_fund(monkeypatch, tmp_path):
    from server.services.market import fund_nav as fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    source = FakeFundSource()
    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: {"akshare": source},
    )

    result = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="akshare", tushare_token=""),
        db,
        watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
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


def test_confirmation_only_skips_same_day_confirmed_nav_even_after_ttl(
    monkeypatch,
    tmp_path,
):
    from server.services.market import fund_nav as fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_latest_quote_sync(
        symbol="019999",
        asset_type="fund",
        price=2.5,
        quote_timestamp="2026-06-12T20:00:00+08:00",
        quote_source="tushare_fund_nav",
        provider_name="tushare",
        provider_status="live",
        quote_status="confirmed",
        nav_date="2026-06-12",
    )
    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: pytest.fail("confirmed same-day NAV must not be refetched"),
    )

    result = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="tushare", tushare_token=""),
        db,
        watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
        latest_quotes={
            "019999": {
                "price": 2.4,
                "timestamp": "2026-06-12T15:00:00+08:00",
                "quote_source": "eastmoney_fund_estimate",
            }
        },
        now=datetime(2026, 6, 12, 21, 30),
        ttl_seconds=900,
        confirmation_only=True,
    )

    assert result.refreshed == []
    assert result.skipped == ["019999"]
    assert result.failed == {}


def test_confirmation_only_refetches_target_date_nonconfirmed_nav_after_midnight(
    monkeypatch,
    tmp_path,
):
    from server.services.market import fund_nav as fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_latest_quote_sync(
        symbol="019999",
        asset_type="fund",
        price=2.4,
        quote_timestamp="2026-06-12T14:00:00+08:00",
        quote_source="tushare_fund_nav",
        provider_name="tushare",
        provider_status="error",
        quote_status="stale",
        stale_reason="provider_error",
        nav_date="2026-06-12",
    )
    source = ConfirmedFundSource()
    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: {"tushare": source},
    )

    result = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="tushare", tushare_token="unit-token"),
        db,
        watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
        latest_quotes={
            "019999": {
                "price": 2.4,
                "quote_source": "tushare_fund_nav",
                "provider_status": "live",
                "quote_status": "confirmed",
                "nav_date": "2026-06-12",
            }
        },
        now=datetime(2026, 6, 13, 0, 5),
        ttl_seconds=900,
        confirmation_only=True,
        target_date="2026-06-12",
    )

    latest = db.get_latest_quote_sync("019999", asset_type="fund")
    assert source.calls == [(Symbol("019999"), AssetClass.FUND)]
    assert result.refreshed == ["019999"]
    assert result.skipped == []
    assert latest is not None
    assert latest["price"] == 2.5
    assert latest["provider_status"] == "live"
    assert latest["quote_status"] == "confirmed"


def test_confirmation_only_falls_back_after_tushare_fund_nav_permission_error(
    monkeypatch,
    tmp_path,
):
    from server.services.market import fund_nav as fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    calls: list[tuple[str, str]] = []

    class PermissionDeniedTushare:
        def fetch_confirmed_fund_nav(self, symbol: Symbol):
            calls.append(("tushare", str(symbol)))
            raise RuntimeError("tushare_fund_nav_permission_denied")

    class PublicFundPage:
        def fetch_confirmed_fund_nav(self, symbol: Symbol):
            calls.append(("akshare", str(symbol)))
            return {
                "price": 2.5123,
                "timestamp": "2026-06-12T15:00:00+08:00",
                "nav_date": "2026-06-12",
                "source": "akshare",
                "quote_source": "eastmoney_fund_page",
                "provider_name": "akshare",
                "provider_symbol": str(symbol),
            }

    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: {
            "tushare": PermissionDeniedTushare(),
            "akshare": PublicFundPage(),
        },
    )

    result = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="tushare", tushare_token="unit-token"),
        db,
        watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
        latest_quotes={},
        now=datetime(2026, 6, 12, 21, 30),
        ttl_seconds=0,
        confirmation_only=True,
        target_date="2026-06-12",
    )

    latest = db.get_latest_quote_sync(
        "019999", asset_type=InstrumentType.OPEN_END_FUND.value
    )
    assert calls == [("tushare", "019999"), ("akshare", "019999")]
    assert result.refreshed == ["019999"]
    assert result.failed == {}
    assert latest is not None
    assert latest["quote_source"] == "eastmoney_fund_page"
    assert latest["nav_date"] == "2026-06-12"


def test_refresh_fund_nav_quotes_fetches_complete_batch_before_persisting(
    monkeypatch, tmp_path
):
    from server.services.market import fund_nav as fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    source = BatchInspectingFundSource(db)
    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: {"akshare": source},
    )

    result = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="akshare", tushare_token=""),
        db,
        watchlist=[
            (Symbol("019999"), InstrumentType.OPEN_END_FUND),
            (Symbol("019998"), InstrumentType.OPEN_END_FUND),
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


def test_confirmation_only_same_timestamp_authority_conflict_fails_closed(
    monkeypatch, tmp_path
):
    from server.services.market import fund_nav as fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="019999",
        asset_class="fund",
        price=2.5123,
        volume=None,
        timestamp="2026-06-12 15:00",
        quote_source="sina_fund_estimate",
        provider_name="sina",
        quote_status="live",
        captured_reason="live_poll",
        nav_date="2026-06-11",
    )
    estimate_source = FakeFundSource(
        {
            "price": 2.5123,
            "volume": None,
            "timestamp": "2026-06-12T15:00:00+08:00",
            "source": "sina",
            "quote_source": "sina_fund_estimate",
            "provider_name": "sina",
            "provider_symbol": "019999",
            "nav_date": "2026-06-11",
            "display_name": "示例成长混合C",
        }
    )
    confirmed_source = ConfirmedFundSource()
    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: {
            "akshare": estimate_source,
            "tushare": confirmed_source,
        },
    )
    request_id = "confirmed-nav-publication-failure-0001"

    result = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="tushare", tushare_token="unit-token"),
        db,
        watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
        latest_quotes={
            "019999": {
                "price": 2.5123,
                "timestamp": "2026-06-12 15:00",
                "quote_source": "sina_fund_estimate",
                "nav_date": "2026-06-11",
            }
        },
        now=datetime(2026, 6, 12, 21, 30),
        ttl_seconds=900,
        confirmation_only=True,
        request_id=request_id,
    )
    replay = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="tushare", tushare_token="unit-token"),
        db,
        watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
        latest_quotes={},
        now=datetime(2026, 6, 12, 21, 30),
        ttl_seconds=900,
        confirmation_only=True,
        request_id=request_id,
    )

    latest = db.get_latest_quote_sync("019999", asset_type="fund")
    restored = {row["symbol"]: row for row in db.get_latest_quotes_sync()}["019999"]
    assert result.refreshed == []
    assert result.failed["__publication__"] == "quote_batch_publication_failed"
    assert replay.idempotent_replay is True
    assert replay.refreshed == []
    assert replay.failed["__publication__"] == "quote_batch_publication_failed"
    assert confirmed_source.calls == [(Symbol("019999"), AssetClass.FUND)]
    assert estimate_source.calls == []
    assert latest is not None
    assert latest["quote_source"] == "sina_fund_estimate"
    assert latest["nav_date"] == "2026-06-11"
    assert restored["quote_source"] == "sina_fund_estimate"
    assert restored["nav_date"] == "2026-06-11"
    run = db.get_quote_fetch_run(result.run_id)
    assert run is not None and run["status"] == "failed"
    publication = db.get_runtime_control_sync("valuation_snapshot_publication")
    assert publication is not None
    assert publication["status"] == "failed"
    assert publication["quote_fetch_run_id"] == result.run_id
    assert publication["reason"] == "quote_batch_publication_failed"


def test_confirmation_only_rejects_intraday_estimate(monkeypatch, tmp_path):
    from server.services.market import fund_nav as fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    estimate_source = FakeFundSource()
    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: {"akshare": estimate_source},
    )

    result = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="akshare", tushare_token=""),
        db,
        watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
        latest_quotes={},
        now=datetime(2026, 6, 12, 21, 30),
        ttl_seconds=0,
        confirmation_only=True,
    )

    assert result.refreshed == []
    assert result.failed == {
        "019999": "fund source returned an unconfirmed NAV estimate"
    }
    assert db.get_latest_quote_sync("019999", asset_type="fund") is None


def test_confirmation_only_rejects_previous_day_confirmed_nav(monkeypatch, tmp_path):
    from server.services.market import fund_nav as fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    confirmed_source = ConfirmedFundSource()
    monkeypatch.setattr(
        confirmed_source,
        "fetch_latest",
        lambda symbol, asset_class=AssetClass.STOCK: {
            "price": 2.5,
            "timestamp": "2026-06-11T15:00:00+08:00",
            "source": "tushare",
            "quote_source": "tushare_fund_nav",
            "provider_name": "tushare",
            "provider_symbol": "019999.OF",
        },
    )
    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: {"tushare": confirmed_source},
    )

    result = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="tushare", tushare_token="unit-token"),
        db,
        watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
        latest_quotes={},
        now=datetime(2026, 6, 12, 21, 30),
        ttl_seconds=0,
        confirmation_only=True,
    )

    assert result.refreshed == []
    assert result.failed == {
        "019999": "confirmed fund NAV is not published for the target date"
    }
    assert db.get_latest_quote_sync("019999", asset_type="fund") is None


def test_confirmation_only_request_replays_persisted_run_after_restart(
    monkeypatch,
    tmp_path,
):
    from server.services.market import fund_nav as fund_nav_sync

    db_path = tmp_path / "app.db"
    db = AppDatabase(db_path)
    db.init_sync()
    source = ConfirmedFundSource()
    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: {"tushare": source},
    )
    request_id = "confirmed-nav-fixture-0001"
    kwargs = {
        "now": datetime(2026, 6, 12, 21, 30),
        "ttl_seconds": 0,
        "confirmation_only": True,
        "request_id": request_id,
    }

    first = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="tushare", tushare_token="unit-token"),
        db,
        watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
        latest_quotes={},
        **kwargs,
    )
    persisted = db.get_latest_quote_sync("019999", asset_type="fund")
    assert persisted is not None
    assert persisted["quote_status"] == "confirmed"
    assert fund_nav_sync.is_confirmed_fund_nav_quote(
        persisted,
        target_date="2026-06-12",
    )
    restarted_db = AppDatabase(db_path)
    restarted_db.init_sync()
    replay = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="tushare", tushare_token="unit-token"),
        restarted_db,
        watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
        latest_quotes={},
        **kwargs,
    )

    assert source.calls == [(Symbol("019999"), AssetClass.FUND)]
    assert first.run_id == f"fund_nav_sync:request:{request_id}"
    assert replay.run_id == first.run_id
    assert replay.request_id == request_id
    assert replay.idempotent_replay is True
    assert replay.refreshed == ["019999"]
    assert replay.failed == {}
    assert len(restarted_db.list_quote_fetch_runs(trigger="fund_nav_sync")) == 1
    assert len(restarted_db.get_recent_quote_snapshots_sync("019999", limit=10)) == 1


def test_confirmation_only_request_replays_running_run_without_provider_contact(
    monkeypatch,
    tmp_path,
):
    from server.services.market import fund_nav as fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    request_id = "confirmed-nav-running-0001"
    db.create_quote_fetch_run(
        run_id=f"fund_nav_sync:request:{request_id}",
        started_at="2026-06-12T21:30:00+08:00",
        trigger="fund_nav_sync",
        provider="deterministic_fixture",
        asset_type="fund",
        symbol_count=1,
        status="running",
        metadata={
            "request_id": request_id,
            "request_scope_symbols": ["019999"],
            "requested_symbols": ["019999"],
            "confirmation_only": True,
            "target_date": "2026-06-12",
        },
    )
    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: pytest.fail(
            "idempotent replay must not build or contact a provider"
        ),
    )

    replay = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="deterministic_fixture", tushare_token=""),
        db,
        watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
        latest_quotes={},
        now=datetime(2026, 6, 12, 21, 30),
        ttl_seconds=0,
        confirmation_only=True,
        request_id=request_id,
    )

    assert replay.idempotent_replay is True
    assert replay.run_id == f"fund_nav_sync:request:{request_id}"
    assert replay.refreshed == []
    assert replay.failed == {}
    assert len(db.list_quote_fetch_runs(trigger="fund_nav_sync")) == 1


def test_confirmation_only_request_rejects_idempotency_payload_drift(
    monkeypatch,
    tmp_path,
):
    from server.services.market import fund_nav as fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    source = ConfirmedFundSource()
    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: {"tushare": source},
    )
    request_id = "confirmed-nav-conflict-0001"
    config = SimpleNamespace(data_source="tushare", tushare_token="unit-token")
    fund_nav_sync.refresh_fund_nav_quotes(
        config,
        db,
        watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
        latest_quotes={},
        now=datetime(2026, 6, 12, 21, 30),
        ttl_seconds=0,
        confirmation_only=True,
        request_id=request_id,
    )

    with pytest.raises(fund_nav_sync.FundNavSyncIdempotencyConflict):
        fund_nav_sync.refresh_fund_nav_quotes(
            config,
            db,
            watchlist=[(Symbol("019998"), InstrumentType.OPEN_END_FUND)],
            latest_quotes={},
            now=datetime(2026, 6, 12, 21, 30),
            ttl_seconds=0,
            confirmation_only=True,
            request_id=request_id,
        )

    assert source.calls == [(Symbol("019999"), AssetClass.FUND)]
    assert len(db.list_quote_fetch_runs(trigger="fund_nav_sync")) == 1


def test_confirmation_only_request_rejects_target_date_drift(
    monkeypatch,
    tmp_path,
):
    from server.services.market import fund_nav as fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    source = ConfirmedFundSource()
    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: {"tushare": source},
    )
    request_id = "confirmed-nav-target-drift-0001"
    config = SimpleNamespace(data_source="tushare", tushare_token="unit-token")
    fund_nav_sync.refresh_fund_nav_quotes(
        config,
        db,
        watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
        latest_quotes={},
        now=datetime(2026, 6, 12, 21, 30),
        ttl_seconds=0,
        confirmation_only=True,
        target_date="2026-06-12",
        request_id=request_id,
    )

    with pytest.raises(fund_nav_sync.FundNavSyncIdempotencyConflict):
        fund_nav_sync.refresh_fund_nav_quotes(
            config,
            db,
            watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
            latest_quotes={},
            now=datetime(2026, 6, 13, 0, 5),
            ttl_seconds=0,
            confirmation_only=True,
            target_date="2026-06-11",
            request_id=request_id,
        )

    assert source.calls == [(Symbol("019999"), AssetClass.FUND)]
    assert len(db.list_quote_fetch_runs(trigger="fund_nav_sync")) == 1


def test_confirmation_only_duplicate_during_active_request_replays_running_run(
    monkeypatch,
    tmp_path,
):
    from server.services.market import fund_nav as fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    started = Event()
    release = Event()
    calls: list[str] = []

    class BlockingConfirmedSource:
        def fetch_latest(self, symbol, asset_class=AssetClass.STOCK):
            calls.append(str(symbol))
            started.set()
            assert release.wait(timeout=3)
            return {
                "price": 2.5,
                "timestamp": "2026-06-12T15:00:00+08:00",
                "quote_source": "tushare_fund_nav",
                "provider_name": "deterministic_fixture",
            }

    source = BlockingConfirmedSource()
    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: {"tushare": source},
    )
    request_id = "confirmed-nav-concurrent-0001"
    config = SimpleNamespace(data_source="tushare", tushare_token="unit-token")

    def run_once():
        return fund_nav_sync.refresh_fund_nav_quotes(
            config,
            db,
            watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
            latest_quotes={},
            now=datetime(2026, 6, 12, 21, 30),
            ttl_seconds=0,
            confirmation_only=True,
            request_id=request_id,
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        first_future = executor.submit(run_once)
        assert started.wait(timeout=3)
        replay = run_once()
        release.set()
        first = first_future.result(timeout=3)

    assert calls == ["019999"]
    assert replay.idempotent_replay is True
    assert replay.run_id == first.run_id
    assert replay.refreshed == []
    assert first.refreshed == ["019999"]
    assert len(db.list_quote_fetch_runs(trigger="fund_nav_sync")) == 1
    assert len(db.get_recent_quote_snapshots_sync("019999", limit=10)) == 1


def test_confirmation_only_failed_request_replays_exact_failure_without_refetch(
    monkeypatch,
    tmp_path,
):
    from server.services.market import fund_nav as fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    source = FakeFundSource()
    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: {"akshare": source},
    )
    request_id = "confirmed-nav-failed-0001"
    kwargs = {
        "now": datetime(2026, 6, 12, 21, 30),
        "ttl_seconds": 0,
        "confirmation_only": True,
        "request_id": request_id,
    }

    first = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="akshare", tushare_token=""),
        db,
        watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
        latest_quotes={},
        **kwargs,
    )
    replay = fund_nav_sync.refresh_fund_nav_quotes(
        SimpleNamespace(data_source="akshare", tushare_token=""),
        db,
        watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
        latest_quotes={},
        **kwargs,
    )

    expected_failure = {"019999": "fund source returned an unconfirmed NAV estimate"}
    assert source.calls == [(Symbol("019999"), AssetClass.FUND)]
    assert first.failed == expected_failure
    assert replay.failed == expected_failure
    assert replay.idempotent_replay is True
    assert replay.run_id == first.run_id
    assert len(db.list_quote_fetch_runs(trigger="fund_nav_sync")) == 1
    assert db.get_recent_quote_snapshots_sync("019999", limit=10) == []


def test_confirmation_only_concurrent_create_race_admits_one_provider_effect(
    monkeypatch,
    tmp_path,
):
    from server.services.market import fund_nav as fund_nav_sync

    base_db = AppDatabase(tmp_path / "app.db")
    base_db.init_sync()
    preflight_barrier = Barrier(2)
    preflight_lock = Lock()

    class PreflightRaceDatabase:
        def __init__(self):
            self.preflight_reads = 0

        def get_quote_fetch_run(self, run_id):
            with preflight_lock:
                is_preflight = self.preflight_reads < 2
                if is_preflight:
                    self.preflight_reads += 1
            if is_preflight:
                preflight_barrier.wait(timeout=3)
                return None
            return base_db.get_quote_fetch_run(run_id)

        def __getattr__(self, name):
            return getattr(base_db, name)

    db = PreflightRaceDatabase()
    source = ConfirmedFundSource()
    monkeypatch.setattr(
        fund_nav_sync,
        "_fund_nav_sources",
        lambda config: {"tushare": source},
    )
    request_id = "confirmed-nav-create-race-0001"
    config = SimpleNamespace(data_source="tushare", tushare_token="unit-token")

    def run_once():
        return fund_nav_sync.refresh_fund_nav_quotes(
            config,
            db,
            watchlist=[(Symbol("019999"), InstrumentType.OPEN_END_FUND)],
            latest_quotes={},
            now=datetime(2026, 6, 12, 21, 30),
            ttl_seconds=0,
            confirmation_only=True,
            request_id=request_id,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run_once(), range(2)))

    assert source.calls == [(Symbol("019999"), AssetClass.FUND)]
    assert sorted(result.idempotent_replay for result in results) == [False, True]
    assert len({result.run_id for result in results}) == 1
    assert len(base_db.list_quote_fetch_runs(trigger="fund_nav_sync")) == 1
    assert len(base_db.get_recent_quote_snapshots_sync("019999", limit=10)) == 1


def _seed_confirmed_fund_nav(
    db: AppDatabase,
    *,
    items: list[tuple[str, float, str, str]],
    run_id: str,
) -> None:
    db.create_quote_fetch_run(
        run_id=run_id,
        started_at="2026-11-25T15:05:00+08:00",
        trigger="fund_nav_sync",
        provider="akshare",
        asset_type="open_end_fund",
        symbol_count=len(items),
        status="running",
        metadata={
            "requested_symbols": [sym for sym, *_ in items],
            "instrument_types": ["open_end_fund"] * len(items),
        },
    )
    for symbol, price, ts, nav_date in items:
        db.persist_quote_ingestion_sync(
            QuoteIngestionCommand(
                symbol=symbol,
                asset_type="open_end_fund",
                price=price,
                volume=0.0,
                quote_timestamp=ts,
                captured_at="2026-11-25T15:05:05+08:00",
                quote_source="eastmoney_fund_page",
                provider_name="akshare",
                provider_status="live",
                quote_status="confirmed",
                captured_reason="fund_nav_sync",
                nav_date=nav_date,
                fetch_run_id=run_id,
            )
        )
    finished = db.finish_quote_fetch_run(
        run_id=run_id,
        finished_at="2026-11-25T15:05:06+08:00",
        status="success",
        success_count=len(items),
        failure_count=0,
        metadata={
            "requested_symbols": [sym for sym, *_ in items],
            "instrument_types": ["open_end_fund"] * len(items),
        },
    )
    assert finished is not None and finished["status"] == "success"


def test_late_sina_estimate_superseded_by_published_nav_for_018125_is_auditable_and_repeatable(
    monkeypatch, tmp_path
) -> None:
    db = AppDatabase(tmp_path / "fund_superseded_018125.db")
    db.init_sync()
    _seed_confirmed_fund_nav(
        db,
        items=[("018125", 1.8028, "2026-11-25T15:00:00+08:00", "2026-11-25")],
        run_id="seed-confirmed-018125",
    )

    class _SinaEstimateSource:
        def fetch_latest(self, symbol, asset_class):
            assert str(symbol) == "018125"
            return {
                "price": 1.8123,
                "volume": 0.0,
                "timestamp": "2026-11-25T15:00:00+08:00",
                "nav_date": "2026-11-25",
                "quote_source": "sina_fund_estimate",
                "provider_name": "sina",
                "source": "sina",
                "quote_status": "live",
                "provider_status": "live",
            }

    monkeypatch.setattr(
        "server.services.market.fund_nav.build_sources",
        lambda **_kwargs: {"akshare": _SinaEstimateSource()},
    )
    config = SimpleNamespace(data_source="akshare", tushare_token="")
    watchlist = [(Symbol("018125"), InstrumentType.OPEN_END_FUND)]
    now = datetime(2026, 11, 26, 9, 30, 16, tzinfo=timezone(timedelta(hours=8)))

    first = refresh_fund_nav_quotes(
        config,
        db,
        watchlist,
        {},
        now=now,
        ttl_seconds=0,
    )
    assert first.refreshed == []
    assert first.skipped == ["018125"]
    assert first.failed == {}
    assert first.quotes == {}
    assert (
        first.skipped_details["018125"]["disposition"] == "superseded_by_published_nav"
    )
    assert (
        first.skipped_details["018125"]["authoritative_quote_source"]
        == "eastmoney_fund_page"
    )
    assert first.skipped_details["018125"]["authoritative_price"] == 1.8028
    assert (
        first.skipped_details["018125"]["incoming_quote_source"] == "sina_fund_estimate"
    )
    assert first.skipped_details["018125"]["incoming_price"] == 1.8123

    latest = db.get_latest_quote_sync("018125", asset_type="open_end_fund")
    assert latest is not None
    assert latest["price"] == 1.8028
    assert latest["quote_source"] == "eastmoney_fund_page"

    run = db.get_quote_fetch_run(str(first.run_id))
    assert run is not None and run["status"] == "success"
    assert run["success_count"] == 0 and run["failure_count"] == 0
    meta = json.loads(run["metadata_json"])
    assert meta["superseded_symbols"] == ["018125"]
    assert meta["valuation_snapshot_publication"] == "not_required_superseded"
    assert (
        meta["skipped_details"]["018125"]["disposition"]
        == "superseded_by_published_nav"
    )

    from server.persistence.valuation_publication_recovery import (
        unresolved_publications,
    )

    with sqlite3.connect(db.path) as conn:
        assert unresolved_publications(conn) == []
        snapshot_count = conn.execute(
            "SELECT COUNT(*) FROM quote_snapshots WHERE symbol='018125'"
        ).fetchone()[0]
        completed = conn.execute(
            "SELECT payload_json FROM event_log WHERE event_type='task_run.completed' AND source_ref=?",
            (first.run_id,),
        ).fetchone()
        assert snapshot_count == 1
        assert completed is not None
        assert (
            json.loads(completed[0])["metadata"]["skipped_details"]["018125"][
                "disposition"
            ]
            == "superseded_by_published_nav"
        )

    # Repeatability: repeated execution without TTL still cleanly skips with zero new facts.
    second = refresh_fund_nav_quotes(
        config,
        db,
        watchlist,
        {},
        now=now + timedelta(minutes=1),
        ttl_seconds=0,
    )
    assert second.refreshed == []
    assert second.skipped == ["018125"]
    assert second.failed == {}
    assert (
        second.skipped_details["018125"]["disposition"] == "superseded_by_published_nav"
    )
    with sqlite3.connect(db.path) as conn:
        assert unresolved_publications(conn) == []
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM quote_snapshots WHERE symbol='018125'"
            ).fetchone()[0]
            == 1
        )

    # Idempotency with request_id replays identical skipped disposition without refetching.
    req_first = refresh_fund_nav_quotes(
        config,
        db,
        watchlist,
        {},
        now=now + timedelta(minutes=2),
        ttl_seconds=0,
        request_id="superseded-req-018125",
    )
    req_replay = refresh_fund_nav_quotes(
        config,
        db,
        watchlist,
        {},
        now=now + timedelta(minutes=3),
        ttl_seconds=0,
        request_id="superseded-req-018125",
    )
    assert req_replay.idempotent_replay is True
    assert req_replay.skipped == req_first.skipped == ["018125"]
    assert req_replay.skipped_details == req_first.skipped_details
    assert req_replay.failed == {}


def test_three_fund_nov26_all_superseded_and_mixed_batch_dispositions(
    monkeypatch, tmp_path
) -> None:
    db = AppDatabase(tmp_path / "fund_mixed_batch.db")
    db.init_sync()
    _seed_confirmed_fund_nav(
        db,
        items=[
            ("018125", 1.8028, "2026-11-25T15:00:00+08:00", "2026-11-25"),
            ("012710", 0.4090, "2026-11-25T15:00:00+08:00", "2026-11-25"),
            ("026539", 0.8711, "2026-11-25T15:00:00+08:00", "2026-11-25"),
        ],
        run_id="seed-confirmed-batch",
    )
    watchlist = [
        (Symbol("018125"), InstrumentType.OPEN_END_FUND),
        (Symbol("012710"), InstrumentType.OPEN_END_FUND),
        (Symbol("026539"), InstrumentType.OPEN_END_FUND),
    ]
    config = SimpleNamespace(data_source="akshare", tushare_token="")

    # Part A: exact 2026-11-26 09:30 three-symbol stale estimate pattern (15:00, 14:59, 16:00 on Nov 25).
    class _Nov26StaleSinaBatch:
        _payloads = {
            "018125": ("1.8123", "2026-11-25T15:00:00+08:00"),
            "012710": ("0.4097", "2026-11-25T14:59:00+08:00"),
            "026539": ("0.8784", "2026-11-25T16:00:00+08:00"),
        }

        def fetch_latest(self, symbol, asset_class):
            price_str, ts = self._payloads[str(symbol)]
            return {
                "price": float(price_str),
                "volume": 0.0,
                "timestamp": ts,
                "nav_date": "2026-11-25",
                "quote_source": "sina_fund_estimate",
                "provider_name": "sina",
                "source": "sina",
                "quote_status": "live",
                "provider_status": "live",
            }

    monkeypatch.setattr(
        "server.services.market.fund_nav.build_sources",
        lambda **_kwargs: {"akshare": _Nov26StaleSinaBatch()},
    )
    stale_batch = refresh_fund_nav_quotes(
        config,
        db,
        watchlist,
        {},
        now=datetime(2026, 11, 26, 9, 30, 16, tzinfo=timezone(timedelta(hours=8))),
        ttl_seconds=0,
    )
    assert stale_batch.refreshed == []
    assert stale_batch.skipped == ["018125", "012710", "026539"]
    assert stale_batch.failed == {}
    for sym in ("018125", "012710", "026539"):
        assert (
            stale_batch.skipped_details[sym]["disposition"]
            == "superseded_by_published_nav"
        )
        assert (
            db.get_latest_quote_sync(sym, asset_type="open_end_fund")["quote_source"]
            == "eastmoney_fund_page"
        )

    # Part B: 3-symbol mixed batch:
    # - 018125 receives superseded Nov 25 estimate
    # - 012710 receives valid Nov 26 intraday estimate
    # - 026539 receives new Nov 26 confirmed published NAV
    class _MixedBatchSource:
        def fetch_latest(self, symbol, asset_class):
            code = str(symbol)
            if code == "018125":
                return {
                    "price": 1.8123,
                    "volume": 0.0,
                    "timestamp": "2026-11-25T15:00:00+08:00",
                    "nav_date": "2026-11-25",
                    "quote_source": "sina_fund_estimate",
                    "provider_name": "sina",
                    "source": "sina",
                }
            if code == "012710":
                return {
                    "price": 0.4150,
                    "volume": 0.0,
                    "timestamp": "2026-11-26T10:30:00+08:00",
                    "nav_date": "2026-11-25",
                    "quote_source": "sina_fund_estimate",
                    "provider_name": "sina",
                    "source": "sina",
                }
            return {
                "price": 0.8885,
                "volume": 0.0,
                "timestamp": "2026-11-26T15:00:00+08:00",
                "nav_date": "2026-11-26",
                "quote_source": "eastmoney_fund_page",
                "provider_name": "eastmoney",
                "source": "eastmoney",
                "quote_status": "confirmed",
            }

    monkeypatch.setattr(
        "server.services.market.fund_nav.build_sources",
        lambda **_kwargs: {"akshare": _MixedBatchSource()},
    )
    mixed = refresh_fund_nav_quotes(
        config,
        db,
        watchlist,
        {},
        now=datetime(2026, 11, 26, 15, 5, 0, tzinfo=timezone(timedelta(hours=8))),
        ttl_seconds=0,
    )
    assert mixed.refreshed == ["012710", "026539"]
    assert mixed.skipped == ["018125"]
    assert mixed.failed == {}
    assert (
        mixed.skipped_details["018125"]["disposition"] == "superseded_by_published_nav"
    )

    q018125 = db.get_latest_quote_sync("018125", asset_type="open_end_fund")
    q012710 = db.get_latest_quote_sync("012710", asset_type="open_end_fund")
    q026539 = db.get_latest_quote_sync("026539", asset_type="open_end_fund")
    assert (
        q018125["price"] == 1.8028 and q018125["quote_source"] == "eastmoney_fund_page"
    )
    assert (
        q012710["price"] == 0.4150 and q012710["quote_source"] == "sina_fund_estimate"
    )
    assert (
        q026539["price"] == 0.8885 and q026539["quote_source"] == "eastmoney_fund_page"
    )

    mixed_run = db.get_quote_fetch_run(str(mixed.run_id))
    assert mixed_run is not None and mixed_run["status"] == "success"
    assert mixed_run["symbol_count"] == 3 and mixed_run["success_count"] == 2
    from server.persistence.valuation_publication_recovery import (
        unresolved_publications,
    )

    with sqlite3.connect(db.path) as conn:
        assert unresolved_publications(conn) == []


def test_confirmed_fund_nav_conflict_and_unresolvable_source_still_block(
    monkeypatch, tmp_path
) -> None:
    from server.persistence.valuation_publication_recovery import (
        unresolved_publications,
    )

    db = AppDatabase(tmp_path / "fund_conflicts.db")
    db.init_sync()
    _seed_confirmed_fund_nav(
        db,
        items=[("018125", 1.8028, "2026-11-25T15:00:00+08:00", "2026-11-25")],
        run_id="seed-confirmed-conflict",
    )
    config = SimpleNamespace(data_source="akshare", tushare_token="")
    watchlist = [(Symbol("018125"), InstrumentType.OPEN_END_FUND)]
    now = datetime(2026, 11, 26, 9, 30, 16, tzinfo=timezone(timedelta(hours=8)))

    # Case 1: Same-level confirmed NAV conflict (tushare_fund_nav differs on same nav_date).
    class _ConflictingConfirmedSource:
        def fetch_latest(self, symbol, asset_class):
            return {
                "price": 1.8500,
                "volume": 0.0,
                "timestamp": "2026-11-25T15:00:00+08:00",
                "nav_date": "2026-11-25",
                "quote_source": "tushare_fund_nav",
                "provider_name": "tushare",
                "source": "tushare",
                "quote_status": "confirmed",
            }

    monkeypatch.setattr(
        "server.services.market.fund_nav.build_sources",
        lambda **_kwargs: {"tushare": _ConflictingConfirmedSource()},
    )
    confirmed_conflict = refresh_fund_nav_quotes(
        config, db, watchlist, {}, now=now, ttl_seconds=0
    )
    assert confirmed_conflict.refreshed == []
    assert confirmed_conflict.skipped == []
    assert "__publication__" in confirmed_conflict.failed
    assert (
        db.get_latest_quote_sync("018125", asset_type="open_end_fund")["price"]
        == 1.8028
    )
    with sqlite3.connect(db.path) as conn:
        assert len(unresolved_publications(conn)) == 1

    # Case 1b: Same nav_date confirmed conflict at a different wall-clock timestamp also blocks.
    db_diff_ts = AppDatabase(tmp_path / "fund_conflict_same_date.db")
    db_diff_ts.init_sync()
    _seed_confirmed_fund_nav(
        db_diff_ts,
        items=[("018125", 1.8028, "2026-11-25T15:00:00+08:00", "2026-11-25")],
        run_id="seed-confirmed-diff-ts",
    )

    class _DiffTimestampConfirmedConflict:
        def fetch_latest(self, symbol, asset_class):
            return {
                "price": 1.8500,
                "volume": 0.0,
                "timestamp": "2026-11-25T15:05:00+08:00",
                "nav_date": "2026-11-25",
                "quote_source": "tushare_fund_nav",
                "provider_name": "tushare",
                "source": "tushare",
                "quote_status": "confirmed",
            }

    monkeypatch.setattr(
        "server.services.market.fund_nav.build_sources",
        lambda **_kwargs: {"tushare": _DiffTimestampConfirmedConflict()},
    )
    diff_ts_conflict = refresh_fund_nav_quotes(
        config, db_diff_ts, watchlist, {}, now=now, ttl_seconds=0
    )
    assert diff_ts_conflict.refreshed == []
    assert "__publication__" in diff_ts_conflict.failed
    assert (
        db_diff_ts.get_latest_quote_sync("018125", asset_type="open_end_fund")["price"]
        == 1.8028
    )
    with sqlite3.connect(db_diff_ts.path) as conn:
        assert len(unresolved_publications(conn)) == 1

    # Case 2: Unresolvable / ambiguous source cannot bypass blocking.
    db2 = AppDatabase(tmp_path / "fund_unresolvable.db")
    db2.init_sync()
    _seed_confirmed_fund_nav(
        db2,
        items=[("018125", 1.8028, "2026-11-25T15:00:00+08:00", "2026-11-25")],
        run_id="seed-confirmed-unresolvable",
    )

    class _UnresolvableSource:
        def fetch_latest(self, symbol, asset_class):
            return {
                "price": 1.8123,
                "volume": 0.0,
                "timestamp": "2026-11-25T16:00:00+08:00",
                "nav_date": "2026-11-25",
                "quote_source": "unrecognized_fund_feed",
                "provider_name": "custom",
                "source": "custom",
            }

    monkeypatch.setattr(
        "server.services.market.fund_nav.build_sources",
        lambda **_kwargs: {"akshare": _UnresolvableSource()},
    )
    unresolved = refresh_fund_nav_quotes(
        config, db2, watchlist, {}, now=now, ttl_seconds=0
    )
    assert unresolved.refreshed == []
    assert unresolved.skipped == []
    assert "__publication__" in unresolved.failed
    assert (
        db2.get_latest_quote_sync("018125", asset_type="open_end_fund")["price"]
        == 1.8028
    )
    with sqlite3.connect(db2.path) as conn:
        assert len(unresolved_publications(conn)) == 1
