from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from server.ai_runtime.contracts import (
    AgentRole,
    ArtifactKind,
    Claim,
    ModelRegistration,
    ProviderRegistration,
    StageDefinition,
    ToolRequest,
    WorkflowDefinition,
    WorkflowStatus,
)
from server.ai_runtime.evidence import (
    CANONICAL_EVIDENCE_KINDS,
    CanonicalEvidenceRecord,
    CanonicalEvidenceRepository,
    CanonicalEvidenceToolExecutors,
    EvidenceContextBuilder,
    EvidenceIdentityMismatch,
    EvidenceReadDenied,
)
from server.ai_runtime.orchestrator import DeterministicWorkflowOrchestrator
from server.ai_runtime.permissions import default_tool_permission_registry
from server.ai_runtime.provider import DeterministicFixtureProvider, ProviderResponse
from server.ai_runtime.registry import AiRuntimeRegistry
from server.ai_runtime.store import AiAuditStore

NOW = "2026-07-13T09:00:00+00:00"
VALUATION_ID = "valuation-evidence-001"
LEDGER_CUTOFF_ID = 57
LEDGER_FINGERPRINT = "ledger-evidence-fingerprint-001"


def _record(
    *,
    tool_name: str = "portfolio_projection.read",
    status: str = "complete",
    valuation_snapshot_id: str = VALUATION_ID,
    ledger_cutoff_id: int = LEDGER_CUTOFF_ID,
    ledger_fingerprint: str = LEDGER_FINGERPRINT,
    marker: str = "portfolio-fixture",
    captured_at: str = NOW,
) -> CanonicalEvidenceRecord:
    return CanonicalEvidenceRecord.capture(
        tool_name=tool_name,
        valuation_snapshot_id=valuation_snapshot_id,
        ledger_cutoff_id=ledger_cutoff_id,
        ledger_fingerprint=ledger_fingerprint,
        status=status,
        as_of=NOW,
        source_schema_version=f"karkinos.{CANONICAL_EVIDENCE_KINDS[tool_name]}.v1",
        payload={
            "marker": marker,
            "valuation_snapshot_id": valuation_snapshot_id,
            "ledger_cutoff_id": ledger_cutoff_id,
            "ledger_fingerprint": ledger_fingerprint,
            "persisted_facts_only": True,
        },
        captured_at=captured_at,
    )


@pytest.mark.unit
def test_canonical_capture_is_content_addressed_idempotent_and_restartable(tmp_path):
    db_path = tmp_path / "app.db"
    record = _record()
    first = CanonicalEvidenceRepository(db_path)
    first.init()

    assert first.persist(record) == record
    assert first.persist(_record(captured_at="2026-07-13T09:01:00+00:00")) == record

    restarted = CanonicalEvidenceRepository(db_path)
    restarted.init()
    assert restarted.get(record.reference_id) == record
    assert restarted.list_for_identity(
        valuation_snapshot_id=VALUATION_ID,
        ledger_cutoff_id=LEDGER_CUTOFF_ID,
        ledger_fingerprint=LEDGER_FINGERPRINT,
    ) == (record,)
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_canonical_evidence").fetchone()[0]
            == 1
        )


@pytest.mark.unit
def test_restart_read_detects_tampered_persisted_payload(tmp_path):
    db_path = tmp_path / "app.db"
    repository = CanonicalEvidenceRepository(db_path)
    repository.init()
    record = repository.persist(_record())
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_canonical_evidence SET payload_json = ? WHERE reference_id = ?",
            ('{"marker":"tampered"}', record.reference_id),
        )

    with pytest.raises(EvidenceIdentityMismatch, match="payload fingerprint drift"):
        repository.get(record.reference_id)


@pytest.mark.unit
def test_changed_payload_gets_distinct_evidence_identity_without_overwrite(tmp_path):
    repository = CanonicalEvidenceRepository(tmp_path / "app.db")
    repository.init()
    first = repository.persist(_record(marker="first"))
    second = repository.persist(_record(marker="second"))

    assert first.reference_id != second.reference_id
    assert first.payload_fingerprint != second.payload_fingerprint
    assert repository.get(first.reference_id) == first
    assert repository.get(second.reference_id) == second


@pytest.mark.unit
@pytest.mark.parametrize(
    "field_name", ["valuation_snapshot_id", "ledger_cutoff_id", "ledger_fingerprint"]
)
def test_capture_rejects_payload_that_contradicts_financial_envelope(field_name):
    payload = {
        "valuation_snapshot_id": VALUATION_ID,
        "ledger_cutoff_id": LEDGER_CUTOFF_ID,
        "ledger_fingerprint": LEDGER_FINGERPRINT,
    }
    payload[field_name] = "drifted" if field_name != "ledger_cutoff_id" else 999

    with pytest.raises(EvidenceIdentityMismatch, match=field_name):
        CanonicalEvidenceRecord.capture(
            tool_name="portfolio_projection.read",
            valuation_snapshot_id=VALUATION_ID,
            ledger_cutoff_id=LEDGER_CUTOFF_ID,
            ledger_fingerprint=LEDGER_FINGERPRINT,
            status="complete",
            as_of=NOW,
            source_schema_version="karkinos.portfolio_projection.v1",
            payload=payload,
            captured_at=NOW,
        )


@pytest.mark.unit
def test_context_builder_fails_closed_on_snapshot_or_ledger_drift():
    with pytest.raises(EvidenceIdentityMismatch, match="identity drift"):
        EvidenceContextBuilder().build(
            account_alias="primary",
            records=(
                _record(),
                _record(
                    tool_name="account_state_projection.read",
                    ledger_cutoff_id=LEDGER_CUTOFF_ID + 1,
                    ledger_fingerprint="ledger-drifted",
                ),
            ),
            created_at=NOW,
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "authoritative"),
    [
        ("complete", True),
        ("partial", False),
        ("stale", False),
        ("estimated", False),
        ("unreconciled", False),
    ],
)
def test_read_executor_makes_incomplete_evidence_non_authoritative(
    tmp_path, status, authoritative
):
    repository = CanonicalEvidenceRepository(tmp_path / "app.db")
    repository.init()
    record = repository.persist(_record(status=status))
    context = EvidenceContextBuilder().build(
        account_alias="primary", records=(record,), created_at=NOW
    )
    executor = CanonicalEvidenceToolExecutors(repository).as_mapping()[
        "portfolio_projection.read"
    ]

    output = executor(
        {"evidence_reference_id": record.reference_id},
        context,
    )

    assert output["authoritative"] is authoritative
    assert output["persisted_facts_only"] is True
    assert output["valuation_snapshot_id"] == VALUATION_ID
    assert output["ledger_cutoff_id"] == LEDGER_CUTOFF_ID
    assert output["payload"] == record.payload
    assert bool(output["blocking_reasons"]) is (not authoritative)


@pytest.mark.unit
@pytest.mark.parametrize("tool_name", tuple(CANONICAL_EVIDENCE_KINDS))
def test_every_registered_financial_read_tool_uses_exact_bound_record(
    tmp_path, tool_name
):
    repository = CanonicalEvidenceRepository(tmp_path / f"{tool_name}.db")
    repository.init()
    record = repository.persist(_record(tool_name=tool_name))
    context = EvidenceContextBuilder().build(
        account_alias="primary", records=(record,), created_at=NOW
    )

    output = CanonicalEvidenceToolExecutors(repository).as_mapping()[tool_name](
        {"evidence_reference_id": record.reference_id}, context
    )

    assert output["kind"] == CANONICAL_EVIDENCE_KINDS[tool_name]
    assert output["record_fingerprint"] == record.record_fingerprint


@pytest.mark.unit
def test_read_executor_rejects_unbound_wrong_tool_and_extra_arguments(tmp_path):
    repository = CanonicalEvidenceRepository(tmp_path / "app.db")
    repository.init()
    portfolio = repository.persist(_record())
    operations = repository.persist(_record(tool_name="operations_summary.read"))
    context = EvidenceContextBuilder().build(
        account_alias="primary", records=(portfolio,), created_at=NOW
    )
    executors = CanonicalEvidenceToolExecutors(repository).as_mapping()

    with pytest.raises(EvidenceReadDenied, match="outside context"):
        executors["operations_summary.read"](
            {"evidence_reference_id": operations.reference_id}, context
        )
    with pytest.raises(EvidenceReadDenied, match="another tool"):
        executors["operations_summary.read"](
            {"evidence_reference_id": portfolio.reference_id}, context
        )
    with pytest.raises(EvidenceReadDenied, match="require only"):
        executors["portfolio_projection.read"](
            {
                "evidence_reference_id": portfolio.reference_id,
                "refresh": True,
            },
            context,
        )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_orchestrator_reads_bound_evidence_and_audit_replays_without_authority_writes(
    tmp_path,
):
    db_path = tmp_path / "app.db"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        for table in (
            "oms_orders",
            "ledger_entries",
            "risk_decisions",
            "runtime_controls",
        ):
            conn.execute(
                f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, marker TEXT NOT NULL)"
            )
            conn.execute(f"INSERT INTO {table} (marker) VALUES ('protected')")

    evidence_repository = CanonicalEvidenceRepository(db_path)
    evidence_repository.init()
    evidence = evidence_repository.persist(_record())
    context = EvidenceContextBuilder().build(
        account_alias="primary", records=(evidence,), created_at=NOW
    )
    store = AiAuditStore(db_path)
    store.init()
    registry = AiRuntimeRegistry(store)
    registry.register_provider(
        ProviderRegistration(
            provider_id="fixture.local",
            display_name="Local fixture",
            adapter_kind="fixture",
            enabled=True,
        )
    )
    registry.register_model(
        ModelRegistration(
            model_id="fixture.local/read-v1",
            provider_id="fixture.local",
            model_name="read-v1",
            enabled=True,
        )
    )
    registry.register_role(
        AgentRole(
            role_id="portfolio_reader",
            display_name="Portfolio reader",
            purpose="Read frozen portfolio evidence only",
            allowed_tools=("portfolio_projection.read",),
            allowed_artifact_kinds=(ArtifactKind.CLAIM,),
        )
    )
    claim = Claim(
        statement="Frozen portfolio evidence was read",
        confidence="fixture",
        assumptions=("The capture caller used the canonical projection",),
        limitations=("No external model was called",),
        evidence_reference_ids=(evidence.reference_id,),
    ).to_draft()
    provider = DeterministicFixtureProvider(
        provider_id="fixture.local",
        responses={
            "read": (
                ProviderResponse(
                    tool_requests=(
                        ToolRequest(
                            request_id="read-portfolio-1",
                            tool_name="portfolio_projection.read",
                            arguments={"evidence_reference_id": evidence.reference_id},
                        ),
                    )
                ),
                ProviderResponse(artifacts=(claim,)),
            )
        },
    )
    orchestrator = DeterministicWorkflowOrchestrator(
        store=store,
        registry=registry,
        permissions=default_tool_permission_registry(),
        providers={"fixture.local": provider},
        tool_executors=CanonicalEvidenceToolExecutors(evidence_repository).as_mapping(),
        now=lambda: NOW,
    )
    workflow = orchestrator.create_workflow(
        definition=WorkflowDefinition(
            definition_id="read-only-portfolio-v1",
            name="Read-only portfolio evidence",
            stages=(
                StageDefinition(
                    stage_id="read",
                    role_id="portfolio_reader",
                    model_id="fixture.local/read-v1",
                    output_kind=ArtifactKind.CLAIM,
                ),
            ),
        ),
        context=context,
        idempotency_key="bound-evidence-read",
    )

    completed = orchestrator.run(workflow.workflow_id)

    assert completed.status == WorkflowStatus.COMPLETED
    assert provider.invocations[1].tool_results[0].output["authoritative"] is True
    assert store.list_tool_calls(workflow.workflow_id)[0].status.value == "completed"
    assert store.verify_replay(workflow.workflow_id).valid is True
    with closing(sqlite3.connect(db_path)) as conn:
        for table in (
            "oms_orders",
            "ledger_entries",
            "risk_decisions",
            "runtime_controls",
        ):
            assert (
                conn.execute(f"SELECT marker FROM {table}").fetchone()[0] == "protected"
            )
