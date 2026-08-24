"""Append-only owner reviews for the declared scope of one CITIC export.

The review is deliberately source-level evidence. It binds an exact pending
source and its current query-window review to a privacy-minimized account
reference plus explicit market, asset, account-value-band, business, filter,
and export-completeness attestations. The value band is source-query scope,
not a balance fact or capital authorization. The review never promotes the
legacy XLS to canonical Account Truth and cannot authorize reconciliation,
execution, or capital.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from account_truth.citic_source_intake import (
    CiticSourceIntakeReadRejected,
    CiticSourceIntakeRepository,
)
from account_truth.citic_source_query_window_review import (
    CiticSourceQueryWindowReviewReadRejected,
    CiticSourceQueryWindowReviewRepository,
)
from account_truth.citic_source_scope_review_contracts import (
    CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION,
    CITIC_SOURCE_SCOPE_SUPPORTED_SCHEMA_VERSIONS,
    LEGACY_CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION,
    CiticSourceScopeReviewDecision,
)
from account_truth.citic_source_scope_review_projection import (
    CiticSourceScopeReviewProjectionMixin,
)
from account_truth.citic_source_scope_review_repository import (
    CiticSourceScopeReviewReadRepositoryMixin,
)
from account_truth.citic_source_scope_review_schema import (
    CiticSourceScopeReviewSchemaMixin,
)
from account_truth.citic_source_scope_review_uow import (
    CiticSourceScopeReviewUnitOfWorkMixin,
)
from account_truth.citic_source_scope_values import (
    EVIDENCE_FINGERPRINT,
    FILE_FINGERPRINT,
    SAFE_SCOPE_CODE,
    citic_source_scope_fingerprint_payload,
    normalize_citic_source_scope_review_inputs,
    require_aware_citic_source_scope_now,
    review_fingerprint,
    review_payload,
    safe_human_label,
    same_citic_source_accepted_scope,
)

_FILE_FINGERPRINT = FILE_FINGERPRINT
_EVIDENCE_FINGERPRINT = EVIDENCE_FINGERPRINT
_SAFE_SCOPE_CODE = SAFE_SCOPE_CODE
_LEGACY_CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION = (
    LEGACY_CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION
)
_SUPPORTED_SCHEMA_VERSIONS = CITIC_SOURCE_SCOPE_SUPPORTED_SCHEMA_VERSIONS


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
    return normalize_citic_source_scope_review_inputs(
        intake_id=intake_id,
        expected_file_fingerprint=expected_file_fingerprint,
        expected_source_preview_fingerprint=expected_source_preview_fingerprint,
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
        complete_returned_results_attested=complete_returned_results_attested,
        source_scope_attested=source_scope_attested,
        reviewer=reviewer,
        rejection=CiticSourceScopeReviewRejected,
        allow_missing_account_value_band=allow_missing_account_value_band,
    )


def _review_payload(
    review: CiticSourceScopeReview, *, reviewer: str
) -> dict[str, object]:
    return review_payload(review, reviewer=reviewer)


def _same_accepted_scope(
    review: CiticSourceScopeReview,
    normalized: dict[str, object],
) -> bool:
    return same_citic_source_accepted_scope(review, normalized)


def _fingerprint_payload(
    normalized: dict[str, object],
    *,
    schema_version: str,
    decision: CiticSourceScopeReviewDecision,
    supersedes_review_id: str | None,
) -> dict[str, object]:
    return citic_source_scope_fingerprint_payload(
        normalized,
        schema_version=schema_version,
        decision=decision,
        supersedes_review_id=supersedes_review_id,
    )


def _aware_now(value: datetime) -> datetime:
    return require_aware_citic_source_scope_now(
        value,
        rejection=CiticSourceScopeReviewRejected,
    )


class CiticSourceScopeReviewRepository(
    CiticSourceScopeReviewUnitOfWorkMixin,
    CiticSourceScopeReviewReadRepositoryMixin,
    CiticSourceScopeReviewSchemaMixin,
    CiticSourceScopeReviewProjectionMixin,
):
    """Persist exact source-scope reviews without persisting exported rows."""

    _review_type = CiticSourceScopeReview
    _rejection_type = CiticSourceScopeReviewRejected
    _read_rejection_type = CiticSourceScopeReviewReadRejected
    _evidence_fingerprint = EVIDENCE_FINGERPRINT

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

    def _query_window_repository(self) -> CiticSourceQueryWindowReviewRepository:
        return CiticSourceQueryWindowReviewRepository(self._path)

    @property
    def _intake_read_rejection_type(self) -> type[CiticSourceIntakeReadRejected]:
        return CiticSourceIntakeReadRejected

    @property
    def _query_window_read_rejection_type(
        self,
    ) -> type[CiticSourceQueryWindowReviewReadRejected]:
        return CiticSourceQueryWindowReviewReadRejected

    def _normalized_review_inputs(self, **kwargs: object) -> dict[str, object]:
        return _normalized_review_inputs(**kwargs)  # type: ignore[arg-type]

    def _review_payload(
        self,
        review: CiticSourceScopeReview,
        *,
        reviewer: str,
    ) -> dict[str, object]:
        return _review_payload(review, reviewer=reviewer)

    def _same_accepted_scope(
        self,
        review: CiticSourceScopeReview,
        normalized: dict[str, object],
    ) -> bool:
        return _same_accepted_scope(review, normalized)

    def _fingerprint_payload(
        self,
        normalized: dict[str, object],
        *,
        schema_version: str,
        decision: CiticSourceScopeReviewDecision,
        supersedes_review_id: str | None,
    ) -> dict[str, object]:
        return _fingerprint_payload(
            normalized,
            schema_version=schema_version,
            decision=decision,
            supersedes_review_id=supersedes_review_id,
        )

    def _review_fingerprint(self, payload: dict[str, object]) -> str:
        return review_fingerprint(payload)

    def _safe_human_label(self, value: str) -> bool:
        return safe_human_label(value)

    def _aware_now(self, value: datetime) -> datetime:
        return _aware_now(value)

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
        return super().record_review(
            intake_id=intake_id,
            expected_file_fingerprint=expected_file_fingerprint,
            expected_source_preview_fingerprint=expected_source_preview_fingerprint,
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
            complete_returned_results_attested=complete_returned_results_attested,
            source_scope_attested=source_scope_attested,
            reviewer=reviewer,
        )

    def revoke_latest(
        self,
        *,
        intake_id: str,
        expected_active_review_id: str,
        expected_active_review_fingerprint: str,
        reviewer: str = "local_owner",
    ) -> CiticSourceScopeReview:
        return super().revoke_latest(
            intake_id=intake_id,
            expected_active_review_id=expected_active_review_id,
            expected_active_review_fingerprint=expected_active_review_fingerprint,
            reviewer=reviewer,
        )

    def get_latest_review(self, intake_id: str) -> CiticSourceScopeReview | None:
        return super().get_latest_review(intake_id)

    def list_latest_reviews(
        self,
        *,
        limit: int = 200,
    ) -> list[CiticSourceScopeReview]:
        return super().list_latest_reviews(limit=limit)


def _review_from_row(row: object) -> CiticSourceScopeReview:
    repository = object.__new__(CiticSourceScopeReviewRepository)
    return repository._review_from_row(row)  # type: ignore[arg-type]
