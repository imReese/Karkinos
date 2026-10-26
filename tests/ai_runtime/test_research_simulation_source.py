"""Exact saved research lineage is readable without granting trading authority."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from analytics.research_evidence import build_research_evidence_bundle
from server.ai_runtime.contracts import (
    ArtifactKind,
    WorkflowStatus,
    canonical_json,
    content_fingerprint,
)
from server.ai_runtime.formula_dsl import FormulaBinding
from server.ai_runtime.strategy_research_model_contract import (
    bind_and_validate_drafts,
    normalize_critique_payload,
)
from server.ai_runtime.strategy_research_privacy import (
    build_normalized_research_pack,
    build_normalized_robustness_evidence,
)
from server.ai_runtime.strategy_research_session import StrategyResearchSessionMixin
from server.ai_runtime.strategy_research_support import selection_from_session
from server.config_types import ResearchSimulationSourceConfig
from server.contracts.strategy_research import StrategyResearchRejected
from tests.ai_runtime.test_karkinos_capture_source import (
    native_exploratory_report as native_exploratory_report,
)


@pytest.fixture
def lineage(native_exploratory_report, monkeypatch):
    saved = deepcopy(native_exploratory_report)
    metrics = saved["metrics_json"]
    # Capture permits parameter-free historical reports; generated drafts require
    # a valid local perturbation panel around the same existing lag-period nodes.
    binding = FormulaBinding(
        **{
            **metrics["formula_binding"],
            "parameter_values": {"period": 1},
            "parameter_ranges": {"period": [1, 2, 3]},
        }
    )
    metrics["formula_binding"] = binding.to_dict()
    metrics["formula_fingerprint"] = binding.fingerprint
    saved["config_json"]["params"]["formula_fingerprint"] = binding.fingerprint
    metrics["research_evidence_bundle"] = build_research_evidence_bundle(
        metrics_json=metrics,
        cost_summary_json=saved["cost_summary_json"],
        evidence_json=metrics["evidence_bundle"],
        strategy_metadata=metrics["strategy_metadata"],
    )
    selection = selection_from_session(
        {"request_json": canonical_json({"selection": metrics["source_selection"]})}
    )
    session = {
        "session_id": "fixture-session",
        "workflow_id": "fixture-hypothesis-workflow",
        "context_snapshot_id": "fixture-context",
        "context_fingerprint": "b" * 64,
        "status": "completed",
        "selection_fingerprint": selection.fingerprint,
        "request_json": canonical_json({"selection": selection.to_dict()}),
        "evidence_reference_id": "fixture-research-evidence",
    }
    candidate = {
        "economic_hypothesis": "Completed-bar momentum research.",
        "selected_universe": list(selection.universe),
        "dataset_snapshot_id": selection.dataset_snapshot_id,
        "test_window": {
            "start_date": selection.start_date,
            "end_date": selection.end_date,
        },
        "frequency": selection.frequency,
        "formula_ast": binding.formula_ast,
        "parameter_values": binding.parameter_values,
        "parameter_ranges": binding.parameter_ranges,
        "entry_conditions": "Completed close rises.",
        "exit_conditions": "Completed close falls.",
        "position_sizing_hypothesis": "Frozen equal-weight research allocation.",
        "portfolio_constraints": deepcopy(selection.deployment_scope),
        "cost_model_reference": selection.cost_model_reference,
        "required_evidence": ["Complete saved backtest facts."],
        "anti_lookahead_assumptions": list(binding.anti_lookahead_assumptions),
        "proposed_deterministic_tests": ["Replay frozen research inputs."],
        "sample_split_plan": "Rolling OOS and separate forward observation.",
        "failure_conditions": ["After-cost loss."],
        "limitations": ["Historical PIT remains unverified."],
        "risk_impact": "Research may lose value.",
        "citations": ["saved_backtest_evidence.performance_summary"],
    }
    draft = bind_and_validate_drafts(
        {"drafts": [candidate]},
        session_id=session["session_id"],
        workflow_id=session["workflow_id"],
        context_snapshot_id="fixture-context",
        context_fingerprint="b" * 64,
        evidence_reference_id=session["evidence_reference_id"],
        selection=selection,
        research_question="Inspect this saved research lineage only.",
        iteration_context=None,
        provider_id="fixture-local",
        model_id="fixture-model",
    )[0]
    assert draft["validation"]["status"] == "valid", draft["validation"]
    assert draft["formula_fingerprint"] == binding.fingerprint
    source = ResearchSimulationSourceConfig(
        session_id=session["session_id"],
        draft_id=draft["draft_id"],
        backtest_run_id="fixture-backtest-run",
        critique_id="fixture-critique",
        canonical_backtest_result_id=saved["id"],
    )
    draft_row = {
        "session_id": source.session_id,
        "draft_id": source.draft_id,
        "validation_status": "valid",
        "artifact_fingerprint": content_fingerprint(draft),
        "formula_fingerprint": binding.fingerprint,
        "contract": draft,
    }
    backtest = {
        "backtest_run_id": source.backtest_run_id,
        "session_id": source.session_id,
        "draft_id": source.draft_id,
        "status": "completed",
        "canonical_backtest_result_id": saved["id"],
        "formula_fingerprint": binding.fingerprint,
        "dataset_snapshot_id": selection.dataset_snapshot_id,
        "cost_model_reference": selection.cost_model_reference,
        "evidence_fingerprint": content_fingerprint(
            metrics["research_evidence_bundle"]
        ),
    }
    pack = build_normalized_research_pack(
        simulation_notional=selection.simulation_validation_binding is not None,
        performance=saved,
        after_cost_evidence=metrics["evidence_bundle"],
        cost_summary=saved["cost_summary_json"],
        research_evidence_bundle=metrics["research_evidence_bundle"],
        oos_validation=metrics["oos_validation"],
    )
    expected_echo = {
        "canonical_backtest_result_id": saved["id"],
        "formula_fingerprint": binding.fingerprint,
        "dataset_snapshot_id": selection.dataset_snapshot_id,
        "cost_model_reference": selection.cost_model_reference,
        "notional_policy_id": pack["notional_policy_id"],
        **pack["performance_summary"],
        **pack["cost_summary"],
        "oos_validation_fingerprint": content_fingerprint(metrics["oos_validation"]),
        "research_evidence_fingerprint": content_fingerprint(
            metrics["research_evidence_bundle"]
        ),
        "robustness_evidence_fingerprint": content_fingerprint(
            build_normalized_robustness_evidence(metrics)
        ),
    }
    citation_catalog = {"cite_return": "critique_input.canonical_backtest.total_return"}
    artifact = normalize_critique_payload(
        {
            "canonical_binding_echo": expected_echo,
            "citations": list(citation_catalog),
            "uncertainty": "Historical PIT and forward performance remain unverified.",
        },
        session["evidence_reference_id"],
        {"required_binding_echo": expected_echo, "canonical_backtest": expected_echo},
        citation_catalog=citation_catalog,
    )
    critique = {
        "critique_id": source.critique_id,
        "session_id": source.session_id,
        "draft_id": source.draft_id,
        "backtest_run_id": source.backtest_run_id,
        "status": "completed",
        "workflow_id": "fixture-critique-workflow",
        "artifact": artifact,
        "artifact_fingerprint": content_fingerprint(artifact),
    }
    rows = {
        "session": {source.session_id: session},
        "draft": {(source.session_id, source.draft_id): draft_row},
        "backtest": {source.backtest_run_id: backtest},
        "saved": {saved["id"]: saved},
        "critique": {source.critique_id: critique},
        "events": {
            source.backtest_run_id: (True, []),
            source.critique_id: (True, []),
        },
        "replay": {critique["workflow_id"]: SimpleNamespace(valid=True)},
        "workflow": {
            critique["workflow_id"]: SimpleNamespace(
                workflow_id=critique["workflow_id"],
                status=WorkflowStatus.COMPLETED,
                partial_result=False,
                context_snapshot_id=session["context_snapshot_id"],
                context_fingerprint=session["context_fingerprint"],
            )
        },
        "report": {
            critique["workflow_id"]: [
                SimpleNamespace(kind=ArtifactKind.REPORT, content=deepcopy(artifact))
            ]
        },
    }
    calls = []

    def read(kind, key):
        calls.append((kind, key))
        return deepcopy(rows[kind][key])

    service = StrategyResearchSessionMixin()
    service._research_store = SimpleNamespace(
        get_session=lambda key: read("session", key),
        get_draft=lambda session_id, draft_id: read("draft", (session_id, draft_id)),
        get_backtest=lambda key: read("backtest", key),
        research_backtest_result=lambda key: read("saved", key),
        get_critique=lambda key: read("critique", key),
        verify_events=lambda key: read("events", key),
    )
    service._ai_store = SimpleNamespace(
        get_workflow=lambda key: read("workflow", key),
        verify_replay=lambda key: read("replay", key),
        list_artifacts=lambda key: read("report", key),
    )
    integrity_calls = []
    monkeypatch.setattr(service, "_validate_session_integrity", integrity_calls.append)
    for name in (
        "load_immutable_dataset_inputs",
        "verify_backtest_dataset_snapshot_replay",
    ):
        monkeypatch.setattr(
            "analytics.dataset_snapshot." + name,
            lambda *args, **kwargs: pytest.fail("Read aggregation must not replay CAS"),
        )
    return SimpleNamespace(
        service=service,
        source=source,
        selection=selection,
        session=session,
        draft_row=draft_row,
        backtest=backtest,
        saved=saved,
        critique=critique,
        rows=rows,
        calls=calls,
        integrity_calls=integrity_calls,
    )


def _assert_research_only(result):
    assert result["read_only"] is True
    assert result["research_only"] is True
    assert result["requires_human_review"] is True
    assert result["authority_effect"] == "none"
    for key in (
        "executable",
        "authorizes_order_creation",
        "authorizes_account_publication",
        "authorizes_execution",
    ):
        assert result[key] is False
    assert not {"order_intents", "approval", "human_approval"}.intersection(result)


def _assert_blocked(result, blocker=None):
    _assert_research_only(result)
    assert result["status"] == "blocked"
    assert result["blockers"]
    if blocker is not None:
        assert result["blockers"] == [blocker]
    assert not {"draft", "critique", "formula_ast", "source_fingerprint"}.intersection(
        result
    )


def test_unselected_source_performs_no_reads(lineage):
    result = lineage.service.resolve_research_simulation_source(None)
    assert result["status"] == "unavailable"
    assert result["blockers"] == ["research_simulation_source_not_configured"]
    assert lineage.calls == lineage.integrity_calls == []
    _assert_research_only(result)


@pytest.mark.parametrize("serialized", [False, True])
def test_exact_saved_research_is_ready_without_formal_admission_or_writes(
    lineage, serialized
):
    if serialized:
        for field in ("config_json", "metrics_json", "cost_summary_json"):
            lineage.saved[field] = canonical_json(lineage.saved[field])
    before = deepcopy(lineage.rows)
    result = lineage.service.resolve_research_simulation_source(lineage.source)

    assert result["status"] == "ready", result["blockers"]
    assert result["blockers"] == []
    assert result["canonical_backtest_result_id"] == 201
    assert result["selection"]["saved_backtest_result_id"] == 183
    assert result["research_evidence_bundle"]["promotion_gate"]["status"] == "blocked"
    assert (
        result["dataset_simulation_admission"]["account_publication_admitted"] is False
    )
    assert result["current_CAS_replayed"] is False
    metrics = lineage.rows["saved"][lineage.source.canonical_backtest_result_id][
        "metrics_json"
    ]
    if isinstance(metrics, str):
        import json

        metrics = json.loads(metrics)
    assert result["dataset_snapshot"] == metrics["dataset_snapshot"]
    assert lineage.integrity_calls == [lineage.session]
    assert lineage.rows == before
    assert lineage.calls == [
        ("session", lineage.source.session_id),
        ("draft", (lineage.source.session_id, lineage.source.draft_id)),
        ("backtest", lineage.source.backtest_run_id),
        ("saved", 201),
        ("critique", lineage.source.critique_id),
        ("workflow", lineage.critique["workflow_id"]),
        ("replay", lineage.critique["workflow_id"]),
        ("report", lineage.critique["workflow_id"]),
        ("events", lineage.source.backtest_run_id),
        ("events", lineage.source.critique_id),
    ]
    fingerprint = result.pop("source_fingerprint")
    assert fingerprint == "sha256:" + content_fingerprint(result)
    _assert_research_only(result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", "missing-exact-session"),
        ("draft_id", "missing-exact-draft"),
        ("backtest_run_id", "missing-exact-run"),
        ("critique_id", "missing-exact-critique"),
        ("canonical_backtest_result_id", 202),
    ],
)
def test_every_explicit_reference_fails_closed_without_latest_fallback(
    lineage, field, value
):
    source = replace(lineage.source, **{field: value})
    _assert_blocked(lineage.service.resolve_research_simulation_source(source))


@pytest.mark.parametrize(
    "target,field,value,blocker",
    [
        ("session", "status", "running", "research_simulation_session_incomplete"),
        (
            "session",
            "session_id",
            "other-session",
            "research_simulation_session_incomplete",
        ),
        (
            "session",
            "selection_fingerprint",
            "drift",
            "research_simulation_selection_drift",
        ),
        (
            "draft_row",
            "validation_status",
            "blocked",
            "research_simulation_draft_drift",
        ),
        ("draft_row", "session_id", "other-session", "research_simulation_draft_drift"),
        ("draft_row", "draft_id", "other-draft", "research_simulation_draft_drift"),
        (
            "draft_row",
            "artifact_fingerprint",
            "drift",
            "research_simulation_draft_drift",
        ),
        ("backtest", "status", "running", "research_simulation_backtest_drift"),
        (
            "backtest",
            "backtest_run_id",
            "other-run",
            "research_simulation_backtest_drift",
        ),
        (
            "backtest",
            "session_id",
            "other-session",
            "research_simulation_backtest_drift",
        ),
        ("backtest", "draft_id", "other-draft", "research_simulation_backtest_drift"),
        (
            "backtest",
            "canonical_backtest_result_id",
            202,
            "research_simulation_backtest_drift",
        ),
        (
            "backtest",
            "formula_fingerprint",
            "drift",
            "research_simulation_formula_binding_drift",
        ),
        (
            "backtest",
            "dataset_snapshot_id",
            "drift",
            "research_simulation_formula_binding_drift",
        ),
        (
            "backtest",
            "cost_model_reference",
            "drift",
            "research_simulation_formula_binding_drift",
        ),
        (
            "backtest",
            "evidence_fingerprint",
            "drift",
            "research_simulation_saved_facts_incomplete",
        ),
        ("critique", "status", "running", "research_simulation_critique_drift"),
        (
            "critique",
            "critique_id",
            "other-critique",
            "research_simulation_critique_drift",
        ),
        (
            "critique",
            "session_id",
            "other-session",
            "research_simulation_critique_drift",
        ),
        ("critique", "draft_id", "other-draft", "research_simulation_critique_drift"),
        (
            "critique",
            "backtest_run_id",
            "other-run",
            "research_simulation_critique_drift",
        ),
        ("critique", "artifact", None, "research_simulation_critique_drift"),
        (
            "critique",
            "artifact_fingerprint",
            "drift",
            "research_simulation_critique_drift",
        ),
    ],
)
def test_incomplete_or_cross_bound_saved_lineage_is_blocked(
    lineage, target, field, value, blocker
):
    getattr(lineage, target)[field] = value
    _assert_blocked(
        lineage.service.resolve_research_simulation_source(lineage.source), blocker
    )


@pytest.mark.parametrize("field", ["session_id", "draft_id", "formula_ast"])
def test_rehashed_draft_still_must_match_selected_lineage_and_formula(lineage, field):
    draft = lineage.draft_row["contract"]
    draft[field] = {} if field == "formula_ast" else "other-lineage"
    lineage.draft_row["artifact_fingerprint"] = content_fingerprint(draft)
    _assert_blocked(lineage.service.resolve_research_simulation_source(lineage.source))


@pytest.mark.parametrize(
    "field",
    [
        "workflow_id",
        "evidence_reference_id",
        "context_snapshot_id",
        "context_fingerprint",
    ],
)
def test_rehashed_draft_cannot_substitute_another_research_context(lineage, field):
    draft = lineage.draft_row["contract"]
    assert draft[field] == lineage.session[field]
    draft[field] = "other-research-context"
    lineage.draft_row["artifact_fingerprint"] = content_fingerprint(draft)
    _assert_blocked(
        lineage.service.resolve_research_simulation_source(lineage.source),
        "research_simulation_draft_drift",
    )


@pytest.mark.parametrize(
    "drift",
    ["missing_oos", "missing_return", "financial_return", "cost", "bundle", "saved_id"],
)
def test_canonical_saved_financial_facts_must_remain_complete(lineage, drift):
    metrics = lineage.saved["metrics_json"]
    if drift == "missing_oos":
        del metrics["oos_validation"]
    elif drift == "missing_return":
        del lineage.saved["total_return"]
        del metrics["total_return"]
    elif drift == "financial_return":
        lineage.saved["total_return"] = metrics["total_return"] = 0.99
    elif drift == "cost":
        lineage.saved["cost_summary_json"]["total_commission"] += 1
    elif drift == "bundle":
        metrics["research_evidence_bundle"]["bundle_id"] = "drift"
    else:
        lineage.saved["id"] = 202
    _assert_blocked(lineage.service.resolve_research_simulation_source(lineage.source))


@pytest.mark.parametrize("field", ["config_json", "metrics_json", "cost_summary_json"])
def test_invalid_canonical_json_cannot_become_ready(lineage, field):
    lineage.saved[field] = "{invalid-json"
    _assert_blocked(lineage.service.resolve_research_simulation_source(lineage.source))


def test_hypothesis_workflow_cannot_substitute_for_independent_critique(lineage):
    previous = lineage.critique["workflow_id"]
    reused = lineage.session["workflow_id"]
    lineage.critique["workflow_id"] = reused
    for kind in ("workflow", "replay", "report"):
        lineage.rows[kind][reused] = deepcopy(lineage.rows[kind][previous])
    lineage.rows["workflow"][reused].workflow_id = reused
    _assert_blocked(lineage.service.resolve_research_simulation_source(lineage.source))


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", WorkflowStatus.RUNNING),
        ("partial_result", True),
        ("workflow_id", "other-workflow"),
        ("context_snapshot_id", "other-context"),
        ("context_fingerprint", "c" * 64),
    ],
)
def test_critique_workflow_must_complete_in_the_selected_session_context(
    lineage, field, value
):
    workflow = lineage.rows["workflow"][lineage.critique["workflow_id"]]
    setattr(workflow, field, value)
    _assert_blocked(
        lineage.service.resolve_research_simulation_source(lineage.source),
        "research_simulation_critique_binding_drift",
    )


@pytest.mark.parametrize("field", ["canonical_binding_echo", "evidence_reference_ids"])
def test_rehashed_critique_still_must_echo_exact_canonical_evidence(lineage, field):
    artifact = lineage.critique["artifact"]
    if field == "canonical_binding_echo":
        artifact[field]["canonical_backtest_result_id"] = 202
    else:
        artifact[field] = ["other-evidence-reference"]
    lineage.critique["artifact_fingerprint"] = content_fingerprint(artifact)
    _assert_blocked(
        lineage.service.resolve_research_simulation_source(lineage.source),
        "research_simulation_critique_binding_drift",
    )


@pytest.mark.parametrize(
    "boundary",
    ["backtest_events", "critique_events", "replay", "report", "missing_report"],
)
def test_saved_audit_and_report_artifact_must_replay(lineage, boundary):
    if boundary.endswith("_events"):
        key = (
            lineage.source.backtest_run_id
            if boundary == "backtest_events"
            else lineage.source.critique_id
        )
        lineage.rows["events"][key] = (False, ["fixture-drift"])
    elif boundary == "replay":
        lineage.rows["replay"][lineage.critique["workflow_id"]].valid = False
    elif boundary == "report":
        lineage.rows["report"][lineage.critique["workflow_id"]][0].content = {}
    else:
        lineage.rows["report"][lineage.critique["workflow_id"]] = []
    _assert_blocked(lineage.service.resolve_research_simulation_source(lineage.source))


def test_session_integrity_drift_blocks_before_any_downstream_read(
    lineage, monkeypatch
):
    def reject(session):
        raise StrategyResearchRejected("fixture_session_integrity_drift")

    monkeypatch.setattr(lineage.service, "_validate_session_integrity", reject)
    _assert_blocked(
        lineage.service.resolve_research_simulation_source(lineage.source),
        "fixture_session_integrity_drift",
    )
    assert lineage.calls == [("session", lineage.source.session_id)]
