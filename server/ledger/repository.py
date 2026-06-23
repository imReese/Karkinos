"""SQLite-backed ledger repository."""

from __future__ import annotations

import json

from server.db import AppDatabase

from .models import LedgerEntry


class LedgerRepository:
    """Persist and list ledger entries."""

    def __init__(self, db: AppDatabase) -> None:
        self._db = db

    def insert_entry(self, entry: LedgerEntry) -> int:
        """Persist a ledger entry and return its row id."""
        return self._db.insert_ledger_entry_sync(
            entry_type=entry.entry_type,
            timestamp=entry.timestamp,
            amount=entry.amount,
            symbol=entry.symbol,
            direction=entry.direction,
            quantity=entry.quantity,
            price=entry.price,
            commission=entry.commission,
            gross_amount=entry.gross_amount,
            net_cash_impact=entry.net_cash_impact,
            fee_breakdown_json=(
                json.dumps(entry.fee_breakdown, ensure_ascii=False, sort_keys=True)
                if entry.fee_breakdown is not None
                else None
            ),
            fee_rule_id=entry.fee_rule_id,
            fee_rule_version=entry.fee_rule_version,
            cost_basis_method=entry.cost_basis_method,
            asset_class=entry.asset_class,
            note=entry.note,
            source=entry.source,
            source_ref=entry.source_ref,
            created_at=entry.created_at,
        )

    def list_entries(self, limit: int = 50, offset: int = 0) -> list[LedgerEntry]:
        """Return persisted ledger entries, newest first."""
        rows = self._db.get_ledger_entries_sync(limit=limit, offset=offset)
        return [LedgerEntry.from_row(row) for row in rows]
