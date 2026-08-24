"""Fail-closed projection for persisted CITIC query-window reviews."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime

from account_truth.citic_source_query_window_review_contracts import (
    CITIC_SOURCE_QUERY_WINDOW_EVIDENCE_FINGERPRINT_PATTERN,
    CITIC_SOURCE_QUERY_WINDOW_FILE_FINGERPRINT_PATTERN,
    CITIC_SOURCE_QUERY_WINDOW_MAX_DAYS,
    CITIC_SOURCE_QUERY_WINDOW_REVIEW_SCHEMA_VERSION,
)

_FILE_FINGERPRINT = re.compile(CITIC_SOURCE_QUERY_WINDOW_FILE_FINGERPRINT_PATTERN)
_EVIDENCE_FINGERPRINT = re.compile(
    CITIC_SOURCE_QUERY_WINDOW_EVIDENCE_FINGERPRINT_PATTERN
)


class CiticSourceQueryWindowReviewProjectionMixin:
    def _review_from_row(self, row: sqlite3.Row) -> object:
        values = {
            "schema_version": str(row["schema_version"]),
            "intake_id": str(row["intake_id"]),
            "file_fingerprint": str(row["file_fingerprint"]),
            "source_preview_fingerprint": str(row["source_preview_fingerprint"]),
            "query_start_date": str(row["query_start_date"]),
            "query_end_date": str(row["query_end_date"]),
            "query_window_attested": bool(int(row["query_window_attested"])),
            "decision": str(row["decision"]),
            "supersedes_review_id": (
                str(row["supersedes_review_id"])
                if row["supersedes_review_id"] is not None
                else None
            ),
            "reviewer": str(row["reviewer"]),
        }
        review_id = str(row["review_id"])
        review_fingerprint = str(row["review_fingerprint"])
        created_at = str(row["created_at"])
        try:
            start = self._parse_date(values["query_start_date"])
            end = self._parse_date(values["query_end_date"])
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except self._rejection_type as exc:
            raise self._read_rejection_type(
                "citic_source_query_window_review_record_invalid"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise self._read_rejection_type(
                "citic_source_query_window_review_record_invalid"
            ) from exc
        if (
            values["schema_version"] != CITIC_SOURCE_QUERY_WINDOW_REVIEW_SCHEMA_VERSION
            or not review_id.startswith("citic_window_review_")
            or not values["intake_id"].startswith("citic_intake_")
            or not _FILE_FINGERPRINT.fullmatch(values["file_fingerprint"])
            or not _FILE_FINGERPRINT.fullmatch(values["source_preview_fingerprint"])
            or values["query_window_attested"] is not True
            or values["decision"] not in {"accepted", "revoked"}
            or (
                values["decision"] == "revoked"
                and not str(values["supersedes_review_id"] or "").startswith(
                    "citic_window_review_"
                )
            )
            or start > end
            or (end - start).days + 1 > CITIC_SOURCE_QUERY_WINDOW_MAX_DAYS
            or not values["reviewer"].strip()
            or created.tzinfo is None
            or created.utcoffset() is None
            or not _EVIDENCE_FINGERPRINT.fullmatch(review_fingerprint)
            or review_fingerprint != self._review_fingerprint(values)
        ):
            raise self._read_rejection_type(
                "citic_source_query_window_review_record_invalid"
            )
        return self._review_type(
            review_id=review_id,
            schema_version=values["schema_version"],
            intake_id=values["intake_id"],
            file_fingerprint=values["file_fingerprint"],
            source_preview_fingerprint=values["source_preview_fingerprint"],
            query_start_date=values["query_start_date"],
            query_end_date=values["query_end_date"],
            query_window_attested=True,
            decision=values["decision"],
            supersedes_review_id=values["supersedes_review_id"],
            reviewer=values["reviewer"],
            review_fingerprint=review_fingerprint,
            created_at=created_at,
        )
