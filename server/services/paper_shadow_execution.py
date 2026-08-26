"""Paper broker execution and OMS persistence for shadow runs."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from core.types import OrderType, Symbol
from execution.paper_broker import (
    PAPER_BROKER_SCHEMA_VERSION,
    PaperBroker,
    PaperBrokerResult,
    PaperFillEvidence,
    PaperOmsStateMachine,
    PaperOrderEvidence,
    PaperOrderRequest,
)
from server.contracts.content_identity import content_fingerprint
from server.contracts.order_state import OmsOrderCommand, OmsTransitionCommand
from server.contracts.paper_shadow import (
    PaperShadowFillFact,
    PaperShadowOrderFact,
    PaperShadowRunPersistence,
)
from server.services.oms import OMS_SCHEMA_VERSION, PAPER_SHADOW_INITIAL_STATUS
from server.services.paper_shadow_contracts import (
    PAPER_SHADOW_EXECUTION_MODE,
    PAPER_SHADOW_RUN_SCHEMA_VERSION,
    PAPER_SHADOW_SOURCE,
)
from server.services.paper_shadow_values import asset_class as _asset_class
from server.services.paper_shadow_values import decimal_value as _decimal
from server.services.paper_shadow_values import dedupe_refs as _dedupe_refs
from server.services.paper_shadow_values import (
    order_intent_snapshot as _order_intent_snapshot,
)
from server.services.paper_shadow_values import (
    paper_order_context as _paper_order_context,
)
from server.services.paper_shadow_values import side as _side


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


def _build_shadow_order(
    order: PaperOrderEvidence,
    *,
    run_id: str,
    plan_date: str,
    input_fingerprint: str,
    intent_ref: str,
    intent: dict[str, Any],
    divergence_status: str,
) -> PaperShadowOrderFact:
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
            "evidence_refs": _dedupe_refs(
                [intent_ref]
                + [str(item) for item in intent.get("evidence_refs") or []]
                + [f"paper_order:{order.order_id}"]
                + _order_payload_oms_transition_refs(
                    order_id=order.order_id,
                    transitions=payload.get("oms_transitions"),
                )
            ),
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        }
    )
    oms_create, oms_transitions = _shadow_oms_commands(
        order_id=order.order_id,
        run_id=run_id,
        input_fingerprint=input_fingerprint,
        intent_ref=intent_ref,
        intent=intent,
        symbol=str(order.symbol),
        side=order.side.value,
        asset_class=order.asset_class.value,
        quantity=float(order.quantity),
        order_type=order.order_type.value,
        limit_price=float(order.price) if order.price is not None else None,
        transitions=[transition.to_payload() for transition in order.oms_transitions],
    )
    return PaperShadowOrderFact(
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
        oms_create=oms_create,
        oms_transitions=oms_transitions,
    )


def _order_payload_oms_transition_refs(
    *,
    order_id: str,
    transitions: Any,
) -> list[str]:
    if not isinstance(transitions, list):
        return []
    refs: list[str] = []
    for transition in transitions:
        if not isinstance(transition, dict):
            continue
        sequence = transition.get("sequence")
        to_status = str(transition.get("to_status") or "").strip()
        if sequence is None or not to_status:
            continue
        refs.append(f"oms_transition:{order_id}:{sequence}:{to_status}")
    return refs


def _build_shadow_fill(
    fill: PaperFillEvidence,
    *,
    run_id: str,
    plan_date: str,
    input_fingerprint: str,
    intent_ref: str,
    intent: dict[str, Any],
) -> PaperShadowFillFact:
    metadata = fill.to_payload()
    metadata.update(
        {
            "run_id": run_id,
            "plan_date": plan_date,
            "input_fingerprint": input_fingerprint,
            "order_intent_ref": intent_ref,
            "evidence_refs": _dedupe_refs(
                [intent_ref]
                + [str(item) for item in intent.get("evidence_refs") or []]
                + [f"paper_order:{fill.order_id}", f"paper_fill:{fill.fill_id}"]
            ),
            "execution_mode": PAPER_SHADOW_EXECUTION_MODE,
            "source": PAPER_SHADOW_SOURCE,
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        }
    )
    return PaperShadowFillFact(
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


def _build_shadow_failed_order(
    request: PaperOrderRequest,
    *,
    run_id: str,
    plan_date: str,
    input_fingerprint: str,
    intent_ref: str,
    intent: dict[str, Any],
    error: Exception,
) -> tuple[PaperShadowOrderFact, list[dict[str, Any]]]:
    oms_transition_payloads = [
        {
            "sequence": 1,
            "from_status": "created",
            "to_status": "staged",
            "source": PAPER_SHADOW_SOURCE,
            "filled_quantity": "0",
            "reason": "created from paper/shadow order intent",
        },
        {
            "sequence": 2,
            "from_status": "staged",
            "to_status": "submitted",
            "source": PAPER_SHADOW_SOURCE,
            "filled_quantity": "0",
            "reason": "paper shadow simulation started",
        },
        {
            "sequence": 3,
            "from_status": "submitted",
            "to_status": "rejected",
            "source": PAPER_SHADOW_SOURCE,
            "filled_quantity": "0",
            "reason": (
                f"paper shadow simulation failed: {type(error).__name__}: {error}"
            ),
        },
    ]
    oms_create, oms_transitions = _shadow_oms_commands(
        order_id=request.order_id,
        run_id=run_id,
        input_fingerprint=input_fingerprint,
        intent_ref=intent_ref,
        intent=intent,
        symbol=str(request.symbol),
        side=request.side.value,
        asset_class=request.asset_class.value,
        quantity=float(request.quantity),
        order_type=request.order_type.value,
        limit_price=float(request.price) if request.price is not None else None,
        transitions=oms_transition_payloads,
        error=error,
    )
    oms_transition_refs = [
        (
            f"oms_transition:{request.order_id}:"
            f"{transition['sequence']}:{transition['to_status']}"
        )
        for transition in oms_transition_payloads
        if transition.get("sequence") is not None and transition.get("to_status")
    ]
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
        "evidence_refs": _dedupe_refs(
            [intent_ref]
            + [str(item) for item in intent.get("evidence_refs") or []]
            + [f"paper_order:{request.order_id}"]
            + oms_transition_refs
        ),
        "oms_transitions": oms_transition_payloads,
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }
    fact = PaperShadowOrderFact(
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
        oms_create=oms_create,
        oms_transitions=oms_transitions,
    )
    return fact, oms_transition_payloads


def _shadow_oms_commands(
    *,
    order_id: str,
    run_id: str,
    input_fingerprint: str,
    intent_ref: str,
    intent: dict[str, Any],
    symbol: str,
    side: str,
    asset_class: str,
    quantity: float,
    order_type: str,
    limit_price: float | None,
    transitions: list[dict[str, Any]],
    error: Exception | None = None,
) -> tuple[OmsOrderCommand, tuple[OmsTransitionCommand, ...]]:
    if not transitions or transitions[0].get("to_status") != "staged":
        raise ValueError("paper-shadow OMS history must begin in staged state")
    intent_key = _paper_shadow_oms_intent_key(
        run_id=run_id,
        intent_ref=intent_ref,
    )
    evidence_refs = _dedupe_refs(
        [intent_ref]
        + [str(item) for item in intent.get("evidence_refs") or []]
        + [f"paper_order:{order_id}"]
    )
    oms_payload = {
        "schema_version": OMS_SCHEMA_VERSION,
        "execution_mode": PAPER_SHADOW_EXECUTION_MODE,
        "run_id": run_id,
        "source_ref": intent_ref,
        "evidence_refs": evidence_refs,
        "manual_confirmation_required": False,
        "broker_submission_enabled": False,
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }
    create = OmsOrderCommand(
        idempotency_key=intent_key,
        order_id=order_id,
        symbol=symbol,
        side=side,
        asset_class=asset_class,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        initial_status=PAPER_SHADOW_INITIAL_STATUS,
        broker_submission_enabled=False,
        source=PAPER_SHADOW_SOURCE,
        source_ref=run_id,
        payload=oms_payload,
        transition_reason="created from paper/shadow order intent",
        transition_payload={
            **oms_payload,
            "intent_key": intent_key,
            "source": PAPER_SHADOW_SOURCE,
        },
    )
    commands: list[OmsTransitionCommand] = []
    for transition in transitions[1:]:
        expected_from = str(transition.get("from_status") or "")
        to_status = str(transition.get("to_status") or "")
        reason = str(transition.get("reason") or f"paper shadow {to_status}")
        payload = {
            "broker_submission_enabled": False,
            "execution_mode": PAPER_SHADOW_EXECUTION_MODE,
            "run_id": run_id,
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
            "source": PAPER_SHADOW_SOURCE,
            "paper_order_id": order_id,
            "input_fingerprint": input_fingerprint,
            "order_intent_ref": intent_ref,
            "filled_quantity": transition.get("filled_quantity"),
        }
        if error is not None and to_status == "rejected":
            payload.update(
                {
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
        command_key = _oms_transition_idempotency_key(
            order_id=order_id,
            from_status=expected_from,
            to_status=to_status,
            reason=reason,
            actor="paper-shadow",
            payload=payload,
        )
        commands.append(
            OmsTransitionCommand(
                idempotency_key=command_key,
                order_id=order_id,
                expected_from=expected_from,
                to_status=to_status,
                reason=reason,
                actor="paper-shadow",
                payload=payload,
            )
        )
    return create, tuple(commands)


def _oms_transition_idempotency_key(
    *,
    order_id: str,
    from_status: str,
    to_status: str,
    reason: str,
    actor: str,
    payload: dict[str, Any],
) -> str:
    fingerprint = content_fingerprint(
        {"reason": reason, "actor": actor, "payload": payload}
    )
    return f"oms-transition:{order_id}:{from_status}:{to_status}:{fingerprint}"


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _matching_latest_run(
    db: PaperShadowRunPersistence,
    *,
    plan_date: str,
    input_fingerprint: str,
) -> dict[str, Any] | None:
    """Reuse an exact persisted simulation across workflow-only status changes."""

    row = db.latest_paper_shadow_run_sync(plan_date=plan_date)
    if not isinstance(row, dict) or row.get("input_fingerprint") != input_fingerprint:
        return None
    payload = _json_dict(row.get("payload_json"))
    if not payload:
        return None
    limitations = _json_list(row.get("limitations_json")) or list(
        payload.get("limitations") or []
    )
    return {
        **row,
        **payload,
        "run_id": row.get("run_id"),
        "input_fingerprint": row.get("input_fingerprint"),
        "status": row.get("status"),
        "order_intent_count": row.get("order_intent_count"),
        "simulated_order_count": row.get("simulated_order_count"),
        "simulated_fill_count": row.get("simulated_fill_count"),
        "divergence_status": row.get("divergence_status"),
        "next_manual_review_step": row.get("next_manual_review_step"),
        "limitations": limitations,
        "reused_existing_run": True,
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _paper_shadow_oms_intent_key(
    *,
    run_id: str,
    intent_ref: str,
) -> str:
    return f"paper-shadow:{run_id}:{intent_ref}"


paper_order_request = _paper_order_request
simulate_outcome = _simulate_outcome
expire_order = _expire_order
build_shadow_order = _build_shadow_order
order_payload_oms_transition_refs = _order_payload_oms_transition_refs
build_shadow_fill = _build_shadow_fill
build_shadow_failed_order = _build_shadow_failed_order
shadow_oms_commands = _shadow_oms_commands
json_dict = _json_dict
matching_latest_run = _matching_latest_run
json_list = _json_list
paper_shadow_oms_intent_key = _paper_shadow_oms_intent_key
