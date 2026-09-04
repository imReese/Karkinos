"""Bounded persisted market-bar lookups for financial fact repositories."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from core.types import InstrumentType


def _instrument_type(raw_type: object) -> str:
    return InstrumentType.from_persisted(
        str(raw_type or "").strip().lower().replace("-", "_")
    ).value


def _project_bar(row: sqlite3.Row, instrument_type: str) -> dict[str, Any]:
    result = dict(row)
    result["trade_date"] = str(result["timestamp"])[:10]
    result["price"] = result["close"]
    result["source"] = "market_bars_v2"
    result["asset_class"] = (
        "fund" if instrument_type == "open_end_fund" else instrument_type
    )
    return result


def get_latest_market_bar_before_date(
    database_path: str | Path,
    symbol: str,
    trade_date: str,
    frequency: str,
    *,
    instrument_type: str,
) -> dict[str, Any] | None:
    """Read one exact instrument's latest bar before ``trade_date``."""

    resolved_type = _instrument_type(instrument_type)
    meta_path = Path(database_path).parent / "meta.db"
    if not meta_path.exists():
        return None
    try:
        with sqlite3.connect(meta_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT
                    symbol, instrument_type, frequency, timestamp,
                    open, high, low, close, volume, amount,
                    identity_provenance, created_at, updated_at
                FROM market_bars_v2
                WHERE symbol = ? AND instrument_type = ? AND frequency = ?
                  AND substr(timestamp, 1, 10) < ?
                ORDER BY substr(timestamp, 1, 10) DESC, timestamp DESC
                LIMIT 1
                """,
                (symbol, resolved_type, frequency, trade_date),
            ).fetchone()
    except sqlite3.Error:
        return None
    return None if row is None else _project_bar(row, resolved_type)


def get_market_bar_on_date(
    database_path: str | Path,
    symbol: str,
    trade_date: str,
    frequency: str,
    *,
    instrument_type: str,
) -> dict[str, Any] | None:
    """Read one exact instrument's daily OHLC bar on ``trade_date``."""

    resolved_type = _instrument_type(instrument_type)
    meta_path = Path(database_path).parent / "meta.db"
    if not meta_path.exists():
        return None
    try:
        with sqlite3.connect(meta_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT
                    symbol, instrument_type, frequency, timestamp,
                    open, high, low, close, volume, amount,
                    identity_provenance, created_at, updated_at
                FROM market_bars_v2
                WHERE symbol = ? AND instrument_type = ? AND frequency = ?
                  AND substr(timestamp, 1, 10) = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (symbol, resolved_type, frequency, trade_date),
            ).fetchone()
    except sqlite3.Error:
        return None
    return None if row is None else _project_bar(row, resolved_type)


__all__ = ["get_latest_market_bar_before_date", "get_market_bar_on_date"]
