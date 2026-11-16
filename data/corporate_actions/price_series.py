"""Price series adjustment routines and OHLC invariant verification.

Applies forward (QFQ), backward (HFQ), unadjusted, or point-in-time (PIT)
adjustment factors to historical OHLCV bars while strictly preserving:
1. High >= max(Open, Close, Low)
2. Low <= min(Open, Close, High)
3. Non-negative prices and volumes
4. Volume scaling to maintain economic turnover invariance on share dilution.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import numpy as np
import pandas as pd

from data.corporate_actions.models import (
    AdjustmentFactorSeries,
    PriceBasis,
)


def verify_ohlcv_invariants(df: pd.DataFrame) -> None:
    """Verify that OHLC prices satisfy fundamental financial geometry invariants."""
    if df.empty:
        return

    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"dataframe_missing_required_ohlc_columns: {missing}")

    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)

    if (h < o - 1e-6).any() or (h < c - 1e-6).any() or (h < l - 1e-6).any():
        raise ValueError(
            "ohlc_invariant_violation: high must be >= max(open, close, low)"
        )

    if (l > o + 1e-6).any() or (l > c + 1e-6).any() or (l > h + 1e-6).any():
        raise ValueError(
            "ohlc_invariant_violation: low must be <= min(open, close, high)"
        )

    if (o <= 0).any() or (h <= 0).any() or (l <= 0).any() or (c <= 0).any():
        raise ValueError("ohlc_invariant_violation: prices must be strictly positive")

    if "volume" in df.columns:
        v = df["volume"].to_numpy(dtype=float)
        if (v < 0).any():
            raise ValueError("ohlc_invariant_violation: volume must be non-negative")


def adjust_ohlcv_dataframe(
    df: pd.DataFrame,
    factor_series: AdjustmentFactorSeries,
    basis: PriceBasis = PriceBasis.UNADJUSTED,
    *,
    adjust_volume: bool = True,
    price_precision: int | None = 4,
) -> pd.DataFrame:
    """Apply adjustment factors to an OHLCV dataframe.

    Parameters:
    - df: DataFrame with at least columns ['open', 'high', 'low', 'close']
          and optionally 'volume', 'amount'/'turnover'.
          Must have either a 'date' / 'trade_date' column or a DatetimeIndex.
    - factor_series: Pre-computed AdjustmentFactorSeries for the security.
    - basis: PriceBasis (UNADJUSTED, FORWARD, BACKWARD, POINT_IN_TIME).
    - adjust_volume: If True, scales volume inversely to share dilution.
    - price_precision: Rounding decimals for prices (e.g. 4 decimals); None for float precision.
    """
    if df.empty:
        return df.copy()

    if basis == PriceBasis.UNADJUSTED:
        out = df.copy()
        verify_ohlcv_invariants(out)
        return out

    out = df.copy()

    # Extract date series
    if "trade_date" in out.columns:
        dates = pd.to_datetime(out["trade_date"]).dt.date
    elif "date" in out.columns:
        dates = pd.to_datetime(out["date"]).dt.date
    elif "timestamp" in out.columns:
        dates = pd.to_datetime(out["timestamp"]).dt.date
    elif isinstance(out.index, pd.DatetimeIndex):
        dates = pd.Series(out.index.date, index=out.index)
    else:
        raise ValueError("dataframe_must_have_date_or_datetime_index")

    # Map factors
    factor_map = {f.trade_date: f for f in factor_series.factors}

    price_factors = []
    vol_factors = []

    for d in dates:
        fac = factor_map.get(d)
        if fac is None:
            price_factors.append(1.0)
            vol_factors.append(1.0)
        else:
            if basis in (PriceBasis.FORWARD, PriceBasis.POINT_IN_TIME):
                price_factors.append(float(fac.qfq_factor))
                vol_factors.append(float(fac.volume_factor))
            else:
                price_factors.append(float(fac.hfq_factor))
                # For HFQ, volume is either unadjusted or scaled by cumulative dilution
                vol_factors.append(1.0)

    p_mult = np.array(price_factors, dtype=float)
    v_mult = np.array(vol_factors, dtype=float)

    for col in ("open", "high", "low", "close"):
        if col in out.columns:
            adjusted = out[col].astype(float) * p_mult
            if price_precision is not None:
                adjusted = adjusted.round(price_precision)
            out[col] = adjusted

    if adjust_volume and "volume" in out.columns:
        adjusted_vol = out["volume"].astype(float) * v_mult
        out["volume"] = np.round(adjusted_vol)

    verify_ohlcv_invariants(out)
    return out
