"""Canonical portfolio-ledger persistence capability."""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal, InvalidOperation
from typing import Any

from server.contracts.content_identity import content_fingerprint
from server.contracts.ledger_mutations import (
    LedgerAppendCommand,
    LedgerEntryDraft,
    LedgerMutationResult,
    LedgerTradeSettlementCommand,
    ledger_entry_state_fingerprint,
)
from server.persistence.database_serialization import normalize_timestamp
from server.persistence.event_log import insert_event_sync


def insert_ledger_entry_on_connection(
    conn: sqlite3.Connection,
    *,
    entry_type: str,
    timestamp: str,
    amount: float | None = None,
    symbol: str | None = None,
    direction: str | None = None,
    quantity: float | None = None,
    price: float | None = None,
    commission: float = 0.0,
    gross_amount: float | None = None,
    net_cash_impact: float | None = None,
    fee_breakdown_json: str | None = None,
    fee_rule_id: str | None = None,
    fee_rule_version: str | None = None,
    cost_basis_method: str | None = None,
    correction_payload_json: str | None = None,
    asset_class: str = "stock",
    note: str = "",
    source: str = "manual",
    source_ref: str | None = None,
    created_at: str,
) -> int:
    """Insert one ledger fact and its event on the caller-owned transaction."""

    normalized_timestamp = normalize_timestamp(timestamp)
    cursor = conn.execute(
        """INSERT INTO ledger_entries
           (entry_type, timestamp, amount, symbol, direction, quantity,
            price, commission, gross_amount, net_cash_impact,
            fee_breakdown_json, fee_rule_id, fee_rule_version,
            cost_basis_method, correction_payload_json, asset_class, note,
            source, source_ref, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entry_type,
            normalized_timestamp,
            amount,
            symbol,
            direction,
            quantity,
            price,
            commission,
            gross_amount,
            net_cash_impact,
            fee_breakdown_json,
            fee_rule_id,
            fee_rule_version,
            cost_basis_method,
            correction_payload_json,
            asset_class,
            note,
            source,
            source_ref,
            created_at,
        ),
    )
    row_id = int(cursor.lastrowid or 0)
    event_payload = {
        "entry_id": row_id,
        "entry_type": entry_type,
        "timestamp": normalized_timestamp,
        "amount": amount,
        "symbol": symbol,
        "direction": direction,
        "quantity": quantity,
        "price": price,
        "commission": commission,
        "asset_class": asset_class,
        "note": note,
        "source": source,
        "source_ref": source_ref,
    }
    event_payload.update(
        {
            key: value
            for key, value in {
                "gross_amount": gross_amount,
                "net_cash_impact": net_cash_impact,
                "fee_breakdown_json": fee_breakdown_json,
                "fee_rule_id": fee_rule_id,
                "fee_rule_version": fee_rule_version,
                "cost_basis_method": cost_basis_method,
                "correction_payload_json": correction_payload_json,
            }.items()
            if value is not None
        }
    )
    insert_event_sync(
        conn,
        event_type="portfolio.ledger_entry.recorded",
        timestamp=normalized_timestamp,
        entity_type="portfolio",
        entity_id="default",
        source="ledger_entries",
        source_ref=str(row_id),
        payload=event_payload,
    )
    return row_id


class LedgerFactsRepositoryMixin:
    def append_ledger_entry_sync(
        self,
        command: LedgerAppendCommand,
    ) -> LedgerMutationResult:
        """Atomically append, audit, value, publish, or replay one request."""

        return self._ledger_mutation_uow().append(command)

    def settle_ledger_trade_sync(
        self,
        command: LedgerTradeSettlementCommand,
    ) -> LedgerMutationResult:
        """Atomically CAS-confirm, audit, value, publish, or replay settlement."""

        return self._ledger_mutation_uow().settle(command)

    def insert_ledger_entry_sync(
        self,
        *,
        entry_type: str,
        timestamp: str,
        amount: float | None = None,
        symbol: str | None = None,
        direction: str | None = None,
        quantity: float | None = None,
        price: float | None = None,
        commission: float = 0.0,
        gross_amount: float | None = None,
        net_cash_impact: float | None = None,
        fee_breakdown_json: str | None = None,
        fee_rule_id: str | None = None,
        fee_rule_version: str | None = None,
        cost_basis_method: str | None = None,
        asset_class: str = "stock",
        note: str = "",
        source: str = "manual",
        source_ref: str | None = None,
        created_at: str | None = None,
    ) -> int:
        """Internal compatibility adapter onto the typed atomic append UoW."""

        if entry_type == "cash":
            entry_type = "cash_deposit"
        created_at_value = created_at or self._now().isoformat()
        (
            amount,
            direction,
            gross_amount,
            net_cash_impact,
        ) = _legacy_trade_defaults(
            entry_type=entry_type,
            amount=amount,
            direction=direction,
            quantity=quantity,
            price=price,
            commission=commission,
            gross_amount=gross_amount,
            net_cash_impact=net_cash_impact,
            fee_breakdown_json=fee_breakdown_json,
        )
        if entry_type in {
            "cash_deposit",
            "cash_interest",
            "cash_withdrawal",
            "fee",
        }:
            asset_class = "cash"
        entry = LedgerEntryDraft(
            entry_type=entry_type,
            timestamp=timestamp,
            amount=amount,
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            price=price,
            commission=commission,
            gross_amount=gross_amount,
            net_cash_impact=net_cash_impact,
            fee_breakdown_json=fee_breakdown_json,
            fee_rule_id=fee_rule_id,
            fee_rule_version=fee_rule_version,
            cost_basis_method=cost_basis_method,
            asset_class=asset_class,
            note=note,
            source=source,
            source_ref=source_ref,
            created_at=created_at_value,
        )
        command = LedgerAppendCommand(
            operator_id="internal-ledger-adapter",
            request_id=_legacy_append_request_id(entry),
            entry=entry,
        )
        result = self.append_ledger_entry_sync(command)
        return int(result.entry["id"])

    def get_ledger_entries_sync(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """同步列出账本事件，最新优先。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT *
                   FROM ledger_entries
                   ORDER BY timestamp DESC, id DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_ledger_entry_sync(self, entry_id: int) -> dict[str, Any] | None:
        """Read one ledger event by id."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM ledger_entries WHERE id = ? LIMIT 1",
                (entry_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def confirm_ledger_trade_settlement_sync(
        self,
        *,
        entry_id: int,
        commission: float,
        net_cash_impact: float,
        fee_breakdown_json: str,
        settled_at: str,
        settlement_source: str,
        settlement_source_ref: str,
        settlement_note: str = "",
        fee_rule_id: str = "broker_settlement_confirmation",
        fee_rule_version: str = "broker_settlement_confirmation.v1",
    ) -> dict[str, Any]:
        """Internal compatibility adapter onto the typed settlement UoW."""

        request_id = _legacy_settlement_request_id(
            settlement_source=settlement_source,
            settlement_source_ref=settlement_source_ref,
        )
        uow = self._ledger_mutation_uow()
        stored_request = uow.load_claim_request(request_id)
        if stored_request is None:
            current = self.get_ledger_entry_sync(entry_id)
            if current is None:
                raise KeyError(f"ledger entry not found: {entry_id}")
            expected_entry_fingerprint = ledger_entry_state_fingerprint(current)
        else:
            expected_entry_fingerprint = str(
                stored_request.get("expected_entry_fingerprint") or ""
            )
        result = uow.settle(
            LedgerTradeSettlementCommand(
                operator_id="internal-ledger-adapter",
                request_id=request_id,
                entry_id=entry_id,
                expected_entry_fingerprint=expected_entry_fingerprint,
                commission=commission,
                net_cash_impact=net_cash_impact,
                fee_breakdown_json=fee_breakdown_json,
                settled_at=settled_at,
                settlement_source=settlement_source,
                settlement_source_ref=settlement_source_ref,
                settlement_note=settlement_note,
                fee_rule_id=fee_rule_id,
                fee_rule_version=fee_rule_version,
            )
        )
        return result.entry

    def _ledger_mutation_uow(self):
        from server.persistence.ledger_mutation_uow import LedgerMutationUnitOfWork

        return LedgerMutationUnitOfWork(
            self._path,
            now=lambda: self._now().isoformat(),
            ledger_entry_inserter=insert_ledger_entry_on_connection,
            valuation_transaction_writer=self._valuation_transaction_writer,
        )


def _legacy_append_request_id(entry: LedgerEntryDraft) -> str:
    identity: dict[str, Any]
    if entry.source_ref:
        identity = {"source": entry.source, "source_ref": entry.source_ref}
    else:
        identity = entry.to_dict()
    return f"internal-ledger-append-{content_fingerprint(identity)}"


def _legacy_settlement_request_id(
    *, settlement_source: str, settlement_source_ref: str
) -> str:
    return "internal-ledger-settlement-" + content_fingerprint(
        {
            "settlement_source": settlement_source,
            "settlement_source_ref": settlement_source_ref,
        }
    )


def _legacy_trade_defaults(
    *,
    entry_type: str,
    amount: float | None,
    direction: str | None,
    quantity: float | None,
    price: float | None,
    commission: float,
    gross_amount: float | None,
    net_cash_impact: float | None,
    fee_breakdown_json: str | None,
) -> tuple[float | None, str | None, float | None, float | None]:
    if entry_type not in {"trade_buy", "trade_sell"}:
        return amount, direction, gross_amount, net_cash_impact
    expected_direction = entry_type.removeprefix("trade_")
    direction = direction or expected_direction
    if quantity is None or price is None:
        return amount, direction, gross_amount, net_cash_impact
    calculated_gross = Decimal(str(quantity)) * Decimal(str(price))
    gross_amount = float(calculated_gross) if gross_amount is None else gross_amount
    amount = gross_amount if amount is None else amount
    if net_cash_impact is None:
        fee_total = _legacy_fee_total(fee_breakdown_json, commission=commission)
        gross = Decimal(str(gross_amount))
        net_cash_impact = float(
            -(gross + fee_total) if expected_direction == "buy" else gross - fee_total
        )
    return amount, direction, gross_amount, net_cash_impact


def _legacy_fee_total(value: str | None, *, commission: float) -> Decimal:
    fallback = Decimal(str(commission))
    if value is None:
        return fallback
    try:
        payload = json.loads(value)
        total = Decimal(str(payload["total_fee"]))
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return fallback
    return total if total.is_finite() else fallback


__all__ = ["LedgerFactsRepositoryMixin", "insert_ledger_entry_on_connection"]
