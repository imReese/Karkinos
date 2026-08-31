"""Account Truth request models owned by the HTTP contract layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from account_truth.manual_review import ManualReviewStatus


class ReviewDecisionCreate(BaseModel):
    category: str
    review_status: ManualReviewStatus
    symbol: str = ""
    note: str = ""
    reviewer: str = "local"


class BrokerStatementPreviewCreate(BaseModel):
    content: str
    source_name: str = "local-broker-statement.csv"


class CiticHistoryXlsPreviewCreate(BaseModel):
    content_base64: str


class CiticHistoryXlsIntakeCreate(BaseModel):
    content_base64: str
    expected_file_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_status: Literal["follow_up_required", "rejected"]


class CiticHistoryXlsDirectoryIntakeCreate(BaseModel):
    expected_file_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_status: Literal["follow_up_required", "rejected"]


class CiticHistoryXlsQueryWindowReviewCreate(BaseModel):
    content_base64: str
    expected_file_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_source_preview_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    query_end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    query_window_attested: Literal[True]
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class CiticHistoryXlsDirectoryQueryWindowReviewCreate(BaseModel):
    expected_file_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_source_preview_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    query_end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    query_window_attested: Literal[True]
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class CiticHistoryXlsQueryWindowReviewRevoke(BaseModel):
    intake_id: str = Field(min_length=1, max_length=128)
    expected_active_review_id: str = Field(min_length=1, max_length=128)
    expected_active_review_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class CiticHistoryXlsSourceScopeReviewCreate(BaseModel):
    intake_id: str = Field(min_length=1, max_length=128)
    expected_file_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_source_preview_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_query_window_review_id: str = Field(min_length=1, max_length=128)
    expected_query_window_review_fingerprint: str = Field(
        pattern=r"^sha256:[0-9a-f]{64}$"
    )
    account_alias: str = Field(min_length=1, max_length=128)
    account_reference_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    account_type: str = Field(pattern=r"^[a-z][a-z0-9_:-]{0,63}$")
    market_scopes: list[str] = Field(min_length=1, max_length=32)
    asset_classes: list[str] = Field(min_length=1, max_length=32)
    account_value_band: str = Field(pattern=r"^[a-z][a-z0-9_:-]{0,63}$")
    business_types: list[str] = Field(min_length=1, max_length=32)
    no_other_filters_attested: Literal[True]
    complete_returned_results_attested: Literal[True]
    source_scope_attested: Literal[True]
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class CiticHistoryXlsSourceScopeReviewRevoke(BaseModel):
    intake_id: str = Field(min_length=1, max_length=128)
    expected_active_review_id: str = Field(min_length=1, max_length=128)
    expected_active_review_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class EvidenceScopeReviewCreate(BaseModel):
    import_run_id: str = Field(min_length=1, max_length=128)
    expected_observed_scope_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    provider: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._:-]{0,63}$")
    account_alias: str = Field(min_length=1, max_length=128)
    account_reference_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    coverage_start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    coverage_end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    asset_classes: list[str] = Field(min_length=1, max_length=16)
    full_account_scope_attested: Literal[True]
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class EvidenceScopeReviewRevoke(BaseModel):
    import_run_id: str = Field(min_length=1, max_length=128)
    expected_observed_scope_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class CiticSourceCanonicalResolutionCreate(BaseModel):
    expected_source_set_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_scope_review_id: str = Field(min_length=1, max_length=128)
    expected_scope_review_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    canonical_statement_covers_sources_attested: Literal[True]
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class CiticSourceCanonicalResolutionRevoke(BaseModel):
    expected_resolution_id: str = Field(min_length=1, max_length=128)
    expected_resolution_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)


class ReviewedFeeSchedulePreviewCreate(BaseModel):
    effective_start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    effective_end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reviewed_asset_classes: list[Literal["stock"]] = Field(
        default_factory=lambda: ["stock"],
        min_length=1,
        max_length=1,
    )


class ReviewedFeeScheduleReviewCreate(ReviewedFeeSchedulePreviewCreate):
    expected_preview_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)
    confirmation: str


class ReviewedFeeScheduleReviewRevoke(BaseModel):
    expected_review_id: str = Field(min_length=1, max_length=128)
    expected_review_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reviewer: str = Field(default="local_owner", min_length=1, max_length=128)
    confirmation: str


__all__ = (
    "BrokerStatementPreviewCreate",
    "CiticHistoryXlsDirectoryIntakeCreate",
    "CiticHistoryXlsDirectoryQueryWindowReviewCreate",
    "CiticHistoryXlsIntakeCreate",
    "CiticHistoryXlsPreviewCreate",
    "CiticHistoryXlsQueryWindowReviewCreate",
    "CiticHistoryXlsQueryWindowReviewRevoke",
    "CiticHistoryXlsSourceScopeReviewCreate",
    "CiticHistoryXlsSourceScopeReviewRevoke",
    "CiticSourceCanonicalResolutionCreate",
    "CiticSourceCanonicalResolutionRevoke",
    "EvidenceScopeReviewCreate",
    "EvidenceScopeReviewRevoke",
    "ReviewDecisionCreate",
    "ReviewedFeeSchedulePreviewCreate",
    "ReviewedFeeScheduleReviewCreate",
    "ReviewedFeeScheduleReviewRevoke",
)
