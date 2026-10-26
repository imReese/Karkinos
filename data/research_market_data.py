"""Reproducible research views of immutable daily receipts.

Old receipts keep their original units and values. A new research snapshot binds
both those receipts and this explicit normalization version; no source row or
historical experiment is rewritten. Unknown historical units fail closed.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from data.market_daily_store import (
    CANONICAL_STOCK_BAR_UNITS,
    RESEARCH_BAR_NORMALIZATION,
    read_verified_market_daily_receipt_records_on_connection,
)

VERIFIED_SUPPLEMENT_NORMALIZATION = (
    "karkinos.receipt_stock_units.verified_supplement.v2"
)


def complete_research_market_binding(
    root: str | Path,
    *,
    binding: Mapping[str, Any],
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    as_of: datetime,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    """Bind real verified history for symbols absent from immutable old receipts.

    Discovery is explicit for new research. Replays use only the resulting
    stored Dataset IDs, and never replace any already receipt-bound source row.
    """
    from data.dataset.catalog import DatasetCatalog
    from data.dataset.manifest import read_daily_bar_dataset_manifest
    from data.dataset.reader import read_daily_bar_dataset
    from data.storage.objects import ContentAddressedObjectStore

    if as_of.utcoffset() is None:
        raise ValueError("research_market_supplement_as_of_invalid")
    arguments = dict(symbols=symbols, start_date=start_date, end_date=end_date)
    frames = load_research_market_frames(root, binding=binding, **arguments)
    receipt_dates = {str(ref["trade_date"]) for ref in binding["receipts"]}
    missing_dates = {
        symbol: receipt_dates
        - {value.date().isoformat() for value in frames[symbol]["timestamp"]}
        if symbol in frames
        else set(receipt_dates)
        for symbol in symbols
    }
    missing = {symbol for symbol, days in missing_dates.items() if days}
    catalog = DatasetCatalog(Path(root) / "research")
    if not missing or not catalog.path.exists():
        return dict(binding), frames
    objects = ContentAddressedObjectStore(catalog.root / "objects")
    supplements = list(binding.get("verified_dataset_supplements", []))
    added = False
    required_start, required_end = min(receipt_dates), max(receipt_dates)
    for entry in reversed(catalog.list_daily_bar_datasets()):
        if (
            entry.cutoff > as_of
            or entry.start_date.isoformat() > required_start
            or entry.end_date.isoformat() < required_end
        ):
            continue
        snapshot = read_daily_bar_dataset_manifest(objects, entry.ref)
        if (
            snapshot.cutoff > as_of
            or snapshot.start_date.isoformat() > required_start
            or snapshot.end_date.isoformat() < required_end
        ):
            continue
        selected = sorted(
            key.symbol
            for key in snapshot.instruments
            if key.instrument_type.value == "stock" and key.symbol in missing
        )
        if not selected or not snapshot.verification_bound:
            continue
        verified = read_daily_bar_dataset(objects, entry.ref)
        selected_set = set(selected)
        selected_keys = {
            (bar.session_date.isoformat(), bar.instrument.symbol)
            for bar in verified.bars
            if bar.instrument.instrument_type.value == "stock"
            and bar.instrument.symbol in selected_set
            and bar.session_date.isoformat() in missing_dates[bar.instrument.symbol]
        }
        selected = sorted({symbol for _, symbol in selected_keys})
        if selected:
            symbols_by_day, days_by_symbol = {}, {}
            for day, symbol in selected_keys:
                symbols_by_day.setdefault(day, []).append(symbol)
                days_by_symbol.setdefault(symbol, set()).add(day)
            supplement = {
                "dataset_id": entry.ref.dataset_id,
                "symbols": selected,
                "session_memberships": [
                    {"trade_date": day, "symbols": sorted(members)}
                    for day, members in sorted(symbols_by_day.items())
                ],
            }
            supplements.append(supplement)
            for symbol, supplement_frame in verified_daily_market_frames(
                verified, selected, start_date, end_date, selected_keys=selected_keys
            ).items():
                if symbol in frames:
                    supplement_frame = (
                        pd.concat([frames[symbol], supplement_frame], ignore_index=True)
                        .sort_values("timestamp")
                        .reset_index(drop=True)
                    )
                    supplement_frame.attrs.update(
                        provider_name="receipt_and_verified_supplement",
                        adjustment_mode="none",
                        volume_unit="shares",
                        amount_unit="CNY",
                    )
                frames[symbol] = supplement_frame
                missing_dates[symbol].difference_update(days_by_symbol[symbol])
                if not missing_dates[symbol]:
                    missing.discard(symbol)
            added = True
        if not missing:
            break
    if not added:
        return dict(binding), frames
    completed = {
        **binding,
        "normalizer_version": VERIFIED_SUPPLEMENT_NORMALIZATION,
        "verified_supplement_as_of": as_of.isoformat(),
        "verified_dataset_supplements": sorted(
            supplements, key=lambda item: item["dataset_id"]
        ),
    }
    return completed, frames


def verified_daily_market_frames(
    result, symbols, start_date, end_date, *, selected_keys=None
):
    """Project already verified Dataset bars without fetching or changing evidence."""
    selected = set(symbols)
    records = [
        {
            "symbol": bar.instrument.symbol,
            "timestamp": pd.Timestamp(bar.session_date),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
            "amount": float(bar.amount),
        }
        for bar in result.bars
        if bar.instrument.instrument_type.value == "stock"
        and bar.instrument.symbol in selected
        and start_date <= bar.session_date.isoformat() <= end_date
        and (
            selected_keys is None
            or (bar.session_date.isoformat(), bar.instrument.symbol) in selected_keys
        )
    ]
    if not records:
        return {}
    providers = {part.provider for part in result.snapshot.partitions}
    provider = next(iter(providers)) if len(providers) == 1 else "verified_multi_source"
    frames = {}
    for symbol, group in pd.DataFrame.from_records(records).groupby(
        "symbol", sort=True
    ):
        frame = (
            group.drop(columns="symbol").sort_values("timestamp").reset_index(drop=True)
        )
        frame["timestamp"] = frame["timestamp"].astype("datetime64[us]")
        frame.attrs.update(
            provider_name=provider,
            adjustment_mode="none",
            volume_unit="shares",
            amount_unit="CNY",
        )
        frames[str(symbol)] = frame
    return frames


def resolve_daily_bar_receipts(
    *,
    data_store: Any,
    start_date: str,
    end_date: str,
    config: Any = None,
    snapshot: Mapping[str, Any] | None = None,
    preferred_provider: str | None = None,
) -> list[dict[str, Any]]:
    """Choose verified receipts per date using deterministic provider priority.

    The source may vary between dates. Reading a receipt neither contacts its
    provider nor upgrades historical availability or membership to PIT proof.
    """
    preferred = str(preferred_provider or "").strip()
    provider_priority: list[str] = []
    if preferred:
        provider_priority.append(preferred)
    if config is not None:
        data_source = str(getattr(config, "data_source", "") or "").strip()
        if data_source and data_source not in provider_priority:
            provider_priority.append(data_source)
        try:
            from data.source_policy import MarketDataUseCase
            from data.source_routing import configured_data_provider_names

            for candidate in configured_data_provider_names(
                config, MarketDataUseCase.DAILY_BARS
            ):
                if candidate not in provider_priority:
                    provider_priority.append(candidate)
        except Exception:
            pass
    snapshot_provider = str(
        (snapshot.get("provider_name") if isinstance(snapshot, Mapping) else "") or ""
    ).strip()
    if snapshot_provider and snapshot_provider not in provider_priority:
        provider_priority.append(snapshot_provider)
    raw_receipts = [
        dict(item)
        for item in data_store.list_market_daily_ingestion_receipts(
            start_date=start_date,
            end_date=end_date,
            provider_name=preferred if preferred else None,
            verify=True,
        )
    ]
    by_date: dict[str, list[dict[str, Any]]] = {}
    for item in raw_receipts:
        date_key = str(item.get("trade_date") or "").strip()
        if date_key:
            by_date.setdefault(date_key, []).append(item)
    selected: list[dict[str, Any]] = []
    for date_key in sorted(by_date.keys()):
        candidates = by_date[date_key]
        if len(candidates) == 1:
            selected.append(candidates[0])
        else:

            def rank(cand: dict[str, Any]) -> tuple[int, str]:
                provider = str(cand.get("provider_name") or "").strip()
                index = (
                    provider_priority.index(provider)
                    if provider in provider_priority
                    else 9999
                )
                return index, provider

            candidates.sort(key=rank)
            selected.append(candidates[0])
    return selected


def research_market_binding(receipts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "normalizer_version": RESEARCH_BAR_NORMALIZATION,
        "units": dict(CANONICAL_STOCK_BAR_UNITS),
        "price_basis": "unadjusted",
        # A captured historical series does not prove historical availability
        # or point-in-time universe membership.
        "point_in_time_verified": False,
        "receipts": [
            {
                key: row[key]
                for key in ("trade_date", "provider_name", "receipt_fingerprint")
            }
            for row in receipts
        ],
    }


def load_research_market_frames(
    root: str | Path,
    *,
    binding: Mapping[str, Any],
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
) -> dict[str, pd.DataFrame]:
    """Verify and normalize exact receipt members in one read-only transaction."""
    refs = binding.get("receipts")
    if (
        binding.get("normalizer_version")
        not in {RESEARCH_BAR_NORMALIZATION, VERIFIED_SUPPLEMENT_NORMALIZATION}
        or binding.get("units") != CANONICAL_STOCK_BAR_UNITS
        or binding.get("price_basis") != "unadjusted"
        or binding.get("point_in_time_verified") is not False
        or not isinstance(refs, list)
        or not refs
        or any(not isinstance(ref, Mapping) for ref in refs)
    ):
        raise ValueError("research_market_binding_invalid")
    dates = [str(ref.get("trade_date") or "") for ref in refs]
    if dates != sorted(set(dates)) or any(
        day < start_date or day > end_date for day in dates
    ):
        raise ValueError("research_market_receipt_dates_invalid")
    wanted = set(symbols)
    supplements = binding.get("verified_dataset_supplements", [])
    if (
        not isinstance(supplements, list)
        or (binding["normalizer_version"] == RESEARCH_BAR_NORMALIZATION and supplements)
        or (
            binding["normalizer_version"] == VERIFIED_SUPPLEMENT_NORMALIZATION
            and not supplements
        )
    ):
        raise ValueError("research_market_supplement_binding_invalid")
    supplement_as_of = None
    if supplements:
        try:
            supplement_as_of = datetime.fromisoformat(
                binding["verified_supplement_as_of"]
            )
            if supplement_as_of.utcoffset() is None:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ValueError("research_market_supplement_as_of_invalid") from None
    parts = []
    all_receipt_keys = set()
    all_receipt_symbols = set()
    path = Path(root).expanduser().resolve() / "meta.db"
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("BEGIN")
        for ref in refs:
            row = conn.execute(
                """SELECT receipt_json FROM market_daily_ingestion_receipts
                   WHERE trade_date=? AND provider_name=?""",
                (ref.get("trade_date"), ref.get("provider_name")),
            ).fetchone()
            receipt = json.loads(row[0]) if row else None
            records = (
                read_verified_market_daily_receipt_records_on_connection(conn, receipt)
                if isinstance(receipt, dict)
                else None
            )
            if (
                not isinstance(receipt, dict)
                or any(
                    receipt.get(key) != ref.get(key)
                    for key in ("trade_date", "provider_name", "receipt_fingerprint")
                )
                or records is None
            ):
                raise ValueError("research_market_receipt_drift")
            schema = receipt["schema_version"]
            if schema == "karkinos.market_daily_ingestion_receipt.v3":
                if (
                    receipt.get("units") != CANONICAL_STOCK_BAR_UNITS
                    or receipt.get("price_basis") != "unadjusted"
                ):
                    raise ValueError("research_market_units_or_price_basis_invalid")
                volume_scale, amount_scale = 1, 1
            elif receipt["provider_name"] == "tushare":
                # v1/v2 TuShare batches were emitted by the old daily adapter,
                # which only renamed vol/amount (lots / thousand CNY).
                volume_scale, amount_scale = 100, 1000
            else:
                raise ValueError("research_market_legacy_units_unknown")
            members = wanted.intersection(receipt["symbols"])
            all_receipt_keys.update(
                (ref["trade_date"], symbol) for symbol in receipt["symbols"]
            )
            all_receipt_symbols.update(receipt["symbols"])
            frame = pd.DataFrame.from_records(
                [record for record in records if str(record[0]) in members],
                columns=(
                    "symbol",
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                ),
            )
            for column, scale in (("volume", volume_scale), ("amount", amount_scale)):
                frame[column] = frame[column].map(
                    lambda value: (
                        float(Decimal(str(value)) * scale) if pd.notna(value) else None
                    )
                )
            parts.append(frame)
    finally:
        conn.close()
    supplement_providers = {}
    if supplements:
        from data.dataset.model import DatasetRef
        from data.dataset.reader import read_daily_bar_dataset
        from data.storage.objects import ContentAddressedObjectStore

        objects = ContentAddressedObjectStore(Path(root) / "research" / "objects")
        bound_keys = set()
        for supplement in supplements:
            if (
                not isinstance(supplement, dict)
                or set(supplement)
                not in (
                    {"dataset_id", "symbols"},
                    {"dataset_id", "symbols", "session_memberships"},
                )
                or not isinstance(supplement["dataset_id"], str)
                or not isinstance(supplement["symbols"], list)
                or not supplement["symbols"]
                or any(not isinstance(symbol, str) for symbol in supplement["symbols"])
                or supplement["symbols"] != sorted(set(supplement["symbols"]))
            ):
                raise ValueError("research_market_supplement_binding_invalid")
            members = set(supplement["symbols"])
            selected_keys = None
            if "session_memberships" in supplement:
                sessions = supplement["session_memberships"]
                if not isinstance(sessions, list) or not sessions:
                    raise ValueError("research_market_supplement_binding_invalid")
                selected_keys = set()
                days = []
                for session in sessions:
                    if (
                        not isinstance(session, dict)
                        or set(session) != {"trade_date", "symbols"}
                        or not isinstance(session["trade_date"], str)
                        or not isinstance(session["symbols"], list)
                        or not session["symbols"]
                        or any(
                            not isinstance(symbol, str) for symbol in session["symbols"]
                        )
                        or session["symbols"] != sorted(set(session["symbols"]))
                        or not set(session["symbols"]) <= members
                    ):
                        raise ValueError("research_market_supplement_binding_invalid")
                    day = session["trade_date"]
                    if (
                        date.fromisoformat(day).isoformat() != day
                        or not start_date <= day <= end_date
                    ):
                        raise ValueError("research_market_supplement_binding_invalid")
                    days.append(day)
                    selected_keys.update((day, symbol) for symbol in session["symbols"])
                if (
                    days != sorted(set(days))
                    or {symbol for _, symbol in selected_keys} != members
                ):
                    raise ValueError("research_market_supplement_binding_invalid")
            result = read_daily_bar_dataset(
                objects, DatasetRef(objects.resolve_ref(supplement["dataset_id"]))
            )
            if (
                result.snapshot.cutoff > supplement_as_of
                or not result.snapshot.verification_bound
                or not members
                <= {
                    key.symbol
                    for key in result.snapshot.instruments
                    if key.instrument_type.value == "stock"
                }
            ):
                raise ValueError("research_market_supplement_unverified")
            providers = {part.provider for part in result.snapshot.partitions}
            actual_keys = {
                (bar.session_date.isoformat(), bar.instrument.symbol)
                for bar in result.bars
                if bar.instrument.instrument_type.value == "stock"
                and bar.instrument.symbol in members
                and start_date <= bar.session_date.isoformat() <= end_date
                and (
                    selected_keys is None
                    or (bar.session_date.isoformat(), bar.instrument.symbol)
                    in selected_keys
                )
            }
            if selected_keys is not None and selected_keys != actual_keys:
                raise ValueError("research_market_supplement_membership_mismatch")
            if actual_keys & (all_receipt_keys | bound_keys):
                raise ValueError("research_market_supplement_overlap")
            bound_keys.update(actual_keys)
            for symbol in members:
                supplement_providers[symbol] = (
                    "receipt_and_verified_supplement"
                    if symbol in all_receipt_symbols
                    else (
                        next(iter(providers))
                        if len(providers) == 1
                        else "verified_multi_source"
                    )
                )
            for symbol, frame in verified_daily_market_frames(
                result,
                members & wanted,
                start_date,
                end_date,
                selected_keys=selected_keys,
            ).items():
                parts.append(frame.assign(symbol=symbol))
    frame = pd.concat(parts, ignore_index=True)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    result = {}
    for symbol, group in frame.groupby("symbol", sort=True):
        bars = (
            group.drop(columns="symbol").sort_values("timestamp").reset_index(drop=True)
        )
        bars.attrs.update(
            provider_name=supplement_providers.get(
                str(symbol), str(refs[0]["provider_name"])
            ),
            adjustment_mode="none",
            volume_unit="shares",
            amount_unit="CNY",
        )
        result[str(symbol)] = bars
    return result
