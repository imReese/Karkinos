"""Deterministic capacity and liquidity evidence for one frozen backtest."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

import pandas as pd

BACKTEST_CAPACITY_EVIDENCE_SCHEMA_VERSION = "karkinos.backtest_capacity.v1"
CAPACITY_MODEL_REFERENCE = "karkinos.backtest.capacity.daily_bar_participation.v1"
DEFAULT_MAX_DAILY_VOLUME_PARTICIPATION = Decimal("0.10")


def build_backtest_capacity_evidence(
    *,
    fills: Iterable[Any],
    data_handlers: Mapping[Any, Any],
    initial_cash: Any,
    max_daily_volume_participation: Decimal = DEFAULT_MAX_DAILY_VOLUME_PARTICIPATION,
) -> dict[str, Any]:
    """Compare exact fills with account capital and same-bar persisted liquidity."""

    fill_list = list(fills)
    cash = _decimal(initial_cash)
    issues: list[str] = []
    observations: list[dict[str, Any]] = []
    if cash is None or cash <= 0:
        issues.append("initial_cash_invalid")
    if max_daily_volume_participation <= 0 or max_daily_volume_participation > 1:
        issues.append("daily_volume_participation_limit_invalid")
    if not fill_list:
        issues.append("capacity_fill_evidence_missing")

    frames = {
        str(symbol): getattr(handler, "_df", None)
        for symbol, handler in data_handlers.items()
    }
    for index, fill in enumerate(fill_list):
        symbol = str(getattr(fill, "symbol", ""))
        timestamp = pd.Timestamp(getattr(fill, "timestamp", None))
        quantity = _decimal(getattr(fill, "fill_quantity", None))
        price = _decimal(getattr(fill, "fill_price", None))
        frame = frames.get(symbol)
        if (
            not symbol
            or pd.isna(timestamp)
            or quantity is None
            or quantity <= 0
            or price is None
            or price <= 0
            or not isinstance(frame, pd.DataFrame)
            or "timestamp" not in frame.columns
            or "volume" not in frame.columns
        ):
            issues.append(f"capacity_fill_or_bar_invalid:{index}")
            continue
        bar_timestamps = pd.to_datetime(frame["timestamp"])
        matching = frame.loc[bar_timestamps == timestamp]
        if len(matching) != 1:
            issues.append(f"capacity_bar_identity_missing:{index}")
            continue
        volume = _decimal(matching.iloc[0]["volume"])
        close = _decimal(matching.iloc[0].get("close"))
        if volume is None or volume <= 0 or close is None or close <= 0:
            issues.append(f"capacity_bar_liquidity_invalid:{index}")
            continue
        fill_notional = quantity * price
        capacity_utilization = fill_notional / cash if cash else Decimal("Infinity")
        raw_volume_participation = quantity / volume
        liquidity_utilization = (
            raw_volume_participation / max_daily_volume_participation
        )
        observations.append(
            {
                "fill_index": index,
                "symbol": symbol,
                "timestamp": timestamp.isoformat(),
                "fill_notional": format(fill_notional, "f"),
                "bar_notional": format(volume * close, "f"),
                "raw_volume_participation": format(raw_volume_participation, "f"),
                "capacity_utilization_pct": format(capacity_utilization, "f"),
                "liquidity_utilization_pct": format(liquidity_utilization, "f"),
            }
        )

    issues = list(dict.fromkeys(issues))
    max_capacity = max(
        (
            _decimal(item["capacity_utilization_pct"]) or Decimal("0")
            for item in observations
        ),
        default=Decimal("0"),
    )
    max_liquidity = max(
        (
            _decimal(item["liquidity_utilization_pct"]) or Decimal("0")
            for item in observations
        ),
        default=Decimal("0"),
    )
    passed = (
        bool(observations) and not issues and max_capacity <= 1 and max_liquidity <= 1
    )
    core = {
        "schema_version": BACKTEST_CAPACITY_EVIDENCE_SCHEMA_VERSION,
        "status": "pass" if passed else "blocked",
        "capacity_model_ref": CAPACITY_MODEL_REFERENCE,
        "capacity_utilization_pct": format(max_capacity, "f"),
        "liquidity_utilization_pct": format(max_liquidity, "f"),
        "max_daily_volume_participation": format(max_daily_volume_participation, "f"),
        "fill_count": len(fill_list),
        "observation_count": len(observations),
        "observations": observations,
        "issues": issues,
        "assumptions": [
            "Capacity is bounded by the frozen initial cash supplied to the canonical backtest.",
            "Liquidity stress uses each fill quantity divided by exact same-bar persisted volume and a 10 percent participation ceiling.",
        ],
        "limitations": [
            "Daily-bar volume is a conservative research proxy and does not prove executable intraday depth or market impact.",
            "Capacity evidence grants no trading or capital authority and must be reviewed against live account limits before any manual ticket.",
        ],
        "persisted_market_data_only": True,
        "human_review_required": True,
        "authorizes_execution": False,
        "does_not_change_capital_authority": True,
    }
    return {**core, "evidence_fingerprint": _fingerprint(core)}


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
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
