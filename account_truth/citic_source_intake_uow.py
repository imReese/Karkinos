"""Atomic write unit of work for CITIC source intake reviews."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from account_truth.broker_statement import BrokerStatementPreview
from account_truth.citic_source_intake_contracts import (
    CITIC_SOURCE_INTAKE_SCHEMA_VERSION,
)


class CiticSourceIntakeUnitOfWorkMixin:
    def record_review(
        self,
        preview: BrokerStatementPreview,
        *,
        expected_file_fingerprint: str,
        review_status: str,
        reviewer: str = "local",
    ) -> object:
        if expected_file_fingerprint != preview.file_fingerprint:
            raise self._intake_rejection_type("citic_source_file_fingerprint_mismatch")
        if review_status not in {"follow_up_required", "rejected"}:
            raise self._intake_rejection_type("citic_source_review_status_invalid")
        recordable = self._preview_recordable(preview)
        if review_status == "follow_up_required" and not recordable:
            raise self._intake_rejection_type(
                "citic_source_not_recordable_for_follow_up"
            )

        preview_fingerprint = self._preview_fingerprint(preview)
        created_at = datetime.now(UTC).isoformat()
        normalized_reviewer = reviewer.strip() or "local"
        error_codes = sorted({error.code for error in preview.errors})
        required_evidence = self._required_evidence(preview)
        limitations = sorted(set(preview.limitations))

        self._ensure_schema()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                    SELECT * FROM citic_source_intakes
                    WHERE file_fingerprint = ?
                    LIMIT 1
                    """,
                (preview.file_fingerprint,),
            ).fetchone()
            if existing is None:
                intake_id = f"citic_intake_{uuid.uuid4().hex}"
                conn.execute(
                    """
                        INSERT INTO citic_source_intakes (
                            intake_id, schema_version, source_type, file_fingerprint,
                            source_preview_fingerprint, validation_status, row_count,
                            valid_row_count, invalid_row_count, duplicate_row_count,
                            recognized_event_count, error_codes_json,
                            required_evidence_json, limitations_json,
                            recordable_for_follow_up, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                    (
                        intake_id,
                        CITIC_SOURCE_INTAKE_SCHEMA_VERSION,
                        preview.source_type,
                        preview.file_fingerprint,
                        preview_fingerprint,
                        preview.validation_status,
                        preview.row_count,
                        preview.valid_row_count,
                        preview.invalid_row_count,
                        preview.duplicate_row_count,
                        len(preview.events),
                        self._json(error_codes),
                        self._json(required_evidence),
                        self._json(limitations),
                        int(recordable),
                        created_at,
                    ),
                )
            else:
                intake_id = str(existing["intake_id"])
                if str(existing["source_preview_fingerprint"]) != preview_fingerprint:
                    raise self._intake_rejection_type(
                        "citic_source_preview_identity_conflict"
                    )

            latest_review = self._latest_review_row(conn, intake_id)
            if latest_review is not None:
                latest_status = str(latest_review["review_status"])
                if latest_status == review_status:
                    conn.commit()
                    saved = self._get_from_connection(conn, intake_id, reused=True)
                    if saved is None:
                        raise RuntimeError("CITIC source intake disappeared")
                    return saved
                if latest_status == "rejected":
                    raise self._intake_rejection_type(
                        "citic_source_rejection_is_terminal"
                    )

            review_id = f"citic_review_{uuid.uuid4().hex}"
            conn.execute(
                """
                    INSERT INTO citic_source_intake_reviews (
                        review_id, intake_id, source_preview_fingerprint,
                        review_status, reviewer, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                (
                    review_id,
                    intake_id,
                    preview_fingerprint,
                    review_status,
                    normalized_reviewer,
                    created_at,
                ),
            )
            conn.commit()
            saved = self._get_from_connection(conn, intake_id, reused=False)
            if saved is None:
                raise RuntimeError("CITIC source intake disappeared")
            return saved
