"""Read-only daily trading plan aggregation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from server.services.daily_research_operation_preview import (
    project_daily_research_operation_preview,
    unavailable_daily_research_operation_preview,
)
from server.services.daily_trading_plan_constraints import (
    constraint_checks as _constraint_checks,
)
from server.services.daily_trading_plan_constraints import (
    constraint_summary as _constraint_summary,
)
from server.services.daily_trading_plan_constraints import (
    estimated_quantity as _estimated_quantity,
)
from server.services.daily_trading_plan_constraints import (
    intent_blocker as _intent_blocker,
)
from server.services.daily_trading_plan_constraints import (
    position_float as _position_float,
)
from server.services.daily_trading_plan_support import (
    account_truth_snapshot as _account_truth_snapshot,
)
from server.services.daily_trading_plan_support import blocker as _blocker
from server.services.daily_trading_plan_support import (
    blocker_reasons as _blocker_reasons,
)
from server.services.daily_trading_plan_support import (
    blocker_summary as _blocker_summary,
)
from server.services.daily_trading_plan_support import bounded_ratio as _bounded_ratio
from server.services.daily_trading_plan_support import (
    candidate_blocking_reasons as _candidate_blocking_reasons,
)
from server.services.daily_trading_plan_support import (
    candidate_status as _candidate_status,
)
from server.services.daily_trading_plan_support import evidence_refs as _evidence_refs
from server.services.daily_trading_plan_support import first_float as _first_float
from server.services.daily_trading_plan_support import float_value as _float
from server.services.daily_trading_plan_support import int_value as _int
from server.services.daily_trading_plan_support import mapping as _dict
from server.services.daily_trading_plan_support import side as _side
from server.services.daily_trading_plan_support import status as _status
from server.services.manual_trade_fees import resolve_manual_trade_fee_breakdown

_READY_MANUAL_CONFIRMATION_STATUS = "ready_for_manual_confirmation"
_PAPER_SHADOW_REVIEW_STATUS = "paper_shadow_review_required"
_BLOCKING_ACCOUNT_TRUTH_STATUSES = {"blocked", "missing"}
_BLOCKING_MARKET_STATUSES = {"blocked", "error", "missing", "unavailable"}
_DEFAULT_MIN_CASH_BUFFER_RATIO = 0.03
_DEFAULT_MAX_SINGLE_SYMBOL_WEIGHT = 0.35
_DEFAULT_DRAWDOWN_REVIEW_THRESHOLD = 0.10


def build_daily_trading_plan(
    *,
    decision_payload: dict[str, Any],
    config: Any,
    positions: dict[str, Any] | None = None,
    research_operation_preview: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only daily trading plan from existing decision evidence."""
    summary = _dict(decision_payload.get("summary"))
    candidates = list(decision_payload.get("candidates") or [])
    portfolio = _dict(summary.get("portfolio"))
    account_truth = _dict(summary.get("account_truth"))
    market_data = _dict(summary.get("market_data"))
    position_map = positions or {}

    account_truth_status = _status(account_truth.get("gate_status"), "blocked")
    market_status = _status(market_data.get("source_health"), "unknown")
    total_equity = _float(portfolio.get("total_equity"), 0.0)
    available_cash = _float(portfolio.get("cash"), 0.0)
    controls = _portfolio_controls(portfolio, config)

    blockers: list[dict[str, Any]] = []
    order_intents: list[dict[str, Any]] = []
    planning_cash = available_cash

    for candidate in candidates:
        candidate_blocker = _candidate_blocker(
            candidate,
            account_truth_status=account_truth_status,
            market_status=market_status,
        )
        if candidate_blocker is not None:
            blockers.append(candidate_blocker)
            continue

        intent = _order_intent_preview(
            candidate,
            config=config,
            total_equity=total_equity,
            available_cash=planning_cash,
            position=_position_for_candidate(candidate, position_map),
            portfolio=portfolio,
            controls=controls,
        )
        if intent is None:
            blockers.append(
                _blocker(candidate, "insufficient_order_intent_inputs", "decision")
            )
            continue
        order_intents.append(intent)
        if intent.get("side") == "buy":
            planning_cash = _float(intent.get("available_cash_after"), planning_cash)
        intent_blocker = _intent_blocker(candidate, intent)
        if intent_blocker is not None:
            blockers.append(intent_blocker)

    manual_ready_count = sum(
        1
        for intent in order_intents
        if intent["submission_status"] == "manual_confirmation_required"
    )
    paper_shadow_ready_count = sum(
        1
        for intent in order_intents
        if intent["submission_status"] == "paper_shadow_required"
    )
    conclusion_status, primary_target = _conclusion(
        account_truth_status=account_truth_status,
        market_status=market_status,
        manual_ready_count=manual_ready_count,
        paper_shadow_ready_count=paper_shadow_ready_count,
        blockers=blockers,
    )
    research_preview = project_daily_research_operation_preview(
        research_operation_preview
    ) or unavailable_daily_research_operation_preview(
        "verified_daily_research_operation_preview_not_supplied"
    )

    return {
        "schema_version": "karkinos.daily_trading_plan.v1",
        "plan_date": decision_payload.get("decision_date"),
        "generated_at": decision_payload.get("generated_at"),
        "source_decision": decision_payload.get("decision"),
        "conclusion_status": conclusion_status,
        "primary_target": primary_target,
        "candidate_pool_count": _int(
            summary.get("candidate_count"),
            len(candidates),
        ),
        "manual_ready_count": manual_ready_count,
        "paper_shadow_ready_count": paper_shadow_ready_count,
        "order_intent_count": len(order_intents),
        "blocked_count": len(blockers),
        "blocker_summary": _blocker_summary(blockers),
        "available_cash": available_cash,
        "total_equity": total_equity,
        "account_truth": _account_truth_snapshot(account_truth, account_truth_status),
        "constraint_summary": _constraint_summary(order_intents),
        "portfolio_controls": controls,
        "default_execution_mode": "manual_confirmation",
        "broker_bridge_status": "disabled",
        "order_intents": order_intents,
        "blockers": blockers,
        "research_operation_preview": research_preview,
        "limitations": [
            "Daily trading plan is read-only and does not create orders, fills, or ledger entries.",
            "Order intents are manual-confirmation previews, not broker submissions.",
            "Broker bridge status is disabled by default.",
        ],
    }


def _candidate_blocker(
    candidate: dict[str, Any],
    *,
    account_truth_status: str,
    market_status: str,
) -> dict[str, Any] | None:
    if str(candidate.get("asset_class") or "").strip().lower() != "stock":
        return _blocker(
            candidate,
            "asset_class_outside_daily_candidate_scope",
            "strategy-lab",
        )
    if account_truth_status in _BLOCKING_ACCOUNT_TRUTH_STATUSES:
        return _blocker(candidate, "account_truth_blocked", "account-truth")
    if market_status in _BLOCKING_MARKET_STATUSES:
        return _blocker(candidate, "market_data_unavailable", "market")
    if _status(candidate.get("risk_gate_status"), "not_checked") == "blocked":
        return _blocker(candidate, "risk_gate_blocked", "risk")
    if _status(candidate.get("risk_gate_status"), "not_checked") != "passed":
        return _blocker(candidate, "awaiting_risk_gate", "risk")
    manual_status = _status(
        candidate.get("manual_confirmation_status"),
        "awaiting_risk_gate",
    )
    if manual_status not in {
        _READY_MANUAL_CONFIRMATION_STATUS,
        _PAPER_SHADOW_REVIEW_STATUS,
    }:
        return _blocker(
            candidate,
            manual_status,
            "decision",
        )
    if manual_status == _PAPER_SHADOW_REVIEW_STATUS:
        strategy_gate = _dict(
            _dict(_dict(candidate.get("evidence")).get("strategy")).get(
                "order_generation_gate"
            )
        )
        if strategy_gate.get("status") != "pass":
            return _blocker(
                candidate,
                "strategy_advancement_review_required",
                "strategy-lab",
            )
    if _side(candidate) is None:
        return _blocker(candidate, "action_not_orderable", "decision")
    return None


def _order_intent_preview(
    candidate: dict[str, Any],
    *,
    config: Any,
    total_equity: float,
    available_cash: float,
    position: Any,
    portfolio: dict[str, Any],
    controls: dict[str, float],
) -> dict[str, Any] | None:
    side = _side(candidate)
    candidate_evidence = _dict(candidate.get("evidence"))
    market_quote = _dict(candidate_evidence.get("data_freshness"))
    market_quote_price = _float(market_quote.get("price"), 0.0)
    price = (
        market_quote_price
        if market_quote_price > 0
        else _float(candidate.get("price"), 0.0)
    )
    target_weight = _float(candidate.get("target_weight"), 0.0)
    quantity, quantity_basis = _estimated_quantity(
        candidate,
        position=position,
        side=side,
        price=price,
        target_weight=target_weight,
        total_equity=total_equity,
    )
    if side is None or price <= 0 or quantity <= 0:
        return None

    gross_amount = quantity * price
    fee = resolve_manual_trade_fee_breakdown(
        config,
        asset_class=str(candidate.get("asset_class") or "stock"),
        direction=side,
        quantity=quantity,
        price=price,
        symbol=str(candidate.get("symbol") or ""),
    )
    fee_breakdown = fee.fee_breakdown_json if fee is not None else {}
    total_fee = float(fee.total_fee) if fee is not None else 0.0
    net_cash_impact = (
        -(gross_amount + total_fee) if side == "buy" else gross_amount - total_fee
    )
    available_cash_after = available_cash + net_cash_impact
    cash_shortfall = max(-available_cash_after, 0.0) if side == "buy" else 0.0
    cash_status = "insufficient_cash" if cash_shortfall > 0 else "sufficient"
    constraint_checks = _constraint_checks(
        candidate,
        position,
        side=side,
        quantity=quantity,
        price=price,
        gross_amount=gross_amount,
        total_fee=total_fee,
        fee_breakdown=fee_breakdown,
        total_equity=total_equity,
        available_cash_after=available_cash_after,
        portfolio=portfolio,
        controls=controls,
    )
    blocking_check = next(
        (check for check in constraint_checks if check["status"] == "blocked"),
        None,
    )
    if cash_shortfall > 0:
        submission_status = "blocked_by_cash_shortfall"
    elif blocking_check is not None:
        submission_status = f"blocked_by_{blocking_check['id']}"
    else:
        submission_status = (
            "paper_shadow_required"
            if _status(candidate.get("manual_confirmation_status"))
            == _PAPER_SHADOW_REVIEW_STATUS
            else "manual_confirmation_required"
        )
    if submission_status == "blocked_by_cash_buffer":
        cash_status = "cash_buffer_breached"
        cash_shortfall = next(
            (
                _float(check.get("cash_buffer_shortfall"), 0.0)
                for check in constraint_checks
                if check["id"] == "cash_buffer"
            ),
            0.0,
        )

    return {
        "action_id": candidate.get("action_id"),
        "symbol": candidate.get("symbol"),
        "asset_class": candidate.get("asset_class"),
        "side": side,
        "raw_target_weight": _float(
            candidate.get("raw_target_weight"),
            target_weight,
        ),
        "target_weight": target_weight,
        "estimated_price": price,
        "market_quote_price": (market_quote_price if market_quote_price > 0 else None),
        "market_quote_timestamp": market_quote.get("quote_timestamp"),
        "market_quote_source": market_quote.get("quote_source"),
        "estimated_quantity": float(quantity),
        "quantity_basis": quantity_basis,
        "allocation_status": candidate.get("allocation_status"),
        "allocation_evidence": dict(candidate.get("allocation_evidence") or {}),
        "estimated_gross_amount": gross_amount,
        "estimated_total_fee": total_fee,
        "estimated_net_cash_impact": net_cash_impact,
        "available_cash_before": available_cash,
        "available_cash_after": available_cash_after,
        "cash_status": cash_status,
        "cash_shortfall": cash_shortfall,
        "position_effect": _position_effect(
            position,
            side=side,
            quantity=quantity,
            price=price,
        ),
        "constraint_checks": constraint_checks,
        "fee_breakdown": fee_breakdown,
        "fee_rule_id": getattr(fee, "fee_rule_id", None) if fee is not None else None,
        "fee_rule_version": (
            getattr(fee, "fee_rule_version", None) if fee is not None else None
        ),
        "risk_gate_status": candidate.get("risk_gate_status"),
        "manual_confirmation_status": candidate.get("manual_confirmation_status"),
        "submission_status": submission_status,
        "does_not_submit_broker_order": True,
        "evidence_refs": _evidence_refs(candidate),
    }


def _portfolio_controls(
    portfolio: dict[str, Any],
    config: Any,
) -> dict[str, float]:
    return {
        "min_cash_buffer_ratio": _bounded_ratio(
            _first_float(
                portfolio.get("min_cash_buffer_ratio"),
                getattr(config, "trading_plan_min_cash_buffer_ratio", None),
                getattr(config, "min_cash_buffer_ratio", None),
                fallback=_DEFAULT_MIN_CASH_BUFFER_RATIO,
            )
        ),
        "max_single_symbol_weight": _bounded_ratio(
            _first_float(
                portfolio.get("max_single_symbol_weight"),
                getattr(config, "max_single_symbol_weight", None),
                fallback=_DEFAULT_MAX_SINGLE_SYMBOL_WEIGHT,
            )
        ),
        "max_drawdown_review_threshold": _bounded_ratio(
            _first_float(
                portfolio.get("max_drawdown_review_threshold"),
                getattr(config, "max_drawdown_review_threshold", None),
                fallback=_DEFAULT_DRAWDOWN_REVIEW_THRESHOLD,
            )
        ),
    }


def _position_for_candidate(
    candidate: dict[str, Any],
    positions: dict[str, Any],
) -> Any:
    symbol = candidate.get("symbol")
    if symbol is None:
        return None
    return positions.get(str(symbol))


def _position_effect(
    position: Any,
    *,
    side: str,
    quantity: float,
    price: float,
) -> dict[str, Any]:
    current_quantity = _position_float(position, "quantity", "shares")
    current_avg_cost = _position_float(position, "avg_cost", "average_cost")
    current_market_value = _position_float(position, "market_value")
    if side == "sell":
        quantity_after = max(current_quantity - quantity, 0.0)
        return {
            "current_quantity": current_quantity,
            "current_avg_cost": current_avg_cost,
            "current_market_value": current_market_value,
            "estimated_quantity_after": quantity_after,
            "estimated_avg_cost_after": (
                current_avg_cost if quantity_after > 0 else None
            ),
            "cost_basis_method": "sell_reduces_position_preview",
        }

    quantity_after = current_quantity + quantity
    estimated_avg_cost = (
        ((current_quantity * current_avg_cost) + (quantity * price)) / quantity_after
        if quantity_after > 0
        else None
    )
    return {
        "current_quantity": current_quantity,
        "current_avg_cost": current_avg_cost,
        "current_market_value": current_market_value,
        "estimated_quantity_after": quantity_after,
        "estimated_avg_cost_after": estimated_avg_cost,
        "cost_basis_method": "weighted_average_preview",
    }


def _conclusion(
    *,
    account_truth_status: str,
    market_status: str,
    manual_ready_count: int,
    paper_shadow_ready_count: int,
    blockers: list[dict[str, Any]],
) -> tuple[str, str]:
    if account_truth_status in _BLOCKING_ACCOUNT_TRUTH_STATUSES:
        return "account_truth_blocked", "account-truth"
    if market_status in _BLOCKING_MARKET_STATUSES:
        return "data_unavailable", "market"
    if manual_ready_count > 0:
        return "manual_confirmation_ready", "trading"
    if paper_shadow_ready_count > 0:
        return "paper_shadow_required", "operations"
    if any(item.get("reason") == "insufficient_cash" for item in blockers):
        return "cash_shortfall", "portfolio"
    if any(item.get("target") == "portfolio" for item in blockers):
        return "portfolio_blocked", "portfolio"
    if any(item.get("reason") == "risk_gate_blocked" for item in blockers):
        return "risk_blocked", "risk"
    if any(
        item.get("target") == "risk" and item.get("reason") != "awaiting_risk_gate"
        for item in blockers
    ):
        return "risk_blocked", "risk"
    if any(item.get("target") == "market" for item in blockers):
        return "market_blocked", "market"
    return "no_manual_action", "decision"
