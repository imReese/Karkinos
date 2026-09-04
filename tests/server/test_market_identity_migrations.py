from __future__ import annotations

import sqlite3

import pytest

from data.store import DataStore
from server.db import AppDatabase
from server.persistence.market_identity_migrations import (
    migrate_legacy_daily_closes_to_v2,
)


def _legacy_close(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    asset_class: str,
    trade_date: str,
    price: float,
    source: str,
) -> None:
    conn.execute(
        """
        INSERT INTO daily_close_snapshots (
            symbol, asset_class, trade_date, close_price, source, captured_at
        ) VALUES (?, ?, ?, ?, ?, '2026-09-04T09:36:00+08:00')
        """,
        (symbol, asset_class, trade_date, price, source),
    )


def _bar_evidence(store: DataStore) -> None:
    with sqlite3.connect(store._meta_path) as conn:
        conn.execute("""
            INSERT INTO market_bars_v2 (
                symbol, instrument_type, frequency, timestamp,
                open, high, low, close, volume, amount,
                identity_provenance, created_at, updated_at
            ) VALUES (
                '600001', 'stock', '1d', '2026-09-03T15:00:00+08:00',
                22.5, 23.0, 22.0, 22.72, 100, NULL,
                'fixture', 'fixture', 'fixture'
            )
            """)


def _confirmed_open_end_quote(conn: sqlite3.Connection) -> None:
    conn.executemany(
        """
        INSERT INTO quote_snapshots (
            symbol, asset_class, price, volume, timestamp, created_at,
            quote_source, quote_status, nav_date, quote_instant_utc,
            instrument_type, identity_provenance
        ) VALUES (
            ?, ?, 1.25, NULL,
            '2026-09-04T20:00:00+08:00', 'fixture',
            'confirmed_fund_nav', 'confirmed', '2026-09-03',
            '2026-09-04T12:00:00.000000+00:00',
            ?, ?
        )
        """,
        [
            (
                "019999",
                "open_end_fund",
                "open_end_fund",
                "explicit_canonical",
            ),
            (
                "ETFONLY",
                "fund",
                "open_end_fund",
                "legacy_fund_compatibility",
            ),
        ],
    )


def _same_day_live_stock_quote(conn: sqlite3.Connection) -> None:
    conn.execute("""
        INSERT INTO quote_snapshots (
            symbol, asset_class, price, volume, timestamp, created_at,
            quote_source, quote_status, quote_instant_utc,
            instrument_type, identity_provenance
        ) VALUES (
            '600001', 'stock', 22.72, 100,
            '2026-09-04T09:36:00+08:00', 'fixture',
            'tushare_realtime_quote', 'live',
            '2026-09-04T01:36:00.000000+00:00',
            'stock', 'explicit_canonical'
        )
        """)


def _build_fixture(tmp_path):
    app = AppDatabase(tmp_path / "app.db")
    app.init_sync()
    store = DataStore(tmp_path)
    _bar_evidence(store)
    with sqlite3.connect(app.path) as conn:
        _legacy_close(
            conn,
            symbol="600001",
            asset_class="stock",
            trade_date="2026-09-03",
            price=22.72,
            source="reported_previous_close",
        )
        # This is the observed production defect: PRE_CLOSE was assigned the
        # current request date. No independent close owns this date yet.
        _legacy_close(
            conn,
            symbol="600001",
            asset_class="stock",
            trade_date="2026-09-04",
            price=22.72,
            source="reported_previous_close",
        )
        _legacy_close(
            conn,
            symbol="019999",
            asset_class="fund",
            trade_date="2026-09-03",
            price=1.25,
            source="confirmed_fund_nav",
        )
        _legacy_close(
            conn,
            symbol="ETFONLY",
            asset_class="etf",
            trade_date="2026-09-03",
            price=1.25,
            source="reported_previous_close",
        )
        _confirmed_open_end_quote(conn)
        # Even an exact same-day realtime quote at the same price does not
        # prove that PRE_CLOSE belongs to the current session's close.
        _same_day_live_stock_quote(conn)
    return app, store


def test_daily_close_migration_excludes_wrong_session_and_separates_fund_etf(
    tmp_path,
) -> None:
    app, store = _build_fixture(tmp_path)

    dry_run = migrate_legacy_daily_closes_to_v2(
        app.path,
        meta_database_path=store._meta_path,
        dry_run=True,
    )
    repeated = migrate_legacy_daily_closes_to_v2(
        app.path,
        meta_database_path=store._meta_path,
        dry_run=True,
    )
    assert dry_run["plan_fingerprint"] == repeated["plan_fingerprint"]
    assert dry_run["planned_rows"] == 2
    assert dry_run["blocker_count"] == 2

    applied = migrate_legacy_daily_closes_to_v2(
        app.path,
        meta_database_path=store._meta_path,
        dry_run=False,
    )
    replay = migrate_legacy_daily_closes_to_v2(
        app.path,
        meta_database_path=store._meta_path,
        dry_run=False,
    )

    assert applied["quick_check"] == "ok"
    assert applied["source_fingerprint"] == dry_run["source_fingerprint"]
    assert applied["migrated_rows"] == 2
    assert replay["migrated_rows"] == 0
    assert replay["target_fingerprint"] == applied["target_fingerprint"]
    with sqlite3.connect(app.path) as conn:
        rows = conn.execute("""
            SELECT symbol, instrument_type, trade_date, close_price,
                   identity_provenance
            FROM daily_close_snapshots_v2
            ORDER BY symbol, instrument_type, trade_date
            """).fetchall()
        assert rows == [
            (
                "019999",
                "open_end_fund",
                "2026-09-03",
                1.25,
                "legacy_fund_compatibility",
            ),
            (
                "600001",
                "stock",
                "2026-09-03",
                22.72,
                "legacy_asset_class_compatibility",
            ),
        ]
        assert (
            conn.execute("SELECT COUNT(*) FROM daily_close_snapshots").fetchone()[0]
            == 4
        )


def test_daily_close_migration_rolls_back_on_failure(tmp_path) -> None:
    app, store = _build_fixture(tmp_path)

    def fail(stage: str) -> None:
        if stage == "after_daily_closes":
            raise RuntimeError("injected daily-close migration failure")

    with pytest.raises(RuntimeError, match="injected daily-close migration failure"):
        migrate_legacy_daily_closes_to_v2(
            app.path,
            meta_database_path=store._meta_path,
            dry_run=False,
            _failure_hook=fail,
        )

    with sqlite3.connect(app.path) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert (
            conn.execute("SELECT COUNT(*) FROM daily_close_snapshots_v2").fetchone()[0]
            == 0
        )


def test_database_schema_init_replays_daily_close_migration_idempotently(
    tmp_path,
) -> None:
    app, _ = _build_fixture(tmp_path)

    app.init_sync()
    app.init_sync()

    with sqlite3.connect(app.path) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert (
            conn.execute("""
            SELECT symbol, instrument_type, trade_date, close_price
            FROM daily_close_snapshots_v2
            ORDER BY symbol, instrument_type, trade_date
            """).fetchall()
            == [
                ("019999", "open_end_fund", "2026-09-03", 1.25),
                ("600001", "stock", "2026-09-03", 22.72),
            ]
        )
