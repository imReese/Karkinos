"""Transaction-local writer for one validated controlled ledger correction."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any

from server.contracts.financial_values import (
    DEFAULT_CURRENCY_CODE,
    EXACT_DECIMAL_WRITE_PROVENANCE,
    decimal_storage_pair,
)
from server.persistence.database_serialization import normalize_timestamp
from server.persistence.event_log import (
    insert_event_sync,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)


def insert_controlled_ledger_correction(
    conn: sqlite3.Connection,
    *,
    requested: dict[str, Any],
    derived_plan: dict[str, Any],
) -> sqlite3.Row | None:
    """Append ledger, audit, and correction records on the caller transaction."""

    from server.projections.controlled_ledger_correction import (
        CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ENTRY_TYPE,
        CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE,
    )

    before = derived_plan["position_before"]
    after = derived_plan["position_after"]
    quantity_delta = Decimal(after["quantity"]) - Decimal(before["quantity"])
    effective_at = normalize_timestamp(derived_plan["effective_at"])
    correction_payload_json = _serialize_event_payload_json(derived_plan)
    amount_real, amount_decimal = decimal_storage_pair(
        derived_plan["cash_delta"], field="amount"
    )
    quantity_real, quantity_decimal = decimal_storage_pair(
        quantity_delta, field="quantity"
    )
    commission_real, commission_decimal = decimal_storage_pair(0, field="commission")
    cursor = conn.execute(
        """
        INSERT INTO ledger_entries (
            entry_type, timestamp, amount, amount_decimal, symbol, direction,
            quantity, quantity_decimal, price, price_decimal, commission,
            commission_decimal, correction_payload_json, asset_class, note,
            source, source_ref, created_at, currency_code, decimal_provenance
        ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ENTRY_TYPE,
            effective_at,
            amount_real,
            amount_decimal,
            derived_plan["symbol"],
            quantity_real,
            quantity_decimal,
            commission_real,
            commission_decimal,
            correction_payload_json,
            derived_plan["asset_class"],
            (
                "Append-only correction derived from canonical replay; "
                f"original posting {requested['posting_id']}."
            ),
            CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE,
            requested["correction_id"],
            requested["applied_at"],
            DEFAULT_CURRENCY_CODE,
            EXACT_DECIMAL_WRITE_PROVENANCE,
        ),
    )
    correction_entry_id = int(cursor.lastrowid or 0)
    stored_payload = dict(requested.get("payload") or {})
    stored_payload.update(
        {
            "correction_ledger_entry_id": correction_entry_id,
            "post_ledger_cutoff_id": correction_entry_id,
        }
    )
    insert_event_sync(
        conn,
        event_type="portfolio.ledger_entry.recorded",
        timestamp=effective_at,
        entity_type="portfolio",
        entity_id="default",
        source="ledger_entries",
        source_ref=str(correction_entry_id),
        payload={
            "entry_id": correction_entry_id,
            "entry_type": CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ENTRY_TYPE,
            "timestamp": effective_at,
            "symbol": derived_plan["symbol"],
            "source": CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE,
            "source_ref": requested["correction_id"],
            "correction_plan": derived_plan,
        },
    )
    conn.execute(
        """
        INSERT INTO controlled_submission_ledger_corrections (
            correction_id, correction_fingerprint, posting_id,
            posting_fingerprint, original_ledger_entry_ids_json,
            original_ledger_entry_fingerprint, reason_code,
            account_truth_import_run_id,
            account_truth_file_fingerprint,
            account_truth_source_fingerprint,
            account_truth_review_fingerprint,
            pre_valuation_snapshot_id, pre_valuation_as_of,
            pre_valuation_status, pre_ledger_cutoff_id,
            pre_ledger_fingerprint, plan_fingerprint, operator_id,
            operator_approval_id, status,
            correction_ledger_entry_id, post_ledger_cutoff_id,
            applied_at_epoch_ms, applied_at, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?, ?, ?, ?, ?, ?)
        """,
        (
            requested["correction_id"],
            requested["correction_fingerprint"],
            requested["posting_id"],
            requested["posting_fingerprint"],
            _serialize_event_payload_json(
                sorted(int(item) for item in requested["original_ledger_entry_ids"])
            ),
            requested["original_ledger_entry_fingerprint"],
            requested["reason_code"],
            requested["account_truth_import_run_id"],
            requested["account_truth_file_fingerprint"],
            requested["account_truth_source_fingerprint"],
            requested["account_truth_review_fingerprint"],
            requested["pre_valuation_snapshot_id"],
            requested["pre_valuation_as_of"],
            requested["pre_valuation_status"],
            int(requested["pre_ledger_cutoff_id"]),
            requested["pre_ledger_fingerprint"],
            requested["plan_fingerprint"],
            requested["operator_id"],
            requested["operator_approval_id"],
            correction_entry_id,
            correction_entry_id,
            int(requested["applied_at_epoch_ms"]),
            requested["applied_at"],
            _serialize_event_payload_json(stored_payload),
            requested["applied_at"],
        ),
    )
    insert_event_sync(
        conn,
        event_type="controlled_broker.ledger_corrected",
        timestamp=requested["applied_at"],
        entity_type="controlled_submission_ledger_correction",
        entity_id=requested["correction_id"],
        source=CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE,
        source_ref=requested["posting_id"],
        payload=stored_payload,
    )
    return conn.execute(
        """
        SELECT * FROM controlled_submission_ledger_corrections
        WHERE correction_id = ? LIMIT 1
        """,
        (requested["correction_id"],),
    ).fetchone()


__all__ = ["insert_controlled_ledger_correction"]
