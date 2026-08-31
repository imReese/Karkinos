"""Daily paper/shadow run service built from trading-plan order intents."""

from __future__ import annotations

from typing import Any

from server.contracts.paper_shadow import (
    PaperShadowRunCommand,
    PaperShadowRunPersistence,
)
from server.services.paper_shadow_contracts import (
    PAPER_SHADOW_RUN_SCHEMA_VERSION,
)
from server.services.paper_shadow_execution import (
    matching_latest_run as _matching_latest_run,
)
from server.services.paper_shadow_review import (
    divergence_summary as _divergence_summary,
)
from server.services.paper_shadow_review import run_evidence_refs as _run_evidence_refs
from server.services.paper_shadow_review import run_status as _run_status
from server.services.paper_shadow_review_queue import (
    build_paper_shadow_review_queue as _build_review_queue,
)
from server.services.paper_shadow_simulation import simulate_paper_shadow_orders
from server.services.paper_shadow_values import dict_value as _dict
from server.services.paper_shadow_values import input_fingerprint as _input_fingerprint
from server.services.paper_shadow_values import input_refs as _input_refs
from server.services.paper_shadow_values import input_snapshot as _input_snapshot
from server.services.paper_shadow_values import (
    normalized_outcome_overrides as _normalized_outcome_overrides,
)
from server.services.paper_shadow_values import order_intents as _order_intents
from server.services.paper_shadow_values import plan_date as _plan_date
from server.services.paper_shadow_values import (
    stable_order_intent_input as _stable_order_intent_input,
)
from server.services.paper_shadow_values import timestamp as _timestamp


def run_paper_shadow_from_trading_plan(
    *,
    db: PaperShadowRunPersistence,
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
    simulation = simulate_paper_shadow_orders(
        order_intents=order_intents,
        outcome_overrides=overrides,
        plan_date=plan_date,
        input_fingerprint=fingerprint,
        run_id=run_id,
        timestamp=timestamp,
    )
    limitations = simulation.limitations
    order_summaries = simulation.order_summaries
    fill_summaries = simulation.fill_summaries

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
    review_queue = _build_review_queue(
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
    saved = db.record_paper_shadow_run_sync(
        PaperShadowRunCommand(
            run_id=run_id,
            plan_date=plan_date,
            input_fingerprint=fingerprint,
            status=status,
            order_intent_count=len(order_intents),
            divergence_status=divergence_status,
            next_manual_review_step=next_step,
            limitations=tuple(limitations),
            payload=payload,
            orders=tuple(simulation.order_facts),
            fills=tuple(simulation.fill_facts),
        )
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
