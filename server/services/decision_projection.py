"""Top-level daily and intraday Decision response projection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from server.services.decision_contracts import (
    DecisionProjectionPorts,
    has_ready_manual_confirmation,
    is_intraday_action,
    overall_decision,
)
from server.services.decision_portfolio_projection import (
    action_filter_date,
    response_decision_date,
)


async def build_intraday_decision_payload(
    state: Any,
    *,
    ports: DecisionProjectionPorts,
) -> dict[str, Any]:
    """Build the canonical intraday Decision projection."""

    db = state.db
    portfolio_context = ports.portfolio_context(state)
    actions = ports.allocate_actions(
        state,
        portfolio_context,
        ports.read_action_tasks(
            db,
            decision_date=action_filter_date(portfolio_context),
        ),
    )
    decision_date = response_decision_date(portfolio_context, actions)
    intraday_actions = [action for action in actions if is_intraday_action(action)]
    daily_actions = [action for action in actions if not is_intraday_action(action)]
    journal_by_signal = ports.journal_by_signal_id(db)
    validation_by_strategy = await ports.validation_by_strategy_id(db)
    account_truth = ports.account_truth_evidence(state)
    strategy_attribution = ports.strategy_attribution_evidence(
        state,
        db,
        actions,
    )
    candidates = [
        ports.decision_candidate(
            action,
            journal_by_signal,
            validation_by_strategy,
            db,
            account_truth,
            strategy_attribution,
            state=state,
            quotes=dict(portfolio_context.get("quotes") or {}),
            allow_direct_quote_fallback=(
                portfolio_context.get("authority") != "persisted_valuation_snapshot"
            ),
        )
        for action in intraday_actions
    ]
    no_action_reasons = [] if candidates else ["no_intraday_stock_or_etf_action_tasks"]
    return {
        "lane": "intraday",
        "decision_date": decision_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cadence": "polling_or_minute_level",
        "decision": overall_decision(candidates),
        "requires_manual_confirmation": has_ready_manual_confirmation(candidates),
        "summary": {
            **ports.decision_summary(
                state,
                actions=actions,
                candidates=candidates,
                journal_by_signal=journal_by_signal,
                account_truth=account_truth,
                strategy_attribution=strategy_attribution,
                portfolio_context=portfolio_context,
            ),
            "excluded_daily_count": len(daily_actions),
        },
        "candidates": candidates,
        "excluded_daily_symbols": [
            str(action.get("symbol")) for action in daily_actions
        ],
        "no_action_reasons": no_action_reasons,
        "limitations": [
            "Intraday decisions are polling/minute-level platform candidates, not high-frequency trading instructions.",
            "Decision platform output is research and portfolio evidence, not investment advice.",
            "Live-like execution remains manual-confirmation only by default.",
        ],
    }


async def build_today_decision_payload(
    state: Any,
    *,
    ports: DecisionProjectionPorts,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = state.db
    resolved_portfolio_context = portfolio_context or ports.portfolio_context(state)
    actions = ports.allocate_actions(
        state,
        resolved_portfolio_context,
        ports.read_action_tasks(
            db,
            decision_date=action_filter_date(resolved_portfolio_context),
        ),
    )
    decision_date = response_decision_date(resolved_portfolio_context, actions)
    journal_by_signal = ports.journal_by_signal_id(db)
    validation_by_strategy = await ports.validation_by_strategy_id(db)
    account_truth = ports.account_truth_evidence(state)
    strategy_attribution = ports.strategy_attribution_evidence(
        state,
        db,
        actions,
    )
    candidates = [
        ports.decision_candidate(
            action,
            journal_by_signal,
            validation_by_strategy,
            db,
            account_truth,
            strategy_attribution,
            state=state,
            quotes=dict(resolved_portfolio_context.get("quotes") or {}),
            allow_direct_quote_fallback=(
                resolved_portfolio_context.get("authority")
                != "persisted_valuation_snapshot"
            ),
        )
        for action in actions
    ]
    no_action_reasons = [] if candidates else ["no_pending_action_tasks"]
    return {
        "lane": "daily",
        "decision_date": decision_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": overall_decision(candidates),
        "requires_manual_confirmation": has_ready_manual_confirmation(candidates),
        "summary": ports.decision_summary(
            state,
            actions=actions,
            candidates=candidates,
            journal_by_signal=journal_by_signal,
            account_truth=account_truth,
            strategy_attribution=strategy_attribution,
            portfolio_context=resolved_portfolio_context,
        ),
        "candidates": candidates,
        "no_action_reasons": no_action_reasons,
        "limitations": [
            "Decision platform output is research and portfolio evidence, not investment advice.",
            "Live-like execution remains manual-confirmation only by default.",
        ],
    }
