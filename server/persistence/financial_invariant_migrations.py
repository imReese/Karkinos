"""Frozen v17 migration for database-enforced financial invariants."""

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


def _exact_pair_guard(field: str) -> str:
    return f"""(
        (NEW.{field} IS NULL AND NEW.{field}_decimal IS NOT NULL)
        OR
        (NEW.{field} IS NOT NULL AND (
            NEW.{field}_decimal IS NULL
            OR trim(NEW.{field}_decimal) = ''
            OR CAST(NEW.{field}_decimal AS REAL) != NEW.{field}
        ))
    )"""


def _exact_insert_trigger(table: str, fields: tuple[str, ...]) -> str:
    guards = [
        "NEW.currency_code != 'CNY'",
        "NEW.decimal_provenance != 'exact_decimal_write_v1'",
        *(_exact_pair_guard(field) for field in fields),
    ]
    condition = "\n        OR ".join(guards)
    return f"""
    CREATE TRIGGER guard_{table}_exact_insert
    BEFORE INSERT ON {table}
    WHEN {condition}
    BEGIN
        SELECT RAISE(ABORT, '{table} exact financial values required');
    END
    """


def _immutable_triggers(table: str, label: str) -> tuple[str, str]:
    return (
        f"""
        CREATE TRIGGER {table}_update_guard
        BEFORE UPDATE ON {table}
        BEGIN
            SELECT RAISE(ABORT, '{label} are append-only');
        END
        """,
        f"""
        CREATE TRIGGER {table}_delete_guard
        BEFORE DELETE ON {table}
        BEGIN
            SELECT RAISE(ABORT, '{label} are append-only');
        END
        """,
    )


_BLOCKERS = (
    (
        """
        SELECT settlement_source
        FROM ledger_entries
        WHERE settlement_source IS NOT NULL AND trim(settlement_source) != ''
          AND settlement_source_ref IS NOT NULL AND trim(settlement_source_ref) != ''
        GROUP BY settlement_source, settlement_source_ref
        HAVING COUNT(*) > 1
        LIMIT 1
        """,
        "settlement evidence is already bound to multiple ledger entries",
    ),
    (
        """
        SELECT id
        FROM ledger_entries
        WHERE coalesce(settlement_status, '') != ''
          AND NOT (
              entry_type IN ('trade_buy', 'trade_sell')
              AND settlement_status = 'confirmed'
              AND settled_at IS NOT NULL AND trim(settled_at) != ''
              AND settlement_source IS NOT NULL AND trim(settlement_source) != ''
              AND settlement_source_ref IS NOT NULL AND trim(settlement_source_ref) != ''
          )
        LIMIT 1
        """,
        "existing trade settlement state is not terminal and auditable",
    ),
    (
        """
        SELECT id
        FROM pending_fund_orders
        WHERE (confirmed_nav IS NULL) != (confirmed_quantity IS NULL)
        LIMIT 1
        """,
        "pending fund confirmation financial fields are partially populated",
    ),
)

_SETTLEMENT_EVIDENCE_INDEX = """
CREATE UNIQUE INDEX uq_ledger_entries_settlement_evidence
ON ledger_entries(settlement_source, settlement_source_ref)
WHERE settlement_source IS NOT NULL AND trim(settlement_source) != ''
  AND settlement_source_ref IS NOT NULL AND trim(settlement_source_ref) != ''
"""

_LEDGER_UPDATE_GUARD = """
CREATE TRIGGER ledger_entries_update_guard
BEFORE UPDATE ON ledger_entries
WHEN NOT (
    (OLD.settlement_status IS NULL OR OLD.settlement_status = '')
    AND OLD.entry_type IN ('trade_buy', 'trade_sell')
    AND NEW.settlement_status = 'confirmed'
    AND NEW.settled_at IS NOT NULL AND trim(NEW.settled_at) != ''
    AND NEW.settlement_source IS NOT NULL AND trim(NEW.settlement_source) != ''
    AND NEW.settlement_source_ref IS NOT NULL AND trim(NEW.settlement_source_ref) != ''
    AND NEW.commission_decimal IS NOT NULL
    AND NEW.net_cash_impact_decimal IS NOT NULL
    AND CAST(NEW.commission_decimal AS REAL) = NEW.commission
    AND CAST(NEW.net_cash_impact_decimal AS REAL) = NEW.net_cash_impact
    AND NEW.id IS OLD.id
    AND NEW.entry_type IS OLD.entry_type
    AND NEW.timestamp IS OLD.timestamp
    AND NEW.amount IS OLD.amount
    AND NEW.amount_decimal IS OLD.amount_decimal
    AND NEW.symbol IS OLD.symbol
    AND NEW.direction IS OLD.direction
    AND NEW.quantity IS OLD.quantity
    AND NEW.quantity_decimal IS OLD.quantity_decimal
    AND NEW.price IS OLD.price
    AND NEW.price_decimal IS OLD.price_decimal
    AND NEW.gross_amount IS OLD.gross_amount
    AND NEW.gross_amount_decimal IS OLD.gross_amount_decimal
    AND NEW.correction_payload_json IS OLD.correction_payload_json
    AND NEW.cost_basis_method IS OLD.cost_basis_method
    AND NEW.asset_class IS OLD.asset_class
    AND NEW.note IS OLD.note
    AND NEW.source IS OLD.source
    AND NEW.source_ref IS OLD.source_ref
    AND NEW.created_at IS OLD.created_at
    AND NEW.currency_code IS OLD.currency_code
    AND NEW.decimal_provenance IS OLD.decimal_provenance
    AND (OLD.estimated_commission IS NULL OR NEW.estimated_commission IS OLD.estimated_commission)
    AND (OLD.estimated_commission_decimal IS NULL OR NEW.estimated_commission_decimal IS OLD.estimated_commission_decimal)
    AND (OLD.estimated_net_cash_impact IS NULL OR NEW.estimated_net_cash_impact IS OLD.estimated_net_cash_impact)
    AND (OLD.estimated_net_cash_impact_decimal IS NULL OR NEW.estimated_net_cash_impact_decimal IS OLD.estimated_net_cash_impact_decimal)
    AND (OLD.estimated_fee_breakdown_json IS NULL OR NEW.estimated_fee_breakdown_json IS OLD.estimated_fee_breakdown_json)
    AND (OLD.estimated_fee_rule_id IS NULL OR NEW.estimated_fee_rule_id IS OLD.estimated_fee_rule_id)
    AND (OLD.estimated_fee_rule_version IS NULL OR NEW.estimated_fee_rule_version IS OLD.estimated_fee_rule_version)
)
BEGIN
    SELECT RAISE(ABORT, 'ledger entries are immutable except one terminal trade settlement');
END
"""

_LEDGER_DELETE_GUARD = """
CREATE TRIGGER ledger_entries_delete_guard
BEFORE DELETE ON ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'ledger entries are append-only');
END
"""

_ORDER_NUMERIC_GUARDS = (
    """
    CREATE TRIGGER orders_financial_update_guard
    BEFORE UPDATE OF quantity, quantity_decimal, price, price_decimal,
                     currency_code, decimal_provenance ON orders
    BEGIN
        SELECT RAISE(ABORT, 'order financial terms are immutable');
    END
    """,
    """
    CREATE TRIGGER manual_orders_financial_update_guard
    BEFORE UPDATE OF quantity, quantity_decimal, price, price_decimal,
                     currency_code, decimal_provenance ON manual_orders
    BEGIN
        SELECT RAISE(ABORT, 'manual order financial terms are immutable');
    END
    """,
    """
    CREATE TRIGGER oms_orders_financial_update_guard
    BEFORE UPDATE OF quantity, quantity_decimal, limit_price, limit_price_decimal,
                     currency_code, decimal_provenance ON oms_orders
    BEGIN
        SELECT RAISE(ABORT, 'OMS order financial terms are immutable');
    END
    """,
    """
    CREATE TRIGGER pending_fund_orders_base_financial_update_guard
    BEFORE UPDATE OF amount, amount_decimal, commission, commission_decimal,
                     currency_code, decimal_provenance ON pending_fund_orders
    BEGIN
        SELECT RAISE(ABORT, 'pending fund order subscription terms are immutable');
    END
    """,
    """
    CREATE TRIGGER pending_fund_orders_confirmation_update_guard
    BEFORE UPDATE OF confirmed_nav, confirmed_nav_decimal,
                     confirmed_quantity, confirmed_quantity_decimal
    ON pending_fund_orders
    WHEN NOT (
        OLD.confirmed_nav IS NULL AND OLD.confirmed_nav_decimal IS NULL
        AND OLD.confirmed_quantity IS NULL AND OLD.confirmed_quantity_decimal IS NULL
        AND NEW.status = 'confirmed'
        AND NEW.confirmed_nav IS NOT NULL AND NEW.confirmed_nav_decimal IS NOT NULL
        AND NEW.confirmed_quantity IS NOT NULL AND NEW.confirmed_quantity_decimal IS NOT NULL
        AND CAST(NEW.confirmed_nav_decimal AS REAL) = NEW.confirmed_nav
        AND CAST(NEW.confirmed_quantity_decimal AS REAL) = NEW.confirmed_quantity
    )
    BEGIN
        SELECT RAISE(ABORT, 'pending fund confirmation is one-way and exact');
    END
    """,
)


_V17_EXACT_TRIGGER_NAMES = tuple(
    f"guard_{table}_exact_insert" for table in _EXACT_TABLE_FIELDS
)
_V17_APPEND_ONLY_TABLES = (
    "cash_flows",
    "trades",
    "fills",
    "portfolio_snapshots",
    "event_log",
)
V17_SCHEMA_OBJECTS = (
    ("index", "uq_ledger_entries_settlement_evidence"),
    ("trigger", "ledger_entries_update_guard"),
    ("trigger", "ledger_entries_delete_guard"),
    *(("trigger", name) for name in _V17_EXACT_TRIGGER_NAMES),
    ("trigger", "orders_financial_update_guard"),
    ("trigger", "manual_orders_financial_update_guard"),
    ("trigger", "oms_orders_financial_update_guard"),
    ("trigger", "pending_fund_orders_base_financial_update_guard"),
    ("trigger", "pending_fund_orders_confirmation_update_guard"),
    *(
        ("trigger", f"{table}_{action}_guard")
        for table in _V17_APPEND_ONLY_TABLES
        for action in ("update", "delete")
    ),
)

_APPEND_ONLY_STATEMENTS = (
    *_immutable_triggers("cash_flows", "cash flow facts"),
    *_immutable_triggers("trades", "trade projections"),
    *_immutable_triggers("fills", "fill facts"),
    *_immutable_triggers("portfolio_snapshots", "portfolio snapshots"),
    *_immutable_triggers("event_log", "audit events"),
)

V17_FINANCIAL_INVARIANT_STATEMENTS = (
    _SETTLEMENT_EVIDENCE_INDEX,
    _LEDGER_UPDATE_GUARD,
    _LEDGER_DELETE_GUARD,
    *(
        _exact_insert_trigger(table, fields)
        for table, fields in _EXACT_TABLE_FIELDS.items()
    ),
    *_ORDER_NUMERIC_GUARDS,
    *_APPEND_ONLY_STATEMENTS,
)


def build_financial_invariant_migration(migration_factory: Callable[..., Any]) -> Any:
    return migration_factory(
        version=17,
        name="enforce_financial_fact_invariants",
        blockers=_BLOCKERS,
        statements=V17_FINANCIAL_INVARIANT_STATEMENTS,
    )


__all__ = [
    "V17_FINANCIAL_INVARIANT_STATEMENTS",
    "V17_SCHEMA_OBJECTS",
    "build_financial_invariant_migration",
]
