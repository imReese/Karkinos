"""Schema migration definition for typed historical market facts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_TYPE_VALUES = (
    "stock",
    "etf",
    "open_end_fund",
    "gold",
    "bond",
    "index",
)
_TYPE_CHECK = ", ".join(f"'{value}'" for value in _TYPE_VALUES)

_V12_BLOCKERS = (
    (
        """
        SELECT id
        FROM quote_snapshots
        WHERE lower(replace(trim(asset_class), '-', '_')) NOT IN (
            'stock', 'etf', 'fund', 'open_end_fund', 'openend_fund',
            'gold', 'bond', 'index'
        )
        LIMIT 1
        """,
        "legacy quote snapshot instrument identity is unresolved",
    ),
    (
        """
        SELECT id
        FROM daily_close_snapshots
        WHERE lower(replace(trim(asset_class), '-', '_')) NOT IN (
            'stock', 'etf', 'fund', 'open_end_fund', 'openend_fund',
            'gold', 'bond', 'index'
        )
        LIMIT 1
        """,
        "legacy daily-close instrument identity is unresolved",
    ),
)

_V12_STATEMENTS = (
    """
    ALTER TABLE quote_snapshots
    ADD COLUMN instrument_type TEXT
    """,
    """
    ALTER TABLE quote_snapshots
    ADD COLUMN identity_provenance TEXT
    """,
    """
    UPDATE quote_snapshots
    SET instrument_type = CASE lower(replace(trim(asset_class), '-', '_'))
            WHEN 'fund' THEN 'open_end_fund'
            WHEN 'openend_fund' THEN 'open_end_fund'
            ELSE lower(replace(trim(asset_class), '-', '_'))
        END,
        identity_provenance = CASE lower(replace(trim(asset_class), '-', '_'))
            WHEN 'fund' THEN 'legacy_fund_compatibility'
            ELSE 'legacy_asset_class_compatibility'
        END
    WHERE instrument_type IS NULL OR identity_provenance IS NULL
    """,
    """
    CREATE INDEX idx_quote_snapshots_typed_identity_instant
    ON quote_snapshots(
        symbol, instrument_type, quote_instant_utc DESC, id DESC
    )
    """,
    f"""
    CREATE TABLE daily_close_snapshots_v2 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL CHECK(trim(symbol) <> ''),
        instrument_type TEXT NOT NULL
            CHECK(instrument_type IN ({_TYPE_CHECK})),
        trade_date TEXT NOT NULL,
        close_price REAL NOT NULL CHECK(close_price > 0),
        source TEXT NOT NULL CHECK(trim(source) <> ''),
        captured_at TEXT NOT NULL,
        identity_provenance TEXT NOT NULL
            CHECK(trim(identity_provenance) <> ''),
        UNIQUE(symbol, instrument_type, trade_date)
    )
    """,
    """
    CREATE INDEX idx_daily_close_v2_identity_trade_date
    ON daily_close_snapshots_v2(
        symbol, instrument_type, trade_date DESC, id DESC
    )
    """,
)


def build_market_identity_schema_migration(
    migration_factory: Callable[..., Any],
) -> Any:
    return migration_factory(
        version=12,
        name="type_historical_market_fact_identity",
        blockers=_V12_BLOCKERS,
        statements=_V12_STATEMENTS,
    )


__all__ = ["build_market_identity_schema_migration"]
