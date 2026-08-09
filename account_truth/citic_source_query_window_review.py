"""Append-only reviews of the query window used for one CITIC export.

This evidence is deliberately narrower than canonical Account Truth scope.  It
binds an operator-attested start/end date to one already reviewed, exact source
fingerprint.  It never persists parsed events and cannot satisfy account
binding, settlement, current-snapshot, reconciliation, execution, or capital
authority gates.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Callable, Iterator, Literal

from account_truth.broker_statement import BrokerStatementPreview
from account_truth.citic_source_intake import (
    CiticSourceIntakeReadRejected,
    CiticSourceIntakeRepository,
    citic_preview_is_recordable_for_follow_up,
    citic_source_preview_fingerprint,
)

CITIC_SOURCE_QUERY_WINDOW_REVIEW_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_source_query_window_review.v1"
)
CiticSourceQueryWindowReviewDecision = Literal["accepted", "revoked"]

_FILE_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_QUERY_WINDOW_DAYS = 31


class CiticSourceQueryWindowReviewRejected(ValueError):
    """Raised when a source-window review would weaken evidence boundaries."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CiticSourceQueryWindowReviewReadRejected(RuntimeError):
    """Raised when persisted source-window reviews cannot be read safely."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CiticSourceQueryWindowReview:
    review_id: str
    schema_version: str
    intake_id: str
    file_fingerprint: str
    source_preview_fingerprint: str
    query_start_date: str
    query_end_date: str
    query_window_attested: bool
    decision: CiticSourceQueryWindowReviewDecision
    supersedes_review_id: str | None
    reviewer: str
    review_fingerprint: str
    created_at: str
    reused: bool = False


class CiticSourceQueryWindowReviewRepository:
    """Persist exact-source window reviews without persisting source rows."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = Path(db_path)
        self._clock = clock or (lambda: datetime.now(UTC))

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
    ) -> CiticSourceQueryWindowReview:
        now = _aware_now(self._clock())
        normalized = _normalized_review_inputs(
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
                latest = _review_from_row(latest_row)
                if latest.decision == "accepted":
                    if _same_accepted_window(latest, normalized):
                        conn.rollback()
                        return replace(latest, reused=True)
                    raise CiticSourceQueryWindowReviewRejected(
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
    ) -> CiticSourceQueryWindowReview:
        normalized_intake_id = intake_id.strip()
        normalized_review_id = expected_active_review_id.strip()
        normalized_fingerprint = expected_active_review_fingerprint.strip()
        normalized_reviewer = reviewer.strip() or "local_owner"
        if not normalized_intake_id.startswith("citic_intake_"):
            raise CiticSourceQueryWindowReviewRejected(
                "citic_source_query_window_intake_invalid"
            )
        if not normalized_review_id.startswith("citic_window_review_"):
            raise CiticSourceQueryWindowReviewRejected(
                "citic_source_query_window_review_id_invalid"
            )
        if not _EVIDENCE_FINGERPRINT.fullmatch(normalized_fingerprint):
            raise CiticSourceQueryWindowReviewRejected(
                "citic_source_query_window_review_fingerprint_invalid"
            )
        if not self._path.is_file():
            raise CiticSourceQueryWindowReviewRejected(
                "citic_source_query_window_review_missing"
            )

        now = _aware_now(self._clock())
        try:
            with sqlite3.connect(self._path) as conn:
                conn.row_factory = sqlite3.Row
                if self._schema_state(conn) == "absent":
                    raise CiticSourceQueryWindowReviewRejected(
                        "citic_source_query_window_review_missing"
                    )
                if self._schema_state(conn) != "complete":
                    raise CiticSourceQueryWindowReviewRejected(
                        "citic_source_query_window_review_schema_incompatible"
                    )
                conn.execute("BEGIN IMMEDIATE")
                latest_row = self._latest_review_row(conn, normalized_intake_id)
                if latest_row is None:
                    raise CiticSourceQueryWindowReviewRejected(
                        "citic_source_query_window_review_missing"
                    )
                latest = _review_from_row(latest_row)
                if latest.decision == "revoked":
                    if latest.supersedes_review_id == normalized_review_id:
                        conn.rollback()
                        return replace(latest, reused=True)
                    raise CiticSourceQueryWindowReviewRejected(
                        "citic_source_query_window_review_drift"
                    )
                if (
                    latest.review_id != normalized_review_id
                    or latest.review_fingerprint != normalized_fingerprint
                ):
                    raise CiticSourceQueryWindowReviewRejected(
                        "citic_source_query_window_review_drift"
                    )
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
        except CiticSourceQueryWindowReviewRejected:
            raise
        except sqlite3.DatabaseError as exc:
            raise CiticSourceQueryWindowReviewRejected(
                "citic_source_query_window_review_store_unreadable"
            ) from exc

    def get_latest_review(
        self,
        intake_id: str,
    ) -> CiticSourceQueryWindowReview | None:
        with self._read_connection() as conn:
            if conn is None:
                return None
            row = self._latest_review_row(conn, intake_id)
        return _review_from_row(row) if row is not None else None

    def list_latest_reviews(
        self,
        *,
        limit: int = 200,
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
        return [_review_from_row(row) for row in rows]

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
                if schema_state != "complete":
                    raise CiticSourceQueryWindowReviewReadRejected(
                        "citic_source_query_window_review_schema_incomplete"
                    )
                yield conn
        except CiticSourceQueryWindowReviewReadRejected:
            raise
        except (OSError, sqlite3.DatabaseError) as exc:
            raise CiticSourceQueryWindowReviewReadRejected(
                "citic_source_query_window_review_store_unreadable"
            ) from exc

    def _require_current_follow_up_source(
        self,
        *,
        file_fingerprint: str,
        source_preview_fingerprint: str,
    ) -> None:
        try:
            CiticSourceIntakeRepository(self._path).list_intakes(limit=1)
        except CiticSourceIntakeReadRejected as exc:
            raise CiticSourceQueryWindowReviewRejected(exc.code) from exc
        if not self._path.is_file():
            raise CiticSourceQueryWindowReviewRejected(
                "citic_source_query_window_intake_missing"
            )
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
            raise CiticSourceQueryWindowReviewRejected(
                "citic_source_intake_store_unreadable"
            ) from exc
        self._validate_current_source_row(
            source,
            source_preview_fingerprint=source_preview_fingerprint,
        )

    def _ensure_schema(self) -> None:
        if not self._path.is_file():
            raise CiticSourceQueryWindowReviewRejected(
                "citic_source_query_window_intake_missing"
            )
        try:
            with sqlite3.connect(self._path) as conn:
                conn.row_factory = sqlite3.Row
                if self._schema_state(conn) == "incomplete":
                    raise CiticSourceQueryWindowReviewRejected(
                        "citic_source_query_window_review_schema_incompatible"
                    )
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS citic_source_query_window_reviews (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        review_id TEXT NOT NULL UNIQUE,
                        schema_version TEXT NOT NULL,
                        intake_id TEXT NOT NULL,
                        file_fingerprint TEXT NOT NULL,
                        source_preview_fingerprint TEXT NOT NULL,
                        query_start_date TEXT NOT NULL,
                        query_end_date TEXT NOT NULL,
                        query_window_attested INTEGER NOT NULL CHECK(
                            query_window_attested = 1
                        ),
                        decision TEXT NOT NULL CHECK(
                            decision IN ('accepted', 'revoked')
                        ),
                        supersedes_review_id TEXT,
                        reviewer TEXT NOT NULL,
                        review_fingerprint TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(intake_id)
                            REFERENCES citic_source_intakes(intake_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_citic_query_window_latest
                    ON citic_source_query_window_reviews(intake_id, id DESC);
                """)
                if self._schema_state(conn) != "complete":
                    raise CiticSourceQueryWindowReviewRejected(
                        "citic_source_query_window_review_schema_incompatible"
                    )
                conn.commit()
        except CiticSourceQueryWindowReviewRejected:
            raise
        except sqlite3.DatabaseError as exc:
            raise CiticSourceQueryWindowReviewRejected(
                "citic_source_query_window_review_store_unreadable"
            ) from exc

    @staticmethod
    def _schema_state(conn: sqlite3.Connection) -> str:
        table_name = "citic_source_query_window_reviews"
        tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if table_name not in tables:
            return "absent"
        columns = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        required = {
            "id",
            "review_id",
            "schema_version",
            "intake_id",
            "file_fingerprint",
            "source_preview_fingerprint",
            "query_start_date",
            "query_end_date",
            "query_window_attested",
            "decision",
            "supersedes_review_id",
            "reviewer",
            "review_fingerprint",
            "created_at",
        }
        return "complete" if required.issubset(columns) else "incomplete"

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

    @staticmethod
    def _validate_current_source_row(
        row: sqlite3.Row | None,
        *,
        source_preview_fingerprint: str,
    ) -> None:
        if row is None:
            raise CiticSourceQueryWindowReviewRejected(
                "citic_source_query_window_intake_missing"
            )
        if str(row["source_preview_fingerprint"]) != source_preview_fingerprint:
            raise CiticSourceQueryWindowReviewRejected(
                "citic_source_query_window_source_drift"
            )
        if int(row["recordable_for_follow_up"]) != 1:
            raise CiticSourceQueryWindowReviewRejected(
                "citic_source_query_window_source_not_recordable"
            )
        if str(row["review_status"]) != "follow_up_required":
            raise CiticSourceQueryWindowReviewRejected(
                "citic_source_query_window_source_not_pending"
            )

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

    @staticmethod
    def _insert_review(
        conn: sqlite3.Connection,
        *,
        intake_id: str,
        file_fingerprint: str,
        source_preview_fingerprint: str,
        query_start_date: str,
        query_end_date: str,
        decision: CiticSourceQueryWindowReviewDecision,
        supersedes_review_id: str | None,
        reviewer: str,
        created_at: str,
    ) -> CiticSourceQueryWindowReview:
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
        review_fingerprint = _review_fingerprint(payload)
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
        return _review_from_row(row)


def _normalized_review_inputs(
    *,
    preview: BrokerStatementPreview,
    expected_file_fingerprint: str,
    expected_source_preview_fingerprint: str,
    query_start_date: str,
    query_end_date: str,
    query_window_attested: bool,
    reviewer: str,
    today: date,
) -> dict[str, str]:
    if query_window_attested is not True:
        raise CiticSourceQueryWindowReviewRejected(
            "citic_source_query_window_attestation_missing"
        )
    if not citic_preview_is_recordable_for_follow_up(preview):
        raise CiticSourceQueryWindowReviewRejected(
            "citic_source_query_window_source_not_recordable"
        )
    file_fingerprint = expected_file_fingerprint.strip()
    source_preview_fingerprint = expected_source_preview_fingerprint.strip()
    if (
        not _FILE_FINGERPRINT.fullmatch(file_fingerprint)
        or file_fingerprint != preview.file_fingerprint
    ):
        raise CiticSourceQueryWindowReviewRejected(
            "citic_source_query_window_file_fingerprint_mismatch"
        )
    actual_preview_fingerprint = citic_source_preview_fingerprint(preview)
    if (
        not _FILE_FINGERPRINT.fullmatch(source_preview_fingerprint)
        or source_preview_fingerprint != actual_preview_fingerprint
    ):
        raise CiticSourceQueryWindowReviewRejected(
            "citic_source_query_window_source_preview_mismatch"
        )
    start = _date(query_start_date)
    end = _date(query_end_date)
    if start > end:
        raise CiticSourceQueryWindowReviewRejected(
            "citic_source_query_window_date_order_invalid"
        )
    if (end - start).days + 1 > _MAX_QUERY_WINDOW_DAYS:
        raise CiticSourceQueryWindowReviewRejected(
            "citic_source_query_window_exceeds_one_month"
        )
    if end > today:
        raise CiticSourceQueryWindowReviewRejected(
            "citic_source_query_window_future_date"
        )
    for event in preview.events:
        occurred_date = _aware_event_date(event.occurred_at)
        if occurred_date is None:
            raise CiticSourceQueryWindowReviewRejected(
                "citic_source_query_window_event_time_invalid"
            )
        if occurred_date < start or occurred_date > end:
            raise CiticSourceQueryWindowReviewRejected(
                "citic_source_query_window_event_outside_reviewed_range"
            )
    return {
        "file_fingerprint": file_fingerprint,
        "source_preview_fingerprint": source_preview_fingerprint,
        "query_start_date": start.isoformat(),
        "query_end_date": end.isoformat(),
        "reviewer": reviewer.strip() or "local_owner",
    }


def _same_accepted_window(
    review: CiticSourceQueryWindowReview,
    normalized: dict[str, str],
) -> bool:
    return (
        review.file_fingerprint == normalized["file_fingerprint"]
        and review.source_preview_fingerprint
        == normalized["source_preview_fingerprint"]
        and review.query_start_date == normalized["query_start_date"]
        and review.query_end_date == normalized["query_end_date"]
    )


def _review_from_row(row: sqlite3.Row) -> CiticSourceQueryWindowReview:
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
        start = _date(values["query_start_date"])
        end = _date(values["query_end_date"])
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except CiticSourceQueryWindowReviewRejected as exc:
        raise CiticSourceQueryWindowReviewReadRejected(
            "citic_source_query_window_review_record_invalid"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise CiticSourceQueryWindowReviewReadRejected(
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
        or (end - start).days + 1 > _MAX_QUERY_WINDOW_DAYS
        or not values["reviewer"].strip()
        or created.tzinfo is None
        or created.utcoffset() is None
        or not _EVIDENCE_FINGERPRINT.fullmatch(review_fingerprint)
        or review_fingerprint != _review_fingerprint(values)
    ):
        raise CiticSourceQueryWindowReviewReadRejected(
            "citic_source_query_window_review_record_invalid"
        )
    return CiticSourceQueryWindowReview(
        review_id=review_id,
        schema_version=values["schema_version"],
        intake_id=values["intake_id"],
        file_fingerprint=values["file_fingerprint"],
        source_preview_fingerprint=values["source_preview_fingerprint"],
        query_start_date=values["query_start_date"],
        query_end_date=values["query_end_date"],
        query_window_attested=True,
        decision=values["decision"],  # type: ignore[arg-type]
        supersedes_review_id=values["supersedes_review_id"],
        reviewer=values["reviewer"],
        review_fingerprint=review_fingerprint,
        created_at=created_at,
    )


def _review_fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _date(value: object) -> date:
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise CiticSourceQueryWindowReviewRejected(
            "citic_source_query_window_date_invalid"
        ) from None
    if parsed.isoformat() != str(value):
        raise CiticSourceQueryWindowReviewRejected(
            "citic_source_query_window_date_invalid"
        )
    return parsed


def _aware_event_date(value: object) -> date | None:
    try:
        occurred_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        return None
    return occurred_at.date()


def _aware_now(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CiticSourceQueryWindowReviewRejected(
            "citic_source_query_window_clock_invalid"
        )
    return value
