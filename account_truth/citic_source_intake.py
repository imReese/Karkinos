"""Persist privacy-minimized reviews of incomplete CITIC source files.

This store is deliberately separate from canonical broker evidence. It records
only a content fingerprint, validation counts/codes, required follow-up
evidence, and the operator's review disposition. Parsed transactions and
account details never enter these tables, and these rows are not eligible for
Account Truth reconciliation or execution gates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from account_truth.broker_statement import BrokerStatementPreview
from account_truth.citic_source_intake_contracts import (
    CITIC_SOURCE_FILE_FINGERPRINT_PATTERN,
    CITIC_SOURCE_INTAKE_SCHEMA_VERSION,
    CiticSourceReviewStatus,
)
from account_truth.citic_source_intake_projection import (
    CiticSourceIntakeProjectionMixin,
)
from account_truth.citic_source_intake_repository import (
    CiticSourceIntakeReadRepositoryMixin,
)
from account_truth.citic_source_intake_schema import CiticSourceIntakeSchemaMixin
from account_truth.citic_source_intake_uow import CiticSourceIntakeUnitOfWorkMixin
from account_truth.citic_source_intake_values import (
    citic_preview_is_recordable_for_follow_up as _preview_recordable,
)
from account_truth.citic_source_intake_values import (
    citic_source_intake_json,
)
from account_truth.citic_source_intake_values import (
    citic_source_preview_fingerprint as _preview_fingerprint,
)
from account_truth.citic_source_intake_values import (
    required_evidence_for_citic_preview as _required_evidence,
)

_FINGERPRINT_PATTERN = re.compile(CITIC_SOURCE_FILE_FINGERPRINT_PATTERN)


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
    return _required_evidence(preview)


def citic_preview_is_recordable_for_follow_up(
    preview: BrokerStatementPreview,
) -> bool:
    """Return whether a blocked preview is structurally useful follow-up evidence."""

    return _preview_recordable(preview)


def citic_source_preview_fingerprint(preview: BrokerStatementPreview) -> str:
    """Fingerprint only the sanitized, review-relevant preview identity."""

    return _preview_fingerprint(preview)


def _json(values: list[str]) -> str:
    return citic_source_intake_json(values)


def _json_list(value: object) -> list[str]:
    repository = object.__new__(CiticSourceIntakeRepository)
    return repository._json_list(value)


class CiticSourceIntakeRepository(
    CiticSourceIntakeUnitOfWorkMixin,
    CiticSourceIntakeReadRepositoryMixin,
    CiticSourceIntakeSchemaMixin,
    CiticSourceIntakeProjectionMixin,
):
    """Append-only operator reviews for non-authoritative CITIC source files."""

    _intake_type = CiticSourceIntake
    _intake_rejection_type = CiticSourceIntakeRejected
    _intake_read_rejection_type = CiticSourceIntakeReadRejected

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)

    def _preview_recordable(self, preview: BrokerStatementPreview) -> bool:
        return citic_preview_is_recordable_for_follow_up(preview)

    def _preview_fingerprint(self, preview: BrokerStatementPreview) -> str:
        return citic_source_preview_fingerprint(preview)

    def _required_evidence(self, preview: BrokerStatementPreview) -> list[str]:
        return required_evidence_for_citic_preview(preview)

    def _json(self, values: list[str]) -> str:
        return _json(values)

    def record_review(
        self,
        preview: BrokerStatementPreview,
        *,
        expected_file_fingerprint: str,
        review_status: CiticSourceReviewStatus,
        reviewer: str = "local",
    ) -> CiticSourceIntake:
        return super().record_review(
            preview,
            expected_file_fingerprint=expected_file_fingerprint,
            review_status=review_status,
            reviewer=reviewer,
        )

    def list_intakes(self, *, limit: int = 50) -> list[CiticSourceIntake]:
        return super().list_intakes(limit=limit)
