"""Canonical quote and market-close persistence capability."""

from __future__ import annotations

import sqlite3
from typing import Any

from core.types import InstrumentType
from server.contracts.quote_ingestion import quote_authority_conflict_fields
from server.persistence.database_serialization import serialize_metadata_json
from server.persistence.event_log import insert_event_sync
from server.persistence.financial_fact_event_payloads import (
    latest_quote_event_payload,
    quote_instant_storage_key,
    quote_observation_rank,
)
from server.persistence.market_bar_facts import (
    get_latest_market_bar_before_date,
    get_market_bar_on_date,
)
from server.persistence.market_price_matrix import read_historical_price_matrix
from server.persistence.quote_current_materialization import (
    advance_quote_snapshot_checkpoint_on_connection,
    assert_quote_current_materialization_on_connection,
    increment_quote_current_revision_on_connection,
)


def _quote_snapshot_row(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value.pop("quote_instant_utc", None)
    if not value.get("instrument_type"):
        instrument_type, provenance = _canonical_quote_identity(
            value.get("asset_class")
        )
        value["instrument_type"] = instrument_type
        value["identity_provenance"] = provenance
    if value.get("instrument_type") == "open_end_fund":
        value["asset_class"] = "fund"
    return value


def _canonical_quote_identity(raw_type: object) -> tuple[str, str]:
    normalized = str(raw_type or "").strip().lower().replace("-", "_")
    instrument_type = InstrumentType.from_persisted(normalized).value
    return (
        instrument_type,
        ("legacy_fund_compatibility" if normalized == "fund" else "explicit_canonical"),
    )


def list_quote_selection_candidates_on_connection(
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Read the write-maintained quote frontier, never append-only history."""

    assert_quote_current_materialization_on_connection(conn)
    latest_rows = conn.execute("""
        SELECT * FROM latest_quotes
        ORDER BY quote_timestamp DESC, updated_at DESC, id DESC
        """).fetchall()
    return [dict(row) for row in latest_rows]


def _advance_latest_quote_from_snapshot_on_connection(
    conn: sqlite3.Connection,
    snapshot: sqlite3.Row,
    *,
    materialized_at: str,
) -> bool:
    """Advance the current quote row for one newly appended audit observation."""

    candidate = _quote_snapshot_row(snapshot)
    existing = conn.execute(
        "SELECT * FROM latest_quotes WHERE symbol = ? AND asset_type = ?",
        (snapshot["symbol"], snapshot["asset_class"]),
    ).fetchone()
    candidate_instant = quote_observation_rank(candidate)[0]
    existing_instant = (
        quote_observation_rank(dict(existing))[0] if existing is not None else None
    )
    if existing_instant is not None and existing_instant == candidate_instant:
        conflict_fields = quote_authority_conflict_fields(dict(existing), candidate)
        if conflict_fields:
            raise ValueError(
                "quote authority facts conflict at the same timestamp: "
                + ",".join(conflict_fields)
            )
        return False
    if existing_instant is not None and existing_instant > candidate_instant:
        return False

    conn.execute(
        """
        INSERT INTO latest_quotes (
            symbol, asset_type, price, volume, quote_timestamp,
            quote_source, provider_name, provider_status, quote_status,
            stale_reason, captured_at, captured_reason, nav_date,
            fetch_run_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, asset_type) DO UPDATE SET
            price = excluded.price,
            previous_close = NULL,
            change = NULL,
            change_percent = NULL,
            volume = excluded.volume,
            turnover = NULL,
            quote_timestamp = excluded.quote_timestamp,
            quote_source = excluded.quote_source,
            provider_name = excluded.provider_name,
            provider_status = excluded.provider_status,
            quote_status = excluded.quote_status,
            stale_reason = excluded.stale_reason,
            captured_at = excluded.captured_at,
            captured_reason = excluded.captured_reason,
            nav_date = excluded.nav_date,
            fetch_run_id = excluded.fetch_run_id,
            metadata_json = NULL,
            updated_at = excluded.updated_at
        """,
        (
            snapshot["symbol"],
            snapshot["asset_class"],
            snapshot["price"],
            snapshot["volume"],
            snapshot["timestamp"],
            snapshot["quote_source"],
            snapshot["provider_name"],
            snapshot["provider_status"],
            snapshot["quote_status"] or "live",
            snapshot["stale_reason"],
            snapshot["created_at"],
            snapshot["captured_reason"],
            snapshot["nav_date"],
            snapshot["fetch_run_id"],
            materialized_at,
            materialized_at,
        ),
    )
    latest = conn.execute(
        "SELECT * FROM latest_quotes WHERE symbol = ? AND asset_type = ?",
        (snapshot["symbol"], snapshot["asset_class"]),
    ).fetchone()
    if latest is None:
        raise RuntimeError("latest quote materialization failed")
    insert_event_sync(
        conn,
        event_type="market.quote.refreshed",
        timestamp=str(snapshot["timestamp"]),
        entity_type="instrument",
        entity_id=str(snapshot["symbol"]),
        source="latest_quotes",
        source_ref=str(latest["id"]),
        payload=latest_quote_event_payload(latest),
    )
    return True


class QuoteFactsRepositoryMixin:
    def upsert_latest_quote_sync(
        self,
        *,
        symbol: str,
        asset_type: str = "stock",
        price: float,
        quote_timestamp: str,
        captured_at: str | None = None,
        previous_close: float | None = None,
        change: float | None = None,
        change_percent: float | None = None,
        volume: float | None = None,
        turnover: float | None = None,
        quote_source: str | None = None,
        provider_name: str | None = None,
        provider_status: str | None = None,
        quote_status: str = "live",
        stale_reason: str | None = None,
        captured_reason: str | None = None,
        nav_date: str | None = None,
        fetch_run_id: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> dict[str, Any] | None:
        """Upsert the current materialized quote for one instrument."""
        now = self._now().isoformat()
        captured_at_value = captured_at or now
        metadata_json = serialize_metadata_json(metadata)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                "SELECT * FROM latest_quotes WHERE symbol = ? AND asset_type = ?",
                (symbol, asset_type),
            ).fetchone()
            candidate = {
                "symbol": symbol,
                "asset_type": asset_type,
                "price": price,
                "previous_close": previous_close,
                "change": change,
                "change_percent": change_percent,
                "volume": volume,
                "turnover": turnover,
                "quote_timestamp": quote_timestamp,
                "quote_source": quote_source,
                "provider_name": provider_name,
                "provider_status": provider_status,
                "quote_status": quote_status,
                "stale_reason": stale_reason,
                "nav_date": nav_date,
            }
            candidate_instant = quote_observation_rank(candidate)[0]
            existing_instant = (
                quote_observation_rank(dict(existing))[0]
                if existing is not None
                else None
            )
            if existing_instant is not None and existing_instant == candidate_instant:
                conflict_fields = quote_authority_conflict_fields(
                    dict(existing), candidate
                )
                if conflict_fields:
                    raise ValueError(
                        "quote authority facts conflict at the same timestamp: "
                        + ",".join(conflict_fields)
                    )
            if existing_instant is not None and existing_instant > candidate_instant:
                return dict(existing)
            conn.execute(
                """
                INSERT INTO latest_quotes (
                    symbol, asset_type, price, previous_close, change,
                    change_percent, volume, turnover, quote_timestamp,
                    quote_source, provider_name, provider_status, quote_status,
                    stale_reason, captured_at, captured_reason, nav_date,
                    fetch_run_id, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, asset_type) DO UPDATE SET
                    price = excluded.price,
                    previous_close = excluded.previous_close,
                    change = excluded.change,
                    change_percent = excluded.change_percent,
                    volume = excluded.volume,
                    turnover = excluded.turnover,
                    quote_timestamp = excluded.quote_timestamp,
                    quote_source = excluded.quote_source,
                    provider_name = excluded.provider_name,
                    provider_status = excluded.provider_status,
                    quote_status = excluded.quote_status,
                    stale_reason = excluded.stale_reason,
                    captured_at = excluded.captured_at,
                    captured_reason = excluded.captured_reason,
                    nav_date = excluded.nav_date,
                    fetch_run_id = excluded.fetch_run_id,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    symbol,
                    asset_type,
                    price,
                    previous_close,
                    change,
                    change_percent,
                    volume,
                    turnover,
                    quote_timestamp,
                    quote_source,
                    provider_name,
                    provider_status,
                    quote_status,
                    stale_reason,
                    captured_at_value,
                    captured_reason,
                    nav_date,
                    fetch_run_id,
                    metadata_json,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM latest_quotes
                WHERE symbol = ? AND asset_type = ?
                """,
                (symbol, asset_type),
            ).fetchone()
            if row is not None:
                insert_event_sync(
                    conn,
                    event_type="market.quote.refreshed",
                    timestamp=row["quote_timestamp"],
                    entity_type="instrument",
                    entity_id=row["symbol"],
                    source="latest_quotes",
                    source_ref=str(row["id"]),
                    payload=latest_quote_event_payload(row),
                )
                if asset_type.strip().lower() != "index":
                    increment_quote_current_revision_on_connection(
                        conn,
                        updated_at=now,
                    )
            conn.commit()
            return dict(row) if row else None

    def get_latest_quote_sync(
        self, symbol: str, asset_type: str | None = None
    ) -> dict[str, Any] | None:
        """Read one current quote; untyped compatibility fails on ambiguity."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            assert_quote_current_materialization_on_connection(conn)
            if asset_type is None:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM latest_quotes
                    WHERE symbol = ?
                    ORDER BY quote_timestamp DESC, updated_at DESC, id DESC
                    """,
                    (symbol,),
                ).fetchall()
                canonical_types = {
                    (
                        InstrumentType.OPEN_END_FUND.value
                        if str(item["asset_type"]).strip().lower() == "fund"
                        else str(item["asset_type"]).strip().lower()
                    )
                    for item in rows
                }
                if len(canonical_types) != 1:
                    return None
                row = rows[0] if rows else None
            elif _canonical_quote_identity(asset_type)[0] == "open_end_fund":
                row = conn.execute(
                    """
                    SELECT *
                    FROM latest_quotes
                    WHERE symbol = ?
                      AND asset_type IN ('fund', 'open_end_fund')
                    ORDER BY quote_timestamp DESC, updated_at DESC, id DESC
                    LIMIT 1
                    """,
                    (symbol,),
                ).fetchone()
            else:
                resolved_type, _ = _canonical_quote_identity(asset_type)
                row = conn.execute(
                    """
                    SELECT *
                    FROM latest_quotes
                    WHERE symbol = ? AND asset_type = ?
                    LIMIT 1
                    """,
                    (symbol, resolved_type),
                ).fetchone()
            return dict(row) if row else None

    def list_latest_quotes_sync(self) -> list[dict[str, Any]]:
        """List materialized latest quotes newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            assert_quote_current_materialization_on_connection(conn)
            rows = conn.execute("""
                SELECT *
                FROM latest_quotes
                ORDER BY quote_timestamp DESC, updated_at DESC, id DESC
                """).fetchall()
            return [dict(row) for row in rows]

    def save_quote_snapshot_sync(
        self,
        symbol: str,
        asset_class: str,
        price: float,
        volume: float | None,
        timestamp: str,
        quote_source: str | None = None,
        provider_name: str | None = None,
        quote_status: str | None = None,
        stale_reason: str | None = None,
        provider_status: str | None = None,
        captured_reason: str | None = None,
        nav_date: str | None = None,
        fetch_run_id: str | None = None,
    ) -> None:
        """Append audit history and atomically advance current quote state."""
        instrument_type, identity_provenance = _canonical_quote_identity(asset_class)
        now = self._now().isoformat()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """INSERT INTO quote_snapshots
                   (
                       symbol, asset_class, price, volume, timestamp, created_at,
                       quote_source, provider_name, quote_status, stale_reason,
                       provider_status, captured_reason, nav_date, fetch_run_id,
                       quote_instant_utc, instrument_type, identity_provenance
                   )
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    symbol,
                    instrument_type,
                    price,
                    volume,
                    timestamp,
                    now,
                    quote_source,
                    provider_name,
                    quote_status,
                    stale_reason,
                    provider_status,
                    captured_reason,
                    nav_date,
                    fetch_run_id,
                    quote_instant_storage_key(timestamp),
                    instrument_type,
                    identity_provenance,
                ),
            )
            snapshot_id = cursor.lastrowid or 0
            insert_event_sync(
                conn,
                event_type="market.quote.snapshot.recorded",
                timestamp=timestamp,
                entity_type="instrument",
                entity_id=symbol,
                source="quote_snapshots",
                source_ref=str(snapshot_id),
                payload={
                    "snapshot_id": snapshot_id,
                    "symbol": symbol,
                    "asset_class": (
                        "fund"
                        if instrument_type == InstrumentType.OPEN_END_FUND.value
                        else instrument_type
                    ),
                    "instrument_type": instrument_type,
                    "identity_provenance": identity_provenance,
                    "price": price,
                    "volume": volume,
                    "timestamp": timestamp,
                    "quote_source": quote_source,
                    "provider_name": provider_name,
                    "quote_status": quote_status,
                    "stale_reason": stale_reason,
                    "provider_status": provider_status,
                    "captured_reason": captured_reason,
                    "nav_date": nav_date,
                    "fetch_run_id": fetch_run_id,
                },
            )
            snapshot = conn.execute(
                "SELECT * FROM quote_snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()
            if snapshot is None:
                raise RuntimeError("quote snapshot persistence failed")
            current_changed = _advance_latest_quote_from_snapshot_on_connection(
                conn,
                snapshot,
                materialized_at=now,
            )
            advance_quote_snapshot_checkpoint_on_connection(
                conn,
                snapshot_id=int(snapshot_id),
                current_changed=(current_changed and instrument_type != "index"),
                updated_at=now,
            )
            conn.commit()

    async def get_latest_quote(
        self,
        symbol: str,
        *,
        instrument_type: str,
    ) -> dict[str, Any] | None:
        """Read one exact identity from the current-quote materialization."""
        import asyncio

        row = await asyncio.to_thread(
            self.get_latest_quote_sync,
            symbol,
            instrument_type,
        )
        if row is None:
            return None
        raw_asset_type = str(row.get("asset_type") or "").strip().lower()
        instrument_type = (
            "open_end_fund" if raw_asset_type == "fund" else raw_asset_type
        )
        return {
            **row,
            "instrument_type": instrument_type,
            "asset_class": (
                "fund" if instrument_type == "open_end_fund" else instrument_type
            ),
            "identity_provenance": (
                "legacy_fund_compatibility"
                if raw_asset_type == "fund"
                else "persisted_canonical"
            ),
            "timestamp": row.get("quote_timestamp"),
        }

    def get_latest_quotes_sync(self) -> list[dict[str, Any]]:
        """Read current quotes without replaying append-only quote history."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            assert_quote_current_materialization_on_connection(conn)
            rows = conn.execute("""
                SELECT
                    id, symbol, asset_type,
                    CASE
                        WHEN asset_type = 'fund' THEN 'open_end_fund'
                        ELSE asset_type
                    END AS instrument_type,
                    CASE
                        WHEN asset_type IN ('fund', 'open_end_fund') THEN 'fund'
                        ELSE asset_type
                    END AS asset_class,
                    CASE
                        WHEN asset_type = 'fund' THEN 'legacy_fund_compatibility'
                        ELSE 'persisted_canonical'
                    END AS identity_provenance,
                    price, volume,
                    quote_timestamp AS timestamp,
                    quote_source, provider_name, quote_status, stale_reason,
                    provider_status, captured_reason, nav_date, fetch_run_id,
                    previous_close, change, change_percent, turnover,
                    captured_at, created_at, updated_at
                FROM latest_quotes
                ORDER BY symbol, asset_type
                """).fetchall()
            return [dict(row) for row in rows]

    def list_quote_selection_candidates_sync(self) -> list[dict[str, Any]]:
        """List the bounded persisted frontier used by canonical valuation."""

        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            return list_quote_selection_candidates_on_connection(conn)

    def list_quote_snapshots_sync(
        self,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Page append-only quote history for explicit audit workflows."""
        if limit <= 0 or limit > 5000 or offset < 0:
            raise ValueError("quote history pagination is invalid")
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM quote_snapshots ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [_quote_snapshot_row(row) for row in rows]

    def get_recent_quote_snapshots_sync(
        self,
        symbol: str,
        limit: int = 2,
        *,
        instrument_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read a bounded canonical-time page from append-only quote history."""
        if limit <= 0 or limit > 500:
            raise ValueError("recent quote snapshot limit is invalid")
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            identity_filter = ""
            params: tuple[object, ...] = (symbol,)
            if instrument_type is not None:
                resolved, _ = _canonical_quote_identity(instrument_type)
                identity_filter = "AND instrument_type = ?"
                params = (symbol, resolved)
            rows = conn.execute(
                f"""
                SELECT
                    id, symbol, asset_class, instrument_type,
                    identity_provenance, price, volume, timestamp,
                    quote_source, provider_name, quote_status, stale_reason,
                    provider_status, captured_reason, nav_date, fetch_run_id,
                    created_at
                FROM quote_snapshots
                WHERE symbol = ? AND quote_instant_utc IS NOT NULL
                {identity_filter}
                ORDER BY quote_instant_utc DESC, id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_historical_price_matrix_sync(
        self,
        *,
        instrument_keys: list[object] | None = None,
        symbols: list[str] | None = None,
        start_date: str,
        end_date: str,
        symbol_batch_size: int = 400,
    ) -> dict[str, list[dict[str, Any]]]:
        """Read a bounded multi-instrument matrix from persisted price facts."""

        return read_historical_price_matrix(
            self._path,
            instrument_keys=instrument_keys,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            symbol_batch_size=symbol_batch_size,
        )

    def save_daily_close_snapshot_sync(
        self,
        *,
        symbol: str,
        asset_class: str,
        trade_date: str,
        close_price: float,
        source: str,
    ) -> None:
        """Write one close under an exact typed identity."""
        instrument_type, identity_provenance = _canonical_quote_identity(asset_class)
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """
                INSERT INTO daily_close_snapshots_v2
                    (symbol, instrument_type, trade_date, close_price, source,
                     captured_at, identity_provenance)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, instrument_type, trade_date) DO UPDATE SET
                    close_price = excluded.close_price,
                    source = excluded.source,
                    captured_at = excluded.captured_at,
                    identity_provenance = excluded.identity_provenance
                """,
                (
                    symbol,
                    instrument_type,
                    trade_date,
                    close_price,
                    source,
                    self._now().isoformat(),
                    identity_provenance,
                ),
            )
            conn.commit()

    def get_latest_daily_close_before_sync(
        self,
        symbol: str,
        trade_date: str,
        instrument_type: str | None = None,
    ) -> dict[str, Any] | None:
        """Read an exact close; untyped compatibility fails on ambiguity."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            params: tuple[object, ...] = (symbol, trade_date)
            identity_filter = ""
            if instrument_type is not None:
                resolved, _ = _canonical_quote_identity(instrument_type)
                identity_filter = "AND instrument_type = ?"
                params = (symbol, trade_date, resolved)
            rows = conn.execute(
                f"""
                SELECT symbol, instrument_type, trade_date, close_price,
                       source, captured_at, identity_provenance
                FROM daily_close_snapshots_v2
                WHERE symbol = ? AND trade_date < ? {identity_filter}
                ORDER BY trade_date DESC, id DESC
                LIMIT 2
                """,
                params,
            ).fetchall()
            if not rows:
                return None
            newest_date = str(rows[0]["trade_date"])
            newest = [row for row in rows if str(row["trade_date"]) == newest_date]
            if (
                instrument_type is None
                and len({str(row["instrument_type"]) for row in newest}) != 1
            ):
                return None
            result = dict(newest[0])
            result["asset_class"] = (
                "fund"
                if result["instrument_type"] == "open_end_fund"
                else result["instrument_type"]
            )
            return result

    def get_latest_market_bar_before_date_sync(
        self,
        symbol: str,
        trade_date: str,
        frequency: str = "1d",
        *,
        instrument_type: str,
    ) -> dict[str, Any] | None:
        return get_latest_market_bar_before_date(
            self._path,
            symbol,
            trade_date,
            frequency,
            instrument_type=instrument_type,
        )

    def get_market_bar_on_date_sync(
        self,
        symbol: str,
        trade_date: str,
        frequency: str = "1d",
        *,
        instrument_type: str,
    ) -> dict[str, Any] | None:
        return get_market_bar_on_date(
            self._path,
            symbol,
            trade_date,
            frequency,
            instrument_type=instrument_type,
        )

    def get_latest_quote_before_date_sync(
        self,
        symbol: str,
        trade_date: str,
        *,
        instrument_type: str,
    ) -> dict[str, Any] | None:
        """Read the latest pre-date quote for one exact instrument identity."""
        resolved_type, _ = _canonical_quote_identity(instrument_type)
        instant_upper_bound = quote_instant_storage_key(f"{trade_date}T00:00:00+08:00")
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT
                    symbol, asset_class, instrument_type, identity_provenance,
                    price, volume, timestamp,
                    quote_source, provider_name, quote_status, stale_reason,
                    provider_status, captured_reason, nav_date
                FROM quote_snapshots
                WHERE symbol = ? AND instrument_type = ?
                  AND quote_instant_utc < ?
                ORDER BY quote_instant_utc DESC, id DESC
                LIMIT 1
                """,
                (symbol, resolved_type, instant_upper_bound),
            ).fetchone()
            return dict(row) if row else None


__all__ = [
    "QuoteFactsRepositoryMixin",
    "list_quote_selection_candidates_on_connection",
]
