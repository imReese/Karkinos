"""Audit-friendly dataset snapshot metadata for research backtests."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

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
        adjustment_mode = (
            meta.get("adjustment_mode") or attrs.get("adjustment_mode") or None
        )
        if adjustment_mode:
            adjustment_modes.add(str(adjustment_mode))
        quality = _dataset_quality_payload(row_count, diagnostics)
        for issue in quality["issues"]:
            top_level_issues.append({"symbol": str(symbol), **issue})

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
        "data_quality": top_level_quality,
        "symbol_universe": rows,
    }
    snapshot["snapshot_id"] = _dataset_snapshot_id(snapshot)
    return snapshot
