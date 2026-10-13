"""Typed market-bar storage schema constants."""

from __future__ import annotations

from core.types import InstrumentType

_CANONICAL_INSTRUMENT_TYPES = tuple(
    item.value for item in InstrumentType if item is not InstrumentType.UNKNOWN
)
_INSTRUMENT_TYPE_CHECK = ", ".join(
    f"'{instrument_type}'" for instrument_type in _CANONICAL_INSTRUMENT_TYPES
)

MARKET_BAR_V2_SCHEMA = (
    f"""
    CREATE TABLE IF NOT EXISTS market_bars_v2 (
        symbol TEXT NOT NULL CHECK(trim(symbol) <> ''),
        instrument_type TEXT NOT NULL
            CHECK(instrument_type IN ({_INSTRUMENT_TYPE_CHECK})),
        frequency TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        open REAL,
        high REAL,
        low REAL,
        close REAL NOT NULL CHECK(close > 0),
        volume REAL,
        amount REAL,
        identity_provenance TEXT NOT NULL
            CHECK(trim(identity_provenance) <> ''),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (symbol, instrument_type, frequency, timestamp)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_market_bars_v2_identity_frequency_ts
    ON market_bars_v2(symbol, instrument_type, frequency, timestamp)
    """,
    f"""
    CREATE TABLE IF NOT EXISTS bar_meta_v2 (
        symbol TEXT NOT NULL CHECK(trim(symbol) <> ''),
        instrument_type TEXT NOT NULL
            CHECK(instrument_type IN ({_INSTRUMENT_TYPE_CHECK})),
        frequency TEXT NOT NULL,
        start_date TEXT,
        end_date TEXT,
        last_updated TEXT,
        row_count INTEGER DEFAULT 0,
        provider_name TEXT,
        data_source TEXT,
        adjustment_mode TEXT,
        fetched_at TEXT,
        dataset_id TEXT,
        diagnostics_json TEXT,
        duplicate_timestamp_count INTEGER DEFAULT 0,
        missing_ohlcv_count INTEGER DEFAULT 0,
        is_monotonic INTEGER DEFAULT 1,
        identity_provenance TEXT NOT NULL
            CHECK(trim(identity_provenance) <> ''),
        PRIMARY KEY (symbol, instrument_type, frequency)
    )
    """,
)

__all__ = [
    "MARKET_BAR_V2_SCHEMA",
    "_INSTRUMENT_TYPE_CHECK",
]
