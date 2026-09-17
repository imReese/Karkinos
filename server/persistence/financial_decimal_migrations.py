"""Frozen v16 migration for exact financial decimal storage."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from server.contracts.financial_values import LEGACY_REAL_BACKFILL_PROVENANCE

_TABLE_FIELDS: dict[str, tuple[str, ...]] = {
    "ledger_entries": (
        "amount",
        "quantity",
        "price",
        "commission",
        "gross_amount",
        "net_cash_impact",
        "estimated_commission",
        "estimated_net_cash_impact",
    ),
    "cash_flows": ("amount",),
    "trades": ("quantity", "price", "commission"),
    "pending_fund_orders": (
        "amount",
        "commission",
        "confirmed_nav",
        "confirmed_quantity",
    ),
    "orders": ("quantity", "price"),
    "manual_orders": ("quantity", "price"),
    "oms_orders": ("quantity", "limit_price"),
    "fills": ("fill_price", "fill_quantity", "commission", "slippage"),
    "portfolio_snapshots": ("cash", "total_equity"),
}


def _statements() -> tuple[str, ...]:
    statements: list[str] = []
    for table, fields in _TABLE_FIELDS.items():
        for field in fields:
            statements.append(f"ALTER TABLE {table} ADD COLUMN {field}_decimal TEXT")
        statements.extend(
            (
                f"ALTER TABLE {table} ADD COLUMN currency_code TEXT NOT NULL "
                "DEFAULT 'CNY' CHECK(length(currency_code) = 3)",
                f"ALTER TABLE {table} ADD COLUMN decimal_provenance TEXT NOT NULL "
                f"DEFAULT '{LEGACY_REAL_BACKFILL_PROVENANCE}'",
            )
        )
        assignments = ", ".join(
            f"{field}_decimal = CASE WHEN {field} IS NULL THEN NULL ELSE CAST({field} AS TEXT) END"
            for field in fields
        )
        statements.append(f"UPDATE {table} SET {assignments}")
    return tuple(statements)


V16_EXACT_FINANCIAL_DECIMAL_STATEMENTS = _statements()


def build_financial_decimal_migration(migration_factory: Callable[..., Any]) -> Any:
    return migration_factory(
        version=16,
        name="add_exact_financial_decimal_storage",
        statements=V16_EXACT_FINANCIAL_DECIMAL_STATEMENTS,
    )


__all__ = [
    "V16_EXACT_FINANCIAL_DECIMAL_STATEMENTS",
    "build_financial_decimal_migration",
]
