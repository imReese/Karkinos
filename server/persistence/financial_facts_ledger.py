"""Canonical portfolio-ledger persistence capability."""

from __future__ import annotations

import json
import logging
import sqlite3
from decimal import Decimal
from typing import Any

from server.persistence.database_support import json_dict, normalize_timestamp
from server.persistence.event_log import insert_event_sync

logger = logging.getLogger("server.persistence.financial_facts")


class LedgerFactsRepositoryMixin:
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
        """同步写入账本事件。"""
        normalized_timestamp = normalize_timestamp(timestamp)
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                """INSERT INTO ledger_entries
                   (entry_type, timestamp, amount, symbol, direction, quantity,
                    price, commission, gross_amount, net_cash_impact,
                    fee_breakdown_json, fee_rule_id, fee_rule_version,
                    cost_basis_method, asset_class, note, source, source_ref,
                    created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    asset_class,
                    note,
                    source,
                    source_ref,
                    created_at or self._now().isoformat(),
                ),
            )
            row_id = cursor.lastrowid or 0
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
            conn.commit()
        try:
            self._valuation_publisher()
        except Exception:
            logger.exception(
                "Ledger entry %s committed but valuation snapshot publication failed",
                row_id,
            )
        return row_id

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
        """Confirm broker-settled trade costs while preserving the estimate."""
        normalized_settled_at = normalize_timestamp(settled_at)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            current_row = conn.execute(
                "SELECT * FROM ledger_entries WHERE id = ? LIMIT 1",
                (entry_id,),
            ).fetchone()
            if current_row is None:
                raise KeyError(f"ledger entry not found: {entry_id}")

            current = dict(current_row)
            if str(current.get("entry_type") or "") not in {
                "trade_buy",
                "trade_sell",
            }:
                raise ValueError("only trade ledger entries can be settled")

            evidence_owner = conn.execute(
                """
                SELECT id
                FROM ledger_entries
                WHERE settlement_source = ?
                  AND settlement_source_ref = ?
                  AND id != ?
                LIMIT 1
                """,
                (settlement_source, settlement_source_ref, entry_id),
            ).fetchone()
            if evidence_owner is not None:
                raise ValueError(
                    "settlement evidence reference already confirms another ledger entry"
                )

            same_evidence = (
                current.get("settlement_status") == "confirmed"
                and current.get("settlement_source") == settlement_source
                and current.get("settlement_source_ref") == settlement_source_ref
            )
            same_values = (
                float(current.get("commission") or 0.0) == float(commission)
                and float(current.get("net_cash_impact") or 0.0)
                == float(net_cash_impact)
                and str(current.get("fee_breakdown_json") or "") == fee_breakdown_json
            )
            if same_evidence:
                if not same_values:
                    raise ValueError(
                        "settlement evidence reference already confirmed with different values"
                    )
                return current

            estimated_commission = current.get("estimated_commission")
            if estimated_commission is None:
                estimated_commission = current.get("commission")
            estimated_net_cash_impact = current.get("estimated_net_cash_impact")
            if estimated_net_cash_impact is None:
                estimated_net_cash_impact = current.get("net_cash_impact")
            estimated_fee_breakdown_json = current.get("estimated_fee_breakdown_json")
            if estimated_fee_breakdown_json is None:
                estimated_fee_breakdown_json = current.get("fee_breakdown_json")
            estimated_fee_rule_id = current.get("estimated_fee_rule_id")
            if estimated_fee_rule_id is None:
                estimated_fee_rule_id = current.get("fee_rule_id")
            estimated_fee_rule_version = current.get("estimated_fee_rule_version")
            if estimated_fee_rule_version is None:
                estimated_fee_rule_version = current.get("fee_rule_version")

            conn.execute(
                """
                UPDATE ledger_entries
                SET commission = ?, net_cash_impact = ?, fee_breakdown_json = ?,
                    fee_rule_id = ?, fee_rule_version = ?,
                    estimated_commission = ?, estimated_net_cash_impact = ?,
                    estimated_fee_breakdown_json = ?, estimated_fee_rule_id = ?,
                    estimated_fee_rule_version = ?, settlement_status = 'confirmed',
                    settled_at = ?, settlement_source = ?, settlement_source_ref = ?,
                    settlement_note = ?
                WHERE id = ?
                """,
                (
                    commission,
                    net_cash_impact,
                    fee_breakdown_json,
                    fee_rule_id,
                    fee_rule_version,
                    estimated_commission,
                    estimated_net_cash_impact,
                    estimated_fee_breakdown_json,
                    estimated_fee_rule_id,
                    estimated_fee_rule_version,
                    normalized_settled_at,
                    settlement_source,
                    settlement_source_ref,
                    settlement_note,
                    entry_id,
                ),
            )
            updated_row = conn.execute(
                "SELECT * FROM ledger_entries WHERE id = ? LIMIT 1",
                (entry_id,),
            ).fetchone()
            if updated_row is None:
                raise RuntimeError("settled ledger entry could not be reloaded")
            updated = dict(updated_row)
            insert_event_sync(
                conn,
                event_type="portfolio.trade_settlement.confirmed",
                timestamp=normalized_settled_at,
                entity_type="ledger_entry",
                entity_id=str(entry_id),
                source=settlement_source,
                source_ref=settlement_source_ref,
                payload={
                    "entry_id": entry_id,
                    "symbol": current.get("symbol"),
                    "direction": current.get("direction"),
                    "estimated": {
                        "commission": estimated_commission,
                        "net_cash_impact": estimated_net_cash_impact,
                        "fee_breakdown": json_dict(estimated_fee_breakdown_json),
                        "fee_rule_id": estimated_fee_rule_id,
                        "fee_rule_version": estimated_fee_rule_version,
                    },
                    "settled": {
                        "commission": commission,
                        "net_cash_impact": net_cash_impact,
                        "fee_breakdown": json_dict(fee_breakdown_json),
                        "fee_rule_id": fee_rule_id,
                        "fee_rule_version": fee_rule_version,
                    },
                    "cash_adjustment": (
                        None
                        if estimated_net_cash_impact is None
                        else float(
                            Decimal(str(net_cash_impact))
                            - Decimal(str(estimated_net_cash_impact))
                        )
                    ),
                    "settlement_note": settlement_note,
                },
            )
            conn.commit()
        try:
            self._valuation_publisher()
        except Exception:
            logger.exception(
                "Ledger settlement %s committed but valuation snapshot publication failed",
                entry_id,
            )
        return updated


__all__ = ["LedgerFactsRepositoryMixin"]
