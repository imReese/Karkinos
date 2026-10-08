"""Independent, revocable data opt-in using the existing policy and job owners."""

from datetime import timedelta
from uuid import uuid4

import pytest

from server.persistence.automation_runs import (
    AutomationRunRepository,
    require_observation_automation_policy,
)
from server.persistence.jobs import SQLiteJobStore
from tests.server.test_research_observations_journey import journey, start  # noqa: F401

pytestmark = pytest.mark.product_smoke


def configure(client, identity, **fields):
    return client.put(
        f"/api/research-observations/{identity}/automation",
        json={"enabled": False, **fields},
    )


def test_data_preparation_requires_its_own_opt_in_and_old_commands_preserve_it(journey):
    client, service, _, _, result_id = journey
    observation, _ = start(client, result_id)
    identity = observation["id"]
    path = f"/api/research-observations/{identity}"
    disabled = client.get(path).json()["automation"]
    assert disabled["dataset_preparation_enabled"] is False
    assert disabled["dataset_preparation"]["status"] == "disabled"
    assert (
        configure(client, identity, dataset_preparation_enabled="true").status_code
        == 422
    )
    enabled = configure(client, identity, dataset_preparation_enabled=True).json()
    assert enabled["dataset_preparation"]["enabled"] is True
    assert enabled["dataset_preparation"]["account_authority"] is False
    assert enabled["enabled"] is False
    assert enabled["paper_settlement_enabled"] is False
    assert (
        configure(client, identity, dataset_preparation_enabled=False).status_code
        == 409
    )
    # A client unaware of the new independent permission cannot accidentally
    # disable it when changing only target publication.
    updated = configure(
        client, identity, enabled=True, expected_generation=enabled["generation"]
    ).json()
    assert updated["dataset_preparation"]["enabled"] is True
    assert updated["generation"] != enabled["generation"]
    assert service.repository.get(identity)["version"] == 0


def test_revocation_fences_queue_completion_and_catalog_publication(journey):
    client, service, _, _, result_id = journey
    observation, _ = start(client, result_id)
    identity = observation["id"]
    enabled = configure(client, identity, dataset_preparation_enabled=True).json()
    generation = enabled["generation"]
    store = SQLiteJobStore(service.db.path)

    def guard(conn):
        require_observation_automation_policy(
            conn, identity, generation, dataset_preparation=True
        )

    now = service.clock()
    payload = {
        "trade_date": "2026-09-18",
        "observation_automation": {
            "observation_id": identity,
            "generation": generation,
        },
    }
    queued = store.enqueue_many(
        "market_daily_verified", (payload,), now=now, guard=guard
    )[0]
    claimed = store.claim("market_daily_verified", "fixture", now=now)
    assert claimed is not None
    revoked = configure(
        client,
        identity,
        dataset_preparation_enabled=False,
        expected_generation=generation,
    )
    assert revoked.status_code == 200
    with pytest.raises(ValueError, match="observation_automation_policy_conflict"):
        store.finish(claimed.lease, now=now, result_ref="fixture", guard=guard)
    assert store.get(queued.job_id).status == "running"
    with pytest.raises(ValueError, match="observation_automation_policy_conflict"):
        store.enqueue_many(
            "market_daily_verified",
            ({**payload, "trade_date": "2026-09-21"},),
            now=now,
            guard=guard,
        )
    assert (
        len(
            store.list_verified_observation_jobs(
                identity, start_date="2026-09-01", end_date="2026-09-30"
            )
        )
        == 1
    )
    with pytest.raises(ValueError, match="observation_automation_policy_conflict"):
        AutomationRunRepository(service.db.path).publish_observation_dataset(
            observation_id=identity,
            generation=generation,
            stop_requested=lambda: False,
            publish=lambda: pytest.fail(
                "Revoked permission must not publish a Dataset"
            ),
        )


def test_paused_observation_can_revoke_data_permission_without_reenabling_targets(
    journey,
):
    client, service, _, _, result_id = journey
    observation, _ = start(client, result_id)
    identity = observation["id"]
    enabled = configure(
        client, identity, enabled=True, dataset_preparation_enabled=True
    ).json()
    assert (
        client.post(
            f"/api/research-observations/{identity}/pause",
            json={"request_id": str(uuid4()), "expected_version": 0},
        ).status_code
        == 200
    )
    revoked = configure(
        client,
        identity,
        enabled=True,
        dataset_preparation_enabled=False,
        expected_generation=enabled["generation"],
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "paused"
    assert service.repository.get(identity)["lifecycle"] == "paused"
    disabled = configure(
        client,
        identity,
        enabled=False,
        expected_generation=revoked.json()["generation"],
    ).json()
    assert (
        configure(
            client,
            identity,
            enabled=True,
            expected_generation=disabled["generation"],
        ).status_code
        == 422
    )


def test_observation_job_discovery_keeps_older_days_and_other_books_separate(journey):
    _, service, _, _, _ = journey
    store = SQLiteJobStore(service.db.path)
    now = service.clock()
    rows = tuple(
        {
            "trade_date": "2026-09-18",
            "round": i,
            "observation_automation": {"observation_id": "first", "generation": str(i)},
        }
        for i in range(105)
    )
    store.enqueue_many("market_daily_verified", rows, now=now)
    store.enqueue(
        "market_daily_verified",
        {
            "trade_date": "2026-09-18",
            "observation_automation": {
                "observation_id": "other",
                "generation": "other",
            },
        },
        now=now + timedelta(seconds=1),
    )
    assert (
        len(
            store.list_verified_observation_jobs(
                "first", start_date="2026-09-18", end_date="2026-09-18"
            )
        )
        == 105
    )
    assert (
        store.list_verified_observation_jobs(
            "first", start_date="2026-09-19", end_date="2026-09-30"
        )
        == ()
    )
