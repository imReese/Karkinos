"""Connection-scoped persistence primitives for portfolio trade UoWs."""

from __future__ import annotations

import sqlite3
from decimal import Decimal, InvalidOperation
from typing import Any

from server.contracts.ledger_mutations import (
    FEE_BREAKDOWN_KEYS,
    validate_fee_breakdown,
)
from server.contracts.portfolio_trades import ManualTradeWrite
from server.persistence.database_serialization import normalize_timestamp


def insert_trade_projection(
    conn: sqlite3.Connection,
    command: ManualTradeWrite,
    *,
    created_at: str,
) -> int:
    """Materialize the legacy ``trades`` read projection inside a UoW."""

    cursor = conn.execute(
        """
        INSERT INTO trades (
            timestamp, symbol, direction, quantity, price, commission,
            asset_class, note, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            command.timestamp,
            command.symbol,
            command.direction,
            command.quantity,
            command.price,
            command.commission,
            command.asset_class,
            command.note,
            created_at,
        ),
    )
    return int(cursor.lastrowid or 0)


def load_trade_projection(
    conn: sqlite3.Connection,
    trade_id: int,
) -> dict[str, Any] | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM trades WHERE id = ? LIMIT 1",
        (trade_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def load_trade_ledger_entry(
    conn: sqlite3.Connection,
    trade_id: int,
) -> dict[str, Any] | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT *
        FROM ledger_entries
        WHERE source = 'portfolio_trade'
          AND source_ref = ?
          AND entry_type IN ('trade_buy', 'trade_sell')
        LIMIT 1
        """,
        (f"trade:{trade_id}",),
    ).fetchone()
    return dict(row) if row is not None else None


def validate_trade_projection(
    trade: dict[str, Any],
    ledger: dict[str, Any],
) -> None:
    """Fail closed when the compatibility projection drifts from its ledger fact."""

    expected_entry_type = f"trade_{trade['direction']}"
    checks = {
        "source": str(ledger.get("source") or "") == "portfolio_trade",
        "source_ref": str(ledger.get("source_ref") or "")
        == f"trade:{int(trade['id'])}",
        "entry_type": str(ledger.get("entry_type") or "") == expected_entry_type,
        "timestamp": normalize_timestamp(str(ledger.get("timestamp") or ""))
        == normalize_timestamp(str(trade.get("timestamp") or "")),
        "symbol": str(ledger.get("symbol") or "") == str(trade.get("symbol") or ""),
        "direction": str(ledger.get("direction") or "")
        == str(trade.get("direction") or ""),
        "quantity": float(ledger.get("quantity") or 0.0)
        == float(trade.get("quantity") or 0.0),
        "price": float(ledger.get("price") or 0.0) == float(trade.get("price") or 0.0),
        "commission": float(ledger.get("commission") or 0.0)
        == float(trade.get("commission") or 0.0),
        "asset_class": str(ledger.get("asset_class") or "stock")
        == str(trade.get("asset_class") or "stock"),
    }
    drifted = [field for field, matches in checks.items() if not matches]
    if drifted:
        raise RuntimeError(
            "manual trade projection drifted from canonical ledger: "
            + ",".join(drifted)
        )


def validate_manual_trade_write(command: ManualTradeWrite) -> None:
    """Reject internally inconsistent financial values before any write."""

    if not command.command_id.strip():
        raise ValueError("command_id is required")
    if not command.operator_id.strip():
        raise ValueError("operator_id is required")
    if not command.symbol.strip():
        raise ValueError("symbol is required")
    if not command.display_name.strip():
        raise ValueError("display_name is required")
    if command.direction not in {"buy", "sell"}:
        raise ValueError("direction must be buy or sell")
    if command.quantity <= 0 or command.price <= 0:
        raise ValueError("quantity and price must be positive")
    if command.commission < 0:
        raise ValueError("commission must be non-negative")
    if not command.asset_class.strip():
        raise ValueError("asset_class is required")
    if not command.fee_rule_id.strip() or not command.fee_rule_version.strip():
        raise ValueError("fee rule identity is required")
    if not command.cost_basis_method.strip():
        raise ValueError("cost_basis_method is required")

    try:
        quantity = Decimal(str(command.quantity))
        price = Decimal(str(command.price))
        gross_amount = Decimal(str(command.gross_amount))
        net_cash_impact = Decimal(str(command.net_cash_impact))
        commission = Decimal(str(command.commission))
    except (InvalidOperation, ValueError):
        raise ValueError("fee breakdown must contain valid financial values") from None
    fee_breakdown = validate_fee_breakdown(
        command.fee_breakdown_json,
        commission=commission,
    )
    unexpected_fee_keys = set(fee_breakdown) - FEE_BREAKDOWN_KEYS
    if unexpected_fee_keys:
        raise ValueError(
            "fee breakdown contains unsupported components: "
            + ",".join(sorted(unexpected_fee_keys))
        )
    if "commission" not in fee_breakdown:
        raise ValueError("fee breakdown must include commission")
    total_fee = Decimal(str(fee_breakdown["total_fee"]))
    recorded_commission = Decimal(str(fee_breakdown["commission"]))
    financial_values = (
        total_fee,
        recorded_commission,
        quantity,
        price,
        gross_amount,
        net_cash_impact,
        commission,
    )
    if not all(value.is_finite() for value in financial_values):
        raise ValueError("manual trade financial values must be finite")
    if total_fee < 0 or recorded_commission < 0:
        raise ValueError("fee breakdown values must be non-negative")
    if not _financially_equal(recorded_commission, commission):
        raise ValueError("commission drifted from fee breakdown")
    expected_gross = quantity * price
    if not _financially_equal(gross_amount, expected_gross):
        raise ValueError("gross amount drifted from quantity and price")
    expected_cash = (
        -(expected_gross + total_fee)
        if command.direction == "buy"
        else expected_gross - total_fee
    )
    if not _financially_equal(net_cash_impact, expected_cash):
        raise ValueError("net cash impact drifted from trade economics")


def _financially_equal(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= Decimal("0.00000001")


def insert_asset_identity_if_missing(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    asset_class: str,
    display_name: str,
    created_at: str,
) -> None:
    """Persist the minimum refreshable identity without overwriting reviewed data."""

    conn.execute(
        """
        INSERT OR IGNORE INTO watchlist_assets (
            symbol, asset_class, display_name, source, created_at, updated_at
        ) VALUES (?, ?, ?, 'trade', ?, ?)
        """,
        (symbol, asset_class, display_name, created_at, created_at),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO instrument_metadata (
            symbol, asset_type, display_name, provider_symbol, source,
            fetched_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'trade', ?, ?, ?)
        """,
        (
            symbol,
            asset_class,
            display_name,
            symbol,
            created_at,
            created_at,
            created_at,
        ),
    )


def load_pending_order(
    conn: sqlite3.Connection,
    order_id: int,
) -> dict[str, Any] | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM pending_fund_orders WHERE id = ? LIMIT 1",
        (order_id,),
    ).fetchone()
    return dict(row) if row is not None else None


__all__ = [
    "insert_asset_identity_if_missing",
    "insert_trade_projection",
    "load_pending_order",
    "load_trade_ledger_entry",
    "load_trade_projection",
    "validate_trade_projection",
    "validate_manual_trade_write",
]
