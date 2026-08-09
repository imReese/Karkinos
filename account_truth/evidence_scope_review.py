"""Append-only human reviews for Account Truth evidence scope.

The review binds one exact canonical broker import to a privacy-minimized
account reference, a declared date window, and an explicitly attested asset
scope.  It does not change broker evidence, reconciliation, the production
ledger, execution authority, or capital authority.
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
from typing import Iterator, Literal

ACCOUNT_TRUTH_EVIDENCE_SCOPE_REVIEW_SCHEMA_VERSION = (
    "karkinos.account_truth.evidence_scope_review.v1"
)
EvidenceScopeReviewDecision = Literal["accepted", "revoked"]

_FILE_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_PROVIDER = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{0,63}$")
_SAFE_ASSET_CLASS = re.compile(r"^[a-z][a-z0-9_:-]{0,63}$")


class EvidenceScopeReviewRejected(ValueError):
    """Raised when a scope review would weaken deterministic boundaries."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class EvidenceScopeReviewReadRejected(RuntimeError):
    """Raised when persisted scope reviews cannot be read safely."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class EvidenceScopeReview:
    review_id: str
    schema_version: str
    import_run_id: str
    import_file_fingerprint: str
    observed_scope_fingerprint: str
    provider: str
    account_alias: str
    account_reference_hash: str
    coverage_start_date: str
    coverage_end_date: str
    asset_classes: list[str]
    full_account_scope_attested: bool
    decision: EvidenceScopeReviewDecision
    reviewer: str
    review_fingerprint: str
    created_at: str
    reused: bool = False


class EvidenceScopeReviewRepository:
    """Persist exact-scope owner reviews without mutating financial facts."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)

    def record_review(
        self,
        *,
        import_run_id: str,
        import_file_fingerprint: str,
        observed_scope_fingerprint: str,
        provider: str,
        account_alias: str,
        account_reference_hash: str,
        coverage_start_date: str,
        coverage_end_date: str,
        asset_classes: list[str],
        full_account_scope_attested: bool,
        decision: EvidenceScopeReviewDecision = "accepted",
        reviewer: str = "local_owner",
    ) -> EvidenceScopeReview:
        normalized = _normalized_review_inputs(
            import_run_id=import_run_id,
            import_file_fingerprint=import_file_fingerprint,
            observed_scope_fingerprint=observed_scope_fingerprint,
            provider=provider,
            account_alias=account_alias,
            account_reference_hash=account_reference_hash,
            coverage_start_date=coverage_start_date,
            coverage_end_date=coverage_end_date,
            asset_classes=asset_classes,
            full_account_scope_attested=full_account_scope_attested,
            decision=decision,
            reviewer=reviewer,
        )
        review_fingerprint = _review_fingerprint(normalized)
        self._ensure_schema()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            latest = self._latest_review_row(conn, normalized["import_run_id"])
            if latest is not None:
                existing = _review_from_row(latest)
                if existing.review_fingerprint == review_fingerprint:
                    conn.rollback()
                    return replace(existing, reused=True)
            review_id = f"scope_review_{uuid.uuid4().hex}"
            created_at = datetime.now(UTC).isoformat()
            conn.execute(
                """
                INSERT INTO account_truth_evidence_scope_reviews (
                    review_id, schema_version, import_run_id,
                    import_file_fingerprint, observed_scope_fingerprint,
                    provider, account_alias, account_reference_hash,
                    coverage_start_date, coverage_end_date, asset_classes_json,
                    full_account_scope_attested, decision, reviewer,
                    review_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    ACCOUNT_TRUTH_EVIDENCE_SCOPE_REVIEW_SCHEMA_VERSION,
                    normalized["import_run_id"],
                    normalized["import_file_fingerprint"],
                    normalized["observed_scope_fingerprint"],
                    normalized["provider"],
                    normalized["account_alias"],
                    normalized["account_reference_hash"],
                    normalized["coverage_start_date"],
                    normalized["coverage_end_date"],
                    json.dumps(normalized["asset_classes"], separators=(",", ":")),
                    1,
                    normalized["decision"],
                    normalized["reviewer"],
                    review_fingerprint,
                    created_at,
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM account_truth_evidence_scope_reviews
                WHERE review_id = ?
                LIMIT 1
                """,
                (review_id,),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("Account Truth evidence-scope review was not persisted")
        return _review_from_row(row)

    def revoke_latest(
        self,
        *,
        import_run_id: str,
        expected_observed_scope_fingerprint: str,
        reviewer: str = "local_owner",
    ) -> EvidenceScopeReview:
        latest = self.get_latest_review(import_run_id)
        if latest is None:
            raise EvidenceScopeReviewRejected(
                "account_truth_evidence_scope_review_missing"
            )
        if latest.observed_scope_fingerprint != expected_observed_scope_fingerprint:
            raise EvidenceScopeReviewRejected(
                "account_truth_evidence_scope_review_fingerprint_mismatch"
            )
        if latest.decision == "revoked":
            return replace(latest, reused=True)
        return self.record_review(
            import_run_id=latest.import_run_id,
            import_file_fingerprint=latest.import_file_fingerprint,
            observed_scope_fingerprint=latest.observed_scope_fingerprint,
            provider=latest.provider,
            account_alias=latest.account_alias,
            account_reference_hash=latest.account_reference_hash,
            coverage_start_date=latest.coverage_start_date,
            coverage_end_date=latest.coverage_end_date,
            asset_classes=latest.asset_classes,
            full_account_scope_attested=True,
            decision="revoked",
            reviewer=reviewer,
        )

    def get_latest_review(self, import_run_id: str) -> EvidenceScopeReview | None:
        with self._read_connection() as conn:
            if conn is None:
                return None
            row = self._latest_review_row(conn, import_run_id)
        return _review_from_row(row) if row is not None else None

    def list_review_history(self, import_run_id: str) -> list[EvidenceScopeReview]:
        with self._read_connection() as conn:
            if conn is None:
                return []
            rows = conn.execute(
                """
                SELECT * FROM account_truth_evidence_scope_reviews
                WHERE import_run_id = ?
                ORDER BY id ASC
                """,
                (import_run_id,),
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
                    raise EvidenceScopeReviewReadRejected(
                        "account_truth_evidence_scope_review_schema_incomplete"
                    )
                yield conn
        except EvidenceScopeReviewReadRejected:
            raise
        except (OSError, sqlite3.DatabaseError) as exc:
            raise EvidenceScopeReviewReadRejected(
                "account_truth_evidence_scope_review_store_unreadable"
            ) from exc

    def _ensure_schema(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            if self._schema_state(conn) == "incomplete":
                raise EvidenceScopeReviewRejected(
                    "account_truth_evidence_scope_review_schema_incompatible"
                )
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS account_truth_evidence_scope_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    review_id TEXT NOT NULL UNIQUE,
                    schema_version TEXT NOT NULL,
                    import_run_id TEXT NOT NULL,
                    import_file_fingerprint TEXT NOT NULL,
                    observed_scope_fingerprint TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    account_alias TEXT NOT NULL,
                    account_reference_hash TEXT NOT NULL,
                    coverage_start_date TEXT NOT NULL,
                    coverage_end_date TEXT NOT NULL,
                    asset_classes_json TEXT NOT NULL,
                    full_account_scope_attested INTEGER NOT NULL,
                    decision TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    review_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_account_truth_scope_reviews_latest
                ON account_truth_evidence_scope_reviews(import_run_id, id DESC);
            """)
            if self._schema_state(conn) != "complete":
                raise EvidenceScopeReviewRejected(
                    "account_truth_evidence_scope_review_schema_incompatible"
                )
            conn.commit()

    @staticmethod
    def _schema_state(conn: sqlite3.Connection) -> str:
        table_name = "account_truth_evidence_scope_reviews"
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
            "import_run_id",
            "import_file_fingerprint",
            "observed_scope_fingerprint",
            "provider",
            "account_alias",
            "account_reference_hash",
            "coverage_start_date",
            "coverage_end_date",
            "asset_classes_json",
            "full_account_scope_attested",
            "decision",
            "reviewer",
            "review_fingerprint",
            "created_at",
        }
        return "complete" if required.issubset(columns) else "incomplete"

    @staticmethod
    def _latest_review_row(
        conn: sqlite3.Connection,
        import_run_id: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT * FROM account_truth_evidence_scope_reviews
            WHERE import_run_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (import_run_id,),
        ).fetchone()


def _normalized_review_inputs(
    *,
    import_run_id: str,
    import_file_fingerprint: str,
    observed_scope_fingerprint: str,
    provider: str,
    account_alias: str,
    account_reference_hash: str,
    coverage_start_date: str,
    coverage_end_date: str,
    asset_classes: list[str],
    full_account_scope_attested: bool,
    decision: str,
    reviewer: str,
) -> dict[str, object]:
    normalized_import_run_id = import_run_id.strip()
    normalized_provider = provider.strip().lower()
    normalized_account_alias = account_alias.strip()
    normalized_reviewer = reviewer.strip() or "local_owner"
    normalized_assets = sorted(
        {str(asset).strip().lower() for asset in asset_classes if str(asset).strip()}
    )
    if not normalized_import_run_id:
        raise EvidenceScopeReviewRejected("account_truth_evidence_scope_import_missing")
    if not _FILE_FINGERPRINT.fullmatch(import_file_fingerprint):
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_import_fingerprint_invalid"
        )
    if not _EVIDENCE_FINGERPRINT.fullmatch(observed_scope_fingerprint):
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_observed_fingerprint_invalid"
        )
    if not _SAFE_PROVIDER.fullmatch(normalized_provider):
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_provider_invalid"
        )
    if not _safe_human_label(normalized_account_alias):
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_account_alias_invalid"
        )
    if not _EVIDENCE_FINGERPRINT.fullmatch(account_reference_hash):
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_account_reference_invalid"
        )
    start = _review_date(coverage_start_date)
    end = _review_date(coverage_end_date)
    if start is None or end is None or start > end:
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_coverage_window_invalid"
        )
    if not normalized_assets or any(
        not _SAFE_ASSET_CLASS.fullmatch(asset) for asset in normalized_assets
    ):
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_asset_classes_invalid"
        )
    if full_account_scope_attested is not True:
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_attestation_required"
        )
    if decision not in {"accepted", "revoked"}:
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_review_decision_invalid"
        )
    if not _safe_human_label(normalized_reviewer):
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_reviewer_invalid"
        )
    return {
        "schema_version": ACCOUNT_TRUTH_EVIDENCE_SCOPE_REVIEW_SCHEMA_VERSION,
        "import_run_id": normalized_import_run_id,
        "import_file_fingerprint": import_file_fingerprint,
        "observed_scope_fingerprint": observed_scope_fingerprint,
        "provider": normalized_provider,
        "account_alias": normalized_account_alias,
        "account_reference_hash": account_reference_hash,
        "coverage_start_date": start.isoformat(),
        "coverage_end_date": end.isoformat(),
        "asset_classes": normalized_assets,
        "full_account_scope_attested": True,
        "decision": decision,
        "reviewer": normalized_reviewer,
    }


def _review_from_row(row: sqlite3.Row) -> EvidenceScopeReview:
    try:
        assets = json.loads(str(row["asset_classes_json"]))
        if not isinstance(assets, list) or any(
            not isinstance(item, str) for item in assets
        ):
            raise ValueError("invalid asset classes")
        review = EvidenceScopeReview(
            review_id=str(row["review_id"]),
            schema_version=str(row["schema_version"]),
            import_run_id=str(row["import_run_id"]),
            import_file_fingerprint=str(row["import_file_fingerprint"]),
            observed_scope_fingerprint=str(row["observed_scope_fingerprint"]),
            provider=str(row["provider"]),
            account_alias=str(row["account_alias"]),
            account_reference_hash=str(row["account_reference_hash"]),
            coverage_start_date=str(row["coverage_start_date"]),
            coverage_end_date=str(row["coverage_end_date"]),
            asset_classes=list(assets),
            full_account_scope_attested=_stored_bool(
                row["full_account_scope_attested"]
            ),
            decision=str(row["decision"]),  # type: ignore[arg-type]
            reviewer=str(row["reviewer"]),
            review_fingerprint=str(row["review_fingerprint"]),
            created_at=str(row["created_at"]),
        )
        normalized = _normalized_review_inputs(
            import_run_id=review.import_run_id,
            import_file_fingerprint=review.import_file_fingerprint,
            observed_scope_fingerprint=review.observed_scope_fingerprint,
            provider=review.provider,
            account_alias=review.account_alias,
            account_reference_hash=review.account_reference_hash,
            coverage_start_date=review.coverage_start_date,
            coverage_end_date=review.coverage_end_date,
            asset_classes=review.asset_classes,
            full_account_scope_attested=review.full_account_scope_attested,
            decision=review.decision,
            reviewer=review.reviewer,
        )
        if (
            review.schema_version != ACCOUNT_TRUTH_EVIDENCE_SCOPE_REVIEW_SCHEMA_VERSION
            or review.review_fingerprint != _review_fingerprint(normalized)
        ):
            raise ValueError("review fingerprint mismatch")
        return review
    except EvidenceScopeReviewRejected as exc:
        raise EvidenceScopeReviewReadRejected(
            "account_truth_evidence_scope_review_record_invalid"
        ) from exc
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise EvidenceScopeReviewReadRejected(
            "account_truth_evidence_scope_review_record_invalid"
        ) from exc


def _review_fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _review_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def _safe_human_label(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= 128
        and all(
            character.isprintable() and character not in "\r\n\t" for character in value
        )
    )


def _stored_bool(value: object) -> bool:
    if value not in {0, 1}:
        raise ValueError("invalid stored boolean")
    return bool(value)
