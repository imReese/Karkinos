"""Atomic daily-market ingestion and value helpers for :mod:`data.store`."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from core.types import BarFrequency, InstrumentType, Symbol
from data.meta_store_connection import connect_meta_sqlite

_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")
_STOCK_RECEIPT_STORAGE_AUTHORITY_BY_SCHEMA = {
    "karkinos.market_daily_ingestion_receipt.v1": "sqlite_market_bars",
    "karkinos.market_daily_ingestion_receipt.v2": "sqlite_market_bars_v2:stock",
    "karkinos.market_daily_ingestion_receipt.v3": "sqlite_market_bars_v2:stock",
}

RESEARCH_BAR_NORMALIZATION = "karkinos.receipt_stock_units.v1"
CANONICAL_STOCK_BAR_UNITS = {"volume": "shares", "amount": "CNY"}


def _resolve_market_table(conn: sqlite3.Connection, base: str) -> str:
    """Return physical table name for typed bar storage."""
    return base


def is_supported_stock_receipt_identity(receipt: Mapping[str, object]) -> bool:
    """Accept only the exact legacy or typed stock daily-receipt identity."""

    schema_version = str(receipt.get("schema_version") or "")
    expected_authority = _STOCK_RECEIPT_STORAGE_AUTHORITY_BY_SCHEMA.get(schema_version)
    if schema_version == "karkinos.market_daily_ingestion_receipt.v3" and (
        receipt.get("units") != CANONICAL_STOCK_BAR_UNITS
        or receipt.get("price_basis") != "unadjusted"
    ):
        return False
    return expected_authority is not None and (
        receipt.get("storage_authority") == expected_authority
    )


def compute_scope_fingerprint(symbols: Sequence[str]) -> str:
    cleaned = sorted({str(s).strip() for s in symbols if str(s).strip()})
    return "sha256:" + hashlib.sha256(",".join(cleaned).encode("utf-8")).hexdigest()


def require_frozen_stock_bars_unchanged(
    conn: sqlite3.Connection,
    records: Sequence[tuple[object, ...]],
) -> None:
    """Reject writes that would revise a receipt-bound stock observation.

    The caller holds the write transaction. Legacy receipts protect their exact
    stock observations too, including copies restored into typed storage.
    """
    if not records:
        return
    dates = {str(record[1])[:10] for record in records}
    authorities: dict[str, list[tuple[str, set[str]]]] = {}
    for row in conn.execute(
        """SELECT trade_date, receipt_json FROM market_daily_ingestion_receipts
           WHERE trade_date >= ? AND trade_date <= ?""",
        (min(dates), max(dates)),
    ):
        receipt = json.loads(str(row[1]))
        if not is_supported_stock_receipt_identity(receipt):
            continue
        table = "market_bars"
        authorities.setdefault(str(row[0]), []).append(
            (table, {str(symbol) for symbol in receipt.get("symbols") or []})
        )
    scoped_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_daily_scoped_receipts'"
    ).fetchone()
    if scoped_exists:
        for row in conn.execute(
            """SELECT trade_date, receipt_json FROM market_daily_scoped_receipts
               WHERE trade_date >= ? AND trade_date <= ?""",
            (min(dates), max(dates)),
        ):
            receipt = json.loads(str(row[1]))
            if not is_supported_stock_receipt_identity(receipt):
                continue
            table = "market_bars"
            authorities.setdefault(str(row[0]), []).append(
                (table, {str(symbol) for symbol in receipt.get("symbols") or []})
            )
    for record in records:
        symbol, timestamp = str(record[0]), str(record[1])
        for table, symbols in authorities.get(timestamp[:10], []):
            if symbol not in symbols:
                continue
            cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            identity = (
                "instrument_type='stock' AND" if "instrument_type" in cols else ""
            )
            existing = conn.execute(
                f"""SELECT open, high, low, close, volume, amount FROM {table}
                    WHERE {identity} symbol=? AND frequency='1d' AND timestamp=?""",
                (symbol, timestamp),
            ).fetchone()
            if existing is None or tuple(existing) != tuple(record[2:8]):
                raise ValueError(f"frozen_market_bar_conflict:{symbol}:{timestamp}")


def _receipt_symbols_set(val: object) -> set[str]:
    if isinstance(val, (list, tuple, set)):
        return {str(x) for x in val}
    return set()


def _receipt_row_count(val: object) -> int:
    if isinstance(val, int):
        return val
    try:
        return int(str(val))
    except (ValueError, TypeError):
        return 0


class MarketDailyIngestionMixin:
    """Own immutable daily-batch receipts on the DataStore SQLite connection."""

    _meta_path: Path

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

        Callers supply unadjusted stock prices, volume in shares, and amount
        in CNY. Provider-specific conversions belong in the adapter. New v3
        receipts record these units; v1/v2 receipts retain their original values.
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
            "schema_version": "karkinos.market_daily_ingestion_receipt.v3",
            "units": CANONICAL_STOCK_BAR_UNITS,
            "price_basis": "unadjusted",
            "trade_date": normalized_date,
            "provider_name": normalized_provider,
            "row_count": len(records),
            "symbols": symbols,
            "dataset_fingerprint": dataset_fingerprint,
            "storage_authority": "sqlite_market_bars_v2:stock",
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

        with connect_meta_sqlite(self._meta_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
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

            require_frozen_stock_bars_unchanged(conn, records)
            target_table = _resolve_market_table(conn, "market_bars")
            conn.executemany(
                f"""
                INSERT INTO {target_table} (
                    symbol, instrument_type, frequency, timestamp,
                    open, high, low, close, volume, amount,
                    identity_provenance, created_at, updated_at
                ) VALUES (?, 'stock', '1d', ?, ?, ?, ?, ?, ?, ?,
                          'verified_market_daily_ingestion_receipt', ?, ?)
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

    def ingest_scoped_market_daily_batch(
        self,
        *,
        trade_date: str,
        provider_name: str,
        bars: pd.DataFrame,
        symbols: Sequence[str] | None = None,
    ) -> dict[str, object]:
        """Atomically freeze one provider-returned scoped daily batch.

        Scoped batches explicitly preserve their symbol scope and do not occupy
        or overwrite the full-market daily batch identity. Expanding scope
        (e.g. A -> A+B) creates a new immutable scoped receipt while keeping
        older scoped receipts intact and replayable.
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
        bar_symbols = [record[0] for record in records]
        scope_fingerprint = compute_scope_fingerprint(bar_symbols)
        receipt_core: dict[str, object] = {
            "schema_version": "karkinos.market_daily_ingestion_receipt.v3",
            "scope_type": "scoped",
            "scope_fingerprint": scope_fingerprint,
            "units": CANONICAL_STOCK_BAR_UNITS,
            "price_basis": "unadjusted",
            "trade_date": normalized_date,
            "provider_name": normalized_provider,
            "row_count": len(records),
            "symbols": bar_symbols,
            "dataset_fingerprint": dataset_fingerprint,
            "storage_authority": "sqlite_market_bars_v2:stock",
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

        with connect_meta_sqlite(self._meta_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
            CREATE TABLE IF NOT EXISTS market_daily_scoped_receipts (
                trade_date TEXT NOT NULL,
                provider_name TEXT NOT NULL,
                scope_fingerprint TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                dataset_fingerprint TEXT NOT NULL,
                receipt_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (trade_date, provider_name, scope_fingerprint)
            )
            """)
            existing = conn.execute(
                """
                SELECT receipt_json FROM market_daily_scoped_receipts
                WHERE trade_date = ? AND provider_name = ? AND scope_fingerprint = ?
                """,
                (normalized_date, normalized_provider, scope_fingerprint),
            ).fetchone()
            if existing is not None:
                stored = json.loads(str(existing["receipt_json"]))
                if stored != receipt or not self._verify_market_daily_receipt(
                    conn, stored
                ):
                    raise ValueError("market_daily_ingestion_receipt_conflict")
                return stored

            require_frozen_stock_bars_unchanged(conn, records)
            target_table = _resolve_market_table(conn, "market_bars")
            conn.executemany(
                f"""
                INSERT INTO {target_table} (
                    symbol, instrument_type, frequency, timestamp,
                    open, high, low, close, volume, amount,
                    identity_provenance, created_at, updated_at
                ) VALUES (?, 'stock', '1d', ?, ?, ?, ?, ?, ?, ?,
                          'verified_market_daily_ingestion_receipt', ?, ?)
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
                INSERT INTO market_daily_scoped_receipts (
                    trade_date, provider_name, scope_fingerprint, row_count,
                    dataset_fingerprint, receipt_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_date,
                    normalized_provider,
                    scope_fingerprint,
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
        symbols: Sequence[str] | None = None,
        verify: bool = True,
    ) -> dict[str, object] | None:
        """Read one frozen full-market batch receipt (or covering scoped receipt) and optionally replay it."""

        with connect_meta_sqlite(self._meta_path) as conn:
            conn.row_factory = sqlite3.Row
            full_row = conn.execute(
                """
                SELECT receipt_json FROM market_daily_ingestion_receipts
                WHERE trade_date = ? AND provider_name = ?
                """,
                (str(trade_date), str(provider_name)),
            ).fetchone()
            full_payload: dict[str, object] | None = None
            if full_row is not None:
                p = json.loads(str(full_row["receipt_json"]))
                if isinstance(p, dict):
                    full_payload = p

            if symbols is None:
                if full_payload is not None:
                    if verify and not self._verify_market_daily_receipt(
                        conn, full_payload
                    ):
                        raise ValueError("market_daily_ingestion_receipt_drift")
                    return full_payload
                return None

            req_symbols = {str(s) for s in symbols}
            if full_payload is not None:
                full_symbols = _receipt_symbols_set(full_payload.get("symbols"))
                if req_symbols.issubset(full_symbols):
                    if verify and not self._verify_market_daily_receipt(
                        conn, full_payload
                    ):
                        raise ValueError("market_daily_ingestion_receipt_drift")
                    return full_payload

            scoped_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_daily_scoped_receipts'"
            ).fetchone()
            if scoped_exists:
                rows = conn.execute(
                    """
                    SELECT receipt_json FROM market_daily_scoped_receipts
                    WHERE trade_date = ? AND provider_name = ?
                    ORDER BY row_count DESC, created_at DESC
                    """,
                    (str(trade_date), str(provider_name)),
                ).fetchall()
                scoped_payloads: list[dict[str, object]] = []
                for r in rows:
                    p = json.loads(str(r["receipt_json"]))
                    if isinstance(p, dict):
                        scoped_payloads.append(p)

                # First check if any scoped receipt covers all requested symbols
                for p in scoped_payloads:
                    p_symbols = _receipt_symbols_set(p.get("symbols"))
                    if req_symbols.issubset(p_symbols):
                        if verify and not self._verify_market_daily_receipt(conn, p):
                            raise ValueError("market_daily_ingestion_receipt_drift")
                        return p

                # If none covers all requested symbols, return the most comprehensive candidate
                candidates: list[dict[str, object]] = (
                    [full_payload] if full_payload is not None else []
                ) + scoped_payloads
                if candidates:
                    best = max(
                        candidates,
                        key=lambda p: (
                            len(
                                req_symbols.intersection(
                                    _receipt_symbols_set(p.get("symbols"))
                                )
                            ),
                            _receipt_row_count(p.get("row_count")),
                        ),
                    )
                    if verify and not self._verify_market_daily_receipt(conn, best):
                        raise ValueError("market_daily_ingestion_receipt_drift")
                    return best

            if full_payload is not None:
                if verify and not self._verify_market_daily_receipt(conn, full_payload):
                    raise ValueError("market_daily_ingestion_receipt_drift")
                return full_payload

            return None

    def get_market_daily_scoped_receipt(
        self,
        *,
        trade_date: str,
        provider_name: str,
        scope_fingerprint: str | None = None,
        symbols: Sequence[str] | None = None,
        verify: bool = True,
    ) -> dict[str, object] | None:
        """Read one frozen scoped receipt by scope_fingerprint or symbols."""
        if scope_fingerprint is None and symbols is not None:
            scope_fingerprint = compute_scope_fingerprint(symbols)

        with connect_meta_sqlite(self._meta_path) as conn:
            conn.row_factory = sqlite3.Row
            scoped_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_daily_scoped_receipts'"
            ).fetchone()
            if not scoped_exists:
                return None
            if scope_fingerprint is not None:
                row = conn.execute(
                    """
                    SELECT receipt_json FROM market_daily_scoped_receipts
                    WHERE trade_date = ? AND provider_name = ? AND scope_fingerprint = ?
                    """,
                    (str(trade_date), str(provider_name), scope_fingerprint),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT receipt_json FROM market_daily_scoped_receipts
                    WHERE trade_date = ? AND provider_name = ?
                    ORDER BY row_count DESC, created_at DESC LIMIT 1
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

    def list_market_daily_scoped_receipts(
        self,
        *,
        trade_date: str | None = None,
        provider_name: str | None = None,
        verify: bool = True,
    ) -> list[dict[str, object]]:
        """Read date/provider filtered scoped receipts for deterministic replay."""
        with connect_meta_sqlite(self._meta_path) as conn:
            conn.row_factory = sqlite3.Row
            scoped_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_daily_scoped_receipts'"
            ).fetchone()
            if not scoped_exists:
                return []
            clauses = []
            params = []
            if trade_date is not None:
                clauses.append("trade_date = ?")
                params.append(str(trade_date))
            if provider_name is not None:
                clauses.append("provider_name = ?")
                params.append(str(provider_name))
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"""
                SELECT receipt_json FROM market_daily_scoped_receipts
                {where}
                ORDER BY trade_date, provider_name, created_at
                """,
                tuple(params),
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

    def list_market_daily_ingestion_receipts(
        self,
        *,
        start_date: str,
        end_date: str,
        provider_name: str | None = None,
        verify: bool = True,
    ) -> list[dict[str, object]]:
        """Read a date-ordered receipt window for deterministic replay."""

        with connect_meta_sqlite(self._meta_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT receipt_json FROM market_daily_ingestion_receipts
                WHERE (? IS NULL OR provider_name = ?) AND trade_date BETWEEN ? AND ?
                ORDER BY trade_date, provider_name
                """,
                (provider_name, provider_name, str(start_date), str(end_date)),
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

    def list_market_daily_ingestion_receipt_providers(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> list[str]:
        """List distinct receipt providers present in the trading date window."""

        with connect_meta_sqlite(self._meta_path) as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT provider_name FROM market_daily_ingestion_receipts
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY provider_name
                """,
                (str(start_date), str(end_date)),
            ).fetchall()
            return [str(row[0]) for row in rows if str(row[0]).strip()]

    def load_market_bar_windows(
        self,
        *,
        symbols: list[str],
        start_date: str,
        end_date: str,
        receipts: Sequence[Mapping[str, object]] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Load frozen stock rows from the storage authority bound by receipts.

        Legacy v1 receipts prove stock identity for their exact dates in
        ``market_bars``; v2 receipts bind their dates to typed
        ``market_bars`` stock rows.  Reading both authorities through the
        verified receipt chain keeps historical windows continuous across the
        storage migration without guessing identity or contacting providers.
        """

        wanted = {str(symbol).strip() for symbol in symbols if str(symbol).strip()}
        if not wanted:
            return {}
        start = pd.Timestamp(start_date).isoformat()
        end = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).isoformat()
        legacy_dates, typed_dates = _receipt_storage_dates(receipts or ())
        with connect_meta_sqlite(self._meta_path) as conn:
            typed_table = "market_bars"
            if receipts:
                parts = [
                    _read_market_window_authority(
                        conn,
                        table="market_bars",
                        identity_filter="",
                        dates=legacy_dates,
                        start=start,
                        end=end,
                        authority_rank=1,
                    ),
                    _read_market_window_authority(
                        conn,
                        table=typed_table,
                        identity_filter="instrument_type = 'stock' AND",
                        dates=typed_dates,
                        start=start,
                        end=end,
                        authority_rank=2,
                    ),
                ]
                available = [part for part in parts if not part.empty]
                frame = (
                    pd.concat(available, ignore_index=True)
                    if available
                    else pd.DataFrame()
                )
            else:
                frame = _read_market_window_authority(
                    conn,
                    table=typed_table,
                    identity_filter="instrument_type = 'stock' AND",
                    dates=None,
                    start=start,
                    end=end,
                    authority_rank=2,
                )
        if frame.empty:
            return {}
        frame = frame.loc[frame["symbol"].isin(wanted)].copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        frame = (
            frame.sort_values(["symbol", "timestamp", "_authority_rank"])
            .drop_duplicates(["symbol", "timestamp"], keep="last")
            .drop(columns=["_authority_rank"])
        )
        return {
            str(symbol): group.drop(columns=["symbol"]).reset_index(drop=True)
            for symbol, group in frame.groupby("symbol", sort=True)
        }

    @staticmethod
    def _verify_market_daily_receipt(
        conn: sqlite3.Connection,
        receipt: dict[str, object],
    ) -> bool:
        return verify_market_daily_receipt_on_connection(conn, receipt)


def _receipt_storage_dates(
    receipts: Sequence[Mapping[str, object]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    legacy_dates: set[str] = set()
    typed_dates: set[str] = set()
    for receipt in receipts:
        if not is_supported_stock_receipt_identity(receipt):
            raise ValueError("market_daily_receipt_storage_authority_invalid")
        trade_date = str(receipt.get("trade_date") or "")
        if not trade_date:
            raise ValueError("market_daily_receipt_trade_date_invalid")
        schema_version = str(receipt.get("schema_version") or "")
        target = (
            typed_dates
            if schema_version != "karkinos.market_daily_ingestion_receipt.v1"
            else legacy_dates
        )
        target.add(trade_date)
    if legacy_dates & typed_dates:
        raise ValueError("market_daily_receipt_storage_authority_conflict")
    return tuple(sorted(legacy_dates)), tuple(sorted(typed_dates))


def _read_market_window_authority(
    conn: sqlite3.Connection,
    *,
    table: str,
    identity_filter: str,
    dates: Sequence[str] | None,
    start: str,
    end: str,
    authority_rank: int,
) -> pd.DataFrame:
    if dates is not None and not dates:
        return pd.DataFrame()
    if table not in {"market_bars"}:
        raise ValueError("market_bar_storage_authority_invalid")
    date_sql = ""
    params: list[object] = [start, end]
    if dates is not None:
        placeholders = ",".join("?" for _ in dates)
        date_sql = f" AND substr(timestamp, 1, 10) IN ({placeholders})"
        params.extend(dates)
    frame = pd.read_sql_query(
        f"""
        SELECT symbol, timestamp, open, high, low, close, volume, amount,
               {int(authority_rank)} AS _authority_rank
        FROM {table}
        WHERE {identity_filter} frequency = '1d'
          AND timestamp >= ? AND timestamp < ?{date_sql}
        ORDER BY symbol, timestamp
        """,
        conn,
        params=params,
    )
    return frame


def verify_market_daily_receipt_on_connection(
    conn: sqlite3.Connection,
    receipt: dict[str, object],
    *,
    schema: str = "main",
) -> bool:
    """Replay a receipt on the caller's existing read or publication transaction."""
    return (
        read_verified_market_daily_receipt_records_on_connection(
            conn, receipt, schema=schema
        )
        is not None
    )


def read_verified_market_daily_receipt_records_on_connection(
    conn: sqlite3.Connection,
    receipt: dict[str, object],
    *,
    schema: str = "main",
) -> tuple[_MarketDailyRecord, ...] | None:
    """Read and verify exact source rows once on the caller's transaction."""
    if schema not in {"main", "market_meta"}:
        raise ValueError("market_daily_receipt_schema_invalid")
    if not is_supported_stock_receipt_identity(receipt):
        return None
    symbols = receipt.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        return None
    try:
        day = date.fromisoformat(str(receipt.get("trade_date") or ""))
        following = day + timedelta(days=1)
    except (ValueError, OverflowError):
        return None
    cols = {row[1] for row in conn.execute(f"PRAGMA {schema}.table_info(market_bars)")}
    has_typed_bars = "instrument_type" in cols
    storage_table = "market_bars"
    identity_filter = "instrument_type = 'stock' AND" if has_typed_bars else ""
    rows = conn.execute(
        f"""
        SELECT symbol, timestamp, open, high, low, close, volume, amount
        FROM {schema}.{storage_table}
        WHERE {identity_filter} frequency = '1d'
          AND timestamp >= ? AND timestamp < ?
        ORDER BY symbol
        """,
        (day.isoformat(), following.isoformat()),
    ).fetchall()
    wanted = set(str(symbol) for symbol in symbols)
    records = tuple(tuple(row) for row in rows if str(row[0]) in wanted)
    if len(records) != len(symbols):
        return None
    expected_dataset_fingerprint = _market_daily_records_fingerprint(
        trade_date=str(receipt.get("trade_date") or ""),
        provider_name=str(receipt.get("provider_name") or ""),
        records=records,
    )
    if receipt.get("dataset_fingerprint") != expected_dataset_fingerprint:
        return None
    core = dict(receipt)
    stored_fingerprint = core.pop("receipt_fingerprint", None)
    valid = (
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
    return records if valid else None


def _nullable_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


_MarketDailyRecord = tuple[
    str,
    str,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
]


def _normalized_market_daily_records(
    frame: pd.DataFrame,
) -> list[_MarketDailyRecord]:
    records: list[_MarketDailyRecord] = []
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
    records: Sequence[tuple[object, ...]],
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
    instrument_type: InstrumentType | None = None,
) -> str:
    payload = {
        "symbol": str(symbol),
        "instrument_type": (None if instrument_type is None else instrument_type.value),
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


nullable_float = _nullable_float
metadata_value = _metadata_value
build_bar_diagnostics = _build_bar_diagnostics
build_dataset_id = _build_dataset_id
parse_diagnostics = _parse_diagnostics
