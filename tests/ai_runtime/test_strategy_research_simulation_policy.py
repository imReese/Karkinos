"""SIM authorization survives the real local session/backtest/critique workflow."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from server.ai_runtime.provider_call_window import (
    DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
    ProviderSendAdmission,
)
from server.ai_runtime.strategy_research_backtest_workflow import (
    StrategyResearchBacktestWorkflowMixin,
)
from server.ai_runtime.strategy_research_provider import StrategyResearchModelProvider
from server.ai_runtime.strategy_research_session import StrategyResearchSessionMixin
from server.contracts.research_observation_automation import (
    SIMULATION_VALIDATION_AUTHORIZE,
)
from server.contracts.strategy_research import (
    BACKTEST_CONFIRMATION,
    CRITIQUE_EXPORT_CONFIRMATION,
    CritiqueRequest,
    FormulaBacktestRequest,
    StrategyResearchRejected,
)
from server.services.ai_shadow.ai_shadow_research_commands import (
    simulation_validation_defaults,
)
from tests.ai_runtime.test_strategy_research_workflow import (
    NOW,
    FixtureTransport,
    _critique_response,
    _local_admission_request,
    _service,
)
from tests.ai_runtime.test_strategy_sealed_backtest_inputs import _scoped_formula_inputs


def _policy(selection):
    value = simulation_validation_defaults(datetime.fromisoformat(NOW))
    value.update(
        enabled=True,
        authorization=SIMULATION_VALIDATION_AUTHORIZE,
        grant_id=str(uuid4()),
        generation=str(uuid4()),
        deployment_scope=deepcopy(selection.deployment_scope),
        deployment_scope_fingerprint=selection.deployment_scope[
            "deployment_scope_fingerprint"
        ],
        initial_cash=str(selection.initial_cash),
    )
    return value


def _bind(selection, policy):
    return replace(
        selection,
        simulation_validation_binding={
            key: policy[key] for key in ("grant_id", "generation", "initial_cash")
        },
    )


@pytest.fixture
def scoped(tmp_path, monkeypatch):
    adapter, selection, draft, snapshot, _ = _scoped_formula_inputs(
        tmp_path, monkeypatch
    )
    policy = _policy(selection)
    selection = _bind(selection, policy)
    return SimpleNamespace(
        adapter=adapter,
        selection=selection,
        draft=draft,
        snapshot=snapshot,
        policy=policy,
    )


def _resolver(scoped):
    service = StrategyResearchSessionMixin()
    reads = []

    def read(key):
        reads.append(key)
        return {"simulation_validation": deepcopy(scoped.policy)}

    service._db = SimpleNamespace(get_automation_policy_sync=read)
    service._now = lambda: NOW
    return service, reads


def test_policy_returns_frozen_main_mask_and_non_sim_never_reads_policy(scoped):
    service, reads = _resolver(scoped)
    actual = service._resolve_simulation_entry_board_policy(scoped.selection)
    assert actual == scoped.policy["entry_board_policy"]
    assert actual["allowed_boards"] == ["main"]
    actual["allowed_boards"].append("star")
    assert scoped.policy["entry_board_policy"]["allowed_boards"] == ["main"]
    assert reads == ["ai_shadow_research"]
    reads.clear()
    assert (
        service._resolve_simulation_entry_board_policy(
            replace(scoped.selection, simulation_validation_binding=None)
        )
        is None
    )
    assert reads == []


@pytest.mark.parametrize(
    "change",
    ["disabled", "expired", "invalid", "grant", "generation", "cash", "scope", "cost"],
)
@pytest.mark.asyncio
async def test_policy_rejects_stale_or_mismatched_authorization(scoped, change):
    service, _ = _resolver(scoped)
    _invalidate_policy(scoped, service, change)
    with pytest.raises(StrategyResearchRejected, match="simulation_"):
        service._resolve_simulation_entry_board_policy(scoped.selection)
    service._research_store = SimpleNamespace(
        get_session=lambda _: {
            "status": "completed",
            "request_json": json.dumps({"selection": scoped.selection.to_dict()}),
        },
        get_draft=lambda *_: {"validation_status": "valid", "contract": scoped.draft},
        create_or_get_backtest=lambda *_a, **_kw: pytest.fail(
            "Must not start a backtest"
        ),
    )
    service._validate_session_integrity = lambda _: None
    with pytest.raises(StrategyResearchRejected, match="simulation_"):
        await StrategyResearchBacktestWorkflowMixin.run_formula_backtest(
            service,
            FormulaBacktestRequest(
                "blocked", "human:test", "session", "draft", BACKTEST_CONFIRMATION
            ),
        )


def _invalidate_policy(scoped, service, change):
    if change == "disabled":
        scoped.policy["enabled"] = False
    elif change == "expired":
        service._now = lambda: scoped.policy["expires_at"]
    elif change == "invalid":
        scoped.policy["authorization"] = "unapproved"
    elif change in {"grant", "generation"}:
        scoped.policy[{"grant": "grant_id", "generation": "generation"}[change]] = str(
            uuid4()
        )
    elif change == "cash":
        scoped.policy["initial_cash"] = "1000000.00000000000000000001"
    elif change == "scope":
        scoped.policy["deployment_scope"]["universe_policy"][
            "minimum_history_rows"
        ] += 1
    elif change == "cost":
        scoped.policy["cost_model_reference"] = "unreviewed-cost"


async def _completed_backtest(tmp_path, monkeypatch, scoped):
    service, _, _, _ = _service(tmp_path, bind_account=False)
    service._now = lambda: NOW
    service._db.get_automation_policy_sync = lambda key: {
        "simulation_validation": deepcopy(scoped.policy)
    }
    selection = replace(scoped.selection, saved_backtest_result_id=17)
    seed = service._db.rows[17]
    seed["config_json"] = {
        "start_date": selection.start_date,
        "end_date": selection.end_date,
        "initial_cash": selection.initial_cash,
        "assets": [
            {"symbol": symbol, "asset_class": "stock"} for symbol in selection.universe
        ],
    }
    seed["metrics_json"] = {"dataset_snapshot": scoped.snapshot}
    service._capture_service._source.research_payload["test_window"] = deepcopy(
        seed["config_json"]
    )
    del service._capture_service._source.research_payload["test_window"]["initial_cash"]
    request = _local_admission_request(selection)
    request.artifact["drafts"][0].update(
        formula_ast=deepcopy(scoped.draft["formula_ast"]),
        parameter_values=deepcopy(scoped.draft["parameter_values"]),
        parameter_ranges=deepcopy(scoped.draft["parameter_ranges"]),
        portfolio_constraints=deepcopy(selection.deployment_scope),
    )
    session = await service.admit_local_hypotheses(request)
    assert session["binding_validity"] == "valid"
    assert session["drafts"][0]["validation"]["status"] == "valid"
    backtest_request = FormulaBacktestRequest(
        idempotency_key="sim-backtest",
        requested_by="human:test",
        session_id=session["session_id"],
        draft_id=session["drafts"][0]["draft_id"],
        confirmation=BACKTEST_CONFIRMATION,
    )
    result = await service.run_formula_backtest(backtest_request)
    assert result["status"] == "completed"
    result_id = result["canonical_backtest"]["result_id"]
    saved = service._db.rows[result_id]
    transport = FixtureTransport([_critique_response()])
    service._transport = transport
    critique_request = CritiqueRequest(
        idempotency_key="sim-critique",
        requested_by="human:test",
        session_id=session["session_id"],
        draft_id=session["drafts"][0]["draft_id"],
        backtest_run_id=result["backtest_run_id"],
        confirmation=CRITIQUE_EXPORT_CONFIRMATION,
    )
    return SimpleNamespace(
        service=service,
        selection=selection,
        session=session,
        saved=saved,
        transport=transport,
        backtest=result,
        backtest_request=backtest_request,
        critique_request=critique_request,
    )


@pytest.mark.asyncio
async def test_main_only_policy_reaches_native_adapter_and_saved_critique(
    tmp_path, monkeypatch, scoped
):
    case = await _completed_backtest(tmp_path, monkeypatch, scoped)
    metrics = json.loads(case.saved["metrics_json"])
    config = json.loads(case.saved["config_json"])
    assert metrics["entry_board_policy"] == scoped.policy["entry_board_policy"]
    assert config["params"]["entry_board_policy"] == metrics["entry_board_policy"]
    assert (
        metrics["simulation_validation_binding"]
        == case.selection.simulation_validation_binding
    )
    assert Decimal(str(case.saved["initial_cash"])) == Decimal("1000000")
    calls = []
    returned = []
    original_post = case.transport.post_json
    original_provider_post = StrategyResearchModelProvider._post_json

    def post(**kwargs):
        response = original_post(**kwargs)
        returned.append(response)
        return response

    def provider_post(provider, payload):
        response = original_provider_post(provider, payload)
        assert response is returned[-1]
        return response

    case.transport.post_json = post
    monkeypatch.setattr(StrategyResearchModelProvider, "_post_json", provider_post)

    class Fence:
        def require_current(self):
            calls.append("fence")

        def begin_provider_send(self, *, timeout_seconds):
            calls.append(("begin", timeout_seconds))
            return "fixture-send"

        def finish_provider_send(self, token):
            calls.append(("finish", token))

    case.service._execution_guard = lambda: calls.append("original_execution_guard")
    case.service._provider_send_admission = ProviderSendAdmission(
        policy=DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
        now=lambda: datetime.fromisoformat("2026-07-15T12:00:00+00:00"),
        execution_fence=Fence(),
    )
    result = await case.service.critique(case.critique_request)
    assert result["status"] == "completed"
    assert len(case.transport.calls) == 1
    row = case.service._research_store.get_critique(result["critique_id"])
    events = case.service._ai_store.list_events(row["workflow_id"])
    contact = [
        event
        for event in events
        if event["event_type"].startswith("provider.transport_")
    ]
    assert [event["event_type"] for event in contact] == [
        "provider.transport_attempted",
        "provider.transport_outcome",
    ]
    assert contact[1]["payload"]["http_status"] == 200
    assert ("begin", case.service._model_timeout_seconds) in calls
    assert ("finish", "fixture-send") in calls
    assert "original_execution_guard" in calls
    assert case.transport.calls[0]["url"] == case.service._settings.endpoint_url
    assert "headers" not in json.dumps(contact)
    assert "fixture-api-key-must-not-persist" not in json.dumps(events)
    assert case.service._ai_store.verify_replay(row["workflow_id"]).valid
    assert case.service._research_store.verify_events(row["critique_id"])[0]
    original_artifact = deepcopy(row["artifact"])
    scoped.policy["generation"] = str(uuid4())
    replay = await case.service.critique(case.critique_request)
    assert replay["reused"] is True and replay["status"] == "completed"
    assert replay["artifact"] == original_artifact
    assert len(case.transport.calls) == 1
    assert case.service._ai_store.list_events(row["workflow_id"]) == events


@pytest.mark.asyncio
async def test_lost_claim_does_not_rewrite_another_running_critique(
    tmp_path, monkeypatch, scoped
):
    case = await _completed_backtest(tmp_path, monkeypatch, scoped)
    claim = case.service._research_store.claim_critique

    def other_request_claimed(*args, **kwargs):
        assert claim(*args, **kwargs)
        scoped.policy["generation"] = str(uuid4())
        return False

    monkeypatch.setattr(
        case.service._research_store, "claim_critique", other_request_claimed
    )
    response = await case.service.critique(case.critique_request)
    assert response["reused"] is True and response["status"] == "running"
    assert case.transport.calls == []
    row = case.service._research_store.get_critique(response["critique_id"])
    assert row["status"] == "running" and row["artifact"] is None


@pytest.mark.asyncio
async def test_transport_exception_records_actual_attempt_without_http_success(
    tmp_path, monkeypatch, scoped
):
    case = await _completed_backtest(tmp_path, monkeypatch, scoped)

    def failed_post(**kwargs):
        case.transport.calls.append(kwargs)
        raise RuntimeError("fixture transport failure")

    case.transport.post_json = failed_post
    result = await case.service.critique(case.critique_request)
    assert result["status"] == "failed"
    assert len(case.transport.calls) == 1
    row = case.service._research_store.get_critique(result["critique_id"])
    events = case.service._ai_store.list_events(row["workflow_id"])
    outcome = next(
        event["payload"]
        for event in events
        if event["event_type"] == "provider.transport_outcome"
    )
    assert outcome["response_returned"] is False
    assert outcome["exception_class"] == "RuntimeError"
    assert "http_status" not in outcome and "response_fingerprint" not in outcome
    assert case.service._ai_store.verify_replay(row["workflow_id"]).valid
    assert case.service._research_store.verify_events(row["critique_id"])[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["disabled", "expired", "invalid", "grant", "generation", "cash", "scope", "cost"],
)
async def test_new_critique_rejects_bad_policy_without_contact_or_pending(
    tmp_path, monkeypatch, scoped, change
):
    case = await _completed_backtest(tmp_path, monkeypatch, scoped)
    _invalidate_policy(scoped, case.service, change)
    with pytest.raises(StrategyResearchRejected, match="simulation_"):
        await case.service.critique(case.critique_request)
    assert case.transport.calls == []
    with case.service._research_store._connect_readonly() as conn:
        row = dict(
            conn.execute("SELECT * FROM ai_strategy_backtest_critiques").fetchone()
        )
    assert row["status"] == "blocked"
    assert row["normalized_artifact_json"] is None
    assert case.service._research_store.verify_events(row["critique_id"])[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "where",
    [
        "metrics",
        "config",
        "sim_binding",
        "source_selection",
        "cash",
        "cost",
        "portfolio",
        "scope",
        "board_drift",
    ],
)
async def test_critique_rejects_missing_or_drifted_saved_policy_before_send(
    tmp_path, monkeypatch, scoped, where
):
    case = await _completed_backtest(tmp_path, monkeypatch, scoped)
    metrics = json.loads(case.saved["metrics_json"])
    config = json.loads(case.saved["config_json"])
    if where == "metrics":
        del metrics["entry_board_policy"]
    elif where == "config":
        del config["params"]["entry_board_policy"]
    elif where == "sim_binding":
        metrics["simulation_validation_binding"]["generation"] = str(uuid4())
    elif where == "source_selection":
        del metrics["source_selection"]
    elif where == "cash":
        config["initial_cash"] = "1000000.00000000000000000001"
    elif where == "cost":
        del metrics["cost_assumptions"]["commission_model_reference"]
    elif where == "portfolio":
        config["params"]["portfolio_policy_id"] = "foreign-policy"
    elif where == "scope":
        del metrics["deployment_scope"]
    elif where == "board_drift":
        config["params"]["entry_board_policy"]["allowed_boards"] = ["main", "star"]
    case.saved["metrics_json"] = json.dumps(metrics)
    case.saved["config_json"] = json.dumps(config)
    with pytest.raises(
        StrategyResearchRejected, match="simulation_backtest_policy_binding_drift"
    ):
        await case.service.critique(case.critique_request)
    assert case.transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before_send", "in_flight", "before_finish"])
async def test_revocation_blocks_new_actions_retains_exposure_and_history(
    tmp_path, monkeypatch, scoped, phase
):
    case = await _completed_backtest(tmp_path, monkeypatch, scoped)
    original_post = case.transport.post_json
    original_validate = case.service._resolve_reviewed_fee_schedule
    original_report = __import__(
        "server.ai_runtime.strategy_research_critique", fromlist=["report_artifact"]
    ).report_artifact

    def revoke():
        scoped.policy["generation"] = str(uuid4())

    def post(**kwargs):
        response = original_post(**kwargs)
        if phase == "in_flight":
            revoke()
        return response

    def validate(*args, **kwargs):
        value = original_validate(*args, **kwargs)
        if phase == "before_send":
            revoke()
        return value

    def report(*args, **kwargs):
        value = original_report(*args, **kwargs)
        if phase == "before_finish":
            revoke()
        return value

    case.transport.post_json = post
    monkeypatch.setattr(case.service, "_resolve_reviewed_fee_schedule", validate)
    monkeypatch.setattr(
        "server.ai_runtime.strategy_research_critique.report_artifact", report
    )
    with pytest.raises(
        StrategyResearchRejected, match="simulation_authorization_changed"
    ):
        await case.service.critique(case.critique_request)
    assert len(case.transport.calls) == (0 if phase == "before_send" else 1)
    with case.service._research_store._connect_readonly() as conn:
        row = dict(
            conn.execute("SELECT * FROM ai_strategy_backtest_critiques").fetchone()
        )
    assert row["status"] == "blocked"
    assert row["normalized_artifact_json"] is None
    assert case.service._research_store.verify_events(row["critique_id"])[0]
    if phase != "before_send":
        events = case.service._ai_store.list_events(row["workflow_id"])
        assert (
            len(
                [
                    event
                    for event in events
                    if event["event_type"] == "provider.transport_outcome"
                ]
            )
            == 1
        )
        assert case.service._ai_store.verify_replay(row["workflow_id"]).valid
    with pytest.raises(
        StrategyResearchRejected, match="simulation_authorization_changed"
    ):
        await case.service.run_formula_backtest(case.backtest_request)
    # Expired/revoked permissions never erase a readable historical session.
    history = case.service.get_session(case.session["session_id"])
    assert history["binding_validity"] == "valid"
    assert history["status"] == "completed"
