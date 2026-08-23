"""SQLite repository for the user-managed market watchlist."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class WatchlistRepository:
    """Own watchlist persistence without market-data or scheduling behavior."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    def upsert_asset(
        self,
        *,
        symbol: str,
        asset_class: str = "stock",
        display_name: str | None = None,
        source: str = "manual",
    ) -> dict[str, Any] | None:
        clean_symbol = str(symbol).strip()
        clean_asset_class = str(asset_class or "stock").strip().lower() or "stock"
        clean_display_name = str(display_name or clean_symbol).strip() or clean_symbol
        if not clean_symbol:
            return None
        now = datetime.now().isoformat()
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO watchlist_assets (
                    symbol, asset_class, display_name, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    asset_class = excluded.asset_class,
                    display_name = excluded.display_name,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    clean_symbol,
                    clean_asset_class,
                    clean_display_name,
                    source,
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT *
                FROM watchlist_assets
                WHERE lower(symbol) = lower(?)
                LIMIT 1
                """,
                (clean_symbol,),
            ).fetchone()
            return dict(row) if row else None

    def list_assets(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT *
                FROM watchlist_assets
                ORDER BY created_at ASC, id ASC
                """).fetchall()
            return [dict(row) for row in rows]

    def delete_asset(self, symbol: str) -> bool:
        clean_symbol = str(symbol).strip()
        if not clean_symbol:
            return False
        with sqlite3.connect(self._database_path) as conn:
            cursor = conn.execute(
                "DELETE FROM watchlist_assets WHERE lower(symbol) = lower(?)",
                (clean_symbol,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def seed_from_config(self, assets: Any) -> int:
        """Migrate supported legacy asset config shapes into the watchlist."""
        seeded = 0
        if not assets:
            return seeded
        iterable = assets.items() if isinstance(assets, dict) else enumerate(assets)
        for key, raw_asset in iterable:
            if isinstance(raw_asset, str):
                symbol = str(key if not isinstance(key, int) else raw_asset).strip()
                asset_class = "stock"
                display_name = raw_asset if not isinstance(key, int) else symbol
            elif isinstance(raw_asset, dict):
                symbol = str(
                    raw_asset.get("provider_symbol")
                    or raw_asset.get("provider_code")
                    or raw_asset.get("code")
                    or raw_asset.get("symbol")
                    or ("" if isinstance(key, int) else key)
                ).strip()
                asset_class = str(raw_asset.get("asset_class") or "stock")
                display_name = str(
                    raw_asset.get("display_name")
                    or raw_asset.get("name")
                    or raw_asset.get("symbol")
                    or symbol
                )
            else:
                continue
            if not symbol:
                continue
            if self.upsert_asset(
                symbol=symbol,
                asset_class=asset_class,
                display_name=display_name,
                source="config_migration",
            ):
                seeded += 1
        return seeded
