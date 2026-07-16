from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier

import pytest

from server.ai_runtime.contracts import (
    AgentRole,
    ArtifactKind,
    Claim,
    Debate,
    EvidenceBoundContextSnapshot,
    EvidenceReference,
    MemoryArtifact,
    ModelRegistration,
    ProviderRegistration,
    Report,
    Review,
    StageDefinition,
    ToolRequest,
    TradePlanDraft,
    WorkflowDefinition,
    WorkflowStatus,
)
from server.ai_runtime.orchestrator import DeterministicWorkflowOrchestrator
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
