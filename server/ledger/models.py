"""Ledger entry model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class LedgerEntry:
    """Single persisted ledger event."""

    entry_type: str
    timestamp: str
    amount: float | None = None
    symbol: str | None = None
    direction: str | None = None
    quantity: float | None = None
    price: float | None = None
    commission: float = 0.0
    gross_amount: float | None = None
    net_cash_impact: float | None = None
    fee_breakdown: dict[str, Any] | None = None
    fee_rule_id: str | None = None
    fee_rule_version: str | None = None
    estimated_commission: float | None = None
    estimated_net_cash_impact: float | None = None
    estimated_fee_breakdown: dict[str, Any] | None = None
    estimated_fee_rule_id: str | None = None
    estimated_fee_rule_version: str | None = None
    settlement_status: str | None = None
    settled_at: str | None = None
    settlement_source: str | None = None
    settlement_source_ref: str | None = None
    settlement_note: str = ""
    cost_basis_method: str | None = None
    asset_class: str = "stock"
    note: str = ""
    source: str = "manual"
    source_ref: str | None = None
    created_at: str | None = None
    id: int | None = None

    @classmethod
    def from_row(cls, row: dict[str, object]) -> "LedgerEntry":
        return cls(
            id=row.get("id"),
            entry_type=str(row["entry_type"]),
            timestamp=str(row["timestamp"]),
            amount=_as_float(row.get("amount")),
            symbol=row.get("symbol"),
            direction=row.get("direction"),
            quantity=_as_float(row.get("quantity")),
            price=_as_float(row.get("price")),
            commission=_as_float(row.get("commission")) or 0.0,
            gross_amount=_as_float(row.get("gross_amount")),
            net_cash_impact=_as_float(row.get("net_cash_impact")),
            fee_breakdown=_as_fee_breakdown(row.get("fee_breakdown_json")),
            fee_rule_id=row.get("fee_rule_id"),
            fee_rule_version=row.get("fee_rule_version"),
            estimated_commission=_as_float(row.get("estimated_commission")),
            estimated_net_cash_impact=_as_float(row.get("estimated_net_cash_impact")),
            estimated_fee_breakdown=_as_fee_breakdown(
                row.get("estimated_fee_breakdown_json")
            ),
            estimated_fee_rule_id=row.get("estimated_fee_rule_id"),
            estimated_fee_rule_version=row.get("estimated_fee_rule_version"),
            settlement_status=row.get("settlement_status"),
            settled_at=row.get("settled_at"),
            settlement_source=row.get("settlement_source"),
            settlement_source_ref=row.get("settlement_source_ref"),
            settlement_note=str(row.get("settlement_note") or ""),
            cost_basis_method=row.get("cost_basis_method"),
            asset_class=str(row.get("asset_class") or "stock"),
            note=str(row.get("note") or ""),
            source=str(row.get("source") or "manual"),
            source_ref=row.get("source_ref"),
            created_at=row.get("created_at"),
        )


def _as_float(value: object | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _as_fee_breakdown(value: object | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        return None
    return parsed
