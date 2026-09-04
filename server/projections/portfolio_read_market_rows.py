"""Persisted market-row adapters for immutable portfolio read snapshots."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from core.types import InstrumentKey
from server.projections.portfolio_read_snapshot import PortfolioReadSnapshotRejected

_MATRIX_SYMBOL_BATCH_SIZE = 400
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _mapping_rows(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PortfolioReadSnapshotRejected(f"{label} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise PortfolioReadSnapshotRejected(f"{label} contain invalid rows")
    return list(value)


def read_intraday_quote_rows(
    database_path: Path,
    *,
    instrument_keys: list[InstrumentKey],
    trade_date: str,
) -> tuple[list[dict[str, Any]], int]:
    """Read one valuation-day quote history batch for intraday projections."""

    if not instrument_keys:
        return [], 0
    trade_day = date.fromisoformat(trade_date)
    start = datetime.combine(trade_day, time.min, tzinfo=_SHANGHAI_TZ).astimezone(
        timezone.utc
    )
    end = (start + timedelta(days=1)).astimezone(timezone.utc)
    rows: list[dict[str, Any]] = []
    query_count = 0
    try:
        with read_only_connection(database_path) as connection:
            quote_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(quote_snapshots)")
            }
            raw_type = (
                "COALESCE(quotes.instrument_type, quotes.asset_class)"
                if "instrument_type" in quote_columns
                else "quotes.asset_class"
            )
            normalized_type = (
                f"CASE lower(replace(trim({raw_type}), '-', '_')) "
                "WHEN 'fund' THEN 'open_end_fund' "
                "WHEN 'openend_fund' THEN 'open_end_fund' "
                f"ELSE lower(replace(trim({raw_type}), '-', '_')) END"
            )
            provenance = (
                "COALESCE(quotes.identity_provenance, "
                "CASE WHEN lower(trim(quotes.asset_class)) = 'fund' "
                "THEN 'legacy_fund_compatibility' "
                "ELSE 'legacy_asset_class_compatibility' END)"
                if "identity_provenance" in quote_columns
                else "CASE WHEN lower(trim(quotes.asset_class)) = 'fund' "
                "THEN 'legacy_fund_compatibility' "
                "ELSE 'legacy_asset_class_compatibility' END"
            )
            for offset in range(0, len(instrument_keys), _MATRIX_SYMBOL_BATCH_SIZE):
                chunk = instrument_keys[offset : offset + _MATRIX_SYMBOL_BATCH_SIZE]
                requested = ", ".join("(?, ?)" for _ in chunk)
                query_count += 1
                result = connection.execute(
                    f"""
                    WITH requested(symbol, instrument_type) AS (VALUES {requested})
                    SELECT
                        quotes.id, quotes.symbol,
                        CASE WHEN {normalized_type} = 'open_end_fund'
                             THEN 'fund' ELSE {normalized_type} END AS asset_class,
                        {normalized_type} AS instrument_type,
                        {provenance} AS identity_provenance,
                        quotes.price, quotes.volume, quotes.timestamp,
                        quote_source, provider_name, quote_status, stale_reason,
                        provider_status, captured_reason, nav_date, fetch_run_id,
                        created_at
                    FROM quote_snapshots AS quotes
                    JOIN requested AS wanted
                      ON wanted.symbol = quotes.symbol
                     AND wanted.instrument_type = {normalized_type}
                    WHERE quote_instant_utc >= ?
                      AND quote_instant_utc < ?
                    ORDER BY quotes.symbol, instrument_type,
                             quote_instant_utc, quotes.id
                    """,
                    (
                        *(value for key in chunk for value in key.storage_tuple()),
                        start.isoformat(timespec="microseconds"),
                        end.isoformat(timespec="microseconds"),
                    ),
                ).fetchall()
                rows.extend(dict(row) for row in result)
    except (sqlite3.Error, OSError) as exc:
        raise PortfolioReadSnapshotRejected(
            "persisted intraday quote history is unavailable"
        ) from exc
    return rows, query_count


def flatten_price_matrix(
    value: object,
    *,
    requested_instrument_keys: list[InstrumentKey],
) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping):
        raise PortfolioReadSnapshotRejected("persisted price matrix must be a mapping")
    requested = set(requested_instrument_keys)
    flattened: list[dict[str, Any]] = []
    for raw_key, raw_rows in value.items():
        if isinstance(raw_key, InstrumentKey):
            key = raw_key
        elif isinstance(raw_key, tuple) and len(raw_key) == 2:
            key = InstrumentKey.from_values(raw_key[0], raw_key[1])
        else:
            matching = [key for key in requested if key.symbol == str(raw_key).strip()]
            if len(matching) != 1:
                raise PortfolioReadSnapshotRejected(
                    "persisted price matrix key has no exact instrument identity"
                )
            key = matching[0]
        if key not in requested:
            raise PortfolioReadSnapshotRejected(
                "persisted price matrix returned an unrequested instrument"
            )
        rows = _mapping_rows(
            raw_rows,
            f"price matrix rows for {key.symbol}/{key.instrument_type.value}",
        )
        for raw_row in rows:
            row = dict(raw_row)
            row_symbol = str(row.get("symbol") or key.symbol).strip()
            raw_type = (
                row.get("instrument_type")
                or row.get("asset_type")
                or row.get("asset_class")
                or key.instrument_type.value
            )
            row_key = InstrumentKey.from_values(row_symbol, raw_type)
            if row_key != key:
                raise PortfolioReadSnapshotRejected(
                    "persisted price matrix instrument identity drifted"
                )
            row["symbol"] = row_symbol
            row["instrument_type"] = row_key.instrument_type.value
            flattened.append(row)
    flattened.sort(
        key=lambda row: (
            str(row.get("symbol") or ""),
            str(row.get("instrument_type") or ""),
            str(row.get("trade_date") or ""),
            str(row.get("timestamp") or ""),
        )
    )
    return flattened


@contextmanager
def read_only_connection(path: Path) -> Iterator[sqlite3.Connection]:
    if not path.is_file():
        raise OSError(f"database does not exist: {path}")
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=1.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("BEGIN")
    try:
        yield connection
    finally:
        connection.close()


__all__ = ["flatten_price_matrix", "read_intraday_quote_rows", "read_only_connection"]
