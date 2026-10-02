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

from data.store import build_bar_diagnostics

logger = logging.getLogger(__name__)


def dataset_research_use(snapshot: Mapping[str, Any]) -> str | None:
    """Apply current admission semantics without rewriting historical reports.

    Daily ingestion receipts bind raw bars, not corporate-action returns or
    historical information availability. Older receipt snapshots omitted this
    label; their exact data can still replay, but a new review is exploratory.
    """
    if snapshot.get("market_data_binding") is not None:
        return "exploratory_backtest"
    return snapshot.get("research_use")


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


def _handler_instrument_type(handler: Any) -> str:
    raw = getattr(handler, "instrument_type", None) or getattr(
        handler, "_instrument_type", None
    )
    if raw is not None:
        normalized = str(getattr(raw, "value", raw)).strip().lower()
        if normalized:
            return "open_end_fund" if normalized == "fund" else normalized
    asset_class = str(_enum_value(_handler_asset_class(handler)) or "").strip().lower()
    if asset_class and asset_class != "fund":
        return asset_class
    raise ValueError("backtest dataset instrument identity is unresolved")


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


def _frame_content_digest(frame: Any, *, include_amount: bool = False) -> str | None:
    """Hash an ordered timestamp/OHLCV frame with backtest engine semantics."""

    required_columns = ("open", "high", "low", "close", "volume")
    if include_amount:
        required_columns += ("amount",)
    if any(column not in getattr(frame, "columns", []) for column in required_columns):
        return None

    digest = hashlib.sha256()
    digest.update(
        b"karkinos.dataset_rows.timestamp_ohlcva.v2\n"
        if include_amount
        else b"karkinos.dataset_rows.timestamp_ohlcv.v1\n"
    )
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


def _safe_store_meta(
    store: Any,
    symbol: Any,
    frequency: Any,
    *,
    instrument_type: str,
) -> dict[str, Any]:
    if store is None or frequency is None or not hasattr(store, "get_meta"):
        return {}
    try:
        meta = store.get_meta(
            symbol,
            frequency,
            instrument_type=instrument_type,
        )
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
    market_data_binding: Mapping[str, Any] | None = None,
    research_dataset_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an audit identity for the exact bars given to the backtest engine."""
    if research_dataset_binding is not None and (
        market_data_binding is not None
        or research_dataset_binding.get("price_basis") != "unadjusted"
        or research_dataset_binding.get("point_in_time_verified") is not False
    ):
        raise ValueError("research_dataset_binding_unsupported")
    rows: list[dict[str, Any]] = []
    top_level_issues: list[dict[str, Any]] = []
    adjustment_modes: set[str] = set()
    metadata_available = False

    for symbol, handler in sorted(data_handlers.items(), key=lambda item: str(item[0])):
        frequency = _handler_frequency(handler)
        instrument_type = _handler_instrument_type(handler)
        meta = (
            {}
            if market_data_binding is not None
            else _safe_store_meta(
                store,
                symbol,
                frequency,
                instrument_type=instrument_type,
            )
        )
        metadata_available = metadata_available or bool(meta)
        attrs = _handler_attrs(handler)
        source_diagnostics = meta.get("diagnostics")
        if not isinstance(source_diagnostics, dict):
            source_diagnostics = {}
        frame = _handler_dataframe(handler)
        diagnostics = (
            build_bar_diagnostics(frame) if isinstance(frame, pd.DataFrame) else {}
        )
        row_count = _handler_row_count(handler)
        first_timestamp, last_timestamp = _handler_timestamp_bounds(handler)
        content_digest = (
            _frame_content_digest(frame, include_amount=True)
            if market_data_binding is not None
            else _handler_content_digest(handler)
        )
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
                "instrument_type": instrument_type,
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
                "consumed_frame_diagnostics": diagnostics,
                "source_diagnostics": source_diagnostics,
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
            "row_contract": "timestamp_ohlcva.v2"
            if market_data_binding is not None
            else "timestamp_ohlcv.v1",
            "complete": bool(rows) and all(row.get("content_digest") for row in rows),
        },
        "data_quality": top_level_quality,
        "symbol_universe": rows,
    }
    if market_data_binding is not None:
        snapshot["market_data_binding"] = dict(market_data_binding)
        snapshot.update(
            price_basis="unadjusted",
            point_in_time_verified=False,
            research_use="exploratory_backtest",
            research_limitations=[
                {
                    "code": "historical_availability_unverified",
                    "message": "Ingestion receipts freeze observed bars, not their availability at historical decisions.",
                },
                {
                    "code": "unadjusted_corporate_actions_unmodeled",
                    "message": "Unadjusted prices do not model corporate-action cash flows or total returns.",
                },
            ],
        )
    if research_dataset_binding is not None:
        snapshot.update(
            immutable_dataset_id=research_dataset_binding["dataset_id"],
            available_as_of=research_dataset_binding["cutoff"],
            price_basis=research_dataset_binding["price_basis"],
            cross_source_verified=research_dataset_binding["cross_source_verified"],
            point_in_time_verified=research_dataset_binding["point_in_time_verified"],
            research_use="exploratory_backtest",
        )
        snapshot["research_limitations"] = [
            {
                "code": "historical_availability_unverified",
                "message": research_dataset_binding["limitations"][0],
            },
            {
                "code": "unadjusted_corporate_actions_unmodeled",
                "message": research_dataset_binding["limitations"][1],
            },
        ]
        if research_dataset_binding.get("corporate_action_evidence") is not None:
            snapshot["corporate_action_evidence"] = research_dataset_binding[
                "corporate_action_evidence"
            ]
    snapshot["snapshot_id"] = _dataset_snapshot_id(snapshot)
    return snapshot


def verify_backtest_dataset_snapshot_replay(
    snapshot: Mapping[str, Any] | None,
    *,
    store_root: str | Path,
    research_root: str | Path | None = None,
) -> dict[str, Any]:
    """Replay one frozen snapshot from its persisted source without writes.

    Legacy snapshots use the exact SQLite market-bar window; bound research
    snapshots use their immutable DatasetRef. The verifier never contacts a
    provider or silently falls back to a mutable cache.
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
        or content_identity.get("row_contract")
        not in {"timestamp_ohlcv.v1", "timestamp_ohlcva.v2"}
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
        (
            str(row.get("symbol") or ""),
            str(row.get("instrument_type") or row.get("asset_class") or ""),
            str(row.get("frequency") or ""),
        )
        for row in universe
    ]
    if any(
        not symbol or not instrument_type or not frequency
        for symbol, instrument_type, frequency in identities
    ) or len(set(identities)) != len(identities):
        blockers.append("dataset_snapshot_universe_identity_invalid")

    verified_symbols = 0
    bound_dataset_id = value.get("immutable_dataset_id")
    if bound_dataset_id is not None and not blockers:
        verified_symbols, replay_blockers = _verify_immutable_dataset_replay(
            value,
            universe=universe,
            start_date=start_date,
            end_date=end_date,
            research_root=(
                Path(research_root)
                if research_root is not None
                else Path(store_root) / "research"
            ),
        )
        blockers.extend(replay_blockers)

    replay_frames = None
    if (
        bound_dataset_id is None
        and value.get("market_data_binding") is not None
        and not blockers
    ):
        from data.research_market_data import load_research_market_frames

        try:
            replay_frames = load_research_market_frames(
                store_root,
                binding=value["market_data_binding"],
                symbols=[str(row["symbol"]) for row in universe],
                start_date=start_date,
                end_date=end_date,
            )
        except (ValueError, sqlite3.Error, OSError):
            blockers.append("dataset_replay_market_binding_invalid")
    if bound_dataset_id is None and not blockers:
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
                            frame=None
                            if replay_frames is None
                            else replay_frames.get(
                                str(manifest["symbol"]), pd.DataFrame()
                            ),
                            include_amount=content_identity.get("row_contract")
                            == "timestamp_ohlcva.v2",
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
        "persisted_market_bars_only": bound_dataset_id is None,
        "parquet_fallback_used": False,
        "provider_contacted": False,
        "does_not_create_order": True,
        "does_not_authorize_execution": True,
        "does_not_change_capital_authority": True,
    }
    return {**core, "evidence_fingerprint": _replay_fingerprint(core)}


def _verify_immutable_dataset_replay(
    snapshot: Mapping[str, Any],
    *,
    universe: list[dict[str, Any]],
    start_date: str,
    end_date: str,
    research_root: Path,
) -> tuple[int, list[str]]:
    """Compare consumed backtest rows with the exact offline DatasetRef."""
    from data.dataset.model import DatasetRef
    from data.dataset.reader import DatasetReaderError, read_daily_bar_dataset
    from data.storage.objects import ContentAddressedObjectStore, ObjectStoreError

    dataset_id = snapshot.get("immutable_dataset_id")
    store = ContentAddressedObjectStore(research_root / "objects")
    try:
        ref = DatasetRef(store.resolve_ref(dataset_id))
        restored = read_daily_bar_dataset(store, ref)
    except (OSError, TypeError, ValueError, ObjectStoreError, DatasetReaderError):
        return 0, ["dataset_replay_immutable_dataset_unreadable"]

    source_names = sorted({part.provider for part in restored.snapshot.partitions})
    single_source = source_names[0] if len(source_names) == 1 else None
    provider = snapshot.get("provider")
    expected_sources = (
        provider.get("available_sources") if isinstance(provider, Mapping) else None
    )
    configured_source = (
        provider.get("configured_source") if isinstance(provider, Mapping) else None
    )
    content_identity = snapshot.get("content_identity")
    expected_instruments = {
        (str(item.get("symbol") or ""), str(item.get("instrument_type") or ""))
        for item in universe
    }
    actual_instruments = {
        (item.symbol, item.instrument_type.value)
        for item in restored.snapshot.instruments
    }
    issues = snapshot.get("research_limitations")
    issue_codes = (
        {
            item["code"]
            for item in issues
            if isinstance(item, Mapping) and isinstance(item.get("code"), str)
        }
        if isinstance(issues, list)
        else set()
    )
    if (
        restored.snapshot.start_date.isoformat() != start_date
        or restored.snapshot.end_date.isoformat() != end_date
        or restored.snapshot.cutoff.isoformat() != snapshot.get("available_as_of")
        or snapshot.get("price_basis") != "unadjusted"
        or snapshot.get("point_in_time_verified") is not False
        or snapshot.get("research_use") != "exploratory_backtest"
        or snapshot.get("cross_source_verified")
        is not restored.snapshot.verification_bound
        or expected_sources != source_names
        or configured_source != single_source
        or expected_instruments != actual_instruments
        or len(universe) != len(actual_instruments)
        or any(item.get("source_dataset_id") != dataset_id for item in universe)
        or any(
            item.get("provider_name") != single_source
            or item.get("data_source") != single_source
            for item in universe
        )
        or not isinstance(content_identity, Mapping)
        or content_identity.get("row_contract") != "timestamp_ohlcv.v1"
        or snapshot.get("adjustment_mode") != "none"
        or snapshot.get("row_count") != restored.row_count
        or snapshot.get("corporate_action_evidence")
        != restored.corporate_action_evidence
        or not {
            "historical_availability_unverified",
            "unadjusted_corporate_actions_unmodeled",
        }.issubset(issue_codes)
    ):
        return 0, ["dataset_replay_immutable_dataset_binding_mismatch"]

    verified = 0
    blockers: list[str] = []
    for item in universe:
        symbol = str(item["symbol"])
        instrument_type = str(item["instrument_type"])
        frequency = str(item.get("frequency") or "")
        if frequency != "1d":
            blockers.append(f"dataset_replay_frequency_invalid:{symbol}:{frequency}")
            continue
        bars = [
            bar
            for bar in restored.bars
            if bar.instrument.symbol == symbol
            and bar.instrument.instrument_type.value == instrument_type
        ]
        frame = pd.DataFrame(
            [
                {
                    "timestamp": bar.event_time,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
                for bar in bars
            ]
        )
        if (
            not bars
            or _frame_content_digest(frame) != item.get("content_digest")
            or len(bars) != _safe_int(item.get("row_count"))
            or _iso_timestamp(frame["timestamp"].min()) != item.get("first_timestamp")
            or _iso_timestamp(frame["timestamp"].max()) != item.get("last_timestamp")
        ):
            blockers.append(f"dataset_replay_content_drift:{symbol}:{frequency}")
        else:
            verified += 1
    return verified, blockers


def _verify_symbol_replay(
    connection: sqlite3.Connection,
    *,
    manifest: Mapping[str, Any],
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    frame: pd.DataFrame | None = None,
    include_amount: bool = False,
) -> str | None:
    symbol = str(manifest.get("symbol") or "")
    instrument_type = str(
        manifest.get("instrument_type") or manifest.get("asset_class") or ""
    )
    frequency = str(manifest.get("frequency") or "")
    if start is None or end is None:
        return "dataset_snapshot_date_range_invalid"
    rows = (
        connection.execute(
            """
        SELECT timestamp, open, high, low, close, volume, amount
        FROM market_bars_v2
        WHERE symbol=? AND instrument_type=? AND frequency=?
        ORDER BY timestamp ASC
        """,
            (symbol, instrument_type, frequency),
        ).fetchall()
        if frame is None
        else None
    )
    if frame is None and not rows:
        return f"dataset_replay_bars_missing:{symbol}:{frequency}"
    frame = (
        pd.DataFrame(
            rows,
            columns=["timestamp", "open", "high", "low", "close", "volume", "amount"],
        )
        if frame is None
        else frame.copy()
    )
    if frame.empty:
        return f"dataset_replay_window_empty:{symbol}:{frequency}"
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
    actual_digest = _frame_content_digest(frozen, include_amount=include_amount)
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
