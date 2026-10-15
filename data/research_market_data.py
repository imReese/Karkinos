"""Reproducible research views of immutable daily receipts.

Old receipts keep their original units and values. A new research snapshot binds
both those receipts and this explicit normalization version; no source row or
historical experiment is rewritten. Unknown historical units fail closed.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from data.market_daily_store import (
    CANONICAL_STOCK_BAR_UNITS,
    RESEARCH_BAR_NORMALIZATION,
    verify_market_daily_receipt_on_connection,
)


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
        binding.get("normalizer_version") != RESEARCH_BAR_NORMALIZATION
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
    parts = []
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
            if (
                not isinstance(receipt, dict)
                or any(
                    receipt.get(key) != ref.get(key)
                    for key in ("trade_date", "provider_name", "receipt_fingerprint")
                )
                or not verify_market_daily_receipt_on_connection(conn, receipt)
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
            legacy = schema == "karkinos.market_daily_ingestion_receipt.v1"
            cols = {row[1] for row in conn.execute("PRAGMA table_info(market_bars)")}
            identity = (
                "instrument_type='stock' AND" if "instrument_type" in cols else ""
            )
            frame = pd.read_sql_query(
                f"""SELECT symbol,timestamp,open,high,low,close,volume,amount
                    FROM market_bars WHERE {identity} frequency='1d'
                    AND substr(timestamp,1,10)=? ORDER BY symbol""",
                conn,
                params=[receipt["trade_date"]],
            )
            members = wanted.intersection(receipt["symbols"])
            frame = frame.loc[frame["symbol"].isin(members)].copy()
            for column, scale in (("volume", volume_scale), ("amount", amount_scale)):
                frame[column] = frame[column].map(
                    lambda value: (
                        float(Decimal(str(value)) * scale) if pd.notna(value) else None
                    )
                )
            parts.append(frame)
    finally:
        conn.close()
    frame = pd.concat(parts, ignore_index=True)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    result = {}
    for symbol, group in frame.groupby("symbol", sort=True):
        bars = (
            group.drop(columns="symbol").sort_values("timestamp").reset_index(drop=True)
        )
        bars.attrs.update(
            provider_name=str(refs[0]["provider_name"]),
            adjustment_mode="none",
            volume_unit="shares",
            amount_unit="CNY",
        )
        result[str(symbol)] = bars
    return result
