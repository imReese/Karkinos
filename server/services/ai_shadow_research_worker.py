"""Independent lease-backed process for external shadow research."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.provider_call_window import (
    DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
    ProviderExecutionFence,
    ProviderExecutionFenced,
)
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_MINIMUM_OFF_PEAK_RUNWAY_SECONDS,
    SHADOW_RESEARCH_POLICY_ID,
    ShadowResearchPolicy,
)
from server.dependencies import AppState
from server.release_activation import wait_for_release_activation
from server.services.ai_shadow_research_job_scheduler import (
    shadow_research_provider_config_fingerprint,
)

logger = logging.getLogger(__name__)

AI_SHADOW_RESEARCH_WORKER_LEASE_SECONDS = 90
AI_SHADOW_RESEARCH_WORKER_HEARTBEAT_SECONDS = 30
AI_SHADOW_RESEARCH_WORKER_POLL_SECONDS = 5
AI_SHADOW_RESEARCH_WORKER_RETRY_SECONDS = 300


class ShadowResearchRunner(Protocol):
    async def run_once(self) -> dict[str, Any]: ...


class ShadowResearchWorkerJobStore(Protocol):
    def claim_next(self, **kwargs: Any) -> dict[str, Any] | None: ...

    def renew_lease(self, **kwargs: Any) -> bool: ...

    def complete(self, **kwargs: Any) -> bool: ...

    def fail(self, **kwargs: Any) -> bool: ...

    def reschedule(self, **kwargs: Any) -> bool: ...

    def lease_is_current(self, **kwargs: Any) -> bool: ...

    def begin_provider_send(self, **kwargs: Any) -> str | None: ...

    def finish_provider_send(self, **kwargs: Any) -> bool: ...

    def get(self, job_id: str) -> dict[str, Any] | None: ...


class AiShadowResearchWorkerLeaseLost(RuntimeError):
    """Raised when an old worker generation may no longer commit a result."""


class AiShadowResearchWorker:
    """Claim one durable job and run provider research outside the API process."""

    def __init__(
        self,
        *,
        state: AppState,
        store: ShadowResearchWorkerJobStore,
        service_builder: (
            Callable[[ProviderExecutionFence], ShadowResearchRunner] | None
        ) = None,
        lease_owner: str | None = None,
        now: Callable[[], datetime] | None = None,
        lease_seconds: int = AI_SHADOW_RESEARCH_WORKER_LEASE_SECONDS,
        heartbeat_seconds: int = AI_SHADOW_RESEARCH_WORKER_HEARTBEAT_SECONDS,
        retry_seconds: int = AI_SHADOW_RESEARCH_WORKER_RETRY_SECONDS,
    ) -> None:
        self._state = state
        self._db = state.require_database()
        self._store = store
        self._service_builder = service_builder or self._build_external_service
        self._lease_owner = lease_owner or (
            f"research-worker:{os.getpid()}:{uuid.uuid4().hex}"
        )
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._retry_seconds = retry_seconds

    async def run_one(self) -> dict[str, Any] | None:
        """Claim and execute at most one job, returning its bounded outcome."""

        claimed_at = self._now()
        job = await asyncio.to_thread(
            self._store.claim_next,
            lease_owner=self._lease_owner,
            claimed_at=claimed_at,
            lease_seconds=self._lease_seconds,
        )
        if job is None:
            return None
        job_id = str(job["run_id"])
        payload = dict(job["payload"])
        lease_generation = int(payload["lease_generation"])
        try:
            self._require_current_admission(payload)
            execution_fence = _WorkerProviderExecutionFence(
                worker=self,
                job_id=job_id,
                lease_generation=lease_generation,
            )
            runner = self._service_builder(execution_fence)
            result = await self._run_with_lease(
                job_id=job_id,
                lease_generation=lease_generation,
                runner=runner,
            )
        except asyncio.CancelledError:
            # Do not release an uncertain attempt.  The durable lease expires and
            # a fresh worker generation may take it over without old-owner commit.
            raise
        except AiShadowResearchWorkerLeaseLost:
            raise
        except ProviderExecutionFenced as exc:
            raise AiShadowResearchWorkerLeaseLost(str(exc)) from exc
        except Exception as exc:
            result = {
                "run_status": "failed",
                "failure_code": _failure_code(exc),
            }

        now = self._now()
        run_status = str(result.get("run_status") or result.get("status") or "")
        if run_status == "completed":
            committed = await asyncio.to_thread(
                self._store.complete,
                job_id=job_id,
                lease_owner=self._lease_owner,
                lease_generation=lease_generation,
                completed_at=now,
                result=result,
            )
            disposition = "completed"
        elif run_status in {
            "waiting_for_market_close",
            "blocked_by_market_evidence",
            "blocked_by_account_evidence",
            "deferred_for_provider_off_peak",
        }:
            next_at = _retry_at(result, now=now, retry_seconds=self._retry_seconds)
            committed = await asyncio.to_thread(
                self._store.reschedule,
                job_id=job_id,
                lease_owner=self._lease_owner,
                lease_generation=lease_generation,
                rescheduled_at=now,
                available_at=next_at,
                result=result,
            )
            disposition = "rescheduled"
        else:
            if run_status == "running" and result.get("reused") is True:
                result = {
                    **result,
                    "run_status": "failed",
                    "failure_code": "research_run_incomplete_requires_reconciliation",
                }
            committed = await asyncio.to_thread(
                self._store.fail,
                job_id=job_id,
                lease_owner=self._lease_owner,
                lease_generation=lease_generation,
                failed_at=now,
                result=result,
            )
            disposition = "failed"
        if not committed:
            raise AiShadowResearchWorkerLeaseLost(
                "research_worker_lease_lost_before_commit"
            )
        return {
            "job_id": job_id,
            "disposition": disposition,
            "run_status": result.get("run_status"),
            "failure_code": result.get("failure_code"),
            "provider_research_only": True,
            "broker_submission_enabled": False,
            "execution_authority_granted": False,
            "capital_authority_granted": False,
        }

    async def run_forever(
        self,
        *,
        poll_seconds: float = AI_SHADOW_RESEARCH_WORKER_POLL_SECONDS,
    ) -> None:
        while True:
            await wait_for_release_activation()
            try:
                outcome = await self.run_one()
            except asyncio.CancelledError:
                raise
            except AiShadowResearchWorkerLeaseLost:
                logger.warning("Shadow research worker lease was lost", exc_info=True)
                outcome = None
            except Exception:
                logger.warning("Shadow research worker failed closed", exc_info=True)
                outcome = None
            if outcome is None:
                await asyncio.sleep(max(0.1, poll_seconds))

    def _require_current_admission(self, payload: Mapping[str, Any]) -> None:
        self._require_current_authority(payload)
        now = self._now()
        decision = DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY.evaluate(
            now,
            minimum_runway=timedelta(
                seconds=SHADOW_RESEARCH_MINIMUM_OFF_PEAK_RUNWAY_SECONDS
            ),
        )
        if not decision.allowed:
            raise PermissionError(
                decision.failure_code or "research_worker_provider_window_blocked"
            )

    def _require_current_authority(self, payload: Mapping[str, Any]) -> None:
        now = self._now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("research_worker_clock_timezone_missing")
        deadline = datetime.fromisoformat(str(payload["deadline_at"]))
        if now >= deadline:
            raise ValueError("research_worker_job_deadline_elapsed")
        policy = ShadowResearchPolicy.from_mapping(
            self._db.get_automation_policy_sync(SHADOW_RESEARCH_POLICY_ID)
        )
        if not policy.enabled:
            raise PermissionError("shadow_research_policy_paused")
        if content_fingerprint(policy.to_dict()) != payload.get("policy_fingerprint"):
            raise PermissionError("shadow_research_policy_changed")
        controls = self._state.trading_controls
        if controls is None or controls.snapshot().kill_switch_enabled:
            raise PermissionError("blocked_by_kill_switch")
        ai_config = getattr(self._state.require_config(), "ai", None)
        if shadow_research_provider_config_fingerprint(ai_config) != payload.get(
            "provider_config_fingerprint"
        ):
            raise PermissionError("research_worker_provider_config_changed")
        if DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY.fingerprint != payload.get(
            "provider_window_policy_fingerprint"
        ):
            raise PermissionError("research_worker_provider_window_policy_changed")

    def _require_current_execution(self, *, job_id: str, lease_generation: int) -> None:
        now = self._now()
        if not self._store.lease_is_current(
            job_id=job_id,
            lease_owner=self._lease_owner,
            lease_generation=lease_generation,
            checked_at=now,
        ):
            raise ProviderExecutionFenced("research_worker_lease_generation_fenced")
        job = self._store.get(job_id)
        if job is None:
            raise ProviderExecutionFenced("research_worker_job_missing")
        try:
            self._require_current_authority(job["payload"])
        except Exception as exc:
            raise ProviderExecutionFenced(_failure_code(exc)) from exc

    async def _run_with_lease(
        self,
        *,
        job_id: str,
        lease_generation: int,
        runner: ShadowResearchRunner,
    ) -> dict[str, Any]:
        job = await asyncio.to_thread(self._store.get, job_id)
        if job is None:
            raise AiShadowResearchWorkerLeaseLost("research_worker_job_missing")
        deadline = datetime.fromisoformat(str(job["payload"]["deadline_at"]))
        remaining = (deadline - self._now().astimezone(deadline.tzinfo)).total_seconds()
        if remaining <= 0:
            raise TimeoutError("research_worker_job_deadline_elapsed")
        runner_task = asyncio.create_task(runner.run_once())
        heartbeat_task = asyncio.create_task(
            self._heartbeat(
                job_id=job_id,
                lease_generation=lease_generation,
                runner_task=runner_task,
            )
        )
        try:
            return await asyncio.wait_for(runner_task, timeout=remaining)
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    async def _heartbeat(
        self,
        *,
        job_id: str,
        lease_generation: int,
        runner_task: asyncio.Task[dict[str, Any]],
    ) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            renewed = await asyncio.to_thread(
                self._store.renew_lease,
                job_id=job_id,
                lease_owner=self._lease_owner,
                lease_generation=lease_generation,
                renewed_at=self._now(),
                lease_seconds=self._lease_seconds,
            )
            if not renewed:
                runner_task.cancel()
                raise AiShadowResearchWorkerLeaseLost(
                    "research_worker_lease_renewal_failed"
                )

    def _build_external_service(
        self, execution_fence: ProviderExecutionFence
    ) -> ShadowResearchRunner:
        # This is the sole automatic composition edge allowed to construct the
        # external provider-backed strategy-research path.
        from server.composition.ai_application_services import (
            build_shadow_research_write_service,
        )

        return build_shadow_research_write_service(
            self._state,
            provider_execution_fence=execution_fence,
        )


class _WorkerProviderExecutionFence:
    def __init__(
        self,
        *,
        worker: AiShadowResearchWorker,
        job_id: str,
        lease_generation: int,
    ) -> None:
        self._worker = worker
        self._job_id = job_id
        self._lease_generation = lease_generation

    def require_current(self) -> None:
        self._worker._require_current_execution(
            job_id=self._job_id,
            lease_generation=self._lease_generation,
        )

    def begin_provider_send(self, *, timeout_seconds: float) -> object:
        self.require_current()
        token = self._worker._store.begin_provider_send(
            job_id=self._job_id,
            lease_owner=self._worker._lease_owner,
            lease_generation=self._lease_generation,
            started_at=self._worker._now(),
            timeout_seconds=timeout_seconds,
        )
        if token is None:
            raise ProviderExecutionFenced("research_worker_provider_send_fenced")
        return token

    def finish_provider_send(self, token: object) -> None:
        if not isinstance(token, str) or not self._worker._store.finish_provider_send(
            job_id=self._job_id,
            lease_owner=self._worker._lease_owner,
            lease_generation=self._lease_generation,
            token=token,
            finished_at=self._worker._now(),
        ):
            raise ProviderExecutionFenced("research_worker_provider_response_fenced")
        self.require_current()


def _retry_at(
    result: Mapping[str, Any], *, now: datetime, retry_seconds: int
) -> datetime:
    next_eligible_at = result.get("next_eligible_at")
    if next_eligible_at:
        try:
            parsed = datetime.fromisoformat(str(next_eligible_at))
            if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                return max(
                    now.astimezone(timezone.utc), parsed.astimezone(timezone.utc)
                )
        except ValueError:
            pass
    return now + timedelta(seconds=retry_seconds)


def _failure_code(exc: Exception) -> str:
    value = str(exc).strip()
    if (
        value
        and len(value) <= 160
        and all(character.isalnum() or character in "_:-." for character in value)
    ):
        return value
    return type(exc).__name__
