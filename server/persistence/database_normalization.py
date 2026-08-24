"""Small value and review-state normalizers shared by SQLite repositories."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def stable_json_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def paper_shadow_run_review_next_step(review_status: str) -> str:
    status = str(review_status or "").strip().lower()
    if status == "accepted_for_manual_confirmation":
        return "review_manual_confirmation"
    if status == "needs_rerun":
        return "run_paper_shadow_daily"
    return "resolve_shadow_divergence"


def validate_paper_shadow_run_review_transition(
    *,
    run_status: str,
    review_status: str,
) -> None:
    normalized_run_status = str(run_status or "").strip().lower()
    normalized_review_status = str(review_status or "").strip().lower()
    if (
        normalized_run_status == "failed"
        and normalized_review_status == "accepted_for_manual_confirmation"
    ):
        raise ValueError(
            "failed paper/shadow run cannot be accepted for manual confirmation; "
            "inspect the failed run or rerun paper/shadow first"
        )
