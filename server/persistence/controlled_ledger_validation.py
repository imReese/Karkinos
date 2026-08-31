"""Immutable evidence validation for controlled ledger posting transactions."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any

from server.persistence.database_normalization import stable_json_fingerprint
from server.persistence.database_serialization import (
    decimal_values_equal,
    normalize_timestamp,
)


def verify_controlled_ledger_entry(
    conn: sqlite3.Connection,
    *,
    entry: dict[str, Any],
    request: dict[str, Any],
) -> list[str]:
    """Re-check one proposed entry against immutable fill and broker evidence."""

    blockers: list[str] = []
    fill_id = str(entry.get("fill_id") or "")
    event_id = str(entry.get("broker_event_id") or "")
    row_fingerprint = str(entry.get("broker_row_fingerprint") or "")
    fill = conn.execute(
        "SELECT * FROM fills WHERE fill_id = ? LIMIT 1", (fill_id,)
    ).fetchone()
    event = conn.execute(
        """
        SELECT * FROM broker_evidence_events
        WHERE import_run_id = ? AND event_id = ? AND row_fingerprint = ?
        LIMIT 1
        """,
        (request["account_truth_import_run_id"], event_id, row_fingerprint),
    ).fetchone()
    if fill is None:
        blockers.append("controlled_ledger_posting_fill_missing")
    else:
        from server.persistence.database_normalization import json_dict

        metadata = json_dict(fill["metadata_json"])
        fill_fields = {
            "order_id": request["order_id"],
            "execution_mode": "controlled_live",
            "source": "controlled_submission_clearance",
            "fill_id": fill_id,
        }
        for field, expected in fill_fields.items():
            if str(fill[field] or "") != str(expected or ""):
                blockers.append(f"controlled_ledger_posting_fill_{field}_changed")
        if str(metadata.get("clearance_id") or "") != request["clearance_id"]:
            blockers.append("controlled_ledger_posting_fill_clearance_changed")
        if str(metadata.get("broker_event_id") or "") != event_id:
            blockers.append("controlled_ledger_posting_fill_event_changed")
        if str(metadata.get("broker_row_fingerprint") or "") != row_fingerprint:
            blockers.append("controlled_ledger_posting_fill_row_changed")
    if event is None:
        blockers.append("controlled_ledger_posting_broker_event_missing")
        return blockers

    direction = str(entry.get("direction") or "")
    if direction not in {"buy", "sell"}:
        blockers.append("controlled_ledger_posting_entry_direction_invalid")
    expected_entry_type = f"trade_{direction}"
    textual_expectations = {
        "entry_type": expected_entry_type,
        "symbol": str(event["symbol"] or ""),
        "asset_class": str(event["asset_class"] or "stock"),
        "source": "controlled_submission_ledger_posting",
        "source_ref": fill_id,
        "settlement_status": "confirmed",
        "settlement_source": "broker_statement",
        "settlement_source_ref": (
            f"{request['account_truth_import_run_id']}:{event_id}"
        ),
        "fee_rule_id": "broker_statement_exact",
        "fee_rule_version": "broker_statement_exact.v1",
        "cost_basis_method": "broker_remaining_cost",
    }
    for field, expected in textual_expectations.items():
        if str(entry.get(field) or "") != expected:
            blockers.append(f"controlled_ledger_posting_entry_{field}_changed")
    if str(event["broker_order_id"] or "") != request["broker_order_id"]:
        blockers.append("controlled_ledger_posting_event_broker_order_changed")
    if str(event["client_order_id"] or "") != request["client_order_id"]:
        blockers.append("controlled_ledger_posting_event_client_order_changed")
    if str(event["event_type"] or "") != expected_entry_type:
        blockers.append("controlled_ledger_posting_event_type_changed")

    numeric_expectations = {
        "quantity": event["quantity"],
        "price": event["price"],
        "amount": event["gross_amount"],
        "gross_amount": event["gross_amount"],
        "commission": event["fee"],
        "net_cash_impact": event["net_amount"],
    }
    for field, expected in numeric_expectations.items():
        if not decimal_values_equal(entry.get(field), expected):
            blockers.append(f"controlled_ledger_posting_entry_{field}_changed")
    if fill is not None:
        for entry_field, fill_field in (
            ("quantity", "fill_quantity"),
            ("price", "fill_price"),
            ("commission", "commission"),
        ):
            if not decimal_values_equal(entry.get(entry_field), fill[fill_field]):
                blockers.append(f"controlled_ledger_posting_fill_{fill_field}_changed")
    fee_breakdown = entry.get("fee_breakdown")
    fee_breakdown = fee_breakdown if isinstance(fee_breakdown, dict) else {}
    fee_expectations = {
        "commission": event["fee"],
        "stamp_tax": event["tax"],
        "transfer_fee": event["transfer_fee"],
        "other_fees": "0",
    }
    for field, expected in fee_expectations.items():
        if not decimal_values_equal(fee_breakdown.get(field), expected):
            blockers.append(f"controlled_ledger_posting_fee_{field}_changed")
    expected_total_fee = sum(
        (Decimal(str(event[field] or "0")) for field in ("fee", "tax", "transfer_fee")),
        Decimal("0"),
    )
    if not decimal_values_equal(fee_breakdown.get("total_fee"), expected_total_fee):
        blockers.append("controlled_ledger_posting_fee_total_changed")
    try:
        if normalize_timestamp(
            str(entry.get("timestamp") or "")
        ) != normalize_timestamp(str(event["occurred_at"] or "")):
            blockers.append("controlled_ledger_posting_entry_timestamp_changed")
        expected_settled_at = str(event["settled_at"] or event["occurred_at"] or "")
        if normalize_timestamp(
            str(entry.get("settled_at") or "")
        ) != normalize_timestamp(expected_settled_at):
            blockers.append("controlled_ledger_posting_entry_settlement_time_changed")
    except ValueError:
        blockers.append("controlled_ledger_posting_entry_timestamp_invalid")

    source_conflict = conn.execute(
        """
        SELECT id FROM ledger_entries
        WHERE (source = ? AND source_ref = ?)
           OR (settlement_source = ? AND settlement_source_ref = ?)
        LIMIT 1
        """,
        (
            entry.get("source"),
            entry.get("source_ref"),
            entry.get("settlement_source"),
            entry.get("settlement_source_ref"),
        ),
    ).fetchone()
    if source_conflict is not None:
        blockers.append("controlled_ledger_posting_entry_already_exists")
    return list(dict.fromkeys(blockers))


def account_truth_review_identity_from_connection(
    conn: sqlite3.Connection,
    *,
    import_run_id: str,
) -> dict[str, Any]:
    """Build a stable identity for current Account Truth review decisions."""

    table_exists = conn.execute("""
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'reconciliation_review_decisions'
        """).fetchone()
    if table_exists is None:
        rows: list[dict[str, Any]] = []
    else:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT import_run_id, item_key, category, symbol,
                       review_status, evidence_fingerprint, schema_version,
                       created_at, updated_at
                FROM reconciliation_review_decisions
                WHERE import_run_id = ?
                ORDER BY item_key ASC, id ASC
                """,
                (import_run_id,),
            ).fetchall()
        ]
    return {
        "import_run_id": import_run_id,
        "decision_count": len(rows),
        "fingerprint": stable_json_fingerprint(rows),
    }


__all__ = [
    "account_truth_review_identity_from_connection",
    "verify_controlled_ledger_entry",
]
