"""Value normalization for exact-source CITIC query-window reviews."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from typing import Callable

from account_truth.broker_statement import BrokerStatementPreview
from account_truth.citic_source_intake import (
    citic_preview_is_recordable_for_follow_up,
    citic_source_preview_fingerprint,
)
from account_truth.citic_source_query_window_review_contracts import (
    CITIC_SOURCE_QUERY_WINDOW_FILE_FINGERPRINT_PATTERN,
    CITIC_SOURCE_QUERY_WINDOW_MAX_DAYS,
)

_FILE_FINGERPRINT = re.compile(CITIC_SOURCE_QUERY_WINDOW_FILE_FINGERPRINT_PATTERN)


def normalize_citic_source_query_window_review_inputs(
    *,
    preview: BrokerStatementPreview,
    expected_file_fingerprint: str,
    expected_source_preview_fingerprint: str,
    query_start_date: str,
    query_end_date: str,
    query_window_attested: bool,
    reviewer: str,
    today: date,
    rejection: Callable[[str], Exception],
) -> dict[str, str]:
    if query_window_attested is not True:
        raise rejection("citic_source_query_window_attestation_missing")
    if not citic_preview_is_recordable_for_follow_up(preview):
        raise rejection("citic_source_query_window_source_not_recordable")
    file_fingerprint = expected_file_fingerprint.strip()
    source_preview_fingerprint = expected_source_preview_fingerprint.strip()
    if (
        not _FILE_FINGERPRINT.fullmatch(file_fingerprint)
        or file_fingerprint != preview.file_fingerprint
    ):
        raise rejection("citic_source_query_window_file_fingerprint_mismatch")
    actual_preview_fingerprint = citic_source_preview_fingerprint(preview)
    if (
        not _FILE_FINGERPRINT.fullmatch(source_preview_fingerprint)
        or source_preview_fingerprint != actual_preview_fingerprint
    ):
        raise rejection("citic_source_query_window_source_preview_mismatch")
    start = parse_citic_source_query_window_date(
        query_start_date,
        rejection=rejection,
    )
    end = parse_citic_source_query_window_date(
        query_end_date,
        rejection=rejection,
    )
    if start > end:
        raise rejection("citic_source_query_window_date_order_invalid")
    if (end - start).days + 1 > CITIC_SOURCE_QUERY_WINDOW_MAX_DAYS:
        raise rejection("citic_source_query_window_exceeds_one_month")
    if end > today:
        raise rejection("citic_source_query_window_future_date")
    for event in preview.events:
        occurred_date = aware_citic_source_query_window_event_date(event.occurred_at)
        if occurred_date is None:
            raise rejection("citic_source_query_window_event_time_invalid")
        if occurred_date < start or occurred_date > end:
            raise rejection("citic_source_query_window_event_outside_reviewed_range")
    return {
        "file_fingerprint": file_fingerprint,
        "source_preview_fingerprint": source_preview_fingerprint,
        "query_start_date": start.isoformat(),
        "query_end_date": end.isoformat(),
        "reviewer": reviewer.strip() or "local_owner",
    }


def same_citic_source_accepted_window(
    review: object,
    normalized: dict[str, str],
) -> bool:
    return (
        getattr(review, "file_fingerprint") == normalized["file_fingerprint"]
        and getattr(review, "source_preview_fingerprint")
        == normalized["source_preview_fingerprint"]
        and getattr(review, "query_start_date") == normalized["query_start_date"]
        and getattr(review, "query_end_date") == normalized["query_end_date"]
    )


def citic_source_query_window_review_fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def parse_citic_source_query_window_date(
    value: object,
    *,
    rejection: Callable[[str], Exception],
) -> date:
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise rejection("citic_source_query_window_date_invalid") from None
    if parsed.isoformat() != str(value):
        raise rejection("citic_source_query_window_date_invalid")
    return parsed


def aware_citic_source_query_window_event_date(value: object) -> date | None:
    try:
        occurred_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        return None
    return occurred_at.date()


def require_aware_citic_source_query_window_now(
    value: datetime,
    *,
    rejection: Callable[[str], Exception],
) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise rejection("citic_source_query_window_clock_invalid")
    return value
