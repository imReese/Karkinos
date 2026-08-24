"""Append-only reviews of the query window used for one CITIC export.

This evidence is deliberately narrower than canonical Account Truth scope. It
binds an operator-attested start/end date to one already reviewed, exact source
fingerprint. It never persists parsed events and cannot satisfy account
binding, settlement, current-snapshot, reconciliation, execution, or capital
authority gates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Callable

from account_truth.broker_statement import BrokerStatementPreview
from account_truth.citic_source_intake import (
    CiticSourceIntakeReadRejected,
    CiticSourceIntakeRepository,
)
from account_truth.citic_source_query_window_review_contracts import (
    CITIC_SOURCE_QUERY_WINDOW_EVIDENCE_FINGERPRINT_PATTERN,
    CITIC_SOURCE_QUERY_WINDOW_FILE_FINGERPRINT_PATTERN,
    CITIC_SOURCE_QUERY_WINDOW_MAX_DAYS,
    CITIC_SOURCE_QUERY_WINDOW_REVIEW_SCHEMA_VERSION,
    CiticSourceQueryWindowReviewDecision,
)
from account_truth.citic_source_query_window_review_projection import (
    CiticSourceQueryWindowReviewProjectionMixin,
)
from account_truth.citic_source_query_window_review_repository import (
    CiticSourceQueryWindowReviewReadRepositoryMixin,
)
from account_truth.citic_source_query_window_review_schema import (
    CiticSourceQueryWindowReviewSchemaMixin,
)
from account_truth.citic_source_query_window_review_uow import (
    CiticSourceQueryWindowReviewUnitOfWorkMixin,
)
from account_truth.citic_source_query_window_review_values import (
    aware_citic_source_query_window_event_date,
    citic_source_query_window_review_fingerprint,
    normalize_citic_source_query_window_review_inputs,
    parse_citic_source_query_window_date,
    require_aware_citic_source_query_window_now,
    same_citic_source_accepted_window,
)

_FILE_FINGERPRINT = re.compile(CITIC_SOURCE_QUERY_WINDOW_FILE_FINGERPRINT_PATTERN)
_EVIDENCE_FINGERPRINT = re.compile(
    CITIC_SOURCE_QUERY_WINDOW_EVIDENCE_FINGERPRINT_PATTERN
)
_MAX_QUERY_WINDOW_DAYS = CITIC_SOURCE_QUERY_WINDOW_MAX_DAYS


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
    return normalize_citic_source_query_window_review_inputs(
        preview=preview,
        expected_file_fingerprint=expected_file_fingerprint,
        expected_source_preview_fingerprint=expected_source_preview_fingerprint,
        query_start_date=query_start_date,
        query_end_date=query_end_date,
        query_window_attested=query_window_attested,
        reviewer=reviewer,
        today=today,
        rejection=CiticSourceQueryWindowReviewRejected,
    )


def _same_accepted_window(
    review: CiticSourceQueryWindowReview,
    normalized: dict[str, str],
) -> bool:
    return same_citic_source_accepted_window(review, normalized)


def _review_fingerprint(payload: dict[str, object]) -> str:
    return citic_source_query_window_review_fingerprint(payload)


def _date(value: object) -> date:
    return parse_citic_source_query_window_date(
        value,
        rejection=CiticSourceQueryWindowReviewRejected,
    )


def _aware_event_date(value: object) -> date | None:
    return aware_citic_source_query_window_event_date(value)


def _aware_now(value: datetime) -> datetime:
    return require_aware_citic_source_query_window_now(
        value,
        rejection=CiticSourceQueryWindowReviewRejected,
    )


class CiticSourceQueryWindowReviewRepository(
    CiticSourceQueryWindowReviewUnitOfWorkMixin,
    CiticSourceQueryWindowReviewReadRepositoryMixin,
    CiticSourceQueryWindowReviewSchemaMixin,
    CiticSourceQueryWindowReviewProjectionMixin,
):
    """Persist exact-source window reviews without persisting source rows."""

    _review_type = CiticSourceQueryWindowReview
    _rejection_type = CiticSourceQueryWindowReviewRejected
    _read_rejection_type = CiticSourceQueryWindowReviewReadRejected
    _evidence_fingerprint = _EVIDENCE_FINGERPRINT

    def __init__(
        self,
        db_path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = Path(db_path)
        self._clock = clock or (lambda: datetime.now(UTC))

    def _intake_repository(self) -> CiticSourceIntakeRepository:
        return CiticSourceIntakeRepository(self._path)

    @property
    def _intake_read_rejection_type(self) -> type[CiticSourceIntakeReadRejected]:
        return CiticSourceIntakeReadRejected

    def _normalized_review_inputs(self, **kwargs: object) -> dict[str, str]:
        return _normalized_review_inputs(**kwargs)  # type: ignore[arg-type]

    def _same_accepted_window(
        self,
        review: CiticSourceQueryWindowReview,
        normalized: dict[str, str],
    ) -> bool:
        return _same_accepted_window(review, normalized)

    def _review_fingerprint(self, payload: dict[str, object]) -> str:
        return _review_fingerprint(payload)

    def _parse_date(self, value: object) -> date:
        return _date(value)

    def _aware_now(self, value: datetime) -> datetime:
        return _aware_now(value)

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
        return super().record_review(
            preview,
            expected_file_fingerprint=expected_file_fingerprint,
            expected_source_preview_fingerprint=expected_source_preview_fingerprint,
            query_start_date=query_start_date,
            query_end_date=query_end_date,
            query_window_attested=query_window_attested,
            reviewer=reviewer,
        )

    def revoke_latest(
        self,
        *,
        intake_id: str,
        expected_active_review_id: str,
        expected_active_review_fingerprint: str,
        reviewer: str = "local_owner",
    ) -> CiticSourceQueryWindowReview:
        return super().revoke_latest(
            intake_id=intake_id,
            expected_active_review_id=expected_active_review_id,
            expected_active_review_fingerprint=expected_active_review_fingerprint,
            reviewer=reviewer,
        )

    def get_latest_review(
        self,
        intake_id: str,
    ) -> CiticSourceQueryWindowReview | None:
        return super().get_latest_review(intake_id)

    def list_latest_reviews(
        self,
        *,
        limit: int = 200,
    ) -> list[CiticSourceQueryWindowReview]:
        return super().list_latest_reviews(limit=limit)


def _review_from_row(row: object) -> CiticSourceQueryWindowReview:
    repository = object.__new__(CiticSourceQueryWindowReviewRepository)
    return repository._review_from_row(row)  # type: ignore[arg-type]
