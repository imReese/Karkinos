"""Immutable evidence validation for controlled ledger corrections."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.persistence.controlled_ledger_validation import (
    account_truth_review_identity_from_connection,
)
from server.persistence.database_normalization import json_list, stable_json_fingerprint


def validate_controlled_ledger_correction(
    conn: sqlite3.Connection,
    *,
    requested: dict[str, Any],
    valuation_facts: Any,
) -> tuple[dict[str, Any], list[str]]:
    """Re-derive one correction plan from immutable transaction-local facts."""

    blockers: list[str] = []
    posting = conn.execute(
        """
        SELECT * FROM controlled_submission_ledger_postings
        WHERE posting_id = ? LIMIT 1
        """,
        (requested["posting_id"],),
    ).fetchone()
    blockers.extend(_posting_blockers(posting, requested=requested))
    blockers.extend(_account_truth_blockers(conn, requested=requested))

    ledger_rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM ledger_entries ORDER BY id ASC"
        ).fetchall()
    ]
    blockers.extend(
        _pre_valuation_blockers(
            ledger_rows,
            requested=requested,
            valuation_facts=valuation_facts,
        )
    )
    derived_plan, plan_blockers = _derive_plan(
        ledger_rows,
        requested=requested,
    )
    blockers.extend(plan_blockers)
    return derived_plan, list(dict.fromkeys(blockers))


def _posting_blockers(
    posting: sqlite3.Row | None,
    *,
    requested: dict[str, Any],
) -> list[str]:
    if posting is None:
        return ["controlled_ledger_correction_posting_missing"]
    blockers: list[str] = []
    if str(posting["status"]) != "applied":
        blockers.append("controlled_ledger_correction_posting_changed")
    if str(posting["posting_fingerprint"]) != requested["posting_fingerprint"]:
        blockers.append("controlled_ledger_correction_posting_fingerprint_changed")
    posting_entry_ids = sorted(
        int(item) for item in json_list(posting["ledger_entry_ids_json"])
    )
    if posting_entry_ids != sorted(
        int(item) for item in requested["original_ledger_entry_ids"]
    ):
        blockers.append("controlled_ledger_correction_original_entry_ids_changed")
    posting_fields = {
        "account_truth_import_run_id": "account_truth_import_run_id",
        "account_truth_file_fingerprint": "account_truth_file_fingerprint",
        "account_truth_source_fingerprint": "account_truth_source_fingerprint",
        "account_truth_review_fingerprint": "account_truth_review_fingerprint",
    }
    for request_field, posting_field in posting_fields.items():
        if str(requested.get(request_field) or "") != str(posting[posting_field] or ""):
            blockers.append(f"controlled_ledger_correction_{request_field}_changed")
    return blockers


def _account_truth_blockers(
    conn: sqlite3.Connection,
    *,
    requested: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
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
            blockers.append("controlled_ledger_correction_import_fingerprint_changed")
    review_identity = account_truth_review_identity_from_connection(
        conn,
        import_run_id=requested["account_truth_import_run_id"],
    )
    if review_identity["fingerprint"] != requested["account_truth_review_fingerprint"]:
        blockers.append("controlled_ledger_correction_account_truth_review_changed")
    return blockers


def _pre_valuation_blockers(
    ledger_rows: list[dict[str, Any]],
    *,
    requested: dict[str, Any],
    valuation_facts: Any,
) -> list[str]:
    from server.projections.valuation_snapshot import (
        build_current_valuation_snapshot,
        ledger_identity_from_rows,
    )

    blockers: list[str] = []
    ledger_identity = ledger_identity_from_rows(ledger_rows)
    if int(ledger_identity["ledger_cutoff_id"]) != int(
        requested["pre_ledger_cutoff_id"]
    ):
        blockers.append("controlled_ledger_correction_pre_ledger_cutoff_changed")
    if (
        str(ledger_identity["ledger_fingerprint"])
        != requested["pre_ledger_fingerprint"]
    ):
        blockers.append("controlled_ledger_correction_pre_ledger_fingerprint_changed")
    current_valuation = build_current_valuation_snapshot(valuation_facts)
    request_fields = {
        "snapshot_id": "pre_valuation_snapshot_id",
        "as_of": "pre_valuation_as_of",
        "status": "pre_valuation_status",
        "ledger_cutoff_id": "pre_ledger_cutoff_id",
        "ledger_fingerprint": "pre_ledger_fingerprint",
    }
    for valuation_field, request_field in request_fields.items():
        if str(current_valuation.get(valuation_field) or "") != str(
            requested.get(request_field) or ""
        ):
            blockers.append(
                "controlled_ledger_correction_pre_valuation_"
                f"{valuation_field}_changed"
            )
    return blockers


def _derive_plan(
    ledger_rows: list[dict[str, Any]],
    *,
    requested: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    from server.projections.controlled_ledger_correction import (
        build_controlled_ledger_correction_plan,
        correction_plan_fingerprint,
    )

    blockers: list[str] = []
    original_ids = sorted(int(item) for item in requested["original_ledger_entry_ids"])
    original_id_set = set(original_ids)
    original_rows = [
        row for row in ledger_rows if int(row.get("id") or 0) in original_id_set
    ]
    if len(original_rows) != len(original_ids):
        blockers.append("controlled_ledger_correction_original_entry_missing")
    if (
        stable_json_fingerprint(original_rows)
        != requested["original_ledger_entry_fingerprint"]
    ):
        blockers.append("controlled_ledger_correction_original_entry_changed")
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
    if correction_plan_fingerprint(derived_plan) != requested["plan_fingerprint"]:
        blockers.append("controlled_ledger_correction_plan_fingerprint_changed")
    return derived_plan, blockers


__all__ = ["validate_controlled_ledger_correction"]
