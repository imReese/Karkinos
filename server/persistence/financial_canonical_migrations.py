"""Frozen v18 migration for canonical exact-decimal write boundaries."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_EXACT_TABLE_FIELDS: dict[str, tuple[str, ...]] = {
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


def _invalid_canonical_decimal(expression: str) -> str:
    body = (
        f"(CASE WHEN substr({expression}, 1, 1) = '-' "
        f"THEN substr({expression}, 2) ELSE {expression} END)"
    )
    fractional_digits = (
        f"(CASE WHEN instr({body}, '.') = 0 THEN 0 "
        f"ELSE length({body}) - instr({body}, '.') END)"
    )
    return f"""(
        typeof({expression}) != 'text'
        OR {expression} != trim({expression})
        OR {expression} = ''
        OR {expression} GLOB '*[^0-9.-]*'
        OR instr(substr({expression}, 2), '-') > 0
        OR length({expression}) - length(replace({expression}, '-', '')) > 1
        OR length({expression}) - length(replace({expression}, '.', '')) > 1
        OR {body} = ''
        OR substr({body}, 1, 1) = '.'
        OR substr({body}, -1, 1) = '.'
        OR (
            length({body}) > 1
            AND substr({body}, 1, 1) = '0'
            AND substr({body}, 2, 1) != '.'
        )
        OR (substr({expression}, 1, 1) = '-' AND {body} = '0')
        OR (instr({body}, '.') > 0 AND substr({body}, -1, 1) = '0')
        OR length(replace({body}, '.', '')) > 38
        OR {fractional_digits} > 18
    )"""


def _insert_guard(table: str, fields: tuple[str, ...]) -> str:
    guards = [
        f"(NEW.{field}_decimal IS NOT NULL AND "
        f"{_invalid_canonical_decimal(f'NEW.{field}_decimal')})"
        for field in fields
    ]
    return f"""
    CREATE TRIGGER guard_{table}_canonical_decimal_insert
    BEFORE INSERT ON {table}
    WHEN {" OR ".join(guards)}
    BEGIN
        SELECT RAISE(ABORT, '{table} canonical financial decimals required');
    END
    """


def _update_guard(
    table: str,
    *,
    name: str,
    fields: tuple[str, ...],
    label: str,
) -> str:
    watched = ", ".join(f"{field}_decimal" for field in fields)
    guards = [
        f"(NEW.{field}_decimal IS NOT NULL AND "
        f"{_invalid_canonical_decimal(f'NEW.{field}_decimal')})"
        for field in fields
    ]
    return f"""
    CREATE TRIGGER {name}
    BEFORE UPDATE OF {watched} ON {table}
    WHEN {" OR ".join(guards)}
    BEGIN
        SELECT RAISE(ABORT, '{label} canonical financial decimals required');
    END
    """


_INSERT_TRIGGER_NAMES = tuple(
    f"guard_{table}_canonical_decimal_insert" for table in _EXACT_TABLE_FIELDS
)
_UPDATE_TRIGGER_NAMES = (
    "ledger_entries_canonical_settlement_update_guard",
    "pending_fund_orders_canonical_confirmation_update_guard",
)
V18_SCHEMA_OBJECTS = (
    *(("trigger", name) for name in _INSERT_TRIGGER_NAMES),
    *(("trigger", name) for name in _UPDATE_TRIGGER_NAMES),
)

V18_CANONICAL_FINANCIAL_STATEMENTS = (
    *(_insert_guard(table, fields) for table, fields in _EXACT_TABLE_FIELDS.items()),
    _update_guard(
        "ledger_entries",
        name="ledger_entries_canonical_settlement_update_guard",
        fields=("commission", "net_cash_impact"),
        label="ledger settlement",
    ),
    _update_guard(
        "pending_fund_orders",
        name="pending_fund_orders_canonical_confirmation_update_guard",
        fields=("confirmed_nav", "confirmed_quantity"),
        label="pending fund confirmation",
    ),
)


def build_financial_canonical_migration(migration_factory: Callable[..., Any]) -> Any:
    return migration_factory(
        version=18,
        name="enforce_canonical_financial_decimal_writes",
        statements=V18_CANONICAL_FINANCIAL_STATEMENTS,
    )


__all__ = [
    "V18_CANONICAL_FINANCIAL_STATEMENTS",
    "V18_SCHEMA_OBJECTS",
    "build_financial_canonical_migration",
]
