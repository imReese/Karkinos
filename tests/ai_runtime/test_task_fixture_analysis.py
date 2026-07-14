from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from server.ai_runtime.capture import CaptureEvidenceType, ContextCaptureAuditStore
from server.ai_runtime.evidence import (
    CanonicalEvidenceRepository,
    EvidenceIdentityMismatch,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from server.ai_runtime.task_analysis import (
    FIXTURE_ANALYSIS_CONFIRMATION,
    FIXTURE_MODEL_ID,
    FIXTURE_PROVIDER_ID,
    HumanFixtureAnalysisRequest,
    HumanResearchTaskFixtureAnalysisService,
    ResearchTaskAnalysisRejected,
    ResearchTaskAnalysisStore,
)
from server.ai_runtime.tasks import (
    HumanResearchTaskService,
    ResearchTaskReviewDecision,
    ResearchTaskStore,
)
from tests.ai_runtime.test_research_tasks import (
    NOW,
    _capture,
    _review_request,
    _task_request,
)


def _analysis_service(db_path):
    evidence = CanonicalEvidenceRepository(db_path)
    ai_store = AiAuditStore(db_path)
    captures = ContextCaptureAuditStore(db_path)
    tasks = ResearchTaskStore(db_path)
    analyses = ResearchTaskAnalysisStore(db_path)
    evidence.init()
    ai_store.init()
    captures.init()
    tasks.init()
    analyses.init()
    task_service = HumanResearchTaskService(
        evidence_repository=evidence,
        context_store=ai_store,
        capture_store=captures,
        task_store=tasks,
        now=lambda: NOW,
    )
    return HumanResearchTaskFixtureAnalysisService(
        ai_store=ai_store,
        evidence_repository=evidence,
        task_store=tasks,
        task_service=task_service,
        analysis_store=analyses,
        now=lambda: NOW,
    )


async def _accepted_task(db_path):
    capture = await _capture(db_path)
    evidence = CanonicalEvidenceRepository(db_path)
    ai_store = AiAuditStore(db_path)
    captures = ContextCaptureAuditStore(db_path)
    tasks = ResearchTaskStore(db_path)
    service = HumanResearchTaskService(
        evidence_repository=evidence,
        context_store=ai_store,
        capture_store=captures,
        task_store=tasks,
        now=lambda: NOW,
    )
    task = service.create(_task_request(capture.run.capture_id)).task
    accepted = service.review(task.task_id, _review_request()).task
    return capture, accepted


def _request(task_id: str, *, requested_by: str = "human:reese"):
    return HumanFixtureAnalysisRequest(
        task_id=task_id,
        idempotency_key="fixture-analysis-001",
        requested_by=requested_by,
        confirmation=FIXTURE_ANALYSIS_CONFIRMATION,
    )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_explicit_fixture_analysis_builds_cited_artifacts_without_authority(
    tmp_path,
):
    db_path = tmp_path / "fixture-analysis.db"
    protected_tables = (
        "oms_orders",
        "ledger_entries",
        "risk_decisions",
        "runtime_controls",
        "capital_authorizations",
    )
    with closing(sqlite3.connect(db_path)) as conn, conn:
        for table in protected_tables:
            conn.execute(
                f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, marker TEXT NOT NULL)"
            )
            conn.execute(f"INSERT INTO {table} (marker) VALUES ('protected')")

    capture, task = await _accepted_task(db_path)
    result = _analysis_service(db_path).start(_request(task.task_id))
    payload = result.to_dict()

    assert payload["workflow_status"] == "completed"
    assert payload["binding_validity"] == "valid"
    assert payload["memory_validity"] == ("human_review_required_exact_context_only")
    assert [item["kind"] for item in payload["artifacts"]] == [
        "claim",
        "debate",
        "report",
        "memory",
    ]
    expected_refs = {item.reference_id for item in capture.records}
    assert all(
        set(item["evidence_reference_ids"]) == expected_refs
        for item in payload["artifacts"]
    )
    memory = payload["artifacts"][-1]
    assert memory["content"]["source_artifact_ids"] == [
        item["artifact_id"] for item in payload["artifacts"][:3]
    ]
    assert len(payload["tool_calls"]) == len(capture.records)
    assert all(item["status"] == "completed" for item in payload["tool_calls"])
    assert payload["fixture_stage_run_count"] == 4
    assert payload["fixture_only"] is True
    assert payload["network_io_used"] is False
    assert payload["external_model_invocation_count"] == 0
    assert payload["real_provider_registered"] is False
    assert payload["authority_effect"] == "none"
    assert payload["audit_replay"]["valid"] is True

    ai_store = AiAuditStore(db_path)
    assert [item.provider_id for item in ai_store.list_providers()] == [
        FIXTURE_PROVIDER_ID
    ]
    assert [item.model_id for item in ai_store.list_models()] == [FIXTURE_MODEL_ID]
    with closing(sqlite3.connect(db_path)) as conn:
        for table in protected_tables:
            assert conn.execute(f"SELECT marker FROM {table}").fetchone()[0] == (
                "protected"
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fixture_analysis_is_idempotent_across_restart(tmp_path):
    db_path = tmp_path / "fixture-analysis.db"
    _, task = await _accepted_task(db_path)
    first = _analysis_service(db_path).start(_request(task.task_id))
    restarted = _analysis_service(db_path).start(_request(task.task_id))

    assert first.reused is False
    assert restarted.reused is True
    assert restarted.record == first.record
    assert restarted.workflow == first.workflow
    assert restarted.artifacts == first.artifacts
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_research_task_analyses").fetchone()[0]
            == 1
        )
        assert conn.execute("SELECT COUNT(*) FROM ai_workflows").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM ai_agent_runs").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM ai_artifacts").fetchone()[0] == 4

    with pytest.raises(IdempotencyConflict, match="different input"):
        _analysis_service(db_path).start(
            _request(task.task_id, requested_by="human:changed")
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fixture_analysis_requires_prior_human_context_acceptance(tmp_path):
    db_path = tmp_path / "fixture-analysis.db"
    capture = await _capture(db_path)
    evidence = CanonicalEvidenceRepository(db_path)
    ai_store = AiAuditStore(db_path)
    captures = ContextCaptureAuditStore(db_path)
    tasks = ResearchTaskStore(db_path)
    task_service = HumanResearchTaskService(
        evidence_repository=evidence,
        context_store=ai_store,
        capture_store=captures,
        task_store=tasks,
        now=lambda: NOW,
    )
    task = task_service.create(_task_request(capture.run.capture_id)).task

    with pytest.raises(ResearchTaskAnalysisRejected, match="explicitly accepted"):
        _analysis_service(db_path).start(_request(task.task_id))

    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_research_task_analyses").fetchone()[0]
            == 0
        )
        assert conn.execute("SELECT COUNT(*) FROM ai_workflows").fetchone()[0] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evidence_drift_blocks_before_fixture_provider_registration(tmp_path):
    db_path = tmp_path / "fixture-analysis.db"
    capture, task = await _accepted_task(db_path)
    service = _analysis_service(db_path)
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_canonical_evidence SET payload_json = ? WHERE reference_id = ?",
            ('{"tampered":true}', capture.records[0].reference_id),
        )

    with pytest.raises(EvidenceIdentityMismatch, match="payload fingerprint drift"):
        service.start(_request(task.task_id))

    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_research_task_analyses").fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_provider_registrations").fetchone()[0]
            == 0
        )
        assert conn.execute("SELECT COUNT(*) FROM ai_workflows").fetchone()[0] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_completed_analysis_and_memory_invalidate_when_evidence_drifts(
    tmp_path,
):
    db_path = tmp_path / "fixture-analysis.db"
    capture, task = await _accepted_task(db_path)
    service = _analysis_service(db_path)
    completed = service.start(_request(task.task_id))
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_canonical_evidence SET payload_json = ? WHERE reference_id = ?",
            ('{"tampered":true}', capture.records[-1].reference_id),
        )

    invalidated = service.get(completed.record.analysis_id)
    replay = service.replay(completed.record.analysis_id)

    assert invalidated.binding_validity == "evidence_drift"
    assert invalidated.memory_validity == "invalidated_by_evidence_drift"
    assert invalidated.to_dict()["research_output_is_account_fact"] is False
    assert replay.valid is False
    assert replay.binding_validity == "evidence_drift"
    assert any("payload fingerprint drift" in item for item in replay.errors)


@pytest.mark.unit
def test_fixture_analysis_reads_do_not_initialize_database_schema(tmp_path):
    db_path = tmp_path / "fixture-analysis-read.db"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("CREATE TABLE existing_financial_fact (id INTEGER PRIMARY KEY)")
        before = conn.execute("PRAGMA schema_version").fetchone()[0]

    store = ResearchTaskAnalysisStore(db_path)

    assert store.list() == ()
    with pytest.raises(LookupError, match="fixture analysis not found"):
        store.get("missing-analysis")
    with closing(sqlite3.connect(db_path)) as conn:
        after = conn.execute("PRAGMA schema_version").fetchone()[0]
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert after == before
    assert tables == {"existing_financial_fact"}


@pytest.mark.unit
def test_fixture_analysis_request_requires_explicit_confirmation():
    with pytest.raises(ValueError, match="explicit deterministic fixture"):
        HumanFixtureAnalysisRequest(
            task_id="task-invalid",
            idempotency_key="analysis-invalid",
            requested_by="human:reese",
            confirmation="",
        )
