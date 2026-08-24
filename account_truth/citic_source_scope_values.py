"""Canonical value handling for CITIC source-scope reviews."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_FILE_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_SCOPE_CODE = re.compile(r"^[a-z][a-z0-9_:-]{0,63}$")


def _review_payload(review: Any, *, reviewer: str) -> dict[str, object]:
    return {
        "intake_id": review.intake_id,
        "file_fingerprint": review.file_fingerprint,
        "source_preview_fingerprint": review.source_preview_fingerprint,
        "query_window_review_id": review.query_window_review_id,
        "query_window_review_fingerprint": review.query_window_review_fingerprint,
        "account_alias": review.account_alias,
        "account_reference_hash": review.account_reference_hash,
        "account_type": review.account_type,
        "market_scopes": list(review.market_scopes),
        "asset_classes": list(review.asset_classes),
        "account_value_band": review.account_value_band,
        "business_types": list(review.business_types),
        "no_other_filters_attested": True,
        "complete_returned_results_attested": True,
        "source_scope_attested": True,
        "reviewer": reviewer,
    }


def _normalized_codes(values: list[str]) -> list[str]:
    return sorted(
        {str(value).strip().lower() for value in values if str(value).strip()}
    )


def _stored_codes(value: object) -> list[str]:
    parsed = json.loads(str(value))
    if not isinstance(parsed, list) or any(
        not isinstance(item, str) for item in parsed
    ):
        raise ValueError("invalid source-scope codes")
    normalized = _normalized_codes(parsed)
    if normalized != parsed:
        raise ValueError("source-scope codes are not canonical")
    return normalized


def _stored_true(value: object) -> bool:
    if value != 1:
        raise ValueError("stored attestation is not true")
    return True


def _review_fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _safe_human_label(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= 128
        and all(
            character.isprintable() and character not in "\r\n\t" for character in value
        )
    )


FILE_FINGERPRINT = _FILE_FINGERPRINT
EVIDENCE_FINGERPRINT = _EVIDENCE_FINGERPRINT
SAFE_SCOPE_CODE = _SAFE_SCOPE_CODE
review_payload = _review_payload
normalized_codes = _normalized_codes
stored_codes = _stored_codes
stored_true = _stored_true
review_fingerprint = _review_fingerprint
safe_human_label = _safe_human_label
