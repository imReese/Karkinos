"""Shared validation primitives for durable research-worker job state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping


class AiShadowResearchWorkerJobRejected(ValueError):
    """Raised when persisted queue state is incomplete or identity-conflicting."""


def safe_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Persist only bounded orchestration facts, never provider bodies or facts."""

    allowed = (
        "run_status",
        "run_id",
        "failure_code",
        "next_eligible_at",
        "reused",
    )
    return {key: result.get(key) for key in allowed if key in result}


def canonical_job_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def required_text(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise AiShadowResearchWorkerJobRejected(f"research_worker_job_{field}_missing")
    return normalized


def aware_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AiShadowResearchWorkerJobRejected(
            f"research_worker_job_{field}_timezone_missing"
        )
    return value.astimezone(timezone.utc)


def parse_utc(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise AiShadowResearchWorkerJobRejected(
            f"research_worker_job_{field}_invalid"
        ) from exc
    return aware_utc(parsed, field=field)


def lease_matches(
    payload: Mapping[str, Any], *, lease_owner: str, lease_generation: int
) -> bool:
    if isinstance(lease_generation, bool) or not isinstance(lease_generation, int):
        return False
    return (
        payload.get("lease_owner") == lease_owner
        and payload.get("lease_generation") == lease_generation
    )
