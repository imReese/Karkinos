"""Read-only, identity-bound historical price evidence."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.types import InstrumentKey, InstrumentType
from server.contracts.quote_ingestion import (
    normalize_as_of_utc,
    select_best_historical_observations,
)
from server.persistence.connection import connect_sqlite
from server.persistence.financial_fact_event_payloads import (
    sql_utc_ms_cutoff_bound,
    sql_utc_timestamp_ms_expr,
)

_MAX_IDENTITIES_PER_QUERY = 400


def read_historical_price_observations(
    connection: sqlite3.Connection,
    *,
    symbols: list[str],
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """Retain exact candidate status/NAV dates on a caller-owned read transaction.

    The caller attaches the read-only meta database as market_store. Missing
    source tables are errors, never an empty-evidence success. This does not
    change the existing matrix's selection order or positive-price filter.
    """
    rows: list[dict[str, Any]] = []
    for offset in range(0, len(symbols), _MAX_IDENTITIES_PER_QUERY):
        chunk = symbols[offset : offset + _MAX_IDENTITIES_PER_QUERY]
        placeholders = ",".join("?" for _ in chunk)
        bars_table = "market_bars"
        queries = (
            f"""SELECT symbol, instrument_type, trade_date,
                       trade_date || 'T15:00:00+08:00' AS timestamp,
                       close_price AS price, source, captured_at,
                       'close' AS kind, 'daily_close_snapshots_v2:' || id AS evidence_ref,
                       NULL AS nav_date, NULL AS quote_status, identity_provenance
                FROM daily_close_snapshots_v2
                WHERE symbol IN ({placeholders}) AND trade_date BETWEEN ? AND ?""",
            f"""SELECT symbol, instrument_type, substr(timestamp, 1, 10) AS trade_date,
                       timestamp, close AS price, 'market_bars' AS source,
                       updated_at AS captured_at, 'bar' AS kind,
                       'market_bars:' || symbol || ':' || instrument_type || ':' || timestamp AS evidence_ref,
                       NULL AS nav_date, NULL AS quote_status, identity_provenance
                FROM market_store.{bars_table}
                WHERE symbol IN ({placeholders}) AND frequency = '1d'
                  AND substr(timestamp, 1, 10) BETWEEN ? AND ?""",
            f"""SELECT symbol, {_normalized_type_sql("COALESCE(instrument_type, asset_class)")} AS instrument_type,
                       substr(timestamp, 1, 10) AS trade_date, timestamp, price,
                       quote_source AS source, created_at AS captured_at,
                       'quote' AS kind, 'quote_snapshots:' || id AS evidence_ref,
                       nav_date, quote_status, identity_provenance
                FROM quote_snapshots
                WHERE symbol IN ({placeholders})
                  AND (substr(timestamp, 1, 10) BETWEEN ? AND ?
                       OR substr(nav_date, 1, 10) BETWEEN ? AND ?)""",
        )
        for index, query in enumerate(queries):
            bounds = (start_date, end_date) * (2 if index == 2 else 1)
            rows.extend(
                dict(row) for row in connection.execute(query, (*chunk, *bounds))
            )
    return sorted(
        rows,
        key=lambda row: (
            row["symbol"],
            row["instrument_type"],
            row["trade_date"],
            row["evidence_ref"],
        ),
    )


def read_historical_price_matrix(
    app_database_path: Path,
    *,
    instrument_keys: (Sequence[object] | None) = None,
    symbols: list[str] | None = None,
    start_date: str,
    end_date: str,
    symbol_batch_size: int = _MAX_IDENTITIES_PER_QUERY,
    as_of: datetime | str | None = None,
) -> dict[Any, list[dict[str, Any]]]:
    """Load only facts matching the complete requested instrument identity.

    ``symbols`` is a stock-only compatibility adapter. Authoritative callers
    pass ``instrument_keys``; generic ``fund`` is accepted solely as legacy
    open-end-fund compatibility and can never match an ETF.
    """

    legacy_symbol_result = instrument_keys is None and symbols is not None
    _validate_date_window(start_date, end_date)
    if symbol_batch_size <= 0 or symbol_batch_size > _MAX_IDENTITIES_PER_QUERY:
        raise ValueError("historical price matrix identity batch size is invalid")
    as_of_utc = normalize_as_of_utc(as_of)
    as_of_utc_ms = None if as_of_utc is None else sql_utc_ms_cutoff_bound(as_of_utc)

    matrix: dict[InstrumentKey, list[dict[str, Any]]] = {}
    meta_database_path = app_database_path.parent / "meta.db"

    if legacy_symbol_result:
        raw_symbols = sorted(
            {str(s).strip() for s in (symbols or ()) if str(s).strip()}
        )
        if not raw_symbols:
            return {}
        for offset in range(0, len(raw_symbols), symbol_batch_size):
            chunk_symbols = raw_symbols[offset : offset + symbol_batch_size]
            rows = _read_chunk(
                app_database_path,
                meta_database_path,
                symbols=chunk_symbols,
                instrument_keys=None,
                start_date=start_date,
                end_date=end_date,
                as_of_utc_ms=as_of_utc_ms,
            )
            grouped_rows: dict[InstrumentKey, list[dict[str, Any]]] = {}
            for row in rows:
                key = InstrumentKey.from_values(row[0], row[1])
                if key.symbol not in chunk_symbols:
                    raise RuntimeError(
                        "historical price matrix identity escaped request"
                    )
                grouped_rows.setdefault(key, []).append(_price_row(row))
            for key, cand_rows in grouped_rows.items():
                matrix[key] = _finalize_instrument_matrix_rows(
                    cand_rows, start_date=start_date, end_date=end_date, as_of=as_of_utc
                )
        by_symbol: dict[str, list[dict[str, Any]]] = {}
        for key, p_rows in matrix.items():
            by_symbol.setdefault(key.symbol, []).extend(p_rows)
        for p_rows in by_symbol.values():
            p_rows.sort(key=lambda r: (str(r["trade_date"]), str(r["timestamp"])))
        return by_symbol

    keys = _normalize_requested_keys(instrument_keys, symbols=symbols)
    if not keys:
        return {}
    for offset in range(0, len(keys), symbol_batch_size):
        chunk = keys[offset : offset + symbol_batch_size]
        rows = _read_chunk(
            app_database_path,
            meta_database_path,
            symbols=None,
            instrument_keys=chunk,
            start_date=start_date,
            end_date=end_date,
            as_of_utc_ms=as_of_utc_ms,
        )
        grouped_rows = {}
        for row in rows:
            key = InstrumentKey.from_values(row[0], row[1])
            if key not in chunk:
                raise RuntimeError("historical price matrix identity escaped request")
            grouped_rows.setdefault(key, []).append(_price_row(row))
        for key, cand_rows in grouped_rows.items():
            finalized = _finalize_instrument_matrix_rows(
                cand_rows, start_date=start_date, end_date=end_date, as_of=as_of_utc
            )
            if finalized:
                matrix[key] = finalized

    return matrix


def _finalize_instrument_matrix_rows(
    candidate_rows: list[dict[str, Any]],
    *,
    start_date: str,
    end_date: str,
    as_of: datetime | None,
) -> list[dict[str, Any]]:
    selected = select_best_historical_observations(candidate_rows, as_of=as_of)
    in_window = [
        row for row in selected if start_date <= str(row["trade_date"]) <= end_date
    ]
    prior = [row for row in selected if str(row["trade_date"]) < start_date]
    kept = ([prior[-1]] if prior else []) + in_window
    kept.sort(key=lambda row: (str(row["trade_date"]), str(row["timestamp"])))
    return kept


def _normalize_requested_keys(
    value: (Sequence[object] | None),
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


def _read_chunk(
    app_database_path: Path,
    meta_database_path: Path,
    *,
    symbols: list[str] | None,
    instrument_keys: list[InstrumentKey] | None,
    start_date: str,
    end_date: str,
    as_of_utc_ms: str | None = None,
) -> list[tuple[Any, ...]]:
    if not app_database_path.is_file():
        return []
    uri = _read_only_uri(app_database_path)
    with connect_sqlite(uri, uri_attachments=True, timeout=1.0) as connection:
        bars_table: str | None = None
        bar_columns: set[str] = set()
        if meta_database_path.is_file():
            connection.execute(
                "ATTACH DATABASE ? AS market_store",
                (_read_only_uri(meta_database_path),),
            )
            if _attached_table_exists(
                connection,
                schema="market_store",
                table="market_bars",
            ):
                bars_table = "market_bars"
                bar_columns = _table_columns(
                    connection, "market_bars", schema="market_store"
                )
        include_daily_closes = _table_exists(
            connection,
            "daily_close_snapshots_v2",
        )
        quote_columns = _table_columns(connection, "quote_snapshots")
        sql, extra_params = _matrix_sql(
            identity_count=len(symbols)
            if symbols is not None
            else len(instrument_keys or []),
            is_symbol_query=symbols is not None,
            bars_table=bars_table,
            bar_columns=bar_columns,
            include_daily_closes=include_daily_closes,
            include_quotes=bool(quote_columns),
            quote_columns=quote_columns,
            as_of_utc_ms=as_of_utc_ms,
        )
        params: list[object] = []
        if symbols is not None:
            params.extend(symbols)
        else:
            for key in instrument_keys or []:
                params.extend(key.storage_tuple())
        params.extend((start_date, end_date))
        params.extend(extra_params)
        return list(connection.execute(sql, params).fetchall())


def _quote_effective_date_sql(
    alias: str, quote_columns: set[str], normalized_type: str
) -> str:
    ts_date = (
        f"coalesce(nullif(date({alias}.quote_instant_utc, '+8 hours'), ''), substr({alias}.timestamp, 1, 10))"
        if "quote_instant_utc" in quote_columns
        else f"substr({alias}.timestamp, 1, 10)"
    )
    if "nav_date" not in quote_columns:
        return ts_date
    return (
        f"CASE WHEN {normalized_type} = 'open_end_fund' "
        f"AND trim(coalesce({alias}.nav_date, '')) != '' "
        f"THEN CASE WHEN trim({alias}.nav_date) GLOB '????-??-??*' "
        f"THEN substr(trim({alias}.nav_date), 1, 10) ELSE NULL END "
        f"ELSE {ts_date} END"
    )


def _matrix_sql(
    *,
    identity_count: int,
    is_symbol_query: bool,
    bars_table: str | None,
    bar_columns: set[str],
    include_daily_closes: bool,
    include_quotes: bool,
    quote_columns: set[str],
    as_of_utc_ms: str | None = None,
) -> tuple[str, list[object]]:
    ctes: list[str] = []
    cte_params: list[object] = []
    observations: list[str] = []
    arm_params: list[object] = []

    if bars_table:
        type_join = (
            ""
            if is_symbol_query
            else "\n             AND wanted.instrument_type = bars.instrument_type"
        )
        prior_type_join = (
            ""
            if is_symbol_query
            else "\n             AND wanted.instrument_type = prior.instrument_type"
        )
        has_updated_at = "updated_at" in bar_columns
        bar_captured = "bars.updated_at" if has_updated_at else "NULL"
        bar_as_of_main = ""
        bar_as_of_prior = ""
        if as_of_utc_ms is not None:
            if has_updated_at:
                bar_as_of_prior = (
                    f"\n              AND (prior.updated_at IS NULL OR trim(prior.updated_at) = '' "
                    f"OR {sql_utc_timestamp_ms_expr('prior.updated_at')} <= ?)"
                    f"\n              AND {sql_utc_timestamp_ms_expr('prior.timestamp')} <= ?"
                )
                bar_as_of_main = (
                    f"\n              AND (bars.updated_at IS NULL OR trim(bars.updated_at) = '' "
                    f"OR {sql_utc_timestamp_ms_expr('bars.updated_at')} <= ?)"
                    f"\n              AND {sql_utc_timestamp_ms_expr('bars.timestamp')} <= ?"
                )
                cte_params.extend([as_of_utc_ms, as_of_utc_ms])
                arm_params.extend([as_of_utc_ms, as_of_utc_ms])
            else:
                bar_as_of_prior = f"\n              AND {sql_utc_timestamp_ms_expr('prior.timestamp')} <= ?"
                bar_as_of_main = f"\n              AND {sql_utc_timestamp_ms_expr('bars.timestamp')} <= ?"
                cte_params.append(as_of_utc_ms)
                arm_params.append(as_of_utc_ms)
        ctes.append(f"""
            prior_bar_cutoffs AS (
                SELECT
                    prior.symbol,
                    prior.instrument_type,
                    MAX(substr(prior.timestamp, 1, 10)) AS prior_date
                FROM requested AS wanted
                CROSS JOIN bounds
                JOIN market_store.{bars_table} AS prior
                  ON prior.symbol = wanted.symbol{prior_type_join}
                WHERE prior.frequency = '1d'
                  AND substr(prior.timestamp, 1, 10) < bounds.start_date
                  AND prior.close > 0{bar_as_of_prior}
                GROUP BY prior.symbol, prior.instrument_type
            )""")
        observations.append(f"""
            SELECT
                bars.symbol,
                bars.instrument_type,
                substr(bars.timestamp, 1, 10) AS trade_date,
                bars.timestamp,
                bars.close AS price,
                'market_bars' AS source,
                CASE WHEN bars.instrument_type = 'open_end_fund'
                     THEN 'fund' ELSE bars.instrument_type END AS asset_class,
                NULL AS generation_id,
                bars.identity_provenance,
                'bar' AS kind,
                NULL AS nav_date,
                'confirmed' AS quote_status,
                'live' AS provider_status,
                NULL AS stale_reason,
                {bar_captured} AS captured_at,
                0 AS row_id
            FROM requested AS wanted
            CROSS JOIN bounds
            JOIN market_store.{bars_table} AS bars
              ON bars.symbol = wanted.symbol{type_join}
            LEFT JOIN prior_bar_cutoffs AS prior_cut
              ON prior_cut.symbol = bars.symbol
             AND prior_cut.instrument_type = bars.instrument_type
            WHERE bars.frequency = '1d'
              AND substr(bars.timestamp, 1, 10) <= bounds.end_date
              AND bars.close > 0{bar_as_of_main}
              AND (
                  substr(bars.timestamp, 1, 10) >= bounds.start_date
                  OR substr(bars.timestamp, 1, 10) = prior_cut.prior_date
              )
            """)
    if include_daily_closes:
        type_join = (
            ""
            if is_symbol_query
            else "\n             AND wanted.instrument_type = closes.instrument_type"
        )
        prior_type_join = (
            ""
            if is_symbol_query
            else "\n             AND wanted.instrument_type = prior.instrument_type"
        )
        close_as_of_prior = ""
        close_as_of_main = ""
        if as_of_utc_ms is not None:
            close_as_of_prior = (
                f"\n              AND prior.captured_at IS NOT NULL "
                f"AND trim(prior.captured_at) != '' "
                f"AND {sql_utc_timestamp_ms_expr('prior.captured_at')} <= ?"
            )
            close_as_of_main = (
                f"\n              AND closes.captured_at IS NOT NULL "
                f"AND trim(closes.captured_at) != '' "
                f"AND {sql_utc_timestamp_ms_expr('closes.captured_at')} <= ?"
            )
            cte_params.append(as_of_utc_ms)
            arm_params.append(as_of_utc_ms)
        ctes.append(f"""
            prior_close_cutoffs AS (
                SELECT
                    prior.symbol,
                    prior.instrument_type,
                    MAX(prior.trade_date) AS prior_date
                FROM requested AS wanted
                CROSS JOIN bounds
                JOIN daily_close_snapshots_v2 AS prior
                  ON prior.symbol = wanted.symbol{prior_type_join}
                WHERE prior.trade_date < bounds.start_date
                  AND prior.close_price > 0{close_as_of_prior}
                GROUP BY prior.symbol, prior.instrument_type
            )""")
        observations.append(f"""
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
                'close' AS kind,
                NULL AS nav_date,
                NULL AS quote_status,
                'live' AS provider_status,
                NULL AS stale_reason,
                closes.captured_at AS captured_at,
                closes.id AS row_id
            FROM requested AS wanted
            CROSS JOIN bounds
            JOIN daily_close_snapshots_v2 AS closes
              ON closes.symbol = wanted.symbol{type_join}
            LEFT JOIN prior_close_cutoffs AS prior_cut
              ON prior_cut.symbol = closes.symbol
             AND prior_cut.instrument_type = closes.instrument_type
            WHERE closes.trade_date <= bounds.end_date
              AND closes.close_price > 0{close_as_of_main}
              AND (
                  closes.trade_date >= bounds.start_date
                  OR closes.trade_date = prior_cut.prior_date
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
        effective_date = _quote_effective_date_sql(
            "quotes", quote_columns, normalized_type
        )
        prior_effective_date = _quote_effective_date_sql(
            "prior", quote_columns, prior_normalized_type
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
        nav_col = "quotes.nav_date" if "nav_date" in quote_columns else "NULL"
        status_col = (
            "quotes.quote_status" if "quote_status" in quote_columns else "NULL"
        )
        provider_status_col = (
            "quotes.provider_status" if "provider_status" in quote_columns else "'live'"
        )
        stale_col = "quotes.stale_reason" if "stale_reason" in quote_columns else "NULL"
        created_col = "quotes.created_at" if "created_at" in quote_columns else "NULL"
        quote_as_of_prior = ""
        quote_as_of_main = ""
        if as_of_utc_ms is not None and "created_at" in quote_columns:
            quote_as_of_prior = (
                f"\n              AND prior.created_at IS NOT NULL "
                f"AND trim(prior.created_at) != '' "
                f"AND {sql_utc_timestamp_ms_expr('prior.created_at')} <= ?"
            )
            quote_as_of_main = (
                f"\n              AND quotes.created_at IS NOT NULL "
                f"AND trim(quotes.created_at) != '' "
                f"AND {sql_utc_timestamp_ms_expr('quotes.created_at')} <= ?"
            )
            cte_params.append(as_of_utc_ms)
            arm_params.append(as_of_utc_ms)
        type_join = (
            ""
            if is_symbol_query
            else f"\n             AND wanted.instrument_type = {normalized_type}"
        )
        prior_type_join = (
            ""
            if is_symbol_query
            else f"\n             AND wanted.instrument_type = {prior_normalized_type}"
        )
        ctes.append(f"""
            prior_quote_cutoffs AS (
                SELECT
                    prior.symbol,
                    {prior_normalized_type} AS instrument_type,
                    MAX({prior_effective_date}) AS prior_date
                FROM requested AS wanted
                CROSS JOIN bounds
                JOIN quote_snapshots AS prior
                  ON prior.symbol = wanted.symbol{prior_type_join}
                WHERE {prior_effective_date} IS NOT NULL
                  AND {prior_effective_date} < bounds.start_date
                  AND prior.price > 0{quote_as_of_prior}
                GROUP BY prior.symbol, {prior_normalized_type}
            )""")
        observations.append(f"""
            SELECT
                quotes.symbol,
                {normalized_type} AS instrument_type,
                {effective_date} AS trade_date,
                quotes.timestamp,
                quotes.price,
                COALESCE(quotes.quote_source, 'quote_snapshots') AS source,
                CASE WHEN {normalized_type} = 'open_end_fund'
                     THEN 'fund' ELSE {normalized_type} END AS asset_class,
                NULL AS generation_id,
                {provenance} AS identity_provenance,
                'quote' AS kind,
                {nav_col} AS nav_date,
                {status_col} AS quote_status,
                {provider_status_col} AS provider_status,
                {stale_col} AS stale_reason,
                {created_col} AS captured_at,
                quotes.id AS row_id
            FROM requested AS wanted
            CROSS JOIN bounds
            JOIN quote_snapshots AS quotes
              ON quotes.symbol = wanted.symbol{type_join}
            LEFT JOIN prior_quote_cutoffs AS prior_cut
              ON prior_cut.symbol = quotes.symbol
             AND prior_cut.instrument_type = {normalized_type}
            WHERE {effective_date} IS NOT NULL
              AND {effective_date} <= bounds.end_date
              AND quotes.price > 0{quote_as_of_main}
              AND (
                  {effective_date} >= bounds.start_date
                  OR {effective_date} = prior_cut.prior_date
              )
            """)
    requested_def = (
        f"requested(symbol) AS (\n            VALUES {_requested_values(identity_count, 1)}\n        )"
        if is_symbol_query
        else f"requested(symbol, instrument_type) AS (\n            VALUES {_requested_values(identity_count, 2)}\n        )"
    )
    if not observations:
        return (
            f"""
                WITH {requested_def}, bounds(start_date, end_date) AS (VALUES (?, ?))
                SELECT NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                       NULL, NULL, NULL, NULL, NULL, NULL
                WHERE 0
            """,
            [],
        )
    cte_block = ",\n        ".join(ctes)
    unioned = "\nUNION ALL\n".join(observations)
    return (
        f"""
            WITH {requested_def},
            bounds(start_date, end_date) AS (VALUES (?, ?)),
            {cte_block},
            observations AS (
                {unioned}
            )
            SELECT
                symbol, instrument_type, trade_date, timestamp, price, source,
                asset_class, generation_id, identity_provenance, kind,
                nav_date, quote_status, provider_status, stale_reason,
                captured_at, row_id
            FROM observations
            ORDER BY symbol, instrument_type, trade_date, timestamp, row_id
        """,
        [*cte_params, *arm_params],
    )


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
        "kind": None if len(row) <= 9 or row[9] is None else str(row[9]),
        "nav_date": None if len(row) <= 10 or row[10] is None else str(row[10]),
        "quote_status": None if len(row) <= 11 or row[11] is None else str(row[11]),
        "provider_status": None if len(row) <= 12 or row[12] is None else str(row[12]),
        "stale_reason": None if len(row) <= 13 or row[13] is None else str(row[13]),
        "captured_at": None if len(row) <= 14 or row[14] is None else str(row[14]),
        "id": 0 if len(row) <= 15 or row[15] is None else int(row[15]),
    }


def _requested_values(count: int, arity: int) -> str:
    item = f"({', '.join('?' for _ in range(arity))})"
    return ", ".join(item for _ in range(count))


def _read_only_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _table_columns(
    conn: sqlite3.Connection, table: str, *, schema: str | None = None
) -> set[str]:
    exists = (
        _attached_table_exists(conn, schema=schema, table=table)
        if schema is not None
        else _table_exists(conn, table)
    )
    if not exists:
        return set()
    pragma = (
        f"PRAGMA {schema}.table_info({table})"
        if schema
        else f"PRAGMA table_info({table})"
    )
    return {str(row[1]) for row in conn.execute(pragma)}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
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
            f"SELECT 1 FROM {schema}.sqlite_master WHERE type IN ('table', 'view') AND name = ?",
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
