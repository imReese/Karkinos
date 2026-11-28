"""Regression tests for consistent historical fund NAV evidence selection."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.types import InstrumentKey, InstrumentType
from server.contracts.quote_ingestion import QuoteIngestionCommand
from server.db import AppDatabase
from server.dependencies import AppState, AppStateContextMiddleware
from server.models import EquitySeriesPoint
from server.projections.portfolio_views.historical_ledger_series import (
    build_daily_equity_series_from_ledger_history,
    historical_quote_for_equity_day,
)
from server.projections.quote_status import (
    quote_pricing_semantics,
    quote_valuation_status,
)
from server.routes import portfolio as portfolio_routes

_SH = ZoneInfo("Asia/Shanghai")


def _seed_verified_calendar(db: AppDatabase, *, trading_dates: set[str]) -> None:
    days = []
    cur = date(2026, 1, 1)
    while cur.year == 2026:
        iso = cur.isoformat()
        is_trading = iso in trading_dates or (cur.weekday() < 5 and cur.month != 11)
        days.append(
            {
                "date": iso,
                "is_trading_day": is_trading,
                "day_type": "trading" if is_trading else "closed",
                "reason_code": "trading_day" if is_trading else "closed",
            }
        )
        cur += timedelta(days=1)
    fp = "a" * 64
    db.upsert_market_calendar_snapshot_sync(
        {
            "exchange": "SSE",
            "year": 2026,
            "provider": "fixture",
            "schema_version": "karkinos.market_calendar.v1",
            "status": "available",
            "trading_day_count": sum(1 for item in days if item["is_trading_day"]),
            "closed_day_count": sum(1 for item in days if not item["is_trading_day"]),
            "source_fingerprint": fp,
            "days": days,
            "limitations": [],
        }
    )
    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2026,
        source_fingerprint=fp,
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="b" * 64,
        verified_by="test",
    )


def _seed_fund_ledger(db: AppDatabase) -> None:
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-11-20T09:00:00+08:00",
        amount=10_000.0,
        asset_class="cash",
        source_ref="dep-1",
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-11-20T10:00:00+08:00",
        amount=1_753.30,
        symbol="018125",
        direction="buy",
        quantity=1_000.0,
        price=1.7533,
        asset_class="open_end_fund",
        source_ref="buy-018125",
    )


def _insert_quote(
    db: AppDatabase,
    *,
    symbol: str = "018125",
    price: float,
    timestamp: str,
    created_at: str,
    quote_source: str,
    quote_status: str | None,
    provider_status: str | None = "live",
    stale_reason: str | None = None,
    nav_date: str | None = None,
    captured_reason: str | None = None,
) -> None:
    instant_utc = (
        datetime.fromisoformat(timestamp).astimezone(ZoneInfo("UTC")).isoformat()
        if "T" in timestamp
        else f"{timestamp}T07:00:00.000000+00:00"
    )
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            """
            INSERT INTO quote_snapshots (
                symbol, asset_class, price, timestamp, quote_source,
                provider_name, quote_status, stale_reason, provider_status,
                captured_reason, nav_date, created_at, quote_instant_utc,
                instrument_type, identity_provenance
            ) VALUES (?, 'fund', ?, ?, ?, 'fixture', ?, ?, ?, ?, ?, ?, ?,
                      'open_end_fund', 'explicit_canonical')
            """,
            (
                symbol,
                price,
                timestamp,
                quote_source,
                quote_status,
                stale_reason,
                provider_status,
                captured_reason,
                nav_date,
                created_at,
                instant_utc,
            ),
        )
        conn.commit()


def _save_daily_close_with_capture(
    db: AppDatabase,
    *,
    symbol: str = "018125",
    trade_date: str,
    close_price: float,
    source: str,
    captured_at: str,
) -> None:
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            """
            INSERT INTO daily_close_snapshots_v2 (
                symbol, instrument_type, trade_date, close_price, source,
                captured_at, identity_provenance
            ) VALUES (?, 'open_end_fund', ?, ?, ?, ?, 'explicit_canonical')
            ON CONFLICT(symbol, instrument_type, trade_date) DO UPDATE SET
                close_price = excluded.close_price,
                source = excluded.source,
                captured_at = excluded.captured_at
            """,
            (symbol, trade_date, close_price, source, captured_at),
        )
        conn.commit()


def test_same_day_confirmed_published_nav_supersedes_reported_previous_close(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    trading_days = {
        "2026-11-20",
        "2026-11-23",
        "2026-11-24",
        "2026-11-25",
        "2026-11-26",
        "2026-11-27",
    }
    _seed_verified_calendar(db, trading_dates=trading_days)
    _seed_fund_ledger(db)

    nav_by_day = {
        "2026-11-20": 1.6485,
        "2026-11-23": 1.8551,
        "2026-11-24": 1.9423,
        "2026-11-25": 1.8028,
        "2026-11-26": 1.7533,
    }
    for index, (day, price) in enumerate(nav_by_day.items()):
        next_day = (
            list(nav_by_day.keys())[index + 1]
            if index + 1 < len(nav_by_day)
            else "2026-11-27"
        )
        _save_daily_close_with_capture(
            db,
            trade_date=day,
            close_price=price,
            source="reported_previous_close",
            captured_at=f"{next_day}T09:31:00+08:00",
        )
        _insert_quote(
            db,
            price=price,
            timestamp=f"{day}T15:00:00+08:00",
            created_at=f"{day}T21:30:00+08:00",
            quote_source="eastmoney_fund_page",
            quote_status="confirmed",
            provider_status="live",
            nav_date=day,
            captured_reason="fund_nav_sync",
        )
        # Daytime estimate carrying previous NAV date must not win over published NAV
        _insert_quote(
            db,
            price=round(price - 0.05, 4),
            timestamp=f"{next_day}T14:57:00+08:00",
            created_at=f"{next_day}T14:57:05+08:00",
            quote_source="sina_fund_estimate",
            quote_status="estimated",
            provider_status="live",
            stale_reason="confirmed_fund_nav_missing_estimate_only",
            nav_date=day,
            captured_reason="scheduler_poll",
        )

    matrix = db.get_historical_price_matrix_sync(
        instrument_keys=[InstrumentKey("018125", InstrumentType.OPEN_END_FUND)],
        start_date="2026-11-23",
        end_date="2026-11-26",
    )
    rows = {
        row["trade_date"]: row
        for row in matrix[InstrumentKey("018125", InstrumentType.OPEN_END_FUND)]
        if row["trade_date"] >= "2026-11-23"
    }
    assert sorted(rows) == ["2026-11-23", "2026-11-24", "2026-11-25", "2026-11-26"]
    for day, price in nav_by_day.items():
        if day < "2026-11-23":
            continue
        row = rows[day]
        assert row["source"] == "eastmoney_fund_page"
        assert row["nav_date"] == day
        assert row["quote_status"] == "confirmed"
        assert row["captured_at"] == f"{day}T21:30:00+08:00"
        assert row["price"] == pytest.approx(price)

    state = SimpleNamespace(db=db)
    for day, price in nav_by_day.items():
        if day < "2026-11-23":
            continue
        single = historical_quote_for_equity_day(
            state,
            symbol="018125",
            asset_class="open_end_fund",
            trade_date=date.fromisoformat(day),
            latest_quotes={},
            is_current_day=False,
        )
        assert single is not None
        assert (
            single.get("quote_source") or single.get("source")
        ) == "eastmoney_fund_page"
        assert single.get("nav_date") == day
        assert single.get("quote_status") == "confirmed"
        assert float(single["price"]) == pytest.approx(price)
        assert quote_valuation_status(single) == "complete"
        assert quote_pricing_semantics(single)["pricing_kind"] == "published_nav"

    series = build_daily_equity_series_from_ledger_history(
        state,
        selected_range="all",
        current_point=EquitySeriesPoint(
            timestamp="2026-11-27T15:00:00+08:00",
            total=10_000.0,
            cash=8_246.70,
            funds=1_753.30,
            stocks=0.0,
            others=0.0,
        ),
        now=datetime(2026, 11, 27, 15, 1, tzinfo=_SH),
    )
    by_date = {point.timestamp[:10]: point for point in series}
    for day in ("2026-11-23", "2026-11-24", "2026-11-25", "2026-11-26"):
        point = by_date[day]
        assert point.valuation_status == "reconstructed", (day, point)
        assert point.missing_price_symbols == []
        assert point.funds == pytest.approx(1_000.0 * nav_by_day[day])


@pytest.mark.parametrize(
    "bad_row",
    [
        # Poll timestamp is 2026-11-25 while declared NAV belongs to 2026-11-24.
        dict(
            price=1.9423,
            timestamp="2026-11-25T15:00:00+08:00",
            created_at="2026-11-25T15:46:00+08:00",
            quote_source="eastmoney_fund_page",
            quote_status="confirmed",
            provider_status="live",
            stale_reason=None,
            nav_date="2026-11-24",
        ),
        # Explicitly stale published NAV captured on 2026-11-25.
        dict(
            price=1.9423,
            timestamp="2026-11-25T15:00:00+08:00",
            created_at="2026-11-25T16:00:00+08:00",
            quote_source="eastmoney_fund_page",
            quote_status="stale",
            provider_status="stale",
            stale_reason="expired_prior_day_nav",
            nav_date="2026-11-25",
        ),
        # Provider status=error cannot become official NAV even with confirmed status.
        dict(
            price=1.9423,
            timestamp="2026-11-25T15:00:00+08:00",
            created_at="2026-11-25T16:00:00+08:00",
            quote_source="eastmoney_fund_page",
            quote_status="confirmed",
            provider_status="error",
            stale_reason=None,
            nav_date="2026-11-25",
        ),
        # Published source explicitly reporting estimated status cannot promote.
        dict(
            price=1.8050,
            timestamp="2026-11-25T15:00:00+08:00",
            created_at="2026-11-25T14:57:00+08:00",
            quote_source="eastmoney_fund_page",
            quote_status="estimated",
            provider_status="live",
            stale_reason=None,
            nav_date="2026-11-25",
        ),
        # Unverified legacy akshare row captured on 2026-11-25 without nav_date.
        dict(
            price=1.9423,
            timestamp="2026-11-25T14:05:16+08:00",
            created_at="2026-11-25T14:05:16+08:00",
            quote_source="akshare",
            quote_status="live",
            provider_status="live",
            stale_reason=None,
            nav_date=None,
        ),
    ],
)
def test_expired_wrong_date_or_stale_fund_quote_never_becomes_next_day_nav(
    tmp_path, bad_row: dict[str, object]
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_verified_calendar(
        db,
        trading_dates={"2026-11-20", "2026-11-23", "2026-11-24", "2026-11-25"},
    )
    _seed_fund_ledger(db)

    # Healthy confirmed 2026-11-24 NAV exists.
    _insert_quote(
        db,
        price=1.9423,
        timestamp="2026-11-24T15:00:00+08:00",
        created_at="2026-11-24T21:30:00+08:00",
        quote_source="eastmoney_fund_page",
        quote_status="confirmed",
        provider_status="live",
        nav_date="2026-11-24",
        captured_reason="fund_nav_sync",
    )
    # No 2026-11-25 official NAV exists; only the bad/expired observation on 25th.
    _insert_quote(db, **bad_row)  # type: ignore[arg-type]

    state = SimpleNamespace(db=db)
    nov24_single = historical_quote_for_equity_day(
        state,
        symbol="018125",
        asset_class="open_end_fund",
        trade_date=date(2026, 11, 24),
        latest_quotes={},
        is_current_day=False,
    )
    assert nov24_single is not None
    assert float(nov24_single["price"]) == pytest.approx(1.9423)
    assert quote_valuation_status(nov24_single) == "complete"

    nov25_single = historical_quote_for_equity_day(
        state,
        symbol="018125",
        asset_class="open_end_fund",
        trade_date=date(2026, 11, 25),
        latest_quotes={},
        is_current_day=False,
    )
    if nov25_single is not None:
        assert (
            quote_valuation_status(nov25_single, valuation_date="2026-11-25")
            != "complete"
        )
    assert (
        quote_pricing_semantics(bad_row, valuation_date="2026-11-25")["pricing_kind"]
        != "published_nav"
    )

    series = build_daily_equity_series_from_ledger_history(
        state,
        selected_range="all",
        current_point=EquitySeriesPoint(
            timestamp="2026-11-25T15:00:00+08:00",
            total=None,
            cash=8_246.70,
            funds=None,
            stocks=0.0,
            others=0.0,
            missing_price_symbols=["018125"],
        ),
        now=datetime(2026, 11, 25, 22, 0, tzinfo=_SH),
    )
    by_date = {point.timestamp[:10]: point for point in series}
    assert by_date["2026-11-24"].valuation_status == "reconstructed"
    assert by_date["2026-11-24"].funds == pytest.approx(1_942.30)
    assert by_date["2026-11-25"].valuation_status == "missing"
    assert by_date["2026-11-25"].funds is None
    assert by_date["2026-11-25"].total is None
    assert by_date["2026-11-25"].missing_price_symbols == ["018125"]


def test_unverified_close_and_estimate_stay_blocked_while_tushare_nav_supersedes(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_verified_calendar(
        db, trading_dates={"2026-11-20", "2026-11-25", "2026-11-26"}
    )
    _seed_fund_ledger(db)

    _save_daily_close_with_capture(
        db,
        trade_date="2026-11-25",
        close_price=1.8028,
        source="reported_previous_close",
        captured_at="2026-11-26T09:31:00+08:00",
    )
    _insert_quote(
        db,
        price=1.8123,
        timestamp="2026-11-25T14:57:00+08:00",
        created_at="2026-11-25T14:57:05+08:00",
        quote_source="sina_fund_estimate",
        quote_status="estimated",
        provider_status="live",
        stale_reason="confirmed_fund_nav_missing_estimate_only",
        nav_date="2026-11-24",
    )
    # Alternate verified publisher for 2026-11-26 coexisting with reported_previous_close.
    _save_daily_close_with_capture(
        db,
        trade_date="2026-11-26",
        close_price=1.7533,
        source="reported_previous_close",
        captured_at="2026-11-27T09:31:00+08:00",
    )
    _insert_quote(
        db,
        price=1.7533,
        timestamp="2026-11-26T15:00:00+08:00",
        created_at="2026-11-26T21:45:00+08:00",
        quote_source="tushare_fund_nav",
        quote_status="live",
        provider_status="live",
        nav_date="2026-11-26",
    )

    state = SimpleNamespace(db=db)
    nov25_single = historical_quote_for_equity_day(
        state,
        symbol="018125",
        asset_class="open_end_fund",
        trade_date=date(2026, 11, 25),
        latest_quotes={},
        is_current_day=False,
    )
    nov26_single = historical_quote_for_equity_day(
        state,
        symbol="018125",
        asset_class="open_end_fund",
        trade_date=date(2026, 11, 26),
        latest_quotes={},
        is_current_day=False,
    )
    assert nov25_single is None or quote_valuation_status(nov25_single) != "complete"
    assert nov26_single is not None
    assert (
        nov26_single.get("quote_source") or nov26_single.get("source")
    ) == "tushare_fund_nav"
    assert quote_valuation_status(nov26_single) == "complete"

    series = build_daily_equity_series_from_ledger_history(
        state,
        selected_range="all",
        current_point=EquitySeriesPoint(
            timestamp="2026-11-26T22:00:00+08:00",
            total=10_000.0,
            cash=8_246.70,
            funds=1_753.30,
            stocks=0.0,
            others=0.0,
        ),
        now=datetime(2026, 11, 26, 22, 0, tzinfo=_SH),
    )
    by_date = {point.timestamp[:10]: point for point in series}
    assert by_date["2026-11-25"].valuation_status == "missing"
    assert by_date["2026-11-25"].funds is None
    assert by_date["2026-11-26"].valuation_status == "reconstructed"
    assert by_date["2026-11-26"].funds == pytest.approx(1_753.30)


def test_historical_replay_respects_point_in_time_capture_cutoff(
    tmp_path, monkeypatch
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_verified_calendar(
        db,
        trading_dates={"2026-11-20", "2026-11-24", "2026-11-25", "2026-11-26"},
    )
    _seed_fund_ledger(db)

    # Captured on 2026-11-24 evening.
    _insert_quote(
        db,
        price=1.9423,
        timestamp="2026-11-24T15:00:00+08:00",
        created_at="2026-11-24T21:30:00+08:00",
        quote_source="eastmoney_fund_page",
        quote_status="confirmed",
        provider_status="live",
        nav_date="2026-11-24",
    )
    # Daytime 11-25 estimate captured at 14:30.
    _insert_quote(
        db,
        price=1.8123,
        timestamp="2026-11-25T14:30:00+08:00",
        created_at="2026-11-25T14:30:05+08:00",
        quote_source="sina_fund_estimate",
        quote_status="estimated",
        provider_status="live",
        stale_reason="confirmed_fund_nav_missing_estimate_only",
        nav_date="2026-11-24",
    )
    # Official 11-25 NAV is NOT captured until 21:30+08 on 11-25!
    _insert_quote(
        db,
        price=1.8028,
        timestamp="2026-11-25T15:00:00+08:00",
        created_at="2026-11-25T21:30:00+08:00",
        quote_source="eastmoney_fund_page",
        quote_status="confirmed",
        provider_status="live",
        nav_date="2026-11-25",
    )
    # A later daily_close written on 2026-11-26 must not leak back either.
    _save_daily_close_with_capture(
        db,
        trade_date="2026-11-25",
        close_price=1.8028,
        source="eastmoney_fund_page",
        captured_at="2026-11-26T09:30:00+08:00",
    )

    midday = datetime(2026, 11, 25, 16, 0, tzinfo=_SH)
    evening = datetime(2026, 11, 25, 22, 0, tzinfo=_SH)

    midday_matrix = db.get_historical_price_matrix_sync(
        instrument_keys=[InstrumentKey("018125", InstrumentType.OPEN_END_FUND)],
        start_date="2026-11-24",
        end_date="2026-11-25",
        as_of=midday,
    )
    midday_rows = {
        row["trade_date"]: row
        for row in midday_matrix[InstrumentKey("018125", InstrumentType.OPEN_END_FUND)]
    }
    assert midday_rows["2026-11-24"]["price"] == pytest.approx(1.9423)
    assert "2026-11-25" not in midday_rows

    state = SimpleNamespace(db=db)
    assert (
        historical_quote_for_equity_day(
            state,
            symbol="018125",
            asset_class="open_end_fund",
            trade_date=date(2026, 11, 25),
            latest_quotes={},
            is_current_day=False,
            as_of=midday,
        )
        is None
    )

    series_midday = build_daily_equity_series_from_ledger_history(
        state,
        selected_range="all",
        current_point=EquitySeriesPoint(
            timestamp=midday.isoformat(),
            total=None,
            cash=8_246.70,
            funds=None,
            stocks=0.0,
            others=0.0,
            missing_price_symbols=["018125"],
        ),
        now=midday,
        as_of=midday,
    )
    by_day_midday = {pt.timestamp[:10]: pt for pt in series_midday}
    assert by_day_midday["2026-11-24"].valuation_status == "reconstructed"
    assert by_day_midday["2026-11-25"].valuation_status == "missing"
    assert by_day_midday["2026-11-25"].missing_price_symbols == ["018125"]

    series_evening = build_daily_equity_series_from_ledger_history(
        state,
        selected_range="all",
        current_point=EquitySeriesPoint(
            timestamp=evening.isoformat(),
            total=10_049.50,
            cash=8_246.70,
            funds=1_802.80,
            stocks=0.0,
            others=0.0,
        ),
        now=evening,
        as_of=evening,
    )
    by_day_evening = {pt.timestamp[:10]: pt for pt in series_evening}
    assert by_day_evening["2026-11-25"].valuation_status == "reconstructed"
    assert by_day_evening["2026-11-25"].funds == pytest.approx(1_802.80)

    # Verify HTTP /api/portfolio/equity-curve/series uses published NAV over reported_previous_close
    http_root = tmp_path / "http"
    http_root.mkdir()
    http_db = AppDatabase(http_root / "app.db")
    http_db.init_sync()
    _seed_verified_calendar(
        http_db,
        trading_dates={"2026-11-20", "2026-11-24", "2026-11-25"},
    )
    _seed_fund_ledger(http_db)
    for day, price in (("2026-11-24", 1.9423), ("2026-11-25", 1.8028)):
        _save_daily_close_with_capture(
            http_db,
            trade_date=day,
            close_price=price,
            source="reported_previous_close",
            captured_at=f"{day}T22:00:00+08:00",
        )
        run_id = f"fund_nav_sync:{day}"
        http_db.create_quote_fetch_run(
            run_id=run_id,
            started_at=f"{day}T21:30:00+08:00",
            trigger="fund_nav_sync",
            provider="akshare",
            asset_type="open_end_fund",
            symbol_count=1,
            status="running",
            metadata={
                "requested_symbols": ["018125"],
                "instrument_types": ["open_end_fund"],
            },
        )
        http_db.persist_quote_ingestion_sync(
            QuoteIngestionCommand(
                symbol="018125",
                asset_type="open_end_fund",
                price=price,
                volume=0.0,
                quote_timestamp=f"{day}T15:00:00+08:00",
                captured_at=f"{day}T21:30:00+08:00",
                quote_source="eastmoney_fund_page",
                provider_name="akshare",
                provider_status="live",
                quote_status="confirmed",
                captured_reason="fund_nav_sync",
                nav_date=day,
                fetch_run_id=run_id,
            )
        )
        http_db.finish_quote_fetch_run(
            run_id=run_id,
            finished_at=f"{day}T21:30:01+08:00",
            status="success",
            success_count=1,
            failure_count=0,
            metadata={
                "requested_symbols": ["018125"],
                "instrument_types": ["open_end_fund"],
            },
        )

    http_db.publish_current_valuation_snapshot_sync(now=evening)
    monkeypatch.setattr(portfolio_routes, "get_shanghai_now", lambda: evening)
    app_state = AppState()
    app_state.db = http_db
    app = FastAPI()
    app.add_middleware(AppStateContextMiddleware, app_state=app_state)
    app.include_router(portfolio_routes.create_router())
    with TestClient(app) as client:
        resp = client.get("/api/portfolio/equity-curve/series?range=all")
        assert resp.status_code == 200
        http_points = {pt["timestamp"][:10]: pt for pt in resp.json()}
        assert http_points["2026-11-24"]["valuation_status"] == "reconstructed"
        assert http_points["2026-11-24"]["funds"] == pytest.approx(1_942.30)
        assert http_points["2026-11-25"]["valuation_status"] == "complete"
        assert http_points["2026-11-25"]["funds"] == pytest.approx(1_802.80)
