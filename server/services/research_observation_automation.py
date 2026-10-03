"""Opt-in local scheduling over existing immutable observation inputs."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import date, datetime, time, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo

from core.types import InstrumentKey
from data.dataset.catalog import DatasetCatalog
from data.dataset.manifest import (
    DatasetManifestError,
    read_daily_bar_dataset_manifest,
)
from data.storage.objects import ObjectStoreError
from server.contracts.content_identity import content_fingerprint
from server.contracts.research_observation_automation import (
    OBSERVATION_AUTOMATION_SCHEMA,
    OBSERVATION_DATASET_SELECTION,
    observation_automation_policy_valid,
)
from server.persistence.automation_runs import AutomationRunRepository
from server.release_activation import (
    is_release_activation_guarded,
    wait_for_release_activation,
)
from server.services.research_observation_inputs import (
    latest_closed_session,
    observation_outcome_sessions,
    read_research_observation_dataset,
)
from server.services.research_observations import (
    ResearchObservationService,
    observation_code_binding,
)

logger = logging.getLogger(__name__)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
OBSERVATION_AUTOMATION_INTERVAL_SECONDS = 300.0


def configure_observation_automation(
    service: ResearchObservationService,
    observation_id: str,
    *,
    enabled: bool,
    expected_generation: str | None,
) -> dict[str, Any]:
    payload = {
        "schema_version": OBSERVATION_AUTOMATION_SCHEMA,
        "observation_id": observation_id,
        "enabled": enabled,
        "generation": str(uuid4()),
        "dataset_selection": OBSERVATION_DATASET_SELECTION,
        "local_data_only": True,
        "account_authority": False,
    }
    now = _now(service)
    AutomationRunRepository(service.db.path).configure_observation_automation(
        payload=payload, expected_generation=expected_generation, now=now.isoformat()
    )
    return project_observation_automation(
        service, service.repository.get(observation_id)
    )


def project_observation_automation(service, observation) -> dict[str, Any]:
    identity = observation["id"]
    store = AutomationRunRepository(service.db.path)
    policy = store.get_observation_automation_policy(identity)
    valid = observation_automation_policy_valid(policy, identity)
    enabled = valid and policy["enabled"] is True
    run = store.get_automation_run_sync(_run_id(identity))
    payload = _run_payload(run)
    invalid_run = payload is None
    payload = payload or {}
    generation = policy.get("generation") if isinstance(policy, dict) else None
    if payload.get("generation") != generation:
        payload = {}
    if policy is not None and not valid:
        status, blocker = "blocked", {"code": "observation_automation_policy_invalid"}
    elif not enabled:
        status, blocker = "disabled", None
    elif observation["lifecycle"] != "active":
        status, blocker = "paused", observation.get("last_blocker")
    elif invalid_run:
        status, blocker = (
            "blocked",
            {"code": "observation_automation_status_unavailable"},
        )
    else:
        status, blocker = payload.get("status", "ready"), payload.get("last_blocker")
    return {
        "observation_id": identity,
        "enabled": enabled,
        "generation": generation,
        "status": status,
        "last_checked_at": payload.get("last_checked_at"),
        "last_attempt_at": payload.get("last_attempt_at"),
        "last_blocker": blocker,
        "dataset_id": payload.get("dataset_id"),
        "decision_session": payload.get("decision_session"),
        "unreadable_candidate_dataset_ids": payload.get(
            "unreadable_candidate_dataset_ids", []
        ),
        "dataset_discovery_complete": payload.get("dataset_discovery_complete"),
        "dataset_selection": OBSERVATION_DATASET_SELECTION,
        "local_data_only": True,
        "account_authority": False,
    }


def _now(service) -> datetime:
    now = service.clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("observation_automation_clock_timezone_required")
    return now.astimezone(timezone.utc)


def _run_id(identity: str) -> str:
    return f"research-observation-automation:{identity}:latest"


def _run_payload(run) -> dict[str, Any] | None:
    """Operational status is rebuildable; corrupt rows cannot block other books."""
    if run is None:
        return {}
    try:
        payload = json.loads(run["payload_json"])
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _select_dataset(
    service, observation, now, decision_session, *, unreadable_candidate_dataset_ids
):
    """Discover a matching manifest; the caller must validate its bound inputs."""
    start = date.fromisoformat(observation["source"]["start_date"])
    instruments = tuple(
        sorted(
            (
                InstrumentKey.from_values(item["symbol"], item["instrument_type"])
                for item in observation["universe"]
            ),
            key=lambda item: (item.instrument_type.value, item.symbol),
        )
    )
    catalog = DatasetCatalog(service.db.path.resolve().parent / "research")
    if not catalog.path.exists():
        raise ValueError("observation_automation_dataset_missing")
    try:
        # Catalog bounds are inequalities. Filter exact dates before selecting,
        # and do not apply the UI's recent-item limit to this consumer.
        candidates = catalog.list_daily_bar_datasets(
            start_date=start, end_date=decision_session, cutoff_lte=now
        )
        for entry in candidates:
            if entry.start_date != start or entry.end_date != decision_session:
                continue
            try:
                snapshot = read_daily_bar_dataset_manifest(service.objects, entry.ref)
            except (DatasetManifestError, ObjectStoreError, OSError):
                # The catalog has no typed universe. An unreadable manifest is
                # unknown discovery evidence, not proof that this book is bad.
                unreadable_candidate_dataset_ids.append(entry.ref.dataset_id)
                continue
            if not snapshot.verification_bound or snapshot.instruments != instruments:
                continue
            return entry, snapshot
    except ValueError:
        raise
    except Exception:
        raise ValueError("observation_automation_dataset_unreadable") from None
    raise ValueError("observation_automation_dataset_missing")


def _record_status(
    service,
    observation,
    policy,
    *,
    now,
    status,
    stop_requested,
    blocker=None,
    dataset_id=None,
    decision_session=None,
    attempted=False,
    unreadable_candidate_dataset_ids=None,
):
    store = AutomationRunRepository(service.db.path)
    previous = store.get_automation_run_sync(_run_id(observation["id"]))
    previous_payload = _run_payload(previous) or {}
    last_attempt = (
        previous_payload.get("last_attempt_at")
        if previous_payload.get("generation") == policy["generation"]
        else None
    )
    same_selection = previous_payload.get("generation") == policy[
        "generation"
    ] and previous_payload.get("decision_session") == (
        decision_session.isoformat() if decision_session else None
    )
    if same_selection and dataset_id is None:
        dataset_id = previous_payload.get("dataset_id")
    discovery_complete = (
        previous_payload.get("dataset_discovery_complete") if same_selection else None
    )
    if unreadable_candidate_dataset_ids is None:
        unreadable_candidate_dataset_ids = (
            previous_payload.get("unreadable_candidate_dataset_ids", [])
            if same_selection
            else []
        )
    else:
        discovery_complete = not unreadable_candidate_dataset_ids
    payload = {
        "generation": policy["generation"],
        "status": status,
        "last_checked_at": now.isoformat(),
        "last_attempt_at": now.isoformat() if attempted else last_attempt,
        "last_blocker": {"code": blocker} if blocker else None,
        "dataset_id": dataset_id,
        "decision_session": decision_session.isoformat() if decision_session else None,
        "unreadable_candidate_dataset_ids": unreadable_candidate_dataset_ids,
        "dataset_discovery_complete": discovery_complete,
    }
    recorded = store.record_observation_automation_status(
        {
            "run_id": _run_id(observation["id"]),
            "run_type": "research_observation_automation",
            "run_date": now.astimezone(_SHANGHAI).date().isoformat(),
            "status": status,
            "execution_mode": "independent_target_shadow",
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "source_ref": observation["id"],
            "payload": payload,
        },
        observation_id=observation["id"],
        generation=policy["generation"],
        stop_requested=stop_requested,
        now=now.isoformat(),
    )
    return payload if recorded else None


def run_research_observation_automation_once(
    service: ResearchObservationService,
    *,
    stop_requested: threading.Event | None = None,
) -> list[dict[str, Any]]:
    """One sequential local pass; unavailable data never changes book version."""
    stop = stop_requested or threading.Event()

    def stopped():
        try:
            return stop.is_set() or is_release_activation_guarded()
        except Exception:
            return True

    if stopped():
        return []
    reports = []
    policies = AutomationRunRepository(
        service.db.path
    ).list_observation_automation_policies()
    for policy in policies:
        if stopped():
            break
        identity = policy.get("observation_id") if isinstance(policy, dict) else None
        if (
            not observation_automation_policy_valid(policy, identity)
            or not policy["enabled"]
        ):
            continue
        observation = service.repository.get(identity)
        if observation is None or observation["lifecycle"] != "active":
            continue
        now = _now(service)
        decision_session = None
        dataset_id = None
        attempted = False
        unreadable_candidate_dataset_ids = None
        try:
            if observation["code_binding"] != observation_code_binding():
                raise ValueError("observation_code_changed")
            calendar = service._calendar(
                date.fromisoformat(observation["source"]["start_date"]), now
            )
            decision_session = latest_closed_session(calendar, now=now)
            # Automatic publication belongs to the just-closed session's window,
            # never to a missed session recovered after its next opening.
            anchor = datetime.combine(decision_session, time(16), _SHANGHAI)
            if now < anchor:
                raise ValueError("observation_automation_waiting_after_close")
            try:
                reference, _ = observation_outcome_sessions(
                    calendar,
                    published_at=anchor,
                    horizon_sessions=observation["policy"]["horizon_sessions"],
                    now=now,
                )
            except ValueError as exc:
                if str(exc) != "observation_calendar_horizon_missing":
                    raise
                row = service.db.get_market_calendar_snapshot_sync(
                    exchange="SSE", year=now.astimezone(_SHANGHAI).year + 1
                )
                if row is None:
                    raise
                calendar.append(row)
                reference, _ = observation_outcome_sessions(
                    calendar,
                    published_at=anchor,
                    horizon_sessions=observation["policy"]["horizon_sessions"],
                    now=now,
                )
            publication_deadline = datetime.combine(reference, time(9, 30), _SHANGHAI)
            if now >= publication_deadline:
                raise ValueError("observation_automation_publication_window_missed")
            published = any(
                item["decision_session"] == decision_session.isoformat()
                for item in observation["publications"]
            )
            measured = {item["publication_id"] for item in observation["outcomes"]}
            due_outcomes = any(
                item["id"] not in measured
                and date.fromisoformat(item["payload"]["end_session"])
                <= decision_session
                for item in observation["publications"]
            )
            if published and not due_outcomes:
                status, blocker = "completed", None
            else:
                unreadable_candidate_dataset_ids = []
                entry, snapshot = _select_dataset(
                    service,
                    observation,
                    now,
                    decision_session,
                    unreadable_candidate_dataset_ids=unreadable_candidate_dataset_ids,
                )
                # Bind the identified matching candidate before reading evidence:
                # validation failure must expose this ID and never try an older
                # matching Dataset. Catalog metadata alone cannot admit it.
                dataset_id = entry.ref.dataset_id
                if (snapshot.start_date, snapshot.end_date, snapshot.cutoff) != (
                    date.fromisoformat(observation["source"]["start_date"]),
                    decision_session,
                    entry.cutoff,
                ):
                    raise ValueError("observation_automation_catalog_mismatch")
                result = read_research_observation_dataset(
                    service.objects,
                    dataset_id,
                    instruments=snapshot.instruments,
                    start_date=snapshot.start_date,
                    now=now,
                    calendar_rows=calendar,
                    minimum_bars=observation["source"]["minimum_bars"],
                )
                if len(result.bars) > observation["policy"]["max_dataset_rows"]:
                    raise ValueError("observation_dataset_budget_exceeded")
                if published and not service._outcomes(
                    observation, result, dataset_id, now, decision_session
                ):
                    raise ValueError("observation_automation_outcome_unavailable")
                if stopped():
                    break
                request_id = str(
                    uuid5(
                        NAMESPACE_URL,
                        content_fingerprint(
                            {
                                "observation_id": identity,
                                "decision_session": decision_session.isoformat(),
                                "dataset_id": dataset_id,
                                "expected_version": observation["version"],
                                "automation_generation": policy["generation"],
                            }
                        ),
                    )
                )
                attempted = True
                result = service.advance(
                    identity,
                    request_id=request_id,
                    expected_version=observation["version"],
                    dataset_id=dataset_id,
                    automation_generation=policy["generation"],
                    automation_stop_requested=stopped,
                    automation_publication_deadline=publication_deadline,
                )
                blocker = (result.get("last_blocker") or {}).get("code")
                status = (
                    "paused"
                    if result["lifecycle"] == "paused"
                    else (
                        "completed"
                        if blocker in (None, "observation_session_already_published")
                        else "waiting"
                    )
                )
        except ValueError as exc:
            blocker = str(exc)
            status = "blocked" if blocker == "observation_code_changed" else "waiting"
        except Exception:
            logger.exception("Local research observation scheduling failed")
            status, blocker = "blocked", "observation_automation_failed"
        if not stopped():
            report = _record_status(
                service,
                observation,
                policy,
                now=now,
                status=status,
                stop_requested=stopped,
                blocker=blocker,
                dataset_id=dataset_id,
                decision_session=decision_session,
                attempted=attempted,
                unreadable_candidate_dataset_ids=unreadable_candidate_dataset_ids,
            )
            if report is not None:
                reports.append(report)
    return reports


async def run_research_observation_automation_loop(
    *, db, interval_seconds: float = OBSERVATION_AUTOMATION_INTERVAL_SECONDS
) -> None:
    service = ResearchObservationService(db)
    stop = threading.Event()
    work = None
    try:
        while True:
            await wait_for_release_activation()
            work = asyncio.create_task(
                asyncio.to_thread(
                    run_research_observation_automation_once,
                    service,
                    stop_requested=stop,
                )
            )
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Local observation automation pass failed")
            await asyncio.sleep(max(30.0, interval_seconds))
    finally:
        stop.set()
        # Cancelling to_thread does not stop the writer. Drain its bounded local
        # pass before lifespan closes, and fence work waiting on the write lock.
        if work is not None:
            try:
                await asyncio.shield(work)
            except Exception:
                logger.exception("Local observation pass failed while stopping")
