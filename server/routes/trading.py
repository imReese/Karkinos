"""Trading control routes."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from inspect import isawaitable
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.contracts.order_state import (
    ManualOrderStateCommand,
    ManualOrderTicketCommand,
)
from server.services.manual_order_tickets import ManualOrderTicketService
from server.services.trading_controls import TradingControlSnapshot

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class KillSwitchRequest(BaseModel):
    enabled: bool
    reason: str = ""


class OrderRejectRequest(BaseModel):
    reason: str = ""


class ActionManualOrderRequest(BaseModel):
    quantity: float
    order_type: str = "market"
    price: float | None = None
    note: str = ""


class ShadowRunRequest(BaseModel):
    run_date: str | None = None
    base_equity: float | None = None


class ShadowDivergenceReviewRequest(BaseModel):
    reviewed_at: str
    divergence_status: str
    review_notes: str
    reviewer: str | None = None


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/trading", tags=["trading"])

    @r.get("/kill-switch", response_model=TradingControlSnapshot)
    async def get_kill_switch() -> TradingControlSnapshot:
        from server.dependencies import get_app_state

        return get_app_state().trading_controls.snapshot()

    @r.put("/kill-switch", response_model=TradingControlSnapshot)
    async def set_kill_switch(payload: KillSwitchRequest) -> TradingControlSnapshot:
        from server.dependencies import get_app_state

        state = get_app_state()
        snapshot = state.trading_controls.set_kill_switch(
            payload.enabled,
            payload.reason,
        )
        if state.hub is not None:
            result = state.hub.broadcast(
                {
                    "event_type": "TradingControlEvent",
                    "control": "kill_switch",
                    "payload": asdict(snapshot),
                }
            )
            if isawaitable(result):
                await result
        return snapshot

    @r.get("/orders")
    async def list_manual_orders(status: str | None = None) -> list[dict]:
        from server.dependencies import get_app_state

        state = get_app_state()
        return state.db.list_manual_orders_sync(status=status)

    @r.post("/actions/{action_id}/manual-order")
    async def create_manual_order_from_action(
        action_id: int,
        payload: ActionManualOrderRequest,
    ) -> dict:
        from server.dependencies import get_app_state

        if payload.quantity <= 0:
            raise HTTPException(status_code=400, detail="quantity must be positive")
        state = get_app_state()
        action = state.db.get_action_task_sync(action_id)
        if action is None:
            raise HTTPException(status_code=404, detail="action task not found")
        side = _manual_order_side(action["direction"])
        if side is None:
            raise HTTPException(
                status_code=400,
                detail=f"action direction is not orderable: {action['direction']}",
            )

        order_id = f"ACTION-{action_id}-MANUAL"
        timestamp = datetime.now().isoformat()
        order_type = payload.order_type or "market"
        price = payload.price if payload.price is not None else action.get("price")
        existing = state.db.get_manual_order_sync(order_id)
        if existing is not None:
            try:
                command = _manual_ticket_replay_command(
                    state.db,
                    action_id=action_id,
                    existing=existing,
                    quantity=payload.quantity,
                    order_type=order_type,
                    requested_price=payload.price,
                    note=payload.note,
                )
            except (RuntimeError, ValueError) as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        else:
            manual_status = action.get("manual_confirmation_status")
            if manual_status != "ready_for_manual_confirmation":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"action is not ready for manual confirmation: {manual_status}"
                    ),
                )
            try:
                current_gate = _current_action_manual_ticket_gate(
                    state,
                    action,
                    proposed_order={
                        "symbol": action.get("symbol"),
                        "side": side,
                        "quantity": payload.quantity,
                        "price": price,
                    },
                )
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            try:
                command = ManualOrderTicketCommand(
                    idempotency_key=f"manual-ticket:action:{action_id}",
                    action_id=action_id,
                    expected_action_status="pending",
                    order_id=order_id,
                    timestamp=timestamp,
                    symbol=action["symbol"],
                    side=side,
                    order_type=order_type,
                    quantity=payload.quantity,
                    price=price,
                    asset_class=action.get("asset_class", "stock"),
                    intent_id=f"ACTION-{action_id}",
                    risk_decision_id=action.get("risk_decision_id"),
                    source_ref=str(action_id),
                    payload={
                        "action_id": action_id,
                        "source_signal_id": action.get("source_signal_id"),
                        "strategy_id": action.get("strategy_id"),
                        "target_weight": action.get("target_weight"),
                        "risk_gate_status": action.get("risk_gate_status"),
                        "manual_confirmation_status": manual_status,
                        "current_action_manual_ticket_gate": current_gate,
                        "note": payload.note,
                    },
                )
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            created = ManualOrderTicketService(persistence=state.db).create(command)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await _broadcast_if_possible(state, "ManualOrderPrepared", created)
        return created

    @r.post("/shadow-runs/daily")
    async def run_daily_shadow_orders(
        payload: ShadowRunRequest | None = None,
    ) -> dict:
        from server.dependencies import get_app_state
        from server.services.daily_trading_plan import build_daily_trading_plan
        from server.services.decision_application import (
            decision_portfolio_context,
            today_decision_payload,
            trading_plan_positions,
        )
        from server.services.paper_shadow_run import run_paper_shadow_from_trading_plan

        state = get_app_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="Database is not initialized")
        body = payload or ShadowRunRequest()
        if body.base_equity is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "caller-supplied shadow base_equity is disabled; "
                    "canonical persisted Account Truth must own sizing"
                ),
            )
        portfolio_context = decision_portfolio_context(state)
        decision_payload = await today_decision_payload(
            state,
            portfolio_context=portfolio_context,
        )
        trading_plan = build_daily_trading_plan(
            decision_payload=decision_payload,
            config=getattr(state, "config", None),
            positions=trading_plan_positions(
                state,
                portfolio_context=portfolio_context,
            ),
        )
        plan_date = str(trading_plan.get("plan_date") or "")
        if body.run_date is not None and body.run_date != plan_date:
            raise HTTPException(
                status_code=409,
                detail=(
                    "requested shadow run_date does not match the canonical "
                    f"persisted plan date: {plan_date or 'missing'}"
                ),
            )
        result = run_paper_shadow_from_trading_plan(
            db=state.db,
            trading_plan=trading_plan,
            generated_at=(
                trading_plan.get("generated_at") or decision_payload.get("generated_at")
            ),
        )
        await _broadcast_if_possible(state, "DailyShadowRunRecorded", result)
        return result

    @r.get("/order-facts")
    async def list_order_facts(
        status: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        from server.dependencies import get_app_state

        state = get_app_state()
        return state.db.list_orders_sync(
            status=status,
            symbol=symbol,
            limit=limit,
            offset=offset,
        )

    @r.get("/fills")
    async def list_fill_facts(
        order_id: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        from server.dependencies import get_app_state

        state = get_app_state()
        return state.db.list_fills_sync(
            order_id=order_id,
            symbol=symbol,
            limit=limit,
            offset=offset,
        )

    @r.post("/order-facts/{order_id}/shadow-divergence-review")
    async def record_shadow_divergence_review(
        order_id: str,
        payload: ShadowDivergenceReviewRequest,
    ) -> dict:
        from server.dependencies import get_app_state

        state = get_app_state()
        order = state.db.get_order_sync(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="order fact not found")
        if order.get("execution_mode") != "paper_shadow":
            raise HTTPException(
                status_code=409,
                detail="shadow divergence review requires a paper_shadow order fact",
            )
        updated = state.db.record_shadow_divergence_review_sync(
            order_id=order_id,
            reviewed_at=payload.reviewed_at,
            divergence_status=payload.divergence_status,
            review_notes=payload.review_notes,
            reviewer=payload.reviewer,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="order fact not found")
        await _broadcast_if_possible(state, "ShadowDivergenceReviewed", updated)
        return updated

    @r.post("/orders/{order_id}/confirm")
    async def confirm_manual_order(order_id: str) -> dict:
        from server.dependencies import get_app_state

        state = get_app_state()
        current = state.db.get_manual_order_sync(order_id)
        if current is None:
            raise HTTPException(status_code=404, detail="manual order not found")
        action_id = _manual_order_action_id(current)
        action = (
            state.db.get_action_task_sync(action_id) if action_id is not None else None
        )
        if not isinstance(action, dict):
            raise HTTPException(
                status_code=409,
                detail=(
                    "manual order confirmation blocked: "
                    "canonical decision action evidence is missing"
                ),
            )
        try:
            _current_action_manual_ticket_gate(
                state,
                action,
                proposed_order={
                    "symbol": current.get("symbol"),
                    "side": current.get("side"),
                    "quantity": current.get("quantity"),
                    "price": current.get("price"),
                },
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        note = "confirmed by operator; downstream execution simulated"
        try:
            updated = ManualOrderTicketService(persistence=state.db).transition(
                ManualOrderStateCommand(
                    idempotency_key=f"manual-order:{order_id}:confirm",
                    order_id=order_id,
                    expected_from="pending_confirm",
                    to_status="confirmed",
                    note=note,
                    action_id=action_id,
                    expected_action_status="pending_manual_confirmation",
                    action_to_status="acted",
                )
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await _broadcast_if_possible(state, "ManualOrderConfirmed", updated)
        return updated

    @r.post("/orders/{order_id}/reject")
    async def reject_manual_order(order_id: str, payload: OrderRejectRequest) -> dict:
        from server.dependencies import get_app_state

        state = get_app_state()
        current = state.db.get_manual_order_sync(order_id)
        if current is None:
            raise HTTPException(status_code=404, detail="manual order not found")
        action_id = _manual_order_action_id(current)
        command_fields: dict[str, Any] = {}
        if action_id is not None:
            command_fields = {
                "action_id": action_id,
                "expected_action_status": "pending_manual_confirmation",
                "action_to_status": "ignored",
            }
        try:
            updated = ManualOrderTicketService(persistence=state.db).transition(
                ManualOrderStateCommand(
                    idempotency_key=f"manual-order:{order_id}:reject",
                    order_id=order_id,
                    expected_from="pending_confirm",
                    to_status="rejected",
                    note=payload.reason,
                    **command_fields,
                )
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await _broadcast_if_possible(state, "ManualOrderRejected", updated)
        return updated

    return r


def _current_action_manual_ticket_gate(
    state: Any,
    action: dict[str, Any],
    *,
    proposed_order: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Re-resolve current persisted gates immediately before ticket writes."""

    from server.services.decision_application import (
        account_truth_gate_evidence,
        action_trade_date,
        data_freshness_evidence,
        paper_shadow_allows_manual_ticket,
        paper_shadow_evidence,
    )
    from server.services.strategy_promotion_pipeline import (
        resolve_strategy_order_generation_gate,
    )

    db = getattr(state, "db", None)
    account_truth = account_truth_gate_evidence(state)
    market_data = data_freshness_evidence(
        action,
        db,
        quotes={},
        allow_direct_quote_fallback=True,
    )
    strategy_gate, strategy_blockers = resolve_strategy_order_generation_gate(
        db,
        str(action.get("strategy_id") or ""),
        as_of_date=action_trade_date(action),
    )
    paper_shadow = paper_shadow_evidence(
        action,
        str(action.get("manual_confirmation_status") or ""),
        db=db,
    )
    blockers: list[str] = []
    trading_controls = getattr(state, "trading_controls", None)
    control_snapshot = (
        trading_controls.snapshot()
        if trading_controls is not None
        and callable(getattr(trading_controls, "snapshot", None))
        else None
    )
    if control_snapshot is None:
        blockers.append("current_trading_controls_unavailable")
    elif bool(getattr(control_snapshot, "kill_switch_enabled", False)):
        blockers.append("current_kill_switch_enabled")
    if str(action.get("risk_gate_status") or "") != "passed":
        blockers.append("current_action_risk_gate_not_passing")
    if (
        str(action.get("manual_confirmation_status") or "")
        != "ready_for_manual_confirmation"
    ):
        blockers.append("current_action_manual_confirmation_not_ready")
    if account_truth.get("gate_status") != "pass":
        blockers.append("current_account_truth_not_passing")
        blockers.extend(
            f"account_truth:{reason}"
            for reason in account_truth.get("blocking_reasons") or []
        )
    if account_truth.get("data_freshness_status") != "fresh":
        blockers.append("current_account_truth_not_fresh")
    if not _is_sha256(account_truth.get("source_fingerprint")):
        blockers.append("current_account_truth_source_fingerprint_invalid")
    if _shanghai_date(account_truth.get("captured_at")) != action_trade_date(action):
        blockers.append("current_account_truth_not_bound_to_action_date")
    ledger_coverage = account_truth.get("ledger_coverage")
    ledger_coverage = ledger_coverage if isinstance(ledger_coverage, dict) else {}
    if ledger_coverage.get("status") != "covered":
        blockers.append("current_account_truth_ledger_coverage_not_complete")
    if str(market_data.get("status") or "") not in {"live", "confirmed"}:
        blockers.append("current_market_data_not_trusted")
        for key in ("reason", "stale_reason", "status"):
            value = str(market_data.get(key) or "").strip()
            if value:
                blockers.append(f"market_data:{value}")
    current_quote_price = _positive_decimal(market_data.get("price"))
    if current_quote_price is None:
        blockers.append("current_market_quote_price_invalid")
    elif proposed_order is not None and not _decimal_values_match(
        proposed_order.get("price"), current_quote_price
    ):
        blockers.append("proposed_order_price_not_bound_to_current_quote")
    if _shanghai_date(market_data.get("quote_timestamp")) != action_trade_date(action):
        blockers.append("current_market_quote_not_bound_to_action_date")
    if not str(market_data.get("quote_source") or "").strip():
        blockers.append("current_market_quote_source_missing")
    if strategy_gate.get("status") != "pass":
        blockers.append("current_strategy_order_generation_not_passing")
    blockers.extend(f"strategy_advancement:{reason}" for reason in strategy_blockers)
    if not paper_shadow_allows_manual_ticket(paper_shadow):
        blockers.append("current_paper_shadow_not_clear")
        blockers.extend(
            f"paper_shadow:{reason}"
            for reason in paper_shadow.get("blocking_reasons") or []
        )
    blockers.extend(
        _manual_ticket_source_binding_blockers(
            action=action,
            proposed_order=proposed_order,
            account_truth=account_truth,
            strategy_gate=strategy_gate,
            paper_shadow=paper_shadow,
        )
    )
    blockers = list(dict.fromkeys(blockers))
    gate = {
        "schema_version": "karkinos.current_action_manual_ticket_gate.v1",
        "status": "pass" if not blockers else "blocked",
        "action_id": action.get("id"),
        "strategy_id": action.get("strategy_id"),
        "account_truth": account_truth,
        "market_data": market_data,
        "trading_controls": {
            "kill_switch_enabled": bool(
                getattr(control_snapshot, "kill_switch_enabled", False)
            ),
            "reason": getattr(control_snapshot, "reason", None),
        },
        "strategy_order_generation": strategy_gate,
        "paper_shadow": paper_shadow,
        "proposed_order": dict(proposed_order or {}),
        "blockers": blockers,
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "does_not_create_order": True,
        "does_not_authorize_execution": True,
        "does_not_change_capital_authority": True,
        "broker_submission_enabled": False,
    }
    if blockers:
        raise ValueError(
            "manual order ticket blocked by current evidence: " + ", ".join(blockers)
        )
    return gate


def _manual_ticket_source_binding_blockers(
    *,
    action: dict[str, Any],
    proposed_order: dict[str, Any] | None,
    account_truth: dict[str, Any],
    strategy_gate: dict[str, Any],
    paper_shadow: dict[str, Any],
) -> list[str]:
    """Bind ticket terms to the exact reviewed plan and simulated order."""

    blockers: list[str] = []
    proposed = proposed_order if isinstance(proposed_order, dict) else {}
    intent = paper_shadow.get("order_intent")
    intent = intent if isinstance(intent, dict) else {}
    if not proposed:
        blockers.append("proposed_manual_order_terms_missing")
    if not intent:
        blockers.append("paper_shadow_order_intent_missing")
        return blockers

    expected_action_ref = f"action:{action.get('id')}"
    if str(intent.get("action_ref") or "") != expected_action_ref:
        blockers.append("paper_shadow_action_binding_mismatch")
    for key, intent_key in (
        ("symbol", "symbol"),
        ("side", "side"),
    ):
        if str(proposed.get(key) or "") != str(intent.get(intent_key) or ""):
            blockers.append(f"paper_shadow_ticket_{key}_mismatch")
    for key, intent_key in (
        ("quantity", "estimated_quantity"),
        ("price", "estimated_price"),
    ):
        if not _decimal_values_match(proposed.get(key), intent.get(intent_key)):
            blockers.append(f"paper_shadow_ticket_{key}_mismatch")

    strategy_id = str(action.get("strategy_id") or "")
    if not strategy_id or f"strategy:{strategy_id}" not in set(
        intent.get("strategy_refs") or []
    ):
        blockers.append("paper_shadow_strategy_binding_mismatch")
    risk_decision_id = str(action.get("risk_decision_id") or "")
    if not risk_decision_id or f"risk:{risk_decision_id}" not in set(
        intent.get("risk_refs") or []
    ):
        blockers.append("paper_shadow_risk_binding_mismatch")
    account_truth_import_run_id = str(account_truth.get("import_run_id") or "")
    if (
        not account_truth_import_run_id
        or f"account_truth:{account_truth_import_run_id}"
        not in set(intent.get("account_truth_refs") or [])
    ):
        blockers.append("paper_shadow_account_truth_binding_mismatch")
    promotion = strategy_gate.get("promotion")
    promotion = promotion if isinstance(promotion, dict) else {}
    advancement_fingerprint = str(
        promotion.get("strategy_advancement_gate_fingerprint") or ""
    )
    if (
        not advancement_fingerprint
        or f"strategy_advancement:{advancement_fingerprint}"
        not in set(intent.get("strategy_advancement_refs") or [])
    ):
        blockers.append("paper_shadow_strategy_advancement_binding_mismatch")
    return blockers


def _decimal_values_match(left: Any, right: Any) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, TypeError, ValueError):
        return False


def _positive_decimal(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed > 0 else None


def _manual_order_side(direction: str) -> str | None:
    if direction in {"buy", "sell"}:
        return direction
    return None


def _shanghai_date(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(_SHANGHAI_TZ).date().isoformat()


def _is_sha256(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    )


def _manual_order_action_id(order: dict) -> int | None:
    payload_json = order.get("payload_json")
    if not payload_json:
        return None
    try:
        payload = json.loads(str(payload_json))
    except json.JSONDecodeError:
        return None
    action_id = payload.get("action_id")
    if action_id is None:
        return None
    return int(action_id)


def _manual_ticket_replay_command(
    database: Any,
    *,
    action_id: int,
    existing: dict[str, Any],
    quantity: float,
    order_type: str,
    requested_price: float | None,
    note: str,
) -> ManualOrderTicketCommand:
    """Rebuild a retry from persisted server evidence and caller-owned terms."""

    shared = database.get_order_sync(str(existing["order_id"]))
    if not isinstance(shared, dict):
        raise RuntimeError("manual order replay is missing its shared projection")
    try:
        stored_payload = json.loads(str(existing.get("payload_json") or ""))
    except json.JSONDecodeError as exc:
        raise RuntimeError("manual order replay payload is invalid") from exc
    if not isinstance(stored_payload, dict):
        raise RuntimeError("manual order replay payload is invalid")
    stored_payload.pop("command_identity", None)
    stored_payload["note"] = note
    return ManualOrderTicketCommand(
        idempotency_key=f"manual-ticket:action:{action_id}",
        action_id=action_id,
        expected_action_status="pending",
        order_id=str(existing["order_id"]),
        timestamp=str(existing["timestamp"]),
        symbol=str(existing["symbol"]),
        side=str(existing["side"]),
        order_type=order_type,
        quantity=quantity,
        price=existing.get("price") if requested_price is None else requested_price,
        asset_class=str(shared["asset_class"]),
        intent_id=str(existing["intent_id"]),
        risk_decision_id=existing.get("risk_decision_id"),
        source=str(shared["source"]),
        source_ref=str(action_id),
        payload=stored_payload,
    )


async def _broadcast_if_possible(state, event_type: str, payload: dict) -> None:
    if state.hub is None:
        return
    result = state.hub.broadcast({"event_type": event_type, "payload": payload})
    if isawaitable(result):
        await result
