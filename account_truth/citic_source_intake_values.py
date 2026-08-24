"""Canonical value normalization for CITIC source intake evidence."""

from __future__ import annotations

import hashlib
import json
import re

from account_truth.broker_statement import BrokerStatementPreview
from account_truth.citic_history_xls import (
    CITIC_HISTORY_XLS_COLUMNS,
    CITIC_HISTORY_XLS_SOURCE_TYPE,
    recognized_non_financial_activity_count,
)
from account_truth.citic_source_intake_contracts import (
    CITIC_SOURCE_FILE_FINGERPRINT_PATTERN,
)

_FINGERPRINT_PATTERN = re.compile(CITIC_SOURCE_FILE_FINGERPRINT_PATTERN)


def required_evidence_for_citic_preview(
    preview: BrokerStatementPreview,
) -> list[str]:
    required: list[str] = []
    if preview.events:
        required.append("itemized_settlement_or_cash_flow")
    required.append("current_cash_and_position_snapshot")
    if recognized_non_financial_activity_count(preview) > 0:
        required.append("review_non_financial_activity")
    if preview.invalid_row_count > 0:
        required.append("resolve_invalid_rows")
    return required


def citic_preview_is_recordable_for_follow_up(
    preview: BrokerStatementPreview,
) -> bool:
    """Return whether a blocked preview is structurally useful follow-up evidence."""

    columns = tuple(preview.normalized_columns)
    non_financial_count = recognized_non_financial_activity_count(preview)
    return (
        preview.source_type == CITIC_HISTORY_XLS_SOURCE_TYPE
        and preview.validation_status == "blocked"
        and bool(_FINGERPRINT_PATTERN.fullmatch(preview.file_fingerprint))
        and len(columns) == len(CITIC_HISTORY_XLS_COLUMNS)
        and set(columns) == set(CITIC_HISTORY_XLS_COLUMNS)
        and preview.row_count
        == preview.valid_row_count + preview.invalid_row_count + non_financial_count
        and preview.valid_row_count == len(preview.events)
        and (preview.valid_row_count > 0 or non_financial_count > 0)
    )


def citic_source_preview_fingerprint(preview: BrokerStatementPreview) -> str:
    """Fingerprint only the sanitized, review-relevant preview identity."""

    payload = {
        "schema_version": preview.schema_version,
        "source_type": preview.source_type,
        "file_fingerprint": preview.file_fingerprint,
        "normalized_columns": list(preview.normalized_columns),
        "row_count": preview.row_count,
        "valid_row_count": preview.valid_row_count,
        "invalid_row_count": preview.invalid_row_count,
        "duplicate_row_count": preview.duplicate_row_count,
        "validation_status": preview.validation_status,
        "recognized_event_count": len(preview.events),
        "errors": sorted(
            (
                {
                    "row_number": error.row_number,
                    "code": error.code,
                }
                for error in preview.errors
            ),
            key=lambda item: (item["row_number"] or -1, item["code"]),
        ),
        "limitations": sorted(set(preview.limitations)),
        "required_evidence": required_evidence_for_citic_preview(preview),
        "recordable_for_follow_up": citic_preview_is_recordable_for_follow_up(preview),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def citic_source_intake_json(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))
