"""Fail-closed row projection for CITIC source intake evidence."""

from __future__ import annotations

import json
import re

from account_truth.citic_history_xls import CITIC_HISTORY_XLS_SOURCE_TYPE
from account_truth.citic_source_intake_contracts import (
    CITIC_SOURCE_FILE_FINGERPRINT_PATTERN,
    CITIC_SOURCE_INTAKE_SCHEMA_VERSION,
)
from account_truth.citic_source_intake_contracts import (
    CITIC_SOURCE_NON_FINANCIAL_ACTIVITY_CODE as _NON_FINANCIAL_ACTIVITY_CODE,
)

_FINGERPRINT_PATTERN = re.compile(CITIC_SOURCE_FILE_FINGERPRINT_PATTERN)


class CiticSourceIntakeProjectionMixin:
    def _intake_from_row(
        self,
        row: object,
        *,
        reused: bool,
    ) -> object | None:
        if row is None:
            return None
        counts = {
            key: int(row[key])
            for key in (
                "row_count",
                "valid_row_count",
                "invalid_row_count",
                "duplicate_row_count",
                "recognized_event_count",
            )
        }
        error_codes = self._json_list(row["error_codes_json"])
        required_evidence = self._json_list(row["required_evidence_json"])
        limitations = self._json_list(row["limitations_json"])
        non_financial_count = (
            counts["row_count"]
            - counts["valid_row_count"]
            - counts["invalid_row_count"]
        )
        recordable = int(row["recordable_for_follow_up"])
        review_status = str(row["review_status"])
        if (
            str(row["schema_version"]) != CITIC_SOURCE_INTAKE_SCHEMA_VERSION
            or str(row["source_type"]) != CITIC_HISTORY_XLS_SOURCE_TYPE
            or str(row["validation_status"]) != "blocked"
            or not _FINGERPRINT_PATTERN.fullmatch(str(row["file_fingerprint"]))
            or not _FINGERPRINT_PATTERN.fullmatch(
                str(row["source_preview_fingerprint"])
            )
            or review_status not in {"follow_up_required", "rejected"}
            or recordable not in {0, 1}
            or (review_status == "follow_up_required" and recordable != 1)
            or any(value < 0 for value in counts.values())
            or non_financial_count < 0
            or (
                non_financial_count > 0
                and _NON_FINANCIAL_ACTIVITY_CODE not in error_codes
            )
            or (
                non_financial_count == 0 and _NON_FINANCIAL_ACTIVITY_CODE in error_codes
            )
            or not str(row["intake_id"]).startswith("citic_intake_")
            or not str(row["review_id"]).startswith("citic_review_")
            or not str(row["reviewer"]).strip()
            or not str(row["created_at"]).strip()
            or not str(row["reviewed_at"]).strip()
        ):
            raise self._intake_read_rejection_type("citic_source_intake_record_invalid")
        return self._intake_type(
            intake_id=str(row["intake_id"]),
            schema_version=str(row["schema_version"]),
            source_type=str(row["source_type"]),
            file_fingerprint=str(row["file_fingerprint"]),
            source_preview_fingerprint=str(row["source_preview_fingerprint"]),
            validation_status=str(row["validation_status"]),
            row_count=counts["row_count"],
            valid_row_count=counts["valid_row_count"],
            invalid_row_count=counts["invalid_row_count"],
            duplicate_row_count=counts["duplicate_row_count"],
            recognized_event_count=counts["recognized_event_count"],
            error_codes=error_codes,
            required_evidence=required_evidence,
            limitations=limitations,
            recordable_for_follow_up=bool(recordable),
            review_id=str(row["review_id"]),
            review_status=review_status,  # type: ignore[arg-type]
            reviewer=str(row["reviewer"]),
            created_at=str(row["created_at"]),
            reviewed_at=str(row["reviewed_at"]),
            reused=reused,
        )

    def _json_list(self, value: object) -> list[str]:
        try:
            loaded = json.loads(str(value))
        except (TypeError, ValueError):
            raise self._intake_read_rejection_type(
                "citic_source_intake_record_invalid"
            ) from None
        if not isinstance(loaded, list) or any(
            not isinstance(item, str) or not item.strip() for item in loaded
        ):
            raise self._intake_read_rejection_type("citic_source_intake_record_invalid")
        return loaded
