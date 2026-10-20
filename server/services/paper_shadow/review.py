"""Paper shadow divergence analysis, execution comparison, and review evidence.

Canonical module in server.services.paper_shadow.
"""

from __future__ import annotations

from server.services.paper_shadow.paper_shadow_review import (
    constraint_status_counts,
    cost_summary,
    divergence_status,
    divergence_summary,
    execution_comparison,
    expected_strategy_behavior,
    fill_count_by_order,
    fills_by_order,
    realized_market_context,
    review_cost_evidence,
    review_evidence,
    review_market_context,
    review_oms_transition,
    review_oms_transition_evidence,
    review_ref_suffix,
    run_evidence_refs,
    run_status,
    terminal_order_review_evidence,
    value_counts,
)

__all__ = [
    "constraint_status_counts",
    "cost_summary",
    "divergence_status",
    "divergence_summary",
    "execution_comparison",
    "expected_strategy_behavior",
    "fill_count_by_order",
    "fills_by_order",
    "realized_market_context",
    "review_cost_evidence",
    "review_evidence",
    "review_market_context",
    "review_oms_transition",
    "review_oms_transition_evidence",
    "review_ref_suffix",
    "run_evidence_refs",
    "run_status",
    "terminal_order_review_evidence",
    "value_counts",
]
