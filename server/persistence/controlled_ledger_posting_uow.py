"""Controlled execution persistence capability: controlled_ledger_posting_uow."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any

from server.persistence.controlled_execution_access import (
    ControlledExecutionRepositoryAccess,
)
from server.persistence.database_support import (
    account_truth_review_identity_from_connection,
    controlled_lifecycle_invalidated_clearance_rows,
    controlled_submission_ledger_posting_rejection,
    normalize_timestamp,
    serialize_metadata_json,
    stable_json_fingerprint,
    verify_controlled_ledger_entry,
)
from server.persistence.event_log import (
    insert_event_sync,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)


class ControlledLedgerPostingUnitOfWorkMixin(ControlledExecutionRepositoryAccess):
    """Cohesive SQLite capability mixed into the aggregate repository."""

    def record_controlled_submission_ledger_posting_sync(
        self,
        *,
        posting: dict[str, Any],
    ) -> dict[str, Any]:
        """Verify and atomically post exact cleared fills to the ledger once."""
        requested = dict(posting)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                return _record_controlled_ledger_posting_transaction(
                    conn,
                    requested,
                )
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
                ArithmeticError,
            ):
                conn.rollback()
                return controlled_submission_ledger_posting_rejection(
                    requested,
                    ["controlled_ledger_posting_transaction_unavailable"],
                )


def _record_controlled_ledger_posting_transaction(
    conn: sqlite3.Connection,
    requested: dict[str, Any],
) -> dict[str, Any]:
    existing = conn.execute(
        """
            SELECT * FROM controlled_submission_ledger_postings
            WHERE posting_id = ? OR clearance_id = ?
               OR submit_intent_id = ? OR order_id = ?
            ORDER BY id ASC LIMIT 1
            """,
        (
            requested["posting_id"],
            requested["clearance_id"],
            requested["submit_intent_id"],
            requested["order_id"],
        ),
    ).fetchone()
    if existing is not None:
        if (
            str(existing["posting_id"]) == requested["posting_id"]
            and str(existing["posting_fingerprint"]) == requested["posting_fingerprint"]
            and str(existing["clearance_id"]) == requested["clearance_id"]
        ):
            conn.commit()
            return {
                "status": "applied",
                "blockers": [],
                "reused": True,
                "posting": dict(existing),
            }
        conn.rollback()
        return controlled_submission_ledger_posting_rejection(
            requested,
            ["controlled_ledger_posting_conflict"],
        )

    clearance = conn.execute(
        """
            SELECT * FROM controlled_submission_reconciliation_clearances
            WHERE clearance_id = ? LIMIT 1
            """,
        (requested["clearance_id"],),
    ).fetchone()
    intent = conn.execute(
        """
            SELECT * FROM controlled_broker_submit_intents
            WHERE submit_intent_id = ? LIMIT 1
            """,
        (requested["submit_intent_id"],),
    ).fetchone()
    order = conn.execute(
        "SELECT * FROM oms_orders WHERE order_id = ? LIMIT 1",
        (requested["order_id"],),
    ).fetchone()
    latest_item = conn.execute(
        """
            SELECT * FROM execution_reconciliation_items
            WHERE order_id = ? ORDER BY id DESC LIMIT 1
            """,
        (requested["order_id"],),
    ).fetchone()
    blockers: list[str] = []
    if clearance is None:
        blockers.append("controlled_ledger_posting_clearance_missing")
    else:
        clearance_fields = {
            "clearance_fingerprint": "clearance_fingerprint",
            "submit_intent_id": "submit_intent_id",
            "order_id": "order_id",
            "broker_order_id": "broker_order_id",
            "terminal_status": "terminal_status",
            "clearance_reconciliation_run_id": ("clearance_reconciliation_run_id"),
            "broker_evidence_fingerprint": ("broker_evidence_fingerprint"),
            "account_truth_import_run_id": ("account_truth_import_run_id"),
            "account_truth_file_fingerprint": ("account_truth_file_fingerprint"),
            "account_truth_source_fingerprint": ("account_truth_source_fingerprint"),
            "lifecycle_observation_id": "lifecycle_observation_id",
            "lifecycle_evidence_fingerprint": ("lifecycle_evidence_fingerprint"),
            "lifecycle_source_sequence": "lifecycle_source_sequence",
            "operator_id": "operator_id",
        }
        for request_field, clearance_field in clearance_fields.items():
            if str(requested.get(request_field) or "") != str(
                clearance[clearance_field] or ""
            ):
                blockers.append(
                    "controlled_ledger_posting_clearance_" f"{request_field}_changed"
                )
        if str(clearance["status"]) != "cleared":
            blockers.append("controlled_ledger_posting_clearance_not_cleared")
    if intent is None:
        blockers.append("controlled_ledger_posting_intent_missing")
    else:
        if str(intent["status"]) != "submitted":
            blockers.append("controlled_ledger_posting_intent_changed")
        if str(intent["order_id"]) != requested["order_id"]:
            blockers.append("controlled_ledger_posting_intent_order_changed")
        if str(intent["broker_order_id"]) != requested["broker_order_id"]:
            blockers.append("controlled_ledger_posting_intent_broker_order_changed")
        if str(intent["client_order_id"]) != requested["client_order_id"]:
            blockers.append("controlled_ledger_posting_intent_client_order_changed")
    if order is None:
        blockers.append("controlled_ledger_posting_order_missing")
    elif str(order["status"]) != requested["terminal_status"]:
        blockers.append("controlled_ledger_posting_order_status_changed")
    if latest_item is None:
        blockers.append("controlled_ledger_posting_reconciliation_missing")
    else:
        if str(latest_item["run_id"]) != requested["clearance_reconciliation_run_id"]:
            blockers.append("controlled_ledger_posting_reconciliation_superseded")
        if str(latest_item["item_status"]) != (
            "controlled_submission_reconciliation_cleared"
        ):
            blockers.append("controlled_ledger_posting_reconciliation_changed")

    invalidated = controlled_lifecycle_invalidated_clearance_rows(conn)
    if any(
        str(item.get("order_id") or "") == requested["order_id"] for item in invalidated
    ):
        blockers.append("controlled_ledger_posting_lifecycle_clearance_invalidated")

    import_row = conn.execute(
        """
            SELECT * FROM broker_import_runs
            WHERE import_run_id = ? LIMIT 1
            """,
        (requested["account_truth_import_run_id"],),
    ).fetchone()
    if import_row is None:
        blockers.append("controlled_ledger_posting_import_missing")
    else:
        if str(import_row["validation_status"]) != "pass":
            blockers.append("controlled_ledger_posting_import_not_pass")
        if (
            str(import_row["file_fingerprint"])
            != requested["account_truth_file_fingerprint"]
        ):
            blockers.append("controlled_ledger_posting_import_fingerprint_changed")
    review_identity = account_truth_review_identity_from_connection(
        conn,
        import_run_id=requested["account_truth_import_run_id"],
    )
    if review_identity["fingerprint"] != requested["account_truth_review_fingerprint"]:
        blockers.append("controlled_ledger_posting_account_truth_review_changed")

    from server.projections.valuation_snapshot import (
        ledger_identity_from_rows,
    )

    ledger_rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM ledger_entries ORDER BY id ASC"
        ).fetchall()
    ]
    ledger_identity = ledger_identity_from_rows(ledger_rows)
    if int(ledger_identity["ledger_cutoff_id"]) != int(
        requested["pre_ledger_cutoff_id"]
    ):
        blockers.append("controlled_ledger_posting_pre_ledger_cutoff_changed")
    if (
        str(ledger_identity["ledger_fingerprint"])
        != requested["pre_ledger_fingerprint"]
    ):
        blockers.append("controlled_ledger_posting_pre_ledger_fingerprint_changed")

    entries = requested.get("ledger_entries")
    entries = entries if isinstance(entries, list) else []
    if len(entries) != int(requested["ledger_entry_count"]):
        blockers.append("controlled_ledger_posting_entry_count_changed")
    if stable_json_fingerprint(entries) != requested["ledger_entry_fingerprint"]:
        blockers.append("controlled_ledger_posting_entry_fingerprint_changed")
    clearance_fill_count = int(clearance["fill_count"]) if clearance is not None else -1
    if len(entries) != clearance_fill_count:
        blockers.append("controlled_ledger_posting_clearance_fill_changed")
    if requested["terminal_status"] == "filled" and not entries:
        blockers.append("controlled_ledger_posting_filled_without_entries")

    verified_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            blockers.append("controlled_ledger_posting_entry_invalid")
            continue
        entry_blockers = verify_controlled_ledger_entry(
            conn,
            entry=entry,
            request=requested,
        )
        blockers.extend(entry_blockers)
        verified_entries.append(entry)
    if blockers:
        conn.rollback()
        return controlled_submission_ledger_posting_rejection(
            requested,
            blockers,
        )

    return _persist_controlled_ledger_posting(
        conn,
        requested,
        verified_entries,
    )


def _persist_controlled_ledger_posting(
    conn: sqlite3.Connection,
    requested: dict[str, Any],
    verified_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    ledger_entry_ids: list[int] = []
    for entry in verified_entries:
        normalized_timestamp = normalize_timestamp(entry["timestamp"])
        cursor = conn.execute(
            """
                INSERT INTO ledger_entries (
                    entry_type, timestamp, amount, symbol, direction,
                    quantity, price, commission, gross_amount,
                    net_cash_impact, fee_breakdown_json, fee_rule_id,
                    fee_rule_version, settlement_status, settled_at,
                    settlement_source, settlement_source_ref,
                    settlement_note, cost_basis_method, asset_class,
                    note, source, source_ref, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
            (
                entry["entry_type"],
                normalized_timestamp,
                float(Decimal(entry["amount"])),
                entry["symbol"],
                entry["direction"],
                float(Decimal(entry["quantity"])),
                float(Decimal(entry["price"])),
                float(Decimal(entry["commission"])),
                float(Decimal(entry["gross_amount"])),
                float(Decimal(entry["net_cash_impact"])),
                serialize_metadata_json(entry["fee_breakdown"]),
                entry["fee_rule_id"],
                entry["fee_rule_version"],
                entry["settlement_status"],
                normalize_timestamp(entry["settled_at"]),
                entry["settlement_source"],
                entry["settlement_source_ref"],
                entry["settlement_note"],
                entry["cost_basis_method"],
                entry["asset_class"],
                entry["note"],
                entry["source"],
                entry["source_ref"],
                requested["applied_at"],
            ),
        )
        entry_id = int(cursor.lastrowid or 0)
        ledger_entry_ids.append(entry_id)
        insert_event_sync(
            conn,
            event_type="portfolio.ledger_entry.recorded",
            timestamp=normalized_timestamp,
            entity_type="portfolio",
            entity_id="default",
            source="ledger_entries",
            source_ref=str(entry_id),
            payload={"entry_id": entry_id, **entry},
        )

    post_cutoff_id = (
        ledger_entry_ids[-1]
        if ledger_entry_ids
        else int(requested["pre_ledger_cutoff_id"])
    )
    stored_payload = dict(requested.get("payload") or {})
    stored_payload.update(
        {
            "ledger_entry_ids": ledger_entry_ids,
            "post_ledger_cutoff_id": post_cutoff_id,
        }
    )
    conn.execute(
        """
            INSERT INTO controlled_submission_ledger_postings (
                posting_id, posting_fingerprint, clearance_id,
                clearance_fingerprint, submit_intent_id, order_id,
                broker_order_id, client_order_id, terminal_status,
                clearance_reconciliation_run_id,
                broker_evidence_fingerprint,
                account_truth_import_run_id,
                account_truth_file_fingerprint,
                account_truth_source_fingerprint,
                account_truth_review_fingerprint,
                lifecycle_observation_id,
                lifecycle_evidence_fingerprint,
                lifecycle_source_sequence, pre_valuation_snapshot_id,
                pre_valuation_as_of, pre_valuation_status,
                pre_ledger_cutoff_id, pre_ledger_fingerprint,
                operator_id, operator_approval_id, status,
                ledger_entry_count, ledger_entry_fingerprint,
                ledger_entry_ids_json, post_ledger_cutoff_id,
                applied_at_epoch_ms, applied_at, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
        (
            requested["posting_id"],
            requested["posting_fingerprint"],
            requested["clearance_id"],
            requested["clearance_fingerprint"],
            requested["submit_intent_id"],
            requested["order_id"],
            requested["broker_order_id"],
            requested["client_order_id"],
            requested["terminal_status"],
            requested["clearance_reconciliation_run_id"],
            requested["broker_evidence_fingerprint"],
            requested["account_truth_import_run_id"],
            requested["account_truth_file_fingerprint"],
            requested["account_truth_source_fingerprint"],
            requested["account_truth_review_fingerprint"],
            requested["lifecycle_observation_id"],
            requested["lifecycle_evidence_fingerprint"],
            int(requested["lifecycle_source_sequence"]),
            requested["pre_valuation_snapshot_id"],
            requested["pre_valuation_as_of"],
            requested["pre_valuation_status"],
            int(requested["pre_ledger_cutoff_id"]),
            requested["pre_ledger_fingerprint"],
            requested["operator_id"],
            requested["operator_approval_id"],
            len(ledger_entry_ids),
            requested["ledger_entry_fingerprint"],
            _serialize_event_payload_json(ledger_entry_ids),
            post_cutoff_id,
            int(requested["applied_at_epoch_ms"]),
            requested["applied_at"],
            _serialize_event_payload_json(stored_payload),
            requested["applied_at"],
        ),
    )
    insert_event_sync(
        conn,
        event_type="controlled_broker.ledger_posted",
        timestamp=requested["applied_at"],
        entity_type="controlled_submission_ledger_posting",
        entity_id=requested["posting_id"],
        source="controlled_submission_ledger_posting",
        source_ref=requested["clearance_id"],
        payload=stored_payload,
    )
    saved = conn.execute(
        """
            SELECT * FROM controlled_submission_ledger_postings
            WHERE posting_id = ? LIMIT 1
            """,
        (requested["posting_id"],),
    ).fetchone()
    conn.commit()
    return {
        "status": "applied",
        "blockers": [],
        "reused": False,
        "posting": dict(saved) if saved is not None else {},
    }
