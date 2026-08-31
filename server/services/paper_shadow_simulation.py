"""Pure in-memory order simulation for one paper-shadow run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from execution.paper_broker import PaperBroker
from server.contracts.paper_shadow import PaperShadowFillFact, PaperShadowOrderFact
from server.services.paper_shadow_contracts import PAPER_SHADOW_SOURCE
from server.services.paper_shadow_execution import (
    build_shadow_failed_order,
    build_shadow_fill,
    build_shadow_order,
    paper_order_request,
    simulate_outcome,
)
from server.services.paper_shadow_review import divergence_status
from server.services.paper_shadow_values import (
    order_intent_ref,
    order_intent_snapshot,
    outcome_for_intent,
)


@dataclass(slots=True)
class PaperShadowSimulation:
    """All facts produced in memory before the atomic persistence boundary."""

    limitations: list[str] = field(default_factory=list)
    order_summaries: list[dict[str, Any]] = field(default_factory=list)
    fill_summaries: list[dict[str, Any]] = field(default_factory=list)
    order_facts: list[PaperShadowOrderFact] = field(default_factory=list)
    fill_facts: list[PaperShadowFillFact] = field(default_factory=list)


def simulate_paper_shadow_orders(
    *,
    order_intents: list[dict[str, Any]],
    outcome_overrides: dict[str, dict[str, Any]],
    plan_date: str,
    input_fingerprint: str,
    run_id: str,
    timestamp: datetime,
) -> PaperShadowSimulation:
    """Simulate every valid intent without performing persistence writes."""

    simulation = PaperShadowSimulation()
    broker = PaperBroker(
        db=None,
        provider_name="paper-shadow-sim",
        source=PAPER_SHADOW_SOURCE,
    )
    for index, intent in enumerate(order_intents, start=1):
        request, intent_limitations = paper_order_request(
            intent,
            plan_date=plan_date,
            fingerprint=input_fingerprint,
            index=index,
            timestamp=timestamp,
        )
        simulation.limitations.extend(intent_limitations)
        if request is None:
            continue
        intent_ref = order_intent_ref(intent, index)
        try:
            result = simulate_outcome(
                broker=broker,
                request=request,
                outcome=outcome_for_intent(intent, outcome_overrides),
            )
        except Exception as exc:
            simulation.limitations.append(
                f"{intent_ref} paper/shadow simulation failed: "
                f"{type(exc).__name__}: {exc}"
            )
            order_fact, oms_transitions = build_shadow_failed_order(
                request,
                run_id=run_id,
                plan_date=plan_date,
                input_fingerprint=input_fingerprint,
                intent_ref=intent_ref,
                intent=intent,
                error=exc,
            )
            simulation.order_facts.append(order_fact)
            simulation.order_summaries.append(
                {
                    "order_id": request.order_id,
                    "symbol": str(request.symbol),
                    "status": "failed",
                    "divergence_status": "failed",
                    "quantity": str(request.quantity),
                    "price": str(request.price) if request.price is not None else None,
                    "filled_quantity": "0",
                    "remaining_quantity": str(request.quantity),
                    "order_intent": order_intent_snapshot(intent, intent_ref),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "oms_transitions": oms_transitions,
                }
            )
            continue
        _append_successful_simulation(
            simulation,
            result=result,
            run_id=run_id,
            plan_date=plan_date,
            input_fingerprint=input_fingerprint,
            intent_ref=intent_ref,
            intent=intent,
        )
    return simulation


def _append_successful_simulation(
    simulation: PaperShadowSimulation,
    *,
    result: Any,
    run_id: str,
    plan_date: str,
    input_fingerprint: str,
    intent_ref: str,
    intent: dict[str, Any],
) -> None:
    status = divergence_status(result)
    order_payload = result.order.to_payload()
    simulation.order_facts.append(
        build_shadow_order(
            result.order,
            run_id=run_id,
            plan_date=plan_date,
            input_fingerprint=input_fingerprint,
            intent_ref=intent_ref,
            intent=intent,
            divergence_status=status,
        )
    )
    simulation.order_summaries.append(
        {
            "order_id": result.order.order_id,
            "symbol": str(result.order.symbol),
            "status": result.order.status.value,
            "divergence_status": status,
            "quantity": order_payload["quantity"],
            "price": order_payload["price"],
            "filled_quantity": order_payload["filled_quantity"],
            "remaining_quantity": order_payload["remaining_quantity"],
            "oms_transitions": order_payload["oms_transitions"],
            "order_intent": order_intent_snapshot(intent, intent_ref),
        }
    )
    if result.fill is None:
        return
    simulation.fill_facts.append(
        build_shadow_fill(
            result.fill,
            run_id=run_id,
            plan_date=plan_date,
            input_fingerprint=input_fingerprint,
            intent_ref=intent_ref,
            intent=intent,
        )
    )
    fill_payload = result.fill.to_payload()
    simulation.fill_summaries.append(
        {
            "fill_id": result.fill.fill_id,
            "order_id": result.fill.order_id,
            "symbol": str(result.fill.symbol),
            "fill_quantity": str(result.fill.fill_quantity),
            "fill_price": str(result.fill.fill_price),
            "commission": fill_payload["commission"],
            "slippage": fill_payload["slippage"],
            "cost_modeling": fill_payload["cost_modeling"],
            "fee_breakdown": fill_payload["fee_breakdown"],
        }
    )


__all__ = ["PaperShadowSimulation", "simulate_paper_shadow_orders"]
