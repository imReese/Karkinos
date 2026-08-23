"""Canonical persisted account-strategy assignment projection."""

from __future__ import annotations

from typing import Any

from server.models import AccountStrategyAssignment

ACCOUNT_STRATEGY_ASSIGNMENT_CONTROL_KEY = "account_strategy_assignment"
ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION = (
    "Strategy assignment is research context; contribution is shown only when "
    "current signals, reviews, orders, and fills have traceable references."
)


def default_account_strategy_assignment(config: Any) -> AccountStrategyAssignment:
    strategy_id = str(getattr(config, "strategy", "dual_ma") or "dual_ma")
    return AccountStrategyAssignment(
        strategy_id=strategy_id,
        strategy_name=strategy_id,
        status="research_only",
        scope="account",
        auto_trade_enabled=False,
        attribution_status="not_started",
        limitations=[ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION],
    )


def account_strategy_assignment_from_payload(
    payload: dict[str, Any],
    *,
    fallback_config: Any,
) -> AccountStrategyAssignment:
    fallback = default_account_strategy_assignment(fallback_config).model_dump()
    merged = {**fallback, **payload}
    merged["auto_trade_enabled"] = False
    merged.setdefault("limitations", [ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION])
    if not merged.get("limitations"):
        merged["limitations"] = [ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION]
    return AccountStrategyAssignment(**merged)
