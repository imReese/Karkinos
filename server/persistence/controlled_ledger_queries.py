"""Controlled execution persistence capability: controlled_ledger_queries."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.persistence.controlled_execution_access import (
    ControlledExecutionRepositoryAccess,
)
from server.persistence.controlled_ledger_validation import (
    account_truth_review_identity_from_connection,
)


class ControlledLedgerQueryRepositoryMixin(ControlledExecutionRepositoryAccess):
    """Cohesive SQLite capability mixed into the aggregate repository."""

    def get_controlled_submission_reconciliation_clearance_sync(
        self,
        clearance_id: str,
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                    SELECT *
                    FROM controlled_submission_reconciliation_clearances
                    WHERE clearance_id = ? LIMIT 1
                    """,
                (clearance_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_controlled_submission_reconciliation_clearance_for_intent_sync(
        self,
        submit_intent_id: str,
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                    SELECT *
                    FROM controlled_submission_reconciliation_clearances
                    WHERE submit_intent_id = ? LIMIT 1
                    """,
                (submit_intent_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_submission_reconciliation_clearances_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                    SELECT *
                    FROM controlled_submission_reconciliation_clearances
                    ORDER BY cleared_at_epoch_ms DESC, id DESC
                    LIMIT ?
                    """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_controlled_submission_ledger_posting_sync(
        self,
        posting_id: str,
    ) -> dict[str, Any] | None:
        """Read one immutable controlled-order ledger posting."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                    SELECT * FROM controlled_submission_ledger_postings
                    WHERE posting_id = ? LIMIT 1
                    """,
                (posting_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_account_truth_review_identity_sync(
        self,
        import_run_id: str,
    ) -> dict[str, Any]:
        """Fingerprint current manual-review decisions for one broker import."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            return account_truth_review_identity_from_connection(
                conn,
                import_run_id=import_run_id,
            )

    def get_controlled_submission_ledger_posting_for_clearance_sync(
        self,
        clearance_id: str,
    ) -> dict[str, Any] | None:
        """Read the exactly-once posting associated with one clearance."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                    SELECT * FROM controlled_submission_ledger_postings
                    WHERE clearance_id = ? LIMIT 1
                    """,
                (clearance_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_submission_ledger_postings_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable controlled-order ledger postings, newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                    SELECT * FROM controlled_submission_ledger_postings
                    ORDER BY applied_at_epoch_ms DESC, id DESC
                    LIMIT ?
                    """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_controlled_submission_ledger_correction_sync(
        self,
        correction_id: str,
    ) -> dict[str, Any] | None:
        """Read one immutable compensating correction."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                    SELECT * FROM controlled_submission_ledger_corrections
                    WHERE correction_id = ? LIMIT 1
                    """,
                (correction_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_controlled_submission_ledger_correction_for_posting_sync(
        self,
        posting_id: str,
    ) -> dict[str, Any] | None:
        """Read the exactly-once correction associated with one posting."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                    SELECT * FROM controlled_submission_ledger_corrections
                    WHERE posting_id = ? LIMIT 1
                    """,
                (posting_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_submission_ledger_corrections_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable compensating corrections, newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                    SELECT * FROM controlled_submission_ledger_corrections
                    ORDER BY applied_at_epoch_ms DESC, id DESC
                    LIMIT ?
                    """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]
