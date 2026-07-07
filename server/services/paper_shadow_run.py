"""Daily paper/shadow run service built from trading-plan order intents."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from core.types import AssetClass, OrderSide, OrderType, Symbol
from execution.paper_broker import (
    PAPER_BROKER_SCHEMA_VERSION,
    PaperBroker,
    PaperBrokerResult,
    PaperFillEvidence,
    PaperOmsStateMachine,
    PaperOrderContext,
    PaperOrderEvidence,
    PaperOrderRequest,
)
from server.services.oms import OmsService

PAPER_SHADOW_RUN_SCHEMA_VERSION = "karkinos.paper_shadow_run.v1"
PAPER_SHADOW_EXECUTION_MODE = "paper_shadow"
PAPER_SHADOW_SOURCE = "paper_shadow_daily"


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
            "order_intents": order_intents,
            "outcome_overrides": normalized_outcome_overrides,
        }
    )
    run_id = f"shadow:{plan_date}:{fingerprint[:12]}"
    input_refs = _input_refs(
        trading_plan=trading_plan,
        plan_date=plan_date,
        input_fingerprint=fingerprint,
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
            _record_shadow_failed_order(
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


def _paper_order_request(
    intent: dict[str, Any],
    *,
    plan_date: str,
    fingerprint: str,
    index: int,
    timestamp: datetime,
) -> tuple[PaperOrderRequest | None, list[str]]:
    limitations: list[str] = []
    symbol = str(intent.get("symbol") or "").strip()
    side = _side(intent.get("side"))
    quantity = _decimal(intent.get("estimated_quantity"))
    price = _decimal(intent.get("estimated_price"))
    if not symbol:
        limitations.append(f"order_intent[{index}] missing symbol")
    if side is None:
        limitations.append(f"order_intent[{index}] missing order side")
    if quantity is None or quantity <= Decimal("0"):
        limitations.append(f"order_intent[{index}] missing estimated_quantity")
    if price is None or price <= Decimal("0"):
        limitations.append(f"order_intent[{index}] missing estimated_price")
    if limitations:
        return None, limitations

    order_id = (
        f"SHADOW-{plan_date}-{index:03d}-{symbol}-{side.value}-{fingerprint[:10]}"
    )
    return (
        PaperOrderRequest(
            timestamp=timestamp,
            order_id=order_id,
            symbol=Symbol(symbol),
            side=side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=price,
            asset_class=_asset_class(intent.get("asset_class")),
            context=_paper_order_context(intent),
        ),
        [],
    )


def _simulate_outcome(
    *,
    broker: PaperBroker,
    request: PaperOrderRequest,
    outcome: dict[str, Any],
) -> PaperBrokerResult:
    outcome_kind = str(outcome.get("outcome") or "filled").lower()
    reason = str(outcome.get("reason") or "")
    if outcome_kind == "rejected":
        return broker.reject_order(request, reason=reason)
    if outcome_kind == "cancelled":
        return broker.cancel_order(request, reason=reason)
    if outcome_kind == "expired":
        return _expire_order(request, reason=reason)
    fill_quantity = (
        _decimal(outcome.get("fill_quantity"))
        if outcome_kind == "partial"
        else request.quantity
    )
    if fill_quantity is None or fill_quantity <= Decimal("0"):
        fill_quantity = request.quantity
    fill_price = _decimal(outcome.get("fill_price")) or request.price
    return broker.submit_order(
        request,
        fill_id=f"{request.order_id}-FILL-1",
        fill_quantity=fill_quantity,
        fill_price=fill_price,
    )


def _expire_order(request: PaperOrderRequest, *, reason: str) -> PaperBrokerResult:
    oms = PaperOmsStateMachine(
        order_id=request.order_id,
        timestamp=request.timestamp,
        source=PAPER_SHADOW_SOURCE,
    )
    oms.mark_submitted()
    oms.mark_expired(reason=reason)
    return PaperBrokerResult(
        order=PaperOrderEvidence(
            order_id=request.order_id,
            timestamp=request.timestamp,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            asset_class=request.asset_class,
            status=oms.current_status,
            filled_quantity=oms.filled_quantity,
            remaining_quantity=request.quantity - oms.filled_quantity,
            status_history=oms.status_history,
            oms_transitions=oms.transitions,
            context=request.context,
        ),
        fill=None,
    )


def _record_shadow_order(
    db: Any,
    order: PaperOrderEvidence,
    *,
    run_id: str,
    plan_date: str,
    input_fingerprint: str,
    intent_ref: str,
    intent: dict[str, Any],
    divergence_status: str,
) -> None:
    payload = order.to_payload()
    payload.update(
        {
            "schema_version": PAPER_BROKER_SCHEMA_VERSION,
            "run_id": run_id,
            "plan_date": plan_date,
            "input_fingerprint": input_fingerprint,
            "order_intent_ref": intent_ref,
            "order_intent": _order_intent_snapshot(intent, intent_ref),
            "divergence_status": divergence_status,
            "execution_mode": PAPER_SHADOW_EXECUTION_MODE,
            "source": PAPER_SHADOW_SOURCE,
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        }
    )
    db.record_order_sync(
        order_id=order.order_id,
        timestamp=order.timestamp.isoformat(),
        symbol=str(order.symbol),
        side=order.side.value,
        order_type=order.order_type.value,
        quantity=float(order.quantity),
        price=float(order.price) if order.price is not None else None,
        asset_class=order.asset_class.value,
        intent_id=intent_ref,
        risk_decision_id=order.context.risk_decision_id,
        execution_mode=PAPER_SHADOW_EXECUTION_MODE,
        status=order.status.value,
        source=PAPER_SHADOW_SOURCE,
        source_ref=run_id,
        payload=payload,
    )
    _record_shadow_oms_order(
        db,
        order,
        run_id=run_id,
        input_fingerprint=input_fingerprint,
        intent_ref=intent_ref,
        intent=intent,
    )


def _record_shadow_fill(
    db: Any,
    fill: PaperFillEvidence,
    *,
    run_id: str,
    plan_date: str,
    input_fingerprint: str,
) -> None:
    metadata = fill.to_payload()
    metadata.update(
        {
            "run_id": run_id,
            "plan_date": plan_date,
            "input_fingerprint": input_fingerprint,
            "execution_mode": PAPER_SHADOW_EXECUTION_MODE,
            "source": PAPER_SHADOW_SOURCE,
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        }
    )
    db.record_fill_sync(
        fill_id=fill.fill_id,
        order_id=fill.order_id,
        timestamp=fill.timestamp.isoformat(),
        symbol=str(fill.symbol),
        side=fill.side.value,
        fill_price=float(fill.fill_price),
        fill_quantity=float(fill.fill_quantity),
        commission=float(fill.commission),
        slippage=float(fill.slippage),
        asset_class=fill.asset_class.value,
        execution_mode=PAPER_SHADOW_EXECUTION_MODE,
        provider_name=fill.provider_name,
        broker_order_id=fill.order_id,
        source=PAPER_SHADOW_SOURCE,
        source_ref=run_id,
        metadata=metadata,
    )


def _record_shadow_failed_order(
    db: Any,
    request: PaperOrderRequest,
    *,
    run_id: str,
    plan_date: str,
    input_fingerprint: str,
    intent_ref: str,
    intent: dict[str, Any],
    error: Exception,
) -> None:
    payload = {
        "schema_version": PAPER_SHADOW_RUN_SCHEMA_VERSION,
        "order_id": request.order_id,
        "symbol": str(request.symbol),
        "side": request.side.value,
        "order_type": request.order_type.value,
        "quantity": str(request.quantity),
        "price": str(request.price) if request.price is not None else None,
        "asset_class": request.asset_class.value,
        "status": "failed",
        "run_id": run_id,
        "plan_date": plan_date,
        "input_fingerprint": input_fingerprint,
        "order_intent_ref": intent_ref,
        "order_intent": _order_intent_snapshot(intent, intent_ref),
        "divergence_status": "failed",
        "execution_mode": PAPER_SHADOW_EXECUTION_MODE,
        "source": PAPER_SHADOW_SOURCE,
        "error_type": type(error).__name__,
        "error": str(error),
        "context": request.context.to_payload(),
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }
    db.record_order_sync(
        order_id=request.order_id,
        timestamp=request.timestamp.isoformat(),
        symbol=str(request.symbol),
        side=request.side.value,
        order_type=request.order_type.value,
        quantity=float(request.quantity),
        price=float(request.price) if request.price is not None else None,
        asset_class=request.asset_class.value,
        intent_id=intent_ref,
        risk_decision_id=request.context.risk_decision_id,
        execution_mode=PAPER_SHADOW_EXECUTION_MODE,
        status="failed",
        source=PAPER_SHADOW_SOURCE,
        source_ref=run_id,
        payload=payload,
    )
    _record_shadow_failed_oms_order(
        db,
        request,
        run_id=run_id,
        input_fingerprint=input_fingerprint,
        intent_ref=intent_ref,
        intent=intent,
        error=error,
    )


def _record_shadow_oms_order(
    db: Any,
    order: PaperOrderEvidence,
    *,
    run_id: str,
    input_fingerprint: str,
    intent_ref: str,
    intent: dict[str, Any],
) -> None:
    if not _db_supports_oms(db):
        return
    service = OmsService(db=db)
    oms_order = service.create_paper_shadow_order(
        intent_key=_paper_shadow_oms_intent_key(
            run_id=run_id,
            intent_ref=intent_ref,
        ),
        order_id=order.order_id,
        run_id=run_id,
        symbol=str(order.symbol),
        side=order.side.value,
        asset_class=order.asset_class.value,
        quantity=float(order.quantity),
        order_type=order.order_type.value,
        limit_price=float(order.price) if order.price is not None else None,
        source_ref=intent_ref,
        evidence_refs=_dedupe_refs(
            [intent_ref]
            + [str(item) for item in intent.get("evidence_refs") or []]
            + [f"paper_order:{order.order_id}"]
        ),
        source=PAPER_SHADOW_SOURCE,
    )
    _replay_shadow_oms_transitions(
        service,
        order_id=order.order_id,
        current_status=str(oms_order["status"]),
        transitions=[transition.to_payload() for transition in order.oms_transitions],
        evidence={
            "paper_order_id": order.order_id,
            "run_id": run_id,
            "input_fingerprint": input_fingerprint,
            "order_intent_ref": intent_ref,
        },
    )


def _record_shadow_failed_oms_order(
    db: Any,
    request: PaperOrderRequest,
    *,
    run_id: str,
    input_fingerprint: str,
    intent_ref: str,
    intent: dict[str, Any],
    error: Exception,
) -> None:
    if not _db_supports_oms(db):
        return
    service = OmsService(db=db)
    oms_order = service.create_paper_shadow_order(
        intent_key=_paper_shadow_oms_intent_key(
            run_id=run_id,
            intent_ref=intent_ref,
        ),
        order_id=request.order_id,
        run_id=run_id,
        symbol=str(request.symbol),
        side=request.side.value,
        asset_class=request.asset_class.value,
        quantity=float(request.quantity),
        order_type=request.order_type.value,
        limit_price=float(request.price) if request.price is not None else None,
        source_ref=intent_ref,
        evidence_refs=_dedupe_refs(
            [intent_ref]
            + [str(item) for item in intent.get("evidence_refs") or []]
            + [f"paper_order:{request.order_id}"]
        ),
        source=PAPER_SHADOW_SOURCE,
    )
    if str(oms_order["status"]) != "staged":
        return
    service.transition_order(
        request.order_id,
        to_status="submitted",
        reason="paper shadow simulation started",
        actor="paper-shadow",
        source=PAPER_SHADOW_SOURCE,
        evidence={
            "paper_order_id": request.order_id,
            "run_id": run_id,
            "input_fingerprint": input_fingerprint,
            "order_intent_ref": intent_ref,
        },
    )
    service.transition_order(
        request.order_id,
        to_status="rejected",
        reason=f"paper shadow simulation failed: {type(error).__name__}: {error}",
        actor="paper-shadow",
        source=PAPER_SHADOW_SOURCE,
        evidence={
            "paper_order_id": request.order_id,
            "run_id": run_id,
            "input_fingerprint": input_fingerprint,
            "order_intent_ref": intent_ref,
            "error_type": type(error).__name__,
            "error": str(error),
        },
    )


def _replay_shadow_oms_transitions(
    service: OmsService,
    *,
    order_id: str,
    current_status: str,
    transitions: list[dict[str, Any]],
    evidence: dict[str, Any],
) -> None:
    statuses = [str(item.get("to_status") or "") for item in transitions]
    if current_status in statuses:
        start = statuses.index(current_status) + 1
    else:
        start = 0
    for transition in transitions[start:]:
        to_status = str(transition.get("to_status") or "")
        if not to_status or to_status == current_status:
            continue
        service.transition_order(
            order_id,
            to_status=to_status,
            reason=str(transition.get("reason") or f"paper shadow {to_status}"),
            actor="paper-shadow",
            source=PAPER_SHADOW_SOURCE,
            evidence={
                **evidence,
                "filled_quantity": transition.get("filled_quantity"),
            },
        )
        current_status = to_status


def _paper_shadow_oms_intent_key(
    *,
    run_id: str,
    intent_ref: str,
) -> str:
    return f"paper-shadow:{run_id}:{intent_ref}"


def _db_supports_oms(db: Any) -> bool:
    return all(
        callable(getattr(db, name, None))
        for name in (
            "get_oms_order_by_intent_key_sync",
            "upsert_oms_order_sync",
            "record_oms_transition_sync",
            "get_oms_order_sync",
            "update_oms_order_status_sync",
        )
    )


def _run_status(
    *,
    order_intent_count: int,
    simulated_order_count: int,
    order_summaries: list[dict[str, Any]],
    limitations: list[str],
) -> tuple[str, str, str]:
    if order_intent_count == 0:
        return "not_required", "not_required", "none"
    if any(
        order.get("status") == "failed" or order.get("divergence_status") == "failed"
        for order in order_summaries
    ):
        return "failed", "failed", "inspect_failed_run"
    if limitations or simulated_order_count < order_intent_count:
        return "review_required", "review_required", "review_shadow_divergence"
    if all(order.get("status") == "filled" for order in order_summaries):
        return (
            "within_expectations",
            "within_expectations",
            "review_manual_confirmation",
        )
    if any(order.get("divergence_status") == "diverged" for order in order_summaries):
        return "diverged", "diverged", "resolve_shadow_divergence"
    return "review_required", "review_required", "review_shadow_divergence"


def _divergence_status(result: PaperBrokerResult) -> str:
    if result.order.status.value == "filled":
        return "within_expectations"
    if result.order.status.value in {
        "partially_filled",
        "rejected",
        "cancelled",
        "expired",
    }:
        return "diverged"
    return "review_required"


def _divergence_summary(
    *,
    trading_plan: dict[str, Any],
    order_intents: list[dict[str, Any]],
    order_summaries: list[dict[str, Any]],
    fill_summaries: list[dict[str, Any]],
    divergence_status: str,
    next_manual_review_step: str,
) -> dict[str, Any]:
    return {
        "status": divergence_status,
        "order_intent_count": len(order_intents),
        "simulated_order_count": len(order_summaries),
        "simulated_fill_count": len(fill_summaries),
        "missing_simulation_count": max(
            len(order_intents) - len(order_summaries),
            0,
        ),
        "diverged_order_count": sum(
            1
            for order in order_summaries
            if order.get("divergence_status") in {"diverged", "failed"}
        ),
        "current_account_facts": _current_account_facts(
            trading_plan,
            order_intents,
        ),
        "broker_account_truth_state": _broker_account_truth_state(trading_plan),
        "cost_summary": _cost_summary(order_intents, fill_summaries),
        "expected_strategy_behavior": _expected_strategy_behavior(
            trading_plan,
            order_intents,
        ),
        "execution_comparison": _execution_comparison(
            order_intents=order_intents,
            order_summaries=order_summaries,
            fill_summaries=fill_summaries,
        ),
        "realized_market_context": _realized_market_context(
            order_intents=order_intents,
            fill_summaries=fill_summaries,
        ),
        "next_manual_review_step": next_manual_review_step,
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }


def _run_evidence_refs(
    *,
    order_intents: list[dict[str, Any]],
    order_summaries: list[dict[str, Any]],
    fill_summaries: list[dict[str, Any]],
) -> list[str]:
    refs: list[str] = []
    for index, intent in enumerate(order_intents, start=1):
        refs.append(_order_intent_ref(intent, index))
        refs.extend(str(item) for item in intent.get("evidence_refs") or [])
    refs.extend(
        f"paper_order:{order['order_id']}"
        for order in order_summaries
        if order.get("order_id")
    )
    refs.extend(
        f"paper_fill:{fill['fill_id']}"
        for fill in fill_summaries
        if fill.get("fill_id")
    )
    for order in order_summaries:
        order_id = str(order.get("order_id") or "").strip()
        if not order_id:
            continue
        for transition in order.get("oms_transitions") or []:
            if not isinstance(transition, dict):
                continue
            sequence = transition.get("sequence")
            to_status = str(transition.get("to_status") or "").strip()
            if sequence is None or not to_status:
                continue
            refs.append(f"oms_transition:{order_id}:{sequence}:{to_status}")
    return _dedupe_refs(refs)


def _review_queue(
    *,
    run_id: str,
    trading_plan: dict[str, Any],
    order_intents: list[dict[str, Any]],
    order_summaries: list[dict[str, Any]],
    fill_summaries: list[dict[str, Any]],
    limitations: list[str],
) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    simulated_refs: set[str] = set()
    intents_by_ref = {
        _order_intent_ref(intent, index): intent
        for index, intent in enumerate(order_intents, start=1)
    }
    fills_by_order = _fills_by_order(fill_summaries)
    for order in order_summaries:
        intent = _dict(order.get("order_intent"))
        intent_ref = str(intent.get("action_ref") or "").strip()
        source_intent = intents_by_ref.get(intent_ref, intent)
        order_fills = fills_by_order.get(str(order.get("order_id") or ""), [])
        if intent_ref:
            simulated_refs.add(intent_ref)
        status = str(order.get("status") or "").strip()
        divergence_status = str(order.get("divergence_status") or "").strip()
        if status == "filled" and divergence_status == "within_expectations":
            continue
        if status == "failed" or divergence_status == "failed":
            required_action = "inspect_failed_run"
            severity = "danger"
            reason = (
                f"Paper/shadow simulation failed for {intent_ref}: "
                f"{order.get('error_type')}: {order.get('error')}"
            )
        elif divergence_status == "diverged":
            required_action = "resolve_shadow_divergence"
            severity = "warning"
            reason = (
                f"Paper/shadow order {status}; compare simulated execution "
                "with the original order intent before manual confirmation."
            )
        else:
            required_action = "review_shadow_divergence"
            severity = "warning"
            reason = "Paper/shadow order requires review before manual confirmation."
        item = {
            "review_id": f"{run_id}:{_review_ref_suffix(intent_ref)}",
            "order_intent_ref": intent_ref,
            "order_id": order.get("order_id"),
            "symbol": order.get("symbol"),
            "status": status,
            "divergence_status": divergence_status or "review_required",
            "severity": severity,
            "required_action": required_action,
            "reason": reason,
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        }
        item.update(
            _review_evidence(
                trading_plan=trading_plan,
                intent_ref=intent_ref,
                intent=source_intent,
                order=order,
                fills=order_fills,
            )
        )
        for key in ("filled_quantity", "remaining_quantity"):
            if order.get(key) is not None:
                item[key] = order.get(key)
        queue.append(item)

    for index, intent in enumerate(order_intents, start=1):
        intent_ref = _order_intent_ref(intent, index)
        if intent_ref in simulated_refs:
            continue
        reasons = [
            limitation
            for limitation in limitations
            if f"order_intent[{index}]" in limitation
        ]
        reason = "; ".join(reasons) if reasons else "Order intent was not simulated."
        queue.append(
            {
                "review_id": f"{run_id}:{_review_ref_suffix(intent_ref)}",
                "order_intent_ref": intent_ref,
                "order_id": None,
                "symbol": str(intent.get("symbol") or ""),
                "status": "missing_simulation",
                "divergence_status": "review_required",
                "severity": "warning",
                "required_action": "review_shadow_divergence",
                "reason": reason,
                "does_not_submit_broker_order": True,
                "does_not_mutate_production_ledger": True,
                **_review_evidence(
                    trading_plan=trading_plan,
                    intent_ref=intent_ref,
                    intent=intent,
                    order={},
                    fills=[],
                ),
            }
        )
    return queue


def _review_evidence(
    *,
    trading_plan: dict[str, Any],
    intent_ref: str,
    intent: dict[str, Any],
    order: dict[str, Any],
    fills: list[dict[str, Any]],
) -> dict[str, Any]:
    refs = [str(item) for item in intent.get("evidence_refs") or []]
    order_id = str(order.get("order_id") or "").strip()
    return {
        "strategy_refs": _dedupe_refs(_refs_with_prefix(refs, "strategy:")),
        "risk_refs": _dedupe_refs(_refs_with_prefix(refs, "risk:")),
        "signal_refs": _dedupe_refs(_refs_with_prefix(refs, "signal:")),
        "evidence_refs": _dedupe_refs(
            [intent_ref]
            + refs
            + ([f"paper_order:{order_id}"] if order_id else [])
            + [f"paper_fill:{fill['fill_id']}" for fill in fills if fill.get("fill_id")]
        ),
        "account_truth": _broker_account_truth_state(trading_plan),
        "risk_gate_status": intent.get("risk_gate_status"),
        "manual_confirmation_status": intent.get("manual_confirmation_status"),
        "submission_status": intent.get("submission_status"),
        "cash_status": intent.get("cash_status"),
        "constraint_status_counts": _constraint_status_counts(intent),
        "cost_evidence": _review_cost_evidence(intent, fills),
        "market_context": _review_market_context(intent, fills),
        **_review_oms_transition_evidence(order),
    }


def _review_oms_transition_evidence(order: dict[str, Any]) -> dict[str, Any]:
    transitions = [
        item for item in order.get("oms_transitions") or [] if isinstance(item, dict)
    ]
    order_id = str(order.get("order_id") or "").strip()
    summarized = [_review_oms_transition(item) for item in transitions]
    return {
        "oms_status_path": [
            str(item["to_status"]) for item in summarized if item.get("to_status")
        ],
        "oms_transition_refs": [
            f"oms_transition:{order_id}:{item['sequence']}:{item['to_status']}"
            for item in summarized
            if order_id and item.get("sequence") is not None and item.get("to_status")
        ],
        "oms_transitions": summarized,
    }


def _review_oms_transition(transition: dict[str, Any]) -> dict[str, Any]:
    return {
        "sequence": transition.get("sequence"),
        "from_status": transition.get("from_status"),
        "to_status": transition.get("to_status"),
        "source": transition.get("source"),
        "reason": transition.get("reason") or "",
        "filled_quantity": transition.get("filled_quantity"),
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }


def _constraint_status_counts(intent: dict[str, Any]) -> dict[str, int]:
    checks = intent.get("constraint_checks")
    if not isinstance(checks, list):
        return {}
    return _value_counts(
        check.get("status") for check in checks if isinstance(check, dict)
    )


def _review_cost_evidence(
    intent: dict[str, Any],
    fills: list[dict[str, Any]],
) -> dict[str, Any]:
    simulated_fee_tax_cost = sum(
        _decimal_or_zero(fill.get("commission")) for fill in fills
    )
    simulated_slippage_cost = sum(
        _decimal_or_zero(fill.get("slippage")) for fill in fills
    )
    return {
        "estimated_gross_amount": _string_or_none(intent.get("estimated_gross_amount")),
        "estimated_total_fee": _string_or_none(intent.get("estimated_total_fee")),
        "simulated_fee_tax_cost": str(simulated_fee_tax_cost),
        "simulated_slippage_cost": str(simulated_slippage_cost),
        "fee_rule_id": intent.get("fee_rule_id"),
    }


def _review_market_context(
    intent: dict[str, Any],
    fills: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "price_basis": str(intent.get("price_basis") or "estimated_price"),
        "expected_price": _string_or_none(intent.get("estimated_price")),
        "simulated_fill_prices": [
            str(fill.get("fill_price"))
            for fill in fills
            if fill.get("fill_price") is not None
        ],
    }


def _fills_by_order(
    fill_summaries: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    fills_by_order: dict[str, list[dict[str, Any]]] = {}
    for fill in fill_summaries:
        order_id = str(fill.get("order_id") or "").strip()
        if not order_id:
            continue
        fills_by_order.setdefault(order_id, []).append(fill)
    return fills_by_order


def _review_ref_suffix(intent_ref: str) -> str:
    if ":" in intent_ref:
        return intent_ref.split(":", 1)[1]
    return intent_ref or "unknown"


def _order_intent_snapshot(intent: dict[str, Any], intent_ref: str) -> dict[str, Any]:
    refs = [str(item) for item in intent.get("evidence_refs") or []]
    return {
        "action_ref": intent_ref,
        "symbol": intent.get("symbol"),
        "side": intent.get("side"),
        "estimated_quantity": intent.get("estimated_quantity"),
        "estimated_price": intent.get("estimated_price"),
        "strategy_refs": _refs_with_prefix(refs, "strategy:"),
        "risk_refs": _refs_with_prefix(refs, "risk:"),
        "signal_refs": _refs_with_prefix(refs, "signal:"),
        "price_basis": str(intent.get("price_basis") or "estimated_price"),
        "estimated_gross_amount": intent.get("estimated_gross_amount"),
        "estimated_total_fee": intent.get("estimated_total_fee"),
        "fee_rule_id": intent.get("fee_rule_id"),
        "risk_gate_status": intent.get("risk_gate_status"),
        "manual_confirmation_status": intent.get("manual_confirmation_status"),
        "submission_status": intent.get("submission_status"),
    }


def _expected_strategy_behavior(
    trading_plan: dict[str, Any],
    order_intents: list[dict[str, Any]],
) -> dict[str, Any]:
    refs: list[str] = []
    for intent in order_intents:
        refs.extend(str(item) for item in intent.get("evidence_refs") or [])
    return {
        "source_decision": trading_plan.get("source_decision"),
        "expected_order_count": len(order_intents),
        "symbols": _dedupe_refs(
            [
                str(intent.get("symbol"))
                for intent in order_intents
                if intent.get("symbol")
            ]
        ),
        "side_counts": _value_counts(intent.get("side") for intent in order_intents),
        "strategy_refs": _dedupe_refs(_refs_with_prefix(refs, "strategy:")),
        "risk_refs": _dedupe_refs(_refs_with_prefix(refs, "risk:")),
        "signal_refs": _dedupe_refs(_refs_with_prefix(refs, "signal:")),
        "risk_gate_status_counts": _value_counts(
            intent.get("risk_gate_status") for intent in order_intents
        ),
        "manual_confirmation_status_counts": _value_counts(
            intent.get("manual_confirmation_status") for intent in order_intents
        ),
        "submission_status_counts": _value_counts(
            intent.get("submission_status") for intent in order_intents
        ),
    }


def _execution_comparison(
    *,
    order_intents: list[dict[str, Any]],
    order_summaries: list[dict[str, Any]],
    fill_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_refs = [
        _order_intent_ref(intent, index)
        for index, intent in enumerate(order_intents, start=1)
    ]
    orders_by_ref = {
        str(_dict(order.get("order_intent")).get("action_ref")): order
        for order in order_summaries
        if _dict(order.get("order_intent")).get("action_ref")
    }
    missing_refs = [ref for ref in expected_refs if ref not in orders_by_ref]
    diverged_refs = [
        str(_dict(order.get("order_intent")).get("action_ref"))
        for order in order_summaries
        if order.get("divergence_status") == "diverged"
        and _dict(order.get("order_intent")).get("action_ref")
    ]
    failed_refs = [
        str(_dict(order.get("order_intent")).get("action_ref"))
        for order in order_summaries
        if order.get("divergence_status") == "failed"
        and _dict(order.get("order_intent")).get("action_ref")
    ]
    return {
        "matched_order_count": len(expected_refs) - len(missing_refs),
        "missing_order_intent_refs": missing_refs,
        "diverged_order_refs": diverged_refs,
        "failed_order_refs": failed_refs,
        "simulated_status_counts": _value_counts(
            order.get("status") for order in order_summaries
        ),
        "fill_count_by_order": _fill_count_by_order(fill_summaries),
        "filled_quantity_by_order": {
            str(order["order_id"]): str(order.get("filled_quantity"))
            for order in order_summaries
            if order.get("order_id") and order.get("filled_quantity") is not None
        },
        "remaining_quantity_by_order": {
            str(order["order_id"]): str(order.get("remaining_quantity"))
            for order in order_summaries
            if order.get("order_id") and order.get("remaining_quantity") is not None
        },
    }


def _realized_market_context(
    *,
    order_intents: list[dict[str, Any]],
    fill_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    fills_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for fill in fill_summaries:
        symbol = str(fill.get("symbol") or "")
        if not symbol:
            continue
        fills_by_symbol.setdefault(symbol, []).append(fill)
    symbols: list[dict[str, Any]] = []
    for intent in order_intents:
        symbol = str(intent.get("symbol") or "")
        if not symbol:
            continue
        symbol_fills = fills_by_symbol.get(symbol, [])
        symbols.append(
            {
                "symbol": symbol,
                "price_basis": str(intent.get("price_basis") or "estimated_price"),
                "expected_price": _float_or_none(intent.get("estimated_price")),
                "simulated_fill_prices": [
                    str(fill.get("fill_price"))
                    for fill in symbol_fills
                    if fill.get("fill_price") is not None
                ],
                "simulated_slippage_cost": str(
                    sum(_decimal_or_zero(fill.get("slippage")) for fill in symbol_fills)
                ),
            }
        )
    return {
        "symbol_count": len(symbols),
        "price_basis_counts": _value_counts(
            str(intent.get("price_basis") or "estimated_price")
            for intent in order_intents
        ),
        "symbols": symbols,
    }


def _current_account_facts(
    trading_plan: dict[str, Any],
    order_intents: list[dict[str, Any]],
) -> dict[str, Any]:
    constraint_statuses: list[Any] = []
    for intent in order_intents:
        checks = intent.get("constraint_checks")
        if not isinstance(checks, list):
            continue
        constraint_statuses.extend(
            check.get("status") for check in checks if isinstance(check, dict)
        )
    return {
        "available_cash": _float_or_none(trading_plan.get("available_cash")),
        "cash_status_counts": _value_counts(
            intent.get("cash_status") for intent in order_intents
        ),
        "constraint_status_counts": _value_counts(constraint_statuses),
        "position_effect_count": sum(
            1
            for intent in order_intents
            if isinstance(intent.get("position_effect"), dict)
        ),
    }


def _broker_account_truth_state(trading_plan: dict[str, Any]) -> dict[str, Any]:
    account_truth = _account_truth_snapshot(trading_plan)
    has_evidence = bool(account_truth.get("has_evidence", bool(account_truth)))
    return {
        "gate_status": str(account_truth.get("gate_status") or "not_attached"),
        "has_evidence": has_evidence,
        "blocking_reasons": [
            str(reason) for reason in account_truth.get("blocking_reasons") or []
        ],
    }


def _account_truth_snapshot(trading_plan: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        trading_plan.get("account_truth"),
        _dict(trading_plan.get("summary")).get("account_truth"),
        _dict(trading_plan.get("evidence")).get("account_truth"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


def _cost_summary(
    order_intents: list[dict[str, Any]],
    fill_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    estimated_total_fee = sum(
        _decimal_or_zero(intent.get("estimated_total_fee")) for intent in order_intents
    )
    simulated_fee_tax_cost = sum(
        _decimal_or_zero(fill.get("commission")) for fill in fill_summaries
    )
    simulated_slippage_cost = sum(
        _decimal_or_zero(fill.get("slippage")) for fill in fill_summaries
    )
    fee_rule_ids = _dedupe_refs(
        [
            str(intent.get("fee_rule_id"))
            for intent in order_intents
            if intent.get("fee_rule_id")
        ]
    )
    return {
        "estimated_total_fee": str(estimated_total_fee),
        "simulated_fee_tax_cost": str(simulated_fee_tax_cost),
        "simulated_slippage_cost": str(simulated_slippage_cost),
        "simulated_total_execution_cost": str(
            simulated_fee_tax_cost + simulated_slippage_cost
        ),
        "fee_rule_ids": fee_rule_ids,
        "fill_count_with_cost_evidence": len(
            [
                fill
                for fill in fill_summaries
                if fill.get("commission") is not None or fill.get("fee_breakdown")
            ]
        ),
    }


def _value_counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if value is None or value == "":
            continue
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _fill_count_by_order(fill_summaries: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for fill in fill_summaries:
        order_id = str(fill.get("order_id") or "")
        if not order_id:
            continue
        counts[order_id] = counts.get(order_id, 0) + 1
    return counts


def _float_or_none(value: Any) -> float | None:
    decimal_value = _decimal(value)
    return float(decimal_value) if decimal_value is not None else None


def _string_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def _decimal_or_zero(value: Any) -> Decimal:
    decimal_value = _decimal(value)
    return decimal_value if decimal_value is not None else Decimal("0")


def _dedupe_refs(refs: list[str]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        value = str(ref).strip()
        if not value or value in seen:
            continue
        values.append(value)
        seen.add(value)
    return values


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _outcome_for_intent(
    intent: dict[str, Any],
    overrides: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    symbol = str(intent.get("symbol") or "")
    action_id = str(intent.get("action_id") or "")
    return overrides.get(symbol) or overrides.get(action_id) or {}


def _normalized_outcome_overrides(
    overrides: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return json.loads(
        json.dumps(
            overrides,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    )


def _input_refs(
    *,
    trading_plan: dict[str, Any],
    plan_date: str,
    input_fingerprint: str,
) -> dict[str, str | None]:
    return {
        "source_decision": (
            str(trading_plan.get("source_decision"))
            if trading_plan.get("source_decision") is not None
            else None
        ),
        "trading_plan_ref": f"trading_plan:{plan_date}:{input_fingerprint[:12]}",
        "trading_plan_schema_version": (
            str(trading_plan.get("schema_version"))
            if trading_plan.get("schema_version") is not None
            else None
        ),
    }


def _input_fingerprint(payload: dict[str, Any]) -> str:
    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _order_intents(trading_plan: dict[str, Any]) -> list[dict[str, Any]]:
    value = trading_plan.get("order_intents")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _plan_date(trading_plan: dict[str, Any], generated_at: str | None) -> str:
    value = trading_plan.get("plan_date") or trading_plan.get("decision_date")
    if value:
        return str(value)
    if generated_at:
        return str(generated_at)[:10]
    return datetime.now().date().isoformat()


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return datetime.now()


def _side(value: Any) -> OrderSide | None:
    try:
        return OrderSide(str(value).lower())
    except ValueError:
        return None


def _asset_class(value: Any) -> AssetClass:
    try:
        return AssetClass(str(value or "stock").lower())
    except ValueError:
        return AssetClass.STOCK


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _paper_order_context(intent: dict[str, Any]) -> PaperOrderContext:
    refs = [str(item) for item in intent.get("evidence_refs") or []]
    return PaperOrderContext(
        strategy_id=_first_ref(refs, "strategy:"),
        signal_id=_first_ref(refs, "signal:") or _order_intent_ref(intent, 0),
        risk_decision_id=_first_ref(refs, "risk:"),
        cost_model_id=str(intent.get("fee_rule_id") or "stock_a_commission_v1"),
    )


def _refs_with_prefix(refs: list[str], prefix: str) -> list[str]:
    return [item for item in refs if item.startswith(prefix)]


def _first_ref(refs: list[str], prefix: str) -> str | None:
    return next((item for item in refs if item.startswith(prefix)), None)


def _order_intent_ref(intent: dict[str, Any], index: int) -> str:
    action_id = intent.get("action_id")
    if action_id is not None and str(action_id):
        return f"action:{action_id}"
    return f"order_intent:{index}"
