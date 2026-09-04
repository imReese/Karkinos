"""Top-level daily and intraday Decision response projection."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from server.services.decision_candidate_market_evidence import (
    bind_candidate_market_evidence,
    candidate_market_evidence,
)
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


def _prepare_decision_projection(
    state: Any,
    ports: DecisionProjectionPorts,
    portfolio_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Read the first canonical persisted-fact stage in one worker thread."""

    db = state.db
    resolved_portfolio_context = portfolio_context or ports.portfolio_context(state)
    raw_actions = ports.read_action_tasks(
        db,
        decision_date=action_filter_date(resolved_portfolio_context),
    )
    if resolved_portfolio_context.get("authority") == "persisted_valuation_snapshot":
        resolved_portfolio_context = bind_candidate_market_evidence(
            resolved_portfolio_context,
            candidate_market_evidence(db, raw_actions, state=state),
        )
    actions = ports.allocate_actions(
        state,
        resolved_portfolio_context,
        raw_actions,
    )
    return {
        "db": db,
        "portfolio_context": resolved_portfolio_context,
        "actions": actions,
        "decision_date": response_decision_date(
            resolved_portfolio_context,
            actions,
        ),
        "journal_by_signal": ports.journal_by_signal_id(db),
    }


def _decision_evidence(
    state: Any,
    ports: DecisionProjectionPorts,
    prepared: dict[str, Any],
    validation_by_strategy: dict[str, dict[str, Any]],
    candidate_actions: list[dict[str, Any]],
    *,
    attribution_actions: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Compose evidence-bound candidates in one worker-thread stage."""

    db = prepared["db"]
    portfolio_context = prepared["portfolio_context"]
    journal_by_signal = prepared["journal_by_signal"]
    account_truth = ports.account_truth_evidence(state)
    strategy_attribution = ports.strategy_attribution_evidence(
        state,
        db,
        candidate_actions if attribution_actions is None else attribution_actions,
    )
    candidate_quotes = dict(
        portfolio_context.get("candidate_quotes")
        if portfolio_context.get("authority") == "persisted_valuation_snapshot"
        else portfolio_context.get("quotes") or {}
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
            quotes=candidate_quotes,
            allow_direct_quote_fallback=(
                portfolio_context.get("authority") != "persisted_valuation_snapshot"
            ),
        )
        for action in candidate_actions
    ]
    return account_truth, strategy_attribution, candidates


def _finish_intraday_decision_projection(
    state: Any,
    ports: DecisionProjectionPorts,
    prepared: dict[str, Any],
    validation_by_strategy: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    actions = prepared["actions"]
    intraday_actions = [action for action in actions if is_intraday_action(action)]
    daily_actions = [action for action in actions if not is_intraday_action(action)]
    account_truth, strategy_attribution, candidates = _decision_evidence(
        state,
        ports,
        prepared,
        validation_by_strategy,
        intraday_actions,
        attribution_actions=actions,
    )
    no_action_reasons = [] if candidates else ["no_intraday_stock_or_etf_action_tasks"]
    return {
        "lane": "intraday",
        "decision_date": prepared["decision_date"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cadence": "polling_or_minute_level",
        "decision": overall_decision(candidates),
        "requires_manual_confirmation": has_ready_manual_confirmation(candidates),
        "summary": {
            **ports.decision_summary(
                state,
                actions=actions,
                candidates=candidates,
                journal_by_signal=prepared["journal_by_signal"],
                account_truth=account_truth,
                strategy_attribution=strategy_attribution,
                portfolio_context=prepared["portfolio_context"],
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


def _finish_today_decision_projection(
    state: Any,
    ports: DecisionProjectionPorts,
    prepared: dict[str, Any],
    validation_by_strategy: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    actions = prepared["actions"]
    account_truth, strategy_attribution, candidates = _decision_evidence(
        state,
        ports,
        prepared,
        validation_by_strategy,
        actions,
    )
    no_action_reasons = [] if candidates else ["no_pending_action_tasks"]
    return {
        "lane": "daily",
        "decision_date": prepared["decision_date"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": overall_decision(candidates),
        "requires_manual_confirmation": has_ready_manual_confirmation(candidates),
        "summary": ports.decision_summary(
            state,
            actions=actions,
            candidates=candidates,
            journal_by_signal=prepared["journal_by_signal"],
            account_truth=account_truth,
            strategy_attribution=strategy_attribution,
            portfolio_context=prepared["portfolio_context"],
        ),
        "candidates": candidates,
        "no_action_reasons": no_action_reasons,
        "limitations": [
            "Decision platform output is research and portfolio evidence, not investment advice.",
            "Live-like execution remains manual-confirmation only by default.",
        ],
    }


async def build_intraday_decision_payload(
    state: Any,
    *,
    ports: DecisionProjectionPorts,
) -> dict[str, Any]:
    """Build the canonical intraday Decision projection."""

    prepared = await asyncio.to_thread(
        _prepare_decision_projection,
        state,
        ports,
        None,
    )
    validation_by_strategy = await ports.validation_by_strategy_id(prepared["db"])
    return await asyncio.to_thread(
        _finish_intraday_decision_projection,
        state,
        ports,
        prepared,
        validation_by_strategy,
    )


async def build_today_decision_payload(
    state: Any,
    *,
    ports: DecisionProjectionPorts,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prepared = await asyncio.to_thread(
        _prepare_decision_projection,
        state,
        ports,
        portfolio_context,
    )
    validation_by_strategy = await ports.validation_by_strategy_id(prepared["db"])
    return await asyncio.to_thread(
        _finish_today_decision_projection,
        state,
        ports,
        prepared,
        validation_by_strategy,
    )
