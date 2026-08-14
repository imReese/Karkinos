"""Deterministic maximum-drawdown evidence from a persisted equity curve."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

BACKTEST_DRAWDOWN_EVIDENCE_SCHEMA_VERSION = "karkinos.backtest_drawdown.v1"


def build_backtest_drawdown_evidence(
    *,
    equity_curve: Iterable[Any],
) -> dict[str, Any]:
    """Build point-by-point peak and drawdown evidence from one equity curve."""

    rows = list(equity_curve)
    issues: list[str] = []
    normalized: list[tuple[str, datetime, Decimal]] = []
    for index, row in enumerate(rows):
        parsed = _equity_row(row)
        if parsed is None:
            issues.append(f"equity_curve_point_invalid:{index}")
            continue
        timestamp_text, timestamp, equity = parsed
        if normalized and timestamp <= normalized[-1][1]:
            issues.append(f"equity_curve_timestamp_not_increasing:{index}")
        normalized.append((timestamp_text, timestamp, equity))
    if len(rows) < 2:
        issues.append("equity_curve_points_insufficient")
    if len(normalized) != len(rows):
        issues.append("equity_curve_normalization_incomplete")

    points: list[dict[str, Any]] = []
    peak: Decimal | None = None
    for index, (timestamp_text, _, equity) in enumerate(normalized):
        peak = equity if peak is None else max(peak, equity)
        drawdown = (peak - equity) / peak
        points.append(
            {
                "point_index": index,
                "timestamp": timestamp_text,
                "equity": format(equity, "f"),
                "peak_equity": format(peak, "f"),
                "drawdown_pct": format(drawdown, "f"),
            }
        )

    issues = list(dict.fromkeys(issues))
    max_drawdown = max(
        (_decimal(point["drawdown_pct"]) or Decimal("0") for point in points),
        default=Decimal("0"),
    )
    complete = not issues and len(points) >= 2
    core = {
        "schema_version": BACKTEST_DRAWDOWN_EVIDENCE_SCHEMA_VERSION,
        "status": "complete" if complete else "incomplete",
        "model_reference": "karkinos.backtest_drawdown.running_peak.v1",
        "point_count": len(rows),
        "observation_count": len(points),
        "max_drawdown_pct": format(max_drawdown, "f"),
        "points": points,
        "issues": issues,
        "assumptions": [
            "Each point is taken from the exact persisted after-cost backtest equity curve.",
            "Drawdown is the nonnegative decline from the running equity peak divided by that peak.",
        ],
        "limitations": [
            "Historical simulated drawdown does not guarantee a future loss bound.",
            "This evidence is research-only and grants no execution or capital authority.",
        ],
        "source_equity_curve_only": True,
        "human_review_required": True,
        "authorizes_execution": False,
        "does_not_change_capital_authority": True,
    }
    return {**core, "evidence_fingerprint": _fingerprint(core)}


def is_valid_complete_backtest_drawdown_evidence(
    value: Any,
    *,
    expected_max_drawdown: Any,
    expected_equity_curve: Any,
    expected_initial_equity: Any,
    expected_final_equity: Any,
) -> bool:
    """Replay running peaks and bind them to the persisted curve and summaries."""

    if not isinstance(value, Mapping):
        return False
    payload = dict(value)
    evidence_fingerprint = payload.pop("evidence_fingerprint", None)
    raw_points = payload.get("points")
    if not isinstance(raw_points, list) or len(raw_points) < 2:
        return False
    expected_curve = _normalized_equity_curve(expected_equity_curve)
    expected_drawdown = _decimal(expected_max_drawdown)
    expected_initial = _decimal(expected_initial_equity)
    expected_final = _decimal(expected_final_equity)
    reported_drawdown = _decimal(payload.get("max_drawdown_pct"))
    point_count = _integer(payload.get("point_count"))
    observation_count = _integer(payload.get("observation_count"))
    if (
        payload.get("schema_version") != BACKTEST_DRAWDOWN_EVIDENCE_SCHEMA_VERSION
        or payload.get("status") != "complete"
        or payload.get("model_reference")
        != "karkinos.backtest_drawdown.running_peak.v1"
        or expected_curve is None
        or len(expected_curve) < 2
        or expected_drawdown is None
        or not 0 <= expected_drawdown < 1
        or expected_initial is None
        or expected_initial <= 0
        or expected_final is None
        or expected_final <= 0
        or reported_drawdown is None
        or not 0 <= reported_drawdown < 1
        or point_count != len(raw_points)
        or observation_count != len(raw_points)
        or len(expected_curve) != len(raw_points)
        or payload.get("issues") != []
        or not _nonempty_text_list(payload.get("assumptions"))
        or not _nonempty_text_list(payload.get("limitations"))
        or payload.get("source_equity_curve_only") is not True
        or payload.get("human_review_required") is not True
        or payload.get("authorizes_execution") is not False
        or payload.get("does_not_change_capital_authority") is not True
        or not isinstance(evidence_fingerprint, str)
        or len(evidence_fingerprint) != 64
        or evidence_fingerprint.lower() != _fingerprint(payload)
    ):
        return False

    drawdowns: list[Decimal] = []
    peak: Decimal | None = None
    prior_timestamp: datetime | None = None
    for index, (raw_point, expected_point) in enumerate(
        zip(raw_points, expected_curve, strict=True)
    ):
        if not isinstance(raw_point, Mapping) or set(raw_point) != {
            "point_index",
            "timestamp",
            "equity",
            "peak_equity",
            "drawdown_pct",
        }:
            return False
        timestamp = _timestamp(raw_point.get("timestamp"))
        equity = _decimal(raw_point.get("equity"))
        reported_peak = _decimal(raw_point.get("peak_equity"))
        drawdown = _decimal(raw_point.get("drawdown_pct"))
        if (
            _integer(raw_point.get("point_index")) != index
            or timestamp is None
            or prior_timestamp is not None
            and timestamp <= prior_timestamp
            or equity is None
            or equity <= 0
            or reported_peak is None
            or reported_peak <= 0
            or drawdown is None
            or not 0 <= drawdown < 1
            or str(raw_point.get("timestamp")) != expected_point[0]
            or equity != expected_point[2]
        ):
            return False
        peak = equity if peak is None else max(peak, equity)
        expected_point_drawdown = (peak - equity) / peak
        if reported_peak != peak or drawdown != expected_point_drawdown:
            return False
        prior_timestamp = timestamp
        drawdowns.append(drawdown)

    return (
        _decimal(raw_points[0]["equity"]) == expected_initial
        and _decimal(raw_points[-1]["equity"]) == expected_final
        and max(drawdowns) == reported_drawdown
        and _close_decimal(reported_drawdown, expected_drawdown)
    )


def _normalized_equity_curve(value: Any) -> list[tuple[str, datetime, Decimal]] | None:
    if not isinstance(value, list):
        return None
    normalized: list[tuple[str, datetime, Decimal]] = []
    for row in value:
        parsed = _equity_row(row)
        if parsed is None:
            return None
        if normalized and parsed[1] <= normalized[-1][1]:
            return None
        normalized.append(parsed)
    return normalized


def _equity_row(value: Any) -> tuple[str, datetime, Decimal] | None:
    if isinstance(value, Mapping):
        raw_timestamp = value.get("timestamp")
        raw_equity = value.get("equity")
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        raw_timestamp, raw_equity = value
    else:
        return None
    timestamp = _timestamp(raw_timestamp)
    equity = _decimal(raw_equity)
    if timestamp is None or equity is None or equity <= 0:
        return None
    return timestamp.isoformat(), timestamp, equity


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return timestamp if timestamp.isoformat() == value else None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return normalized if normalized.is_finite() else None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _close_decimal(left: Decimal, right: Decimal) -> bool:
    tolerance = max(
        Decimal("1e-9"),
        max(abs(left), abs(right)) * Decimal("1e-9"),
    )
    return abs(left - right) <= tolerance


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
