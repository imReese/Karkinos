"""SQLite repository for persisted instrument identity metadata."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

_MAX_METADATA_BATCH_READ = 40


class InstrumentMetadataRepository:
    """Own instrument metadata persistence without provider behavior."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    def upsert_metadata(
        self,
        *,
        symbol: str,
        asset_type: str = "stock",
        display_name: str,
        provider_symbol: str | None = None,
        exchange: str | None = None,
        market: str | None = None,
        provider_name: str | None = None,
        source: str = "provider",
        fetched_at: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> dict[str, Any] | None:
        clean_symbol = str(symbol).strip()
        clean_name = str(display_name).strip()
        if not clean_symbol or not clean_name:
            return None
        now = datetime.now().isoformat()
        fetched_at_value = fetched_at or now
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO instrument_metadata (
                    symbol, asset_type, display_name, provider_symbol, exchange,
                    market, provider_name, source, fetched_at, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, asset_type) DO UPDATE SET
                    display_name = excluded.display_name,
                    provider_symbol = excluded.provider_symbol,
                    exchange = excluded.exchange,
                    market = excluded.market,
                    provider_name = excluded.provider_name,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    clean_symbol,
                    asset_type,
                    clean_name,
                    provider_symbol,
                    exchange,
                    market,
                    provider_name,
                    source,
                    fetched_at_value,
                    _serialize_metadata_json(metadata),
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT *
                FROM instrument_metadata
                WHERE symbol = ? AND asset_type = ?
                """,
                (clean_symbol, asset_type),
            ).fetchone()
            return dict(row) if row else None

    def upsert_metadata_batch(
        self,
        items: Sequence[Mapping[str, Any]],
    ) -> int:
        """Upsert one stock-master batch atomically in a single transaction."""
        now = datetime.now().isoformat()
        normalized: dict[tuple[str, str], tuple[Any, ...]] = {}
        for item in items:
            symbol = str(item.get("symbol") or "").strip()
            display_name = str(item.get("display_name") or "").strip()
            asset_type = str(
                item.get("asset_type") or item.get("asset_class") or "stock"
            ).strip()
            if not symbol or not display_name or not asset_type:
                continue
            fetched_at = str(item.get("fetched_at") or now)
            metadata = (
                item.get("metadata")
                if "metadata" in item
                else item.get("metadata_json")
            )
            normalized[(symbol, asset_type)] = (
                symbol,
                asset_type,
                display_name,
                _optional_text(item.get("provider_symbol")),
                _optional_text(item.get("exchange")),
                _optional_text(item.get("market")),
                _optional_text(item.get("provider_name")),
                str(item.get("source") or "provider"),
                fetched_at,
                _serialize_metadata_json(metadata),
                now,
                now,
            )
        if not normalized:
            return 0

        with sqlite3.connect(self._database_path) as conn:
            conn.executemany(
                """
                INSERT INTO instrument_metadata (
                    symbol, asset_type, display_name, provider_symbol, exchange,
                    market, provider_name, source, fetched_at, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, asset_type) DO UPDATE SET
                    display_name = excluded.display_name,
                    provider_symbol = excluded.provider_symbol,
                    exchange = excluded.exchange,
                    market = excluded.market,
                    provider_name = excluded.provider_name,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                list(normalized.values()),
            )
            conn.commit()
        return len(normalized)

    def get_metadata(
        self, symbol: str, asset_type: str | None = None
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            if asset_type:
                row = conn.execute(
                    """
                    SELECT *
                    FROM instrument_metadata
                    WHERE symbol = ? AND asset_type = ?
                    LIMIT 1
                    """,
                    (symbol, asset_type),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT *
                    FROM instrument_metadata
                    WHERE symbol = ?
                    ORDER BY fetched_at DESC, updated_at DESC, id DESC
                    LIMIT 1
                    """,
                    (symbol,),
                ).fetchone()
            return dict(row) if row else None

    def get_metadata_batch(
        self,
        symbols: Sequence[str],
        asset_type: str = "stock",
    ) -> list[dict[str, Any]]:
        """Read one bounded symbol set with one indexed ``IN`` query."""
        normalized_symbols = tuple(
            dict.fromkeys(
                str(symbol).strip() for symbol in symbols if str(symbol).strip()
            )
        )
        normalized_asset_type = str(asset_type).strip()
        if not normalized_symbols or not normalized_asset_type:
            return []
        if len(normalized_symbols) > _MAX_METADATA_BATCH_READ:
            raise ValueError("instrument_metadata_batch_read_too_large")
        placeholders = ",".join("?" for _ in normalized_symbols)
        uri = f"{self._database_path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=1.0) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            rows = conn.execute(
                f"""
                SELECT *
                FROM instrument_metadata
                WHERE symbol IN ({placeholders}) AND asset_type = ?
                ORDER BY symbol ASC
                """,  # noqa: S608 - placeholders are generated, not user input
                (*normalized_symbols, normalized_asset_type),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_metadata(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT *
                FROM instrument_metadata
                ORDER BY fetched_at DESC, updated_at DESC, id DESC
                """).fetchall()
            return [dict(row) for row in rows]


def _serialize_metadata_json(value: dict[str, Any] | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
