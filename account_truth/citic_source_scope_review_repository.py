"""Read repository for persisted CITIC source-scope reviews."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator


class CiticSourceScopeReviewReadRepositoryMixin:
    def get_latest_review(self, intake_id: str) -> object | None:
        with self._read_connection() as conn:
            if conn is None:
                return None
            row = self._latest_review_row(conn, intake_id.strip())
        return self._review_from_row(row) if row is not None else None

    def list_latest_reviews(self, *, limit: int = 200) -> list[object]:
        effective_limit = max(1, min(int(limit), 500))
        with self._read_connection() as conn:
            if conn is None:
                return []
            rows = conn.execute(
                """
                SELECT review.*
                FROM citic_source_scope_reviews AS review
                JOIN (
                    SELECT intake_id, MAX(id) AS latest_id
                    FROM citic_source_scope_reviews
                    GROUP BY intake_id
                ) AS latest ON latest.latest_id = review.id
                ORDER BY review.id DESC
                LIMIT ?
                """,
                (effective_limit,),
            ).fetchall()
        return [self._review_from_row(row) for row in rows]

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection | None]:
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
                if schema_state not in {"complete", "legacy_v1"}:
                    raise self._read_rejection_type(
                        "citic_source_scope_review_schema_incomplete"
                    )
                yield conn
        except self._read_rejection_type:
            raise
        except (OSError, sqlite3.DatabaseError) as exc:
            raise self._read_rejection_type(
                "citic_source_scope_review_store_unreadable"
            ) from exc

    def _require_current_source_and_query_window(
        self,
        normalized: dict[str, object],
    ) -> None:
        try:
            self._intake_repository().list_intakes(limit=1)
            query_review = self._query_window_repository().get_latest_review(
                str(normalized["intake_id"])
            )
        except self._intake_read_rejection_type as exc:
            raise self._rejection_type(exc.code) from exc
        except self._query_window_read_rejection_type as exc:
            raise self._rejection_type(exc.code) from exc
        if not self._path.is_file():
            raise self._rejection_type("citic_source_scope_intake_missing")
        try:
            read_uri = f"{self._path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(read_uri, uri=True) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only = ON")
                source = conn.execute(
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
                    WHERE intake.intake_id = ?
                    LIMIT 1
                    """,
                    (normalized["intake_id"],),
                ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise self._rejection_type("citic_source_intake_store_unreadable") from exc
        if source is None:
            raise self._rejection_type("citic_source_scope_intake_missing")
        if (
            str(source["file_fingerprint"]) != normalized["file_fingerprint"]
            or str(source["source_preview_fingerprint"])
            != normalized["source_preview_fingerprint"]
        ):
            raise self._rejection_type("citic_source_scope_source_drift")
        if int(source["recordable_for_follow_up"]) != 1:
            raise self._rejection_type("citic_source_scope_source_not_recordable")
        if str(source["review_status"]) != "follow_up_required":
            raise self._rejection_type("citic_source_scope_source_not_pending")
        if (
            query_review is None
            or query_review.decision != "accepted"
            or query_review.review_id != normalized["query_window_review_id"]
            or query_review.review_fingerprint
            != normalized["query_window_review_fingerprint"]
            or query_review.file_fingerprint != normalized["file_fingerprint"]
            or query_review.source_preview_fingerprint
            != normalized["source_preview_fingerprint"]
        ):
            raise self._rejection_type(
                "citic_source_scope_query_window_review_mismatch"
            )

    @staticmethod
    def _latest_review_row(
        conn: sqlite3.Connection,
        intake_id: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT * FROM citic_source_scope_reviews
            WHERE intake_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (intake_id,),
        ).fetchone()
