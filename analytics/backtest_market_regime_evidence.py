"""Frozen-market regime robustness evidence for canonical backtest results."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

import pandas as pd

MARKET_REGIME_EVIDENCE_SCHEMA_VERSION = "karkinos.market_regime_robustness.v1"


def build_backtest_market_regime_evidence(
    *,
    result: Any,
    data_handlers: Mapping[Any, Any],
) -> dict[str, Any]:
    """Measure candidate net equity returns across rising/falling frozen bars."""

    issues: list[str] = []
    market_returns = _equal_weight_market_returns(data_handlers)
    equity_returns = _equity_returns(getattr(result, "equity_curve", []))
    if market_returns.empty:
        issues.append("market_regime_returns_missing")
    if equity_returns.empty:
        issues.append("candidate_equity_returns_missing")
    aligned = pd.concat(
        [market_returns.rename("market_return"), equity_returns.rename("net_return")],
        axis=1,
        join="inner",
    ).dropna()
    if aligned.empty:
        issues.append("market_candidate_regime_alignment_missing")

    if not aligned.empty:
        aligned["regime"] = aligned["market_return"].map(_regime_name)
    regimes: list[dict[str, Any]] = []
    for name, group in aligned.groupby("regime", sort=True):
        compounded = _compound(group["net_return"])
        passed = len(group) >= 2 and compounded >= 0
        regimes.append(
            {
                "name": str(name),
                "observation_count": int(len(group)),
                "market_return": format(_compound(group["market_return"]), "f"),
                "candidate_net_return": format(compounded, "f"),
                "status": "pass" if passed else "blocked",
            }
        )

    failed_count = sum(1 for regime in regimes if regime["status"] != "pass")
    status = (
        "pass" if not issues and len(regimes) >= 2 and failed_count == 0 else "blocked"
    )
    core = {
        "schema_version": MARKET_REGIME_EVIDENCE_SCHEMA_VERSION,
        "status": status,
        "regime_definition": "equal_weight_frozen_close_return_sign.v1",
        "regime_count": len(regimes),
        "failed_regime_count": failed_count,
        "aligned_observation_count": int(len(aligned)),
        "regimes": regimes,
        "issues": list(dict.fromkeys(issues)),
        "assumptions": [
            "Each timestamp market return is the equal-weight mean of available frozen-symbol close returns.",
            "Rising, falling, and flat states are classified only from the sign of that persisted market return.",
            "Candidate returns use the canonical after-cost equity curve and require at least two observations in every passing state.",
        ],
        "limitations": [
            "This deterministic state partition is intentionally simple and does not prove robustness to every macro or volatility regime.",
            "Market-regime evidence is research-only and grants no strategy, execution, or capital authority.",
        ],
        "persisted_market_data_only": True,
        "human_review_required": True,
        "authorizes_execution": False,
        "does_not_change_capital_authority": True,
    }
    return {**core, "evidence_fingerprint": _fingerprint(core)}


def _equal_weight_market_returns(data_handlers: Mapping[Any, Any]) -> pd.Series:
    returns: list[pd.Series] = []
    for handler in data_handlers.values():
        frame = getattr(handler, "_df", None)
        if (
            not isinstance(frame, pd.DataFrame)
            or "timestamp" not in frame.columns
            or "close" not in frame.columns
        ):
            continue
        series = pd.Series(
            pd.to_numeric(frame["close"], errors="coerce").to_numpy(),
            index=pd.to_datetime(frame["timestamp"]),
            dtype=float,
        )
        returns.append(series.groupby(level=0).last().pct_change(fill_method=None))
    if not returns:
        return pd.Series(dtype=float)
    return pd.concat(returns, axis=1).mean(axis=1, skipna=True).dropna()


def _equity_returns(equity_curve: Any) -> pd.Series:
    rows = list(equity_curve or [])
    if len(rows) < 2:
        return pd.Series(dtype=float)
    series = pd.Series(
        [float(equity) for _, equity in rows],
        index=pd.to_datetime([timestamp for timestamp, _ in rows]),
        dtype=float,
    )
    return series.groupby(level=0).last().pct_change(fill_method=None).dropna()


def _regime_name(value: Any) -> str:
    normalized = float(value)
    if normalized > 0:
        return "rising"
    if normalized < 0:
        return "falling"
    return "flat"


def _compound(values: pd.Series) -> Decimal:
    result = Decimal("1")
    for value in values:
        normalized = _decimal(value)
        if normalized is not None:
            result *= Decimal("1") + normalized
    return result - Decimal("1")


def _decimal(value: Any) -> Decimal | None:
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return normalized if normalized.is_finite() else None


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
