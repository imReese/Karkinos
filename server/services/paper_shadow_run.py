"""Daily paper/shadow run service built from trading-plan order intents."""

from __future__ import annotations

from typing import Any

from execution.paper_broker import PaperBroker
from server.services.paper_shadow_contracts import (
    PAPER_SHADOW_EXECUTION_MODE,
    PAPER_SHADOW_INPUT_SNAPSHOT_SCHEMA_VERSION,
    PAPER_SHADOW_RUN_SCHEMA_VERSION,
    PAPER_SHADOW_SOURCE,
)
from server.services.paper_shadow_execution import (
    matching_latest_run as _matching_latest_run,
)
from server.services.paper_shadow_execution import (
    paper_order_request as _paper_order_request,
)
from server.services.paper_shadow_execution import (
    record_shadow_failed_order as _record_shadow_failed_order,
)
from server.services.paper_shadow_execution import (
    record_shadow_fill as _record_shadow_fill,
)
from server.services.paper_shadow_execution import (
    record_shadow_order as _record_shadow_order,
)
from server.services.paper_shadow_execution import simulate_outcome as _simulate_outcome
from server.services.paper_shadow_review import divergence_status as _divergence_status
from server.services.paper_shadow_review import (
    divergence_summary as _divergence_summary,
)
from server.services.paper_shadow_review import review_queue as _review_queue
from server.services.paper_shadow_review import run_evidence_refs as _run_evidence_refs
from server.services.paper_shadow_review import run_status as _run_status
from server.services.paper_shadow_values import dict_value as _dict
from server.services.paper_shadow_values import input_fingerprint as _input_fingerprint
from server.services.paper_shadow_values import input_refs as _input_refs
from server.services.paper_shadow_values import input_snapshot as _input_snapshot
from server.services.paper_shadow_values import (
    normalized_outcome_overrides as _normalized_outcome_overrides,
)
from server.services.paper_shadow_values import order_intent_ref as _order_intent_ref
from server.services.paper_shadow_values import (
    order_intent_snapshot as _order_intent_snapshot,
)
from server.services.paper_shadow_values import order_intents as _order_intents
from server.services.paper_shadow_values import (
    outcome_for_intent as _outcome_for_intent,
)
from server.services.paper_shadow_values import plan_date as _plan_date
from server.services.paper_shadow_values import (
    stable_order_intent_input as _stable_order_intent_input,
)
from server.services.paper_shadow_values import timestamp as _timestamp


def run_paper_shadow_from_trading_plan(
    *,
    db: Any,
    trading_plan: dict[str, Any],
    generated_at: str | None = None,
    outcome_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create or reuse a deterministic paper/shadow run from order intents."""
    plan_date = _plan_date(trading_plan, generated_at)
    order_intents = _order_intents(trading_plan)
    overrides = outcome_overrides or {}
    normalized_outcome_overrides = _normalized_outcome_overrides(overrides)
    fingerprint = _input_fingerprint(
        {
            "schema_version": PAPER_SHADOW_RUN_SCHEMA_VERSION,
            "plan_date": plan_date,
            "trading_plan_schema_version": trading_plan.get("schema_version"),
            "order_intents": [
                _stable_order_intent_input(intent) for intent in order_intents
            ],
            "account_truth": _dict(trading_plan.get("account_truth")),
            "outcome_overrides": normalized_outcome_overrides,
        }
    )
    reusable = _matching_latest_run(
        db,
        plan_date=plan_date,
        input_fingerprint=fingerprint,
    )
    if reusable is not None:
        return reusable
    run_id = f"shadow:{plan_date}:{fingerprint[:12]}"
    input_refs = _input_refs(
        trading_plan=trading_plan,
        plan_date=plan_date,
        input_fingerprint=fingerprint,
    )
    input_snapshot = _input_snapshot(
        trading_plan=trading_plan,
        plan_date=plan_date,
        input_fingerprint=fingerprint,
        input_refs=input_refs,
        order_intents=order_intents,
        outcome_overrides=normalized_outcome_overrides,
    )
    timestamp = _timestamp(generated_at or trading_plan.get("generated_at"))
    broker = PaperBroker(
        db=None,
        provider_name="paper-shadow-sim",
        source=PAPER_SHADOW_SOURCE,
    )

    limitations: list[str] = []
    order_summaries: list[dict[str, Any]] = []
    fill_summaries: list[dict[str, Any]] = []

    for index, intent in enumerate(order_intents, start=1):
        request, intent_limitations = _paper_order_request(
            intent,
            plan_date=plan_date,
            fingerprint=fingerprint,
            index=index,
            timestamp=timestamp,
        )
        limitations.extend(intent_limitations)
        if request is None:
            continue

        outcome = _outcome_for_intent(intent, overrides)
        intent_ref = _order_intent_ref(intent, index)
        try:
            result = _simulate_outcome(
                broker=broker,
                request=request,
                outcome=outcome,
            )
        except Exception as exc:
            limitation = (
                f"{intent_ref} paper/shadow simulation failed: "
                f"{type(exc).__name__}: {exc}"
            )
            limitations.append(limitation)
            oms_transitions = _record_shadow_failed_order(
                db,
                request,
                run_id=run_id,
                plan_date=plan_date,
                input_fingerprint=fingerprint,
                intent_ref=intent_ref,
                intent=intent,
                error=exc,
            )
            order_summaries.append(
                {
                    "order_id": request.order_id,
                    "symbol": str(request.symbol),
                    "status": "failed",
                    "divergence_status": "failed",
                    "quantity": str(request.quantity),
                    "price": str(request.price) if request.price is not None else None,
                    "filled_quantity": "0",
                    "remaining_quantity": str(request.quantity),
                    "order_intent": _order_intent_snapshot(intent, intent_ref),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "oms_transitions": oms_transitions,
                }
            )
            continue
        divergence_status = _divergence_status(result)
        order_payload = result.order.to_payload()
        _record_shadow_order(
            db,
            result.order,
            run_id=run_id,
            plan_date=plan_date,
            input_fingerprint=fingerprint,
            intent_ref=intent_ref,
            intent=intent,
            divergence_status=divergence_status,
        )
        order_summaries.append(
            {
                "order_id": result.order.order_id,
                "symbol": str(result.order.symbol),
                "status": result.order.status.value,
                "divergence_status": divergence_status,
                "quantity": order_payload["quantity"],
                "price": order_payload["price"],
                "filled_quantity": order_payload["filled_quantity"],
                "remaining_quantity": order_payload["remaining_quantity"],
                "oms_transitions": order_payload["oms_transitions"],
                "order_intent": _order_intent_snapshot(intent, intent_ref),
            }
        )
        if result.fill is not None:
            _record_shadow_fill(
                db,
                result.fill,
                run_id=run_id,
                plan_date=plan_date,
                input_fingerprint=fingerprint,
                intent_ref=intent_ref,
                intent=intent,
            )
            fill_payload = result.fill.to_payload()
            fill_summaries.append(
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

    status, divergence_status, next_step = _run_status(
        order_intent_count=len(order_intents),
        simulated_order_count=len(order_summaries),
        order_summaries=order_summaries,
        limitations=limitations,
    )
    divergence_summary = _divergence_summary(
        trading_plan=trading_plan,
        order_intents=order_intents,
        order_summaries=order_summaries,
        fill_summaries=fill_summaries,
        divergence_status=divergence_status,
        next_manual_review_step=next_step,
    )
    evidence_refs = _run_evidence_refs(
        order_intents=order_intents,
        order_summaries=order_summaries,
        fill_summaries=fill_summaries,
    )
    review_queue = _review_queue(
        run_id=run_id,
        trading_plan=trading_plan,
        order_intents=order_intents,
        order_summaries=order_summaries,
        fill_summaries=fill_summaries,
        limitations=limitations,
    )
    payload = {
        "schema_version": PAPER_SHADOW_RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "plan_date": plan_date,
        "input_fingerprint": fingerprint,
        "input_refs": input_refs,
        "input_snapshot": input_snapshot,
        "generated_at": timestamp.isoformat(),
        "outcome_overrides": normalized_outcome_overrides,
        "evidence_refs": evidence_refs,
        "orders": order_summaries,
        "fills": fill_summaries,
        "review_queue": review_queue,
        "divergence_summary": divergence_summary,
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }
    saved = db.upsert_paper_shadow_run_sync(
        run_id=run_id,
        plan_date=plan_date,
        input_fingerprint=fingerprint,
        status=status,
        order_intent_count=len(order_intents),
        simulated_order_count=len(order_summaries),
        simulated_fill_count=len(fill_summaries),
        divergence_status=divergence_status,
        next_manual_review_step=next_step,
        limitations=limitations,
        payload=payload,
    )
    return {
        **saved,
        "input_fingerprint": fingerprint,
        "input_refs": input_refs,
        "input_snapshot": input_snapshot,
        "status": status,
        "order_intent_count": len(order_intents),
        "simulated_order_count": len(order_summaries),
        "simulated_fill_count": len(fill_summaries),
        "divergence_status": divergence_status,
        "next_manual_review_step": next_step,
        "limitations": limitations,
        "evidence_refs": evidence_refs,
        "orders": order_summaries,
        "fills": fill_summaries,
        "review_queue": review_queue,
        "divergence_summary": divergence_summary,
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }
