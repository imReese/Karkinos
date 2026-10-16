"""DataStore — Parquet mirror + SQLite market-data storage engine."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from core.types import BarFrequency, InstrumentKey, InstrumentType, Symbol
from data.market_daily_store import (
    MarketDailyIngestionMixin,
    require_frozen_stock_bars_unchanged,
)
from data.market_daily_store import build_bar_diagnostics as _build_bar_diagnostics
from data.market_daily_store import build_dataset_id as _build_dataset_id
from data.market_daily_store import metadata_value as _metadata_value
from data.market_daily_store import nullable_float as _nullable_float
from data.market_daily_store import parse_diagnostics as _parse_diagnostics
from data.meta_store_connection import connect_meta_sqlite
from data.meta_store_schema import (
    meta_database_requires_preparation,
    prepare_meta_database,
)

build_bar_diagnostics = _build_bar_diagnostics


def normalize_stock_master_metadata(
    rows: Sequence[Mapping[str, Any]], members: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Retain actual adapter facts without filling missing listing/status data."""
    allowed = {str(member["symbol"]) for member in members}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("market_universe_metadata_row_invalid")
        symbol = str(row.get("symbol") or "").split(".", maxsplit=1)[0].strip()
        if symbol not in allowed:
            continue
        name = row.get("display_name")
        name = name.strip() if isinstance(name, str) and name.strip() else None
        status = row.get("list_status")
        status = status.strip() if isinstance(status, str) and status.strip() else None
        fact = {
            "symbol": symbol,
            "display_name": name,
            "list_status": status,
        }
        for field in ("list_date", "delist_date"):
            # Old v3 observations never contained delist_date. Omission keeps
            # those exact canonical bytes and identities unchanged.
            if field == "delist_date" and field not in row:
                continue
            value = row.get(field)
            fact[field] = (
                datetime.strptime(str(value), "%Y%m%d").date().isoformat()
                if value and len(str(value)) == 8
                else date.fromisoformat(str(value)).isoformat()
                if value
                else None
            )
        status_fields = {"trade_status", "status_session_date", "status_capture_id"}
        if status_fields.intersection(row):
            if not status_fields <= row.keys() or row["trade_status"] not in {"0", "1"}:
                raise ValueError("market_universe_session_status_invalid")
            fact.update(
                trade_status=row["trade_status"],
                status_session_date=date.fromisoformat(
                    str(row["status_session_date"])
                ).isoformat(),
                status_capture_id=str(row["status_capture_id"]),
            )
        if symbol in result and result[symbol] != fact:
            raise ValueError("market_universe_metadata_conflict")
        result[symbol] = fact
    return [result[symbol] for symbol in sorted(result)]


def require_stock_master_capture_evidence(objects, snapshot):
    """Replay optional official raw sources with the writer's exact projection."""
    from data.providers.eastmoney import read_official_stock_master_captures

    identities = snapshot["source_capture_ids"]
    if (
        not isinstance(identities, list)
        or not identities
        or identities != sorted(set(identities))
    ):
        raise ValueError("market_universe_source_captures_invalid")
    rows, started, completed = read_official_stock_master_captures(
        objects, identities, trade_date=snapshot["trade_date"]
    )
    members = snapshot["members"]
    if (
        len(members) != len(rows)
        or {str(row["symbol"]) for row in rows}
        != {str(row["symbol"]) for row in members}
        or snapshot["member_metadata"] != normalize_stock_master_metadata(rows, members)
        or datetime.fromisoformat(snapshot["capture_started_at"]) != started
        or datetime.fromisoformat(snapshot["capture_completed_at"]) != completed
        or datetime.fromisoformat(snapshot["available_at"]) != completed
    ):
        raise ValueError("market_universe_source_projection_mismatch")


def stock_master_nontrading_instruments(snapshot, *, session_date):
    """Derive explicitly dated status facts after their raw sources are verified."""
    refs = set(snapshot.get("source_capture_ids") or ())
    return tuple(
        sorted(
            (
                InstrumentKey.from_values(row["symbol"], "stock")
                for row in snapshot.get("member_metadata", ())
                if row.get("trade_status") == "0"
                and row.get("status_session_date") == str(session_date)
                and row.get("status_capture_id") in refs
            ),
            key=lambda key: (key.instrument_type.value, key.symbol),
        )
    )


def _market_universe_utc(value: datetime, *, field: str) -> str:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"market_universe_{field}_timezone_required")
    try:
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"market_universe_{field}_invalid") from exc


def _market_universe_capture_fields(
    started_at: datetime | None, completed_at: datetime | None
) -> dict[str, object]:
    if started_at is None and completed_at is None:
        return {}
    if started_at is None or completed_at is None:
        raise ValueError("market_universe_capture_times_incomplete")
    started = _market_universe_utc(started_at, field="capture_started_at")
    completed = _market_universe_utc(completed_at, field="capture_completed_at")
    if completed < started:
        raise ValueError("market_universe_capture_completed_before_started")
    return {
        "capture_started_at": started,
        "capture_completed_at": completed,
        "available_at": completed,
        "availability_basis": "capture_completed_at",
        "observation_basis": "adapter_response",
        "membership_basis": "current_active_stock_master",
        "trade_date_role": "daily_bar_window_end",
        "historical_membership_verified": False,
    }


def _resolve_market_table(conn: sqlite3.Connection, base: str) -> str:
    """Return the physical table name holding typed bars or metadata."""
    return base


def _market_universe_snapshot_id(core: dict[str, object]) -> str:
    canonical = json.dumps(
        core, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _verified_market_universe_row(row: sqlite3.Row) -> dict[str, object]:
    """Check content identity and denormalized lookup columns before using a row."""
    try:
        payload = json.loads(row["snapshot_json"])
        if not isinstance(payload, dict):
            raise ValueError("payload_not_object")
        core = dict(payload)
        snapshot_id = core.pop("snapshot_id")
        if snapshot_id != row[
            "snapshot_id"
        ] or snapshot_id != _market_universe_snapshot_id(core):
            raise ValueError("fingerprint_mismatch")
        for field in ("trade_date", "provider_name", "member_count"):
            if payload.get(field) != row[field]:
                raise ValueError("index_binding_mismatch")
        members = payload.get("members")
        if not isinstance(members, list) or len(members) != payload["member_count"]:
            raise ValueError("member_count_mismatch")
        time_fields = ("capture_started_at", "capture_completed_at", "available_at")
        if payload.get("schema_version") == "karkinos.market_universe_snapshot.v1":
            if any(row[field] is not None or field in payload for field in time_fields):
                raise ValueError("legacy_availability_unknown")
        elif payload.get("schema_version") in {
            "karkinos.market_universe_snapshot.v2",
            "karkinos.market_universe_snapshot.v3",
        }:
            expected = _market_universe_capture_fields(
                datetime.fromisoformat(payload["capture_started_at"]),
                datetime.fromisoformat(payload["capture_completed_at"]),
            )
            if any(payload.get(field) != value for field, value in expected.items()):
                raise ValueError("capture_binding_mismatch")
            if any(row[field] != payload[field] for field in time_fields):
                raise ValueError("capture_index_binding_mismatch")
            if (
                payload["schema_version"] == "karkinos.market_universe_snapshot.v3"
                and normalize_stock_master_metadata(payload["member_metadata"], members)
                != payload["member_metadata"]
            ):
                raise ValueError("metadata_not_canonical")
        else:
            raise ValueError("schema_unsupported")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("market_universe_snapshot_integrity_invalid") from exc
    return payload


class DataStore(MarketDailyIngestionMixin):
    """数据存储引擎。

    - SQLite stores historical market bars and metadata.
    - Parquet remains a local cache mirror for compatibility and inspection.
    """

    def __init__(self, root: str | Path = "data/store") -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._meta_path = self._root / "meta.db"
        # Runtime consumers attach to the prepared schema. Whole-file integrity
        # checks belong to explicit preparation before API/workers start; doing
        # them for every DataStore read blocks startup and each request as the
        # market cache grows. History, structure and observation-time constraints
        # are still verified here, and each financial/research reader verifies
        # the actual evidence it consumes.
        if meta_database_requires_preparation(self._meta_path, verify_integrity=False):
            prepare_meta_database(self._meta_path)

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
        """Persist bars under an exact instrument identity."""
        key = InstrumentKey.from_values(symbol, instrument_type)
        freq_dir = self._root / "bars" / frequency.value / key.instrument_type.value
        freq_dir.mkdir(parents=True, exist_ok=True)
        path = freq_dir / f"{key.symbol}.parquet"
        self._save_bars_to_db(key, frequency, df)
        df.to_parquet(path, index=False)
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
        """Load bars for the requested instrument identity."""
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
        """Append bars to one exact instrument identity."""
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
        made queryable from the typed ``market_bars`` table.
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
        """Read exact instrument metadata."""
        with connect_meta_sqlite(self._meta_path) as conn:
            conn.row_factory = sqlite3.Row
            table = _resolve_market_table(conn, "bar_meta")
            if instrument_type is None:
                row = conn.execute(
                    f"SELECT * FROM {table} WHERE symbol=? AND frequency=?",
                    (str(symbol), frequency.value),
                ).fetchone()
            else:
                key = InstrumentKey.from_values(symbol, instrument_type)
                row = conn.execute(
                    f"""
                    SELECT * FROM {table}
                    WHERE symbol=? AND instrument_type=? AND frequency=?
                    """,
                    (*key.storage_tuple(), frequency.value),
                ).fetchone()
            if row is None:
                return None
            meta = dict(row)
            meta["diagnostics"] = _parse_diagnostics(meta.get("diagnostics_json"))
            return meta

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

        with connect_meta_sqlite(self._meta_path) as conn:
            table = _resolve_market_table(conn, "bar_meta")
            conn.execute(
                f"""INSERT OR REPLACE INTO {table}
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
        with connect_meta_sqlite(self._meta_path) as conn:
            table = _resolve_market_table(conn, "market_bars")
            if instrument_type is None:
                rows = conn.execute(
                    f"SELECT DISTINCT symbol FROM {table} WHERE frequency = ?",
                    (frequency.value,),
                ).fetchall()
            else:
                resolved_type = InstrumentType.from_persisted(
                    instrument_type.value
                    if isinstance(instrument_type, InstrumentType)
                    else instrument_type
                )
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT symbol FROM {table}
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
        members: Sequence[Mapping[str, Any]],
        capture_started_at: datetime | None = None,
        capture_completed_at: datetime | None = None,
        source_metadata: Sequence[Mapping[str, Any]] | None = None,
        source_capture_ids: Sequence[str] | None = None,
    ) -> dict[str, object]:
        """Append an adapter observation, or preserve a time-unknown legacy snapshot.

        ``trade_date`` identifies the requested daily-bar window, not historical
        membership. New captures bind both real aware instants. Omitting both
        preserves the v1 bytes and per-date/provider legacy conflict behavior.
        """
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
        capture = _market_universe_capture_fields(
            capture_started_at, capture_completed_at
        )
        if source_metadata is not None and not capture:
            raise ValueError("market_universe_metadata_capture_required")
        if source_capture_ids is not None and (not source_metadata or not capture):
            raise ValueError("market_universe_source_capture_metadata_required")
        core = {
            "schema_version": "karkinos.market_universe_snapshot.v3"
            if source_metadata is not None
            else "karkinos.market_universe_snapshot.v2"
            if capture
            else "karkinos.market_universe_snapshot.v1",
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
            **capture,
        }
        if source_metadata is not None:
            core["member_metadata"] = normalize_stock_master_metadata(
                source_metadata, normalized_members
            )
        if source_capture_ids is not None:
            from data.storage.objects import ContentAddressedObjectStore

            core["source_capture_ids"] = sorted(set(source_capture_ids))
            require_stock_master_capture_evidence(
                ContentAddressedObjectStore(self._root / "research" / "objects"), core
            )
        snapshot_id = _market_universe_snapshot_id(core)
        payload = {**core, "snapshot_id": snapshot_id}
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        now = datetime.now().isoformat()
        with connect_meta_sqlite(self._meta_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM market_universe_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            if existing is None and not capture:
                existing = conn.execute(
                    """
                    SELECT * FROM market_universe_snapshots
                    WHERE trade_date = ? AND provider_name = ? AND available_at IS NULL
                    """,
                    (normalized_date, normalized_provider),
                ).fetchone()
            if existing is not None:
                verified = _verified_market_universe_row(existing)
                if str(existing["snapshot_id"]) != snapshot_id:
                    raise ValueError("market_universe_snapshot_conflict")
                return verified
            conn.execute(
                """
                INSERT INTO market_universe_snapshots
                    (snapshot_id, trade_date, provider_name, member_count,
                     snapshot_json, created_at, capture_started_at,
                     capture_completed_at, available_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    normalized_date,
                    normalized_provider,
                    len(normalized_members),
                    payload_json,
                    now,
                    capture.get("capture_started_at"),
                    capture.get("capture_completed_at"),
                    capture.get("available_at"),
                ),
            )
        return payload

    def get_market_universe_snapshot(
        self,
        *,
        trade_date: str | None = None,
        provider_name: str | None = None,
        snapshot_id: str | None = None,
        as_of: datetime | None = None,
    ) -> dict[str, object] | None:
        """Read exact identity or the latest known observation at a real cutoff.

        Legacy rows remain readable by ID/date, but are never eligible for as-of
        selection. A date-only query retains its daily-bar-window meaning.
        """
        conditions: list[str] = []
        params: list[str] = []
        if trade_date is not None:
            conditions.append("trade_date = ?")
            params.append(str(trade_date))
        if provider_name is not None:
            normalized_provider = str(provider_name).strip()
            if not normalized_provider:
                raise ValueError("market_universe_provider_name_invalid")
            conditions.append("provider_name = ?")
            params.append(normalized_provider)
        if snapshot_id is not None:
            if not str(snapshot_id).strip():
                raise ValueError("market_universe_snapshot_id_invalid")
            conditions.append("snapshot_id = ?")
            params.append(str(snapshot_id))
        if as_of is not None:
            conditions.extend(("available_at IS NOT NULL", "available_at <= ?"))
            params.append(_market_universe_utc(as_of, field="as_of"))
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        ordering = "available_at DESC, capture_started_at DESC, snapshot_id DESC"
        if as_of is None:
            ordering = (
                "trade_date DESC, available_at DESC, capture_started_at DESC, "
                "CASE WHEN available_at IS NULL THEN created_at END DESC, snapshot_id DESC"
            )
        query = """
            SELECT * FROM market_universe_snapshots
            {where_clause}
            ORDER BY {ordering}
            LIMIT 1
        """
        with connect_meta_sqlite(self._meta_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            row = conn.execute(
                query.format(where_clause=where_clause, ordering=ordering),
                tuple(params),
            ).fetchone()
            if row is None:
                return None
            payload = _verified_market_universe_row(row)
            if snapshot_id is None and row["available_at"] is not None:
                peers = conn.execute(
                    """SELECT * FROM market_universe_snapshots
                       WHERE trade_date = ? AND provider_name = ?
                       AND capture_started_at = ? AND capture_completed_at = ?""",
                    (
                        row["trade_date"],
                        row["provider_name"],
                        row["capture_started_at"],
                        row["capture_completed_at"],
                    ),
                ).fetchall()
                if len(peers) > 1:
                    for peer in peers:
                        _verified_market_universe_row(peer)
                    # A content hash identifies a response; it cannot decide
                    # which conflicting response at the same time was newer.
                    raise ValueError("market_universe_observation_ambiguous")
            return payload

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

        with connect_meta_sqlite(self._meta_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            table = _resolve_market_table(conn, "market_bars")
            if (
                key.instrument_type is InstrumentType.STOCK
                and frequency is BarFrequency.DAILY
            ):
                require_frozen_stock_bars_unchanged(
                    conn, [(row[0], row[3], *row[4:10]) for row in rows]
                )
            conn.executemany(
                f"""
                INSERT INTO {table} (
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
        params: tuple[str, ...]
        with connect_meta_sqlite(self._meta_path) as conn:
            table = _resolve_market_table(conn, "market_bars")
            if key is None:
                sql = f"""
                    SELECT timestamp, open, high, low, close, volume, amount
                    FROM {table}
                    WHERE symbol = ? AND frequency = ?
                    ORDER BY timestamp ASC
                """
                params = (str(symbol), frequency.value)
            else:
                sql = f"""
                    SELECT timestamp, open, high, low, close, volume, amount
                    FROM {table}
                    WHERE symbol = ? AND instrument_type = ? AND frequency = ?
                    ORDER BY timestamp ASC
                """
                params = (*key.storage_tuple(), frequency.value)
            df = pd.read_sql_query(sql, conn, params=params)
        if df.empty:
            return None
        df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601")
        return df
