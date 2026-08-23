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

    def ingest_market_daily_batch(
        self,
        *,
        trade_date: str,
        provider_name: str,
        bars: pd.DataFrame,
    ) -> dict[str, object]:
        """Atomically freeze one provider-returned full-market daily batch.

        The SQLite bar rows and their content-addressed receipt commit in the
        same transaction.  An existing receipt is immutable: a later provider
        correction or local row drift is rejected instead of silently changing
        a previously frozen decision input.
        """

        normalized_date = str(trade_date).strip()
        normalized_provider = str(provider_name).strip()
        if not normalized_date or not normalized_provider:
            raise ValueError("market_daily_batch_identity_invalid")
        try:
            expected_date = pd.Timestamp(normalized_date).date()
        except (TypeError, ValueError) as exc:
            raise ValueError("market_daily_batch_trade_date_invalid") from exc
        required = {"symbol", "timestamp", "open", "high", "low", "close", "volume"}
        if bars is None or bars.empty or not required.issubset(bars.columns):
            raise ValueError("market_daily_batch_incomplete")

        normalized = bars.copy()
        normalized["symbol"] = normalized["symbol"].map(
            lambda value: str(value).strip().split(".", maxsplit=1)[0]
        )
        normalized["timestamp"] = pd.to_datetime(normalized["timestamp"])
        if (
            normalized["symbol"].eq("").any()
            or normalized["symbol"].duplicated().any()
            or any(value.date() != expected_date for value in normalized["timestamp"])
        ):
            raise ValueError("market_daily_batch_membership_invalid")
        normalized = normalized.sort_values("symbol").reset_index(drop=True)
        records = _normalized_market_daily_records(normalized)
        if any(record[5] is None or record[5] <= 0 for record in records):
            raise ValueError("market_daily_batch_close_invalid")
        dataset_fingerprint = _market_daily_records_fingerprint(
            trade_date=normalized_date,
            provider_name=normalized_provider,
            records=records,
        )
        symbols = [record[0] for record in records]
        receipt_core: dict[str, object] = {
            "schema_version": "karkinos.market_daily_ingestion_receipt.v1",
            "trade_date": normalized_date,
            "provider_name": normalized_provider,
            "row_count": len(records),
            "symbols": symbols,
            "dataset_fingerprint": dataset_fingerprint,
            "storage_authority": "sqlite_market_bars",
            "parquet_mirror_required_for_decision": False,
            "provider_contact_performed_during_ingestion": True,
            "read_endpoints_contact_providers": False,
            "authorizes_strategy_promotion": False,
            "authorizes_order_creation": False,
            "changes_capital_authority": False,
        }
        receipt_fingerprint = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    receipt_core,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
        receipt = {**receipt_core, "receipt_fingerprint": receipt_fingerprint}
        receipt_json = json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        now = datetime.now().isoformat()

        with sqlite3.connect(self._meta_path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT receipt_json FROM market_daily_ingestion_receipts
                WHERE trade_date = ? AND provider_name = ?
                """,
                (normalized_date, normalized_provider),
            ).fetchone()
            if existing is not None:
                stored = json.loads(str(existing["receipt_json"]))
                if stored != receipt or not self._verify_market_daily_receipt(
                    conn, stored
                ):
                    raise ValueError("market_daily_ingestion_receipt_conflict")
                return stored

            conn.executemany(
                """
                INSERT INTO market_bars (
                    symbol, frequency, timestamp, open, high, low, close,
                    volume, amount, created_at, updated_at
                ) VALUES (?, '1d', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, frequency, timestamp) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    amount = excluded.amount,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        symbol,
                        timestamp,
                        open_price,
                        high_price,
                        low_price,
                        close_price,
                        volume,
                        amount,
                        now,
                        now,
                    )
                    for (
                        symbol,
                        timestamp,
                        open_price,
                        high_price,
                        low_price,
                        close_price,
                        volume,
                        amount,
                    ) in records
                ],
            )
            if not self._verify_market_daily_receipt(conn, receipt):
                raise ValueError("market_daily_batch_persistence_verification_failed")
            conn.execute(
                """
                INSERT INTO market_daily_ingestion_receipts (
                    trade_date, provider_name, row_count, dataset_fingerprint,
                    receipt_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_date,
                    normalized_provider,
                    len(records),
                    dataset_fingerprint,
                    receipt_json,
                    now,
                ),
            )
            conn.commit()
        return receipt

    def get_market_daily_ingestion_receipt(
        self,
        *,
        trade_date: str,
        provider_name: str,
        verify: bool = True,
    ) -> dict[str, object] | None:
        """Read one frozen full-market batch receipt and optionally replay it."""

        with sqlite3.connect(self._meta_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT receipt_json FROM market_daily_ingestion_receipts
                WHERE trade_date = ? AND provider_name = ?
                """,
                (str(trade_date), str(provider_name)),
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(str(row["receipt_json"]))
            if not isinstance(payload, dict):
                return None
            if verify and not self._verify_market_daily_receipt(conn, payload):
                raise ValueError("market_daily_ingestion_receipt_drift")
            return payload

    def list_market_daily_ingestion_receipts(
        self,
        *,
        start_date: str,
        end_date: str,
        provider_name: str,
        verify: bool = True,
    ) -> list[dict[str, object]]:
        """Read a date-ordered receipt window for deterministic replay."""

        with sqlite3.connect(self._meta_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT receipt_json FROM market_daily_ingestion_receipts
                WHERE provider_name = ? AND trade_date BETWEEN ? AND ?
                ORDER BY trade_date
                """,
                (str(provider_name), str(start_date), str(end_date)),
            ).fetchall()
            payloads = [json.loads(str(row["receipt_json"])) for row in rows]
            if any(not isinstance(payload, dict) for payload in payloads):
                raise ValueError("market_daily_ingestion_receipt_invalid")
            if verify and any(
                not self._verify_market_daily_receipt(conn, payload)
                for payload in payloads
            ):
                raise ValueError("market_daily_ingestion_receipt_drift")
            return payloads

    def load_market_bar_windows(
        self,
        *,
        symbols: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, pd.DataFrame]:
        """Load one stock-only frozen window without provider contact."""

        wanted = {str(symbol).strip() for symbol in symbols if str(symbol).strip()}
        if not wanted:
            return {}
        with sqlite3.connect(self._meta_path) as conn:
            frame = pd.read_sql_query(
                """
                SELECT symbol, timestamp, open, high, low, close, volume, amount
                FROM market_bars
                WHERE frequency = '1d'
                  AND timestamp >= ?
                  AND timestamp < ?
                ORDER BY symbol, timestamp
                """,
                conn,
                params=(
                    pd.Timestamp(start_date).isoformat(),
                    (pd.Timestamp(end_date) + pd.Timedelta(days=1)).isoformat(),
                ),
            )
        if frame.empty:
            return {}
        frame = frame.loc[frame["symbol"].isin(wanted)].copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        return {
            str(symbol): group.drop(columns=["symbol"]).reset_index(drop=True)
            for symbol, group in frame.groupby("symbol", sort=True)
        }

    @staticmethod
    def _verify_market_daily_receipt(
        conn: sqlite3.Connection,
        receipt: dict[str, object],
    ) -> bool:
        if receipt.get("schema_version") != (
            "karkinos.market_daily_ingestion_receipt.v1"
        ):
            return False
        symbols = receipt.get("symbols")
        if not isinstance(symbols, list) or not symbols:
            return False
        rows = conn.execute(
            """
            SELECT symbol, timestamp, open, high, low, close, volume, amount
            FROM market_bars
            WHERE frequency = '1d' AND substr(timestamp, 1, 10) = ?
            ORDER BY symbol
            """,
            (str(receipt.get("trade_date") or ""),),
        ).fetchall()
        wanted = set(str(symbol) for symbol in symbols)
        records = [tuple(row) for row in rows if str(row[0]) in wanted]
        if len(records) != len(symbols):
            return False
        expected_dataset_fingerprint = _market_daily_records_fingerprint(
            trade_date=str(receipt.get("trade_date") or ""),
            provider_name=str(receipt.get("provider_name") or ""),
            records=records,
        )
        if receipt.get("dataset_fingerprint") != expected_dataset_fingerprint:
            return False
        core = dict(receipt)
        stored_fingerprint = core.pop("receipt_fingerprint", None)
        return (
            stored_fingerprint
            == "sha256:"
            + hashlib.sha256(
                json.dumps(
                    core,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )

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


def _normalized_market_daily_records(
    frame: pd.DataFrame,
) -> list[tuple[object, ...]]:
    records: list[tuple[object, ...]] = []
    for _, row in frame.iterrows():
        records.append(
            (
                str(row["symbol"]),
                pd.Timestamp(row["timestamp"]).isoformat(),
                _nullable_float(row.get("open")),
                _nullable_float(row.get("high")),
                _nullable_float(row.get("low")),
                _nullable_float(row.get("close")),
                _nullable_float(row.get("volume")),
                _nullable_float(row.get("amount")),
            )
        )
    return records


def _market_daily_records_fingerprint(
    *,
    trade_date: str,
    provider_name: str,
    records: list[tuple[object, ...]],
) -> str:
    payload = {
        "schema_version": "karkinos.market_daily_dataset.v1",
        "trade_date": str(trade_date),
        "provider_name": str(provider_name),
        "records": [list(record) for record in records],
    }
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )


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
