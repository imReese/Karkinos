"""Append-only resolutions binding legacy CITIC sources to canonical Account Truth."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from account_truth.citic_source_canonical_resolution_contracts import (
    CITIC_SOURCE_CANONICAL_EVIDENCE_FINGERPRINT_PATTERN,
    CITIC_SOURCE_CANONICAL_RESOLUTION_SCHEMA_VERSION,
    CITIC_SOURCE_PREVIEW_FINGERPRINT_PATTERN,
    CiticSourceCanonicalResolutionDecision,
)
from account_truth.citic_source_canonical_resolution_projection import (
    CiticSourceCanonicalResolutionProjectionMixin,
)
from account_truth.citic_source_canonical_resolution_repository import (
    CiticSourceCanonicalResolutionReadRepositoryMixin,
)
from account_truth.citic_source_canonical_resolution_schema import (
    CiticSourceCanonicalResolutionSchemaMixin,
)
from account_truth.citic_source_canonical_resolution_uow import (
    CiticSourceCanonicalResolutionUnitOfWorkMixin,
)
from account_truth.citic_source_canonical_resolution_values import (
    citic_source_resolution_fingerprint,
    citic_source_resolution_json,
    citic_source_set_fingerprint_value,
    normalized_citic_source_preview_fingerprints,
)

_EVIDENCE_FINGERPRINT = re.compile(CITIC_SOURCE_CANONICAL_EVIDENCE_FINGERPRINT_PATTERN)
_SOURCE_PREVIEW_FINGERPRINT = re.compile(CITIC_SOURCE_PREVIEW_FINGERPRINT_PATTERN)


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
    normalized = normalized_citic_source_preview_fingerprints(
        source_preview_fingerprints
    )
    if normalized is None:
        raise CiticSourceCanonicalResolutionRejected(
            "citic_source_canonical_resolution_source_set_invalid"
        )
    return citic_source_set_fingerprint_value(normalized)


def _fingerprint(payload: object) -> str:
    return citic_source_resolution_fingerprint(payload)


def _json(value: object) -> str:
    return citic_source_resolution_json(value)


class CiticSourceCanonicalResolutionRepository(
    CiticSourceCanonicalResolutionUnitOfWorkMixin,
    CiticSourceCanonicalResolutionReadRepositoryMixin,
    CiticSourceCanonicalResolutionSchemaMixin,
    CiticSourceCanonicalResolutionProjectionMixin,
):
    """Persist revocable coverage decisions without changing financial facts."""

    _resolution_type = CiticSourceCanonicalResolution
    _rejection_type = CiticSourceCanonicalResolutionRejected
    _read_rejection_type = CiticSourceCanonicalResolutionReadRejected
    _evidence_fingerprint = _EVIDENCE_FINGERPRINT

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)

    def _source_set_fingerprint(self, source_preview_fingerprints: list[str]) -> str:
        return citic_source_set_fingerprint(source_preview_fingerprints)

    def _resolution_fingerprint(self, payload: object) -> str:
        return _fingerprint(payload)

    def _resolution_json(self, value: object) -> str:
        return _json(value)

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
        return super().record_resolution(
            source_preview_fingerprints=source_preview_fingerprints,
            expected_source_set_fingerprint=expected_source_set_fingerprint,
            scope_review_id=scope_review_id,
            scope_review_import_run_id=scope_review_import_run_id,
            scope_review_fingerprint=scope_review_fingerprint,
            reviewer=reviewer,
        )

    def revoke_latest(
        self,
        *,
        expected_resolution_id: str,
        expected_resolution_fingerprint: str,
        reviewer: str = "local_owner",
    ) -> CiticSourceCanonicalResolution:
        return super().revoke_latest(
            expected_resolution_id=expected_resolution_id,
            expected_resolution_fingerprint=expected_resolution_fingerprint,
            reviewer=reviewer,
        )

    def get_latest(self) -> CiticSourceCanonicalResolution | None:
        return super().get_latest()


def _resolution_from_row(row: object) -> CiticSourceCanonicalResolution:
    repository = object.__new__(CiticSourceCanonicalResolutionRepository)
    return repository._resolution_from_row(row)  # type: ignore[arg-type]
