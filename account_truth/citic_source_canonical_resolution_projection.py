"""Fail-closed projection of persisted CITIC canonical-source resolutions."""

from __future__ import annotations

import json
import re
import sqlite3

from account_truth.citic_source_canonical_resolution_contracts import (
    CITIC_SOURCE_CANONICAL_EVIDENCE_FINGERPRINT_PATTERN,
    CITIC_SOURCE_CANONICAL_RESOLUTION_SCHEMA_VERSION,
)

_EVIDENCE_FINGERPRINT = re.compile(CITIC_SOURCE_CANONICAL_EVIDENCE_FINGERPRINT_PATTERN)


class CiticSourceCanonicalResolutionProjectionMixin:
    def _resolution_from_row(self, row: sqlite3.Row) -> object:
        try:
            sources = json.loads(str(row["source_preview_fingerprints_json"]))
            resolution = self._resolution_type(
                resolution_id=str(row["resolution_id"]),
                schema_version=str(row["schema_version"]),
                source_preview_fingerprints=sorted({str(item) for item in sources}),
                source_set_fingerprint=str(row["source_set_fingerprint"]),
                scope_review_id=str(row["scope_review_id"]),
                scope_review_import_run_id=str(row["scope_review_import_run_id"]),
                scope_review_fingerprint=str(row["scope_review_fingerprint"]),
                decision=str(row["decision"]),
                reviewer=str(row["reviewer"]),
                resolution_fingerprint=str(row["resolution_fingerprint"]),
                created_at=str(row["created_at"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise self._read_rejection_type(
                "citic_source_canonical_resolution_record_invalid"
            ) from exc
        try:
            expected_source_set_fingerprint = self._source_set_fingerprint(
                resolution.source_preview_fingerprints
            )
        except self._rejection_type as exc:
            raise self._read_rejection_type(
                "citic_source_canonical_resolution_record_invalid"
            ) from exc
        if (
            resolution.schema_version
            != CITIC_SOURCE_CANONICAL_RESOLUTION_SCHEMA_VERSION
            or resolution.decision not in {"accepted", "revoked"}
            or resolution.source_set_fingerprint != expected_source_set_fingerprint
            or not _EVIDENCE_FINGERPRINT.fullmatch(resolution.scope_review_fingerprint)
            or not _EVIDENCE_FINGERPRINT.fullmatch(resolution.resolution_fingerprint)
        ):
            raise self._read_rejection_type(
                "citic_source_canonical_resolution_record_invalid"
            )
        return resolution
