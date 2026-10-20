"""Bounded prospective dividend supply through the existing leased data queue."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from data.dataset.catalog import DatasetCatalog
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.reader import read_daily_bar_dataset
from data.market.contracts import MarketDataProviderDescriptor
from data.market.corporate_actions import (
    WINDOW_SCHEMA,
    publish_corporate_action_window,
    read_corporate_action_window,
    read_market_dividend_day,
)
from data.providers.tushare_corporate_actions import collect_tushare_market_dividend_day
from data.storage.objects import ContentAddressedObjectStore
from server.contracts.research_observation_automation import (
    read_research_validation_policy,
)
from server.persistence.automation_runs import (
    AutomationRunRepository,
    require_corporate_action_capture_permission,
)
from server.persistence.jobs import SQLiteJobStore

CORPORATE_ACTION_DAY_JOB = "research_corporate_action_day"
DIVIDEND_DESCRIPTOR = MarketDataProviderDescriptor(
    "tushare", "tushare", "karkinos.tushare.dividend.v1", ()
)
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def require_corporate_action_job_permission(conn, payload, *, now):
    """Revoke or replace either existing opt-in before more provider I/O."""
    require_corporate_action_capture_permission(conn, payload["permission"], now=now)
    day = date.fromisoformat(payload["date"])
    if now < datetime.combine(day, time(21), _SHANGHAI):
        raise ValueError("tushare_dividend_update_window_pending")


def ensure_dataset_corporate_actions(
    db,
    config,
    *,
    snapshot,
    now,
    prospective_start,
    permission=None,
    previous_observation_ids=(),
    stopped=lambda: False,
):
    """Queue actual market-date queries, then bind a fully replayable window.

    The start belongs to the fresh cash book, never to exploratory price warmup.
    Four calls/day cover all typed members, independent of basket size.
    """
    root = db.path.resolve().parent / "research"
    objects = ContentAddressedObjectStore(root / "objects")
    if not str(getattr(config, "tushare_token", "") or "").strip():
        return {
            "status": "blocked",
            "job_ids": [],
            "last_blocker": {"code": "corporate_action_tushare_token_required"},
        }
    if permission is None:
        try:
            grant = read_research_validation_policy(db, now=now)
            if grant["deployment_scope_fingerprint"] != snapshot.universe_policy_id:
                raise ValueError("corporate_action_publication_scope_mismatch")
            permission = {
                "kind": "simulation"
                if grant.get("schema_version")
                == "karkinos.research_simulation_policy.v1"
                else "publication",
                **{
                    key: grant[key]
                    for key in (
                        "grant_id",
                        "generation",
                        "deployment_scope_fingerprint",
                    )
                },
            }
        except ValueError as exc:
            return {
                "status": "blocked",
                "job_ids": [],
                "last_blocker": {"code": str(exc)},
            }
    local = now.astimezone(_SHANGHAI)
    through = local.date() - (
        timedelta(days=1) if local.time() < time(21) else timedelta()
    )
    if through < snapshot.end_date:
        return {
            "status": "waiting",
            "job_ids": [],
            "last_blocker": {"code": "tushare_dividend_update_window_pending"},
        }
    previous = None
    if len(previous_observation_ids) == 1:
        previous_ref = objects.resolve_ref(previous_observation_ids[0])
        if (
            json.loads(objects.read_bytes(previous_ref)).get("schema_version")
            == WINDOW_SCHEMA
        ):
            previous = read_corporate_action_window(objects, previous_ref)
            if datetime.fromisoformat(previous["available_at"]) > now:
                raise ValueError("corporate_action_previous_window_not_available")
    start = (
        date.fromisoformat(previous["coverage_start_date"])
        if previous
        else prospective_start
    )
    if (through - start).days > 3652 or through < start:
        return {
            "status": "blocked",
            "job_ids": [],
            "last_blocker": {"code": "corporate_action_window_budget_exceeded"},
        }
    identities = list(previous["day_observation_ids"]) if previous else []
    begin = (
        date.fromisoformat(previous["coverage_end_date"]) + timedelta(days=1)
        if previous
        else start
    )
    payloads = [
        {"date": (begin + timedelta(days=index)).isoformat(), "permission": permission}
        for index in range((through - begin).days + 1)
    ]

    def guard(conn):
        if stopped():
            raise ValueError("corporate_action_preparation_stopped")
        require_corporate_action_job_permission(
            conn,
            {"date": through.isoformat(), "permission": permission},
            now=max(now, datetime.now(timezone.utc)),
        )

    jobs = SQLiteJobStore(db.path).enqueue_many(
        CORPORATE_ACTION_DAY_JOB, payloads, now=now, guard=guard
    )
    if any(job.status != "succeeded" for job in jobs):
        return {
            "status": "blocked"
            if any(job.status == "failed" for job in jobs)
            else "waiting",
            "job_ids": [job.job_id for job in jobs],
            "pending_job_ids": [
                job.job_id for job in jobs if job.status != "succeeded"
            ],
            "last_blocker": {
                "code": next(
                    (job.error for job in jobs if job.status == "failed" and job.error),
                    "corporate_action_jobs_incomplete",
                )
            },
        }
    for job in jobs:
        if not job.result_ref or not job.result_ref.startswith(
            "corporate_action_day:sha256:"
        ):
            raise ValueError("corporate_action_job_result_invalid")
        identity = job.result_ref.removeprefix("corporate_action_day:")
        day = read_market_dividend_day(objects, objects.resolve_ref(identity))
        if day["date"].isoformat() != job.payload["date"] or day["available_at"] > now:
            raise ValueError("corporate_action_job_result_invalid")
        identities.append(identity)
    # Heavy immutable composition and canonical replay do not hold the account
    # DB write lock. Revocation may leave inert CAS bytes; only the final fresh
    # generation check admits this candidate into the public catalog.
    window = publish_corporate_action_window(
        objects, instruments=snapshot.instruments, day_observation_ids=identities
    )
    evidence = read_corporate_action_window(objects, window)
    combined = replace(
        snapshot,
        corporate_action_observation_ids=(window.object_id,),
        cutoff=max(snapshot.cutoff, datetime.fromisoformat(evidence["available_at"])),
    )
    ref = publish_daily_bar_dataset_manifest(objects, combined)
    read_daily_bar_dataset(objects, ref)
    AutomationRunRepository(db.path).publish_corporate_action_dataset(
        permission=permission,
        now=max(now, datetime.now(timezone.utc)),
        stop_requested=stopped,
        publish=lambda: DatasetCatalog(root).register(objects, ref),
    )
    return {
        "status": "ready",
        "dataset_id": ref.dataset_id,
        "job_ids": [job.job_id for job in jobs],
        "last_blocker": None,
    }


class CorporateActionDayService:
    """Concrete provider adapter for the existing data worker's fenced executor."""

    def __init__(self, root: Path, config):
        self.objects = ContentAddressedObjectStore(root / "objects")
        self.config = config

    def run(
        self, payload, *, before_publish, before_provider_fetch, publication_guard=None
    ):
        ref = collect_tushare_market_dividend_day(
            self.objects,
            day=date.fromisoformat(payload["date"]),
            token=self.config.tushare_token,
            before_fetch=lambda: before_provider_fetch(DIVIDEND_DESCRIPTOR),
        )
        before_publish()
        # Captures are append-only. A revoked generation can leave inert CAS
        # bytes, but cannot finish the job or publish any Dataset composition.
        return "corporate_action_day:" + ref.object_id
