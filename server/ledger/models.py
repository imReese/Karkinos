"""Ledger entry model."""

from __future__ import annotations

from dataclasses import dataclass


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
