"""Local scheduled observations through real HTTP, immutable inputs and SQLite."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from functools import partial
from uuid import uuid4

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import DatasetCatalog
from data.dataset.manifest import (
    publish_daily_bar_dataset_manifest,
    read_daily_bar_dataset_manifest,
)
from server.contracts.research_observation_automation import (
    observation_automation_policy_id,
)
from server.release_activation import wait_for_release_activation
from server.services import research_observation_automation as automation
from server.services.research_observations import ResearchObservationService
from tests.server.test_research_observation_inputs import DAYS, NOW, calendar, dataset
from tests.server.test_research_observations_health import policy, request_start
from tests.server.test_research_observations_journey import journey, start  # noqa: F401

pytestmark = pytest.mark.product_smoke


def toggle(client, identity, enabled=True, generation=None):
    response = client.put(
        f"/api/research-observations/{identity}/automation",
        json={"enabled": enabled, "expected_generation": generation},
    )
    assert response.status_code == 200, response.text
    return response.json()


def register(service, ref):
    return DatasetCatalog(service.db.path.parent / "research").register(
        service.objects, ref, registered_at=service.clock()
    )


def extend_calendar(service):
    service.db.upsert_market_calendar_snapshot_sync(
        calendar(trading_days=(*DAYS, date(2026, 9, 24), date(2026, 9, 25)))
    )
    service.db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2026,
        source_fingerprint="a" * 64,
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="b" * 64,
        verified_by="synthetic fixture",
    )


def receipt_count(service, identity):
    with sqlite3.connect(service.db.path) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM research_observation_operations WHERE observation_id=?",
            (identity,),
        ).fetchone()[0]


def test_explicit_opt_in_projects_in_list_and_restart_does_not_duplicate(journey):
    client, service, current, ref, result_id = journey
    started, _ = start(client, result_id)
    other, _ = start(client, result_id)
    identity = started["id"]
    path = f"/api/research-observations/{identity}"
    assert client.get(path).json()["automation"]["status"] == "disabled"
    assert automation.run_research_observation_automation_once(service) == []
    register(service, ref)
    enabled = toggle(client, identity)
    assert enabled["status"] == "ready"
    assert enabled["enabled"] is True
    assert enabled["account_authority"] is False
    stale = client.put(path + "/automation", json={"enabled": False})
    assert stale.status_code == 409
    assert client.put(path + "/automation", json={"enabled": "true"}).status_code == 422

    first = automation.run_research_observation_automation_once(service)
    assert first[0]["status"] == "completed", first
    assert first[0]["dataset_discovery_complete"] is True
    detail = client.get(path).json()
    assert detail["version"] == 1
    publication = detail["publications"][0]
    assert publication["payload"]["publication_actor"] == "local_schedule"
    assert publication["payload"]["automation_generation"] == enabled["generation"]
    assert publication["decision_session"] == DAYS[4].isoformat()
    assert service.repository.get(other["id"])["version"] == 0
    assert (
        next(
            item
            for item in client.get("/api/research-observations").json()
            if item["id"] == identity
        )
        == detail
    )
    receipts = receipt_count(service, identity)
    reopened = ResearchObservationService(service.db, clock=lambda: current[0])
    second = automation.run_research_observation_automation_once(reopened)
    assert second[0]["status"] == "completed"
    assert second[0]["dataset_discovery_complete"] is True
    assert second[0]["dataset_id"] == ref.dataset_id
    assert service.repository.get(identity)["version"] == 1
    assert receipt_count(service, identity) == receipts

    disabled = toggle(client, identity, False, enabled["generation"])
    assert disabled["status"] == "disabled"
    assert disabled["generation"] != enabled["generation"]
    assert automation.run_research_observation_automation_once(reopened) == []


def test_missing_local_dataset_waits_and_recovers_without_restart(journey):
    client, service, _, ref, result_id = journey
    started, _ = start(client, result_id)
    toggle(client, started["id"])
    for _ in range(2):
        report = automation.run_research_observation_automation_once(service)[0]
        assert report["status"] == "waiting"
        assert (
            report["last_blocker"]["code"] == "observation_automation_dataset_missing"
        )
    assert service.repository.get(started["id"])["version"] == 0
    register(service, ref)
    assert (
        automation.run_research_observation_automation_once(service)[0]["status"]
        == "completed"
    )
    assert len(service.repository.get(started["id"])["publications"]) == 1


@pytest.mark.parametrize("bad_payload", ["{", "null", "[]", "42", "bad_generation"])
def test_bad_policy_isolated_in_reads_and_scheduler_and_explicitly_repairable(
    journey, bad_payload
):
    client, service, _, ref, result_id = journey
    bad, _ = start(client, result_id)
    good, _ = start(client, result_id)
    toggle(client, bad["id"])
    good_policy = toggle(client, good["id"])
    register(service, ref)
    with sqlite3.connect(service.db.path) as conn:
        identity = observation_automation_policy_id(bad["id"])
        if bad_payload == "bad_generation":
            stored = json.loads(
                conn.execute(
                    "SELECT payload_json FROM automation_policies WHERE policy_id=?",
                    (identity,),
                ).fetchone()[0]
            )
            stored["generation"] = "not-a-uuid"
            bad_payload = json.dumps(stored)
        conn.execute(
            "UPDATE automation_policies SET payload_json=? WHERE policy_id=?",
            (bad_payload, identity),
        )
    response = client.get("/api/research-observations")
    assert response.status_code == 200, response.text
    bad_projection = next(item for item in response.json() if item["id"] == bad["id"])[
        "automation"
    ]
    assert bad_projection["status"] == "blocked"
    assert (
        bad_projection["last_blocker"]["code"]
        == "observation_automation_policy_invalid"
    )
    assert bad_projection["enabled"] is False
    assert bad_projection["generation"] is None
    assert (
        client.get(f"/api/research-observations/{bad['id']}").json()["automation"]
        == bad_projection
    )
    reports = automation.run_research_observation_automation_once(service)
    assert len(reports) == 1
    assert reports[0]["status"] == "completed"
    assert service.repository.get(bad["id"])["version"] == 0
    assert service.repository.get(good["id"])["version"] == 1
    repaired = toggle(client, bad["id"], False)
    assert repaired["status"] == "disabled"
    assert repaired["generation"] is not None
    # Recovery of invalid configuration does not weaken a valid generation CAS.
    response = client.put(
        f"/api/research-observations/{good['id']}/automation", json={"enabled": False}
    )
    assert response.status_code == 409
    assert (
        toggle(client, good["id"], False, good_policy["generation"])["status"]
        == "disabled"
    )


def test_enabled_observation_is_not_hidden_by_recent_paused_history(journey):
    client, service, _, ref, result_id = journey
    started, _ = start(client, result_id)
    toggle(client, started["id"])
    register(service, ref)
    # Historical books are valid persisted rows, all more recent than the sole
    # active opt-in. The UI's 100-row window must not become scheduler admission.
    with sqlite3.connect(service.db.path) as conn:
        conn.row_factory = sqlite3.Row
        prototype = dict(
            conn.execute(
                "SELECT * FROM research_observations WHERE id=?", (started["id"],)
            ).fetchone()
        )
        columns = tuple(prototype)
        for _ in range(101):
            row = {
                **prototype,
                "id": str(uuid4()),
                "lifecycle": "paused",
                "started_at": (NOW + timedelta(seconds=1)).isoformat(),
            }
            conn.execute(
                f"INSERT INTO research_observations ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(row[key] for key in columns),
            )
    assert started["id"] not in {
        item["id"] for item in client.get("/api/research-observations?limit=100").json()
    }
    reports = automation.run_research_observation_automation_once(service)
    assert reports[0]["status"] == "completed"
    assert service.repository.get(started["id"])["version"] == 1


@pytest.mark.parametrize("bad_payload", ["{", "null", "[]"])
def test_bad_operational_status_is_local_and_rebuilt_without_book_writes(
    journey, bad_payload
):
    client, service, _, ref, result_id = journey
    bad, _ = start(client, result_id)
    toggle(client, bad["id"])
    register(service, ref)
    automation.run_research_observation_automation_once(service)
    good, _ = start(client, result_id)
    toggle(client, good["id"])
    with sqlite3.connect(service.db.path) as conn:
        conn.execute(
            "UPDATE automation_runs SET payload_json=? WHERE source_ref=?",
            (bad_payload, bad["id"]),
        )
    response = client.get("/api/research-observations")
    assert response.status_code == 200, response.text
    blocked = next(item for item in response.json() if item["id"] == bad["id"])
    assert blocked["automation"]["status"] == "blocked"
    assert (
        blocked["automation"]["last_blocker"]["code"]
        == "observation_automation_status_unavailable"
    )
    reports = automation.run_research_observation_automation_once(service)
    assert len(reports) == 2
    assert all(item["status"] == "completed" for item in reports)
    assert service.repository.get(bad["id"])["version"] == 1
    assert service.repository.get(good["id"])["version"] == 1
    assert (
        client.get(f"/api/research-observations/{bad['id']}").json()["automation"][
            "status"
        ]
        == "completed"
    )


def test_failure_after_dataset_preflight_does_not_create_empty_automatic_receipts(
    journey, monkeypatch
):
    client, service, _, ref, result_id = journey
    started, _ = start(client, result_id)
    toggle(client, started["id"])
    register(service, ref)

    def unavailable(*args):
        raise ValueError("observation_bound_evidence_unreadable")

    monkeypatch.setattr(service, "_publication", unavailable)
    before = receipt_count(service, started["id"])
    for _ in range(2):
        report = automation.run_research_observation_automation_once(service)[0]
        assert report["status"] == "waiting"
        assert report["last_blocker"]["code"] == "observation_bound_evidence_unreadable"
    assert service.repository.get(started["id"])["version"] == 0
    assert receipt_count(service, started["id"]) == before


def test_newest_exact_verified_prefix_skips_other_universe_and_unknown_manifests(
    journey, tmp_path
):
    client, service, current, ref, result_id = journey
    started, _ = start(client, result_id)
    toggle(client, started["id"])
    register(service, ref)
    snapshot = read_daily_bar_dataset_manifest(service.objects, ref)
    unrelated = publish_daily_bar_dataset_manifest(
        service.objects,
        replace(
            snapshot,
            instruments=(InstrumentKey("000001", InstrumentType.STOCK),),
            cutoff=NOW + timedelta(seconds=1),
        ),
    )
    register(service, unrelated)
    unknown = publish_daily_bar_dataset_manifest(
        service.objects, replace(snapshot, cutoff=NOW + timedelta(seconds=2))
    )
    register(service, unknown)
    service.objects._path_for(unknown.dataset_id).chmod(0o600)
    service.objects._path_for(unknown.dataset_id).write_bytes(
        b"broken manifest fixture"
    )
    _, unverified = dataset(
        tmp_path / "research", verified=False, cutoff=NOW + timedelta(seconds=3)
    )
    register(service, unverified)
    _, wrong_start = dataset(
        tmp_path / "research", days=DAYS[1:5], cutoff=NOW + timedelta(seconds=4)
    )
    register(service, wrong_start)
    future = publish_daily_bar_dataset_manifest(
        service.objects, replace(snapshot, cutoff=NOW + timedelta(hours=1))
    )
    register(service, future)
    current[0] = NOW + timedelta(seconds=10)
    report = automation.run_research_observation_automation_once(service)[0]
    assert report["status"] == "completed", report
    assert report["dataset_id"] == ref.dataset_id
    assert report["unreadable_candidate_dataset_ids"] == [unknown.dataset_id]
    assert report["dataset_discovery_complete"] is False
    projection = client.get(f"/api/research-observations/{started['id']}").json()[
        "automation"
    ]
    assert projection["unreadable_candidate_dataset_ids"] == [unknown.dataset_id]
    assert projection["dataset_discovery_complete"] is False


def test_identified_matching_newest_bad_evidence_blocks_without_older_fallback(journey):
    client, service, current, ref, result_id = journey
    started, _ = start(client, result_id)
    toggle(client, started["id"])
    register(service, ref)
    snapshot = read_daily_bar_dataset_manifest(service.objects, ref)
    bad = publish_daily_bar_dataset_manifest(
        service.objects,
        replace(
            snapshot,
            cutoff=NOW + timedelta(seconds=1),
            partitions=(
                *snapshot.partitions[:-1],
                replace(snapshot.partitions[-1], verification_id="sha256:" + "0" * 64),
            ),
        ),
    )
    register(service, bad)
    current[0] = NOW + timedelta(seconds=2)
    report = automation.run_research_observation_automation_once(service)[0]
    assert report["status"] == "waiting", report
    assert report["dataset_id"] == bad.dataset_id
    assert report["last_blocker"] is not None
    assert service.repository.get(started["id"])["version"] == 0


def test_restart_skips_missed_session_and_unresolved_outcomes_do_not_empty_write(
    journey, tmp_path, monkeypatch
):
    client, service, current, ref, result_id = journey
    extend_calendar(service)
    started, _ = start(client, result_id)
    toggle(client, started["id"])
    register(service, ref)
    automation.run_research_observation_automation_once(service)
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    _, future = dataset(tmp_path / "research", days=DAYS[:7], cutoff=current[0])
    register(service, future)
    original = ResearchObservationService._outcomes
    monkeypatch.setattr(
        ResearchObservationService, "_outcomes", staticmethod(lambda *args: [])
    )
    reopened = ResearchObservationService(service.db, clock=lambda: current[0])
    report = automation.run_research_observation_automation_once(reopened)[0]
    assert report["status"] == "completed", report
    detail = service.repository.get(started["id"])
    assert [item["decision_session"] for item in detail["publications"]] == [
        DAYS[4].isoformat(),
        DAYS[6].isoformat(),
    ]
    assert detail["outcomes"] == []
    receipts = receipt_count(service, started["id"])
    for _ in range(2):
        report = automation.run_research_observation_automation_once(reopened)[0]
        assert (
            report["last_blocker"]["code"]
            == "observation_automation_outcome_unavailable"
        )
        assert service.repository.get(started["id"])["version"] == 2
        assert receipt_count(service, started["id"]) == receipts
    monkeypatch.setattr(ResearchObservationService, "_outcomes", staticmethod(original))
    assert (
        automation.run_research_observation_automation_once(reopened)[0]["status"]
        == "completed"
    )
    detail = service.repository.get(started["id"])
    assert detail["version"] == 3
    assert len(detail["publications"]) == 2
    assert len(detail["outcomes"]) == 1


@pytest.mark.parametrize(
    "change", ["disable", "disable_enable", "pause", "stop", "deadline", "activation"]
)
def test_locked_fence_rejects_changed_authorization_or_publication_window(
    journey, monkeypatch, change
):
    client, service, current, ref, result_id = journey
    started, _ = start(client, result_id)
    identity = started["id"]
    enabled = toggle(client, identity)
    register(service, ref)
    reached, release, stop = threading.Event(), threading.Event(), threading.Event()
    guarded = [False]
    monkeypatch.setattr(automation, "is_release_activation_guarded", lambda: guarded[0])
    original = service.repository.advance

    def delayed(**kwargs):
        reached.set()
        assert release.wait(5)
        return original(**kwargs)

    monkeypatch.setattr(service.repository, "advance", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            automation.run_research_observation_automation_once,
            service,
            stop_requested=stop,
        )
        try:
            assert reached.wait(5)
            if change in {"disable", "disable_enable"}:
                disabled = toggle(client, identity, False, enabled["generation"])
                if change == "disable_enable":
                    toggle(client, identity, True, disabled["generation"])
            elif change == "pause":
                service.pause(identity, request_id=str(uuid4()), expected_version=0)
            elif change == "stop":
                stop.set()
            elif change == "activation":
                guarded[0] = True
            else:
                current[0] = datetime(2026, 9, 21, 1, 30, tzinfo=timezone.utc)
        finally:
            release.set()
        reports = pending.result(timeout=5)
    detail = service.repository.get(identity)
    assert detail["publications"] == []
    assert detail["version"] == (1 if change == "pause" else 0)
    if change in {"stop", "activation", "disable", "disable_enable"}:
        assert reports == []
    else:
        assert reports[0]["status"] == "waiting"
    if change == "deadline":
        assert (
            reports[0]["last_blocker"]["code"]
            == "observation_automation_publication_window_missed"
        )


@pytest.mark.parametrize(
    "instant,code",
    [
        (
            datetime(2026, 9, 18, 7, 30, tzinfo=timezone.utc),
            "observation_automation_waiting_after_close",
        ),
        (
            datetime(2026, 9, 21, 2, tzinfo=timezone.utc),
            "observation_automation_publication_window_missed",
        ),
    ],
)
def test_scheduler_waits_until_1600_and_never_publishes_after_next_open(
    journey, instant, code
):
    client, service, current, ref, result_id = journey
    started, _ = start(client, result_id)
    toggle(client, started["id"])
    register(service, ref)
    current[0] = instant
    report = automation.run_research_observation_automation_once(service)[0]
    assert report["last_blocker"]["code"] == code
    assert report["dataset_discovery_complete"] is None
    assert service.repository.get(started["id"])["version"] == 0


def test_real_health_pause_is_persisted_and_never_automatically_resumed(
    journey, tmp_path
):
    client, service, current, _, result_id = journey
    extend_calendar(service)
    closes = dict(zip(DAYS, ("12", "11", "10", "9", "12", "10", "11", "11")))
    _, today = dataset(tmp_path / "research", closes=closes)
    register(service, today)
    started, _ = request_start(client, result_id, policy())
    enabled = toggle(client, started["id"])
    assert (
        automation.run_research_observation_automation_once(service)[0]["status"]
        == "completed"
    )
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    _, future = dataset(
        tmp_path / "research", days=DAYS[:7], closes=closes, cutoff=current[0]
    )
    register(service, future)
    report = automation.run_research_observation_automation_once(service)[0]
    assert report["status"] == "paused", report
    detail = client.get(f"/api/research-observations/{started['id']}").json()
    assert detail["health_decision"]["action"] == "pause_observation"
    assert detail["automation"]["status"] == "paused"
    assert len(detail["publications"]) == 1
    assert len(detail["outcomes"]) == 1
    assert automation.run_research_observation_automation_once(service) == []
    assert service.repository.get(started["id"])["version"] == detail["version"]
    response = client.put(
        f"/api/research-observations/{started['id']}/automation",
        json={"enabled": True, "expected_generation": enabled["generation"]},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "observation_automation_paused"
    assert (
        toggle(client, started["id"], False, enabled["generation"])["enabled"] is False
    )


def test_activation_guard_also_fences_waiting_status_write(journey, monkeypatch):
    client, service, _, _, result_id = journey
    started, _ = start(client, result_id)
    toggle(client, started["id"])
    reached, release = threading.Event(), threading.Event()
    guarded = [False]
    monkeypatch.setattr(automation, "is_release_activation_guarded", lambda: guarded[0])
    owner = automation.AutomationRunRepository
    original = owner.record_observation_automation_status

    def delayed(self, *args, **kwargs):
        reached.set()
        assert release.wait(5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(owner, "record_observation_automation_status", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            automation.run_research_observation_automation_once, service
        )
        try:
            assert reached.wait(5)
            guarded[0] = True
        finally:
            release.set()
        assert pending.result(timeout=5) == []
    with sqlite3.connect(service.db.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM automation_runs").fetchone()[0] == 0
    assert service.repository.get(started["id"])["version"] == 0


def test_activation_blocks_dispatch_and_shutdown_drains_thread_before_finishing(
    monkeypatch,
):
    entered_guard = asyncio.Event()
    release_guard = asyncio.Event()
    started, finish = threading.Event(), threading.Event()
    guarded = [True]
    stops = []

    async def guard_sleep(_):
        entered_guard.set()
        await release_guard.wait()

    def run_once(service, *, stop_requested):
        stops.append(stop_requested)
        started.set()
        assert finish.wait(5)
        return []

    monkeypatch.setattr(automation, "ResearchObservationService", lambda db: object())
    monkeypatch.setattr(
        automation, "run_research_observation_automation_once", run_once
    )
    monkeypatch.setattr(
        automation,
        "wait_for_release_activation",
        partial(
            wait_for_release_activation,
            activation_guarded=lambda: guarded[0],
            sleep=guard_sleep,
        ),
    )

    async def scenario():
        task = asyncio.create_task(
            automation.run_research_observation_automation_loop(db=object())
        )
        try:
            await asyncio.wait_for(entered_guard.wait(), timeout=2)
            assert not started.is_set()
            guarded[0] = False
            release_guard.set()
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(0.01)
            assert stops[0].is_set()
            assert not task.done()
        finally:
            finish.set()
            task.cancel() if not stops else None
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
