"""DataStore — Parquet mirror + SQLite market-data storage engine."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.types import BarFrequency, InstrumentKey, InstrumentType, Symbol
from data.market_bar_identity import (
    ensure_market_bar_v2_schema,
    migrate_legacy_market_bars_to_v2,
)
from data.market_daily_store import (
    MarketDailyIngestionMixin,
)
from data.market_daily_store import build_bar_diagnostics as _build_bar_diagnostics
from data.market_daily_store import build_dataset_id as _build_dataset_id
from data.market_daily_store import metadata_value as _metadata_value
from data.market_daily_store import nullable_float as _nullable_float
from data.market_daily_store import parse_diagnostics as _parse_diagnostics

build_bar_diagnostics = _build_bar_diagnostics

_BAR_META_AUDIT_COLUMNS = {
    "provider_name": "TEXT",
    "data_source": "TEXT",
    "adjustment_mode": "TEXT",
    "fetched_at": "TEXT",
    "dataset_id": "TEXT",
    "diagnostics_json": "TEXT",
    "duplicate_timestamp_count": "INTEGER DEFAULT 0",
    "missing_ohlcv_count": "INTEGER DEFAULT 0",
    "is_monotonic": "INTEGER DEFAULT 1",
}


class DataStore(MarketDailyIngestionMixin):
    """数据存储引擎。

    - SQLite stores historical market bars and metadata.
    - Parquet remains a local cache mirror for compatibility and inspection.
    """

    def __init__(self, root: str | Path = "data/store") -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._meta_path = self._root / "meta.db"
        self._init_meta_db()

    def _init_meta_db(self) -> None:
        with sqlite3.connect(self._meta_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bar_meta (
                    symbol TEXT NOT NULL,
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
                    PRIMARY KEY (symbol, frequency)
                )
            """)
            self._ensure_bar_meta_audit_columns(conn)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_bars (
                    symbol TEXT NOT NULL,
                    frequency TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL NOT NULL,
                    volume REAL,
                    amount REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, frequency, timestamp)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_bars_symbol_frequency_ts
                ON market_bars(symbol, frequency, timestamp)
            """)
            ensure_market_bar_v2_schema(conn)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_universe_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    trade_date TEXT NOT NULL,
                    provider_name TEXT NOT NULL,
                    member_count INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(trade_date, provider_name)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_universe_snapshots_date
                ON market_universe_snapshots(trade_date DESC, created_at DESC)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_daily_ingestion_receipts (
                    trade_date TEXT NOT NULL,
                    provider_name TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    dataset_fingerprint TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (trade_date, provider_name)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_daily_receipts_date
                ON market_daily_ingestion_receipts(trade_date DESC)
            """)

    # ---------- 行情数据 ----------

    def save_bars(
        self,
        symbol: Symbol,
        frequency: BarFrequency,
        df: pd.DataFrame,
        *,
        provider_name: str | None = None,
        data_source: str | None = None,
        adjustment_mode: str | None = None,
        instrument_type: InstrumentType | str,
    ) -> None:
        """Persist bars under an exact identity in typed v2 storage."""
        key = InstrumentKey.from_values(symbol, instrument_type)
        freq_dir = self._root / "bars" / frequency.value / key.instrument_type.value
        freq_dir.mkdir(parents=True, exist_ok=True)
        path = freq_dir / f"{key.symbol}.parquet"
        df.to_parquet(path, index=False)
        self._save_bars_to_db(key, frequency, df)
        provider_name = _metadata_value(df, "provider_name", provider_name)
        data_source = _metadata_value(df, "data_source", data_source or provider_name)
        adjustment_mode = _metadata_value(df, "adjustment_mode", adjustment_mode)
        self._save_bar_meta(
            key,
            frequency,
            df,
            provider_name=provider_name,
            data_source=data_source,
            adjustment_mode=adjustment_mode,
        )

    def load_bars(
        self,
        symbol: Symbol,
        frequency: BarFrequency = BarFrequency.DAILY,
        *,
        instrument_type: InstrumentType | str | None = None,
    ) -> pd.DataFrame | None:
        """Load exact v2 bars, or read the legacy source when type is omitted."""
        key = (
            None
            if instrument_type is None
            else InstrumentKey.from_values(symbol, instrument_type)
        )
        db_df = self._load_bars_from_db(symbol, frequency, key=key)
        if db_df is not None:
            return db_df

        path = (
            self._root / "bars" / frequency.value / f"{symbol}.parquet"
            if key is None
            else self._root
            / "bars"
            / frequency.value
            / key.instrument_type.value
            / f"{key.symbol}.parquet"
        )
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df

    def append_bars(
        self,
        symbol: Symbol,
        frequency: BarFrequency,
        new_df: pd.DataFrame,
        *,
        provider_name: str | None = None,
        data_source: str | None = None,
        adjustment_mode: str | None = None,
        instrument_type: InstrumentType | str,
    ) -> None:
        """Append bars to one exact v2 identity."""
        key = InstrumentKey.from_values(symbol, instrument_type)
        existing = self.load_bars(
            symbol,
            frequency,
            instrument_type=key.instrument_type,
        )

        if existing is None or existing.empty:
            self.save_bars(
                symbol,
                frequency,
                new_df,
                provider_name=provider_name,
                data_source=data_source,
                adjustment_mode=adjustment_mode,
                instrument_type=key.instrument_type,
            )
            return

        combined = pd.concat([existing, new_df], ignore_index=True)
        if "timestamp" in combined.columns:
            combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
            combined = combined.sort_values("timestamp").reset_index(drop=True)

        self.save_bars(
            symbol,
            frequency,
            combined,
            provider_name=_metadata_value(new_df, "provider_name", provider_name),
            data_source=_metadata_value(new_df, "data_source", data_source),
            adjustment_mode=_metadata_value(new_df, "adjustment_mode", adjustment_mode),
            instrument_type=key.instrument_type,
        )

    def sync_parquet_bars_to_database(
        self,
        frequency: BarFrequency | None = None,
        *,
        instrument_type: InstrumentType | str,
        data_source: str = "local_parquet_sync",
    ) -> dict[str, object]:
        """Import existing Parquet bar mirrors into SQLite.

        This is idempotent and does not fetch remote data. It is intended for
        local cache migrations where historical bars already exist under
        ``bars/<frequency>/<instrument_type>/<symbol>.parquet`` and must be
        made queryable from the typed ``market_bars_v2`` table.
        """
        resolved_type = InstrumentType.from_persisted(
            instrument_type.value
            if isinstance(instrument_type, InstrumentType)
            else instrument_type
        )
        frequencies = (
            [frequency] if frequency is not None else self._list_bar_frequencies()
        )
        files: list[dict[str, object]] = []
        synced_rows = 0

        for bar_frequency in frequencies:
            freq_dir = self._root / "bars" / bar_frequency.value / resolved_type.value
            if not freq_dir.exists():
                continue
            for path in sorted(freq_dir.glob("*.parquet")):
                symbol = Symbol(path.stem)
                df = pd.read_parquet(path)
                key = InstrumentKey(str(symbol), resolved_type)
                self._save_bars_to_db(key, bar_frequency, df)
                provider_name = _metadata_value(df, "provider_name", None)
                frame_data_source = _metadata_value(df, "data_source", None)
                adjustment_mode = _metadata_value(df, "adjustment_mode", None)
                self._save_bar_meta(
                    key,
                    bar_frequency,
                    df,
                    provider_name=provider_name,
                    data_source=frame_data_source or data_source,
                    adjustment_mode=adjustment_mode,
                )
                row_count = len(df)
                synced_rows += row_count
                files.append(
                    {
                        "symbol": str(symbol),
                        "instrument_type": resolved_type.value,
                        "frequency": bar_frequency.value,
                        "rows": row_count,
                        "path": str(path),
                    }
                )

        return {
            "synced_files": len(files),
            "synced_rows": synced_rows,
            "files": files,
        }

    def get_meta(
        self,
        symbol: Symbol,
        frequency: BarFrequency,
        *,
        instrument_type: InstrumentType | str | None = None,
    ) -> dict | None:
        """Read exact v2 metadata, or the read-only legacy source."""
        with sqlite3.connect(self._meta_path) as conn:
            conn.row_factory = sqlite3.Row
            if instrument_type is None:
                row = conn.execute(
                    "SELECT * FROM bar_meta WHERE symbol=? AND frequency=?",
                    (str(symbol), frequency.value),
                ).fetchone()
            else:
                key = InstrumentKey.from_values(symbol, instrument_type)
                row = conn.execute(
                    """
                    SELECT * FROM bar_meta_v2
                    WHERE symbol=? AND instrument_type=? AND frequency=?
                    """,
                    (*key.storage_tuple(), frequency.value),
                ).fetchone()
            if row is None:
                return None
            meta = dict(row)
            meta["diagnostics"] = _parse_diagnostics(meta.get("diagnostics_json"))
            return meta

    def _ensure_bar_meta_audit_columns(self, conn: sqlite3.Connection) -> None:
        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(bar_meta)").fetchall()
        }
        for column, definition in _BAR_META_AUDIT_COLUMNS.items():
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE bar_meta ADD COLUMN {column} {definition}")

    def _save_bar_meta(
        self,
        key: InstrumentKey,
        frequency: BarFrequency,
        df: pd.DataFrame,
        *,
        provider_name: str,
        data_source: str,
        adjustment_mode: str,
    ) -> None:
        diagnostics = _build_bar_diagnostics(df)
        fetched_at = datetime.now().isoformat()

        if "timestamp" in df.columns and len(df) > 0:
            start = str(df["timestamp"].min())
            end = str(df["timestamp"].max())
        else:
            start = end = ""

        with sqlite3.connect(self._meta_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO bar_meta_v2
                   (
                       symbol, instrument_type, frequency,
                       start_date, end_date, last_updated,
                       row_count, provider_name, data_source, adjustment_mode,
                       fetched_at, dataset_id, diagnostics_json,
                       duplicate_timestamp_count, missing_ohlcv_count,
                       is_monotonic, identity_provenance
                   )
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    key.symbol,
                    key.instrument_type.value,
                    frequency.value,
                    start,
                    end,
                    fetched_at,
                    len(df),
                    provider_name,
                    data_source,
                    adjustment_mode,
                    fetched_at,
                    _build_dataset_id(
                        Symbol(key.symbol),
                        frequency,
                        df,
                        provider_name=provider_name,
                        data_source=data_source,
                        adjustment_mode=adjustment_mode,
                        start=start,
                        end=end,
                        diagnostics=diagnostics,
                        instrument_type=key.instrument_type,
                    ),
                    json.dumps(diagnostics, sort_keys=True),
                    diagnostics["duplicate_timestamp_count"],
                    diagnostics["missing_ohlcv_count"],
                    int(diagnostics["is_monotonic"]),
                    "explicit_canonical",
                ),
            )

    # ---------- 辅助 ----------

    def list_symbols(
        self,
        frequency: BarFrequency = BarFrequency.DAILY,
        *,
        instrument_type: InstrumentType | str | None = None,
    ) -> list[Symbol]:
        """List symbols, optionally within one exact identity namespace."""
        symbols: set[Symbol] = set()
        with sqlite3.connect(self._meta_path) as conn:
            if instrument_type is None:
                rows = conn.execute(
                    "SELECT DISTINCT symbol FROM market_bars WHERE frequency = ?",
                    (frequency.value,),
                ).fetchall()
            else:
                resolved_type = InstrumentType.from_persisted(
                    instrument_type.value
                    if isinstance(instrument_type, InstrumentType)
                    else instrument_type
                )
                rows = conn.execute(
                    """
                    SELECT DISTINCT symbol FROM market_bars_v2
                    WHERE instrument_type = ? AND frequency = ?
                    """,
                    (resolved_type.value, frequency.value),
                ).fetchall()
            symbols.update(Symbol(str(row[0])) for row in rows)

        freq_dir = self._root / "bars" / frequency.value
        if instrument_type is not None:
            freq_dir = freq_dir / resolved_type.value
        if freq_dir.exists():
            symbols.update(Symbol(p.stem) for p in freq_dir.glob("*.parquet"))
        return sorted(symbols, key=str)

    def save_market_universe_snapshot(
        self,
        *,
        trade_date: str,
        provider_name: str,
        members: list[dict[str, object]],
    ) -> dict[str, object]:
        """Persist one immutable, content-addressed market-universe snapshot."""
        normalized_date = str(trade_date).strip()
        normalized_provider = str(provider_name).strip()
        if not normalized_date or not normalized_provider or not members:
            raise ValueError("market_universe_snapshot_input_invalid")
        normalized_members = sorted(
            (dict(member) for member in members),
            key=lambda member: str(member.get("symbol") or ""),
        )
        if any(
            not str(member.get("symbol") or "").strip() for member in normalized_members
        ):
            raise ValueError("market_universe_member_symbol_invalid")
        if len({str(member["symbol"]) for member in normalized_members}) != len(
            normalized_members
        ):
            raise ValueError("market_universe_member_duplicate")
        core = {
            "schema_version": "karkinos.market_universe_snapshot.v1",
            "trade_date": normalized_date,
            "provider_name": normalized_provider,
            "asset_scope": ["stock"],
            "members": normalized_members,
            "member_count": len(normalized_members),
            "provider_contact_performed_during_ingestion": True,
            "read_endpoints_contact_providers": False,
            "authorizes_strategy_promotion": False,
            "authorizes_order_creation": False,
            "changes_capital_authority": False,
        }
        canonical = json.dumps(
            core,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        snapshot_id = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        payload = {**core, "snapshot_id": snapshot_id}
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        now = datetime.now().isoformat()
        with sqlite3.connect(self._meta_path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT * FROM market_universe_snapshots
                WHERE trade_date = ? AND provider_name = ?
                """,
                (normalized_date, normalized_provider),
            ).fetchone()
            if existing is not None:
                if str(existing["snapshot_id"]) != snapshot_id:
                    raise ValueError("market_universe_snapshot_conflict")
                return json.loads(str(existing["snapshot_json"]))
            conn.execute(
                """
                INSERT INTO market_universe_snapshots
                    (snapshot_id, trade_date, provider_name, member_count,
                     snapshot_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    normalized_date,
                    normalized_provider,
                    len(normalized_members),
                    payload_json,
                    now,
                ),
            )
        return payload

    def get_market_universe_snapshot(
        self,
        *,
        trade_date: str | None = None,
    ) -> dict[str, object] | None:
        """Read the exact-date or latest immutable market-universe snapshot."""
        query = """
            SELECT snapshot_json FROM market_universe_snapshots
            {where_clause}
            ORDER BY trade_date DESC, created_at DESC
            LIMIT 1
        """
        where_clause = "WHERE trade_date = ?" if trade_date is not None else ""
        params = (str(trade_date),) if trade_date is not None else ()
        with sqlite3.connect(self._meta_path) as conn:
            row = conn.execute(
                query.format(where_clause=where_clause), params
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row[0]))
        return payload if isinstance(payload, dict) else None

    def _list_bar_frequencies(self) -> list[BarFrequency]:
        bars_root = self._root / "bars"
        if not bars_root.exists():
            return []

        frequencies: list[BarFrequency] = []
        for freq_dir in sorted(path for path in bars_root.iterdir() if path.is_dir()):
            try:
                frequencies.append(BarFrequency(freq_dir.name))
            except ValueError:
                continue
        return frequencies

    def _save_bars_to_db(
        self,
        key: InstrumentKey,
        frequency: BarFrequency,
        df: pd.DataFrame,
    ) -> None:
        if df.empty or "timestamp" not in df.columns or "close" not in df.columns:
            return

        normalized = df.copy()
        normalized["timestamp"] = pd.to_datetime(normalized["timestamp"])
        now = datetime.now().isoformat()
        rows = []
        for _, row in normalized.iterrows():
            rows.append(
                (
                    key.symbol,
                    key.instrument_type.value,
                    frequency.value,
                    row["timestamp"].isoformat(),
                    _nullable_float(row.get("open")),
                    _nullable_float(row.get("high")),
                    _nullable_float(row.get("low")),
                    _nullable_float(row.get("close")),
                    _nullable_float(row.get("volume")),
                    _nullable_float(row.get("amount")),
                    now,
                    now,
                    "explicit_canonical",
                )
            )

        with sqlite3.connect(self._meta_path) as conn:
            conn.executemany(
                """
                INSERT INTO market_bars_v2 (
                    symbol, instrument_type, frequency, timestamp,
                    open, high, low, close, volume, amount,
                    created_at, updated_at, identity_provenance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, instrument_type, frequency, timestamp)
                DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    amount = excluded.amount,
                    updated_at = excluded.updated_at
                """,
                rows,
            )

    def _load_bars_from_db(
        self,
        symbol: Symbol,
        frequency: BarFrequency,
        *,
        key: InstrumentKey | None,
    ) -> pd.DataFrame | None:
        with sqlite3.connect(self._meta_path) as conn:
            if key is None:
                sql = """
                    SELECT timestamp, open, high, low, close, volume, amount
                    FROM market_bars
                    WHERE symbol = ? AND frequency = ?
                    ORDER BY timestamp ASC
                """
                params = (str(symbol), frequency.value)
            else:
                sql = """
                    SELECT timestamp, open, high, low, close, volume, amount
                    FROM market_bars_v2
                    WHERE symbol = ? AND instrument_type = ? AND frequency = ?
                    ORDER BY timestamp ASC
                """
                params = (*key.storage_tuple(), frequency.value)
            df = pd.read_sql_query(sql, conn, params=params)
        if df.empty:
            return None
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df

    def migrate_legacy_market_bars_to_v2(
        self,
        *,
        identity_evidence: dict[str, object] | None = None,
        dry_run: bool = True,
    ) -> dict[str, object]:
        """Plan or apply the evidence-bound legacy-to-v2 migration."""

        return migrate_legacy_market_bars_to_v2(
            self._meta_path,
            identity_evidence=identity_evidence,
            dry_run=dry_run,
        )
