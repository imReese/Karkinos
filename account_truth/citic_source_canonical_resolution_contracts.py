"""Contracts for revocable CITIC canonical-source resolutions."""

from __future__ import annotations

from typing import Literal

CITIC_SOURCE_CANONICAL_RESOLUTION_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_source_canonical_resolution.v1"
)
CiticSourceCanonicalResolutionDecision = Literal["accepted", "revoked"]
CITIC_SOURCE_CANONICAL_EVIDENCE_FINGERPRINT_PATTERN = r"^sha256:[0-9a-f]{64}$"
CITIC_SOURCE_PREVIEW_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"
