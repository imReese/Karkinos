"""Regression tests for point-in-time filtering before SQL ordering/LIMIT."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from core.types import InstrumentKey, InstrumentType
from server.db import AppDatabase

_SH = ZoneInfo("Asia/Shanghai")


def _insert_quote_row(
    db: AppDatabase,
    *,
    symbol: str,
    asset_class: str,
    instrument_type: str,
    price: float,
    timestamp: str,
    created_at: str,
    quote_source: str,
    quote_status: str = "live",
    provider_status: str = "live",
    stale_reason: str | None = None,
    nav_date: str | None = None,
    quote_instant_utc: str | None = None,
) -> None:
    if quote_instant_utc is None:
        parsed = datetime.fromisoformat(timestamp)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_SH)
        instant_utc = parsed.astimezone(ZoneInfo("UTC")).isoformat(
            timespec="microseconds"
        )
    else:
        instant_utc = quote_instant_utc
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            """
            INSERT INTO quote_snapshots (
                symbol, asset_class, price, timestamp, quote_source,
                provider_name, quote_status, stale_reason, provider_status,
                captured_reason, nav_date, created_at, quote_instant_utc,
                instrument_type, identity_provenance
            ) VALUES (?, ?, ?, ?, ?, 'fixture', ?, ?, ?, 'regression', ?, ?, ?, ?, 'explicit_canonical')
            """,
            (
                symbol,
                asset_class,
                price,
                timestamp,
                quote_source,
                quote_status,
                stale_reason,
                provider_status,
                nav_date,
                created_at,
                instant_utc,
                instrument_type,
            ),
        )
        conn.commit()


def test_as_of_quote_lookup_remains_consistent_after_many_post_cutoff_quotes(
    tmp_path,
) -> None:
    """Appending >=32 quotes after as_of must never hide quotes visible at as_of."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    # Same symbol across two instrument types must stay isolated.
    _insert_quote_row(
        db,
        symbol="601985",
        asset_class="fund",
        instrument_type="open_end_fund",
        price=1.2345,
        timestamp="2026-11-26T15:00:00+08:00",
        created_at="2026-11-26T21:30:00+08:00",
        quote_source="eastmoney_fund_page",
        quote_status="confirmed",
        nav_date="2026-11-26",
    )
    _insert_quote_row(
        db,
        symbol="601985",
        asset_class="stock",
        instrument_type="stock",
        price=9.82,
        timestamp="2026-11-27T09:43:26+08:00",
        created_at="2026-11-27T01:43:30.000000+00:00",
        quote_source="tencent_realtime_quote",
    )
    _insert_quote_row(
        db,
        symbol="601985",
        asset_class="stock",
        instrument_type="stock",
        price=9.83,
        timestamp="2026-11-27T09:44:26+08:00",
        created_at="2026-11-27T01:44:31.172079+00:00",
        quote_source="tencent_realtime_quote",
    )

    as_of = datetime(2026, 11, 27, 9, 45, 0, tzinfo=_SH)
    baseline = db.get_latest_quote_before_date_sync(
        "601985", "2026-11-28", instrument_type="stock", as_of=as_of
    )
    assert baseline is not None
    assert baseline["price"] == pytest.approx(9.83)
    assert baseline["instrument_type"] == "stock"

    # Append 40 later polls and close on the same trading day (> SQL LIMIT 32).
    for step in range(40):
        ts = datetime(2026, 11, 27, 9, 46, 0, tzinfo=_SH) + timedelta(minutes=step)
        _insert_quote_row(
            db,
            symbol="601985",
            asset_class="stock",
            instrument_type="stock",
            price=9.84 + step * 0.01,
            timestamp=ts.isoformat(),
            created_at=(ts + timedelta(seconds=3))
            .astimezone(ZoneInfo("UTC"))
            .isoformat(),
            quote_source="tencent_realtime_quote",
        )
    _insert_quote_row(
        db,
        symbol="601985",
        asset_class="stock",
        instrument_type="stock",
        price=9.89,
        timestamp="2026-11-27T15:00:00+08:00",
        created_at="2026-11-27T08:02:07.062825+00:00",
        quote_source="market_bar_close",
        quote_status="confirmed",
        provider_status="persisted_verified",
    )

    replayed = db.get_latest_quote_before_date_sync(
        "601985", "2026-11-28", instrument_type="stock", as_of=as_of
    )
    assert replayed is not None
    assert replayed["price"] == pytest.approx(baseline["price"])
    assert replayed["timestamp"] == baseline["timestamp"]
    assert replayed["created_at"] == baseline["created_at"]
    assert replayed["instrument_type"] == "stock"


def test_as_of_exact_boundary_and_subsecond_isolation(tmp_path) -> None:
    """Quotes equal to as_of are visible; quotes even microseconds later never hide them."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    cutoff = datetime(2026, 11, 27, 9, 45, 0, 500_000, tzinfo=_SH)
    _insert_quote_row(
        db,
        symbol="603659",
        asset_class="stock",
        instrument_type="stock",
        price=17.03,
        timestamp=cutoff.isoformat(),
        created_at=cutoff.astimezone(ZoneInfo("UTC")).isoformat(
            timespec="microseconds"
        ),
        quote_source="tencent_realtime_quote",
    )
    # Append 40 rows captured within the exact same second / right after cutoff.
    for offset in range(1, 41):
        later = cutoff + timedelta(microseconds=offset * 10_000)
        _insert_quote_row(
            db,
            symbol="603659",
            asset_class="stock",
            instrument_type="stock",
            price=17.50 + offset * 0.01,
            timestamp=later.isoformat(),
            created_at=later.astimezone(ZoneInfo("UTC")).isoformat(
                timespec="microseconds"
            ),
            quote_source="tencent_realtime_quote",
        )

    exact = db.get_latest_quote_before_date_sync(
        "603659", "2026-11-28", instrument_type="stock", as_of=cutoff
    )
    assert exact is not None
    assert exact["price"] == pytest.approx(17.03)

    before_exact = db.get_latest_quote_before_date_sync(
        "603659",
        "2026-11-28",
        instrument_type="stock",
        as_of=cutoff - timedelta(microseconds=1),
    )
    assert before_exact is None


def test_as_of_handles_historical_timezone_naive_timestamps(tmp_path) -> None:
    """Historical naive created_at/timestamp strings use Asia/Shanghai wall clock."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    # Historical pre-cutoff naive timestamp (09:44:30+08 = 01:44:30Z) and exact boundary (09:45:00+08)
    _insert_quote_row(
        db,
        symbol="601985",
        asset_class="stock",
        instrument_type="stock",
        price=9.44,
        timestamp="2026-08-27T09:44:30",
        created_at="2026-08-27T09:44:30.516322",
        quote_source="tencent_realtime_quote",
    )
    _insert_quote_row(
        db,
        symbol="601985",
        asset_class="stock",
        instrument_type="stock",
        price=9.45,
        timestamp="2026-08-27T09:45:00",
        created_at="2026-08-27T09:45:00",
        quote_source="tencent_realtime_quote",
    )
    # 40 naive post-cutoff quotes on the same morning (09:46..10:25 Shanghai time)
    for step in range(1, 41):
        naive_ts = (datetime(2026, 8, 27, 9, 45, 0) + timedelta(minutes=step)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        _insert_quote_row(
            db,
            symbol="601985",
            asset_class="stock",
            instrument_type="stock",
            price=9.50 + step * 0.01,
            timestamp=naive_ts,
            created_at=naive_ts,
            quote_source="tencent_realtime_quote",
        )

    for as_of in (
        datetime(2026, 8, 27, 9, 45, 0, tzinfo=_SH),
        datetime(2026, 8, 27, 1, 45, 0, tzinfo=ZoneInfo("UTC")),
        "2026-08-27T09:45:00",
    ):
        found = db.get_latest_quote_before_date_sync(
            "601985", "2026-08-28", instrument_type="stock", as_of=as_of
        )
        assert found is not None, as_of
        assert found["price"] == pytest.approx(9.45)

    earlier = db.get_latest_quote_before_date_sync(
        "601985",
        "2026-08-28",
        instrument_type="stock",
        as_of=datetime(2026, 8, 27, 9, 44, 59, tzinfo=_SH),
    )
    assert earlier is not None
    assert earlier["price"] == pytest.approx(9.44)

    # Historical matrix with aware as_of must agree on naive Shanghai created_at rows.
    matrix = db.get_historical_price_matrix_sync(
        instrument_keys=[InstrumentKey("601985", InstrumentType.STOCK)],
        start_date="2026-08-27",
        end_date="2026-08-27",
        as_of=datetime(2026, 8, 27, 9, 45, 0, tzinfo=_SH),
    )
    rows = matrix[InstrumentKey("601985", InstrumentType.STOCK)]
    assert len(rows) == 1
    assert rows[0]["price"] == pytest.approx(9.45)


def test_as_of_fund_lookup_preserves_nav_date_and_source_authority(tmp_path) -> None:
    """Published NAV wins over >32 later estimates; post-cutoff NAV never leaks."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    _insert_quote_row(
        db,
        symbol="018125",
        asset_class="fund",
        instrument_type="open_end_fund",
        price=1.8028,
        timestamp="2026-11-25T15:00:00+08:00",
        created_at="2026-11-25T21:30:00+08:00",
        quote_source="eastmoney_fund_page",
        quote_status="confirmed",
        nav_date="2026-11-25",
    )
    # 35 estimates before as_of on 2026-11-26 (stale/estimated) plus future NAV after as_of.
    for step in range(35):
        ts = datetime(2026, 11, 26, 10, 0, 0, tzinfo=_SH) + timedelta(minutes=step)
        _insert_quote_row(
            db,
            symbol="018125",
            asset_class="fund",
            instrument_type="open_end_fund",
            price=1.78 + step * 0.001,
            timestamp=ts.isoformat(),
            created_at=ts.astimezone(ZoneInfo("UTC")).isoformat(),
            quote_source="sina_fund_estimate",
            quote_status="estimated",
            stale_reason="confirmed_fund_nav_missing_estimate_only",
            nav_date="2026-11-25",
        )
    # Post-cutoff 2026-11-26 published NAV plus >=35 post-cutoff published NAVs & estimates (> LIMIT 32)
    _insert_quote_row(
        db,
        symbol="018125",
        asset_class="fund",
        instrument_type="open_end_fund",
        price=1.7533,
        timestamp="2026-11-26T15:00:00+08:00",
        created_at="2026-11-26T21:30:00+08:00",
        quote_source="eastmoney_fund_page",
        quote_status="confirmed",
        nav_date="2026-11-26",
    )
    for step in range(1, 36):
        later_nav_dt = datetime(2026, 11, 26, 21, 31, 0, tzinfo=_SH) + timedelta(
            minutes=step
        )
        _insert_quote_row(
            db,
            symbol="018125",
            asset_class="fund",
            instrument_type="open_end_fund",
            price=1.76 + step * 0.001,
            timestamp=later_nav_dt.isoformat(),
            created_at=later_nav_dt.astimezone(ZoneInfo("UTC")).isoformat(),
            quote_source="tushare_fund_nav" if step % 2 == 0 else "eastmoney_fund_page",
            quote_status="confirmed",
            nav_date="2026-11-26",
        )
    for step in range(35):
        ts = datetime(2026, 11, 27, 9, 30, 0, tzinfo=_SH) + timedelta(minutes=step)
        _insert_quote_row(
            db,
            symbol="018125",
            asset_class="fund",
            instrument_type="open_end_fund",
            price=1.74,
            timestamp=ts.isoformat(),
            created_at=ts.astimezone(ZoneInfo("UTC")).isoformat(),
            quote_source="eastmoney_fund_estimate",
            quote_status="estimated",
            stale_reason="confirmed_fund_nav_missing_estimate_only",
            nav_date="2026-11-26",
        )

    pre_cutoff = db.get_latest_quote_before_date_sync(
        "018125",
        "2026-11-28",
        instrument_type="open_end_fund",
        as_of=datetime(2026, 11, 26, 16, 0, 0, tzinfo=_SH),
    )
    assert pre_cutoff is not None
    assert pre_cutoff["quote_source"] == "eastmoney_fund_page"
    assert pre_cutoff["nav_date"] == "2026-11-25"
    assert pre_cutoff["price"] == pytest.approx(1.8028)

    post_cutoff = db.get_latest_quote_before_date_sync(
        "018125",
        "2026-11-28",
        instrument_type="open_end_fund",
        as_of=datetime(2026, 11, 27, 12, 0, 0, tzinfo=_SH),
    )
    assert post_cutoff is not None
    assert post_cutoff["quote_source"] in {"eastmoney_fund_page", "tushare_fund_nav"}
    assert post_cutoff["nav_date"] == "2026-11-26"
    assert post_cutoff["price"] >= 1.7533
