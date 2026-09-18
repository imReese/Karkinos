from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier

import pytest

from server.ai_runtime.contracts import (
    AgentRole,
    AIResearchCapability,
    AITrace,
    ArtifactKind,
    Claim,
    Debate,
    EvidenceBoundContextSnapshot,
    EvidenceReference,
    MemoryArtifact,
    ModelRegistration,
    ProviderRegistration,
    Report,
    ResearchBudget,
    ResearchClaim,
    ResearchClaimSupportStatus,
    ResearchEvaluationBundle,
    ResearchHypothesis,
    ResearchSelection,
    ResearchSelectionDecision,
    ResearchSelectionSource,
    Review,
    StageDefinition,
    ToolRequest,
    TradePlanDraft,
    WorkflowDefinition,
    WorkflowStatus,
    canonical_json,
    content_fingerprint,
)
from server.ai_runtime.orchestrator import (
    DeterministicWorkflowOrchestrator,
    WorkflowValidationError,
)
from server.ai_runtime.permissions import default_tool_permission_registry
from server.ai_runtime.provider import (
    DeterministicFixtureProvider,
    ProviderResponse,
)
from server.ai_runtime.registry import AiRuntimeRegistry
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict

NOW = "2026-07-13T08:00:00+00:00"
PROVIDER_ID = "fixture.local"
MODEL_ID = "fixture.local/research-v1"
ROLE_ID = "fundamental_analyst"
PORTFOLIO_REF = "portfolio-projection-001"
RESEARCH_REF = "research-evidence-001"


def _context(
    *,
    valuation_snapshot_id: str = "valuation-001",
    ledger_cutoff_id: int = 41,
    ledger_fingerprint: str = "ledger-fingerprint-001",
) -> EvidenceBoundContextSnapshot:
    return EvidenceBoundContextSnapshot.create(
        account_alias="primary",
        valuation_snapshot_id=valuation_snapshot_id,
        ledger_cutoff_id=ledger_cutoff_id,
        ledger_fingerprint=ledger_fingerprint,
        evidence_references=(
            EvidenceReference(
                reference_id=PORTFOLIO_REF,
                kind="canonical_portfolio_projection",
                fingerprint="portfolio-fingerprint-001",
                as_of=NOW,
                status="complete",
                schema_version="karkinos.portfolio_projection.v1",
            ),
            EvidenceReference(
                reference_id=RESEARCH_REF,
                kind="research_evidence_bundle",
                fingerprint="research-fingerprint-001",
                as_of=NOW,
                status="complete",
                schema_version="karkinos.research_evidence_bundle.v1",
            ),
        ),
        created_at=NOW,
    )


def _definition(*stages: StageDefinition) -> WorkflowDefinition:
    return WorkflowDefinition(
        definition_id="daily-research-v1",
        name="Daily evidence review",
        stages=tuple(stages),
    )


def _stage(
    stage_id: str,
    *,
    output_kind: ArtifactKind = ArtifactKind.CLAIM,
) -> StageDefinition:
    return StageDefinition(
        stage_id=stage_id,
        role_id=ROLE_ID,
        model_id=MODEL_ID,
        output_kind=output_kind,
    )


def _claim(text: str = "The portfolio evidence is internally consistent"):
    return Claim(
        statement=text,
        confidence="fixture",
        assumptions=("Inputs are frozen",),
        limitations=("No external model was called",),
        evidence_reference_ids=(PORTFOLIO_REF,),
    ).to_draft()


def _report():
    return Report(
        title="Fixture research report",
        summary="Deterministic synthesis",
        sections=({"heading": "Evidence", "body": "Frozen local facts"},),
        limitations=("Fixture-only",),
        evidence_reference_ids=(PORTFOLIO_REF, RESEARCH_REF),
    ).to_draft()


def _trade_plan_draft():
    return TradePlanDraft(
        thesis="Review a possible rebalance; do not execute it",
        candidate_actions=({"symbol": "510300", "action": "review"},),
        assumptions=("Valuation remains bound to the frozen snapshot",),
        risk_notes=("Requires independent human and risk review",),
        evidence_reference_ids=(PORTFOLIO_REF, RESEARCH_REF),
    ).to_draft()


def _runtime(
    db_path: Path,
    *,
    responses: dict[str, tuple[ProviderResponse, ...]],
    failures: dict[tuple[str, int], Exception] | None = None,
    allowed_tools: tuple[str, ...] = (),
    artifact_kinds: tuple[ArtifactKind, ...] = (
        ArtifactKind.CLAIM,
        ArtifactKind.REPORT,
        ArtifactKind.TRADE_PLAN_DRAFT,
    ),
    tool_executors=None,
):
    store = AiAuditStore(db_path)
    store.init()
    registry = AiRuntimeRegistry(store)
    if not store.list_providers():
        registry.register_provider(
            ProviderRegistration(
                provider_id=PROVIDER_ID,
                display_name="Deterministic local fixture",
                adapter_kind="fixture",
                enabled=True,
                capabilities=("research",),
            )
        )
        registry.register_model(
            ModelRegistration(
                model_id=MODEL_ID,
                provider_id=PROVIDER_ID,
                model_name="research-v1",
                enabled=True,
                purposes=("research",),
            )
        )
        registry.register_role(
            AgentRole(
                role_id=ROLE_ID,
                display_name="Fixture analyst",
                purpose="Analyze frozen evidence without execution authority",
                capability=AIResearchCapability.EXPLAIN,
                allowed_tools=allowed_tools,
                allowed_artifact_kinds=artifact_kinds,
            )
        )
    provider = DeterministicFixtureProvider(
        provider_id=PROVIDER_ID,
        responses=responses,
        failures=failures,
    )
    orchestrator = DeterministicWorkflowOrchestrator(
        store=store,
        registry=registry,
        permissions=default_tool_permission_registry(),
        providers={PROVIDER_ID: provider},
        tool_executors=tool_executors or {},
        now=lambda: NOW,
    )
    return store, provider, orchestrator


@pytest.mark.unit
@pytest.mark.trading_safety
def test_ai_capability_levels_stop_at_bounded_research():
    assert [item.value for item in AIResearchCapability] == [
        "observe",
        "explain",
        "investigate",
        "propose",
        "orchestrate_research",
    ]
    assert all("execut" not in item.value for item in AIResearchCapability)


@pytest.mark.unit
def test_tool_permissions_enforce_minimum_ai_capability():
    permissions = default_tool_permission_registry()
    observer = AgentRole(
        role_id="observer",
        display_name="Observer",
        purpose="Read persisted evidence without interpretation.",
        capability=AIResearchCapability.OBSERVE,
        allowed_tools=("portfolio_projection.read", "calculator.evaluate"),
        allowed_artifact_kinds=(ArtifactKind.CLAIM,),
    )
    read_authorization = permissions.authorize(
        role=observer,
        tool_name="portfolio_projection.read",
        context=_context(),
    )
    calculator_authorization = permissions.authorize(
        role=observer,
        tool_name="calculator.evaluate",
        context=_context(),
    )

    assert read_authorization.allowed is True
    assert calculator_authorization.allowed is False
    assert calculator_authorization.reason == "capability_too_low"

    explainer = AgentRole(
        role_id="explainer",
        display_name="Explainer",
        purpose="Explain persisted evidence using deterministic arithmetic.",
        capability=AIResearchCapability.EXPLAIN,
        allowed_tools=("calculator.evaluate",),
        allowed_artifact_kinds=(ArtifactKind.CLAIM,),
    )
    assert (
        permissions.authorize(
            role=explainer,
            tool_name="calculator.evaluate",
            context=_context(),
        ).allowed
        is True
    )


@pytest.mark.unit
def test_legacy_role_payload_upgrades_without_false_registration_conflict(tmp_path):
    db_path = tmp_path / "legacy-role.db"
    store = AiAuditStore(db_path)
    store.init()
    legacy_payload = {
        "role_id": "external.strategy_hypothesis_researcher.v10",
        "display_name": "Strategy hypothesis researcher",
        "purpose": "Propose bounded research hypotheses without authority.",
        "allowed_tools": ["research_evidence.read"],
        "allowed_artifact_kinds": ["report"],
        "instructions_version": "karkinos.ai.strategy_research_prompt.v11",
    }
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            """
            INSERT INTO ai_agent_roles (
                role_id, payload_json, payload_fingerprint, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                legacy_payload["role_id"],
                canonical_json(legacy_payload),
                content_fingerprint(legacy_payload),
                NOW,
            ),
        )

    upgraded = AgentRole(
        role_id=legacy_payload["role_id"],
        display_name=legacy_payload["display_name"],
        purpose=legacy_payload["purpose"],
        capability=AIResearchCapability.PROPOSE,
        allowed_tools=("research_evidence.read",),
        allowed_artifact_kinds=(ArtifactKind.REPORT,),
        instructions_version=legacy_payload["instructions_version"],
    )

    assert store.list_roles() == (upgraded,)
    store.register_role(upgraded, created_at=NOW)
    assert store.list_roles() == (upgraded,)

    with pytest.raises(IdempotencyConflict):
        store.register_role(
            AgentRole(
                role_id=legacy_payload["role_id"],
                display_name=legacy_payload["display_name"],
                purpose=legacy_payload["purpose"],
                capability=AIResearchCapability.EXPLAIN,
                allowed_tools=("research_evidence.read",),
                allowed_artifact_kinds=(ArtifactKind.REPORT,),
                instructions_version=legacy_payload["instructions_version"],
            ),
            created_at=NOW,
        )


@pytest.mark.unit
def test_research_budget_is_explicit_bounded_and_fingerprint_stable():
    budget = ResearchBudget(
        max_candidates=5,
        max_iterations=5,
        max_backtests=30,
        max_parameter_variants=20,
        max_provider_calls=10,
        max_external_searches=8,
    )

    assert budget.to_dict()["max_backtests"] == 30
    assert (
        budget.fingerprint
        == ResearchBudget(
            **{
                key: value
                for key, value in budget.to_dict().items()
                if key != "schema_version"
            }
        ).fingerprint
    )
    with pytest.raises(ValueError, match="max_candidates must be positive"):
        ResearchBudget(
            max_candidates=0,
            max_iterations=5,
            max_backtests=30,
            max_parameter_variants=20,
            max_provider_calls=10,
            max_external_searches=8,
        )
    with pytest.raises(ValueError, match="max_provider_calls must be non-negative"):
        ResearchBudget(
            max_candidates=5,
            max_iterations=5,
            max_backtests=30,
            max_parameter_variants=20,
            max_provider_calls=-1,
            max_external_searches=8,
        )


@pytest.mark.unit
def test_workflow_budget_round_trips_without_changing_legacy_definition_shape():
    legacy = _definition(_stage("evidence"))
    legacy_payload = legacy.to_dict()

    assert "research_budget" not in legacy_payload
    assert WorkflowDefinition.from_dict(legacy_payload) == legacy
    assert (
        WorkflowDefinition.from_dict(legacy_payload).fingerprint == legacy.fingerprint
    )

    budget = ResearchBudget(
        max_candidates=5,
        max_iterations=5,
        max_backtests=5,
        max_parameter_variants=9,
        max_provider_calls=10,
        max_external_searches=0,
    )
    budgeted = WorkflowDefinition(
        definition_id="budgeted-research-v1",
        name="Budgeted research",
        stages=(_stage("evidence"),),
        research_budget=budget,
    )

    assert budgeted.to_dict()["research_budget"] == budget.to_dict()
    assert WorkflowDefinition.from_dict(budgeted.to_dict()) == budgeted


@pytest.mark.unit
@pytest.mark.trading_safety
def test_provider_call_upper_bound_must_fit_research_budget_before_persistence(
    tmp_path,
):
    db_path = tmp_path / "budget-rejected.db"
    store, provider, runtime = _runtime(
        db_path,
        responses={"evidence": (ProviderResponse(artifacts=(_claim(),)),)},
    )
    definition = WorkflowDefinition(
        definition_id="budget-too-small-v1",
        name="Budget too small",
        stages=(_stage("evidence"),),
        research_budget=ResearchBudget(
            max_candidates=1,
            max_iterations=1,
            max_backtests=1,
            max_parameter_variants=0,
            max_provider_calls=1,
            max_external_searches=0,
        ),
    )

    with pytest.raises(
        WorkflowValidationError,
        match="provider-call upper bound exceeds research budget",
    ):
        runtime.create_workflow(
            definition=definition,
            context=_context(),
            idempotency_key="budget-too-small",
        )

    assert provider.invocations == ()
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ai_workflows").fetchone()[0] == 0


@pytest.mark.unit
@pytest.mark.trading_safety
def test_research_evaluation_bundle_cannot_be_ai_generated_or_authoritative():
    base = dict(
        evaluation_id="research-evaluation-001",
        backtest_result_id=17,
        source_fingerprint="sha256:" + "a" * 64,
        dataset_snapshot_id="sha256:dataset-001",
        research_gate_status="pass",
        research_evidence_bundle={"gate_status": "pass"},
        oos_validation={"validation_status": "passed"},
        after_cost_evidence={"total_cost": 12.0},
        cost_summary={"total_trades": 3},
        parameter_robustness={},
        market_regime_robustness={},
        capacity_review={},
        drawdown_evidence={},
        signal_execution_evidence={},
        lot_feasibility_evidence={},
        missing_evidence=(),
    )
    bundle = ResearchEvaluationBundle(**base)

    payload = bundle.to_dict()
    assert payload["persisted_source_only"] is True
    assert payload["deterministic"] is True
    assert payload["ai_generated"] is False
    assert payload["authority_effect"] == "none"

    with pytest.raises(ValueError, match="AI cannot generate"):
        ResearchEvaluationBundle(**base, ai_generated=True)
    with pytest.raises(ValueError, match="cannot change execution authority"):
        ResearchEvaluationBundle(**base, authority_effect="expand")


@pytest.mark.unit
@pytest.mark.trading_safety
def test_research_selection_is_non_ai_non_promoting_and_non_executable():
    selection = ResearchSelection(
        selection_id="research-selection-001",
        session_id="session-001",
        task_id="task-001",
        task_binding_status="bound",
        candidate_id="candidate-001",
        critique_id="critique-001",
        evaluation_id="evaluation-001",
        evaluation_fingerprint="sha256:" + "a" * 64,
        evaluation_gate_status="pass",
        decision=ResearchSelectionDecision.SELECTED_FOR_FURTHER_RESEARCH,
        source=ResearchSelectionSource.HUMAN,
        reviewer="human:reese",
        notes="Continue deterministic research; do not promote.",
        created_at=NOW,
    )

    payload = selection.to_dict()
    assert payload["decision"] == "selected_for_further_research"
    assert payload["requires_human_promotion"] is True
    assert payload["ai_generated"] is False
    assert payload["authority_effect"] == "none"
    assert selection.fingerprint == content_fingerprint(payload)

    with pytest.raises(ValueError, match="cannot bypass human promotion"):
        ResearchSelection(
            selection_id="research-selection-no-human",
            session_id="session-001",
            task_id="task-001",
            task_binding_status="bound",
            candidate_id="candidate-001",
            critique_id="critique-001",
            evaluation_id="evaluation-001",
            evaluation_fingerprint="sha256:" + "a" * 64,
            evaluation_gate_status="pass",
            decision=ResearchSelectionDecision.SELECTED_FOR_FURTHER_RESEARCH,
            source=ResearchSelectionSource.HUMAN,
            reviewer="human:reese",
            notes="unsafe",
            created_at=NOW,
            requires_human_promotion=False,
        )
    with pytest.raises(ValueError, match="AI cannot create canonical"):
        ResearchSelection(
            selection_id="research-selection-ai",
            session_id="session-001",
            task_id="task-001",
            task_binding_status="bound",
            candidate_id="candidate-001",
            critique_id="critique-001",
            evaluation_id="evaluation-001",
            evaluation_fingerprint="sha256:" + "a" * 64,
            evaluation_gate_status="pass",
            decision=ResearchSelectionDecision.NEEDS_REVISION,
            source=ResearchSelectionSource.HUMAN,
            reviewer="human:reese",
            notes="unsafe",
            created_at=NOW,
            ai_generated=True,
        )
    with pytest.raises(ValueError, match="cannot change execution authority"):
        ResearchSelection(
            selection_id="research-selection-authority",
            session_id="session-001",
            task_id="task-001",
            task_binding_status="bound",
            candidate_id="candidate-001",
            critique_id="critique-001",
            evaluation_id="evaluation-001",
            evaluation_fingerprint="sha256:" + "a" * 64,
            evaluation_gate_status="pass",
            decision=ResearchSelectionDecision.REJECTED,
            source=ResearchSelectionSource.HUMAN,
            reviewer="human:reese",
            notes="unsafe",
            created_at=NOW,
            authority_effect="expand",
        )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_formal_hypothesis_requires_falsification_and_has_no_authority_effect():
    hypothesis = ResearchHypothesis(
        hypothesis_id="hypothesis-001",
        task_id="task-001",
        thesis="Short-horizon reversal may improve the trend baseline.",
        mechanism="Crowded short-term momentum overshoots inside a long trend.",
        baseline_reference="dual_ma:v3",
        expected_regime="positive long trend with elevated short-horizon volatility",
        falsification_conditions=(
            "OOS return does not improve after costs",
            "turnover increase erases gross improvement",
        ),
        required_evidence=("frozen daily bars", "canonical cost model"),
        source_trace_id="trace-001",
    )

    payload = hypothesis.to_dict()
    assert payload["authority_effect"] == "none"
    assert payload["falsification_conditions"] == [
        "OOS return does not improve after costs",
        "turnover increase erases gross improvement",
    ]
    with pytest.raises(ValueError, match="require falsification conditions"):
        ResearchHypothesis(
            hypothesis_id="hypothesis-invalid",
            task_id="task-001",
            thesis="Unfalsifiable idea",
            mechanism="Unknown",
            baseline_reference="dual_ma:v3",
            expected_regime="all regimes",
            falsification_conditions=(),
            required_evidence=(),
        )
    with pytest.raises(ValueError, match="require evidence requirements"):
        ResearchHypothesis(
            hypothesis_id="hypothesis-no-evidence",
            task_id="task-001",
            thesis="Testable but underspecified idea",
            mechanism="Unknown",
            baseline_reference="dual_ma:v3",
            expected_regime="all regimes",
            falsification_conditions=("candidate fails evaluation",),
            required_evidence=(),
        )
    with pytest.raises(ValueError, match="cannot change execution authority"):
        ResearchHypothesis(
            hypothesis_id="hypothesis-unsafe",
            task_id="task-001",
            thesis="Unsafe idea",
            mechanism="Unknown",
            baseline_reference="dual_ma:v3",
            expected_regime="all regimes",
            falsification_conditions=("candidate fails evaluation",),
            required_evidence=("frozen evidence",),
            authority_effect="expand",
        )


@pytest.mark.unit
def test_research_claim_uses_evidence_status_not_numeric_model_confidence():
    claim = ResearchClaim(
        claim_id="claim-001",
        task_id="task-001",
        run_id="run-001",
        statement="Transaction costs materially reduce the candidate edge.",
        claim_type="evaluation_interpretation",
        evidence_reference_ids=("backtest-001", "cost-report-001"),
        support_status=ResearchClaimSupportStatus.SUPPORTED,
        as_of=NOW,
        source_trace_id="trace-001",
    )

    payload = claim.to_dict()
    assert payload["support_status"] == "supported"
    assert payload["evidence_reference_ids"] == ["backtest-001", "cost-report-001"]
    assert "confidence" not in payload
    assert payload["authority_effect"] == "none"

    with pytest.raises(ValueError, match="must cite evidence"):
        ResearchClaim(
            claim_id="claim-invalid",
            task_id="task-001",
            run_id="run-001",
            statement="Unsupported assertion",
            claim_type="interpretation",
            evidence_reference_ids=(),
            support_status=ResearchClaimSupportStatus.UNREVIEWED,
            as_of=NOW,
        )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_ai_trace_records_research_provenance_without_authority():
    trace = AITrace(
        trace_id="trace-001",
        task_id="task-001",
        run_id="run-001",
        capability=AIResearchCapability.PROPOSE,
        provider_id=PROVIDER_ID,
        model_id=MODEL_ID,
        prompt_version="karkinos.ai.fixture_prompt.v1",
        input_artifact_ids=("artifact-001",),
        evidence_reference_ids=(RESEARCH_REF,),
        tool_names=("research_evidence.read",),
        started_at=NOW,
        finished_at=NOW,
        token_usage=512,
        raw_output_fingerprint="raw-fingerprint",
        parsed_output_fingerprint="parsed-fingerprint",
    )

    payload = trace.to_dict()
    assert payload["capability"] == "propose"
    assert payload["authority_effect"] == "none"
    assert trace.fingerprint == content_fingerprint(payload)

    with pytest.raises(ValueError, match="cannot change execution authority"):
        AITrace(
            trace_id="trace-unsafe",
            task_id="task-001",
            run_id="run-001",
            capability=AIResearchCapability.ORCHESTRATE_RESEARCH,
            provider_id=PROVIDER_ID,
            model_id=MODEL_ID,
            prompt_version="karkinos.ai.fixture_prompt.v1",
            input_artifact_ids=(),
            evidence_reference_ids=(),
            tool_names=(),
            started_at=NOW,
            authority_effect="execute",
        )


@pytest.mark.unit
def test_runtime_registration_is_atomic_across_concurrent_store_instances(tmp_path):
    db_path = tmp_path / "concurrent-registration.db"
    seed_store = AiAuditStore(db_path)
    seed_store.init()
    registration = ProviderRegistration(
        provider_id=PROVIDER_ID,
        display_name="Deterministic local fixture",
        adapter_kind="fixture",
        enabled=True,
        capabilities=("research",),
    )

    def register_exact_duplicate(_: int) -> None:
        AiAuditStore(db_path).register_provider(registration, created_at=NOW)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(register_exact_duplicate, range(32)))

    assert seed_store.list_providers() == (registration,)
    with pytest.raises(IdempotencyConflict, match="conflicting registration"):
        seed_store.register_provider(
            ProviderRegistration(
                provider_id=PROVIDER_ID,
                display_name="Conflicting provider",
                adapter_kind="different-adapter",
                enabled=True,
            ),
            created_at=NOW,
        )


@pytest.mark.unit
def test_restart_resumes_from_persisted_stage_without_repeating_completed_stage(
    tmp_path,
):
    db_path = tmp_path / "app.db"
    responses = {
        "evidence": (ProviderResponse(artifacts=(_claim(),)),),
        "report": (ProviderResponse(artifacts=(_report(),)),),
    }
    store, first_provider, first_runtime = _runtime(db_path, responses=responses)
    workflow = first_runtime.create_workflow(
        definition=_definition(
            _stage("evidence"),
            _stage("report", output_kind=ArtifactKind.REPORT),
        ),
        context=_context(),
        idempotency_key="restart-case",
    )

    paused = first_runtime.run(workflow.workflow_id, max_stages=1)

    assert paused.status == WorkflowStatus.RUNNING
    assert paused.current_stage_index == 1
    assert [call.stage_id for call in first_provider.invocations] == ["evidence"]

    restarted_store, restarted_provider, restarted_runtime = _runtime(
        db_path, responses=responses
    )
    completed = restarted_runtime.run(workflow.workflow_id)

    assert completed.status == WorkflowStatus.COMPLETED
    assert [call.stage_id for call in restarted_provider.invocations] == ["report"]
    assert [
        item.kind for item in restarted_store.list_artifacts(workflow.workflow_id)
    ] == [
        ArtifactKind.CLAIM,
        ArtifactKind.REPORT,
    ]
    assert store.verify_replay(workflow.workflow_id).valid is True


@pytest.mark.unit
def test_duplicate_workflow_run_is_idempotent_and_conflicting_input_is_rejected(
    tmp_path,
):
    store, provider, runtime = _runtime(
        tmp_path / "app.db",
        responses={"evidence": (ProviderResponse(artifacts=(_claim(),)),)},
    )
    definition = _definition(_stage("evidence"))
    first = runtime.create_workflow(
        definition=definition,
        context=_context(),
        idempotency_key="duplicate-case",
    )
    duplicate = runtime.create_workflow(
        definition=definition,
        context=_context(),
        idempotency_key="duplicate-case",
    )

    assert duplicate.workflow_id == first.workflow_id
    assert runtime.run(first.workflow_id).status == WorkflowStatus.COMPLETED
    assert runtime.run(first.workflow_id).status == WorkflowStatus.COMPLETED
    assert len(provider.invocations) == 1
    assert len(store.list_agent_runs(first.workflow_id)) == 1
    assert len(store.list_artifacts(first.workflow_id)) == 1

    with pytest.raises(IdempotencyConflict):
        runtime.create_workflow(
            definition=definition,
            context=_context(
                valuation_snapshot_id="valuation-002",
                ledger_cutoff_id=42,
                ledger_fingerprint="ledger-fingerprint-002",
            ),
            idempotency_key="duplicate-case",
        )


@pytest.mark.unit
def test_concurrent_workflow_creation_reuses_one_atomic_audit_record(tmp_path):
    store, _, runtime = _runtime(
        tmp_path / "app.db",
        responses={"evidence": (ProviderResponse(artifacts=(_claim(),)),)},
    )
    definition = _definition(_stage("evidence"))
    context = _context()
    workers = 8
    barrier = Barrier(workers)

    def create_workflow(_):
        barrier.wait()
        return runtime.create_workflow(
            definition=definition,
            context=context,
            idempotency_key="concurrent-duplicate-case",
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        workflows = tuple(executor.map(create_workflow, range(workers)))

    assert len({workflow.workflow_id for workflow in workflows}) == 1
    workflow_id = workflows[0].workflow_id
    assert store.get_workflow(workflow_id).workflow_id == workflow_id
    with closing(sqlite3.connect(tmp_path / "app.db")) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_workflows WHERE idempotency_key = ?",
                ("concurrent-duplicate-case",),
            ).fetchone()[0]
            == 1
        )


@pytest.mark.unit
def test_stage_failure_preserves_prior_artifacts_as_explicit_partial_result(tmp_path):
    store, _, runtime = _runtime(
        tmp_path / "app.db",
        responses={
            "evidence": (ProviderResponse(artifacts=(_claim(),)),),
            "report": (ProviderResponse(artifacts=(_report(),)),),
        },
        failures={("report", 0): RuntimeError("fixture stage failure")},
    )
    workflow = runtime.create_workflow(
        definition=_definition(
            _stage("evidence"),
            _stage("report", output_kind=ArtifactKind.REPORT),
        ),
        context=_context(),
        idempotency_key="stage-failure-case",
    )

    failed = runtime.run(workflow.workflow_id)

    assert failed.status == WorkflowStatus.FAILED
    assert failed.partial_result is True
    assert failed.failure_code == "runtime"
    assert [item.kind for item in store.list_artifacts(workflow.workflow_id)] == [
        ArtifactKind.CLAIM
    ]
    assert [
        run.status.value for run in store.list_agent_runs(workflow.workflow_id)
    ] == [
        "completed",
        "failed",
    ]


@pytest.mark.unit
def test_partial_provider_result_is_persisted_and_not_promoted_to_complete(tmp_path):
    store, _, runtime = _runtime(
        tmp_path / "app.db",
        responses={"report": (ProviderResponse(artifacts=(_report(),), partial=True),)},
    )
    workflow = runtime.create_workflow(
        definition=_definition(_stage("report", output_kind=ArtifactKind.REPORT)),
        context=_context(),
        idempotency_key="partial-case",
    )

    partial = runtime.run(workflow.workflow_id)

    assert partial.status == WorkflowStatus.PARTIAL
    assert partial.partial_result is True
    assert partial.failure_code == "partial_stage_result"
    assert len(store.list_artifacts(workflow.workflow_id)) == 1


@pytest.mark.unit
def test_evidence_drift_blocks_before_provider_invocation(tmp_path):
    _, provider, runtime = _runtime(
        tmp_path / "app.db",
        responses={"evidence": (ProviderResponse(artifacts=(_claim(),)),)},
    )
    workflow = runtime.create_workflow(
        definition=_definition(_stage("evidence")),
        context=_context(),
        idempotency_key="drift-case",
    )

    blocked = runtime.run(
        workflow.workflow_id,
        current_context=_context(
            valuation_snapshot_id="valuation-002",
            ledger_cutoff_id=42,
            ledger_fingerprint="ledger-fingerprint-002",
        ),
    )

    assert blocked.status == WorkflowStatus.BLOCKED
    assert blocked.failure_code == "evidence_drift"
    assert provider.invocations == ()


@pytest.mark.unit
@pytest.mark.trading_safety
def test_forbidden_tool_request_is_audited_and_never_executed(tmp_path):
    executor_calls = []
    store, provider, runtime = _runtime(
        tmp_path / "app.db",
        responses={
            "evidence": (
                ProviderResponse(
                    tool_requests=(
                        ToolRequest(
                            request_id="submit-1",
                            tool_name="broker.submit",
                            arguments={"symbol": "510300"},
                        ),
                    )
                ),
            )
        },
        tool_executors={
            "broker.submit": lambda arguments, context: executor_calls.append(
                (arguments, context)
            )
        },
    )
    workflow = runtime.create_workflow(
        definition=_definition(_stage("evidence")),
        context=_context(),
        idempotency_key="forbidden-tool-case",
    )

    failed = runtime.run(workflow.workflow_id)

    assert failed.status == WorkflowStatus.FAILED
    assert failed.failure_code == "unauthorized_tool_request"
    assert executor_calls == []
    assert len(provider.invocations) == 1
    calls = store.list_tool_calls(workflow.workflow_id)
    assert [
        (call.tool_name, call.status.value, call.denial_reason) for call in calls
    ] == [("broker.submit", "denied", "authority_namespace_forbidden")]


@pytest.mark.unit
def test_read_tool_result_must_bind_context_evidence_and_is_fed_to_next_turn(
    tmp_path,
):
    def read_portfolio(arguments, context):
        assert arguments == {"projection_id": PORTFOLIO_REF}
        assert context.valuation_snapshot_id == "valuation-001"
        return {
            "evidence_reference_id": PORTFOLIO_REF,
            "persisted_facts_only": True,
            "summary": {"total_equity": "100000.00"},
        }

    store, provider, runtime = _runtime(
        tmp_path / "app.db",
        responses={
            "evidence": (
                ProviderResponse(
                    tool_requests=(
                        ToolRequest(
                            request_id="portfolio-1",
                            tool_name="portfolio_projection.read",
                            arguments={"projection_id": PORTFOLIO_REF},
                        ),
                    )
                ),
                ProviderResponse(artifacts=(_claim(),)),
            )
        },
        allowed_tools=("portfolio_projection.read",),
        tool_executors={"portfolio_projection.read": read_portfolio},
    )
    workflow = runtime.create_workflow(
        definition=_definition(_stage("evidence")),
        context=_context(),
        idempotency_key="read-tool-case",
    )

    completed = runtime.run(workflow.workflow_id)

    assert completed.status == WorkflowStatus.COMPLETED
    assert len(provider.invocations) == 2
    assert provider.invocations[1].tool_results[0].output["persisted_facts_only"]
    assert store.list_tool_calls(workflow.workflow_id)[0].status.value == "completed"


@pytest.mark.unit
@pytest.mark.trading_safety
def test_read_tool_output_outside_frozen_evidence_context_fails_closed(tmp_path):
    store, _, runtime = _runtime(
        tmp_path / "app.db",
        responses={
            "evidence": (
                ProviderResponse(
                    tool_requests=(
                        ToolRequest(
                            request_id="portfolio-drift",
                            tool_name="portfolio_projection.read",
                            arguments={"projection_id": PORTFOLIO_REF},
                        ),
                    )
                ),
            )
        },
        allowed_tools=("portfolio_projection.read",),
        tool_executors={
            "portfolio_projection.read": lambda arguments, context: {
                "evidence_reference_id": "unbound-runtime-value",
                "persisted_facts_only": True,
            }
        },
    )
    workflow = runtime.create_workflow(
        definition=_definition(_stage("evidence")),
        context=_context(),
        idempotency_key="unbound-tool-output-case",
    )

    failed = runtime.run(workflow.workflow_id)

    assert failed.status == WorkflowStatus.FAILED
    assert failed.failure_code == "workflow_validation"
    assert store.list_tool_calls(workflow.workflow_id)[0].status.value == "failed"
    assert store.list_artifacts(workflow.workflow_id) == ()


@pytest.mark.unit
def test_audit_hash_chain_replays_and_detects_tampering(tmp_path):
    db_path = tmp_path / "app.db"
    store, _, runtime = _runtime(
        db_path,
        responses={"evidence": (ProviderResponse(artifacts=(_claim(),)),)},
    )
    workflow = runtime.create_workflow(
        definition=_definition(_stage("evidence")),
        context=_context(),
        idempotency_key="replay-case",
    )
    runtime.run(workflow.workflow_id)

    replay = store.verify_replay(workflow.workflow_id)
    assert replay.valid is True
    assert replay.event_count >= 4

    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_workflow_events SET payload_json = ? "
            "WHERE workflow_id = ? AND sequence_number = 2",
            ('{"tampered":true}', workflow.workflow_id),
        )

    tampered = store.verify_replay(workflow.workflow_id)
    assert tampered.valid is False
    assert "event_hash_mismatch:2" in tampered.errors


@pytest.mark.unit
@pytest.mark.trading_safety
def test_ai_runtime_shares_database_without_mutating_authority_or_financial_tables(
    tmp_path,
):
    db_path = tmp_path / "app.db"
    protected_tables = (
        "oms_orders",
        "ledger_entries",
        "risk_decisions",
        "runtime_controls",
        "controlled_broker_submit_intents",
        "broker_gateway_events",
    )
    with closing(sqlite3.connect(db_path)) as conn, conn:
        for table_name in protected_tables:
            conn.execute(
                f"CREATE TABLE {table_name} "
                "(id INTEGER PRIMARY KEY, marker TEXT NOT NULL)"
            )
            conn.execute(
                f"INSERT INTO {table_name} (marker) VALUES (?)",
                ("protected-sentinel",),
            )
    before = _table_counts(db_path, protected_tables)
    _, _, runtime = _runtime(
        db_path,
        responses={"draft": (ProviderResponse(artifacts=(_trade_plan_draft(),)),)},
    )
    workflow = runtime.create_workflow(
        definition=_definition(
            _stage("draft", output_kind=ArtifactKind.TRADE_PLAN_DRAFT)
        ),
        context=_context(),
        idempotency_key="shared-db-safety-case",
    )

    completed = runtime.run(workflow.workflow_id)

    assert completed.status == WorkflowStatus.COMPLETED
    assert _table_counts(db_path, protected_tables) == before


@pytest.mark.unit
@pytest.mark.trading_safety
def test_trade_plan_contract_rejects_any_authority_effect():
    with pytest.raises(ValueError, match="non-executable"):
        TradePlanDraft(
            thesis="unsafe",
            candidate_actions=(),
            assumptions=(),
            risk_notes=(),
            evidence_reference_ids=(PORTFOLIO_REF,),
            executable=True,
        )
    with pytest.raises(ValueError, match="cannot change execution authority"):
        TradePlanDraft(
            thesis="unsafe",
            candidate_actions=(),
            assumptions=(),
            risk_notes=(),
            evidence_reference_ids=(PORTFOLIO_REF,),
            authority_effect="expand",
        )


@pytest.mark.unit
def test_claim_debate_report_review_and_memory_contracts_keep_evidence_links():
    drafts = (
        _claim(),
        Debate(
            topic="Competing explanations",
            participant_role_ids=("analyst", "critic"),
            positions=({"role_id": "critic", "position": "Evidence is limited"},),
            unresolved_questions=("Will the finding survive OOS review?",),
            evidence_reference_ids=(RESEARCH_REF,),
        ).to_draft(),
        _report(),
        Review(
            decision="revise",
            reviewer_type="human_required",
            notes="Add a longer OOS window",
            reviewed_artifact_ids=("artifact-001",),
            evidence_reference_ids=(RESEARCH_REF,),
        ).to_draft(),
        MemoryArtifact(
            scope="strategy/dual-ma",
            content={"lesson": "Short windows were unstable"},
            source_artifact_ids=("artifact-001",),
            validity_status="review_required_on_evidence_drift",
            evidence_reference_ids=(RESEARCH_REF,),
        ).to_draft(),
    )

    assert [draft.kind for draft in drafts] == [
        ArtifactKind.CLAIM,
        ArtifactKind.DEBATE,
        ArtifactKind.REPORT,
        ArtifactKind.REVIEW,
        ArtifactKind.MEMORY,
    ]
    assert all(draft.evidence_reference_ids for draft in drafts)
    assert drafts[-1].content["authority_effect"] == "none"


def _table_counts(db_path: Path, table_names: tuple[str, ...]) -> dict[str, int]:
    with closing(sqlite3.connect(db_path)) as conn:
        return {
            table_name: int(
                conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            )
            for table_name in table_names
        }
