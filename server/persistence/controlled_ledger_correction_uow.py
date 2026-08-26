"""Controlled execution persistence capability: controlled_ledger_correction_uow."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.persistence.controlled_execution_access import (
    ControlledExecutionRepositoryAccess,
)
from server.persistence.controlled_execution_rejections import (
    controlled_submission_ledger_correction_rejection,
)
from server.persistence.controlled_ledger_correction_validation import (
    validate_controlled_ledger_correction,
)
from server.persistence.controlled_ledger_correction_writer import (
    insert_controlled_ledger_correction,
)


def _existing_correction_resolution(
    conn: sqlite3.Connection,
    requested: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool]:
    existing = conn.execute(
        """
            SELECT * FROM controlled_submission_ledger_corrections
            WHERE correction_id = ? OR posting_id = ?
            ORDER BY id ASC LIMIT 1
            """,
        (requested["correction_id"], requested["posting_id"]),
    ).fetchone()
    if existing is None:
        return None, False
    if (
        str(existing["correction_id"]) == requested["correction_id"]
        and str(existing["correction_fingerprint"])
        == requested["correction_fingerprint"]
        and str(existing["posting_id"]) == requested["posting_id"]
    ):
        return (
            {
                "status": "applied",
                "blockers": [],
                "reused": True,
                "correction": dict(existing),
            },
            True,
        )
    return (
        controlled_submission_ledger_correction_rejection(
            requested,
            ["controlled_ledger_correction_conflict"],
        ),
        False,
    )


class ControlledLedgerCorrectionUnitOfWorkMixin(ControlledExecutionRepositoryAccess):
    """Cohesive SQLite capability mixed into the aggregate repository."""

    def record_controlled_submission_ledger_correction_sync(
        self,
        *,
        correction: dict[str, Any],
    ) -> dict[str, Any]:
        """Re-derive and atomically append one exact correction event."""
        requested = dict(correction)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing_result, reusable = _existing_correction_resolution(
                    conn,
                    requested,
                )
                if existing_result is not None:
                    conn.commit() if reusable else conn.rollback()
                    return existing_result

                derived_plan, blockers = validate_controlled_ledger_correction(
                    conn,
                    requested=requested,
                    valuation_facts=self._valuation_facts,
                )
                if blockers:
                    conn.rollback()
                    return controlled_submission_ledger_correction_rejection(
                        requested,
                        blockers,
                    )
                saved = insert_controlled_ledger_correction(
                    conn,
                    requested=requested,
                    derived_plan=derived_plan,
                )
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
