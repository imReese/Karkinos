"""Deterministic capacity and liquidity evidence for one frozen backtest."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
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
    gross_turnover = sum(
        (_decimal(item["fill_notional"]) or Decimal("0") for item in observations),
        Decimal("0"),
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
        "gross_turnover": format(gross_turnover, "f"),
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


def is_valid_passed_backtest_capacity_evidence(
    value: Any,
    *,
    expected_initial_cash: Any | None = None,
    expected_gross_turnover: Any | None = None,
) -> bool:
    """Validate exact fill/bar capacity arithmetic before strategy advancement."""

    if not isinstance(value, Mapping):
        return False
    payload = dict(value)
    evidence_fingerprint = payload.pop("evidence_fingerprint", None)
    observations_raw = payload.get("observations")
    if not isinstance(observations_raw, list):
        return False
    observations = [
        dict(observation)
        for observation in observations_raw
        if isinstance(observation, Mapping)
    ]
    if len(observations) != len(observations_raw):
        return False
    fill_count = _integer(payload.get("fill_count"))
    observation_count = _integer(payload.get("observation_count"))
    max_participation = _decimal(payload.get("max_daily_volume_participation"))
    reported_capacity = _decimal(payload.get("capacity_utilization_pct"))
    reported_liquidity = _decimal(payload.get("liquidity_utilization_pct"))
    reported_turnover = _decimal(payload.get("gross_turnover"))
    expected_cash = _decimal(expected_initial_cash)
    expected_turnover = _decimal(expected_gross_turnover)
    if (
        payload.get("schema_version") != BACKTEST_CAPACITY_EVIDENCE_SCHEMA_VERSION
        or payload.get("status") != "pass"
        or payload.get("capacity_model_ref") != CAPACITY_MODEL_REFERENCE
        or fill_count is None
        or fill_count <= 0
        or observation_count != fill_count
        or len(observations) != fill_count
        or max_participation is None
        or not 0 < max_participation <= 1
        or reported_capacity is None
        or not 0 <= reported_capacity <= 1
        or reported_liquidity is None
        or not 0 <= reported_liquidity <= 1
        or reported_turnover is None
        or reported_turnover <= 0
        or (expected_initial_cash is not None and expected_cash is None)
        or (expected_cash is not None and expected_cash <= 0)
        or (expected_gross_turnover is not None and expected_turnover is None)
        or (expected_turnover is not None and expected_turnover <= 0)
        or payload.get("issues") != []
        or payload.get("persisted_market_data_only") is not True
        or payload.get("human_review_required") is not True
        or payload.get("authorizes_execution") is not False
        or payload.get("does_not_change_capital_authority") is not True
        or not _nonempty_text_list(payload.get("assumptions"))
        or not _nonempty_text_list(payload.get("limitations"))
        or not isinstance(evidence_fingerprint, str)
        or len(evidence_fingerprint) != 64
        or evidence_fingerprint.lower() != _fingerprint(payload)
    ):
        return False

    capacities: list[Decimal] = []
    liquidities: list[Decimal] = []
    fill_indexes: list[int] = []
    for observation in observations:
        fill_index = _integer(observation.get("fill_index"))
        fill_notional = _decimal(observation.get("fill_notional"))
        bar_notional = _decimal(observation.get("bar_notional"))
        raw_participation = _decimal(observation.get("raw_volume_participation"))
        capacity = _decimal(observation.get("capacity_utilization_pct"))
        liquidity = _decimal(observation.get("liquidity_utilization_pct"))
        timestamp = str(observation.get("timestamp") or "").strip()
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return False
        if (
            fill_index is None
            or not str(observation.get("symbol") or "").strip()
            or fill_notional is None
            or fill_notional <= 0
            or bar_notional is None
            or bar_notional <= 0
            or raw_participation is None
            or raw_participation <= 0
            or capacity is None
            or not 0 < capacity <= 1
            or (expected_cash is not None and fill_notional / expected_cash != capacity)
            or liquidity is None
            or not 0 < liquidity <= 1
            or raw_participation / max_participation != liquidity
        ):
            return False
        fill_indexes.append(fill_index)
        capacities.append(capacity)
        liquidities.append(liquidity)

    return (
        fill_indexes == list(range(fill_count))
        and max(capacities) == reported_capacity
        and max(liquidities) == reported_liquidity
        and sum(
            (
                _decimal(observation["fill_notional"]) or Decimal("0")
                for observation in observations
            ),
            Decimal("0"),
        )
        == reported_turnover
        and (expected_turnover is None or reported_turnover == expected_turnover)
    )


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return normalized if normalized.is_finite() else None


def _integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _nonempty_text_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
