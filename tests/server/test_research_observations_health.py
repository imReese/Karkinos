"""Configured price monitoring through the real HTTP, Dataset and storage path."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from analytics.forward_observation_health import evaluate_forward_observation_health
from server.routes import research_observations as routes
from server.services.research_observations import ResearchObservationService
from tests.server.test_research_observation_inputs import DAYS, calendar, dataset
from tests.server.test_research_observations_journey import journey  # noqa: F401

pytestmark = pytest.mark.product_smoke


def policy(mode="pause_on_breach"):
    # Deliberately small synthetic rule; not a product default or recommendation.
    return {
        "mode": mode,
        "window_intervals": 2,
        "minimum_eligible_intervals": 1,
        "minimum_mean_relative_price_response": "-0.05",
    }


def request_start(client, result_id, settings):
    body = {
        "request_id": str(uuid4()),
        "source_backtest_result_id": result_id,
        "horizon_sessions": 1,
        "health_policy": settings,
    }
    response = client.post("/api/research-observations", json=body)
    assert response.status_code == 200, response.text
    return response.json(), body


def advance(client, path, version, dataset_id):
    body = {
        "request_id": str(uuid4()),
        "expected_version": version,
        "dataset_id": dataset_id,
    }
    response = client.post(path + "/advance", json=body)
    assert response.status_code == 200, response.text
    return response.json(), body


@pytest.mark.parametrize("mode", ["observe_only", "pause_on_breach"])
def test_price_rule_is_bound_durable_and_scoped_to_one_observation(
    journey, tmp_path, monkeypatch, mode
):
    client, service, current, _, result_id = journey
    closes = dict(zip(DAYS, ("12", "11", "10", "9", "12", "10", "11", "11")))
    _, today = dataset(tmp_path / "research", closes=closes)
    started, start_body = request_start(client, result_id, policy(mode))
    unrelated, _ = request_start(client, result_id, None)
    path = f"/api/research-observations/{started['id']}"
    first, _ = advance(client, path, 0, today.dataset_id)
    assert first["publication_id"]
    assert first["health_decision"]["status"] == "waiting"
    initial = client.get(path).json()
    assert initial["policy"]["health_policy"]["mode"] == mode
    assert initial["health_decision"]["input_version"] == 0

    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    missing, missing_body = advance(client, path, 1, "sha256:" + "0" * 64)
    assert missing["lifecycle"] == "active"
    assert missing["health_decision"]["status"] == "unavailable"
    assert missing["health_decision"]["action"] == "none"
    assert missing["health_decision"]["data_available"] is False
    assert client.get(path).json()["outcomes"] == []

    _, future = dataset(
        tmp_path / "research", days=DAYS[:7], closes=closes, cutoff=current[0]
    )
    measured, measured_body = advance(client, path, 2, future.dataset_id)
    health = measured["health_decision"]
    assert health["status"] == "threshold_breached", health
    assert health["counts"]["eligible"] == 1
    assert Decimal(health["mean_relative_price_response"]) == Decimal("-0.075")
    assert health["is_nav_return"] is False
    assert health["corporate_action_coverage_complete"] is False
    assert health["observation_id"] == started["id"]
    assert health["input_version"] == 2
    assert health["decision_actor"] == "configured_rule"
    expected_lifecycle = "paused" if mode == "pause_on_breach" else "active"
    assert measured["lifecycle"] == expected_lifecycle
    if mode == "pause_on_breach":
        assert measured["publication_id"] is None
        assert measured["last_blocker"]["code"] == "observation_health_rule_paused"
        assert health["action"] == "pause_observation"
    else:
        assert health["action"] == "none"

    reopened = ResearchObservationService(service.db, clock=lambda: current[0])
    monkeypatch.setattr(routes, "_service", lambda: reopened)
    detail = client.get(path).json()
    assert detail["lifecycle"] == expected_lifecycle
    assert detail["health_decision"] == health
    assert len(detail["outcomes"]) == 1
    assert client.post(path + "/advance", json=measured_body).json() == measured
    assert client.post(path + "/advance", json=missing_body).json() == missing
    assert client.post("/api/research-observations", json=start_body).json() == started
    assert client.get(path).json() == detail
    other = client.get(f"/api/research-observations/{unrelated['id']}").json()
    assert other["lifecycle"] == "active"
    assert other["version"] == 0
    assert other["health_decision"] is None
    replayed_health = evaluate_forward_observation_health(
        publications=detail["publications"],
        outcomes=detail["outcomes"],
        policy=detail["policy"]["health_policy"],
        evaluated_at=current[0],
        market_as_of=DAYS[6],
    )
    assert replayed_health["input_fingerprint"] == health["input_fingerprint"]
    assert (
        replayed_health["mean_relative_price_response"]
        == health["mean_relative_price_response"]
    )


def test_invalid_health_rule_rejected_before_persistence(journey):
    client, _, _, _, result_id = journey
    for settings in (
        {},
        {**policy(), "window_intervals": 0},
        {**policy(), "minimum_eligible_intervals": 3},
        {**policy(), "window_intervals": True},
        {**policy(), "minimum_mean_relative_price_response": "NaN"},
        {**policy(), "mode": "close_actual_positions"},
        {**policy(), "human_approval_id": "fabricated"},
    ):
        response = client.post(
            "/api/research-observations",
            json={
                "request_id": str(uuid4()),
                "source_backtest_result_id": result_id,
                "health_policy": settings,
            },
        )
        assert response.status_code == 422, response.text
    assert client.get("/api/research-observations").json() == []


def test_rule_is_not_retrofitted_by_retry_and_zero_exposure_never_breaches(
    journey, tmp_path
):
    client, _, current, today, result_id = journey
    started, body = request_start(client, result_id, policy())
    path = f"/api/research-observations/{started['id']}"
    changed = {**body, "health_policy": {**policy(), "mode": "observe_only"}}
    assert client.post("/api/research-observations", json=changed).status_code == 409
    advance(client, path, 0, today.dataset_id)
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    _, future = dataset(tmp_path / "research", days=DAYS[:7], cutoff=current[0])
    receipt, _ = advance(client, path, 1, future.dataset_id)
    assert receipt["lifecycle"] == "active"
    health = receipt["health_decision"]
    assert health["counts"]["zero_exposure"] == 1
    assert health["status"] == "insufficient_evidence"
    assert health["action"] == "none"
    assert health["mean_relative_price_response"] is None


def test_changed_code_records_unavailable_without_evaluating_performance(
    journey, monkeypatch
):
    client, _, _, today, result_id = journey
    started, _ = request_start(client, result_id, policy())
    path = f"/api/research-observations/{started['id']}"
    monkeypatch.setattr(
        "server.services.research_observations.observation_code_binding",
        lambda: {"changed": True},
    )
    receipt, _ = advance(client, path, 0, today.dataset_id)
    assert receipt["last_blocker"]["code"] == "observation_code_changed"
    assert receipt["lifecycle"] == "active"
    assert receipt["publication_id"] is None
    assert receipt["health_decision"]["status"] == "unavailable"
    assert receipt["health_decision"]["action"] == "none"
    assert receipt["health_decision"]["market_as_of"] is None


def test_replay_restores_calculation_inputs_when_commit_clock_advances(
    journey, tmp_path, monkeypatch
):
    client, service, current, _, result_id = journey
    # An extra known session lets the same command also publish the next target.
    service.db.upsert_market_calendar_snapshot_sync(
        calendar(trading_days=(*DAYS, date(2026, 9, 24)))
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
    closes = dict(zip(DAYS, ("12", "11", "10", "9", "12", "10", "11", "11")))
    _, today = dataset(tmp_path / "research", closes=closes)
    started, _ = request_start(client, result_id, policy("observe_only"))
    path = f"/api/research-observations/{started['id']}"
    first, _ = advance(client, path, 0, today.dataset_id)
    before = client.get(path).json()
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    _, future = dataset(
        tmp_path / "research", days=DAYS[:7], closes=closes, cutoff=current[0]
    )

    def advancing_clock():
        value = current[0]
        current[0] += timedelta(microseconds=1)
        return value

    reopened = ResearchObservationService(service.db, clock=advancing_clock)
    monkeypatch.setattr(routes, "_service", lambda: reopened)
    receipt, body = advance(client, path, first["version"], future.dataset_id)
    health = receipt["health_decision"]
    after = client.get(path).json()
    assert receipt["publication_id"] is not None, receipt
    assert len(after["publications"]) == 2
    assert health["status"] == "threshold_breached"
    assert health["action"] == "none"
    assert health["input_version"] == first["version"]
    assert datetime.fromisoformat(after["outcomes"][0]["measured_at"]) > (
        datetime.fromisoformat(health["evaluated_at"])
    )
    # Reconstruct from this operation's outcome keys and the previous version.
    # Only the newly computed outcomes lacked the storage-owned commit time.
    keys = {
        (item["publication_id"], item["horizon"]) for item in receipt["outcome_keys"]
    }
    computed = [
        {key: value for key, value in outcome.items() if key != "measured_at"}
        for outcome in after["outcomes"]
        if (outcome["publication_id"], outcome["horizon"]) in keys
    ]
    replayed = evaluate_forward_observation_health(
        publications=before["publications"],
        outcomes=[*before["outcomes"], *computed],
        policy=before["policy"]["health_policy"],
        evaluated_at=datetime.fromisoformat(health["evaluated_at"]),
        market_as_of=date.fromisoformat(health["market_as_of"]),
    )
    assert replayed == {key: health[key] for key in replayed}
    assert client.post(path + "/advance", json=body).json() == receipt
    assert client.get(path).json() == after
