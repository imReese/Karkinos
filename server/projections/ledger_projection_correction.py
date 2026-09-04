"""Validation and replay of protected ledger projection corrections."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from server.ledger.models import LedgerEntry
from server.projections.legacy_fund_trade_duplicate_contract import (
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE,
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_PLAN_SCHEMA_VERSION,
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE,
)
from server.projections.models import ZERO, PortfolioProjection, ProjectedPosition
from server.projections.portfolio_projection_values import as_decimal as _as_decimal
from server.projections.portfolio_projection_values import require_text as _require_text

_PROJECTION_CORRECTION_CONTRACTS = {
    "controlled_projection_correction": (
        "controlled_submission_ledger_correction",
        "karkinos.controlled_submission_ledger_correction_plan.v1",
        "Controlled ledger correction",
    ),
    "manual_trade_projection_correction": (
        "manual_trade_correction",
        "karkinos.manual_trade_correction_plan.v1",
        "Manual trade correction",
    ),
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE: (
        LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE,
        LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_PLAN_SCHEMA_VERSION,
        "Legacy fund trade duplicate correction",
    ),
}


def is_projection_correction_entry_type(entry_type: str) -> bool:
    """Return whether ``entry_type`` has a protected correction contract."""

    return entry_type in _PROJECTION_CORRECTION_CONTRACTS


def apply_projection_correction(
    projection: PortfolioProjection,
    entry: LedgerEntry,
    *,
    entry_type: str,
) -> None:
    """Apply a protected, canonical-replay-derived compensating event."""

    expected_source, expected_schema, label = _PROJECTION_CORRECTION_CONTRACTS[
        entry_type
    ]
    if entry.source != expected_source:
        raise ValueError(f"{label} source is invalid")
    payload = entry.correction_payload
    if not isinstance(payload, dict):
        raise ValueError(f"{label} payload is missing")
    if payload.get("schema_version") != expected_schema:
        raise ValueError(f"{label} schema is invalid")
    if payload.get("arbitrary_financial_input_used") is not False:
        raise ValueError(f"{label} derivation is invalid")

    symbol = _require_text(str(payload.get("symbol") or ""), "symbol")
    if (entry.symbol or "") != symbol:
        raise ValueError(f"{label} symbol is invalid")
    before = payload.get("position_before")
    after = payload.get("position_after")
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        raise ValueError(f"{label} position state is invalid")

    position = projection.positions.get(symbol)
    if position is None:
        position = ProjectedPosition(symbol=symbol)
    if _projected_position_accounting_state(position) != _normalized_position_state(
        before
    ):
        raise ValueError(f"{label} position evidence drifted for {symbol}")

    cash_delta = _as_decimal(payload.get("cash_delta", "0"))
    if entry_type == LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE:
        cash_before = _as_decimal(payload.get("cash_before"))
        cash_after = _as_decimal(payload.get("cash_after"))
        if payload.get("cash_allocation") != "ordered_batch_absolute_cash_state_v1":
            raise ValueError(f"{label} cash allocation is invalid")
        if projection.cash != cash_before:
            raise ValueError(f"{label} cash evidence drifted")
        if cash_after - cash_before != cash_delta:
            raise ValueError(f"{label} cash delta is invalid")
        projection.cash = cash_after
    else:
        projection.cash += cash_delta
    deposits_delta = _as_decimal(payload.get("total_deposits_delta", "0"))
    if deposits_delta != ZERO:
        raise ValueError(f"{label} cannot change deposits")
    projection.total_deposits += deposits_delta

    normalized_after = _normalized_position_state(after)
    previous_quantity = position.quantity
    position.quantity = normalized_after["quantity"]
    position.available_qty = normalized_after["available_qty"]
    position.frozen_qty = normalized_after["frozen_qty"]
    position.avg_cost = normalized_after["avg_cost"]
    position.realized_pnl = normalized_after["realized_pnl"]
    position.commission_paid = normalized_after["commission_paid"]
    position.broker_displayed_cost_basis = normalized_after[
        "broker_displayed_cost_basis"
    ]
    position.broker_displayed_unit_cost = normalized_after["broker_displayed_unit_cost"]
    position.broker_cost_basis_difference = normalized_after[
        "broker_cost_basis_difference"
    ]
    position.broker_cost_basis_method = normalized_after["broker_cost_basis_method"]
    position.broker_cost_basis_status = normalized_after["broker_cost_basis_status"]
    if position.quantity == ZERO and previous_quantity != ZERO:
        position.closed_at = entry.timestamp
    elif position.quantity != ZERO and previous_quantity == ZERO:
        position.closed_at = None
    if position.available_qty != position.quantity - position.frozen_qty:
        raise ValueError(f"{label} availability is invalid")
    projection.positions[symbol] = position


def _projected_position_accounting_state(
    position: ProjectedPosition,
) -> dict[str, Decimal | str | None]:
    return {
        "quantity": position.quantity,
        "available_qty": position.available_qty,
        "frozen_qty": position.frozen_qty,
        "avg_cost": position.avg_cost,
        "realized_pnl": position.realized_pnl,
        "commission_paid": position.commission_paid,
        "broker_displayed_cost_basis": position.broker_displayed_cost_basis,
        "broker_displayed_unit_cost": position.broker_displayed_unit_cost,
        "broker_cost_basis_difference": position.broker_cost_basis_difference,
        "broker_cost_basis_method": position.broker_cost_basis_method,
        "broker_cost_basis_status": position.broker_cost_basis_status,
    }


def _normalized_position_state(
    raw: Mapping[str, Any],
) -> dict[str, Decimal | str | None]:
    decimal_fields = (
        "quantity",
        "available_qty",
        "frozen_qty",
        "avg_cost",
        "realized_pnl",
        "commission_paid",
        "broker_displayed_cost_basis",
        "broker_displayed_unit_cost",
        "broker_cost_basis_difference",
    )
    required = {*decimal_fields, "broker_cost_basis_method", "broker_cost_basis_status"}
    if set(raw) != required:
        raise ValueError("Ledger correction position fields are invalid")
    return {
        **{field: _as_decimal(raw[field]) for field in decimal_fields},
        "broker_cost_basis_method": (
            None
            if raw["broker_cost_basis_method"] is None
            else str(raw["broker_cost_basis_method"])
        ),
        "broker_cost_basis_status": (
            None
            if raw["broker_cost_basis_status"] is None
            else str(raw["broker_cost_basis_status"])
        ),
    }


__all__ = ["apply_projection_correction", "is_projection_correction_entry_type"]
