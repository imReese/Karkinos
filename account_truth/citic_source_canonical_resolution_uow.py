"""Atomic writes for revocable CITIC canonical-source resolutions."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import replace
from datetime import UTC, datetime

from account_truth.citic_source_canonical_resolution_contracts import (
    CITIC_SOURCE_CANONICAL_RESOLUTION_SCHEMA_VERSION,
)


class CiticSourceCanonicalResolutionUnitOfWorkMixin:
    def record_resolution(
        self,
        *,
        source_preview_fingerprints: list[str],
        expected_source_set_fingerprint: str,
        scope_review_id: str,
        scope_review_import_run_id: str,
        scope_review_fingerprint: str,
        reviewer: str = "local_owner",
    ) -> object:
        normalized_sources = sorted(
            {str(item).strip() for item in source_preview_fingerprints}
        )
        source_set_fingerprint = self._source_set_fingerprint(normalized_sources)
        if expected_source_set_fingerprint != source_set_fingerprint:
            raise self._rejection_type(
                "citic_source_canonical_resolution_source_set_drift"
            )
        normalized_review_id = str(scope_review_id).strip()
        normalized_import_id = str(scope_review_import_run_id).strip()
        normalized_review_fingerprint = str(scope_review_fingerprint).strip()
        normalized_reviewer = str(reviewer).strip()
        if not normalized_review_id or not normalized_import_id:
            raise self._rejection_type(
                "citic_source_canonical_resolution_scope_binding_missing"
            )
        if not self._evidence_fingerprint.fullmatch(normalized_review_fingerprint):
            raise self._rejection_type(
                "citic_source_canonical_resolution_scope_fingerprint_invalid"
            )
        if not normalized_reviewer:
            raise self._rejection_type(
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
        resolution_fingerprint = self._resolution_fingerprint(payload)
        self._ensure_schema()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            latest = self._latest_row(conn)
            if latest is not None:
                existing = self._resolution_from_row(latest)
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
                    self._resolution_json(normalized_sources),
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
            return self._resolution_from_row(saved)

    def revoke_latest(
        self,
        *,
        expected_resolution_id: str,
        expected_resolution_fingerprint: str,
        reviewer: str = "local_owner",
    ) -> object:
        latest = self.get_latest()
        if latest is None or latest.decision != "accepted":
            raise self._rejection_type(
                "citic_source_canonical_resolution_active_record_missing"
            )
        if latest.resolution_id != str(expected_resolution_id).strip():
            raise self._rejection_type("citic_source_canonical_resolution_id_mismatch")
        if (
            latest.resolution_fingerprint
            != str(expected_resolution_fingerprint).strip()
        ):
            raise self._rejection_type(
                "citic_source_canonical_resolution_fingerprint_mismatch"
            )
        normalized_reviewer = str(reviewer).strip()
        if not normalized_reviewer:
            raise self._rejection_type(
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
        resolution_fingerprint = self._resolution_fingerprint(payload)
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
                    self._resolution_json(latest.source_preview_fingerprints),
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
