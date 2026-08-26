"""Connection-scoped persistence primitives for portfolio cash-flow UoWs."""

from __future__ import annotations

import math
import sqlite3
from typing import Any

from server.contracts.portfolio_cash_flows import CashFlowWrite
from server.persistence.database_serialization import normalize_timestamp

_ENTRY_TYPE_BY_FLOW_TYPE = {
    "deposit": "cash_deposit",
    "withdraw": "cash_withdrawal",
}
_REVERSED_ENTRY_TYPE = {
    "cash_deposit": "cash_withdrawal",
    "cash_withdrawal": "cash_deposit",
}


def validate_cash_flow_write(command: CashFlowWrite) -> None:
    if not command.command_id.strip():
        raise ValueError("command_id is required")
    if not command.operator_id.strip():
        raise ValueError("operator_id is required")
    if command.flow_type not in _ENTRY_TYPE_BY_FLOW_TYPE:
        raise ValueError("flow_type must be deposit or withdraw")
    if not math.isfinite(command.amount) or command.amount <= 0:
        raise ValueError("cash-flow amount must be finite and positive")
    normalize_timestamp(command.timestamp)


def cash_flow_entry_type(flow_type: str) -> str:
    try:
        return _ENTRY_TYPE_BY_FLOW_TYPE[flow_type]
    except KeyError:
        raise ValueError("flow_type must be deposit or withdraw") from None


def reversed_cash_flow_entry_type(entry_type: str) -> str:
    try:
        return _REVERSED_ENTRY_TYPE[entry_type]
    except KeyError:
        raise RuntimeError("canonical cash-flow ledger type is invalid") from None


def insert_cash_flow_projection(
    conn: sqlite3.Connection,
    command: CashFlowWrite,
    *,
    created_at: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO cash_flows (timestamp, amount, flow_type, note, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            command.timestamp,
            command.amount,
            command.flow_type,
            command.note,
            created_at,
        ),
    )
    return int(cursor.lastrowid or 0)


def load_cash_flow_projection(
    conn: sqlite3.Connection,
    cash_flow_id: int,
) -> dict[str, Any] | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM cash_flows WHERE id = ? LIMIT 1",
        (cash_flow_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def load_cash_flow_ledger_entry(
    conn: sqlite3.Connection,
    cash_flow_id: int,
) -> dict[str, Any] | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT *
        FROM ledger_entries
        WHERE source = 'portfolio_cash_flow'
          AND source_ref = ?
          AND entry_type IN ('cash_deposit', 'cash_withdrawal')
        LIMIT 1
        """,
        (f"cash_flow:{cash_flow_id}",),
    ).fetchone()
    return dict(row) if row is not None else None


def validate_cash_flow_projection(
    cash_flow: dict[str, Any],
    ledger: dict[str, Any],
) -> None:
    checks = {
        "source": str(ledger.get("source") or "") == "portfolio_cash_flow",
        "source_ref": str(ledger.get("source_ref") or "")
        == f"cash_flow:{int(cash_flow['id'])}",
        "entry_type": str(ledger.get("entry_type") or "")
        == cash_flow_entry_type(str(cash_flow.get("flow_type") or "")),
        "timestamp": normalize_timestamp(str(ledger.get("timestamp") or ""))
        == normalize_timestamp(str(cash_flow.get("timestamp") or "")),
        "amount": float(ledger.get("amount") or 0.0)
        == float(cash_flow.get("amount") or 0.0),
        "note": str(ledger.get("note") or "") == str(cash_flow.get("note") or ""),
    }
    drifted = [field for field, matches in checks.items() if not matches]
    if drifted:
        raise RuntimeError(
            "cash-flow projection drifted from canonical ledger: " + ",".join(drifted)
        )


__all__ = [
    "cash_flow_entry_type",
    "insert_cash_flow_projection",
    "load_cash_flow_ledger_entry",
    "load_cash_flow_projection",
    "reversed_cash_flow_entry_type",
    "validate_cash_flow_projection",
    "validate_cash_flow_write",
]
