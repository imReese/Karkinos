"""Shared Decision constants, value normalization, and projection ports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

ACCOUNT_STRATEGY_CONTROL_KEY = "account_strategy_assignment"
STRATEGY_ATTRIBUTION_READY_STATUSES = {"evidence_bound_from_posted_fills"}
READY_MANUAL_CONFIRMATION_STATUS = "ready_for_manual_confirmation"
TRUSTED_DATA_STATUSES = {"complete", "confirmed", "fresh", "live", "pass"}
REVIEW_DATA_STATUSES = {
    "cache",
    "cache_only",
    "confirmed_nav_missing",
    "estimated",
    "partial",
    "stale",
    "unknown",
}
BLOCKING_DATA_STATUSES = {"blocked", "error", "missing", "unavailable"}
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class DecisionProjectionPorts:
    """Facade-owned seams used to compose a Decision projection."""

    portfolio_context: Callable[[Any], dict[str, Any]]
    read_action_tasks: Callable[..., list[dict[str, Any]]]
    allocate_actions: Callable[
        [Any, dict[str, Any], list[dict[str, Any]]],
        list[dict[str, Any]],
    ]
    journal_by_signal_id: Callable[[Any], dict[int, dict[str, Any]]]
    validation_by_strategy_id: Callable[[Any], Any]
    account_truth_evidence: Callable[[Any], dict[str, Any]]
    strategy_attribution_evidence: Callable[
        [Any, Any, list[dict[str, Any]]],
        dict[str, Any],
    ]
    decision_candidate: Callable[..., dict[str, Any]]
    decision_summary: Callable[..., dict[str, Any]]


def parse_action_timestamp(value: Any) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=SHANGHAI_TZ)
    return parsed.astimezone(SHANGHAI_TZ)


def action_trade_date(action: dict[str, Any]) -> str | None:
    parsed = parse_action_timestamp(action.get("timestamp"))
    return parsed.date().isoformat() if parsed is not None else None


def action_sort_key(action: dict[str, Any]) -> tuple[float, int]:
    timestamp = parse_action_timestamp(action.get("timestamp"))
    try:
        action_id = int(action.get("id") or 0)
    except (TypeError, ValueError):
        action_id = 0
    return (
        timestamp.timestamp() if timestamp is not None else float("-inf"),
        action_id,
    )


def normalize_decision_action(action: dict[str, Any]) -> str:
    direction = str(action.get("direction") or "").lower()
    if direction in {"buy", "sell", "hold", "rebalance"}:
        return direction
    return "review_required"


def is_intraday_action(action: dict[str, Any]) -> bool:
    asset_class = str(action.get("asset_class") or "").lower()
    symbol = str(action.get("symbol") or "")
    if asset_class == "stock":
        return True
    if asset_class in {"fund", "etf"}:
        return looks_exchange_traded_fund_symbol(symbol)
    return False


def looks_exchange_traded_fund_symbol(symbol: str) -> bool:
    return symbol.startswith(
        (
            "159",
            "510",
            "511",
            "512",
            "513",
            "515",
            "516",
            "517",
            "518",
            "560",
            "561",
            "562",
            "563",
            "588",
        )
    )


def overall_decision(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "no_action"
    if any(
        candidate["evidence"].get("certainty", {}).get("status") != "pass"
        for candidate in candidates
    ):
        return "review_required"
    if any(candidate["risk_gate_status"] != "passed" for candidate in candidates):
        return "review_required"
    if any(
        candidate["evidence"]["account_truth"]["gate_status"] != "pass"
        for candidate in candidates
    ):
        return "review_required"
    if any(
        candidate["evidence"]["strategy_attribution"]["gate_status"] != "pass"
        for candidate in candidates
    ):
        return "review_required"
    actions = {candidate["action"] for candidate in candidates}
    if len(actions) == 1:
        return next(iter(actions))
    if actions <= {"buy", "sell", "rebalance"}:
        return "rebalance"
    return "review_required"


def has_ready_manual_confirmation(candidates: list[dict[str, Any]]) -> bool:
    return any(
        candidate.get("manual_confirmation_required")
        and candidate.get("manual_confirmation_status")
        == READY_MANUAL_CONFIRMATION_STATUS
        for candidate in candidates
    )


def data_quality_manual_confirmation_status(
    data_freshness: dict[str, Any],
) -> str | None:
    status = str(data_freshness.get("status") or "unknown")
    if status in TRUSTED_DATA_STATUSES:
        return None
    if status in BLOCKING_DATA_STATUSES:
        return "blocked_by_data_quality"
    return "data_review_required"


def account_truth_manual_confirmation_status(gate_status: str) -> str:
    if gate_status == "degraded":
        return "account_truth_review_required"
    return "blocked_by_account_truth"


def append_unique_text(values: list[str], value: Any) -> None:
    if value is None:
        return
    text = str(value)
    if text and text not in values:
        values.append(text)


def float_or_zero(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def int_or_none(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
