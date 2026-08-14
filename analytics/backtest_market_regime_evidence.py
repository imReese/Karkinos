"""Frozen-market regime robustness evidence for canonical backtest results."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

import pandas as pd

MARKET_REGIME_EVIDENCE_SCHEMA_VERSION = "karkinos.market_regime_robustness.v2"
REQUIRED_MARKET_REGIMES = frozenset({"falling", "rising"})


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

    observations = [
        {
            "timestamp": pd.Timestamp(timestamp).isoformat(),
            "market_return": _format_decimal(row["market_return"]),
            "candidate_net_return": _format_decimal(row["net_return"]),
            "regime": _regime_name(row["market_return"]),
        }
        for timestamp, row in aligned.sort_index().iterrows()
    ]
    return _build_market_regime_evidence(
        observations=observations,
        issues=issues,
    )


def is_valid_passed_backtest_market_regime_evidence(value: Any) -> bool:
    """Replay persisted observation details and reject summary-only evidence."""

    if not isinstance(value, Mapping):
        return False
    payload = dict(value)
    fingerprint = str(payload.get("evidence_fingerprint") or "")
    core = {key: item for key, item in payload.items() if key != "evidence_fingerprint"}
    if (
        payload.get("schema_version") != MARKET_REGIME_EVIDENCE_SCHEMA_VERSION
        or payload.get("status") != "pass"
        or len(fingerprint) != 64
        or fingerprint != _fingerprint(core)
    ):
        return False

    raw_observations = payload.get("aligned_observations")
    if not isinstance(raw_observations, list) or not raw_observations:
        return False
    observations: list[dict[str, Any]] = []
    timestamps: set[str] = set()
    for raw in raw_observations:
        if not isinstance(raw, Mapping):
            return False
        timestamp = _normalized_timestamp(raw.get("timestamp"))
        market_return = _decimal(raw.get("market_return"))
        candidate_return = _decimal(raw.get("candidate_net_return"))
        regime = str(raw.get("regime") or "").strip()
        if (
            timestamp is None
            or timestamp in timestamps
            or market_return is None
            or candidate_return is None
            or market_return <= Decimal("-1")
            or candidate_return <= Decimal("-1")
            or regime != _regime_name(market_return)
        ):
            return False
        timestamps.add(timestamp)
        observations.append(
            {
                "timestamp": timestamp,
                "market_return": format(market_return, "f"),
                "candidate_net_return": format(candidate_return, "f"),
                "regime": regime,
            }
        )

    replayed = _build_market_regime_evidence(
        observations=observations,
        issues=[],
    )
    return payload == replayed


def _build_market_regime_evidence(
    *,
    observations: list[dict[str, Any]],
    issues: list[str],
) -> dict[str, Any]:
    canonical_observations = sorted(
        [dict(observation) for observation in observations],
        key=lambda observation: str(observation.get("timestamp") or ""),
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for observation in canonical_observations:
        grouped.setdefault(str(observation["regime"]), []).append(observation)

    regimes: list[dict[str, Any]] = []
    for name in sorted(grouped):
        rows = grouped[name]
        compounded = _compound(row["candidate_net_return"] for row in rows)
        passed = len(rows) >= 2 and compounded >= 0
        regimes.append(
            {
                "name": name,
                "observation_count": len(rows),
                "market_return": format(
                    _compound(row["market_return"] for row in rows), "f"
                ),
                "candidate_net_return": format(compounded, "f"),
                "status": "pass" if passed else "blocked",
            }
        )

    regime_names = {regime["name"] for regime in regimes}
    normalized_issues = list(dict.fromkeys(issues))
    if not REQUIRED_MARKET_REGIMES.issubset(regime_names):
        normalized_issues.append("required_market_regimes_missing")
    failed_count = sum(1 for regime in regimes if regime["status"] != "pass")
    status = "pass" if not normalized_issues and failed_count == 0 else "blocked"
    core = {
        "schema_version": MARKET_REGIME_EVIDENCE_SCHEMA_VERSION,
        "status": status,
        "regime_definition": "equal_weight_frozen_close_return_sign.v1",
        "regime_count": len(regimes),
        "failed_regime_count": failed_count,
        "required_regimes": sorted(REQUIRED_MARKET_REGIMES),
        "aligned_observation_count": len(canonical_observations),
        "aligned_observations": canonical_observations,
        "regimes": regimes,
        "issues": normalized_issues,
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


def _compound(values: Iterable[Any]) -> Decimal:
    result = Decimal("1")
    for value in values:
        normalized = _decimal(value)
        if normalized is not None:
            result *= Decimal("1") + normalized
    return result - Decimal("1")


def _format_decimal(value: Any) -> str:
    normalized = _decimal(value)
    if normalized is None:
        raise ValueError("market regime return must be finite")
    return format(normalized, "f")


def _normalized_timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(timestamp):
        return None
    normalized = timestamp.isoformat()
    return normalized if value == normalized else None


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
