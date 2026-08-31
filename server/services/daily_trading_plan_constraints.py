"""Constraint projections for read-only daily trading-plan intents."""

from __future__ import annotations

from math import floor
from typing import Any

from server.services.daily_trading_plan_support import blocker as _blocker
from server.services.daily_trading_plan_support import (
    candidate_status as _candidate_status,
)
from server.services.daily_trading_plan_support import float_value as _float

BOARD_LOT_ASSET_CLASSES = {"stock", "etf"}
BLOCKING_SUBMISSION_REASONS = {
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


def constraint_checks(
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
    """Evaluate the complete deterministic intent-constraint set."""

    asset_class = str(candidate.get("asset_class") or "").lower()
    current_quantity = position_float(position, "quantity", "shares")
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
        trading_unit_check(asset_class, side, quantity),
        fee_tax_check(total_fee, fee_breakdown),
        cash_buffer_check(
            side,
            available_cash_after=available_cash_after,
            total_equity=total_equity,
            min_cash_buffer_ratio=controls["min_cash_buffer_ratio"],
        ),
        concentration_check(
            side,
            estimated_weight_after=estimated_weight_after,
            max_single_symbol_weight=controls["max_single_symbol_weight"],
        ),
        t1_check(candidate, position, side=side, quantity=quantity),
        limit_check(candidate, side=side),
        suspension_check(candidate),
        special_treatment_check(candidate),
        drawdown_check(
            portfolio,
            max_drawdown_review_threshold=controls["max_drawdown_review_threshold"],
        ),
        fund_nav_latency_check(candidate, asset_class),
    ]
    for check in checks:
        check["estimated_market_value_after"] = estimated_market_value_after
        check["estimated_weight_after"] = estimated_weight_after
        check["estimated_gross_amount"] = gross_amount
    return checks


def trading_unit_check(asset_class: str, side: str, quantity: float) -> dict[str, Any]:
    if asset_class in BOARD_LOT_ASSET_CLASSES and side == "buy":
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


def fee_tax_check(total_fee: float, fee_breakdown: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "fee_tax_preview",
        "status": "pass" if total_fee >= 0 else "blocked",
        "target": "cost",
        "estimated_total_fee": total_fee,
        "fee_components": fee_breakdown,
    }


def cash_buffer_check(
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


def concentration_check(
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


def t1_check(
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
        position_float(
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


def limit_check(candidate: dict[str, Any], *, side: str) -> dict[str, Any]:
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


def suspension_check(candidate: dict[str, Any]) -> dict[str, Any]:
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


def special_treatment_check(candidate: dict[str, Any]) -> dict[str, Any]:
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


def drawdown_check(
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


def fund_nav_latency_check(
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


def estimated_quantity(
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
    if "allocation_quantity" in candidate:
        return (
            _float(candidate.get("allocation_quantity"), 0.0),
            "portfolio_allocation_quantity",
        )
    if side == "sell":
        quantity = _float(
            candidate.get("current_quantity")
            or candidate.get("position_quantity")
            or candidate.get("quantity"),
            position_float(position, "quantity", "shares"),
        )
        return quantity, "current_position_quantity"
    target_total_quantity = (total_equity * target_weight) / price
    asset_class = str(candidate.get("asset_class") or "").lower()
    if asset_class in BOARD_LOT_ASSET_CLASSES:
        target_total_quantity = float(floor(target_total_quantity / 100) * 100)
    current_quantity = position_float(position, "quantity", "shares")
    delta_quantity = max(target_total_quantity - current_quantity, 0.0)
    return delta_quantity, (
        "target_position_delta_lot_rounded"
        if asset_class in BOARD_LOT_ASSET_CLASSES
        else "target_position_delta"
    )


def intent_blocker(
    candidate: dict[str, Any],
    intent: dict[str, Any],
) -> dict[str, Any] | None:
    reason_target = BLOCKING_SUBMISSION_REASONS.get(
        str(intent.get("submission_status") or "")
    )
    if reason_target is None:
        return None
    reason, target = reason_target
    blocker = _blocker(candidate, reason, target)
    blocker["submission_status"] = intent.get("submission_status")
    return blocker


def constraint_summary(order_intents: list[dict[str, Any]]) -> dict[str, Any]:
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


def position_float(position: Any, *names: str) -> float:
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


__all__ = [
    "constraint_checks",
    "constraint_summary",
    "estimated_quantity",
    "intent_blocker",
    "position_float",
]
