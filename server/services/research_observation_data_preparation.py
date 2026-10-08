"""Opt-in supply of verified daily inputs for one frozen research observation."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from core.types import InstrumentKey
from data.dataset.model import DatasetRef
from data.dataset.reader import read_daily_bar_dataset
from data.market.contracts import DailyBarRequest
from data.source_policy import verification_source_policy_for_config
from server.contracts.jobs import JobRun
from server.contracts.research_observation_automation import (
    observation_automation_policy_valid,
)
from server.persistence.automation_runs import (
    AutomationRunRepository,
    require_observation_automation_policy,
)
from server.persistence.jobs import SQLiteJobStore, job_id_for
from server.release_activation import is_release_activation_guarded
from server.services.market_calendar_dates import (
    resolve_latest_verified_closed_trading_date,
    resolve_verified_closed_trading_dates_in_range,
)
from server.services.research_datasets import publish_verified_interval_dataset
from server.services.research_observations import (
    ResearchObservationService,
    observation_code_binding,
)
from server.services.verified_daily_market_data import (
    VerifiedDailyMarketJobRequest,
    verified_daily_resolver_policy_id,
)
from server.services.verified_daily_market_jobs import VERIFIED_DAILY_MARKET_JOB

logger = logging.getLogger(__name__)


def observation_daily_job_grant(payload: dict[str, Any]) -> dict[str, str] | None:
    """Manual jobs retain their original identities and independent permission."""
    if "observation_automation" not in payload:
        return None
    grant = payload["observation_automation"]
    try:
        if not isinstance(grant, dict) or set(grant) != {
            "observation_id",
            "generation",
        }:
            raise ValueError
        if any(str(UUID(grant[key])) != grant[key] for key in grant):
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        raise ValueError("observation_data_preparation_grant_invalid") from None
    return grant


def guard_observation_data_preparation(
    conn: Any, grant: dict[str, str], stopped: Callable[[], bool]
) -> None:
    if stopped():
        raise ValueError("observation_data_preparation_stopped")
    require_observation_automation_policy(
        conn, grant["observation_id"], grant["generation"], dataset_preparation=True
    )


def _observation(service: ResearchObservationService, grant: dict[str, str]):
    AutomationRunRepository(service.db.path).require_observation_dataset_preparation(
        grant["observation_id"], grant["generation"]
    )
    observation = service.repository.get(grant["observation_id"])
    if observation is None:
        raise ValueError("observation_not_found")
    if observation["code_binding"] != observation_code_binding():
        raise ValueError("observation_code_changed")
    return observation


def _prefix(service, observation, now):
    source = observation["source"]
    identity = (
        source["dataset_id"]
        if source["source_dataset_kind"] == "immutable_dataset"
        else source.get("immutable_dataset_id")
    )
    if not identity:
        raise ValueError("observation_data_preparation_verified_source_required")
    try:
        ref = DatasetRef(service.objects.resolve_ref(identity))
        result = read_daily_bar_dataset(service.objects, ref)
    except Exception:
        raise ValueError("observation_data_preparation_source_unreadable") from None
    snapshot = result.snapshot
    instruments = tuple(
        sorted(
            (
                InstrumentKey.from_values(row["symbol"], row["instrument_type"])
                for row in observation["universe"]
            ),
            key=lambda item: (item.instrument_type.value, item.symbol),
        )
    )
    if (
        not snapshot.verification_bound
        or snapshot.instruments != instruments
        or snapshot.start_date.isoformat() != source["start_date"]
        or snapshot.end_date.isoformat() != source["end_date"]
        or snapshot.cutoff > now
        or not 1 <= len(instruments) <= 32
    ):
        raise ValueError("observation_data_preparation_source_mismatch")
    expected = resolve_verified_closed_trading_dates_in_range(
        service.db, now, start_date=snapshot.start_date, end_date=snapshot.end_date
    )
    if not expected or tuple(
        part.partition_date.isoformat() for part in snapshot.partitions
    ) != tuple(day.trade_date for day in expected):
        raise ValueError("observation_data_preparation_source_calendar_mismatch")
    if len(result.bars) > observation["policy"]["max_dataset_rows"]:
        raise ValueError("observation_dataset_budget_exceeded")
    return ref, snapshot


def require_observation_preparation_job(db, config, job: JobRun) -> None:
    """Recheck the current grant and exact frozen scope at every provider entry."""
    grant = observation_daily_job_grant(job.payload)
    if grant is None:
        return
    service = ResearchObservationService(db)
    observation = _observation(service, grant)
    _, prefix = _prefix(service, observation, service.clock())
    planned = VerifiedDailyMarketJobRequest.from_payload(job.payload)
    if (
        planned.instruments != prefix.instruments
        or planned.trade_date <= prefix.end_date
        or (planned.trade_date - prefix.start_date).days >= 366
        or planned.source_policy_id
        != verification_source_policy_for_config(config).policy_id
    ):
        raise ValueError("observation_data_preparation_job_scope_mismatch")


def _daily_jobs(db, config, store, observation, prefix, through, now, grant, stopped):
    if through == prefix.end_date:
        return ()
    dates = resolve_verified_closed_trading_dates_in_range(
        db, now, start_date=prefix.end_date + timedelta(days=1), end_date=through
    )
    if not dates:
        raise ValueError("observation_data_preparation_calendar_unavailable")
    if (len(prefix.partitions) + len(dates)) * len(prefix.instruments) > observation[
        "policy"
    ]["max_dataset_rows"]:
        raise ValueError("observation_dataset_budget_exceeded")
    source_policy = verification_source_policy_for_config(config).policy_id
    prior = store.list_verified_observation_jobs(
        observation["id"], start_date=dates[0].trade_date, end_date=through.isoformat()
    )
    payloads, reuse = [], {}
    for resolved in dates:
        base = VerifiedDailyMarketJobRequest(
            date.fromisoformat(resolved.trade_date),
            prefix.instruments,
            source_policy,
            resolved.calendar_evidence_refs,
        ).to_payload()
        candidates = [store.get(job_id_for(VERIFIED_DAILY_MARKET_JOB, base)), *prior]
        for candidate in candidates:
            if candidate is None or candidate.status != "succeeded":
                continue
            comparable = {
                key: value
                for key, value in candidate.payload.items()
                if key != "observation_automation"
            }
            if comparable == base:
                reuse[resolved.trade_date] = candidate
                break
        else:
            payloads.append({**base, "observation_automation": grant})
    queued = store.enqueue_many(
        VERIFIED_DAILY_MARKET_JOB,
        payloads,
        now=now,
        guard=lambda conn: guard_observation_data_preparation(conn, grant, stopped),
    )
    reuse.update({job.payload["trade_date"]: job for job in queued})
    return tuple(reuse[resolved.trade_date] for resolved in dates)


def _prepare(service, config, store, observation, now, grant, stopped):
    ref, prefix = _prefix(service, observation, now)
    if prefix.resolver_policy_id != verified_daily_resolver_policy_id(
        verification_source_policy_for_config(config).policy_id
    ):
        raise ValueError("observation_data_preparation_source_policy_changed")
    closed = resolve_latest_verified_closed_trading_date(service.db, now)
    if closed is None:
        raise ValueError("observation_data_preparation_calendar_unavailable")
    through = date.fromisoformat(closed.trade_date)
    if through < prefix.end_date:
        raise ValueError("observation_data_preparation_source_not_closed")
    if (through - prefix.start_date).days >= 366:
        raise ValueError("observation_data_preparation_range_exceeds_366_days")
    jobs = _daily_jobs(
        service.db, config, store, observation, prefix, through, now, grant, stopped
    )
    job_ids = tuple(job.job_id for job in jobs)
    if any(job.status != "succeeded" for job in jobs):
        return {
            "status": "blocked"
            if any(job.status == "failed" for job in jobs)
            else "waiting",
            "through_session": through.isoformat(),
            "job_ids": list(job_ids),
            "pending_job_ids": [
                job.job_id for job in jobs if job.status != "succeeded"
            ],
            "last_blocker": {"code": "verified_interval_job_incomplete"},
        }
    published = AutomationRunRepository(service.db.path).publish_observation_dataset(
        observation_id=observation["id"],
        generation=grant["generation"],
        stop_requested=stopped,
        publish=lambda: publish_verified_interval_dataset(
            service.db.path.resolve().parent / "research",
            DailyBarRequest(prefix.instruments, prefix.start_date, through),
            db=service.db,
            job_ids=job_ids,
            prefix_dataset_id=ref.dataset_id,
        ),
    )
    return {
        "status": "completed",
        "through_session": through.isoformat(),
        "job_ids": list(job_ids),
        "dataset_id": published["dataset_id"],
        "last_blocker": None,
    }


def run_research_observation_data_preparation_once(
    db,
    config,
    *,
    now: datetime | None = None,
    stop_requested: threading.Event | None = None,
) -> list[dict[str, Any]]:
    """Prepare inputs only; target publication retains its original deadline."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("observation_data_preparation_clock_timezone_required")
    stop = stop_requested or threading.Event()

    def stopped():
        return stop.is_set() or is_release_activation_guarded()

    service = ResearchObservationService(db, clock=lambda: now)
    runs = AutomationRunRepository(db.path)
    store = SQLiteJobStore(db.path)
    reports = []
    for policy in runs.list_observation_automation_policies():
        if stopped():
            break
        identity = policy.get("observation_id")
        if (
            not isinstance(identity, str)
            or not observation_automation_policy_valid(policy, identity)
            or not policy.get("dataset_preparation_enabled", False)
        ):
            continue
        grant = {"observation_id": identity, "generation": policy["generation"]}
        try:
            observation = _observation(service, grant)
            payload = _prepare(service, config, store, observation, now, grant, stopped)
        except ValueError as exc:
            code = str(exc)
            payload = {
                "status": "waiting"
                if code == "observation_data_preparation_calendar_unavailable"
                else "blocked",
                "last_blocker": {"code": code},
            }
        except Exception:
            logger.exception("Research observation input preparation failed")
            payload = {
                "status": "blocked",
                "last_blocker": {"code": "observation_data_preparation_failed"},
            }
        payload.update(generation=policy["generation"], last_checked_at=now.isoformat())
        if runs.record_observation_automation_status(
            {
                "run_id": f"research-observation-automation:{identity}:latest:data",
                "run_type": "research_observation_dataset_preparation",
                "run_date": now.date().isoformat(),
                "status": payload["status"],
                "execution_mode": "research_inputs",
                "source_ref": identity,
                "payload": payload,
            },
            observation_id=identity,
            generation=policy["generation"],
            stop_requested=stopped,
            now=now.isoformat(),
            dataset_preparation=True,
        ):
            reports.append(payload)
    return reports
