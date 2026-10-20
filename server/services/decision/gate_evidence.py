"""Gate evidence composition covering account truth, freshness, and paper shadow.

Canonical module in server.services.decision.
"""

from __future__ import annotations

from server.services.decision.decision_gate_evidence import (
    account_truth_gate_evidence,
    data_freshness_evidence,
    first_action_strategy_id,
    paper_shadow_allows_manual_ticket,
    paper_shadow_evidence,
    strategy_attribution_gate_evidence,
)

__all__ = [
    "account_truth_gate_evidence",
    "data_freshness_evidence",
    "first_action_strategy_id",
    "paper_shadow_allows_manual_ticket",
    "paper_shadow_evidence",
    "strategy_attribution_gate_evidence",
]
