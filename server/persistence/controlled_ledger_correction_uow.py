"""Controlled execution persistence capability: controlled_ledger_correction_uow."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any

from server.persistence.controlled_execution_access import (
    ControlledExecutionRepositoryAccess,
)
from server.persistence.database_support import (
    account_truth_review_identity_from_connection,
    controlled_submission_ledger_correction_rejection,
    json_list,
    normalize_timestamp,
    stable_json_fingerprint,
)
from server.persistence.event_log import (
    insert_event_sync,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)


class ControlledLedgerCorrectionUnitOfWorkMixin(ControlledExecutionRepositoryAccess):
    """Cohesive SQLite capability mixed into the aggregate repository."""

    def record_controlled_submission_ledger_correction_sync(
        self,
        *,
        correction: dict[str, Any],
    ) -> dict[str, Any]:
        """Re-derive and atomically append one exact correction event."""
        from server.projections.controlled_ledger_correction import (
            CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ENTRY_TYPE,
            CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE,
            build_controlled_ledger_correction_plan,
            correction_plan_fingerprint,
        )
        from server.projections.valuation_snapshot import (
            build_current_valuation_snapshot,
            ledger_identity_from_rows,
        )

        requested = dict(correction)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                        SELECT * FROM controlled_submission_ledger_corrections
                        WHERE correction_id = ? OR posting_id = ?
                        ORDER BY id ASC LIMIT 1
                        """,
                    (requested["correction_id"], requested["posting_id"]),
                ).fetchone()
                if existing is not None:
                    if (
                        str(existing["correction_id"]) == requested["correction_id"]
                        and str(existing["correction_fingerprint"])
                        == requested["correction_fingerprint"]
                        and str(existing["posting_id"]) == requested["posting_id"]
                    ):
                        conn.commit()
                        return {
                            "status": "applied",
                            "blockers": [],
                            "reused": True,
                            "correction": dict(existing),
                        }
                    conn.rollback()
                    return controlled_submission_ledger_correction_rejection(
                        requested,
                        ["controlled_ledger_correction_conflict"],
                    )

                posting = conn.execute(
                    """
                        SELECT * FROM controlled_submission_ledger_postings
                        WHERE posting_id = ? LIMIT 1
                        """,
                    (requested["posting_id"],),
                ).fetchone()
                blockers: list[str] = []
                if posting is None:
                    blockers.append("controlled_ledger_correction_posting_missing")
                else:
                    if str(posting["status"]) != "applied":
                        blockers.append("controlled_ledger_correction_posting_changed")
                    if (
                        str(posting["posting_fingerprint"])
                        != requested["posting_fingerprint"]
                    ):
                        blockers.append(
                            "controlled_ledger_correction_posting_fingerprint_changed"
                        )
                    posting_entry_ids = sorted(
                        int(item)
                        for item in json_list(posting["ledger_entry_ids_json"])
                    )
                    if posting_entry_ids != sorted(
                        int(item) for item in requested["original_ledger_entry_ids"]
                    ):
                        blockers.append(
                            "controlled_ledger_correction_original_entry_ids_changed"
                        )
                    posting_fields = {
                        "account_truth_import_run_id": "account_truth_import_run_id",
                        "account_truth_file_fingerprint": (
                            "account_truth_file_fingerprint"
                        ),
                        "account_truth_source_fingerprint": (
                            "account_truth_source_fingerprint"
                        ),
                        "account_truth_review_fingerprint": (
                            "account_truth_review_fingerprint"
                        ),
                    }
                    for request_field, posting_field in posting_fields.items():
                        if str(requested.get(request_field) or "") != str(
                            posting[posting_field] or ""
                        ):
                            blockers.append(
                                f"controlled_ledger_correction_{request_field}_changed"
                            )

                import_row = conn.execute(
                    """
                        SELECT * FROM broker_import_runs
                        WHERE import_run_id = ? LIMIT 1
                        """,
                    (requested["account_truth_import_run_id"],),
                ).fetchone()
                if import_row is None:
                    blockers.append("controlled_ledger_correction_import_missing")
                else:
                    if str(import_row["validation_status"]) != "pass":
                        blockers.append("controlled_ledger_correction_import_not_pass")
                    if (
                        str(import_row["file_fingerprint"])
                        != requested["account_truth_file_fingerprint"]
                    ):
                        blockers.append(
                            "controlled_ledger_correction_import_fingerprint_changed"
                        )
                review_identity = account_truth_review_identity_from_connection(
                    conn,
                    import_run_id=requested["account_truth_import_run_id"],
                )
                if (
                    review_identity["fingerprint"]
                    != requested["account_truth_review_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_correction_account_truth_review_changed"
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
                    blockers.append(
                        "controlled_ledger_correction_pre_ledger_cutoff_changed"
                    )
                if (
                    str(ledger_identity["ledger_fingerprint"])
                    != requested["pre_ledger_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_correction_pre_ledger_fingerprint_changed"
                    )
                current_valuation = build_current_valuation_snapshot(
                    self._valuation_facts,
                    persist=False,
                )
                valuation_fields = (
                    "snapshot_id",
                    "as_of",
                    "status",
                    "ledger_cutoff_id",
                    "ledger_fingerprint",
                )
                request_fields = {
                    "snapshot_id": "pre_valuation_snapshot_id",
                    "as_of": "pre_valuation_as_of",
                    "status": "pre_valuation_status",
                    "ledger_cutoff_id": "pre_ledger_cutoff_id",
                    "ledger_fingerprint": "pre_ledger_fingerprint",
                }
                for valuation_field in valuation_fields:
                    request_field = request_fields[valuation_field]
                    if str(current_valuation.get(valuation_field) or "") != str(
                        requested.get(request_field) or ""
                    ):
                        blockers.append(
                            "controlled_ledger_correction_pre_valuation_"
                            f"{valuation_field}_changed"
                        )

                original_ids = sorted(
                    int(item) for item in requested["original_ledger_entry_ids"]
                )
                original_rows = [
                    row
                    for row in ledger_rows
                    if int(row.get("id") or 0) in set(original_ids)
                ]
                if len(original_rows) != len(original_ids):
                    blockers.append(
                        "controlled_ledger_correction_original_entry_missing"
                    )
                if (
                    stable_json_fingerprint(original_rows)
                    != requested["original_ledger_entry_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_correction_original_entry_changed"
                    )
                try:
                    derived_plan = build_controlled_ledger_correction_plan(
                        ledger_rows=ledger_rows,
                        original_entry_ids=original_ids,
                        posting_id=requested["posting_id"],
                    )
                except ValueError as exc:
                    blockers.append(str(exc))
                    derived_plan = {}
                if derived_plan != requested.get("correction_plan"):
                    blockers.append("controlled_ledger_correction_plan_changed")
                if (
                    correction_plan_fingerprint(derived_plan)
                    != requested["plan_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_correction_plan_fingerprint_changed"
                    )
                if blockers:
                    conn.rollback()
                    return controlled_submission_ledger_correction_rejection(
                        requested,
                        blockers,
                    )

                before = derived_plan["position_before"]
                after = derived_plan["position_after"]
                quantity_delta = Decimal(after["quantity"]) - Decimal(
                    before["quantity"]
                )
                correction_payload_json = _serialize_event_payload_json(derived_plan)
                cursor = conn.execute(
                    """
                        INSERT INTO ledger_entries (
                            entry_type, timestamp, amount, symbol, direction,
                            quantity, price, commission, correction_payload_json,
                            asset_class, note, source, source_ref, created_at
                        ) VALUES (?, ?, ?, ?, NULL, ?, NULL, 0, ?, ?, ?, ?, ?, ?)
                        """,
                    (
                        CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ENTRY_TYPE,
                        normalize_timestamp(derived_plan["effective_at"]),
                        float(Decimal(derived_plan["cash_delta"])),
                        derived_plan["symbol"],
                        float(quantity_delta),
                        correction_payload_json,
                        derived_plan["asset_class"],
                        (
                            "Append-only correction derived from canonical replay; "
                            f"original posting {requested['posting_id']}."
                        ),
                        CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE,
                        requested["correction_id"],
                        requested["applied_at"],
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
                    timestamp=normalize_timestamp(derived_plan["effective_at"]),
                    entity_type="portfolio",
                    entity_id="default",
                    source="ledger_entries",
                    source_ref=str(correction_entry_id),
                    payload={
                        "entry_id": correction_entry_id,
                        "entry_type": CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ENTRY_TYPE,
                        "timestamp": normalize_timestamp(derived_plan["effective_at"]),
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
                        _serialize_event_payload_json(original_ids),
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
                saved = conn.execute(
                    """
                        SELECT * FROM controlled_submission_ledger_corrections
                        WHERE correction_id = ? LIMIT 1
                        """,
                    (requested["correction_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "applied",
                    "blockers": [],
                    "reused": False,
                    "correction": dict(saved) if saved is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
                ArithmeticError,
            ):
                conn.rollback()
                return controlled_submission_ledger_correction_rejection(
                    requested,
                    ["controlled_ledger_correction_transaction_unavailable"],
                )
