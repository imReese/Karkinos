"""Factor evaluation and curated universe analytics service."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from analytics.factor_evaluation import (
    calculate_quantile_returns,
    calculate_rank_ic,
    summarize_ic,
    summarize_quantile_spread,
)
from core.types import BarFrequency
from data.store import DataStore
from data.universe import UniverseMember, get_universe, list_universes
from server.runtime_paths import resolve_data_dir


def list_curated_universes() -> list[dict[str, Any]]:
    """List all pre-configured multi-asset/ETF universes."""
    return [
        {
            "universe_id": u.universe_id,
            "display_name": u.display_name,
            "description": u.description,
            "benchmark_symbol": str(u.benchmark_symbol) if u.benchmark_symbol else None,
            "cash_proxy_symbol": str(u.cash_proxy_symbol)
            if u.cash_proxy_symbol
            else None,
            "symbols": [str(s) for s in u.symbols],
            "member_count": len(u.members),
            "members": [
                {
                    "symbol": str(m.symbol),
                    "name": m.name,
                    "asset_class": m.asset_class.value,
                    "instrument_type": m.instrument_type.value,
                    "benchmark": m.benchmark,
                    "cash_proxy": m.cash_proxy,
                    "description": m.description,
                }
                for m in u.members
            ],
        }
        for u in list_universes()
    ]


def get_curated_universe(universe_id: str) -> dict[str, Any] | None:
    """Retrieve universe definition by ID."""
    u = get_universe(universe_id)
    if u is None:
        return None
    return {
        "universe_id": u.universe_id,
        "display_name": u.display_name,
        "description": u.description,
        "benchmark_symbol": str(u.benchmark_symbol) if u.benchmark_symbol else None,
        "cash_proxy_symbol": str(u.cash_proxy_symbol) if u.cash_proxy_symbol else None,
        "symbols": [str(s) for s in u.symbols],
        "member_count": len(u.members),
        "members": [
            {
                "symbol": str(m.symbol),
                "name": m.name,
                "asset_class": m.asset_class.value,
                "instrument_type": m.instrument_type.value,
                "benchmark": m.benchmark,
                "cash_proxy": m.cash_proxy,
                "description": m.description,
            }
            for m in u.members
        ],
    }


def _load_universe_price_panel(
    members: list[UniverseMember],
    data_dir: Path | None = None,
) -> pd.DataFrame:
    """Load daily close prices for symbols into an aligned date-indexed DataFrame."""
    root = data_dir if data_dir is not None else Path(resolve_data_dir())
    store = DataStore(root)

    price_series: dict[str, pd.Series] = {}
    missing = []
    for member in members:
        df = store.load_bars(
            member.symbol,
            frequency=BarFrequency.DAILY,
            instrument_type=member.instrument_type,
        )
        if df is None or df.empty:
            missing.append(str(member.symbol))
            continue
        if not {"timestamp", "close"}.issubset(df.columns):
            raise ValueError(f"factor_price_columns_missing:{member.symbol}")
        dates = pd.to_datetime(df["timestamp"], errors="coerce").dt.normalize()
        closes = pd.to_numeric(df["close"], errors="coerce")
        if (
            dates.isna().any()
            or dates.duplicated().any()
            or not np.isfinite(closes).all()
            or (closes <= 0).any()
        ):
            raise ValueError(f"factor_price_data_invalid:{member.symbol}")
        price_series[str(member.symbol)] = pd.Series(closes.to_numpy(), index=dates)
    if missing:
        raise ValueError("factor_price_data_missing:" + ",".join(missing))
    panel = pd.DataFrame(price_series).sort_index()
    if panel.isna().any().any():
        raise ValueError("factor_price_history_incomplete")
    return panel


def compute_factor_panel(
    price_df: pd.DataFrame,
    factor_type: str,
    lookback_period: int,
) -> pd.DataFrame:
    """Compute cross-sectional factor values across all symbols."""
    period = max(2, lookback_period)
    if factor_type == "reversal":
        # Short-term reversal (negative momentum)
        return -1.0 * (price_df / price_df.shift(period) - 1.0)
    elif factor_type == "volatility":
        # Rolling annualized volatility
        daily_rets = price_df.pct_change(fill_method=None)
        return daily_rets.rolling(period).std() * math.sqrt(252)
    elif factor_type == "risk_adjusted_momentum":
        # Momentum / Volatility (Sharpe-like ratio)
        mom = price_df / price_df.shift(period) - 1.0
        daily_rets = price_df.pct_change(fill_method=None)
        vol = daily_rets.rolling(period).std() * math.sqrt(252)
        return mom / vol.clip(lower=0.04)
    elif factor_type == "rsi":
        factor_dict = {}
        for col in price_df.columns:
            delta = price_df[col].diff()
            gain = delta.where(delta > 0, 0.0)
            loss = -delta.where(delta < 0, 0.0)
            avg_gain = gain.ewm(
                alpha=1 / period, min_periods=period, adjust=False
            ).mean()
            avg_loss = loss.ewm(
                alpha=1 / period, min_periods=period, adjust=False
            ).mean()
            rs = avg_gain / avg_loss.clip(lower=1e-6)
            factor_dict[col] = 100.0 - (100.0 / (1.0 + rs))
        return pd.DataFrame(factor_dict, index=price_df.index)
    else:
        # Default: Momentum (period-day return)
        return price_df / price_df.shift(period) - 1.0


def run_factor_evaluation(
    universe_id: str = "core_etf_universe",
    factor_type: str = "momentum",
    lookback_period: int = 20,
    forward_period: int = 5,
    n_quantiles: int = 5,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute end-to-end cross-sectional factor evaluation."""
    u = get_universe(universe_id)
    if u is None:
        raise ValueError(f"universe_not_found: {universe_id}")
    if factor_type not in {
        "momentum",
        "reversal",
        "volatility",
        "risk_adjusted_momentum",
        "rsi",
    }:
        raise ValueError("factor_type_unsupported")
    for name, value, minimum, maximum in (
        ("lookback_period", lookback_period, 2, 250),
        ("forward_period", forward_period, 1, 60),
        ("n_quantiles", n_quantiles, 2, 10),
    ):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"factor_{name}_invalid")

    members = [member for member in u.members if not member.cash_proxy]
    if len(members) < 2:
        raise ValueError("factor_universe_insufficient_assets")

    price_df = _load_universe_price_panel(members, data_dir=data_dir)
    if len(price_df) < lookback_period + 2 * forward_period + 1:
        raise ValueError("factor_price_history_insufficient")
    factor_df = compute_factor_panel(price_df, factor_type, lookback_period)
    forward_rets = price_df.shift(-forward_period) / price_df - 1.0

    rank_ic_series = calculate_rank_ic(factor_df, forward_rets)
    ic_summary = summarize_ic(rank_ic_series, holding_period=forward_period)

    quantile_count = min(n_quantiles, len(members))
    quantile_df = calculate_quantile_returns(
        factor_df, forward_rets, n_quantiles=quantile_count
    )
    spread_summary = summarize_quantile_spread(
        quantile_df, holding_period=forward_period
    )

    # Time series formatting
    ic_clean = (
        rank_ic_series.iloc[::forward_period]
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )
    ic_items = [
        {"date": dt.strftime("%Y-%m-%d"), "ic": round(float(val), 4)}
        for dt, val in ic_clean.items()
    ]

    # Quantile returns formatting & cumulative calculation
    q_cols = [c for c in quantile_df.columns if c.startswith("Q") or c == "long_short"]
    cum_wealth = {c: 1.0 for c in q_cols}
    cum_rows = []

    sampled_quantiles = (
        quantile_df.iloc[::forward_period].replace([np.inf, -np.inf], np.nan).dropna()
    )
    if not sampled_quantiles.empty:
        cum_rows.append(
            {
                "date": sampled_quantiles.index[0].strftime("%Y-%m-%d"),
                **{key.lower(): value for key, value in cum_wealth.items()},
            }
        )
    for dt, row in sampled_quantiles.iterrows():
        # The forward return ends horizon rows after its factor decision. Do not
        # date an already-realized cumulative result at the earlier decision.
        endpoint = price_df.index.get_loc(dt) + forward_period
        c_record: dict[str, Any] = {
            "date": price_df.index[endpoint].strftime("%Y-%m-%d")
        }
        for c in q_cols:
            val = float(row[c])
            cum_wealth[c] *= 1.0 + val
            c_record[c.lower()] = round(cum_wealth[c], 4)
        cum_rows.append(c_record)

    # Latest cross-section ranking
    valid_factor_rows = factor_df.dropna(how="all")
    cross_section = []
    if not valid_factor_rows.empty:
        latest_date = valid_factor_rows.index[-1]
        latest_series = (
            valid_factor_rows.loc[latest_date]
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
            .sort_index()
        )
        ranks = latest_series.rank(ascending=False, method="first")
        total_valid = len(latest_series)

        member_map = {str(m.symbol): m.name for m in u.members}
        for sym_str, score in latest_series.items():
            r = int(ranks.get(sym_str, 0))
            pct = (
                round((total_valid - r + 1) / total_valid * 100, 1)
                if total_valid > 0
                else 0.0
            )
            cross_section.append(
                {
                    "symbol": sym_str,
                    "name": member_map.get(sym_str, sym_str),
                    "factor_value": round(float(score), 4),
                    "rank": r,
                    "percentile": pct,
                }
            )
        cross_section.sort(key=lambda x: x["rank"])

    return {
        "universe_id": u.universe_id,
        "universe_name": u.display_name,
        "factor_type": factor_type,
        "lookback_period": lookback_period,
        "forward_period": forward_period,
        "n_quantiles": quantile_count,
        "sample_count": int(ic_summary.get("sample_count", 0)),
        "data_source": "local_typed_daily_bars",
        "data_start": price_df.index[0].strftime("%Y-%m-%d"),
        "data_end": price_df.index[-1].strftime("%Y-%m-%d"),
        "evaluated_symbols": [str(member.symbol) for member in members],
        "sampling": "fixed_nonoverlapping_daily_bar_rows",
        "return_basis": "gross_unadjusted_quantile_diagnostic",
        "research_only": True,
        "limitations": [
            "Local cached bars do not establish historical PIT availability or complete corporate-action coverage.",
            "Quantile spreads exclude fees and fills; they are not executable portfolio returns or promotion evidence.",
            "Fixed non-overlapping samples reduce horizon overlap; normal-approximation p-values do not prove independence or alpha.",
        ],
        "summary": ic_summary,
        "spread_summary": spread_summary,
        "ic_series": ic_items[-60:],  # Recent 60 periods for responsive charts
        "quantile_cumulative": cum_rows,
        "latest_cross_section": cross_section,
    }
