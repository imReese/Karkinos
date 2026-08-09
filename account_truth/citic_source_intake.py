"""Persist privacy-minimized reviews of incomplete CITIC source files.

This store is deliberately separate from canonical broker evidence.  It records
only a content fingerprint, validation counts/codes, required follow-up
evidence, and the operator's review disposition.  Parsed transactions and
account details never enter these tables, and these rows are not eligible for
Account Truth reconciliation or execution gates.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from account_truth.broker_statement import BrokerStatementPreview
from account_truth.citic_history_xls import (
    CITIC_HISTORY_XLS_COLUMNS,
    CITIC_HISTORY_XLS_SOURCE_TYPE,
    recognized_non_financial_activity_count,
)

CITIC_SOURCE_INTAKE_SCHEMA_VERSION = "karkinos.account_truth.citic_source_intake.v1"
CiticSourceReviewStatus = Literal["follow_up_required", "rejected"]

_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_NON_FINANCIAL_ACTIVITY_CODE = "citic_history_xls_non_financial_activity_ignored"


class CiticSourceIntakeRejected(ValueError):
    """Raised when an intake review would weaken a persisted safety boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CiticSourceIntakeReadRejected(RuntimeError):
    """Raised when persisted intake metadata cannot be read safely."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CiticSourceIntake:
    intake_id: str
    schema_version: str
    source_type: str
    file_fingerprint: str
    source_preview_fingerprint: str
    validation_status: str
    row_count: int
    valid_row_count: int
    invalid_row_count: int
    duplicate_row_count: int
    recognized_event_count: int
    error_codes: list[str]
    required_evidence: list[str]
    limitations: list[str]
    recordable_for_follow_up: bool
    review_id: str
    review_status: CiticSourceReviewStatus
    reviewer: str
    created_at: str
    reviewed_at: str
    reused: bool = False


def required_evidence_for_citic_preview(
    preview: BrokerStatementPreview,
) -> list[str]:
    required: list[str] = []
    if preview.events:
        required.append("itemized_settlement_or_cash_flow")
    required.append("current_cash_and_position_snapshot")
    if recognized_non_financial_activity_count(preview) > 0:
        required.append("review_non_financial_activity")
    if preview.invalid_row_count > 0:
        required.append("resolve_invalid_rows")
    return required


def citic_preview_is_recordable_for_follow_up(
    preview: BrokerStatementPreview,
) -> bool:
    """Return whether a blocked preview is structurally useful follow-up evidence."""

    columns = tuple(preview.normalized_columns)
    non_financial_count = recognized_non_financial_activity_count(preview)
    return (
        preview.source_type == CITIC_HISTORY_XLS_SOURCE_TYPE
        and preview.validation_status == "blocked"
        and bool(_FINGERPRINT_PATTERN.fullmatch(preview.file_fingerprint))
        and len(columns) == len(CITIC_HISTORY_XLS_COLUMNS)
        and set(columns) == set(CITIC_HISTORY_XLS_COLUMNS)
        and preview.row_count
        == preview.valid_row_count + preview.invalid_row_count + non_financial_count
        and preview.valid_row_count == len(preview.events)
        and (preview.valid_row_count > 0 or non_financial_count > 0)
    )


def citic_source_preview_fingerprint(preview: BrokerStatementPreview) -> str:
    """Fingerprint only the sanitized, review-relevant preview identity."""

    payload = {
        "schema_version": preview.schema_version,
        "source_type": preview.source_type,
        "file_fingerprint": preview.file_fingerprint,
        "normalized_columns": list(preview.normalized_columns),
        "row_count": preview.row_count,
        "valid_row_count": preview.valid_row_count,
        "invalid_row_count": preview.invalid_row_count,
        "duplicate_row_count": preview.duplicate_row_count,
        "validation_status": preview.validation_status,
        "recognized_event_count": len(preview.events),
        "errors": sorted(
            (
                {
                    "row_number": error.row_number,
                    "code": error.code,
                }
                for error in preview.errors
            ),
            key=lambda item: (item["row_number"] or -1, item["code"]),
        ),
        "limitations": sorted(set(preview.limitations)),
        "required_evidence": required_evidence_for_citic_preview(preview),
        "recordable_for_follow_up": citic_preview_is_recordable_for_follow_up(preview),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CiticSourceIntakeRepository:
    """Append-only operator reviews for non-authoritative CITIC source files."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)

    def record_review(
        self,
        preview: BrokerStatementPreview,
        *,
        expected_file_fingerprint: str,
        review_status: CiticSourceReviewStatus,
        reviewer: str = "local",
    ) -> CiticSourceIntake:
        if expected_file_fingerprint != preview.file_fingerprint:
            raise CiticSourceIntakeRejected("citic_source_file_fingerprint_mismatch")
        if review_status not in {"follow_up_required", "rejected"}:
            raise CiticSourceIntakeRejected("citic_source_review_status_invalid")
        recordable = citic_preview_is_recordable_for_follow_up(preview)
        if review_status == "follow_up_required" and not recordable:
            raise CiticSourceIntakeRejected("citic_source_not_recordable_for_follow_up")

        preview_fingerprint = citic_source_preview_fingerprint(preview)
        created_at = datetime.now(UTC).isoformat()
        normalized_reviewer = reviewer.strip() or "local"
        error_codes = sorted({error.code for error in preview.errors})
        required_evidence = required_evidence_for_citic_preview(preview)
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
                        _json(error_codes),
                        _json(required_evidence),
                        _json(limitations),
                        int(recordable),
                        created_at,
                    ),
                )
            else:
                intake_id = str(existing["intake_id"])
                if str(existing["source_preview_fingerprint"]) != preview_fingerprint:
                    raise CiticSourceIntakeRejected(
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
                    raise CiticSourceIntakeRejected(
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

    def list_intakes(self, *, limit: int = 50) -> list[CiticSourceIntake]:
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
                    raise CiticSourceIntakeReadRejected(
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
        except CiticSourceIntakeReadRejected:
            raise
        except sqlite3.DatabaseError as exc:
            raise CiticSourceIntakeReadRejected(
                "citic_source_intake_store_unreadable"
            ) from exc

    def _ensure_schema(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS citic_source_intakes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    intake_id TEXT NOT NULL UNIQUE,
                    schema_version TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    file_fingerprint TEXT NOT NULL UNIQUE,
                    source_preview_fingerprint TEXT NOT NULL,
                    validation_status TEXT NOT NULL CHECK(validation_status = 'blocked'),
                    row_count INTEGER NOT NULL,
                    valid_row_count INTEGER NOT NULL,
                    invalid_row_count INTEGER NOT NULL,
                    duplicate_row_count INTEGER NOT NULL,
                    recognized_event_count INTEGER NOT NULL,
                    error_codes_json TEXT NOT NULL,
                    required_evidence_json TEXT NOT NULL,
                    limitations_json TEXT NOT NULL,
                    recordable_for_follow_up INTEGER NOT NULL CHECK(
                        recordable_for_follow_up IN (0, 1)
                    ),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS citic_source_intake_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    review_id TEXT NOT NULL UNIQUE,
                    intake_id TEXT NOT NULL,
                    source_preview_fingerprint TEXT NOT NULL,
                    review_status TEXT NOT NULL CHECK(
                        review_status IN ('follow_up_required', 'rejected')
                    ),
                    reviewer TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(intake_id, review_status),
                    FOREIGN KEY(intake_id) REFERENCES citic_source_intakes(intake_id)
                );

                CREATE INDEX IF NOT EXISTS idx_citic_source_intakes_created
                ON citic_source_intakes(created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_citic_source_intake_reviews_latest
                ON citic_source_intake_reviews(intake_id, id DESC);
            """)
            conn.commit()

    @staticmethod
    def _schema_state(conn: sqlite3.Connection) -> str:
        required_tables = {
            "citic_source_intakes": {
                "id",
                "intake_id",
                "schema_version",
                "source_type",
                "file_fingerprint",
                "source_preview_fingerprint",
                "validation_status",
                "row_count",
                "valid_row_count",
                "invalid_row_count",
                "duplicate_row_count",
                "recognized_event_count",
                "error_codes_json",
                "required_evidence_json",
                "limitations_json",
                "recordable_for_follow_up",
                "created_at",
            },
            "citic_source_intake_reviews": {
                "id",
                "review_id",
                "intake_id",
                "source_preview_fingerprint",
                "review_status",
                "reviewer",
                "created_at",
            },
        }
        table_names = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        present = table_names.intersection(required_tables)
        if not present:
            return "absent"
        if present != set(required_tables):
            return "incomplete"
        for table_name, required_columns in required_tables.items():
            columns = {
                str(row["name"])
                for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            }
            if not required_columns.issubset(columns):
                return "incomplete"
        return "complete"

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
        self,
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
        if row is None:
            return None
        counts = {
            key: int(row[key])
            for key in (
                "row_count",
                "valid_row_count",
                "invalid_row_count",
                "duplicate_row_count",
                "recognized_event_count",
            )
        }
        error_codes = _json_list(row["error_codes_json"])
        required_evidence = _json_list(row["required_evidence_json"])
        limitations = _json_list(row["limitations_json"])
        non_financial_count = (
            counts["row_count"]
            - counts["valid_row_count"]
            - counts["invalid_row_count"]
        )
        recordable = int(row["recordable_for_follow_up"])
        review_status = str(row["review_status"])
        if (
            str(row["schema_version"]) != CITIC_SOURCE_INTAKE_SCHEMA_VERSION
            or str(row["source_type"]) != CITIC_HISTORY_XLS_SOURCE_TYPE
            or str(row["validation_status"]) != "blocked"
            or not _FINGERPRINT_PATTERN.fullmatch(str(row["file_fingerprint"]))
            or not _FINGERPRINT_PATTERN.fullmatch(
                str(row["source_preview_fingerprint"])
            )
            or review_status not in {"follow_up_required", "rejected"}
            or recordable not in {0, 1}
            or (review_status == "follow_up_required" and recordable != 1)
            or any(value < 0 for value in counts.values())
            or non_financial_count < 0
            or (
                non_financial_count > 0
                and _NON_FINANCIAL_ACTIVITY_CODE not in error_codes
            )
            or (
                non_financial_count == 0 and _NON_FINANCIAL_ACTIVITY_CODE in error_codes
            )
            or not str(row["intake_id"]).startswith("citic_intake_")
            or not str(row["review_id"]).startswith("citic_review_")
            or not str(row["reviewer"]).strip()
            or not str(row["created_at"]).strip()
            or not str(row["reviewed_at"]).strip()
        ):
            raise CiticSourceIntakeReadRejected("citic_source_intake_record_invalid")
        return CiticSourceIntake(
            intake_id=str(row["intake_id"]),
            schema_version=str(row["schema_version"]),
            source_type=str(row["source_type"]),
            file_fingerprint=str(row["file_fingerprint"]),
            source_preview_fingerprint=str(row["source_preview_fingerprint"]),
            validation_status=str(row["validation_status"]),
            row_count=counts["row_count"],
            valid_row_count=counts["valid_row_count"],
            invalid_row_count=counts["invalid_row_count"],
            duplicate_row_count=counts["duplicate_row_count"],
            recognized_event_count=counts["recognized_event_count"],
            error_codes=error_codes,
            required_evidence=required_evidence,
            limitations=limitations,
            recordable_for_follow_up=bool(recordable),
            review_id=str(row["review_id"]),
            review_status=review_status,  # type: ignore[arg-type]
            reviewer=str(row["reviewer"]),
            created_at=str(row["created_at"]),
            reviewed_at=str(row["reviewed_at"]),
            reused=reused,
        )


def _json(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _json_list(value: object) -> list[str]:
    try:
        loaded = json.loads(str(value))
    except (TypeError, ValueError):
        raise CiticSourceIntakeReadRejected(
            "citic_source_intake_record_invalid"
        ) from None
    if not isinstance(loaded, list) or any(
        not isinstance(item, str) or not item.strip() for item in loaded
    ):
        raise CiticSourceIntakeReadRejected("citic_source_intake_record_invalid")
    return loaded
