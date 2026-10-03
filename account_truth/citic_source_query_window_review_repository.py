"""Read repository for persisted CITIC query-window reviews."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    import re
    from contextlib import AbstractContextManager
    from datetime import date, datetime
    from pathlib import Path
    from typing import Callable, Protocol

    from account_truth.citic_source_intake import (
        CiticSourceIntakeReadRejected,
        CiticSourceIntakeRepository,
    )
    from account_truth.citic_source_query_window_review import (
        CiticSourceQueryWindowReview,
        CiticSourceQueryWindowReviewReadRejected,
        CiticSourceQueryWindowReviewRejected,
    )

    class CiticSourceQueryWindowReviewRepositoryAccess(Protocol):
        """Dependencies supplied by the concrete repository to its persistence mixins."""

        def _aware_now(self, value: datetime) -> datetime: ...

        _clock: Callable[[], datetime]

        @staticmethod
        def _current_source_row(
            conn: sqlite3.Connection, *, file_fingerprint: str
        ) -> sqlite3.Row | None: ...

        def _ensure_schema(self) -> None: ...

        _evidence_fingerprint: re.Pattern[str]

        def _insert_review(
            self,
            conn: sqlite3.Connection,
            *,
            intake_id: str,
            file_fingerprint: str,
            source_preview_fingerprint: str,
            query_start_date: str,
            query_end_date: str,
            decision: str,
            supersedes_review_id: str | None,
            reviewer: str,
            created_at: str,
        ) -> CiticSourceQueryWindowReview: ...

        @property
        def _intake_read_rejection_type(
            self,
        ) -> type[CiticSourceIntakeReadRejected]: ...

        def _intake_repository(self) -> CiticSourceIntakeRepository: ...

        @staticmethod
        def _latest_review_row(
            conn: sqlite3.Connection, intake_id: str
        ) -> sqlite3.Row | None: ...

        def _normalized_review_inputs(self, **kwargs: object) -> dict[str, str]: ...

        def _parse_date(self, value: object) -> date: ...

        _path: Path

        def _read_connection(
            self,
        ) -> AbstractContextManager[sqlite3.Connection | None]: ...

        _read_rejection_type: type[CiticSourceQueryWindowReviewReadRejected]
        _rejection_type: type[CiticSourceQueryWindowReviewRejected]

        def _require_current_follow_up_source(
            self, *, file_fingerprint: str, source_preview_fingerprint: str
        ) -> None: ...

        def _review_fingerprint(self, payload: dict[str, object]) -> str: ...

        def _review_from_row(
            self, row: sqlite3.Row
        ) -> CiticSourceQueryWindowReview: ...

        _review_type: type[CiticSourceQueryWindowReview]

        def _same_accepted_window(
            self, review: CiticSourceQueryWindowReview, normalized: dict[str, str]
        ) -> bool: ...

        @staticmethod
        def _schema_state(conn: sqlite3.Connection) -> str: ...

        def _validate_current_source_row(
            self, row: sqlite3.Row | None, *, source_preview_fingerprint: str
        ) -> None: ...


class CiticSourceQueryWindowReviewReadRepositoryMixin:
    def get_latest_review(
        self: CiticSourceQueryWindowReviewRepositoryAccess, intake_id: str
    ) -> CiticSourceQueryWindowReview | None:
        with self._read_connection() as conn:
            if conn is None:
                return None
            row = self._latest_review_row(conn, intake_id)
        return self._review_from_row(row) if row is not None else None

    def list_latest_reviews(
        self: CiticSourceQueryWindowReviewRepositoryAccess, *, limit: int = 200
    ) -> list[CiticSourceQueryWindowReview]:
        effective_limit = max(1, min(int(limit), 500))
        with self._read_connection() as conn:
            if conn is None:
                return []
            rows = conn.execute(
                """
                SELECT review.*
                FROM citic_source_query_window_reviews AS review
                JOIN (
                    SELECT intake_id, MAX(id) AS latest_id
                    FROM citic_source_query_window_reviews
                    GROUP BY intake_id
                ) AS latest ON latest.latest_id = review.id
                ORDER BY review.id DESC
                LIMIT ?
                """,
                (effective_limit,),
            ).fetchall()
        return [self._review_from_row(row) for row in rows]

    @contextmanager
    def _read_connection(
        self: CiticSourceQueryWindowReviewRepositoryAccess,
    ) -> Iterator[sqlite3.Connection | None]:
        if not self._path.is_file():
            yield None
            return
        try:
            read_uri = f"{self._path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(read_uri, uri=True) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only = ON")
                schema_state = self._schema_state(conn)
                if schema_state == "absent":
                    yield None
                    return
                if schema_state != "complete":
                    raise self._read_rejection_type(
                        "citic_source_query_window_review_schema_incomplete"
                    )
                yield conn
        except self._read_rejection_type:
            raise
        except (OSError, sqlite3.DatabaseError) as exc:
            raise self._read_rejection_type(
                "citic_source_query_window_review_store_unreadable"
            ) from exc

    def _require_current_follow_up_source(
        self: CiticSourceQueryWindowReviewRepositoryAccess,
        *,
        file_fingerprint: str,
        source_preview_fingerprint: str,
    ) -> None:
        try:
            self._intake_repository().list_intakes(limit=1)
        except self._intake_read_rejection_type as exc:
            raise self._rejection_type(exc.code) from exc
        if not self._path.is_file():
            raise self._rejection_type("citic_source_query_window_intake_missing")
        try:
            read_uri = f"{self._path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(read_uri, uri=True) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only = ON")
                source = self._current_source_row(
                    conn,
                    file_fingerprint=file_fingerprint,
                )
        except sqlite3.DatabaseError as exc:
            raise self._rejection_type("citic_source_intake_store_unreadable") from exc
        self._validate_current_source_row(
            source,
            source_preview_fingerprint=source_preview_fingerprint,
        )

    @staticmethod
    def _current_source_row(
        conn: sqlite3.Connection,
        *,
        file_fingerprint: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT intake.intake_id, intake.file_fingerprint,
                   intake.source_preview_fingerprint,
                   intake.recordable_for_follow_up,
                   review.review_status
            FROM citic_source_intakes AS intake
            JOIN citic_source_intake_reviews AS review
              ON review.id = (
                  SELECT MAX(candidate.id)
                  FROM citic_source_intake_reviews AS candidate
                  WHERE candidate.intake_id = intake.intake_id
              )
            WHERE intake.file_fingerprint = ?
            LIMIT 1
            """,
            (file_fingerprint,),
        ).fetchone()

    def _validate_current_source_row(
        self: CiticSourceQueryWindowReviewRepositoryAccess,
        row: sqlite3.Row | None,
        *,
        source_preview_fingerprint: str,
    ) -> None:
        if row is None:
            raise self._rejection_type("citic_source_query_window_intake_missing")
        if str(row["source_preview_fingerprint"]) != source_preview_fingerprint:
            raise self._rejection_type("citic_source_query_window_source_drift")
        if int(row["recordable_for_follow_up"]) != 1:
            raise self._rejection_type(
                "citic_source_query_window_source_not_recordable"
            )
        if str(row["review_status"]) != "follow_up_required":
            raise self._rejection_type("citic_source_query_window_source_not_pending")

    @staticmethod
    def _latest_review_row(
        conn: sqlite3.Connection,
        intake_id: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT * FROM citic_source_query_window_reviews
            WHERE intake_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (intake_id,),
        ).fetchone()
