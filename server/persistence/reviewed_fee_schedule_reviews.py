"""Append-only persistence for reviewed account fee schedules."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Mapping

from server.contracts.content_identity import canonical_json
from server.contracts.reviewed_fee_schedule import (
    REVIEWED_FEE_SCHEDULE_REVIEW_SCHEMA_VERSION,
    ReviewedFeeScheduleReadRejected,
)

_REVIEW_COLUMNS = (
    "review_id",
    "schema_version",
    "decision",
    "schedule_json",
    "schedule_fingerprint",
    "preview_json",
    "preview_fingerprint",
    "account_truth_import_run_id",
    "account_truth_source_fingerprint",
    "account_truth_scope_fingerprint",
    "account_reference_hash",
    "effective_start_date",
    "effective_end_date",
    "reviewer",
    "review_fingerprint",
    "created_at",
)


class ReviewedFeeScheduleReviewStore:
    """Own the immutable review rows and their SQLite transaction boundary."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)

    def get_latest_review(self) -> dict[str, Any] | None:
        with self._read_connection() as connection:
            if connection is None:
                return None
            row = connection.execute(
                "SELECT * FROM reviewed_fee_schedule_reviews ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row is not None else None

    def get_review(self, review_id: str) -> dict[str, Any] | None:
        with self._read_connection() as connection:
            if connection is None:
                return None
            row = connection.execute(
                "SELECT * FROM reviewed_fee_schedule_reviews "
                "WHERE review_id=? LIMIT 1",
                (str(review_id),),
            ).fetchone()
        return dict(row) if row is not None else None

    def append(
        self,
        *,
        decision: str,
        preview: Mapping[str, Any],
        reviewer: str,
        review_fingerprint: str,
    ) -> tuple[dict[str, Any], bool]:
        self._ensure_schema()
        with sqlite3.connect(self._path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                "SELECT * FROM reviewed_fee_schedule_reviews ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if latest is not None:
                if str(latest["review_fingerprint"]) == review_fingerprint:
                    connection.rollback()
                    return dict(latest), True
            review_id = f"fee_review_{uuid.uuid4().hex}"
            created_at = datetime.now(UTC).isoformat()
            connection.execute(
                """
                INSERT INTO reviewed_fee_schedule_reviews (
                    review_id, schema_version, decision, schedule_json,
                    schedule_fingerprint, preview_json, preview_fingerprint,
                    account_truth_import_run_id, account_truth_source_fingerprint,
                    account_truth_scope_fingerprint, account_reference_hash,
                    effective_start_date, effective_end_date, reviewer,
                    review_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    REVIEWED_FEE_SCHEDULE_REVIEW_SCHEMA_VERSION,
                    decision,
                    canonical_json(preview["schedule"]),
                    preview["schedule_fingerprint"],
                    canonical_json(dict(preview)),
                    preview["preview_fingerprint"],
                    preview["account_truth_import_run_id"],
                    preview["account_truth_source_fingerprint"],
                    preview["account_truth_scope_fingerprint"],
                    preview["account_reference_hash"],
                    preview["effective_start_date"],
                    preview["effective_end_date"],
                    reviewer,
                    review_fingerprint,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM reviewed_fee_schedule_reviews WHERE review_id=?",
                (review_id,),
            ).fetchone()
            connection.commit()
        if row is None:
            raise RuntimeError("reviewed fee schedule review was not persisted")
        return dict(row), False

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection | None]:
        if not self._path.is_file():
            yield None
            return
        try:
            uri = f"{self._path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only = ON")
                row = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    ("reviewed_fee_schedule_reviews",),
                ).fetchone()
                if row is None:
                    yield None
                    return
                columns = {
                    str(item["name"])
                    for item in connection.execute(
                        "PRAGMA table_info(reviewed_fee_schedule_reviews)"
                    ).fetchall()
                }
                if not set(_REVIEW_COLUMNS).issubset(columns):
                    raise ReviewedFeeScheduleReadRejected(
                        "reviewed_fee_schedule_review_schema_incomplete"
                    )
                yield connection
        except ReviewedFeeScheduleReadRejected:
            raise
        except sqlite3.Error as exc:
            raise ReviewedFeeScheduleReadRejected(
                "reviewed_fee_schedule_review_read_failed"
            ) from exc

    def _ensure_schema(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS reviewed_fee_schedule_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    review_id TEXT NOT NULL UNIQUE,
                    schema_version TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    schedule_json TEXT NOT NULL,
                    schedule_fingerprint TEXT NOT NULL,
                    preview_json TEXT NOT NULL,
                    preview_fingerprint TEXT NOT NULL,
                    account_truth_import_run_id TEXT NOT NULL,
                    account_truth_source_fingerprint TEXT NOT NULL,
                    account_truth_scope_fingerprint TEXT NOT NULL,
                    account_reference_hash TEXT NOT NULL,
                    effective_start_date TEXT NOT NULL,
                    effective_end_date TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    review_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_reviewed_fee_schedule_created "
                "ON reviewed_fee_schedule_reviews(id DESC)"
            )
