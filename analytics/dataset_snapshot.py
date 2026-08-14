"""Audit-friendly dataset snapshot metadata for research backtests."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

logger = logging.getLogger(__name__)


def _enum_value(raw: Any) -> str | None:
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


def _iso_timestamp(raw: Any) -> str | None:
    if raw is None:
        return None
    if hasattr(raw, "to_pydatetime"):
        raw = raw.to_pydatetime()
    if hasattr(raw, "isoformat"):
        return raw.isoformat()
    return str(raw)


def _handler_dataframe(handler: Any) -> Any:
    return getattr(handler, "_df", None)


def _handler_frequency(handler: Any) -> Any:
    return getattr(handler, "_frequency", None)


def _handler_asset_class(handler: Any) -> Any:
    return getattr(handler, "_asset_class", None)


def _handler_row_count(handler: Any) -> int:
    total_bars = getattr(handler, "total_bars", None)
    if isinstance(total_bars, int):
        return total_bars
    frame = _handler_dataframe(handler)
    if frame is not None:
        try:
            return int(len(frame))
        except TypeError:
            return 0
    return 0


def _handler_timestamp_bounds(handler: Any) -> tuple[str | None, str | None]:
    frame = _handler_dataframe(handler)
    if frame is None or "timestamp" not in getattr(frame, "columns", []):
        return None, None
    if len(frame) == 0:
        return None, None
    timestamps = frame["timestamp"]
    return _iso_timestamp(timestamps.min()), _iso_timestamp(timestamps.max())


def _handler_attrs(handler: Any) -> dict[str, Any]:
    frame = _handler_dataframe(handler)
    attrs = getattr(frame, "attrs", {}) if frame is not None else {}
    return dict(attrs) if isinstance(attrs, dict) else {}


def _handler_content_digest(handler: Any) -> str | None:
    """Hash the exact ordered timestamp/OHLCV rows consumed by DataHandler."""
    frame = _handler_dataframe(handler)
    if frame is None:
        return None
    return _frame_content_digest(frame)


def _frame_content_digest(frame: Any) -> str | None:
    """Hash an ordered timestamp/OHLCV frame with backtest engine semantics."""

    required_columns = ("open", "high", "low", "close", "volume")
    if any(column not in getattr(frame, "columns", []) for column in required_columns):
        return None

    digest = hashlib.sha256()
    digest.update(b"karkinos.dataset_rows.timestamp_ohlcv.v1\n")
    for index, row in frame.iterrows():
        timestamp = row.get("timestamp", row.get("日期", index))
        values = {
            "timestamp": _iso_timestamp(timestamp),
            **{
                column: _canonical_numeric_value(row[column])
                for column in required_columns
            },
        }
        digest.update(
            json.dumps(
                values,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def _canonical_numeric_value(raw: Any) -> str:
    """Match Decimal-based engine semantics across CSV dtype round trips."""
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return str(raw)
    if not value.is_finite():
        return str(raw).lower()
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _safe_store_meta(store: Any, symbol: Any, frequency: Any) -> dict[str, Any]:
    if store is None or frequency is None or not hasattr(store, "get_meta"):
        return {}
    try:
        meta = store.get_meta(symbol, frequency)
    except Exception:
        logger.warning(
            "Failed to read backtest dataset metadata for %s", symbol, exc_info=True
        )
        return {}
    return meta if isinstance(meta, dict) else {}


def _dataset_quality_payload(
    row_count: int,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if row_count <= 0:
        issues.append(
            {
                "code": "no_rows",
                "message": "No bars were available for this symbol in the requested range.",
            }
        )
    duplicate_count = int(diagnostics.get("duplicate_timestamp_count") or 0)
    if duplicate_count > 0:
        issues.append(
            {
                "code": "duplicate_timestamps",
                "count": duplicate_count,
                "message": "Duplicate timestamps were present in the source bars.",
            }
        )
    missing_count = int(diagnostics.get("missing_ohlcv_count") or 0)
    if missing_count > 0:
        issues.append(
            {
                "code": "missing_ohlcv",
                "count": missing_count,
                "message": "One or more OHLCV fields were missing in source bars.",
            }
        )
    if diagnostics.get("is_monotonic") is False:
        issues.append(
            {
                "code": "non_monotonic_timestamps",
                "message": "Source timestamps were not monotonic before normalization.",
            }
        )
    return {"status": "ok" if not issues else "warning", "issues": issues}


def _dataset_snapshot_id(payload: dict[str, Any]) -> str:
    frozen = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(frozen.encode("utf-8")).hexdigest()


def build_backtest_dataset_snapshot(
    *,
    start_date: str,
    end_date: str,
    configured_source: str | None,
    data_handlers: dict[Any, Any],
    store: Any,
    source_names: list[str],
) -> dict[str, Any]:
    """Build an audit identity for the exact bars given to the backtest engine."""
    rows: list[dict[str, Any]] = []
    top_level_issues: list[dict[str, Any]] = []
    adjustment_modes: set[str] = set()
    metadata_available = False

    for symbol, handler in sorted(data_handlers.items(), key=lambda item: str(item[0])):
        frequency = _handler_frequency(handler)
        meta = _safe_store_meta(store, symbol, frequency)
        metadata_available = metadata_available or bool(meta)
        attrs = _handler_attrs(handler)
        diagnostics = meta.get("diagnostics")
        if not isinstance(diagnostics, dict):
            diagnostics = {}
        row_count = _handler_row_count(handler)
        first_timestamp, last_timestamp = _handler_timestamp_bounds(handler)
        content_digest = _handler_content_digest(handler)
        adjustment_mode = (
            meta.get("adjustment_mode") or attrs.get("adjustment_mode") or None
        )
        if adjustment_mode:
            adjustment_modes.add(str(adjustment_mode))
        quality = _dataset_quality_payload(row_count, diagnostics)
        for issue in quality["issues"]:
            top_level_issues.append({"symbol": str(symbol), **issue})
        if content_digest is None:
            content_issue = {
                "code": "dataset_content_digest_unavailable",
                "message": (
                    "The exact ordered timestamp/OHLCV rows could not be hashed; "
                    "this dataset cannot be treated as frozen evidence."
                ),
            }
            quality["status"] = "warning"
            quality["issues"].append(content_issue)
            top_level_issues.append({"symbol": str(symbol), **content_issue})

        rows.append(
            {
                "symbol": str(symbol),
                "asset_class": _enum_value(_handler_asset_class(handler)),
                "frequency": _enum_value(frequency),
                "row_count": row_count,
                "first_timestamp": first_timestamp,
                "last_timestamp": last_timestamp,
                "provider_name": meta.get("provider_name")
                or attrs.get("provider_name")
                or None,
                "data_source": meta.get("data_source")
                or attrs.get("data_source")
                or configured_source,
                "adjustment_mode": adjustment_mode,
                "source_dataset_id": meta.get("dataset_id") or attrs.get("dataset_id"),
                "content_digest": content_digest,
                "data_quality": quality,
            }
        )

    total_rows = sum(row["row_count"] for row in rows)
    top_level_quality = {
        "status": "ok" if not top_level_issues else "warning",
        "issues": top_level_issues,
    }
    if len(adjustment_modes) == 1:
        adjustment_mode = next(iter(adjustment_modes))
    elif len(adjustment_modes) > 1:
        adjustment_mode = "mixed"
    else:
        adjustment_mode = None

    snapshot = {
        "schema_version": "karkinos.dataset_snapshot.v1",
        "provider": {
            "configured_source": configured_source,
            "available_sources": sorted(source_names),
        },
        "cache": {
            "store_available": store is not None,
            "metadata_available": metadata_available,
        },
        "date_range": {
            "start": start_date,
            "end": end_date,
        },
        "row_count": total_rows,
        "adjustment_mode": adjustment_mode,
        "content_identity": {
            "algorithm": "sha256",
            "row_contract": "timestamp_ohlcv.v1",
            "complete": bool(rows) and all(row.get("content_digest") for row in rows),
        },
        "data_quality": top_level_quality,
        "symbol_universe": rows,
    }
    snapshot["snapshot_id"] = _dataset_snapshot_id(snapshot)
    return snapshot


def verify_backtest_dataset_snapshot_replay(
    snapshot: Mapping[str, Any] | None,
    *,
    store_root: str | Path,
) -> dict[str, Any]:
    """Replay one frozen snapshot from persisted SQLite bars without writes.

    Future bars outside the frozen date range do not invalidate the snapshot.
    Missing or corrected rows inside the window do.  The verifier never falls
    back to a provider or the mutable Parquet cache.
    """

    value = dict(snapshot) if isinstance(snapshot, Mapping) else {}
    snapshot_id = str(value.get("snapshot_id") or "")
    blockers: list[str] = []
    snapshot_core = dict(value)
    snapshot_core.pop("snapshot_id", None)
    if value.get("schema_version") != "karkinos.dataset_snapshot.v1":
        blockers.append("dataset_snapshot_schema_invalid")
    if not snapshot_id or snapshot_id != _dataset_snapshot_id(snapshot_core):
        blockers.append("dataset_snapshot_identity_mismatch")
    content_identity = value.get("content_identity")
    if (
        not isinstance(content_identity, Mapping)
        or content_identity.get("algorithm") != "sha256"
        or content_identity.get("row_contract") != "timestamp_ohlcv.v1"
        or content_identity.get("complete") is not True
    ):
        blockers.append("dataset_snapshot_content_identity_incomplete")
    quality = value.get("data_quality")
    if not isinstance(quality, Mapping) or quality.get("status") != "ok":
        blockers.append("dataset_snapshot_quality_not_clear")
    date_range = value.get("date_range")
    start_date = (
        str(date_range.get("start") or "") if isinstance(date_range, Mapping) else ""
    )
    end_date = (
        str(date_range.get("end") or "") if isinstance(date_range, Mapping) else ""
    )
    try:
        start = pd.Timestamp(start_date)
        end = (
            pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        )
        if pd.isna(start) or pd.isna(end):
            raise ValueError("date range is missing")
    except (TypeError, ValueError, OverflowError):
        start = None
        end = None
        blockers.append("dataset_snapshot_date_range_invalid")
    universe_raw = value.get("symbol_universe")
    universe = (
        [dict(row) for row in universe_raw if isinstance(row, Mapping)]
        if isinstance(universe_raw, list)
        else []
    )
    if (
        not isinstance(universe_raw, list)
        or not universe
        or len(universe) != len(universe_raw)
    ):
        blockers.append("dataset_snapshot_universe_invalid")
    identities = [
        (str(row.get("symbol") or ""), str(row.get("frequency") or ""))
        for row in universe
    ]
    if any(not symbol or not frequency for symbol, frequency in identities) or len(
        set(identities)
    ) != len(identities):
        blockers.append("dataset_snapshot_universe_identity_invalid")

    verified_symbols = 0
    if not blockers:
        meta_path = Path(store_root).expanduser() / "meta.db"
        if not meta_path.is_file():
            blockers.append("dataset_replay_store_missing")
        else:
            try:
                connection = sqlite3.connect(
                    f"{meta_path.resolve().as_uri()}?mode=ro",
                    uri=True,
                )
            except (OSError, sqlite3.Error):
                blockers.append("dataset_replay_store_unreadable")
            else:
                try:
                    for manifest in universe:
                        replay_blocker = _verify_symbol_replay(
                            connection,
                            manifest=manifest,
                            start=start,
                            end=end,
                        )
                        if replay_blocker is not None:
                            blockers.append(replay_blocker)
                        else:
                            verified_symbols += 1
                except sqlite3.Error:
                    blockers.append("dataset_replay_store_unreadable")
                finally:
                    connection.close()

    blockers = list(dict.fromkeys(blockers))
    core = {
        "schema_version": "karkinos.dataset_snapshot_replay.v1",
        "status": "pass" if not blockers else "blocked",
        "snapshot_id": snapshot_id or None,
        "manifest_symbol_count": len(universe),
        "verified_symbol_count": verified_symbols,
        "blockers": blockers,
        "persisted_market_bars_only": True,
        "parquet_fallback_used": False,
        "provider_contacted": False,
        "does_not_create_order": True,
        "does_not_authorize_execution": True,
        "does_not_change_capital_authority": True,
    }
    return {**core, "evidence_fingerprint": _replay_fingerprint(core)}


def _verify_symbol_replay(
    connection: sqlite3.Connection,
    *,
    manifest: Mapping[str, Any],
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> str | None:
    symbol = str(manifest.get("symbol") or "")
    frequency = str(manifest.get("frequency") or "")
    if start is None or end is None:
        return "dataset_snapshot_date_range_invalid"
    rows = connection.execute(
        """
        SELECT timestamp, open, high, low, close, volume
        FROM market_bars
        WHERE symbol=? AND frequency=?
        ORDER BY timestamp ASC
        """,
        (symbol, frequency),
    ).fetchall()
    if not rows:
        return f"dataset_replay_bars_missing:{symbol}:{frequency}"
    frame = pd.DataFrame(
        rows,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    if frame["timestamp"].isna().any():
        return f"dataset_replay_timestamp_invalid:{symbol}:{frequency}"
    try:
        frozen = (
            frame.loc[(frame["timestamp"] >= start) & (frame["timestamp"] <= end)]
            .sort_values("timestamp")
            .reset_index(drop=True)
        )
    except TypeError:
        return f"dataset_replay_timestamp_invalid:{symbol}:{frequency}"
    if frozen.empty:
        return f"dataset_replay_window_empty:{symbol}:{frequency}"
    actual_digest = _frame_content_digest(frozen)
    first_timestamp = _iso_timestamp(frozen["timestamp"].min())
    last_timestamp = _iso_timestamp(frozen["timestamp"].max())
    if (
        actual_digest != manifest.get("content_digest")
        or len(frozen) != _safe_int(manifest.get("row_count"))
        or first_timestamp != manifest.get("first_timestamp")
        or last_timestamp != manifest.get("last_timestamp")
    ):
        return f"dataset_replay_content_drift:{symbol}:{frequency}"
    return None


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _replay_fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
