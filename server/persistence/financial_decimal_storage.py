"""Runtime integrity checks for exact financial decimal persistence."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.contracts.financial_values import (
    EXACT_DECIMAL_WRITE_PROVENANCE,
    LEGACY_REAL_BACKFILL_PROVENANCE,
    decimal_text,
    decimal_value,
    real_projection_matches,
)

EXACT_FINANCIAL_FIELDS: dict[str, tuple[str, ...]] = {
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
_ALLOWED_PROVENANCE = {
    EXACT_DECIMAL_WRITE_PROVENANCE,
    LEGACY_REAL_BACKFILL_PROVENANCE,
}


def exact_decimal_storage_present(conn: sqlite3.Connection) -> bool:
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(ledger_entries)").fetchall()
    }
    return "amount_decimal" in columns and "decimal_provenance" in columns


def assert_exact_financial_storage(conn: sqlite3.Connection) -> None:
    """Fail closed on missing, invalid, or drifted exact financial values."""

    if not exact_decimal_storage_present(conn):
        return
    previous = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        for table, fields in EXACT_FINANCIAL_FIELDS.items():
            _assert_table(conn, table, fields)
    finally:
        conn.row_factory = previous


def _assert_table(
    conn: sqlite3.Connection,
    table: str,
    fields: tuple[str, ...],
) -> None:
    columns = {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    expected = {
        *(f"{field}_decimal" for field in fields),
        "currency_code",
        "decimal_provenance",
    }
    missing = expected - columns
    if missing:
        raise RuntimeError(
            f"financial_decimal_schema_incomplete:{table}:{','.join(sorted(missing))}"
        )
    for row in conn.execute(f"SELECT * FROM {table}"):
        payload = dict(row)
        row_id = payload.get("id", "?")
        if str(payload.get("currency_code") or "") != "CNY":
            raise RuntimeError(f"financial_decimal_currency_invalid:{table}:{row_id}")
        if str(payload.get("decimal_provenance") or "") not in _ALLOWED_PROVENANCE:
            raise RuntimeError(f"financial_decimal_provenance_invalid:{table}:{row_id}")
        for field in fields:
            legacy = payload.get(field)
            exact = payload.get(f"{field}_decimal")
            if legacy is None:
                if exact is not None:
                    raise RuntimeError(
                        f"financial_decimal_null_drift:{table}:{row_id}:{field}"
                    )
                continue
            if exact in {None, ""}:
                raise RuntimeError(
                    f"financial_decimal_missing:{table}:{row_id}:{field}"
                )
            try:
                decimal_value(exact, field=field)
                canonical = decimal_text(exact, field=field)
            except ValueError as exc:
                raise RuntimeError(
                    f"financial_decimal_invalid:{table}:{row_id}:{field}"
                ) from exc
            if (
                payload.get("decimal_provenance") == EXACT_DECIMAL_WRITE_PROVENANCE
                and canonical != exact
            ):
                raise RuntimeError(
                    f"financial_decimal_not_canonical:{table}:{row_id}:{field}"
                )
            if not real_projection_matches(
                payload,
                field,
                legacy_backfill=(
                    payload.get("decimal_provenance") == LEGACY_REAL_BACKFILL_PROVENANCE
                ),
            ):
                raise RuntimeError(
                    f"financial_decimal_projection_drift:{table}:{row_id}:{field}"
                )


__all__ = [
    "EXACT_FINANCIAL_FIELDS",
    "assert_exact_financial_storage",
    "exact_decimal_storage_present",
]
