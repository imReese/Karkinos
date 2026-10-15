"""Portfolio-owned target allocation for an independent research observation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from fractions import Fraction
from typing import TypeGuard

RESEARCH_TARGET_POLICY_ID = "karkinos.research.target_weights.capped_proportional.v1"
FORMULA_PORTFOLIO_POLICY_ID = "karkinos.research.session_portfolio.liquidity_slots.v1"
_WEIGHT_UNITS = 100_000_000


def build_research_target_weights(
    desired_weights: Mapping[str, Decimal],
    *,
    max_symbol_weight: Decimal,
    max_gross_weight: Decimal,
) -> dict[str, Decimal]:
    """Cap each long-only target, then proportionally cap gross exposure.

    Eight-decimal weights are rounded down using exact rational arithmetic.
    This keeps the total within its bound even at rounding boundaries and does
    not depend on the caller's Decimal context. No cash, holdings or fills are
    inferred from these desired weights.
    """

    for name, limit in (
        ("max_symbol_weight", max_symbol_weight),
        ("max_gross_weight", max_gross_weight),
    ):
        if not _valid_weight(limit) or limit > 1:
            raise ValueError(f"research_target_{name}_invalid")
    if not desired_weights:
        raise ValueError("research_target_universe_empty")
    capped = {}
    for symbol, weight in desired_weights.items():
        if not isinstance(symbol, str) or not symbol or symbol.strip() != symbol:
            raise ValueError("research_target_symbol_invalid")
        if not _valid_weight(weight):
            raise ValueError("research_target_weight_invalid")
        capped[symbol] = Fraction(min(weight, max_symbol_weight))
    gross = sum(capped.values(), Fraction(0))
    scale = min(Fraction(1), Fraction(max_gross_weight) / gross) if gross else 1
    result = {}
    for symbol in sorted(capped):
        scaled_units = capped[symbol] * scale * _WEIGHT_UNITS
        units = scaled_units.numerator // scaled_units.denominator
        # Decimal(tuple) is exact even when the ambient context is restrictive.
        result[symbol] = Decimal((0, tuple(map(int, str(units))), -8))
    return result


def _valid_weight(value: object) -> TypeGuard[Decimal]:
    return isinstance(value, Decimal) and value.is_finite() and value >= 0


def allocate_formula_targets(
    *,
    entries: Sequence[str],
    exits: Sequence[str],
    position_values: Mapping[str, Decimal],
    prices: Mapping[str, Decimal],
    liquidity: Mapping[str, Decimal],
    lot_sizes: Mapping[str, Decimal],
    cash: Decimal,
    equity: Decimal,
    buy_cost: Callable[[str, Decimal, Decimal], Decimal | None],
    max_positions: int = 4,
    max_symbol_weight: Decimal = Decimal("0.25"),
    max_gross_weight: Decimal = Decimal("0.97"),
    cash_buffer_ratio: Decimal = Decimal("0.03"),
) -> dict[str, object]:
    """Allocate one complete session using actual book state and shared cash.

    Existing holdings retain their actual weight unless explicitly exited; the
    symbol cap sizes new entries rather than implying a daily rebalance.
    Exits are targets, not confirmed sales: their positions still consume slots,
    gross exposure and cash until fills arrive. The execution owner supplies the
    complete modeled purchase cost, including its minimum fees and slippage.
    A missing quote bounds the admissible size; it never means a zero-cost fill.
    """
    if (
        type(max_positions) is not int
        or max_positions < 1
        or not _valid_weight(cash)
        or not _valid_weight(equity)
        or equity <= 0
        or any(not _valid_weight(value) for value in position_values.values())
        or any(
            not _valid_weight(value) or value > 1
            for value in (max_symbol_weight, max_gross_weight, cash_buffer_ratio)
        )
        or max_symbol_weight <= 0
        or max_gross_weight <= 0
    ):
        raise ValueError("formula_portfolio_inputs_invalid")
    held = {symbol: value for symbol, value in position_values.items() if value > 0}
    exit_symbols = set(exits) & set(held)
    targets = {
        symbol: (Decimal(0) if symbol in exit_symbols else value / equity)
        for symbol, value in held.items()
    }
    remaining_slots = max(0, max_positions - len(held))
    available = max(Decimal(0), cash - equity * cash_buffer_ratio)
    gross_room = max(
        Decimal(0), equity * max_gross_weight - sum(held.values(), Decimal(0))
    )
    selected = []
    entry_quantities = {}
    purchase_costs = {}
    rejected = {}
    ranked = sorted(
        set(entries) - set(held) - set(exits),
        key=lambda symbol: (-liquidity.get(symbol, Decimal(0)), symbol),
    )
    for symbol in ranked:
        if remaining_slots <= 0:
            rejected[symbol] = "position_limit"
            continue
        price, lot = prices.get(symbol), lot_sizes.get(symbol)
        if not _valid_weight(price) or price <= 0 or not _valid_weight(lot) or lot <= 0:
            rejected[symbol] = "instrument_or_price_unavailable"
            continue
        budget = min(equity * max_symbol_weight, available, gross_room)
        lots = int(budget / (price * lot))
        # Binary search avoids an O(number of shares) cost adjustment for cheap
        # instruments while preserving the canonical fee calculator's result.
        low, high = 0, lots
        while low < high:
            middle = (low + high + 1) // 2
            cost = buy_cost(symbol, price, lot * middle)
            if cost is None:
                high = middle - 1
                continue
            if not _valid_weight(cost) or cost < price * lot * middle:
                raise ValueError("formula_portfolio_buy_cost_invalid")
            if cost <= available and price * lot * middle <= budget:
                low = middle
            else:
                high = middle - 1
        quantity = lot * low
        if quantity <= 0:
            rejected[symbol] = "cash_or_lot_constraint"
            continue
        amount = price * quantity
        cost = buy_cost(symbol, price, quantity)
        if cost is None:
            rejected[symbol] = "cost_quote_unavailable"
            continue
        targets[symbol] = amount / equity
        selected.append(symbol)
        entry_quantities[symbol] = quantity
        purchase_costs[symbol] = cost
        available -= cost
        gross_room -= amount
        remaining_slots -= 1
    return {
        "policy_id": FORMULA_PORTFOLIO_POLICY_ID,
        "target_weights": dict(sorted(targets.items())),
        "selected_entries": selected,
        "entry_quantities": entry_quantities,
        "purchase_costs": purchase_costs,
        "exit_symbols": sorted(exit_symbols),
        "rejected_entries": dict(sorted(rejected.items())),
    }
