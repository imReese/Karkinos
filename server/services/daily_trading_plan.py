"""Read-only daily trading plan aggregation."""

from __future__ import annotations

from math import floor
from typing import Any

from server.services.manual_trade_fees import resolve_manual_trade_fee_breakdown

_READY_MANUAL_CONFIRMATION_STATUS = "ready_for_manual_confirmation"
_ORDERABLE_ACTIONS = {"buy", "sell", "rebalance"}
_BOARD_LOT_ASSET_CLASSES = {"stock", "etf"}
_BLOCKING_ACCOUNT_TRUTH_STATUSES = {"blocked", "missing"}
_BLOCKING_MARKET_STATUSES = {"blocked", "error", "missing", "unavailable"}
_DEFAULT_MIN_CASH_BUFFER_RATIO = 0.03
_DEFAULT_MAX_SINGLE_SYMBOL_WEIGHT = 0.35
_DEFAULT_DRAWDOWN_REVIEW_THRESHOLD = 0.10
_BLOCKING_SUBMISSION_REASONS = {
    "blocked_by_cash_shortfall": ("insufficient_cash", "portfolio"),
    "blocked_by_cash_buffer": ("cash_buffer_breached", "portfolio"),
    "blocked_by_concentration": ("concentration_limit_breached", "portfolio"),
    "blocked_by_t1_available_quantity": (
        "t1_available_quantity_insufficient",
        "risk",
    ),
    "blocked_by_limit_up": ("limit_up_blocked", "market"),
    "blocked_by_limit_down": ("limit_down_blocked", "market"),
    "blocked_by_suspension": ("security_suspended", "market"),
    "blocked_by_special_treatment": ("special_treatment_risk", "risk"),
    "blocked_by_drawdown": ("drawdown_limit_breached", "risk"),
    "blocked_by_fund_nav_latency": ("fund_nav_latency", "market"),
}


def build_daily_trading_plan(
    *,
    decision_payload: dict[str, Any],
    config: Any,
    positions: dict[str, Any] | None = None,
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
            available_cash=available_cash,
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
        intent_blocker = _intent_blocker(candidate, intent)
        if intent_blocker is not None:
            blockers.append(intent_blocker)

    manual_ready_count = sum(
        1
        for intent in order_intents
        if intent["submission_status"] == "manual_confirmation_required"
    )
    conclusion_status, primary_target = _conclusion(
        account_truth_status=account_truth_status,
        market_status=market_status,
        manual_ready_count=manual_ready_count,
        blockers=blockers,
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
        "order_intent_count": len(order_intents),
        "blocked_count": len(blockers),
        "blocker_summary": _blocker_summary(blockers),
        "available_cash": available_cash,
        "total_equity": total_equity,
        "constraint_summary": _constraint_summary(order_intents),
        "portfolio_controls": controls,
        "default_execution_mode": "manual_confirmation",
        "broker_bridge_status": "disabled",
        "order_intents": order_intents,
        "blockers": blockers,
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
    if account_truth_status in _BLOCKING_ACCOUNT_TRUTH_STATUSES:
        return _blocker(candidate, "account_truth_blocked", "account-truth")
    if market_status in _BLOCKING_MARKET_STATUSES:
        return _blocker(candidate, "market_data_unavailable", "market")
    if _status(candidate.get("risk_gate_status"), "not_checked") == "blocked":
        return _blocker(candidate, "risk_gate_blocked", "risk")
    if _status(candidate.get("risk_gate_status"), "not_checked") != "passed":
        return _blocker(candidate, "awaiting_risk_gate", "risk")
    if (
        _status(candidate.get("manual_confirmation_status"), "awaiting_risk_gate")
        != _READY_MANUAL_CONFIRMATION_STATUS
    ):
        return _blocker(
            candidate,
            _status(candidate.get("manual_confirmation_status"), "manual_not_ready"),
            "decision",
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
    price = _float(candidate.get("price"), 0.0)
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
        submission_status = "manual_confirmation_required"
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
        "target_weight": target_weight,
        "estimated_price": price,
        "estimated_quantity": float(quantity),
        "quantity_basis": quantity_basis,
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


def _constraint_checks(
    candidate: dict[str, Any],
    position: Any,
    *,
    side: str,
    quantity: float,
    price: float,
    gross_amount: float,
    total_fee: float,
    fee_breakdown: dict[str, Any],
    total_equity: float,
    available_cash_after: float,
    portfolio: dict[str, Any],
    controls: dict[str, float],
) -> list[dict[str, Any]]:
    asset_class = str(candidate.get("asset_class") or "").lower()
    current_quantity = _position_float(position, "quantity", "shares")
    estimated_quantity_after = (
        max(current_quantity - quantity, 0.0)
        if side == "sell"
        else current_quantity + quantity
    )
    estimated_market_value_after = estimated_quantity_after * price
    estimated_weight_after = (
        estimated_market_value_after / total_equity if total_equity > 0 else 0.0
    )
    checks = [
        _trading_unit_check(asset_class, side, quantity),
        _fee_tax_check(total_fee, fee_breakdown),
        _cash_buffer_check(
            side,
            available_cash_after=available_cash_after,
            total_equity=total_equity,
            min_cash_buffer_ratio=controls["min_cash_buffer_ratio"],
        ),
        _concentration_check(
            side,
            estimated_weight_after=estimated_weight_after,
            max_single_symbol_weight=controls["max_single_symbol_weight"],
        ),
        _t1_check(candidate, position, side=side, quantity=quantity),
        _limit_check(candidate, side=side),
        _suspension_check(candidate),
        _special_treatment_check(candidate),
        _drawdown_check(
            portfolio,
            max_drawdown_review_threshold=controls["max_drawdown_review_threshold"],
        ),
        _fund_nav_latency_check(candidate, asset_class),
    ]
    for check in checks:
        check["estimated_market_value_after"] = estimated_market_value_after
        check["estimated_weight_after"] = estimated_weight_after
        check["estimated_gross_amount"] = gross_amount
    return checks


def _trading_unit_check(asset_class: str, side: str, quantity: float) -> dict[str, Any]:
    if asset_class in _BOARD_LOT_ASSET_CLASSES and side == "buy":
        lot_size = 100.0
        status = "pass" if quantity % lot_size == 0 else "blocked"
        return {
            "id": "trading_unit",
            "status": status,
            "target": "market",
            "required_lot_size": lot_size,
            "estimated_quantity": quantity,
        }
    return {
        "id": "trading_unit",
        "status": "pass",
        "target": "market",
        "required_lot_size": None,
        "estimated_quantity": quantity,
    }


def _fee_tax_check(total_fee: float, fee_breakdown: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "fee_tax_preview",
        "status": "pass" if total_fee >= 0 else "blocked",
        "target": "cost",
        "estimated_total_fee": total_fee,
        "fee_components": fee_breakdown,
    }


def _cash_buffer_check(
    side: str,
    *,
    available_cash_after: float,
    total_equity: float,
    min_cash_buffer_ratio: float,
) -> dict[str, Any]:
    required_cash = total_equity * min_cash_buffer_ratio
    shortfall = max(required_cash - available_cash_after, 0.0) if side == "buy" else 0.0
    return {
        "id": "cash_buffer",
        "status": "blocked" if shortfall > 0 else "pass",
        "target": "portfolio",
        "required_cash": required_cash,
        "available_cash_after": available_cash_after,
        "cash_buffer_shortfall": shortfall,
        "min_cash_buffer_ratio": min_cash_buffer_ratio,
    }


def _concentration_check(
    side: str,
    *,
    estimated_weight_after: float,
    max_single_symbol_weight: float,
) -> dict[str, Any]:
    blocked = side == "buy" and estimated_weight_after > max_single_symbol_weight
    return {
        "id": "concentration",
        "status": "blocked" if blocked else "pass",
        "target": "portfolio",
        "max_single_symbol_weight": max_single_symbol_weight,
        "estimated_weight_after": estimated_weight_after,
    }


def _t1_check(
    candidate: dict[str, Any],
    position: Any,
    *,
    side: str,
    quantity: float,
) -> dict[str, Any]:
    available_quantity = _float(
        candidate.get("t1_available_quantity")
        or candidate.get("sellable_quantity")
        or candidate.get("available_quantity"),
        _position_float(
            position,
            "t1_available_quantity",
            "sellable_quantity",
            "available_quantity",
            "quantity",
            "shares",
        ),
    )
    blocked = side == "sell" and available_quantity < quantity
    return {
        "id": "t1_available_quantity",
        "status": "blocked" if blocked else "pass",
        "target": "risk",
        "available_quantity": available_quantity,
        "estimated_quantity": quantity,
    }


def _limit_check(candidate: dict[str, Any], *, side: str) -> dict[str, Any]:
    limit_status = _candidate_status(
        candidate,
        "limit_status",
        "price_limit_status",
        nested=("market_data", "data_freshness"),
    )
    blocked_limit = (
        "limit_up"
        if side == "buy" and limit_status == "limit_up"
        else "limit_down" if side == "sell" and limit_status == "limit_down" else None
    )
    return {
        "id": blocked_limit or "limit_move",
        "status": "blocked" if blocked_limit is not None else "pass",
        "target": "market",
        "limit_status": limit_status,
        "side": side,
    }


def _suspension_check(candidate: dict[str, Any]) -> dict[str, Any]:
    trading_status = _candidate_status(
        candidate,
        "trading_status",
        "security_status",
        "quote_status",
        nested=("market_data", "data_freshness"),
    )
    return {
        "id": "suspension",
        "status": "blocked" if trading_status == "suspended" else "pass",
        "target": "market",
        "trading_status": trading_status,
    }


def _special_treatment_check(candidate: dict[str, Any]) -> dict[str, Any]:
    display_name = str(
        candidate.get("display_name") or candidate.get("name") or ""
    ).upper()
    is_st = bool(candidate.get("special_treatment")) or display_name.startswith(
        ("ST", "*ST")
    )
    return {
        "id": "special_treatment",
        "status": "blocked" if is_st else "pass",
        "target": "risk",
        "special_treatment": is_st,
    }


def _drawdown_check(
    portfolio: dict[str, Any],
    *,
    max_drawdown_review_threshold: float,
) -> dict[str, Any]:
    current_drawdown = _float(portfolio.get("current_drawdown"), 0.0)
    return {
        "id": "drawdown",
        "status": (
            "blocked" if current_drawdown >= max_drawdown_review_threshold else "pass"
        ),
        "target": "risk",
        "current_drawdown": current_drawdown,
        "max_drawdown_review_threshold": max_drawdown_review_threshold,
    }


def _fund_nav_latency_check(
    candidate: dict[str, Any], asset_class: str
) -> dict[str, Any]:
    data_status = _candidate_status(
        candidate,
        "nav_status",
        "quote_status",
        nested=("data_freshness", "market_data"),
    )
    blocked = asset_class == "fund" and data_status in {
        "estimated",
        "stale",
        "missing",
        "unavailable",
    }
    return {
        "id": "fund_nav_latency",
        "status": "blocked" if blocked else "pass",
        "target": "market",
        "data_status": data_status,
    }


def _estimated_quantity(
    candidate: dict[str, Any],
    *,
    position: Any,
    side: str | None,
    price: float,
    target_weight: float,
    total_equity: float,
) -> tuple[float, str]:
    if price <= 0:
        return 0.0, "price_unavailable"
    if side == "sell":
        quantity = _float(
            candidate.get("current_quantity")
            or candidate.get("position_quantity")
            or candidate.get("quantity"),
            _position_float(position, "quantity", "shares"),
        )
        return quantity, "current_position_quantity"
    raw_quantity = (total_equity * target_weight) / price
    asset_class = str(candidate.get("asset_class") or "").lower()
    if asset_class in _BOARD_LOT_ASSET_CLASSES:
        return float(floor(raw_quantity / 100) * 100), (
            "target_weight_total_equity_lot_rounded"
        )
    return raw_quantity, "target_weight_total_equity"


def _intent_blocker(
    candidate: dict[str, Any],
    intent: dict[str, Any],
) -> dict[str, Any] | None:
    reason_target = _BLOCKING_SUBMISSION_REASONS.get(
        str(intent.get("submission_status") or "")
    )
    if reason_target is None:
        return None
    reason, target = reason_target
    blocker = _blocker(candidate, reason, target)
    blocker["submission_status"] = intent.get("submission_status")
    return blocker


def _constraint_summary(order_intents: list[dict[str, Any]]) -> dict[str, Any]:
    checks = [
        check
        for intent in order_intents
        for check in intent.get("constraint_checks", [])
    ]
    return {
        "check_count": len(checks),
        "passed_count": sum(1 for check in checks if check.get("status") == "pass"),
        "blocked_count": sum(1 for check in checks if check.get("status") == "blocked"),
        "blocked_ids": [
            str(check.get("id")) for check in checks if check.get("status") == "blocked"
        ],
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


def _position_float(position: Any, *names: str) -> float:
    if position is None:
        return 0.0
    for name in names:
        if isinstance(position, dict):
            value = position.get(name)
        else:
            value = getattr(position, name, None)
        if value is not None:
            return _float(value, 0.0)
    return 0.0


def _conclusion(
    *,
    account_truth_status: str,
    market_status: str,
    manual_ready_count: int,
    blockers: list[dict[str, Any]],
) -> tuple[str, str]:
    if account_truth_status in _BLOCKING_ACCOUNT_TRUTH_STATUSES:
        return "account_truth_blocked", "account-truth"
    if market_status in _BLOCKING_MARKET_STATUSES:
        return "data_unavailable", "market"
    if manual_ready_count > 0:
        return "manual_confirmation_ready", "trading"
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


def _blocker_summary(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for blocker in blockers:
        category = _blocker_category(blocker)
        bucket = grouped.setdefault(
            category,
            {
                "category": category,
                "target": blocker.get("target") or "decision",
                "count": 0,
                "reasons": [],
                "sample_symbols": [],
            },
        )
        bucket["count"] += 1
        for reason in _blocker_reasons(blocker):
            if reason and reason not in bucket["reasons"]:
                bucket["reasons"].append(reason)
        symbol = blocker.get("symbol")
        if (
            symbol
            and symbol not in bucket["sample_symbols"]
            and len(bucket["sample_symbols"]) < 5
        ):
            bucket["sample_symbols"].append(symbol)
    return sorted(
        grouped.values(),
        key=lambda item: _BLOCKER_CATEGORY_ORDER.get(str(item["category"]), 99),
    )


_BLOCKER_CATEGORY_ORDER = {
    "account_truth": 0,
    "market_data": 1,
    "portfolio": 2,
    "risk": 3,
    "evidence_not_ready": 4,
    "other": 9,
}


def _blocker_category(blocker: dict[str, Any]) -> str:
    target = str(blocker.get("target") or "").strip().lower()
    reason = str(blocker.get("reason") or "").strip().lower()
    if target == "account-truth" or reason == "account_truth_blocked":
        return "account_truth"
    if target == "market" or reason == "market_data_unavailable":
        return "market_data"
    if target == "portfolio" or reason in {
        "insufficient_cash",
        "cash_buffer_breached",
        "concentration_limit_breached",
    }:
        return "portfolio"
    if reason == "awaiting_risk_gate" or target == "decision":
        return "evidence_not_ready"
    if target == "risk":
        return "risk"
    return "other"


def _side(candidate: dict[str, Any]) -> str | None:
    action = _status(candidate.get("action") or candidate.get("direction"), "")
    if action == "buy":
        return "buy"
    if action == "sell":
        return "sell"
    if action == "rebalance":
        return "buy" if _float(candidate.get("target_weight"), 0.0) > 0 else "sell"
    if action in _ORDERABLE_ACTIONS:
        return action
    return None


def _blocker(candidate: dict[str, Any], reason: str, target: str) -> dict[str, Any]:
    return {
        "action_id": candidate.get("action_id"),
        "symbol": candidate.get("symbol"),
        "reason": reason,
        "reasons": _candidate_blocking_reasons(candidate, fallback=reason),
        "target": target,
        "risk_gate_status": candidate.get("risk_gate_status"),
        "manual_confirmation_status": candidate.get("manual_confirmation_status"),
    }


def _blocker_reasons(blocker: dict[str, Any]) -> list[str]:
    reasons = blocker.get("reasons")
    if isinstance(reasons, list):
        values = [str(reason) for reason in reasons if reason]
        if values:
            return values
    reason = blocker.get("reason")
    return [str(reason)] if reason else []


def _candidate_blocking_reasons(
    candidate: dict[str, Any],
    *,
    fallback: str,
) -> list[str]:
    risk_reasons = candidate.get("risk_gate_reasons")
    if fallback == "risk_gate_blocked" and isinstance(risk_reasons, list):
        values = [str(reason) for reason in risk_reasons if reason]
        if values:
            return values
    return [fallback]


def _evidence_refs(candidate: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    action_id = candidate.get("action_id")
    if action_id is not None:
        refs.append(f"decision_action:{action_id}")
    evidence = _dict(candidate.get("evidence"))
    signal = _dict(evidence.get("signal"))
    signal_id = signal.get("signal_id") or signal.get("id")
    if signal_id is not None:
        refs.append(f"signal:{signal_id}")
    strategy = _dict(evidence.get("strategy"))
    strategy_id = strategy.get("strategy_id")
    if strategy_id is not None:
        refs.append(f"strategy:{strategy_id}")
    return refs


def _candidate_status(
    candidate: dict[str, Any],
    *names: str,
    nested: tuple[str, ...] = (),
) -> str:
    for name in names:
        value = candidate.get(name)
        if value is not None:
            return _status(value, "unknown")
    evidence = _dict(candidate.get("evidence"))
    for nested_name in nested:
        source = _dict(candidate.get(nested_name)) or _dict(evidence.get(nested_name))
        for name in names:
            value = source.get(name)
            if value is not None:
                return _status(value, "unknown")
    return "unknown"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _status(value: Any, default: str = "unknown") -> str:
    text = str(value if value is not None else default).strip().lower()
    return text or default


def _float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _first_float(*values: Any, fallback: float) -> float:
    for value in values:
        if value is None:
            continue
        return _float(value, fallback)
    return fallback


def _bounded_ratio(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def _int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
