from __future__ import annotations

import sqlite3

_UPDATE_GUARDS: dict[str, tuple[str, ...]] = {
    "ledger_entries": ("ledger_entries_update_guard",),
    "cash_flows": ("cash_flows_update_guard",),
    "trades": ("trades_update_guard",),
    "fills": ("fills_update_guard",),
    "orders": ("orders_financial_update_guard",),
    "manual_orders": ("manual_orders_financial_update_guard",),
    "oms_orders": ("oms_orders_financial_update_guard",),
    "pending_fund_orders": (
        "pending_fund_orders_base_financial_update_guard",
        "pending_fund_orders_confirmation_update_guard",
    ),
}


def allow_out_of_band_update(conn: sqlite3.Connection, table: str) -> None:
    """Simulate admin/disk corruption after bypassing production DB guards."""

    try:
        guards = _UPDATE_GUARDS[table]
    except KeyError as exc:
        raise ValueError(f"no corruption guard fixture for table: {table}") from exc
    for name in guards:
        conn.execute(f'DROP TRIGGER IF EXISTS "{name}"')


__all__ = ["allow_out_of_band_update"]
