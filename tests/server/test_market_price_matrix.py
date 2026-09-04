"""Provider-free, SQL-bounded historical price matrix reads."""

from __future__ import annotations

import sqlite3

from core.types import InstrumentKey, InstrumentType
from server.db import AppDatabase


def _create_market_bars(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("""
            CREATE TABLE market_bars_v2 (
                symbol TEXT NOT NULL,
                instrument_type TEXT NOT NULL,
                frequency TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                close REAL NOT NULL,
                identity_provenance TEXT NOT NULL,
                PRIMARY KEY (symbol, instrument_type, frequency, timestamp)
            )
            """)
        connection.executemany(
            "INSERT INTO market_bars_v2 VALUES (?, 'stock', '1d', ?, ?, 'fixture')",
            [
                ("600001", "2026-08-26T15:00:00+08:00", 10.5),
                ("600002", "2026-08-26T15:00:00+08:00", 20.5),
                ("600003", "2026-08-26T15:00:00+08:00", 30.5),
                ("NOISE", "2026-08-26T15:00:00+08:00", 99.0),
            ],
        )


def test_market_price_matrix_keeps_persisted_market_bars_provider_free(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _create_market_bars(tmp_path / "meta.db")

    matrix = db.get_historical_price_matrix_sync(
        symbols=["600001"],
        start_date="2026-08-26",
        end_date="2026-08-26",
    )

    assert list(matrix) == ["600001"]
    assert matrix["600001"][0]["price"] == 10.5
    assert matrix["600001"][0]["generation_id"] is None


def test_market_price_matrix_uses_bounded_symbol_chunks(tmp_path, monkeypatch) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _create_market_bars(tmp_path / "meta.db")

    from server.persistence import market_price_matrix as price_matrix

    real_connect = price_matrix.sqlite3.connect
    select_parameter_counts: list[int] = []

    class TracedConnection:
        def __init__(self, connection) -> None:
            self._connection = connection

        def __enter__(self):
            self._connection.__enter__()
            return self

        def __exit__(self, *args):
            return self._connection.__exit__(*args)

        def execute(self, sql, parameters=()):
            if str(sql).lstrip().upper().startswith("WITH"):
                select_parameter_counts.append(len(tuple(parameters)))
            return self._connection.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(self._connection, name)

    monkeypatch.setattr(
        price_matrix.sqlite3,
        "connect",
        lambda *args, **kwargs: TracedConnection(real_connect(*args, **kwargs)),
    )

    matrix = db.get_historical_price_matrix_sync(
        symbols=["600001", "600002", "600003"],
        start_date="2026-08-26",
        end_date="2026-08-26",
        symbol_batch_size=2,
    )

    assert len(select_parameter_counts) == 2
    assert sorted(matrix) == ["600001", "600002", "600003"]


def test_market_price_matrix_separates_etf_from_legacy_open_end_fund(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    with sqlite3.connect(db.path) as connection:
        connection.executemany(
            """
            INSERT INTO quote_snapshots (
                symbol, asset_class, price, timestamp, created_at,
                quote_source, quote_status, quote_instant_utc,
                instrument_type, identity_provenance
            ) VALUES (?, ?, ?, ?, 'fixture', 'fixture', 'live', ?, ?, ?)
            """,
            [
                (
                    "019999",
                    "fund",
                    1.25,
                    "2026-08-26T15:00:00+08:00",
                    "2026-08-26T07:00:00.000000+00:00",
                    "open_end_fund",
                    "legacy_fund_compatibility",
                ),
                (
                    "019999",
                    "etf",
                    2.5,
                    "2026-08-26T15:00:00+08:00",
                    "2026-08-26T07:00:00.000000+00:00",
                    "etf",
                    "explicit_canonical",
                ),
            ],
        )

    keys = [
        InstrumentKey("019999", InstrumentType.ETF),
        InstrumentKey("019999", InstrumentType.OPEN_END_FUND),
    ]
    matrix = db.get_historical_price_matrix_sync(
        instrument_keys=keys,
        start_date="2026-08-26",
        end_date="2026-08-26",
    )

    assert matrix[keys[0]][0]["price"] == 2.5
    assert matrix[keys[0]][0]["instrument_type"] == "etf"
    assert matrix[keys[1]][0]["price"] == 1.25
    assert matrix[keys[1]][0]["instrument_type"] == "open_end_fund"
