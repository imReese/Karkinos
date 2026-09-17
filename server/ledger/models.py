"""Ledger entry model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from server.contracts.financial_values import (
    LEGACY_REAL_BACKFILL_PROVENANCE,
    decimal_value,
)


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
    amount_decimal: str | None = None
    quantity_decimal: str | None = None
    price_decimal: str | None = None
    commission_decimal: str | None = None
    gross_amount_decimal: str | None = None
    net_cash_impact_decimal: str | None = None
    estimated_commission_decimal: str | None = None
    estimated_net_cash_impact_decimal: str | None = None
    currency_code: str | None = None
    decimal_provenance: str | None = None
    estimated_fee_breakdown: dict[str, Any] | None = None
    estimated_fee_rule_id: str | None = None
    estimated_fee_rule_version: str | None = None
    settlement_status: str | None = None
    settled_at: str | None = None
    settlement_source: str | None = None
    settlement_source_ref: str | None = None
    settlement_note: str = ""
    cost_basis_method: str | None = None
    correction_payload: dict[str, Any] | None = None
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
            amount_decimal=_as_text(row.get("amount_decimal")),
            quantity_decimal=_as_text(row.get("quantity_decimal")),
            price_decimal=_as_text(row.get("price_decimal")),
            commission_decimal=_as_text(row.get("commission_decimal")),
            gross_amount_decimal=_as_text(row.get("gross_amount_decimal")),
            net_cash_impact_decimal=_as_text(row.get("net_cash_impact_decimal")),
            estimated_commission_decimal=_as_text(
                row.get("estimated_commission_decimal")
            ),
            estimated_net_cash_impact_decimal=_as_text(
                row.get("estimated_net_cash_impact_decimal")
            ),
            currency_code=_as_text(row.get("currency_code")),
            decimal_provenance=_as_text(row.get("decimal_provenance")),
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
            correction_payload=_as_json_object(row.get("correction_payload_json")),
            asset_class=str(row.get("asset_class") or "").strip().lower(),
            note=str(row.get("note") or ""),
            source=str(row.get("source") or "manual"),
            source_ref=row.get("source_ref"),
            created_at=row.get("created_at"),
        )

    def decimal(self, field: str, *, allow_none: bool = False) -> Decimal | None:
        """Return the exact persisted financial value when v16 storage exists."""

        legacy = getattr(self, field)
        if self.decimal_provenance == LEGACY_REAL_BACKFILL_PROVENANCE:
            return decimal_value(legacy, field=field, allow_none=allow_none)
        exact_name = f"{field}_decimal"
        if hasattr(self, exact_name):
            exact = getattr(self, exact_name)
            if exact not in {None, ""}:
                return decimal_value(exact, field=field, allow_none=allow_none)
        return decimal_value(legacy, field=field, allow_none=allow_none)


def _as_text(value: object | None) -> str | None:
    if value in {None, ""}:
        return None
    return str(value)


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


def _as_json_object(value: object | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else None
