"""Fail-closed projection for persisted CITIC source-scope reviews."""

from __future__ import annotations

import json
import sqlite3

from account_truth.citic_source_scope_review_contracts import (
    CITIC_SOURCE_SCOPE_SUPPORTED_SCHEMA_VERSIONS,
    LEGACY_CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION,
)
from account_truth.citic_source_scope_values import (
    EVIDENCE_FINGERPRINT,
    review_fingerprint,
    stored_codes,
    stored_true,
)


class CiticSourceScopeReviewProjectionMixin:
    def _review_from_row(self, row: sqlite3.Row) -> object:
        try:
            schema_version = str(row["schema_version"])
            if schema_version not in CITIC_SOURCE_SCOPE_SUPPORTED_SCHEMA_VERSIONS:
                raise ValueError("unsupported source-scope review schema")
            account_value_band = (
                str(row["account_value_band"])
                if "account_value_band" in row.keys()
                and row["account_value_band"] is not None
                else None
            )
            review = self._review_type(
                review_id=str(row["review_id"]),
                schema_version=schema_version,
                intake_id=str(row["intake_id"]),
                file_fingerprint=str(row["file_fingerprint"]),
                source_preview_fingerprint=str(row["source_preview_fingerprint"]),
                query_window_review_id=str(row["query_window_review_id"]),
                query_window_review_fingerprint=str(
                    row["query_window_review_fingerprint"]
                ),
                account_alias=str(row["account_alias"]),
                account_reference_hash=str(row["account_reference_hash"]),
                account_type=str(row["account_type"]),
                market_scopes=stored_codes(row["market_scopes_json"]),
                asset_classes=stored_codes(row["asset_classes_json"]),
                account_value_band=account_value_band,
                business_types=stored_codes(row["business_types_json"]),
                no_other_filters_attested=stored_true(row["no_other_filters_attested"]),
                complete_returned_results_attested=stored_true(
                    row["complete_returned_results_attested"]
                ),
                source_scope_attested=stored_true(row["source_scope_attested"]),
                decision=str(row["decision"]),
                supersedes_review_id=(
                    str(row["supersedes_review_id"])
                    if row["supersedes_review_id"] is not None
                    else None
                ),
                reviewer=str(row["reviewer"]),
                review_fingerprint=str(row["review_fingerprint"]),
                created_at=str(row["created_at"]),
            )
            normalized = self._normalized_review_inputs(
                intake_id=review.intake_id,
                expected_file_fingerprint=review.file_fingerprint,
                expected_source_preview_fingerprint=review.source_preview_fingerprint,
                expected_query_window_review_id=review.query_window_review_id,
                expected_query_window_review_fingerprint=(
                    review.query_window_review_fingerprint
                ),
                account_alias=review.account_alias,
                account_reference_hash=review.account_reference_hash,
                account_type=review.account_type,
                market_scopes=review.market_scopes,
                asset_classes=review.asset_classes,
                account_value_band=review.account_value_band,
                business_types=review.business_types,
                no_other_filters_attested=review.no_other_filters_attested,
                complete_returned_results_attested=(
                    review.complete_returned_results_attested
                ),
                source_scope_attested=review.source_scope_attested,
                reviewer=review.reviewer,
                allow_missing_account_value_band=(
                    review.schema_version
                    == LEGACY_CITIC_SOURCE_SCOPE_REVIEW_SCHEMA_VERSION
                ),
            )
            expected = review_fingerprint(
                self._fingerprint_payload(
                    normalized,
                    schema_version=review.schema_version,
                    decision=review.decision,
                    supersedes_review_id=review.supersedes_review_id,
                )
            )
            if (
                review.decision not in {"accepted", "revoked"}
                or not review.review_id.startswith("citic_scope_review_")
                or not EVIDENCE_FINGERPRINT.fullmatch(review.review_fingerprint)
                or review.review_fingerprint != expected
                or not review.created_at.strip()
            ):
                raise ValueError("invalid source-scope review")
            return review
        except self._rejection_type as exc:
            raise self._read_rejection_type(
                "citic_source_scope_review_record_invalid"
            ) from exc
        except (
            IndexError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise self._read_rejection_type(
                "citic_source_scope_review_record_invalid"
            ) from exc
