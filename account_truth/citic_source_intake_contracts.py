"""Contracts for privacy-minimized CITIC source intake reviews."""

from __future__ import annotations

from typing import Literal

CITIC_SOURCE_INTAKE_SCHEMA_VERSION = "karkinos.account_truth.citic_source_intake.v1"
CiticSourceReviewStatus = Literal["follow_up_required", "rejected"]
CITIC_SOURCE_FILE_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"
CITIC_SOURCE_NON_FINANCIAL_ACTIVITY_CODE = (
    "citic_history_xls_non_financial_activity_ignored"
)
