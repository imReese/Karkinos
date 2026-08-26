"""SQLite-backed ledger repository."""

from __future__ import annotations

from server.contracts.content_identity import canonical_json
from server.contracts.ledger_mutations import (
    LedgerAppendCommand,
    LedgerMutationResult,
    LedgerTradeSettlementCommand,
)
from server.db import AppDatabase

from .models import LedgerEntry


class LedgerRepository:
    """Persist and list ledger entries."""

    def __init__(self, db: AppDatabase) -> None:
        self._db = db

    def append_entry(self, command: LedgerAppendCommand) -> LedgerMutationResult:
        """Append or replay one operator-authored ledger command."""

        return self._db.append_ledger_entry_sync(command)

    def insert_entry(self, entry: LedgerEntry) -> int:
        """Internal compatibility adapter onto the typed atomic ledger UoW."""

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
                canonical_json(entry.fee_breakdown)
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

    def get_entry(self, entry_id: int) -> LedgerEntry | None:
        """Return one persisted ledger entry."""
        row = self._db.get_ledger_entry_sync(entry_id)
        return LedgerEntry.from_row(row) if row is not None else None

    def settle_trade(
        self,
        command: LedgerTradeSettlementCommand,
    ) -> LedgerMutationResult:
        """CAS-confirm or replay one broker settlement command."""

        return self._db.settle_ledger_trade_sync(command)

    def confirm_trade_settlement(
        self,
        *,
        entry_id: int,
        commission: float,
        net_cash_impact: float,
        fee_breakdown: dict[str, str],
        settled_at: str,
        settlement_source: str,
        settlement_source_ref: str,
        settlement_note: str = "",
    ) -> LedgerEntry:
        """Internal compatibility adapter onto the typed settlement UoW."""

        row = self._db.confirm_ledger_trade_settlement_sync(
            entry_id=entry_id,
            commission=commission,
            net_cash_impact=net_cash_impact,
            fee_breakdown_json=canonical_json(fee_breakdown),
            settled_at=settled_at,
            settlement_source=settlement_source,
            settlement_source_ref=settlement_source_ref,
            settlement_note=settlement_note,
        )
        return LedgerEntry.from_row(row)
