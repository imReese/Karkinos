"""Atomic controlled-submission reconciliation clearance unit of work."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.persistence.controlled_clearance_repository import (
    find_existing_clearance,
)
from server.persistence.controlled_clearance_validation import (
    build_controlled_clearance_write_plan,
)
from server.persistence.controlled_clearance_writer import (
    write_controlled_clearance,
)
from server.persistence.controlled_execution_access import (
    ControlledExecutionRepositoryAccess,
)
from server.persistence.controlled_execution_rejections import (
    controlled_submission_clearance_rejection,
)


class ControlledClearanceUnitOfWorkMixin(ControlledExecutionRepositoryAccess):
    """Coordinate one SQLite transaction over revalidation and persistence."""

    def record_controlled_submission_reconciliation_clearance_sync(
        self,
        *,
        clearance: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically record real fills, terminal OMS state, and clearance."""

        requested = dict(clearance)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = find_existing_clearance(conn, requested)
                if existing is not None:
                    if (
                        existing["clearance_id"] == requested["clearance_id"]
                        and existing["clearance_fingerprint"]
                        == requested["clearance_fingerprint"]
                        and existing["submit_intent_id"]
                        == requested["submit_intent_id"]
                    ):
                        conn.commit()
                        return {
                            "status": "cleared",
                            "blockers": [],
                            "reused": True,
                            "clearance": dict(existing),
                        }
                    conn.rollback()
                    return controlled_submission_clearance_rejection(
                        requested,
                        ["controlled_submission_clearance_conflict"],
                    )

                plan = build_controlled_clearance_write_plan(conn, requested)
                if plan.blockers:
                    conn.rollback()
                    return controlled_submission_clearance_rejection(
                        requested,
                        list(plan.blockers),
                    )
                write_blockers, saved = write_controlled_clearance(
                    conn,
                    requested,
                    plan,
                )
                if write_blockers:
                    conn.rollback()
                    return controlled_submission_clearance_rejection(
                        requested,
                        write_blockers,
                    )
                conn.commit()
                return {
                    "status": "cleared",
                    "blockers": [],
                    "reused": False,
                    "clearance": dict(saved) if saved is not None else {},
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
                return controlled_submission_clearance_rejection(
                    requested,
                    ["controlled_submission_clearance_transaction_unavailable"],
                )
