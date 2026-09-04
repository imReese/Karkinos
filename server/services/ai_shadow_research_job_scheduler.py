"""Provider-free admission and durable enqueue for shadow research."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.provider_call_window import (
    DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
    ProviderCallWindowPolicy,
    is_deepseek_endpoint,
)
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_MINIMUM_OFF_PEAK_RUNWAY_SECONDS,
    SHADOW_RESEARCH_POLICY_ID,
    ShadowResearchPolicy,
)
from server.dependencies import AppState


class ShadowResearchJobEnqueuer(Protocol):
    def enqueue(self, **kwargs: Any) -> dict[str, Any]: ...


class AiShadowResearchJobScheduler:
    """Turn standing local policy into one durable off-peak worker job."""

    def __init__(
        self,
        *,
        state: AppState,
        store: ShadowResearchJobEnqueuer,
        now: Callable[[], datetime] | None = None,
        provider_call_window_policy: ProviderCallWindowPolicy = (
            DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY
        ),
    ) -> None:
        self._state = state
        self._db = state.require_database()
        self._store = store
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._provider_call_window_policy = provider_call_window_policy

    def enqueue_if_authorized(self) -> dict[str, Any]:
        """Perform cheap local gates and enqueue without constructing a provider."""

        observed_at = self._now()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("research_worker_scheduler_clock_timezone_missing")
        stored_policy = self._db.get_automation_policy_sync(SHADOW_RESEARCH_POLICY_ID)
        policy = ShadowResearchPolicy.from_mapping(stored_policy)
        if not policy.enabled:
            return _scheduler_result("disabled", "shadow_research_policy_disabled")
        controls = self._state.trading_controls
        if controls is None:
            return _scheduler_result(
                "blocked", "research_worker_kill_switch_status_unavailable"
            )
        snapshot = controls.snapshot()
        if snapshot.kill_switch_enabled:
            return _scheduler_result("blocked", "kill_switch_enabled")

        ai_config = getattr(self._state.require_config(), "ai", None)
        provider_enabled = getattr(ai_config, "enabled", False) is True
        provider_id = str(getattr(ai_config, "provider", "")).strip().casefold()
        endpoint_origin = str(getattr(ai_config, "base_url", "")).strip()
        if (
            not provider_enabled
            or provider_id != "deepseek"
            or not is_deepseek_endpoint(endpoint_origin)
        ):
            return _scheduler_result("blocked", "deepseek_provider_not_configured")

        decision = self._provider_call_window_policy.evaluate(
            observed_at,
            minimum_runway=timedelta(
                seconds=SHADOW_RESEARCH_MINIMUM_OFF_PEAK_RUNWAY_SECONDS
            ),
        )
        available_at = (
            observed_at
            if decision.allowed
            else datetime.fromisoformat(str(decision.next_eligible_at))
        )
        deadline_at = self._provider_call_window_policy.eligible_until(available_at)
        if deadline_at is None or available_at >= deadline_at:
            raise ValueError("research_worker_scheduler_deadline_unavailable")
        provider_config_fingerprint = shadow_research_provider_config_fingerprint(
            ai_config
        )
        job = self._store.enqueue(
            policy_fingerprint=content_fingerprint(policy.to_dict()),
            provider_config_fingerprint=provider_config_fingerprint,
            provider_window_policy_fingerprint=(
                self._provider_call_window_policy.fingerprint
            ),
            available_at=available_at,
            deadline_at=deadline_at,
            enqueued_at=observed_at,
        )
        return {
            "schema_version": "karkinos.ai.shadow_research_job_scheduler.v1",
            "status": "enqueued" if job["enqueued"] else "already_enqueued",
            "failure_code": None,
            "job_id": job["run_id"],
            "available_at": job["payload"]["available_at"],
            "deadline_at": job["payload"]["deadline_at"],
            "provider_call_performed": False,
            "broker_order_created": False,
            "execution_authority_granted": False,
            "capital_authority_granted": False,
        }


def _scheduler_result(status: str, failure_code: str) -> dict[str, Any]:
    return {
        "schema_version": "karkinos.ai.shadow_research_job_scheduler.v1",
        "status": status,
        "failure_code": failure_code,
        "provider_call_performed": False,
        "broker_order_created": False,
        "execution_authority_granted": False,
        "capital_authority_granted": False,
    }


def shadow_research_provider_config_fingerprint(ai_config: Any) -> str:
    """Hash only reviewed provider identity/configuration, never secret values."""

    return content_fingerprint(
        {
            "enabled": getattr(ai_config, "enabled", False) is True,
            "provider": str(getattr(ai_config, "provider", "")).strip().casefold(),
            "model": str(getattr(ai_config, "model", "")),
            "base_url": str(getattr(ai_config, "base_url", "")).strip(),
            "adapter_kind": str(getattr(ai_config, "adapter_kind", "")),
            "timeout_seconds": getattr(ai_config, "timeout_seconds", None),
            "api_key_env": str(getattr(ai_config, "api_key_env", "")),
        }
    )
