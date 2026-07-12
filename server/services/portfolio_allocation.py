"""Deterministic account-level allocation for decision action tasks."""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal
from typing import Any

_BOARD_LOT_ASSET_CLASSES = {"stock", "etf"}
_DEFAULT_MIN_CASH_BUFFER_RATIO = Decimal("0.03")
_DEFAULT_MAX_SINGLE_SYMBOL_WEIGHT = Decimal("0.35")
_ZERO = Decimal("0")


def allocate_action_tasks(
    actions: list[dict[str, Any]],
    *,
    portfolio: Any,
    quotes: dict[str, dict[str, Any]],
    config: Any = None,
) -> list[dict[str, Any]]:
    """Convert raw per-symbol targets into a cash-bounded account allocation.

    Raw strategy targets remain attached as audit evidence. Effective targets
    and quantities are allocated sequentially in the already deterministic
    action order, without netting expected sell proceeds into buy capacity.
    """

    cash = _decimal(getattr(portfolio, "cash", 0))
    positions = dict(getattr(portfolio, "positions", {}) or {})
    total_equity = _portfolio_equity(portfolio, cash)
    min_cash_buffer_ratio = _bounded_ratio(
        _first_value(
            getattr(config, "trading_plan_min_cash_buffer_ratio", None),
            getattr(config, "min_cash_buffer_ratio", None),
        ),
        fallback=_DEFAULT_MIN_CASH_BUFFER_RATIO,
    )
    max_single_symbol_weight = _bounded_ratio(
        getattr(config, "max_single_symbol_weight", None),
        fallback=_DEFAULT_MAX_SINGLE_SYMBOL_WEIGHT,
    )
    required_cash_reserve = total_equity * min_cash_buffer_ratio
    remaining_buy_cash = max(cash - required_cash_reserve, _ZERO)
    buy_allocations = _allocate_buy_quantities(
        actions,
        positions=positions,
        quotes=quotes,
        total_equity=total_equity,
        available_buy_cash=remaining_buy_cash,
        max_single_symbol_weight=max_single_symbol_weight,
    )
    allocated: list[dict[str, Any]] = []

    for index, raw_action in enumerate(actions):
        action = dict(raw_action)
        symbol = str(action.get("symbol") or "")
        raw_target_weight = _bounded_ratio(
            action.get("target_weight"),
            fallback=_ZERO,
        )
        asset_class = str(action.get("asset_class") or "stock").lower()
        position = positions.get(symbol)
        current_quantity = _position_quantity(position)
        available_quantity = _position_available_quantity(position)
        quote = quotes.get(symbol) or {}
        price = _decimal(quote.get("price") or action.get("price"))
        direction = str(action.get("direction") or "").lower()

        allocation_quantity = _ZERO
        effective_target_weight = raw_target_weight
        allocation_status = "not_orderable"
        capped_target_weight = min(raw_target_weight, max_single_symbol_weight)
        remaining_cash_before = remaining_buy_cash

        if price <= 0 or total_equity <= 0:
            allocation_status = "missing_price_or_equity"
        elif direction == "sell" or raw_target_weight <= 0:
            allocation_quantity = max(available_quantity, _ZERO)
            effective_target_weight = _ZERO
            allocation_status = (
                "allocated_exit"
                if allocation_quantity > 0
                else "no_position_available_to_sell"
            )
        elif direction in {"buy", "rebalance"}:
            desired_total_quantity = _target_total_quantity(
                total_equity=total_equity,
                target_weight=capped_target_weight,
                price=price,
                asset_class=asset_class,
            )
            desired_delta = max(desired_total_quantity - current_quantity, _ZERO)
            allocation_quantity = min(
                desired_delta,
                buy_allocations.get(index, _ZERO),
            )
            remaining_buy_cash = max(
                remaining_buy_cash - allocation_quantity * price,
                _ZERO,
            )
            effective_target_weight = (
                (current_quantity + allocation_quantity) * price / total_equity
            )
            if allocation_quantity <= 0:
                allocation_status = "no_buy_capacity_or_target_delta"
            elif allocation_quantity < desired_delta:
                allocation_status = "allocated_cash_bounded"
            elif raw_target_weight > capped_target_weight:
                allocation_status = "allocated_concentration_capped"
            else:
                allocation_status = "allocated"

        action.update(
            {
                "raw_target_weight": float(raw_target_weight),
                "target_weight": float(effective_target_weight),
                "allocation_quantity": float(allocation_quantity),
                "allocation_status": allocation_status,
                "allocation_price": float(price) if price > 0 else None,
                "price": float(price) if price > 0 else action.get("price"),
                "allocation_evidence": {
                    "schema_version": "karkinos.portfolio_allocation.v1",
                    "raw_target_weight": float(raw_target_weight),
                    "capped_target_weight": float(capped_target_weight),
                    "effective_target_weight": float(effective_target_weight),
                    "allocation_quantity": float(allocation_quantity),
                    "current_quantity": float(current_quantity),
                    "available_quantity": float(available_quantity),
                    "price": float(price) if price > 0 else None,
                    "remaining_buy_cash_before": float(remaining_cash_before),
                    "remaining_buy_cash_after": float(remaining_buy_cash),
                    "required_cash_reserve": float(required_cash_reserve),
                    "max_single_symbol_weight": float(max_single_symbol_weight),
                    "sell_proceeds_netted_into_buy_capacity": False,
                    "status": allocation_status,
                },
            }
        )
        allocated.append(action)
    return allocated


def _allocate_buy_quantities(
    actions: list[dict[str, Any]],
    *,
    positions: dict[str, Any],
    quotes: dict[str, dict[str, Any]],
    total_equity: Decimal,
    available_buy_cash: Decimal,
    max_single_symbol_weight: Decimal,
) -> dict[int, Decimal]:
    demands: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        direction = str(action.get("direction") or "").lower()
        raw_target_weight = _bounded_ratio(
            action.get("target_weight"),
            fallback=_ZERO,
        )
        if direction not in {"buy", "rebalance"} or raw_target_weight <= 0:
            continue
        symbol = str(action.get("symbol") or "")
        asset_class = str(action.get("asset_class") or "stock").lower()
        price = _decimal((quotes.get(symbol) or {}).get("price") or action.get("price"))
        if price <= 0 or total_equity <= 0:
            continue
        current_quantity = _position_quantity(positions.get(symbol))
        desired_total_quantity = _target_total_quantity(
            total_equity=total_equity,
            target_weight=min(raw_target_weight, max_single_symbol_weight),
            price=price,
            asset_class=asset_class,
        )
        desired_delta = max(desired_total_quantity - current_quantity, _ZERO)
        if desired_delta <= 0:
            continue
        demands.append(
            {
                "index": index,
                "asset_class": asset_class,
                "price": price,
                "desired_delta": desired_delta,
            }
        )

    allocations = {int(demand["index"]): _ZERO for demand in demands}
    remaining_cash = max(available_buy_cash, _ZERO)
    board_demands = [
        demand
        for demand in demands
        if demand["asset_class"] in _BOARD_LOT_ASSET_CLASSES
    ]
    while board_demands:
        progressed = False
        for demand in board_demands:
            index = int(demand["index"])
            lot_quantity = Decimal("100")
            lot_notional = lot_quantity * demand["price"]
            if allocations[index] + lot_quantity > demand["desired_delta"]:
                continue
            if lot_notional > remaining_cash:
                continue
            allocations[index] += lot_quantity
            remaining_cash -= lot_notional
            progressed = True
        if not progressed:
            break

    fractional_demands = [
        demand
        for demand in demands
        if demand["asset_class"] not in _BOARD_LOT_ASSET_CLASSES
    ]
    total_fractional_notional = sum(
        (demand["desired_delta"] * demand["price"] for demand in fractional_demands),
        _ZERO,
    )
    if remaining_cash > 0 and total_fractional_notional > 0:
        fractional_budget = min(remaining_cash, total_fractional_notional)
        for demand in fractional_demands:
            index = int(demand["index"])
            desired_notional = demand["desired_delta"] * demand["price"]
            cash_share = (
                fractional_budget * desired_notional / total_fractional_notional
            )
            allocations[index] = min(
                demand["desired_delta"],
                _normalize_quantity(
                    cash_share / demand["price"],
                    asset_class=str(demand["asset_class"]),
                ),
            )
    return allocations


def _portfolio_equity(portfolio: Any, cash: Decimal) -> Decimal:
    total_equity = getattr(portfolio, "total_equity", None)
    if callable(total_equity):
        return _decimal(total_equity())
    if total_equity is not None:
        return _decimal(total_equity)
    positions = dict(getattr(portfolio, "positions", {}) or {})
    return cash + sum(
        (
            _decimal(getattr(position, "market_value", 0))
            for position in positions.values()
        ),
        _ZERO,
    )


def _target_total_quantity(
    *,
    total_equity: Decimal,
    target_weight: Decimal,
    price: Decimal,
    asset_class: str,
) -> Decimal:
    return _normalize_quantity(
        total_equity * target_weight / price,
        asset_class=asset_class,
    )


def _normalize_quantity(quantity: Decimal, *, asset_class: str) -> Decimal:
    if asset_class in _BOARD_LOT_ASSET_CLASSES:
        lots = (quantity / Decimal("100")).to_integral_value(rounding=ROUND_FLOOR)
        return max(lots * Decimal("100"), _ZERO)
    return max(quantity.quantize(Decimal("0.000001"), rounding=ROUND_FLOOR), _ZERO)


def _position_quantity(position: Any) -> Decimal:
    if position is None:
        return _ZERO
    return _decimal(getattr(position, "quantity", getattr(position, "shares", 0)))


def _position_available_quantity(position: Any) -> Decimal:
    if position is None:
        return _ZERO
    for name in (
        "t1_available_quantity",
        "sellable_quantity",
        "available_quantity",
        "available_qty",
        "quantity",
        "shares",
    ):
        value = getattr(position, name, None)
        if value is not None:
            return _decimal(value)
    return _ZERO


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _bounded_ratio(value: Any, *, fallback: Decimal) -> Decimal:
    if value is None:
        return fallback
    try:
        ratio = _decimal(value)
    except (ValueError, TypeError):
        return fallback
    return min(max(ratio, _ZERO), Decimal("1"))


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))
