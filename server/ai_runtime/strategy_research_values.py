"""Runtime identifiers and immutable limits for AI strategy research."""

from __future__ import annotations

from server.ai_runtime.contracts import JsonObject, WorkflowStatus
from server.ai_runtime.openai_compatibility import edge_request_options
from server.ai_runtime.provider_call_window import is_deepseek_provider_endpoint
from server.ai_runtime.provider_connectivity_contracts import (
    ProviderConnectivitySettings,
)
from server.ai_runtime.reasoning_roi import strategy_research_reasoning_policy
from server.contracts.strategy_research import (
    SANITIZED_ACCOUNT_EVIDENCE_CONTRACT,
    STRATEGY_RESEARCH_MAX_CANDIDATES,
    STRATEGY_RESEARCH_MAX_CITATION_CATALOG_BYTES,
    STRATEGY_RESEARCH_MAX_CITATION_PATHS,
    STRATEGY_RESEARCH_MAX_INPUT_BYTES,
    STRATEGY_RESEARCH_MAX_OUTPUT_TOKENS,
    STRATEGY_RESEARCH_MAX_PROVIDER_CALLS,
    STRATEGY_RESEARCH_PROMPT_VERSION,
    STRATEGY_RESEARCH_PROVIDER_TOKEN_RESERVATION,
)

RESEARCH_TOOL = "research_evidence.read"
ACCOUNT_STATE_TOOL = "account_state_projection.read"
CATALOG_TOOL = "formula_operator_catalog.read"
SELECTION_TOOL = "strategy_research_selection.read"
HYPOTHESIS_ROLE = "external.strategy_hypothesis_researcher.v13"
CRITIQUE_ROLE = "external.strategy_backtest_critic.v13"
HYPOTHESIS_STAGE = "strategy_hypothesis_generation"
CRITIQUE_STAGE = "strategy_backtest_critique"


def strategy_research_request_options(
    settings: ProviderConnectivitySettings,
) -> JsonObject:
    """Reserve the response budget for the bounded final JSON contract."""
    if is_deepseek_provider_endpoint(
        settings.provider_id,
        settings.endpoint_origin,
    ):
        return strategy_research_reasoning_policy()
    return edge_request_options(settings)


CRITIQUE_CITATION_PATHS = (
    "critique_input.canonical_backtest.performance_summary.total_return",
    "critique_input.canonical_backtest.performance_summary.annual_return",
    "critique_input.canonical_backtest.performance_summary.sharpe",
    "critique_input.canonical_backtest.performance_summary.sortino",
    "critique_input.canonical_backtest.performance_summary.max_drawdown",
    "critique_input.canonical_backtest.performance_summary.win_rate",
    "critique_input.canonical_backtest.performance_summary.duration_days",
    "critique_input.canonical_backtest.after_cost_evidence.net_return_after_costs",
    "critique_input.canonical_backtest.after_cost_evidence.gross_return_before_costs",
    "critique_input.canonical_backtest.after_cost_evidence.total_cost_bps",
    "critique_input.canonical_backtest.cost_summary.total_commission_bps",
    "critique_input.canonical_backtest.cost_summary.total_slippage_bps",
    "critique_input.canonical_backtest.cost_summary.total_cost_bps",
    "critique_input.canonical_backtest.cost_summary.total_trades",
    "critique_input.canonical_backtest.cost_summary.gross_turnover_ratio",
    "critique_input.canonical_backtest.after_cost_evidence",
    "critique_input.canonical_backtest.cost_summary",
    "critique_input.canonical_backtest.oos_validation.validation_mode",
    "critique_input.canonical_backtest.oos_validation.validation_status",
    "critique_input.canonical_backtest.oos_validation.fold_count",
    "critique_input.canonical_backtest.oos_validation.mean_out_of_sample_return",
    "critique_input.canonical_backtest.oos_validation.worst_out_of_sample_return",
    "critique_input.canonical_backtest.research_evidence_bundle.gate_status",
    "critique_input.canonical_backtest.research_evidence_bundle.analyzers",
    "critique_input.canonical_backtest.research_evidence_bundle.evidence_references",
    "critique_input.canonical_backtest.research_evidence_bundle.promotion_gate",
    "critique_input.canonical_backtest.signal_execution_evidence",
    "critique_input.canonical_backtest.lot_feasibility_evidence",
    "critique_input.hypothesis_draft.economic_hypothesis",
    "critique_input.hypothesis_draft.failure_conditions",
    "critique_input.hypothesis_draft.limitations",
    "critique_input.hypothesis_draft.sample_split_plan",
    "critique_input.hypothesis_draft.parameter_values",
    "critique_input.hypothesis_draft.portfolio_constraints",
    "critique_input.formula_fingerprint",
    "critique_input.dataset_snapshot_id",
    "critique_input.cost_model_reference",
)
TERMINAL_WORKFLOW_STATUSES = {
    WorkflowStatus.COMPLETED,
    WorkflowStatus.PARTIAL,
    WorkflowStatus.FAILED,
    WorkflowStatus.BLOCKED,
}
