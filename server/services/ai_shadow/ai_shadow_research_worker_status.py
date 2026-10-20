"""Provider-free public projection of durable research-worker jobs."""

from __future__ import annotations

from typing import Any, Protocol


class ShadowResearchWorkerJobReader(Protocol):
    def list_recent(self, *, limit: int = 20) -> list[dict[str, Any]]: ...


def build_ai_shadow_research_worker_status(
    store: ShadowResearchWorkerJobReader, *, limit: int = 20
) -> dict[str, Any]:
    jobs = [_project_job(row) for row in store.list_recent(limit=limit)]
    return {
        "schema_version": "karkinos.ai.shadow_research_worker_status.v1",
        "jobs": jobs,
        "latest_job": jobs[0] if jobs else None,
        "provider_call_performed": False,
        "provider_call_performed_scope": "this_status_read",
        "broker_order_created": False,
        "execution_authority_granted": False,
        "capital_authority_granted": False,
    }


def _project_job(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row["payload"])
    return {
        "job_id": row["run_id"],
        "run_date": row["run_date"],
        "status": row["status"],
        "available_at": payload.get("available_at"),
        "deadline_at": payload.get("deadline_at"),
        "attempt_count": int(payload.get("attempt_count") or 0),
        "lease_generation": int(payload.get("lease_generation") or 0),
        "takeover_count": int(payload.get("takeover_count") or 0),
        "lease_expires_at": payload.get("lease_expires_at"),
        "last_result": payload.get("last_result"),
        "provider_research_only": True,
        "automatic_strategy_replacement_enabled": False,
        "broker_submission_enabled": False,
        "execution_authority_granted": False,
        "capital_authority_granted": False,
    }
