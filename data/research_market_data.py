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
            table = "market_bars" if legacy else "market_bars_v2"
            identity = "" if legacy else "instrument_type='stock' AND"
            frame = pd.read_sql_query(
                f"""SELECT symbol,timestamp,open,high,low,close,volume,amount
                    FROM {table} WHERE {identity} frequency='1d'
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
