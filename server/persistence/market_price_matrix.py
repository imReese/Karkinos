"""Read-only, identity-bound historical price evidence."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from core.types import InstrumentKey, InstrumentType

_MAX_IDENTITIES_PER_QUERY = 400


def read_historical_price_matrix(
    app_database_path: Path,
    *,
    instrument_keys: (
        Sequence[InstrumentKey | Mapping[str, object] | tuple[object, object]] | None
    ) = None,
    symbols: list[str] | None = None,
    start_date: str,
    end_date: str,
    symbol_batch_size: int = _MAX_IDENTITIES_PER_QUERY,
) -> dict[Any, list[dict[str, Any]]]:
    """Load only facts matching the complete requested instrument identity.

    ``symbols`` is a stock-only compatibility adapter. Authoritative callers
    pass ``instrument_keys``; generic ``fund`` is accepted solely as legacy
    open-end-fund compatibility and can never match an ETF.
    """

    legacy_symbol_result = instrument_keys is None
    keys = _normalize_requested_keys(instrument_keys, symbols=symbols)
    if not keys:
        return {}
    _validate_date_window(start_date, end_date)
    if symbol_batch_size <= 0 or symbol_batch_size > _MAX_IDENTITIES_PER_QUERY:
        raise ValueError("historical price matrix identity batch size is invalid")

    matrix: dict[InstrumentKey, list[dict[str, Any]]] = {}
    meta_database_path = app_database_path.parent / "meta.db"
    for offset in range(0, len(keys), symbol_batch_size):
        chunk = keys[offset : offset + symbol_batch_size]
        rows = _read_typed_chunk(
            app_database_path,
            meta_database_path,
            instrument_keys=chunk,
            start_date=start_date,
            end_date=end_date,
        )
        for row in rows:
            key = InstrumentKey.from_values(row[0], row[1])
            if key not in chunk:
                raise RuntimeError("historical price matrix identity escaped request")
            matrix.setdefault(key, []).append(_price_row(row))

    for rows in matrix.values():
        rows.sort(key=lambda row: (str(row["trade_date"]), str(row["timestamp"])))
    if legacy_symbol_result:
        return {key.symbol: rows for key, rows in matrix.items()}
    return matrix


def _normalize_requested_keys(
    value: (
        Sequence[InstrumentKey | Mapping[str, object] | tuple[object, object]] | None
    ),
    *,
    symbols: list[str] | None,
) -> list[InstrumentKey]:
    if value is not None and symbols is not None:
        raise ValueError("provide instrument_keys, not both identities and symbols")
    if value is None:
        value = [
            InstrumentKey(str(symbol), InstrumentType.STOCK)
            for symbol in symbols or ()
            if str(symbol).strip()
        ]
    keys: set[InstrumentKey] = set()
    for item in value:
        if isinstance(item, InstrumentKey):
            key = item
        elif isinstance(item, Mapping):
            key = InstrumentKey.from_values(
                item.get("symbol"),
                item.get("instrument_type")
                or item.get("asset_type")
                or item.get("asset_class"),
            )
        elif isinstance(item, tuple) and len(item) == 2:
            key = InstrumentKey.from_values(item[0], item[1])
        else:
            raise TypeError("historical price matrix identity is invalid")
        keys.add(key)
    return sorted(keys, key=lambda key: key.storage_tuple())


def _read_typed_chunk(
    app_database_path: Path,
    meta_database_path: Path,
    *,
    instrument_keys: list[InstrumentKey],
    start_date: str,
    end_date: str,
) -> list[tuple[Any, ...]]:
    if not app_database_path.is_file():
        return []
    uri = _read_only_uri(app_database_path)
    with sqlite3.connect(uri, uri=True, timeout=1.0) as connection:
        include_market_bars = False
        if meta_database_path.is_file():
            connection.execute(
                "ATTACH DATABASE ? AS market_store",
                (_read_only_uri(meta_database_path),),
            )
            include_market_bars = _attached_table_exists(
                connection,
                schema="market_store",
                table="market_bars_v2",
            )
        include_daily_closes = _table_exists(
            connection,
            "daily_close_snapshots_v2",
        )
        quote_columns = _table_columns(connection, "quote_snapshots")
        sql = _matrix_sql(
            identity_count=len(instrument_keys),
            include_market_bars=include_market_bars,
            include_daily_closes=include_daily_closes,
            include_quotes=bool(quote_columns),
            quote_columns=quote_columns,
        )
        params: list[object] = []
        for key in instrument_keys:
            params.extend(key.storage_tuple())
        params.extend((start_date, end_date))
        return list(connection.execute(sql, params).fetchall())


def _matrix_sql(
    *,
    identity_count: int,
    include_market_bars: bool,
    include_daily_closes: bool,
    include_quotes: bool,
    quote_columns: set[str],
) -> str:
    observations: list[str] = []
    if include_market_bars:
        observations.append("""
            SELECT
                bars.symbol,
                bars.instrument_type,
                substr(bars.timestamp, 1, 10) AS trade_date,
                bars.timestamp,
                bars.close AS price,
                'market_bars_v2' AS source,
                CASE WHEN bars.instrument_type = 'open_end_fund'
                     THEN 'fund' ELSE bars.instrument_type END AS asset_class,
                NULL AS generation_id,
                bars.identity_provenance,
                0 AS source_priority
            FROM market_store.market_bars_v2 AS bars
            JOIN requested AS wanted
              ON wanted.symbol = bars.symbol
             AND wanted.instrument_type = bars.instrument_type
            CROSS JOIN bounds
            WHERE bars.frequency = '1d'
              AND substr(bars.timestamp, 1, 10) <= bounds.end_date
              AND bars.close > 0
              AND (
                  substr(bars.timestamp, 1, 10) >= bounds.start_date
                  OR bars.timestamp = (
                      SELECT MAX(prior.timestamp)
                      FROM market_store.market_bars_v2 AS prior
                      WHERE prior.symbol = bars.symbol
                        AND prior.instrument_type = bars.instrument_type
                        AND prior.frequency = bars.frequency
                        AND substr(prior.timestamp, 1, 10) < bounds.start_date
                  )
              )
            """)
    if include_daily_closes:
        observations.append("""
            SELECT
                closes.symbol,
                closes.instrument_type,
                closes.trade_date,
                closes.trade_date || 'T15:00:00+08:00' AS timestamp,
                closes.close_price AS price,
                COALESCE(closes.source, 'daily_close_snapshots_v2') AS source,
                CASE WHEN closes.instrument_type = 'open_end_fund'
                     THEN 'fund' ELSE closes.instrument_type END AS asset_class,
                NULL AS generation_id,
                closes.identity_provenance,
                1 AS source_priority
            FROM daily_close_snapshots_v2 AS closes
            JOIN requested AS wanted
              ON wanted.symbol = closes.symbol
             AND wanted.instrument_type = closes.instrument_type
            CROSS JOIN bounds
            WHERE closes.trade_date <= bounds.end_date
              AND closes.close_price > 0
              AND (
                  closes.trade_date >= bounds.start_date
                  OR closes.trade_date = (
                      SELECT MAX(prior.trade_date)
                      FROM daily_close_snapshots_v2 AS prior
                      WHERE prior.symbol = closes.symbol
                        AND prior.instrument_type = closes.instrument_type
                        AND prior.trade_date < bounds.start_date
                  )
              )
            """)
    if include_quotes:
        raw_type = (
            "COALESCE(quotes.instrument_type, quotes.asset_class)"
            if "instrument_type" in quote_columns
            else "quotes.asset_class"
        )
        prior_raw_type = (
            "COALESCE(prior.instrument_type, prior.asset_class)"
            if "instrument_type" in quote_columns
            else "prior.asset_class"
        )
        normalized_type = _normalized_type_sql(raw_type)
        prior_normalized_type = _normalized_type_sql(prior_raw_type)
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
        observations.append(f"""
            SELECT
                quotes.symbol,
                {normalized_type} AS instrument_type,
                substr(quotes.timestamp, 1, 10) AS trade_date,
                quotes.timestamp,
                quotes.price,
                COALESCE(quotes.quote_source, 'quote_snapshots') AS source,
                CASE WHEN {normalized_type} = 'open_end_fund'
                     THEN 'fund' ELSE {normalized_type} END AS asset_class,
                NULL AS generation_id,
                {provenance} AS identity_provenance,
                2 AS source_priority
            FROM quote_snapshots AS quotes
            JOIN requested AS wanted
              ON wanted.symbol = quotes.symbol
             AND wanted.instrument_type = {normalized_type}
            CROSS JOIN bounds
            WHERE substr(quotes.timestamp, 1, 10) <= bounds.end_date
              AND quotes.price > 0
              AND (
                  substr(quotes.timestamp, 1, 10) >= bounds.start_date
                  OR quotes.timestamp = (
                      SELECT MAX(prior.timestamp)
                      FROM quote_snapshots AS prior
                      WHERE prior.symbol = quotes.symbol
                        AND {prior_normalized_type} = {normalized_type}
                        AND substr(prior.timestamp, 1, 10) < bounds.start_date
                  )
              )
            """)
    if not observations:
        return f"""
            WITH requested(symbol, instrument_type) AS (
                VALUES {_requested_identity_values(identity_count)}
            ), bounds(start_date, end_date) AS (VALUES (?, ?))
            SELECT NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL
            WHERE 0
        """
    unioned = "\nUNION ALL\n".join(observations)
    return f"""
        WITH requested(symbol, instrument_type) AS (
            VALUES {_requested_identity_values(identity_count)}
        ),
        bounds(start_date, end_date) AS (VALUES (?, ?)),
        observations AS (
            {unioned}
        ),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY symbol, instrument_type, trade_date
                ORDER BY source_priority, timestamp DESC
            ) AS evidence_rank
            FROM observations
        )
        SELECT
            symbol, instrument_type, trade_date, timestamp, price, source,
            asset_class, generation_id, identity_provenance
        FROM ranked
        WHERE evidence_rank = 1
        ORDER BY symbol, instrument_type, trade_date, timestamp
    """


def _normalized_type_sql(expression: str) -> str:
    normalized = f"lower(replace(trim({expression}), '-', '_'))"
    return (
        f"CASE {normalized} "
        "WHEN 'fund' THEN 'open_end_fund' "
        "WHEN 'openend_fund' THEN 'open_end_fund' "
        f"ELSE {normalized} END"
    )


def _price_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "symbol": str(row[0]),
        "instrument_type": str(row[1]),
        "trade_date": str(row[2]),
        "timestamp": str(row[3]),
        "price": float(row[4]),
        "source": str(row[5]),
        "asset_class": None if row[6] is None else str(row[6]),
        "generation_id": None if row[7] is None else str(row[7]),
        "identity_provenance": None if row[8] is None else str(row[8]),
    }


def _requested_identity_values(count: int) -> str:
    return ", ".join("(?, ?)" for _ in range(count))


def _read_only_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def _attached_table_exists(
    conn: sqlite3.Connection,
    *,
    schema: str,
    table: str,
) -> bool:
    return (
        conn.execute(
            f"SELECT 1 FROM {schema}.sqlite_master "
            "WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def _validate_date_window(start_date: str, end_date: str) -> None:
    try:
        start = date.fromisoformat(str(start_date))
        end = date.fromisoformat(str(end_date))
    except ValueError:
        raise ValueError("historical price matrix date window is invalid") from None
    if start > end:
        raise ValueError("historical price matrix date window is invalid")


__all__ = ["read_historical_price_matrix"]
