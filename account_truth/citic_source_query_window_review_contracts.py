"""Contracts for exact-source CITIC query-window reviews."""

from __future__ import annotations

from typing import Literal

CITIC_SOURCE_QUERY_WINDOW_REVIEW_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_source_query_window_review.v1"
)
CiticSourceQueryWindowReviewDecision = Literal["accepted", "revoked"]
CITIC_SOURCE_QUERY_WINDOW_FILE_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"
CITIC_SOURCE_QUERY_WINDOW_EVIDENCE_FINGERPRINT_PATTERN = r"^sha256:[0-9a-f]{64}$"
CITIC_SOURCE_QUERY_WINDOW_MAX_DAYS = 31
