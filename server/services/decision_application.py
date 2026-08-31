"""Stable facade for canonical Decision application and projection flows."""

from __future__ import annotations

from typing import Any

from server.services import decision_action_application as action_application
from server.services import decision_candidate_projection as candidate_projection
from server.services import decision_contracts as contracts
from server.services import decision_gate_evidence as gate_evidence
from server.services import decision_portfolio_projection as portfolio_projection
from server.services import decision_projection
from server.services import decision_workflow_projection as workflow_projection
from server.services.strategy_promotion_pipeline import (
    resolve_strategy_order_generation_gate,
)

# Stable private compatibility names are intentionally retained because route and
# integration tests patch these seams. Split modules never import this facade.
_ACCOUNT_STRATEGY_CONTROL_KEY = contracts.ACCOUNT_STRATEGY_CONTROL_KEY
_STRATEGY_ATTRIBUTION_READY_STATUSES = contracts.STRATEGY_ATTRIBUTION_READY_STATUSES
_READY_MANUAL_CONFIRMATION_STATUS = contracts.READY_MANUAL_CONFIRMATION_STATUS
_TRUSTED_DATA_STATUSES = contracts.TRUSTED_DATA_STATUSES
_REVIEW_DATA_STATUSES = contracts.REVIEW_DATA_STATUSES
_BLOCKING_DATA_STATUSES = contracts.BLOCKING_DATA_STATUSES
_SHANGHAI_TZ = contracts.SHANGHAI_TZ

_read_action_tasks = action_application.read_action_tasks
_action_sort_key = contracts.action_sort_key
_allocate_decision_actions = action_application.allocate_decision_actions
_blocked_batch_pre_trade_risk_response = (
    action_application.blocked_batch_pre_trade_risk_response
)

_decision_portfolio_context = portfolio_projection.decision_portfolio_context
_decision_date_from_context = portfolio_projection.decision_date_from_context
_action_filter_date = portfolio_projection.action_filter_date
_response_decision_date = portfolio_projection.response_decision_date
_action_trade_date = contracts.action_trade_date
_parse_action_timestamp = contracts.parse_action_timestamp
_journal_by_signal_id = portfolio_projection.journal_by_signal_id
_portfolio_state_summary = portfolio_projection.portfolio_state_summary
_portfolio_total_equity = portfolio_projection.portfolio_total_equity
_position_market_value = portfolio_projection.position_market_value
_float_or_zero = contracts.float_or_zero
_market_data_summary = portfolio_projection.market_data_summary
_decision_symbols = portfolio_projection.decision_symbols
_append_unique_symbol = portfolio_projection.append_unique_symbol
_collect_decision_quotes = portfolio_projection.collect_decision_quotes
_normalize_quote = portfolio_projection.normalize_quote
_latest_quote_timestamp = portfolio_projection.latest_quote_timestamp
_has_persistent_quote_cache = portfolio_projection.has_persistent_quote_cache

_decision_summary = workflow_projection.decision_summary
_action_task_summary = workflow_projection.action_task_summary
_audit_summary = workflow_projection.audit_summary
_workflow_tasks = workflow_projection.workflow_tasks
_data_refresh_workflow_task = workflow_projection.data_refresh_workflow_task
_account_truth_workflow_task = workflow_projection.account_truth_workflow_task
_risk_review_workflow_task = workflow_projection.risk_review_workflow_task
_strategy_evidence_workflow_task = workflow_projection.strategy_evidence_workflow_task
_paper_shadow_workflow_task = workflow_projection.paper_shadow_workflow_task
_manual_confirmation_workflow_task = (
    workflow_projection.manual_confirmation_workflow_task
)
_workflow_task = workflow_projection.workflow_task

_validation_by_strategy_id = candidate_projection.validation_by_strategy_id
_normalize_decision_action = contracts.normalize_decision_action
_is_intraday_action = contracts.is_intraday_action
_looks_exchange_traded_fund_symbol = contracts.looks_exchange_traded_fund_symbol
_overall_decision = contracts.overall_decision
_has_ready_manual_confirmation = contracts.has_ready_manual_confirmation
_signal_evidence = candidate_projection.signal_evidence
_risk_gate_evidence = candidate_projection.risk_gate_evidence
_after_cost_oos_validation_evidence = (
    candidate_projection.after_cost_oos_validation_evidence
)
_manual_confirmation_evidence = candidate_projection.manual_confirmation_evidence
_cost_impact_evidence = candidate_projection.cost_impact_evidence
_uncertainty_evidence = candidate_projection.uncertainty_evidence
_append_unique_text = contracts.append_unique_text
_float_or_none = contracts.float_or_none
_journal_evidence = candidate_projection.journal_evidence
_backtest_strategy_id = candidate_projection.backtest_strategy_id
_backtest_validation_row = candidate_projection.backtest_validation_row
_validation_limitations = candidate_projection.validation_limitations
_json_object = contracts.json_object
_int_or_none = contracts.int_or_none

_account_truth_gate_evidence = gate_evidence.account_truth_gate_evidence
_strategy_attribution_gate_evidence = gate_evidence.strategy_attribution_gate_evidence
_first_action_strategy_id = gate_evidence.first_action_strategy_id
_account_truth_manual_confirmation_status = (
    contracts.account_truth_manual_confirmation_status
)
_data_freshness_evidence = gate_evidence.data_freshness_evidence
_data_quality_manual_confirmation_status = (
    contracts.data_quality_manual_confirmation_status
)
_paper_shadow_evidence = gate_evidence.paper_shadow_evidence
_paper_shadow_allows_manual_ticket = gate_evidence.paper_shadow_allows_manual_ticket


def _projection_ports() -> contracts.DecisionProjectionPorts:
    """Capture facade seams at call time so monkeypatches remain effective."""

    return contracts.DecisionProjectionPorts(
        portfolio_context=_decision_portfolio_context,
        read_action_tasks=_read_action_tasks,
        allocate_actions=_allocate_decision_actions,
        journal_by_signal_id=_journal_by_signal_id,
        validation_by_strategy_id=_validation_by_strategy_id,
        account_truth_evidence=_account_truth_gate_evidence,
        strategy_attribution_evidence=_strategy_attribution_gate_evidence,
        decision_candidate=_decision_candidate,
        decision_summary=_decision_summary,
    )


async def run_batch_pre_trade_risk_for_state(state: Any) -> dict[str, Any]:
    """Run the canonical persisted-evidence batch risk gate for one app state."""

    return await action_application.run_batch_pre_trade_risk(
        state,
        portfolio_context_resolver=_decision_portfolio_context,
        read_action_tasks_resolver=_read_action_tasks,
        action_filter_date_resolver=_action_filter_date,
        evidence_gate_resolver=_batch_pre_trade_risk_evidence_gate,
        blocked_response_resolver=_blocked_batch_pre_trade_risk_response,
        allocate_actions_resolver=_allocate_decision_actions,
    )


async def intraday_decision_payload(state: Any) -> dict[str, Any]:
    """Build the canonical intraday Decision projection."""

    return await decision_projection.build_intraday_decision_payload(
        state,
        ports=_projection_ports(),
    )


async def _today_decision_payload(
    state: Any,
    *,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await decision_projection.build_today_decision_payload(
        state,
        ports=_projection_ports(),
        portfolio_context=portfolio_context,
    )


def _trading_plan_positions(
    state: Any,
    *,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return action_application.trading_plan_positions(
        state,
        portfolio_context=portfolio_context,
        portfolio_context_resolver=_decision_portfolio_context,
    )


def _batch_pre_trade_risk_evidence_gate(
    db: Any,
    *,
    portfolio_context: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    return action_application.batch_pre_trade_risk_evidence_gate(
        db,
        portfolio_context=portfolio_context,
        tasks=tasks,
        data_freshness_resolver=_data_freshness_evidence,
    )


def _decision_candidate(
    action: dict[str, Any],
    journal_by_signal: dict[int, dict[str, Any]],
    validation_by_strategy: dict[str, dict[str, Any]],
    db: Any,
    account_truth: dict[str, Any],
    strategy_attribution: dict[str, Any],
    *,
    state: Any,
    quotes: dict[str, dict[str, Any]],
    allow_direct_quote_fallback: bool,
) -> dict[str, Any]:
    return candidate_projection.decision_candidate(
        action,
        journal_by_signal,
        validation_by_strategy,
        db,
        account_truth,
        strategy_attribution,
        state=state,
        quotes=quotes,
        allow_direct_quote_fallback=allow_direct_quote_fallback,
        data_freshness_resolver=_data_freshness_evidence,
        strategy_order_gate_resolver=resolve_strategy_order_generation_gate,
        paper_shadow_resolver=_paper_shadow_evidence,
        paper_shadow_ticket_gate=_paper_shadow_allows_manual_ticket,
    )


def _certainty_evidence(
    *,
    data_freshness: dict[str, Any],
    account_truth: dict[str, Any],
    risk_gate: dict[str, Any],
    strategy_order_generation: dict[str, Any],
    paper_shadow: dict[str, Any],
) -> dict[str, Any]:
    return candidate_projection.certainty_evidence(
        data_freshness=data_freshness,
        account_truth=account_truth,
        risk_gate=risk_gate,
        strategy_order_generation=strategy_order_generation,
        paper_shadow=paper_shadow,
        paper_shadow_ticket_gate=_paper_shadow_allows_manual_ticket,
    )


async def today_decision_payload(
    state: Any,
    *,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility port for non-HTTP composition callers."""

    return await _today_decision_payload(
        state,
        portfolio_context=portfolio_context,
    )


def trading_plan_positions(
    state: Any,
    *,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility port for non-HTTP composition callers."""

    return _trading_plan_positions(state, portfolio_context=portfolio_context)


def decision_portfolio_context(state: Any) -> dict[str, Any]:
    """Compatibility port for non-HTTP composition callers."""

    return _decision_portfolio_context(state)


def account_truth_gate_evidence(state: Any) -> dict[str, Any]:
    """Compatibility port for non-HTTP composition callers."""

    return _account_truth_gate_evidence(state)


def action_trade_date(action: dict[str, Any]) -> str | None:
    """Compatibility port for non-HTTP composition callers."""

    return _action_trade_date(action)


def data_freshness_evidence(
    action: dict[str, Any],
    db: Any,
    *,
    quotes: dict[str, dict[str, Any]],
    allow_direct_quote_fallback: bool,
) -> dict[str, Any]:
    """Compatibility port for non-HTTP composition callers."""

    return _data_freshness_evidence(
        action,
        db,
        quotes=quotes,
        allow_direct_quote_fallback=allow_direct_quote_fallback,
    )


def paper_shadow_evidence(
    action: dict[str, Any],
    manual_confirmation_status: str,
    *,
    db: Any,
) -> dict[str, Any]:
    """Compatibility port for non-HTTP composition callers."""

    return _paper_shadow_evidence(
        action,
        manual_confirmation_status,
        db=db,
    )


def paper_shadow_allows_manual_ticket(evidence: dict[str, Any]) -> bool:
    """Compatibility port for non-HTTP composition callers."""

    return _paper_shadow_allows_manual_ticket(evidence)


def latest_quote_timestamp(quotes: Any) -> str | None:
    """Return the latest normalized timestamp across Decision quote evidence."""

    return _latest_quote_timestamp(quotes)


def strategy_attribution_gate_evidence(
    state: Any,
    db: Any,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Project the canonical strategy-attribution admission evidence."""

    return _strategy_attribution_gate_evidence(state, db, actions)
