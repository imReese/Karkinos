"""Read-only SQLite access for persisted market-bar facts."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


def read_market_bars(
    db_path: Path,
    *,
    symbol: str,
    instrument_type: str,
    frequency: str,
    start_at: datetime,
    end_exclusive: datetime,
) -> list[dict[str, float | str]]:
    """Read one exact instrument's bounded v2 window without writes."""

    if not db_path.is_file():
        return []

    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=1.0) as connection:
        if (
            connection.execute("""
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'market_bars_v2'
                """).fetchone()
            is None
        ):
            return []

        legacy_lot_dates: set[str] = set()
        if (
            connection.execute("""
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'market_daily_ingestion_receipts'
                """).fetchone()
            is not None
        ):
            for r in connection.execute(
                """
                SELECT trade_date, receipt_json FROM market_daily_ingestion_receipts
                WHERE trade_date >= ? AND trade_date < ?
                """,
                (start_at.strftime("%Y-%m-%d"), end_exclusive.strftime("%Y-%m-%d")),
            ).fetchall():
                try:
                    payload = json.loads(str(r[1]))
                    schema = payload.get("schema_version")
                    provider = payload.get("provider_name")
                    if (
                        schema
                        in (
                            "karkinos.market_daily_ingestion_receipt.v1",
                            "karkinos.market_daily_ingestion_receipt.v2",
                        )
                        and provider == "tushare"
                    ):
                        legacy_lot_dates.add(str(r[0]))
                except Exception:
                    pass

        rows = connection.execute(
            """
            SELECT timestamp, open, high, low, close, volume
            FROM market_bars_v2
            WHERE symbol = ? AND instrument_type = ? AND frequency = ?
              AND timestamp >= ? AND timestamp < ?
            ORDER BY timestamp ASC
            """,
            (
                symbol,
                instrument_type,
                frequency,
                start_at.isoformat(),
                end_exclusive.isoformat(),
            ),
        ).fetchall()

    result: list[dict[str, float | str]] = []
    for row in rows:
        ts = str(row[0])
        trade_date = ts[:10]
        raw_vol = float(row[5]) if row[5] is not None else 0.0
        # TuShare v1/v2 daily batches stored volume in lots (手); normalize to shares (股)
        # to match canonical stock bar units (1 lot = 100 shares).
        if trade_date in legacy_lot_dates and frequency == "1d":
            raw_vol *= 100.0

        result.append(
            {
                "timestamp": ts,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": raw_vol,
            }
        )

    return result


__all__ = ("read_market_bars",)
