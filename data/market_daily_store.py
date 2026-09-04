"""Atomic daily-market ingestion and value helpers for :mod:`data.store`."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.types import BarFrequency, InstrumentType, Symbol

_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")
_STOCK_RECEIPT_STORAGE_AUTHORITY_BY_SCHEMA = {
    "karkinos.market_daily_ingestion_receipt.v1": "sqlite_market_bars",
    "karkinos.market_daily_ingestion_receipt.v2": "sqlite_market_bars_v2:stock",
}


def is_supported_stock_receipt_identity(receipt: Mapping[str, object]) -> bool:
    """Accept only the exact legacy or typed stock daily-receipt identity."""

    schema_version = str(receipt.get("schema_version") or "")
    expected_authority = _STOCK_RECEIPT_STORAGE_AUTHORITY_BY_SCHEMA.get(schema_version)
    return expected_authority is not None and (
        receipt.get("storage_authority") == expected_authority
    )


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
            "schema_version": "karkinos.market_daily_ingestion_receipt.v2",
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
                INSERT INTO market_bars_v2 (
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
                FROM market_bars_v2
                WHERE instrument_type = 'stock' AND frequency = '1d'
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
        schema_version = str(receipt.get("schema_version") or "")
        if not is_supported_stock_receipt_identity(receipt):
            return False
        symbols = receipt.get("symbols")
        if not isinstance(symbols, list) or not symbols:
            return False
        if schema_version == "karkinos.market_daily_ingestion_receipt.v2":
            storage_table = "market_bars_v2"
            identity_filter = "instrument_type = 'stock' AND"
        else:
            storage_table = "market_bars"
            identity_filter = ""
        rows = conn.execute(
            f"""
            SELECT symbol, timestamp, open, high, low, close, volume, amount
            FROM {storage_table}
            WHERE {identity_filter} frequency = '1d'
              AND substr(timestamp, 1, 10) = ?
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
