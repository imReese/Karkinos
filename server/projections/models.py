"""Projection models for deterministic portfolio reconstruction."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

ZERO = Decimal("0")


@dataclass(slots=True)
class ProjectedPosition:
    """Reconstructed position state derived from ledger events."""

    symbol: str
    quantity: Decimal = ZERO
    available_qty: Decimal = ZERO
    frozen_qty: Decimal = ZERO
    avg_cost: Decimal = ZERO
    market_value: Decimal = ZERO
    unrealized_pnl: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    commission_paid: Decimal = ZERO
    broker_displayed_cost_basis: Decimal = ZERO
    broker_displayed_unit_cost: Decimal = ZERO
    broker_cost_basis_difference: Decimal = ZERO
    broker_cost_basis_method: str | None = None
    broker_cost_basis_status: str | None = None

    def sync_available_qty(self) -> None:
        self.available_qty = self.quantity - self.frozen_qty


@dataclass(slots=True)
class PortfolioProjection:
    """Deterministic portfolio snapshot reconstructed from ledger entries."""

    cash: Decimal = ZERO
    total_equity: Decimal = ZERO
    total_deposits: Decimal = ZERO
    positions: dict[str, ProjectedPosition] = field(default_factory=dict)
