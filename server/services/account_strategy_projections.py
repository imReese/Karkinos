"""Canonical read-only account-strategy projections."""

from __future__ import annotations

from typing import Any

from server.models import (
    AccountStrategyAssignment,
    AccountStrategyAttributionSummary,
    AccountStrategyContributionReport,
)
from server.services.account_strategy_assignment import (
    ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION,
)
from server.services.account_strategy_evidence import linked_strategy_evidence
from server.services.strategy_contribution import build_strategy_contribution_report

_PNL_PENDING_LIMITATION = (
    "P/L contribution is not calculated until fills are reconciled with position "
    "and valuation history."
)


def build_attribution_summary(
    db: Any,
    assignment: AccountStrategyAssignment,
) -> AccountStrategyAttributionSummary:
    """Project persisted signal, risk, order, and fill linkage for one strategy."""
    evidence = linked_strategy_evidence(db, assignment)
    strategy_entries = evidence["strategy_entries"]
    signal_ids = evidence["signal_ids"]
    risk_decisions = evidence["risk_decisions"]
    linked_orders = evidence["linked_orders"]
    linked_fills = evidence["linked_fills"]
    unattributed_fill_count = evidence["unattributed_fill_count"]

    total_fees = sum(
        float(fill.get("commission") or 0.0) + float(fill.get("slippage") or 0.0)
        for fill in linked_fills
    )
    action_refs = sorted(
        {
            f"action:{entry['action_task']['id']}"
            for entry in strategy_entries
            if entry.get("action_task") and entry["action_task"].get("id") is not None
        }
    )
    risk_refs = sorted(
        {
            f"risk:{risk['decision_id']}"
            for risk in risk_decisions
            if risk and risk.get("decision_id")
        }
    )
    review_refs = sorted(
        {
            f"review:{entry['review']['signal_id']}"
            for entry in strategy_entries
            if entry.get("review") and entry["review"].get("signal_id") is not None
        }
    )
    if linked_fills:
        status = "evidence_linked_pnl_pending"
        limitations = [_PNL_PENDING_LIMITATION]
    elif linked_orders:
        status = "orders_linked_no_fills"
        limitations = ["Orders are linked, but no fills are available for attribution."]
    elif strategy_entries:
        status = "signal_chain_pending"
        limitations = ["Signals exist, but order/fill evidence is not linked yet."]
    else:
        status = "not_started"
        limitations = [ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION]

    evidence_refs = [
        *(f"signal:{signal_id}" for signal_id in sorted(signal_ids)),
        *action_refs,
        *risk_refs,
        *review_refs,
        *(f"order:{order['order_id']}" for order in linked_orders),
        *(f"fill:{fill['fill_id']}" for fill in linked_fills),
    ]
    return AccountStrategyAttributionSummary(
        strategy_id=assignment.strategy_id,
        attribution_status=status,
        signal_count=len(strategy_entries),
        action_count=sum(1 for entry in strategy_entries if entry.get("action_task")),
        risk_decision_count=len(risk_decisions),
        order_count=len(linked_orders),
        fill_count=len(linked_fills),
        unattributed_fill_count=unattributed_fill_count,
        total_fees=round(total_fees, 6),
        attributed_pnl=None,
        realized_pnl=None,
        unrealized_pnl=None,
        evidence_refs=evidence_refs,
        limitations=limitations,
    )


def build_contribution_report(
    db: Any,
    assignment: AccountStrategyAssignment,
) -> AccountStrategyContributionReport:
    """Build the canonical persisted, evidence-bound strategy contribution."""
    evidence = linked_strategy_evidence(db, assignment)
    return build_strategy_contribution_report(
        db=db,
        assignment=assignment,
        evidence=evidence,
    )
