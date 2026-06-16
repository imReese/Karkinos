"""DataStore — Parquet mirror + SQLite market-data storage engine."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.types import BarFrequency, Symbol

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
_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


class DataStore:
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
    ) -> None:
        """保存 K 线数据到 SQLite，并保留 Parquet 镜像。"""
        freq_dir = self._root / "bars" / frequency.value
        freq_dir.mkdir(parents=True, exist_ok=True)
        path = freq_dir / f"{symbol}.parquet"
        df.to_parquet(path, index=False)
        self._save_bars_to_db(symbol, frequency, df)
        provider_name = _metadata_value(df, "provider_name", provider_name)
        data_source = _metadata_value(df, "data_source", data_source or provider_name)
        adjustment_mode = _metadata_value(df, "adjustment_mode", adjustment_mode)
        self._save_bar_meta(
            symbol,
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
    ) -> pd.DataFrame | None:
        """从 Parquet 加载 K 线数据。"""
        db_df = self._load_bars_from_db(symbol, frequency)
        if db_df is not None:
            return db_df

        path = self._root / "bars" / frequency.value / f"{symbol}.parquet"
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
    ) -> None:
        """追加 K 线数据到已有 Parquet，按 timestamp 去重排序。"""
        existing = self.load_bars(symbol, frequency)

        if existing is None or existing.empty:
            self.save_bars(
                symbol,
                frequency,
                new_df,
                provider_name=provider_name,
                data_source=data_source,
                adjustment_mode=adjustment_mode,
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
        )

    def sync_parquet_bars_to_database(
        self,
        frequency: BarFrequency | None = None,
        *,
        data_source: str = "local_parquet_sync",
    ) -> dict[str, object]:
        """Import existing Parquet bar mirrors into SQLite.

        This is idempotent and does not fetch remote data. It is intended for
        local cache migrations where historical bars already exist under
        ``bars/<frequency>/<symbol>.parquet`` and must be made queryable from
        the authoritative ``market_bars`` table.
        """
        frequencies = (
            [frequency] if frequency is not None else self._list_bar_frequencies()
        )
        files: list[dict[str, object]] = []
        synced_rows = 0

        for bar_frequency in frequencies:
            freq_dir = self._root / "bars" / bar_frequency.value
            if not freq_dir.exists():
                continue
            for path in sorted(freq_dir.glob("*.parquet")):
                symbol = Symbol(path.stem)
                df = pd.read_parquet(path)
                self._save_bars_to_db(symbol, bar_frequency, df)
                provider_name = _metadata_value(df, "provider_name", None)
                frame_data_source = _metadata_value(df, "data_source", None)
                adjustment_mode = _metadata_value(df, "adjustment_mode", None)
                self._save_bar_meta(
                    symbol,
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

    def get_meta(self, symbol: Symbol, frequency: BarFrequency) -> dict | None:
        """获取行情元数据。"""
        with sqlite3.connect(self._meta_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM bar_meta WHERE symbol=? AND frequency=?",
                (str(symbol), frequency.value),
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
        symbol: Symbol,
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
                """INSERT OR REPLACE INTO bar_meta
                   (
                       symbol, frequency, start_date, end_date, last_updated,
                       row_count, provider_name, data_source, adjustment_mode,
                       fetched_at, dataset_id, diagnostics_json,
                       duplicate_timestamp_count, missing_ohlcv_count,
                       is_monotonic
                   )
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(symbol),
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
                        symbol,
                        frequency,
                        df,
                        provider_name=provider_name,
                        data_source=data_source,
                        adjustment_mode=adjustment_mode,
                        start=start,
                        end=end,
                        diagnostics=diagnostics,
                    ),
                    json.dumps(diagnostics, sort_keys=True),
                    diagnostics["duplicate_timestamp_count"],
                    diagnostics["missing_ohlcv_count"],
                    int(diagnostics["is_monotonic"]),
                ),
            )

    # ---------- 辅助 ----------

    def list_symbols(
        self, frequency: BarFrequency = BarFrequency.DAILY
    ) -> list[Symbol]:
        """列出已存储的标的。"""
        symbols: set[Symbol] = set()
        with sqlite3.connect(self._meta_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT symbol FROM market_bars WHERE frequency = ?",
                (frequency.value,),
            ).fetchall()
            symbols.update(Symbol(str(row[0])) for row in rows)

        freq_dir = self._root / "bars" / frequency.value
        if freq_dir.exists():
            symbols.update(Symbol(p.stem) for p in freq_dir.glob("*.parquet"))
        return sorted(symbols, key=str)

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
        symbol: Symbol,
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
                    str(symbol),
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
                )
            )

        with sqlite3.connect(self._meta_path) as conn:
            conn.executemany(
                """
                INSERT INTO market_bars (
                    symbol, frequency, timestamp, open, high, low, close,
                    volume, amount, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, frequency, timestamp) DO UPDATE SET
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
    ) -> pd.DataFrame | None:
        with sqlite3.connect(self._meta_path) as conn:
            df = pd.read_sql_query(
                """
                SELECT timestamp, open, high, low, close, volume, amount
                FROM market_bars
                WHERE symbol = ? AND frequency = ?
                ORDER BY timestamp ASC
                """,
                conn,
                params=(str(symbol), frequency.value),
            )
        if df.empty:
            return None
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df


def _nullable_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _metadata_value(
    df: pd.DataFrame,
    key: str,
    explicit_value: str | None,
) -> str:
    if explicit_value is not None:
        return str(explicit_value)
    value = df.attrs.get(key)
    if value is None:
        return ""
    return str(value)


def _build_bar_diagnostics(df: pd.DataFrame) -> dict:
    row_count = len(df)
    if "timestamp" in df.columns:
        timestamps = pd.to_datetime(df["timestamp"])
        duplicate_timestamp_count = int(timestamps.duplicated(keep="first").sum())
        is_monotonic = bool(timestamps.is_monotonic_increasing)
    else:
        duplicate_timestamp_count = 0
        is_monotonic = True

    missing_ohlcv_count = 0
    for column in _OHLCV_COLUMNS:
        if column in df.columns:
            missing_ohlcv_count += int(df[column].isna().sum())
        else:
            missing_ohlcv_count += row_count

    return {
        "duplicate_timestamp_count": duplicate_timestamp_count,
        "missing_ohlcv_count": missing_ohlcv_count,
        "is_monotonic": is_monotonic,
        "row_count": row_count,
    }


def _build_dataset_id(
    symbol: Symbol,
    frequency: BarFrequency,
    df: pd.DataFrame,
    *,
    provider_name: str,
    data_source: str,
    adjustment_mode: str,
    start: str,
    end: str,
    diagnostics: dict,
) -> str:
    payload = {
        "symbol": str(symbol),
        "frequency": frequency.value,
        "provider_name": provider_name,
        "data_source": data_source,
        "adjustment_mode": adjustment_mode,
        "start_date": start,
        "end_date": end,
        "row_count": len(df),
        "diagnostics": diagnostics,
        "content_hash": _dataframe_content_hash(df),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dataframe_content_hash(df: pd.DataFrame) -> str:
    normalized = df.copy()
    if "timestamp" in normalized.columns:
        normalized["timestamp"] = pd.to_datetime(normalized["timestamp"]).map(
            lambda value: value.isoformat()
        )
    records = normalized.to_dict(orient="records")
    encoded = json.dumps(records, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_diagnostics(value) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
