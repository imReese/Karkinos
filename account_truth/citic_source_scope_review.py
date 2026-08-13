"""Append-only owner reviews for the declared scope of one CITIC export.

The review is deliberately source-level evidence.  It binds an exact pending
source and its current query-window review to a privacy-minimized account
reference plus explicit market, asset, account-value-band, business, filter,
and export-completeness attestations.  The value band is source-query scope,
not a balance fact or capital authorization.  The review never promotes the
legacy XLS to canonical Account Truth and cannot authorize reconciliation,
execution, or capital.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterator, Literal

from account_truth.citic_source_intake import (
    CiticSourceIntakeReadRejected,
    CiticSourceIntakeRepository,
)
from account_truth.citic_source_query_window_review import (
    CiticSourceQueryWindowReviewReadRejected,
    CiticSourceQueryWindowReviewRepository,
)

CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_source_scope_review.v2"
)
_LEGACY_CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_source_scope_review.v1"
)
_SUPPORTED_SCHEMA_VERSIONS = {
    _LEGACY_CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION,
    CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION,
}
CiticSourceScopeReviewDecision = Literal["accepted", "revoked"]

_FILE_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_SCOPE_CODE = re.compile(r"^[a-z][a-z0-9_:-]{0,63}$")


class CiticSourceScopeReviewRejected(ValueError):
    """Raised when a source-scope review would weaken evidence boundaries."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CiticSourceScopeReviewReadRejected(RuntimeError):
    """Raised when persisted source-scope reviews cannot be read safely."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CiticSourceScopeReview:
    review_id: str
    schema_version: str
    intake_id: str
    file_fingerprint: str
    source_preview_fingerprint: str
    query_window_review_id: str
    query_window_review_fingerprint: str
    account_alias: str
    account_reference_hash: str
    account_type: str
    market_scopes: list[str]
    asset_classes: list[str]
    account_value_band: str | None
    business_types: list[str]
    no_other_filters_attested: bool
    complete_returned_results_attested: bool
    source_scope_attested: bool
    decision: CiticSourceScopeReviewDecision
    supersedes_review_id: str | None
    reviewer: str
    review_fingerprint: str
    created_at: str
    reused: bool = False


class CiticSourceScopeReviewRepository:
    """Persist exact source-scope reviews without persisting exported rows."""

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
        *,
        intake_id: str,
        expected_file_fingerprint: str,
        expected_source_preview_fingerprint: str,
        expected_query_window_review_id: str,
        expected_query_window_review_fingerprint: str,
        account_alias: str,
        account_reference_hash: str,
        account_type: str,
        market_scopes: list[str],
        asset_classes: list[str],
        account_value_band: str,
        business_types: list[str],
        no_other_filters_attested: bool,
        complete_returned_results_attested: bool,
        source_scope_attested: bool,
        reviewer: str = "local_owner",
    ) -> CiticSourceScopeReview:
        normalized = _normalized_review_inputs(
            intake_id=intake_id,
            expected_file_fingerprint=expected_file_fingerprint,
            expected_source_preview_fingerprint=(expected_source_preview_fingerprint),
            expected_query_window_review_id=expected_query_window_review_id,
            expected_query_window_review_fingerprint=(
                expected_query_window_review_fingerprint
            ),
            account_alias=account_alias,
            account_reference_hash=account_reference_hash,
            account_type=account_type,
            market_scopes=market_scopes,
            asset_classes=asset_classes,
            account_value_band=account_value_band,
            business_types=business_types,
            no_other_filters_attested=no_other_filters_attested,
            complete_returned_results_attested=(complete_returned_results_attested),
            source_scope_attested=source_scope_attested,
            reviewer=reviewer,
        )
        self._require_current_source_and_query_window(normalized)
        self._ensure_schema()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN IMMEDIATE")
            latest_row = self._latest_review_row(
                conn,
                str(normalized["intake_id"]),
            )
            supersedes_review_id: str | None = None
            if latest_row is not None:
                latest = _review_from_row(latest_row)
                if latest.decision == "accepted":
                    if _same_accepted_scope(latest, normalized):
                        conn.rollback()
                        return replace(latest, reused=True)
                    raise CiticSourceScopeReviewRejected(
                        "citic_source_scope_active_review_conflict"
                    )
                supersedes_review_id = latest.review_id
            saved = self._insert_review(
                conn,
                normalized=normalized,
                decision="accepted",
                supersedes_review_id=supersedes_review_id,
                created_at=_aware_now(self._clock()).isoformat(),
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
    ) -> CiticSourceScopeReview:
        normalized_intake_id = intake_id.strip()
        normalized_review_id = expected_active_review_id.strip()
        normalized_fingerprint = expected_active_review_fingerprint.strip()
        normalized_reviewer = reviewer.strip() or "local_owner"
        if not normalized_intake_id.startswith("citic_intake_"):
            raise CiticSourceScopeReviewRejected("citic_source_scope_intake_id_invalid")
        if not normalized_review_id.startswith("citic_scope_review_"):
            raise CiticSourceScopeReviewRejected("citic_source_scope_review_id_invalid")
        if not _EVIDENCE_FINGERPRINT.fullmatch(normalized_fingerprint):
            raise CiticSourceScopeReviewRejected(
                "citic_source_scope_review_fingerprint_invalid"
            )
        if not _safe_human_label(normalized_reviewer):
            raise CiticSourceScopeReviewRejected("citic_source_scope_reviewer_invalid")
        latest = self.get_latest_review(normalized_intake_id)
        if latest is None:
            raise CiticSourceScopeReviewRejected("citic_source_scope_review_missing")
        if latest.decision == "revoked":
            if latest.supersedes_review_id == normalized_review_id:
                return replace(latest, reused=True)
            raise CiticSourceScopeReviewRejected("citic_source_scope_review_superseded")
        if latest.review_id != normalized_review_id:
            raise CiticSourceScopeReviewRejected("citic_source_scope_review_superseded")
        if latest.review_fingerprint != normalized_fingerprint:
            raise CiticSourceScopeReviewRejected(
                "citic_source_scope_review_fingerprint_mismatch"
            )
        normalized = _review_payload(latest, reviewer=normalized_reviewer)
        self._ensure_schema()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            current_row = self._latest_review_row(conn, normalized_intake_id)
            if current_row is None or str(current_row["review_id"]) != latest.review_id:
                raise CiticSourceScopeReviewRejected(
                    "citic_source_scope_review_superseded"
                )
            saved = self._insert_review(
                conn,
                normalized=normalized,
                decision="revoked",
                supersedes_review_id=latest.review_id,
                created_at=_aware_now(self._clock()).isoformat(),
                schema_version=latest.schema_version,
            )
            conn.commit()
            return saved

    def get_latest_review(self, intake_id: str) -> CiticSourceScopeReview | None:
        with self._read_connection() as conn:
            if conn is None:
                return None
            row = self._latest_review_row(conn, intake_id.strip())
        return _review_from_row(row) if row is not None else None

    def list_latest_reviews(
        self,
        *,
        limit: int = 200,
    ) -> list[CiticSourceScopeReview]:
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
                if schema_state not in {"complete", "legacy_v1"}:
                    raise CiticSourceScopeReviewReadRejected(
                        "citic_source_scope_review_schema_incomplete"
                    )
                yield conn
        except CiticSourceScopeReviewReadRejected:
            raise
        except (OSError, sqlite3.DatabaseError) as exc:
            raise CiticSourceScopeReviewReadRejected(
                "citic_source_scope_review_store_unreadable"
            ) from exc

    def _require_current_source_and_query_window(
        self,
        normalized: dict[str, object],
    ) -> None:
        try:
            CiticSourceIntakeRepository(self._path).list_intakes(limit=1)
            query_review = CiticSourceQueryWindowReviewRepository(
                self._path
            ).get_latest_review(str(normalized["intake_id"]))
        except CiticSourceIntakeReadRejected as exc:
            raise CiticSourceScopeReviewRejected(exc.code) from exc
        except CiticSourceQueryWindowReviewReadRejected as exc:
            raise CiticSourceScopeReviewRejected(exc.code) from exc
        if not self._path.is_file():
            raise CiticSourceScopeReviewRejected("citic_source_scope_intake_missing")
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
            raise CiticSourceScopeReviewRejected(
                "citic_source_intake_store_unreadable"
            ) from exc
        if source is None:
            raise CiticSourceScopeReviewRejected("citic_source_scope_intake_missing")
        if (
            str(source["file_fingerprint"]) != normalized["file_fingerprint"]
            or str(source["source_preview_fingerprint"])
            != normalized["source_preview_fingerprint"]
        ):
            raise CiticSourceScopeReviewRejected("citic_source_scope_source_drift")
        if int(source["recordable_for_follow_up"]) != 1:
            raise CiticSourceScopeReviewRejected(
                "citic_source_scope_source_not_recordable"
            )
        if str(source["review_status"]) != "follow_up_required":
            raise CiticSourceScopeReviewRejected(
                "citic_source_scope_source_not_pending"
            )
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
            raise CiticSourceScopeReviewRejected(
                "citic_source_scope_query_window_review_mismatch"
            )

    def _ensure_schema(self) -> None:
        if not self._path.is_file():
            raise CiticSourceScopeReviewRejected("citic_source_scope_intake_missing")
        try:
            with sqlite3.connect(self._path) as conn:
                conn.row_factory = sqlite3.Row
                schema_state = self._schema_state(conn)
                if schema_state == "incomplete":
                    raise CiticSourceScopeReviewRejected(
                        "citic_source_scope_review_schema_incompatible"
                    )
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS citic_source_scope_reviews (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        review_id TEXT NOT NULL UNIQUE,
                        schema_version TEXT NOT NULL,
                        intake_id TEXT NOT NULL,
                        file_fingerprint TEXT NOT NULL,
                        source_preview_fingerprint TEXT NOT NULL,
                        query_window_review_id TEXT NOT NULL,
                        query_window_review_fingerprint TEXT NOT NULL,
                        account_alias TEXT NOT NULL,
                        account_reference_hash TEXT NOT NULL,
                        account_type TEXT NOT NULL,
                        market_scopes_json TEXT NOT NULL,
                        asset_classes_json TEXT NOT NULL,
                        account_value_band TEXT NOT NULL,
                        business_types_json TEXT NOT NULL,
                        no_other_filters_attested INTEGER NOT NULL CHECK(
                            no_other_filters_attested = 1
                        ),
                        complete_returned_results_attested INTEGER NOT NULL CHECK(
                            complete_returned_results_attested = 1
                        ),
                        source_scope_attested INTEGER NOT NULL CHECK(
                            source_scope_attested = 1
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

                    CREATE INDEX IF NOT EXISTS idx_citic_source_scope_latest
                    ON citic_source_scope_reviews(intake_id, id DESC);
                """)
                if schema_state == "legacy_v1":
                    conn.execute(
                        "ALTER TABLE citic_source_scope_reviews "
                        "ADD COLUMN account_value_band TEXT"
                    )
                if self._schema_state(conn) != "complete":
                    raise CiticSourceScopeReviewRejected(
                        "citic_source_scope_review_schema_incompatible"
                    )
                conn.commit()
        except CiticSourceScopeReviewRejected:
            raise
        except sqlite3.DatabaseError as exc:
            raise CiticSourceScopeReviewRejected(
                "citic_source_scope_review_store_unreadable"
            ) from exc

    @staticmethod
    def _schema_state(conn: sqlite3.Connection) -> str:
        table_name = "citic_source_scope_reviews"
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
        required_v1 = {
            "id",
            "review_id",
            "schema_version",
            "intake_id",
            "file_fingerprint",
            "source_preview_fingerprint",
            "query_window_review_id",
            "query_window_review_fingerprint",
            "account_alias",
            "account_reference_hash",
            "account_type",
            "market_scopes_json",
            "asset_classes_json",
            "business_types_json",
            "no_other_filters_attested",
            "complete_returned_results_attested",
            "source_scope_attested",
            "decision",
            "supersedes_review_id",
            "reviewer",
            "review_fingerprint",
            "created_at",
        }
        if not required_v1.issubset(columns):
            return "incomplete"
        return "complete" if "account_value_band" in columns else "legacy_v1"

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

    @staticmethod
    def _insert_review(
        conn: sqlite3.Connection,
        *,
        normalized: dict[str, object],
        decision: CiticSourceScopeReviewDecision,
        supersedes_review_id: str | None,
        created_at: str,
        schema_version: str = CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION,
    ) -> CiticSourceScopeReview:
        payload = _fingerprint_payload(
            normalized,
            schema_version=schema_version,
            decision=decision,
            supersedes_review_id=supersedes_review_id,
        )
        review_id = f"citic_scope_review_{uuid.uuid4().hex}"
        review_fingerprint = _review_fingerprint(payload)
        conn.execute(
            """
            INSERT INTO citic_source_scope_reviews (
                review_id, schema_version, intake_id, file_fingerprint,
                source_preview_fingerprint, query_window_review_id,
                query_window_review_fingerprint, account_alias,
                account_reference_hash, account_type, market_scopes_json,
                asset_classes_json, account_value_band, business_types_json,
                no_other_filters_attested,
                complete_returned_results_attested, source_scope_attested,
                decision, supersedes_review_id, reviewer,
                review_fingerprint, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                schema_version,
                normalized["intake_id"],
                normalized["file_fingerprint"],
                normalized["source_preview_fingerprint"],
                normalized["query_window_review_id"],
                normalized["query_window_review_fingerprint"],
                normalized["account_alias"],
                normalized["account_reference_hash"],
                normalized["account_type"],
                json.dumps(normalized["market_scopes"], separators=(",", ":")),
                json.dumps(normalized["asset_classes"], separators=(",", ":")),
                normalized["account_value_band"],
                json.dumps(normalized["business_types"], separators=(",", ":")),
                1,
                1,
                1,
                decision,
                supersedes_review_id,
                normalized["reviewer"],
                review_fingerprint,
                created_at,
            ),
        )
        row = conn.execute(
            "SELECT * FROM citic_source_scope_reviews WHERE review_id = ? LIMIT 1",
            (review_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("CITIC source-scope review disappeared")
        return _review_from_row(row)


def _normalized_review_inputs(
    *,
    intake_id: str,
    expected_file_fingerprint: str,
    expected_source_preview_fingerprint: str,
    expected_query_window_review_id: str,
    expected_query_window_review_fingerprint: str,
    account_alias: str,
    account_reference_hash: str,
    account_type: str,
    market_scopes: list[str],
    asset_classes: list[str],
    account_value_band: str | None,
    business_types: list[str],
    no_other_filters_attested: bool,
    complete_returned_results_attested: bool,
    source_scope_attested: bool,
    reviewer: str,
    allow_missing_account_value_band: bool = False,
) -> dict[str, object]:
    normalized = {
        "intake_id": intake_id.strip(),
        "file_fingerprint": expected_file_fingerprint.strip(),
        "source_preview_fingerprint": expected_source_preview_fingerprint.strip(),
        "query_window_review_id": expected_query_window_review_id.strip(),
        "query_window_review_fingerprint": (
            expected_query_window_review_fingerprint.strip()
        ),
        "account_alias": account_alias.strip(),
        "account_reference_hash": account_reference_hash.strip(),
        "account_type": account_type.strip().lower(),
        "market_scopes": _normalized_codes(market_scopes),
        "asset_classes": _normalized_codes(asset_classes),
        "account_value_band": (
            str(account_value_band).strip().lower()
            if account_value_band is not None
            else None
        ),
        "business_types": _normalized_codes(business_types),
        "no_other_filters_attested": no_other_filters_attested,
        "complete_returned_results_attested": complete_returned_results_attested,
        "source_scope_attested": source_scope_attested,
        "reviewer": reviewer.strip() or "local_owner",
    }
    if not str(normalized["intake_id"]).startswith("citic_intake_"):
        raise CiticSourceScopeReviewRejected("citic_source_scope_intake_id_invalid")
    if not _FILE_FINGERPRINT.fullmatch(str(normalized["file_fingerprint"])):
        raise CiticSourceScopeReviewRejected(
            "citic_source_scope_file_fingerprint_invalid"
        )
    if not _FILE_FINGERPRINT.fullmatch(str(normalized["source_preview_fingerprint"])):
        raise CiticSourceScopeReviewRejected(
            "citic_source_scope_preview_fingerprint_invalid"
        )
    if not str(normalized["query_window_review_id"]).startswith("citic_window_review_"):
        raise CiticSourceScopeReviewRejected(
            "citic_source_scope_query_window_review_id_invalid"
        )
    if not _EVIDENCE_FINGERPRINT.fullmatch(
        str(normalized["query_window_review_fingerprint"])
    ):
        raise CiticSourceScopeReviewRejected(
            "citic_source_scope_query_window_review_fingerprint_invalid"
        )
    if not _safe_human_label(str(normalized["account_alias"])):
        raise CiticSourceScopeReviewRejected("citic_source_scope_account_alias_invalid")
    if not _EVIDENCE_FINGERPRINT.fullmatch(str(normalized["account_reference_hash"])):
        raise CiticSourceScopeReviewRejected(
            "citic_source_scope_account_reference_invalid"
        )
    if not _SAFE_SCOPE_CODE.fullmatch(str(normalized["account_type"])):
        raise CiticSourceScopeReviewRejected("citic_source_scope_account_type_invalid")
    for key in ("market_scopes", "asset_classes", "business_types"):
        values = normalized[key]
        if not values or any(
            not _SAFE_SCOPE_CODE.fullmatch(str(value)) for value in values
        ):
            raise CiticSourceScopeReviewRejected(f"citic_source_scope_{key}_invalid")
    if normalized["account_value_band"] is None:
        if not allow_missing_account_value_band:
            raise CiticSourceScopeReviewRejected(
                "citic_source_scope_account_value_band_missing"
            )
    elif not _SAFE_SCOPE_CODE.fullmatch(str(normalized["account_value_band"])):
        raise CiticSourceScopeReviewRejected(
            "citic_source_scope_account_value_band_invalid"
        )
    if no_other_filters_attested is not True:
        raise CiticSourceScopeReviewRejected(
            "citic_source_scope_no_other_filters_attestation_missing"
        )
    if complete_returned_results_attested is not True:
        raise CiticSourceScopeReviewRejected(
            "citic_source_scope_complete_results_attestation_missing"
        )
    if source_scope_attested is not True:
        raise CiticSourceScopeReviewRejected("citic_source_scope_attestation_missing")
    if not _safe_human_label(str(normalized["reviewer"])):
        raise CiticSourceScopeReviewRejected("citic_source_scope_reviewer_invalid")
    return normalized


def _review_from_row(row: sqlite3.Row) -> CiticSourceScopeReview:
    try:
        schema_version = str(row["schema_version"])
        if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError("unsupported source-scope review schema")
        account_value_band = (
            str(row["account_value_band"])
            if "account_value_band" in row.keys()
            and row["account_value_band"] is not None
            else None
        )
        review = CiticSourceScopeReview(
            review_id=str(row["review_id"]),
            schema_version=schema_version,
            intake_id=str(row["intake_id"]),
            file_fingerprint=str(row["file_fingerprint"]),
            source_preview_fingerprint=str(row["source_preview_fingerprint"]),
            query_window_review_id=str(row["query_window_review_id"]),
            query_window_review_fingerprint=str(row["query_window_review_fingerprint"]),
            account_alias=str(row["account_alias"]),
            account_reference_hash=str(row["account_reference_hash"]),
            account_type=str(row["account_type"]),
            market_scopes=_stored_codes(row["market_scopes_json"]),
            asset_classes=_stored_codes(row["asset_classes_json"]),
            account_value_band=account_value_band,
            business_types=_stored_codes(row["business_types_json"]),
            no_other_filters_attested=_stored_true(row["no_other_filters_attested"]),
            complete_returned_results_attested=_stored_true(
                row["complete_returned_results_attested"]
            ),
            source_scope_attested=_stored_true(row["source_scope_attested"]),
            decision=str(row["decision"]),  # type: ignore[arg-type]
            supersedes_review_id=(
                str(row["supersedes_review_id"])
                if row["supersedes_review_id"] is not None
                else None
            ),
            reviewer=str(row["reviewer"]),
            review_fingerprint=str(row["review_fingerprint"]),
            created_at=str(row["created_at"]),
        )
        normalized = _normalized_review_inputs(
            intake_id=review.intake_id,
            expected_file_fingerprint=review.file_fingerprint,
            expected_source_preview_fingerprint=review.source_preview_fingerprint,
            expected_query_window_review_id=review.query_window_review_id,
            expected_query_window_review_fingerprint=(
                review.query_window_review_fingerprint
            ),
            account_alias=review.account_alias,
            account_reference_hash=review.account_reference_hash,
            account_type=review.account_type,
            market_scopes=review.market_scopes,
            asset_classes=review.asset_classes,
            account_value_band=review.account_value_band,
            business_types=review.business_types,
            no_other_filters_attested=review.no_other_filters_attested,
            complete_returned_results_attested=(
                review.complete_returned_results_attested
            ),
            source_scope_attested=review.source_scope_attested,
            reviewer=review.reviewer,
            allow_missing_account_value_band=(
                review.schema_version
                == _LEGACY_CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION
            ),
        )
        expected = _review_fingerprint(
            _fingerprint_payload(
                normalized,
                schema_version=review.schema_version,
                decision=review.decision,
                supersedes_review_id=review.supersedes_review_id,
            )
        )
        if (
            review.decision not in {"accepted", "revoked"}
            or not review.review_id.startswith("citic_scope_review_")
            or not _EVIDENCE_FINGERPRINT.fullmatch(review.review_fingerprint)
            or review.review_fingerprint != expected
            or not review.created_at.strip()
        ):
            raise ValueError("invalid source-scope review")
        return review
    except CiticSourceScopeReviewRejected as exc:
        raise CiticSourceScopeReviewReadRejected(
            "citic_source_scope_review_record_invalid"
        ) from exc
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CiticSourceScopeReviewReadRejected(
            "citic_source_scope_review_record_invalid"
        ) from exc


def _same_accepted_scope(
    review: CiticSourceScopeReview,
    normalized: dict[str, object],
) -> bool:
    return _review_payload(review, reviewer=review.reviewer) == normalized


def _review_payload(
    review: CiticSourceScopeReview,
    *,
    reviewer: str,
) -> dict[str, object]:
    return {
        "intake_id": review.intake_id,
        "file_fingerprint": review.file_fingerprint,
        "source_preview_fingerprint": review.source_preview_fingerprint,
        "query_window_review_id": review.query_window_review_id,
        "query_window_review_fingerprint": review.query_window_review_fingerprint,
        "account_alias": review.account_alias,
        "account_reference_hash": review.account_reference_hash,
        "account_type": review.account_type,
        "market_scopes": list(review.market_scopes),
        "asset_classes": list(review.asset_classes),
        "account_value_band": review.account_value_band,
        "business_types": list(review.business_types),
        "no_other_filters_attested": True,
        "complete_returned_results_attested": True,
        "source_scope_attested": True,
        "reviewer": reviewer,
    }


def _fingerprint_payload(
    normalized: dict[str, object],
    *,
    schema_version: str,
    decision: CiticSourceScopeReviewDecision,
    supersedes_review_id: str | None,
) -> dict[str, object]:
    payload = dict(normalized)
    if schema_version == _LEGACY_CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION:
        payload.pop("account_value_band", None)
    return {
        **payload,
        "schema_version": schema_version,
        "decision": decision,
        "supersedes_review_id": supersedes_review_id,
    }


def _normalized_codes(values: list[str]) -> list[str]:
    return sorted(
        {str(value).strip().lower() for value in values if str(value).strip()}
    )


def _stored_codes(value: object) -> list[str]:
    parsed = json.loads(str(value))
    if not isinstance(parsed, list) or any(
        not isinstance(item, str) for item in parsed
    ):
        raise ValueError("invalid source-scope codes")
    normalized = _normalized_codes(parsed)
    if normalized != parsed:
        raise ValueError("source-scope codes are not canonical")
    return normalized


def _stored_true(value: object) -> bool:
    if value != 1:
        raise ValueError("stored attestation is not true")
    return True


def _review_fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _safe_human_label(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= 128
        and all(
            character.isprintable() and character not in "\r\n\t" for character in value
        )
    )


def _aware_now(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CiticSourceScopeReviewRejected("citic_source_scope_clock_invalid")
    return value.astimezone(UTC)
