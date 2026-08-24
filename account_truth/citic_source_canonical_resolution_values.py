"""Deterministic value functions for CITIC canonical-source resolutions."""

from __future__ import annotations

import hashlib
import json
import re

from account_truth.citic_source_canonical_resolution_contracts import (
    CITIC_SOURCE_CANONICAL_RESOLUTION_SCHEMA_VERSION,
    CITIC_SOURCE_PREVIEW_FINGERPRINT_PATTERN,
)

_SOURCE_PREVIEW_FINGERPRINT = re.compile(CITIC_SOURCE_PREVIEW_FINGERPRINT_PATTERN)


def normalized_citic_source_preview_fingerprints(
    source_preview_fingerprints: list[str],
) -> list[str] | None:
    normalized = sorted({str(item).strip() for item in source_preview_fingerprints})
    if not normalized or any(
        not _SOURCE_PREVIEW_FINGERPRINT.fullmatch(item) for item in normalized
    ):
        return None
    return normalized


def citic_source_set_fingerprint_value(
    normalized_source_preview_fingerprints: list[str],
) -> str:
    return citic_source_resolution_fingerprint(
        {
            "schema_version": CITIC_SOURCE_CANONICAL_RESOLUTION_SCHEMA_VERSION,
            "source_preview_fingerprints": normalized_source_preview_fingerprints,
        }
    )


def citic_source_resolution_fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def citic_source_resolution_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
