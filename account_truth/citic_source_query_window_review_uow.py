"""Atomic writes for exact-source CITIC query-window reviews."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import replace

from account_truth.broker_statement import BrokerStatementPreview
from account_truth.citic_source_query_window_review_contracts import (
    CITIC_SOURCE_QUERY_WINDOW_REVIEW_SCHEMA_VERSION,
)


class CiticSourceQueryWindowReviewUnitOfWorkMixin:
    def record_review(
        self,
        preview: BrokerStatementPreview,
        *,
        expected_file_fingerprint: str,
        expected_source_preview_fingerprint: str,
        query_start_date: str,
        query_end_date: str,
        query_window_attested: bool,
        reviewer: str = "local_owner",
    ) -> object:
        now = self._aware_now(self._clock())
        normalized = self._normalized_review_inputs(
            preview=preview,
            expected_file_fingerprint=expected_file_fingerprint,
            expected_source_preview_fingerprint=(expected_source_preview_fingerprint),
            query_start_date=query_start_date,
            query_end_date=query_end_date,
            query_window_attested=query_window_attested,
            reviewer=reviewer,
            today=now.date(),
        )
        self._require_current_follow_up_source(
            file_fingerprint=normalized["file_fingerprint"],
            source_preview_fingerprint=normalized["source_preview_fingerprint"],
        )
        self._ensure_schema()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN IMMEDIATE")
            source = self._current_source_row(
                conn,
                file_fingerprint=normalized["file_fingerprint"],
            )
            self._validate_current_source_row(
                source,
                source_preview_fingerprint=normalized["source_preview_fingerprint"],
            )
            intake_id = str(source["intake_id"])
            latest_row = self._latest_review_row(conn, intake_id)
            supersedes_review_id: str | None = None
            if latest_row is not None:
                latest = self._review_from_row(latest_row)
                if latest.decision == "accepted":
                    if self._same_accepted_window(latest, normalized):
                        conn.rollback()
                        return replace(latest, reused=True)
                    raise self._rejection_type(
                        "citic_source_query_window_active_review_conflict"
                    )
                supersedes_review_id = latest.review_id

            saved = self._insert_review(
                conn,
                intake_id=intake_id,
                file_fingerprint=normalized["file_fingerprint"],
                source_preview_fingerprint=normalized["source_preview_fingerprint"],
                query_start_date=normalized["query_start_date"],
                query_end_date=normalized["query_end_date"],
                decision="accepted",
                supersedes_review_id=supersedes_review_id,
                reviewer=normalized["reviewer"],
                created_at=now.isoformat(),
            )
            conn.commit()
            return saved

    def revoke_latest(
        self,
        *,
        intake_id: str,
        expected_active_review_id: str,
        expected_active_review_fingerprint: str,
        reviewer: str = "local_owner",
    ) -> object:
        normalized_intake_id = intake_id.strip()
        normalized_review_id = expected_active_review_id.strip()
        normalized_fingerprint = expected_active_review_fingerprint.strip()
        normalized_reviewer = reviewer.strip() or "local_owner"
        if not normalized_intake_id.startswith("citic_intake_"):
            raise self._rejection_type("citic_source_query_window_intake_invalid")
        if not normalized_review_id.startswith("citic_window_review_"):
            raise self._rejection_type("citic_source_query_window_review_id_invalid")
        if not self._evidence_fingerprint.fullmatch(normalized_fingerprint):
            raise self._rejection_type(
                "citic_source_query_window_review_fingerprint_invalid"
            )
        if not self._path.is_file():
            raise self._rejection_type("citic_source_query_window_review_missing")

        now = self._aware_now(self._clock())
        try:
            with sqlite3.connect(self._path) as conn:
                conn.row_factory = sqlite3.Row
                if self._schema_state(conn) == "absent":
                    raise self._rejection_type(
                        "citic_source_query_window_review_missing"
                    )
                if self._schema_state(conn) != "complete":
                    raise self._rejection_type(
                        "citic_source_query_window_review_schema_incompatible"
                    )
                conn.execute("BEGIN IMMEDIATE")
                latest_row = self._latest_review_row(conn, normalized_intake_id)
                if latest_row is None:
                    raise self._rejection_type(
                        "citic_source_query_window_review_missing"
                    )
                latest = self._review_from_row(latest_row)
                if latest.decision == "revoked":
                    if latest.supersedes_review_id == normalized_review_id:
                        conn.rollback()
                        return replace(latest, reused=True)
                    raise self._rejection_type("citic_source_query_window_review_drift")
                if (
                    latest.review_id != normalized_review_id
                    or latest.review_fingerprint != normalized_fingerprint
                ):
                    raise self._rejection_type("citic_source_query_window_review_drift")
                revoked = self._insert_review(
                    conn,
                    intake_id=latest.intake_id,
                    file_fingerprint=latest.file_fingerprint,
                    source_preview_fingerprint=(latest.source_preview_fingerprint),
                    query_start_date=latest.query_start_date,
                    query_end_date=latest.query_end_date,
                    decision="revoked",
                    supersedes_review_id=latest.review_id,
                    reviewer=normalized_reviewer,
                    created_at=now.isoformat(),
                )
                conn.commit()
                return revoked
        except self._rejection_type:
            raise
        except sqlite3.DatabaseError as exc:
            raise self._rejection_type(
                "citic_source_query_window_review_store_unreadable"
            ) from exc

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
    ) -> object:
        payload = {
            "schema_version": CITIC_SOURCE_QUERY_WINDOW_REVIEW_SCHEMA_VERSION,
            "intake_id": intake_id,
            "file_fingerprint": file_fingerprint,
            "source_preview_fingerprint": source_preview_fingerprint,
            "query_start_date": query_start_date,
            "query_end_date": query_end_date,
            "query_window_attested": True,
            "decision": decision,
            "supersedes_review_id": supersedes_review_id,
            "reviewer": reviewer,
        }
        review_id = f"citic_window_review_{uuid.uuid4().hex}"
        review_fingerprint = self._review_fingerprint(payload)
        conn.execute(
            """
            INSERT INTO citic_source_query_window_reviews (
                review_id, schema_version, intake_id, file_fingerprint,
                source_preview_fingerprint, query_start_date, query_end_date,
                query_window_attested, decision, supersedes_review_id,
                reviewer, review_fingerprint, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                CITIC_SOURCE_QUERY_WINDOW_REVIEW_SCHEMA_VERSION,
                intake_id,
                file_fingerprint,
                source_preview_fingerprint,
                query_start_date,
                query_end_date,
                1,
                decision,
                supersedes_review_id,
                reviewer,
                review_fingerprint,
                created_at,
            ),
        )
        row = conn.execute(
            """
            SELECT * FROM citic_source_query_window_reviews
            WHERE review_id = ?
            LIMIT 1
            """,
            (review_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("CITIC source query-window review disappeared")
        return self._review_from_row(row)
