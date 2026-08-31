"""Contracts for privacy-minimized CITIC source-scope reviews."""

from __future__ import annotations

from typing import Literal

CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_source_scope_review.v2"
)
LEGACY_CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_source_scope_review.v1"
)
CITIC_SOURCE_SCOPE_SUPPORTED_SCHEMA_VERSIONS = {
    LEGACY_CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION,
    CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION,
}
CiticSourceScopeReviewDecision = Literal["accepted", "revoked"]
CITIC_SOURCE_SCOPE_FILE_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"
CITIC_SOURCE_SCOPE_EVIDENCE_FINGERPRINT_PATTERN = r"^sha256:[0-9a-f]{64}$"
CITIC_SOURCE_SCOPE_SAFE_CODE_PATTERN = r"^[a-z][a-z0-9_:-]{0,63}$"
