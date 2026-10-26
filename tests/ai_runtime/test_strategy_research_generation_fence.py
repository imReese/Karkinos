"""New SIM hypothesis sends retain authorization and immutable request bindings."""

import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from server.ai_runtime.provider_call_window import ProviderExecutionFenced
from server.contracts.strategy_research import (
    HYPOTHESIS_EXPORT_CONFIRMATION,
    HypothesisGenerationRequest,
    StrategyResearchRejected,
)
from server.services.market.market_universe_truth import (
    MarketUniversePolicy,
    market_deployment_scope,
)
from tests.ai_runtime.test_strategy_research_simulation_policy import (
    _bind,
    _invalidate_policy,
    _policy,
)
from tests.ai_runtime.test_strategy_research_workflow import (
    FixtureTransport,
    _hypothesis_response,
    _service,
)


@pytest.fixture
def generation_case(tmp_path):
    service, selection, _, _ = _service(tmp_path, bind_account=False)
    scope = market_deployment_scope(
        MarketUniversePolicy(minimum_master_member_count=1, allocation_slots=4)
    )
    selection = replace(
        selection,
        deployment_scope=scope,
        portfolio_policy_id=scope["portfolio_policy_id"],
    )
    policy = _policy(selection)
    selection = _bind(selection, policy)
    service._db.get_automation_policy_sync = lambda _: {
        "simulation_validation": deepcopy(policy)
    }
    response = _hypothesis_response(selection, include_account_evidence=False)
    payload = json.loads(response.payload["choices"][0]["message"]["content"])
    payload["drafts"][0]["portfolio_constraints"] = deepcopy(scope)
    response.payload["choices"][0]["message"]["content"] = json.dumps(payload)
    transport = FixtureTransport([response])
    service._transport = transport
    request = HypothesisGenerationRequest(
        idempotency_key="sim-generation-fence",
        requested_by="human:fixture-owner",
        account_alias="synthetic-research-only",
        research_question="Validate synthetic hypothesis authorization boundaries.",
        selection=selection,
        confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
    )
    return SimpleNamespace(
        service=service,
        selection=selection,
        policy=policy,
        transport=transport,
        request=request,
    )


def _session(case):
    with case.service._research_store._connect_readonly() as conn:
        rows = conn.execute("SELECT * FROM ai_strategy_research_sessions").fetchall()
    assert len(rows) == 1
    return dict(rows[0])


def _transport_events(case, row):
    return [
        event
        for event in case.service._ai_store.list_events(row["workflow_id"])
        if event["event_type"].startswith("provider.transport_")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["disabled", "expired", "invalid", "grant", "generation", "cash", "scope", "cost"],
)
async def test_new_generation_rejects_stale_SIM_before_contact(generation_case, change):
    case = generation_case
    _invalidate_policy(case, case.service, change)
    with pytest.raises(StrategyResearchRejected, match="simulation_"):
        await case.service.generate_hypotheses(case.request)
    row = _session(case)
    assert row["status"] == "blocked"
    assert case.service._research_store.list_drafts(row["session_id"]) == []
    assert case.transport.calls == []
    assert _transport_events(case, row) == []
    assert case.service._research_store.verify_events(row["session_id"])[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase", ["before_send", "in_flight", "before_save", "before_finish"]
)
async def test_generation_revocation_keeps_exposure_without_completion(
    generation_case, monkeypatch, phase
):
    case = generation_case

    def revoke():
        case.policy["generation"] = str(uuid4())

    if phase == "before_send":
        capture = case.service._capture_service.capture

        async def held_capture(request):
            result = await capture(request)
            revoke()
            return result

        monkeypatch.setattr(case.service._capture_service, "capture", held_capture)
    elif phase == "in_flight":
        post = case.transport.post_json

        def in_flight(**kwargs):
            result = post(**kwargs)
            revoke()
            return result

        monkeypatch.setattr(case.transport, "post_json", in_flight)
    elif phase == "before_save":
        from server.ai_runtime import strategy_research_generation as generation

        bind = generation.bind_and_validate_drafts

        def before_save(*args, **kwargs):
            result = bind(*args, **kwargs)
            revoke()
            return result

        monkeypatch.setattr(generation, "bind_and_validate_drafts", before_save)
    else:
        save = case.service._research_store.save_drafts

        def before_finish(*args, **kwargs):
            save(*args, **kwargs)
            revoke()

        monkeypatch.setattr(case.service._research_store, "save_drafts", before_finish)

    with pytest.raises(
        StrategyResearchRejected, match="simulation_authorization_changed"
    ):
        await case.service.generate_hypotheses(case.request)
    row = _session(case)
    assert row["status"] == "blocked"
    assert len(case.transport.calls) == (0 if phase == "before_send" else 1)
    drafts = case.service._research_store.list_drafts(row["session_id"])
    # A draft saved while authorized remains historical; the blocked session
    # cannot authorize a new native backtest after a later revocation.
    assert len(drafts) == (1 if phase == "before_finish" else 0)
    events = _transport_events(case, row)
    assert [e["event_type"] for e in events] == (
        []
        if phase == "before_send"
        else ["provider.transport_attempted", "provider.transport_outcome"]
    )
    if events:
        assert events[1]["payload"]["http_status"] == 200
        assert events[1]["payload"]["response_returned"] is True
        assert "fixture-api-key-must-not-persist" not in json.dumps(events)
        assert "headers" not in json.dumps(events)
    assert case.service._research_store.verify_events(row["session_id"])[0]
    assert case.service._ai_store.verify_replay(row["workflow_id"]).valid


@pytest.mark.asyncio
async def test_generation_claim_loser_does_not_block_winner(
    generation_case, monkeypatch
):
    case = generation_case
    claim = case.service._research_store.claim_session_run

    def lost_claim(*args, **kwargs):
        assert claim(*args, **kwargs)
        case.policy["generation"] = str(uuid4())
        return False

    monkeypatch.setattr(case.service._research_store, "claim_session_run", lost_claim)
    result = await case.service.generate_hypotheses(case.request)
    assert result["reused"] is True and result["status"] == "running"
    assert case.transport.calls == []
    assert _session(case)["status"] == "running"


@pytest.mark.asyncio
async def test_lost_worker_fence_does_not_finish_owned_SIM_session(
    generation_case, monkeypatch
):
    case = generation_case
    worker_current = True

    def require_worker():
        if not worker_current:
            raise ProviderExecutionFenced("fixture lease replaced")

    post = case.transport.post_json

    def lose_worker(**kwargs):
        nonlocal worker_current
        result = post(**kwargs)
        worker_current = False
        case.policy["generation"] = str(uuid4())
        return result

    case.service._execution_guard = require_worker
    monkeypatch.setattr(case.transport, "post_json", lose_worker)
    with pytest.raises(ProviderExecutionFenced, match="fixture lease replaced"):
        await case.service.generate_hypotheses(case.request)
    assert len(case.transport.calls) == 1
    row = _session(case)
    assert row["status"] == "running"
    assert case.service._research_store.list_drafts(row["session_id"]) == []
    assert _transport_events(case, row)[1]["payload"]["response_returned"] is True


@pytest.mark.asyncio
async def test_completed_generation_remains_readable_after_revocation(generation_case):
    case = generation_case
    first = await case.service.generate_hypotheses(case.request)
    assert first["status"] == "completed"
    assert first["drafts"][0]["validation"]["status"] == "valid"
    events = case.service._ai_store.list_events(first["workflow"]["workflow_id"])
    case.policy["generation"] = str(uuid4())
    replay = await case.service.generate_hypotheses(case.request)
    assert replay["reused"] is True and replay["status"] == "completed"
    assert replay["drafts"] == first["drafts"]
    assert len(case.transport.calls) == 1
    assert (
        case.service._ai_store.list_events(first["workflow"]["workflow_id"]) == events
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("refresh_policy", [False, True])
async def test_generation_freezes_caller_owned_nested_selection(
    generation_case, monkeypatch, refresh_policy
):
    case = generation_case
    original = deepcopy(case.selection.to_dict())
    capture = case.service._capture_service.capture

    async def mutate_caller(request):
        result = await capture(request)
        if refresh_policy:
            case.policy["generation"] = str(uuid4())
            case.selection.simulation_validation_binding["generation"] = case.policy[
                "generation"
            ]
        else:
            case.selection.deployment_scope["universe_policy"][
                "minimum_history_rows"
            ] += 1
        return result

    monkeypatch.setattr(case.service._capture_service, "capture", mutate_caller)
    if refresh_policy:
        with pytest.raises(
            StrategyResearchRejected, match="simulation_authorization_changed"
        ):
            await case.service.generate_hypotheses(case.request)
        assert case.transport.calls == []
    else:
        result = await case.service.generate_hypotheses(case.request)
        assert result["status"] == "completed"
        assert result["drafts"][0]["validation"]["status"] == "valid"
    row = _session(case)
    assert json.loads(row["request_json"])["selection"] == original


@pytest.mark.asyncio
async def test_non_SIM_generation_does_not_read_SIM_policy(tmp_path):
    service, selection, transport, _ = _service(tmp_path, bind_account=False)
    service._db.get_automation_policy_sync = lambda _: pytest.fail(
        "Non-SIM research must not require a SIM grant"
    )
    result = await service.generate_hypotheses(
        HypothesisGenerationRequest(
            idempotency_key="normalized-not-SIM",
            requested_by="human:fixture-owner",
            account_alias="synthetic-research-only",
            research_question="Preserve ordinary normalized research.",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        )
    )
    assert result["status"] == "completed"
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_future_prior_rejected_before_session_or_provider(generation_case):
    case = generation_case
    prior = {
        "artifact_fingerprint": "sha256:" + "2" * 64,
        "source_code_sha": "3" * 40,
        "observed_at": "2026-07-16T01:00:00+00:00",
        "universe": list(case.selection.universe),
        "start_date": case.selection.start_date,
        "end_date": case.selection.end_date,
        "frequency": case.selection.frequency,
        "cost_model_reference": case.selection.cost_model_reference,
        "observed_trial_count": 2,
        "provenance": {
            "generator": "fixture",
            "model_id": "fixture-model",
            "disposition": "existing synthetic cost stresses",
            "external_provider_api_called": False,
        },
    }
    request = replace(case.request, prior_diagnostic_exposures=(prior,))
    with pytest.raises(
        StrategyResearchRejected, match="prior_diagnostic_source_time_in_future"
    ):
        await case.service.generate_hypotheses(request)
    assert case.transport.calls == []
    with case.service._research_store._connect_readonly() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_strategy_research_sessions"
            ).fetchone()[0]
            == 0
        )
