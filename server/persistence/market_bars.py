"""Read-only SQLite access for persisted market-bar facts."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


def read_market_bars(
    db_path: Path,
    *,
    symbol: str,
    frequency: str,
    start_at: datetime,
    end_exclusive: datetime,
) -> list[dict[str, float | str]]:
    """Read a bounded market-bar window without creating or mutating storage."""

    if not db_path.is_file():
        return []

    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=1.0) as connection:
        rows = connection.execute(
            """
            SELECT timestamp, open, high, low, close, volume
            FROM market_bars
            WHERE symbol = ? AND frequency = ?
              AND timestamp >= ? AND timestamp < ?
            ORDER BY timestamp ASC
            """,
            (
                symbol,
                frequency,
                start_at.isoformat(),
                end_exclusive.isoformat(),
            ),
        ).fetchall()

    return [
        {
            "timestamp": str(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
        for row in rows
    ]


__all__ = ("read_market_bars",)
