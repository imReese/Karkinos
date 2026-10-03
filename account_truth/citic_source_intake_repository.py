"""Read repository for persisted CITIC source intake reviews."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Protocol

    from account_truth.broker_statement import BrokerStatementPreview
    from account_truth.citic_source_intake import (
        CiticSourceIntake,
        CiticSourceIntakeReadRejected,
        CiticSourceIntakeRejected,
    )

    class CiticSourceIntakeRepositoryAccess(Protocol):
        """Dependencies supplied by the concrete repository to its persistence mixins."""

        def _ensure_schema(self) -> None: ...

        def _get_from_connection(
            self, conn: sqlite3.Connection, intake_id: str, *, reused: bool
        ) -> CiticSourceIntake | None: ...

        def _intake_from_row(
            self, row: sqlite3.Row | None, *, reused: bool
        ) -> CiticSourceIntake | None: ...

        _intake_read_rejection_type: type[CiticSourceIntakeReadRejected]
        _intake_rejection_type: type[CiticSourceIntakeRejected]
        _intake_type: type[CiticSourceIntake]

        def _json(self, values: list[str]) -> str: ...

        def _json_list(self, value: object) -> list[str]: ...

        @staticmethod
        def _latest_review_row(
            conn: sqlite3.Connection, intake_id: str
        ) -> sqlite3.Row | None: ...

        _path: Path

        def _preview_fingerprint(self, preview: BrokerStatementPreview) -> str: ...

        def _preview_recordable(self, preview: BrokerStatementPreview) -> bool: ...

        def _required_evidence(self, preview: BrokerStatementPreview) -> list[str]: ...

        @staticmethod
        def _schema_state(conn: sqlite3.Connection) -> str: ...


class CiticSourceIntakeReadRepositoryMixin:
    def list_intakes(
        self: CiticSourceIntakeRepositoryAccess, *, limit: int = 50
    ) -> list[CiticSourceIntake]:
        effective_limit = max(1, min(int(limit), 200))
        if not self._path.is_file():
            return []
        try:
            read_uri = f"{self._path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(read_uri, uri=True) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only = ON")
                schema_state = self._schema_state(conn)
                if schema_state == "absent":
                    return []
                if schema_state != "complete":
                    raise self._intake_read_rejection_type(
                        "citic_source_intake_schema_incomplete"
                    )
                rows = conn.execute(
                    """
                        SELECT intake_id
                        FROM citic_source_intakes
                        ORDER BY created_at DESC, id DESC
                        LIMIT ?
                        """,
                    (effective_limit,),
                ).fetchall()
                return [
                    intake
                    for row in rows
                    if (
                        intake := self._get_from_connection(
                            conn,
                            str(row["intake_id"]),
                            reused=False,
                        )
                    )
                    is not None
                ]
        except self._intake_read_rejection_type:
            raise
        except sqlite3.DatabaseError as exc:
            raise self._intake_read_rejection_type(
                "citic_source_intake_store_unreadable"
            ) from exc

    @staticmethod
    def _latest_review_row(
        conn: sqlite3.Connection,
        intake_id: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
                SELECT * FROM citic_source_intake_reviews
                WHERE intake_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
            (intake_id,),
        ).fetchone()

    def _get_from_connection(
        self: CiticSourceIntakeRepositoryAccess,
        conn: sqlite3.Connection,
        intake_id: str,
        *,
        reused: bool,
    ) -> CiticSourceIntake | None:
        row = conn.execute(
            """
            SELECT intake.*, review.review_id, review.review_status,
                   review.reviewer, review.created_at AS reviewed_at
            FROM citic_source_intakes AS intake
            JOIN citic_source_intake_reviews AS review
              ON review.id = (
                  SELECT MAX(candidate.id)
                  FROM citic_source_intake_reviews AS candidate
                  WHERE candidate.intake_id = intake.intake_id
              )
            WHERE intake.intake_id = ?
            LIMIT 1
            """,
            (intake_id,),
        ).fetchone()
        return self._intake_from_row(row, reused=reused)
