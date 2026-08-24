"""Canonical value handling for CITIC source-scope reviews."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any, Callable

from account_truth.citic_source_scope_review_contracts import (
    CITIC_SOURCE_SCOPE_EVIDENCE_FINGERPRINT_PATTERN,
    CITIC_SOURCE_SCOPE_FILE_FINGERPRINT_PATTERN,
    CITIC_SOURCE_SCOPE_SAFE_CODE_PATTERN,
    LEGACY_CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION,
)

_FILE_FINGERPRINT = re.compile(CITIC_SOURCE_SCOPE_FILE_FINGERPRINT_PATTERN)
_EVIDENCE_FINGERPRINT = re.compile(CITIC_SOURCE_SCOPE_EVIDENCE_FINGERPRINT_PATTERN)
_SAFE_SCOPE_CODE = re.compile(CITIC_SOURCE_SCOPE_SAFE_CODE_PATTERN)


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


def normalize_citic_source_scope_review_inputs(
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
    rejection: Callable[[str], Exception],
    allow_missing_account_value_band: bool = False,
) -> dict[str, object]:
    normalized = {
        "intake_id": intake_id.strip(),
        "file_fingerprint": expected_file_fingerprint.strip(),
        "source_preview_fingerprint": expected_source_preview_fingerprint.strip(),
        "query_window_review_id": expected_query_window_review_id.strip(),
        "query_window_review_fingerprint": (
            expected_query_window_review_fingerprint.strip()
        ),
        "account_alias": account_alias.strip(),
        "account_reference_hash": account_reference_hash.strip(),
        "account_type": account_type.strip().lower(),
        "market_scopes": _normalized_codes(market_scopes),
        "asset_classes": _normalized_codes(asset_classes),
        "account_value_band": (
            str(account_value_band).strip().lower()
            if account_value_band is not None
            else None
        ),
        "business_types": _normalized_codes(business_types),
        "no_other_filters_attested": no_other_filters_attested,
        "complete_returned_results_attested": complete_returned_results_attested,
        "source_scope_attested": source_scope_attested,
        "reviewer": reviewer.strip() or "local_owner",
    }
    if not str(normalized["intake_id"]).startswith("citic_intake_"):
        raise rejection("citic_source_scope_intake_id_invalid")
    if not _FILE_FINGERPRINT.fullmatch(str(normalized["file_fingerprint"])):
        raise rejection("citic_source_scope_file_fingerprint_invalid")
    if not _FILE_FINGERPRINT.fullmatch(str(normalized["source_preview_fingerprint"])):
        raise rejection("citic_source_scope_preview_fingerprint_invalid")
    if not str(normalized["query_window_review_id"]).startswith("citic_window_review_"):
        raise rejection("citic_source_scope_query_window_review_id_invalid")
    if not _EVIDENCE_FINGERPRINT.fullmatch(
        str(normalized["query_window_review_fingerprint"])
    ):
        raise rejection("citic_source_scope_query_window_review_fingerprint_invalid")
    if not _safe_human_label(str(normalized["account_alias"])):
        raise rejection("citic_source_scope_account_alias_invalid")
    if not _EVIDENCE_FINGERPRINT.fullmatch(str(normalized["account_reference_hash"])):
        raise rejection("citic_source_scope_account_reference_invalid")
    if not _SAFE_SCOPE_CODE.fullmatch(str(normalized["account_type"])):
        raise rejection("citic_source_scope_account_type_invalid")
    for key in ("market_scopes", "asset_classes", "business_types"):
        values = normalized[key]
        if not values or any(
            not _SAFE_SCOPE_CODE.fullmatch(str(value)) for value in values
        ):
            raise rejection(f"citic_source_scope_{key}_invalid")
    if normalized["account_value_band"] is None:
        if not allow_missing_account_value_band:
            raise rejection("citic_source_scope_account_value_band_missing")
    elif not _SAFE_SCOPE_CODE.fullmatch(str(normalized["account_value_band"])):
        raise rejection("citic_source_scope_account_value_band_invalid")
    if no_other_filters_attested is not True:
        raise rejection("citic_source_scope_no_other_filters_attestation_missing")
    if complete_returned_results_attested is not True:
        raise rejection("citic_source_scope_complete_results_attestation_missing")
    if source_scope_attested is not True:
        raise rejection("citic_source_scope_attestation_missing")
    if not _safe_human_label(str(normalized["reviewer"])):
        raise rejection("citic_source_scope_reviewer_invalid")
    return normalized


def same_citic_source_accepted_scope(
    review: Any,
    normalized: dict[str, object],
) -> bool:
    return _review_payload(review, reviewer=review.reviewer) == normalized


def citic_source_scope_fingerprint_payload(
    normalized: dict[str, object],
    *,
    schema_version: str,
    decision: str,
    supersedes_review_id: str | None,
) -> dict[str, object]:
    payload = dict(normalized)
    if schema_version == LEGACY_CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION:
        payload.pop("account_value_band", None)
    return {
        **payload,
        "schema_version": schema_version,
        "decision": decision,
        "supersedes_review_id": supersedes_review_id,
    }


def require_aware_citic_source_scope_now(
    value: datetime,
    *,
    rejection: Callable[[str], Exception],
) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise rejection("citic_source_scope_clock_invalid")
    return value.astimezone(UTC)


FILE_FINGERPRINT = _FILE_FINGERPRINT
EVIDENCE_FINGERPRINT = _EVIDENCE_FINGERPRINT
SAFE_SCOPE_CODE = _SAFE_SCOPE_CODE
review_payload = _review_payload
normalized_codes = _normalized_codes
stored_codes = _stored_codes
stored_true = _stored_true
review_fingerprint = _review_fingerprint
safe_human_label = _safe_human_label
