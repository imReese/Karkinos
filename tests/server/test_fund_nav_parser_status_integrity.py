from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from core.events import MarketEvent
from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from data.providers.akshare import AKShareSource
from server.contracts.http.market import ConfirmedFundNavRefreshRequest
from server.db import AppDatabase
from server.projections.quote_status import (
    quote_freshness_reason,
    quote_is_stale,
    quote_pricing_semantics,
    quote_valuation_status,
)
from server.projections.valuation_snapshot import select_authoritative_valuation_marks
from server.services.market.fund_nav import (
    normalize_fund_nav_snapshot,
    refresh_fund_nav_quotes,
)
from server.services.market.providers import load_provider_quote_payload
from server.services.market.quotes import (
    build_quote_ingestion_command,
    persist_quote_ingestion,
)
from server.services.market.refresh import refresh_one_quote
from server.services.market_views.confirmed_nav import refresh_confirmed_fund_nav

SH_TZ = ZoneInfo("Asia/Shanghai")


def _seed_prior_valid_official_nav(
    db: AppDatabase,
    *,
    symbol: str = "018125",
    nav_date: str = "2026-11-24",
    price: float = 2.05,
) -> None:
    cmd = build_quote_ingestion_command(
        symbol=symbol,
        asset_type="open_end_fund",
        snapshot={
            "price": price,
            "volume": None,
            "timestamp": f"{nav_date}T15:00:00+08:00",
        },
        quote_source="eastmoney_fund_page",
        provider_name="akshare",
        provider_status="live",
        quote_status="confirmed",
        captured_reason="fund_nav_sync",
        fetch_run_id=None,
        captured_at=f"{nav_date}T20:00:00+08:00",
        nav_date=nav_date,
    )
    persist_quote_ingestion(db, cmd)


def _state_with_akshare(db: AppDatabase, symbol: str) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            data_source="akshare",
            tushare_token="",
            assets=[
                {
                    "symbol": symbol,
                    "asset_class": "fund",
                    "instrument_type": "open_end_fund",
                }
            ],
            live_poll_interval=120,
        ),
        db=db,
        scheduler=None,
    )


def test_real_akshare_missing_source_date_never_uses_request_time_as_nav_date(
    monkeypatch,
    tmp_path: Path,
) -> None:
    db = AppDatabase(tmp_path.resolve() / "app.db")
    db.init_sync()
    symbol = "018125"
    _seed_prior_valid_official_nav(db, symbol=symbol, nav_date="2026-11-24", price=2.05)

    source = AKShareSource()
    request_time = datetime(2026, 11, 27, 10, 30, tzinfo=SH_TZ)

    # Only stub external upstream responses on the real AKShare parser.
    monkeypatch.setattr(
        "data.providers.akshare.eastmoney_upstream.fetch_eastmoney_fund_page",
        lambda **_kw: (
            'var fS_name = "测试基金";\nvar Data_netWorthTrend = [{"y": 2.11}];'
        ),
    )
    monkeypatch.setattr(
        "data.providers.akshare.sina_upstream.fetch_sina_fund_estimate",
        lambda **_kw: {},
    )
    monkeypatch.setattr(source, "_resolve_open_end_fund_code", lambda _sym: symbol)

    raw_latest = source.fetch_latest(Symbol(symbol), AssetClass.FUND)
    assert raw_latest is not None
    assert raw_latest["price"] == 2.11
    assert raw_latest["timestamp"] == ""
    assert raw_latest["quote_status"] == "stale"
    assert raw_latest["stale_reason"] == "missing_nav_date"
    assert "nav_date" not in raw_latest
    assert source.fetch_confirmed_fund_nav(Symbol(symbol)) is None

    monkeypatch.setattr(
        "server.services.market.providers._quote_sources",
        lambda **_kw: {"akshare": source},
    )
    monkeypatch.setattr(
        "server.services.market.fund_nav.build_sources",
        lambda **_kw: {"akshare": source},
    )

    state = _state_with_akshare(db, symbol)
    monkeypatch.setattr(
        "server.services.market.refresh.shanghai_now", lambda: request_time
    )

    # 1a. Normal refresh via refresh_one_quote fails closed and preserves prior NAV.
    async def _inline(fn, *args):
        return fn(*args)

    res_one = asyncio.run(refresh_one_quote(state, symbol, AssetClass.FUND))
    assert res_one.status == "failed"
    assert res_one.error == "missing_nav_date"
    assert res_one.using_persistent_cache is True
    assert res_one.last_refresh_error == "missing_nav_date"

    # 1b. Normal refresh via refresh_fund_nav_quotes (confirmation_only=False).
    res_sync = refresh_fund_nav_quotes(
        state.config,
        db,
        [(Symbol(symbol), InstrumentType.OPEN_END_FUND)],
        {},
        now=request_time,
        ttl_seconds=0,
        confirmation_only=False,
    )
    assert res_sync.refreshed == []
    assert symbol in res_sync.failed
    sync_run = db.get_quote_fetch_run(res_sync.run_id)
    assert sync_run is not None
    assert sync_run["started_at"] == request_time.isoformat()

    # 2. Dedicated confirmation entrypoint (both service & application view).
    res_confirmed = asyncio.run(
        refresh_confirmed_fund_nav(
            state,
            ConfirmedFundNavRefreshRequest(
                symbols=[symbol],
                target_date="2026-11-27",
                request_id="confirm-missing-date-20261127",
            ),
            run_blocking_fetch=_inline,
            shanghai_now=lambda: request_time,
        )
    )
    assert res_confirmed.status == "failed"
    assert res_confirmed.refreshed_symbols == []
    assert symbol in res_confirmed.failed_symbols

    # Request time NEVER leaked into nav_date; prior valid official NAV remains readable.
    latest = db.get_latest_quote_sync(symbol, asset_type="open_end_fund")
    assert latest is not None
    assert (latest["price"], latest["nav_date"], latest["quote_status"]) == (
        2.05,
        "2026-11-24",
        "confirmed",
    )
    facts = db.list_fund_quote_precedence_facts_sync(symbol)
    assert [(r["nav_date"], r["price"]) for r in facts["published_nav_rows"]] == [
        ("2026-11-24", 2.05)
    ]
    with sqlite3.connect(db.path) as conn:
        assert conn.execute(
            "SELECT trade_date, close_price, source FROM daily_close_snapshots_v2 WHERE symbol=?",
            (symbol,),
        ).fetchall() == [("2026-11-24", 2.05, "eastmoney_fund_page")]

    # Follow-up healthy NAV with real source timestamp publishes cleanly across normal & confirmed.
    ms_nov27 = int(datetime(2026, 11, 27, 0, 0, tzinfo=SH_TZ).timestamp() * 1000)
    monkeypatch.setattr(
        "data.providers.akshare.eastmoney_upstream.fetch_eastmoney_fund_page",
        lambda **_kw: (
            'var fS_name = "测试基金";\nvar Data_netWorthTrend = '
            + json.dumps([{"x": ms_nov27, "y": 2.15}])
            + ";"
        ),
    )
    res_ok = refresh_fund_nav_quotes(
        state.config,
        db,
        [(Symbol(symbol), InstrumentType.OPEN_END_FUND)],
        {},
        now=datetime(2026, 11, 27, 20, 30, tzinfo=SH_TZ),
        ttl_seconds=0,
        confirmation_only=False,
    )
    assert res_ok.refreshed == [symbol]
    latest_after = db.get_latest_quote_sync(symbol, asset_type="open_end_fund")
    assert latest_after is not None
    assert (
        latest_after["price"],
        latest_after["nav_date"],
        latest_after["quote_status"],
    ) == (
        2.15,
        "2026-11-27",
        "confirmed",
    )


@pytest.mark.parametrize(
    ("variant", "extra"),
    [
        ("estimated", {"quote_status": "estimated"}),
        (
            "provider-error",
            {"provider_status": "error", "stale_reason": "upstream_error"},
        ),
        (
            "stale-with-reason",
            {"quote_status": "stale", "stale_reason": "upstream_nav_delayed"},
        ),
    ],
)
def test_regular_source_explicit_statuses_are_never_coerced_to_confirmed_or_live(
    monkeypatch,
    tmp_path: Path,
    variant: str,
    extra: dict,
) -> None:
    db = _db_init(tmp_path)
    symbol = "018125"
    _seed_prior_valid_official_nav(db, symbol=symbol, nav_date="2026-11-24", price=2.05)
    now = datetime(2026, 11, 27, 14, 0, tzinfo=SH_TZ)

    snapshot_in = {
        "price": 2.11,
        "volume": None,
        "timestamp": "2026-11-27T14:00:00+08:00",
        "nav_date": "2026-11-27",
        "source": "akshare",
        "quote_source": "eastmoney_fund_page",
        "provider_name": "akshare",
        **extra,
    }
    normalized = normalize_fund_nav_snapshot(
        symbol=symbol,
        snapshot=dict(snapshot_in),
        source_name="akshare",
        now=now,
    )
    if variant == "estimated":
        assert normalized["quote_status"] == "estimated"
    elif variant == "provider-error":
        assert normalized["provider_status"] == "error"
        assert normalized["quote_status"] != "confirmed"
        assert normalized["stale_reason"] == "upstream_error"
    else:
        assert normalized["quote_status"] == "stale"
        assert normalized["stale_reason"] == "upstream_nav_delayed"

    class _RegularSource:
        def fetch_latest(self, _sym, _ac):
            return dict(snapshot_in)

    monkeypatch.setattr(
        "server.services.market.providers._quote_sources",
        lambda **_kw: {"akshare": _RegularSource()},
    )
    monkeypatch.setattr(
        "server.services.market.fund_nav.build_sources",
        lambda **_kw: {"akshare": _RegularSource()},
    )
    state = _state_with_akshare(db, symbol)

    def load_payload():
        return load_provider_quote_payload(
            state,
            symbol,
            AssetClass.FUND,
            fetch_with_timeout=lambda src, s, ac, **_kw: src.fetch_latest(s, ac),
            provider_timeout_seconds=1.0,
            index_timeout_seconds=1.0,
        )

    if variant == "provider-error":
        with pytest.raises(ValueError, match="upstream_error"):
            load_payload()
    else:
        payload = load_payload()
        assert payload is not None
        assert payload["quote_status"] == extra["quote_status"]
        assert payload["stale_reason"] == extra.get("stale_reason")

    confirmed = refresh_fund_nav_quotes(
        state.config,
        db,
        [(Symbol(symbol), InstrumentType.OPEN_END_FUND)],
        {},
        now=now,
        ttl_seconds=0,
        confirmation_only=True,
        target_date="2026-11-27",
    )
    assert confirmed.refreshed == [] and symbol in confirmed.failed

    # Prior valid official NAV remains readable through normal refresh paths too.
    res_sync = refresh_fund_nav_quotes(
        state.config,
        db,
        [(Symbol(symbol), InstrumentType.OPEN_END_FUND)],
        {},
        now=now,
        ttl_seconds=0,
        confirmation_only=False,
    )
    res_one = asyncio.run(refresh_one_quote(state, symbol, AssetClass.FUND))
    if variant == "provider-error":
        assert symbol in res_sync.failed
        assert res_one.status == "failed"
    else:
        assert res_one.status == "stale"

    facts = db.list_fund_quote_precedence_facts_sync(symbol)
    assert [(r["nav_date"], r["price"]) for r in facts["published_nav_rows"]] == [
        ("2026-11-24", 2.05)
    ]
    if variant == "stale-with-reason":
        current = db.get_latest_quote_sync(symbol, asset_type="open_end_fund")
        assert current["quote_status"] == "stale"
        assert quote_pricing_semantics(current)["pricing_authority"] != "authoritative"
        (mark,) = select_authoritative_valuation_marks(
            db.list_quote_selection_candidates_sync()
        )
        assert (mark["price"], mark["nav_date"]) == (2.05, "2026-11-24")
        assert mark["latest_observation"]["price"] == 2.11
        assert mark["latest_observation"]["pricing_authority"] != "authoritative"
    with sqlite3.connect(db.path) as conn:
        assert conn.execute(
            "SELECT trade_date, close_price, source FROM daily_close_snapshots_v2 WHERE symbol=?",
            (symbol,),
        ).fetchall() == [("2026-11-24", 2.05, "eastmoney_fund_page")]


def test_expired_historical_official_nav_keeps_original_date_and_staleness(
    monkeypatch, tmp_path: Path
) -> None:
    db = _db_init(tmp_path)
    symbol = "018125"
    _seed_prior_valid_official_nav(db, symbol=symbol, nav_date="2026-11-20", price=1.99)
    ms_nov20 = int(datetime(2026, 11, 20, 0, 0, tzinfo=SH_TZ).timestamp() * 1000)

    source = AKShareSource()
    monkeypatch.setattr(
        "data.providers.akshare.eastmoney_upstream.fetch_eastmoney_fund_page",
        lambda **_kw: (
            'var fS_name = "测试基金";\nvar Data_netWorthTrend = '
            + json.dumps([{"x": ms_nov20, "y": 1.99}])
            + ";"
        ),
    )
    monkeypatch.setattr(
        "data.providers.akshare.sina_upstream.fetch_sina_fund_estimate",
        lambda **_kw: {},
    )
    monkeypatch.setattr(source, "_resolve_open_end_fund_code", lambda _sym: symbol)
    monkeypatch.setattr(
        "server.services.market.fund_nav.build_sources",
        lambda **_kw: {"akshare": source},
    )

    later_now = datetime(2026, 11, 27, 10, 30, tzinfo=SH_TZ)
    refresh_fund_nav_quotes(
        SimpleNamespace(data_source="akshare", tushare_token=""),
        db,
        [(Symbol(symbol), InstrumentType.OPEN_END_FUND)],
        {},
        now=later_now,
        ttl_seconds=0,
        confirmation_only=False,
    )
    latest = db.get_latest_quote_sync(symbol, asset_type="open_end_fund")
    assert latest is not None
    assert latest["nav_date"] == "2026-11-20"
    assert latest["price"] == 1.99
    assert quote_is_stale(latest, now=later_now) is True
    assert quote_freshness_reason(latest, now=later_now) is not None


def _db_init(tmp_path: Path) -> AppDatabase:
    db = AppDatabase(tmp_path.resolve() / "app.db")
    db.init_sync()
    return db


def test_registered_nav_time_of_day_cannot_inherit_capture_date(monkeypatch) -> None:
    from server.scheduler.values import scheduler_quote_evidence

    now = datetime(2026, 11, 27, 10, 30, tzinfo=SH_TZ)
    raw = {"timestamp": "10:30:00", "quote_source": "eastmoney_fund_page", "price": 2.0}
    with pytest.raises(ValueError, match="missing_nav_date"):
        normalize_fund_nav_snapshot(
            symbol="018125", snapshot=raw, source_name="akshare", now=now
        )
    monkeypatch.setattr(
        "server.services.market.providers._quote_sources",
        lambda **_: {"akshare": object()},
    )
    with pytest.raises(ValueError, match="missing_nav_date"):
        load_provider_quote_payload(
            SimpleNamespace(config=SimpleNamespace(data_source="akshare")),
            "018125",
            AssetClass.FUND,
            fetch_with_timeout=lambda *args, **kwargs: raw,
            provider_timeout_seconds=1,
            index_timeout_seconds=1,
        )
    with pytest.raises(ValueError, match="missing_nav_date"):
        build_quote_ingestion_command(
            symbol="018125",
            asset_type="open_end_fund",
            snapshot=raw,
            quote_source="eastmoney_fund_page",
            provider_name="akshare",
            provider_status="live",
            quote_status="confirmed",
            captured_reason="refresh",
            fetch_run_id=None,
            captured_at=now.isoformat(),
        )
    price = Decimal("2.0")
    event = MarketEvent(
        timestamp=now,
        symbol=Symbol("018125"),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal(0),
        frequency=BarFrequency.DAILY,
        asset_class=AssetClass.FUND,
        instrument_type=InstrumentType.OPEN_END_FUND,
    )
    with pytest.raises(RuntimeError, match="fund NAV date missing"):
        scheduler_quote_evidence(event, raw, now=now, live_poll_interval=60)


def test_legacy_error_marked_confirmed_does_not_shadow_later_real_nav(tmp_path):
    db = _db_init(tmp_path)
    _seed_prior_valid_official_nav(db, nav_date="2026-11-24", price=2.05)
    db.save_quote_snapshot_sync(
        symbol="018125",
        asset_class="open_end_fund",
        timestamp="2026-11-27T13:00:00+08:00",
        price=2.30,
        volume=None,
        nav_date="2026-11-27",
        quote_source="eastmoney_fund_page",
        quote_status="confirmed",
        provider_status="error",
    )
    facts = db.list_fund_quote_precedence_facts_sync("018125")
    assert [(row["nav_date"], row["price"]) for row in facts["published_nav_rows"]] == [
        ("2026-11-24", 2.05)
    ]
    marks = select_authoritative_valuation_marks(
        db.list_quote_selection_candidates_sync()
    )
    assert len(marks) == 1
    assert quote_valuation_status(marks[0]) == "missing"
    assert quote_pricing_semantics(marks[0])["pricing_authority"] == "missing"
    _seed_prior_valid_official_nav(db, nav_date="2026-11-27", price=2.15)
    facts = db.list_fund_quote_precedence_facts_sync("018125")
    assert [(row["nav_date"], row["price"]) for row in facts["published_nav_rows"]] == [
        ("2026-11-27", 2.15)
    ]
