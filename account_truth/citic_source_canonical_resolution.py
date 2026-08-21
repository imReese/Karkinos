"""Append-only resolutions binding legacy CITIC sources to canonical Account Truth."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

CITIC_SOURCE_CANONICAL_RESOLUTION_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_source_canonical_resolution.v1"
)
CiticSourceCanonicalResolutionDecision = Literal["accepted", "revoked"]

_EVIDENCE_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_SOURCE_PREVIEW_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


class CiticSourceCanonicalResolutionRejected(ValueError):
    """Raised when a canonical coverage resolution cannot be recorded safely."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CiticSourceCanonicalResolutionReadRejected(RuntimeError):
    """Raised when persisted canonical coverage resolutions fail closed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CiticSourceCanonicalResolution:
    resolution_id: str
    schema_version: str
    source_preview_fingerprints: list[str]
    source_set_fingerprint: str
    scope_review_id: str
    scope_review_import_run_id: str
    scope_review_fingerprint: str
    decision: CiticSourceCanonicalResolutionDecision
    reviewer: str
    resolution_fingerprint: str
    created_at: str
    reused: bool = False


def citic_source_set_fingerprint(source_preview_fingerprints: list[str]) -> str:
    normalized = sorted({str(item).strip() for item in source_preview_fingerprints})
    if not normalized or any(
        not _SOURCE_PREVIEW_FINGERPRINT.fullmatch(item) for item in normalized
    ):
        raise CiticSourceCanonicalResolutionRejected(
            "citic_source_canonical_resolution_source_set_invalid"
        )
    return _fingerprint(
        {
            "schema_version": CITIC_SOURCE_CANONICAL_RESOLUTION_SCHEMA_VERSION,
            "source_preview_fingerprints": normalized,
        }
    )


class CiticSourceCanonicalResolutionRepository:
    """Persist revocable coverage decisions without changing financial facts."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)

    def record_resolution(
        self,
        *,
        source_preview_fingerprints: list[str],
        expected_source_set_fingerprint: str,
        scope_review_id: str,
        scope_review_import_run_id: str,
        scope_review_fingerprint: str,
        reviewer: str = "local_owner",
    ) -> CiticSourceCanonicalResolution:
        normalized_sources = sorted(
            {str(item).strip() for item in source_preview_fingerprints}
        )
        source_set_fingerprint = citic_source_set_fingerprint(normalized_sources)
        if expected_source_set_fingerprint != source_set_fingerprint:
            raise CiticSourceCanonicalResolutionRejected(
                "citic_source_canonical_resolution_source_set_drift"
            )
        normalized_review_id = str(scope_review_id).strip()
        normalized_import_id = str(scope_review_import_run_id).strip()
        normalized_review_fingerprint = str(scope_review_fingerprint).strip()
        normalized_reviewer = str(reviewer).strip()
        if not normalized_review_id or not normalized_import_id:
            raise CiticSourceCanonicalResolutionRejected(
                "citic_source_canonical_resolution_scope_binding_missing"
            )
        if not _EVIDENCE_FINGERPRINT.fullmatch(normalized_review_fingerprint):
            raise CiticSourceCanonicalResolutionRejected(
                "citic_source_canonical_resolution_scope_fingerprint_invalid"
            )
        if not normalized_reviewer:
            raise CiticSourceCanonicalResolutionRejected(
                "citic_source_canonical_resolution_reviewer_invalid"
            )

        payload = {
            "schema_version": CITIC_SOURCE_CANONICAL_RESOLUTION_SCHEMA_VERSION,
            "source_preview_fingerprints": normalized_sources,
            "source_set_fingerprint": source_set_fingerprint,
            "scope_review_id": normalized_review_id,
            "scope_review_import_run_id": normalized_import_id,
            "scope_review_fingerprint": normalized_review_fingerprint,
            "decision": "accepted",
            "reviewer": normalized_reviewer,
        }
        resolution_fingerprint = _fingerprint(payload)
        self._ensure_schema()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            latest = self._latest_row(conn)
            if latest is not None:
                existing = _resolution_from_row(latest)
                if existing.resolution_fingerprint == resolution_fingerprint:
                    conn.rollback()
                    return replace(existing, reused=True)
            resolution_id = f"citic_resolution_{uuid.uuid4().hex}"
            created_at = datetime.now(UTC).isoformat()
            conn.execute(
                """
                INSERT INTO citic_source_canonical_resolutions (
                    resolution_id, schema_version,
                    source_preview_fingerprints_json, source_set_fingerprint,
                    scope_review_id, scope_review_import_run_id,
                    scope_review_fingerprint, decision, reviewer,
                    resolution_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolution_id,
                    CITIC_SOURCE_CANONICAL_RESOLUTION_SCHEMA_VERSION,
                    _json(normalized_sources),
                    source_set_fingerprint,
                    normalized_review_id,
                    normalized_import_id,
                    normalized_review_fingerprint,
                    "accepted",
                    normalized_reviewer,
                    resolution_fingerprint,
                    created_at,
                ),
            )
            conn.commit()
            saved = self._latest_row(conn)
            if saved is None:
                raise RuntimeError("CITIC canonical resolution disappeared")
            return _resolution_from_row(saved)

    def revoke_latest(
        self,
        *,
        expected_resolution_id: str,
        expected_resolution_fingerprint: str,
        reviewer: str = "local_owner",
    ) -> CiticSourceCanonicalResolution:
        latest = self.get_latest()
        if latest is None or latest.decision != "accepted":
            raise CiticSourceCanonicalResolutionRejected(
                "citic_source_canonical_resolution_active_record_missing"
            )
        if latest.resolution_id != str(expected_resolution_id).strip():
            raise CiticSourceCanonicalResolutionRejected(
                "citic_source_canonical_resolution_id_mismatch"
            )
        if (
            latest.resolution_fingerprint
            != str(expected_resolution_fingerprint).strip()
        ):
            raise CiticSourceCanonicalResolutionRejected(
                "citic_source_canonical_resolution_fingerprint_mismatch"
            )
        normalized_reviewer = str(reviewer).strip()
        if not normalized_reviewer:
            raise CiticSourceCanonicalResolutionRejected(
                "citic_source_canonical_resolution_reviewer_invalid"
            )
        payload = {
            "schema_version": CITIC_SOURCE_CANONICAL_RESOLUTION_SCHEMA_VERSION,
            "source_preview_fingerprints": latest.source_preview_fingerprints,
            "source_set_fingerprint": latest.source_set_fingerprint,
            "scope_review_id": latest.scope_review_id,
            "scope_review_import_run_id": latest.scope_review_import_run_id,
            "scope_review_fingerprint": latest.scope_review_fingerprint,
            "decision": "revoked",
            "reviewer": normalized_reviewer,
            "revokes_resolution_id": latest.resolution_id,
        }
        resolution_fingerprint = _fingerprint(payload)
        self._ensure_schema()
        with sqlite3.connect(self._path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            resolution_id = f"citic_resolution_{uuid.uuid4().hex}"
            created_at = datetime.now(UTC).isoformat()
            conn.execute(
                """
                INSERT INTO citic_source_canonical_resolutions (
                    resolution_id, schema_version,
                    source_preview_fingerprints_json, source_set_fingerprint,
                    scope_review_id, scope_review_import_run_id,
                    scope_review_fingerprint, decision, reviewer,
                    resolution_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolution_id,
                    CITIC_SOURCE_CANONICAL_RESOLUTION_SCHEMA_VERSION,
                    _json(latest.source_preview_fingerprints),
                    latest.source_set_fingerprint,
                    latest.scope_review_id,
                    latest.scope_review_import_run_id,
                    latest.scope_review_fingerprint,
                    "revoked",
                    normalized_reviewer,
                    resolution_fingerprint,
                    created_at,
                ),
            )
            conn.commit()
        revoked = self.get_latest()
        if revoked is None:
            raise RuntimeError("CITIC canonical resolution disappeared")
        return revoked

    def get_latest(self) -> CiticSourceCanonicalResolution | None:
        if not self._path.is_file():
            return None
        try:
            read_uri = f"{self._path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(read_uri, uri=True) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only = ON")
                schema_state = self._schema_state(conn)
                if schema_state == "absent":
                    return None
                if schema_state != "complete":
                    raise CiticSourceCanonicalResolutionReadRejected(
                        "citic_source_canonical_resolution_schema_incomplete"
                    )
                row = self._latest_row(conn)
                return _resolution_from_row(row) if row is not None else None
        except CiticSourceCanonicalResolutionReadRejected:
            raise
        except sqlite3.Error as exc:
            raise CiticSourceCanonicalResolutionReadRejected(
                "citic_source_canonical_resolution_store_unreadable"
            ) from exc

    def _ensure_schema(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            schema_state = self._schema_state(conn)
            if schema_state == "partial":
                raise CiticSourceCanonicalResolutionRejected(
                    "citic_source_canonical_resolution_schema_incompatible"
                )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS citic_source_canonical_resolutions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resolution_id TEXT NOT NULL UNIQUE,
                    schema_version TEXT NOT NULL,
                    source_preview_fingerprints_json TEXT NOT NULL,
                    source_set_fingerprint TEXT NOT NULL,
                    scope_review_id TEXT NOT NULL,
                    scope_review_import_run_id TEXT NOT NULL,
                    scope_review_fingerprint TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('accepted', 'revoked')),
                    reviewer TEXT NOT NULL,
                    resolution_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """)
            conn.commit()

    @staticmethod
    def _schema_state(conn: sqlite3.Connection) -> str:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("citic_source_canonical_resolutions",),
        ).fetchone()
        if row is None:
            return "absent"
        columns = {
            str(item[1])
            for item in conn.execute(
                "PRAGMA table_info(citic_source_canonical_resolutions)"
            ).fetchall()
        }
        required = {
            "id",
            "resolution_id",
            "schema_version",
            "source_preview_fingerprints_json",
            "source_set_fingerprint",
            "scope_review_id",
            "scope_review_import_run_id",
            "scope_review_fingerprint",
            "decision",
            "reviewer",
            "resolution_fingerprint",
            "created_at",
        }
        return "complete" if required.issubset(columns) else "partial"

    @staticmethod
    def _latest_row(conn: sqlite3.Connection) -> sqlite3.Row | None:
        return conn.execute("""
            SELECT * FROM citic_source_canonical_resolutions
            ORDER BY id DESC
            LIMIT 1
            """).fetchone()


def _resolution_from_row(row: sqlite3.Row) -> CiticSourceCanonicalResolution:
    try:
        sources = json.loads(str(row["source_preview_fingerprints_json"]))
        resolution = CiticSourceCanonicalResolution(
            resolution_id=str(row["resolution_id"]),
            schema_version=str(row["schema_version"]),
            source_preview_fingerprints=sorted({str(item) for item in sources}),
            source_set_fingerprint=str(row["source_set_fingerprint"]),
            scope_review_id=str(row["scope_review_id"]),
            scope_review_import_run_id=str(row["scope_review_import_run_id"]),
            scope_review_fingerprint=str(row["scope_review_fingerprint"]),
            decision=str(row["decision"]),  # type: ignore[arg-type]
            reviewer=str(row["reviewer"]),
            resolution_fingerprint=str(row["resolution_fingerprint"]),
            created_at=str(row["created_at"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CiticSourceCanonicalResolutionReadRejected(
            "citic_source_canonical_resolution_record_invalid"
        ) from exc
    try:
        expected_source_set_fingerprint = citic_source_set_fingerprint(
            resolution.source_preview_fingerprints
        )
    except CiticSourceCanonicalResolutionRejected as exc:
        raise CiticSourceCanonicalResolutionReadRejected(
            "citic_source_canonical_resolution_record_invalid"
        ) from exc
    if (
        resolution.schema_version != CITIC_SOURCE_CANONICAL_RESOLUTION_SCHEMA_VERSION
        or resolution.decision not in {"accepted", "revoked"}
        or resolution.source_set_fingerprint != expected_source_set_fingerprint
        or not _EVIDENCE_FINGERPRINT.fullmatch(resolution.scope_review_fingerprint)
        or not _EVIDENCE_FINGERPRINT.fullmatch(resolution.resolution_fingerprint)
    ):
        raise CiticSourceCanonicalResolutionReadRejected(
            "citic_source_canonical_resolution_record_invalid"
        )
    return resolution


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
