from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from server.ai_runtime.evidence import CanonicalEvidenceRepository
from server.ai_runtime.memory_informed_analysis import (
    MEMORY_INFORMED_ANALYSIS_CONFIRMATION,
    MEMORY_INFORMED_MODEL_ID,
    MEMORY_INFORMED_PROVIDER_ID,
    HumanMemoryInformedAnalysisRequest,
    HumanMemoryInformedFixtureAnalysisService,
    MemoryInformedAnalysisStore,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from tests.ai_runtime.test_memory_retrieval import (
    _new_current_context,
    _retrieval_request,
    _retrieval_service,
    _reviewed_memory,
)
from tests.ai_runtime.test_research_tasks import NOW


def _service(
    db_path,
    *,
    fixture_failures=None,
    partial_stage_id=None,
):
    store = MemoryInformedAnalysisStore(db_path)
    store.init()
    return HumanMemoryInformedFixtureAnalysisService(
        retrieval_service=_retrieval_service(db_path),
        ai_store=AiAuditStore(db_path),
        evidence_repository=CanonicalEvidenceRepository(db_path),
        analysis_store=store,
        now=lambda: NOW,
        fixture_failures=fixture_failures,
        partial_stage_id=partial_stage_id,
    )


def _request(retrieval_id: str, **overrides):
    values = {
        "retrieval_id": retrieval_id,
        "idempotency_key": "memory-informed-analysis-001",
        "requested_by": "human:reese",
        "research_question": (
            "Which historical assumptions require re-evaluation against current "
            "persisted evidence?"
        ),
        "confirmation": MEMORY_INFORMED_ANALYSIS_CONFIRMATION,
    }
    values.update(overrides)
    return HumanMemoryInformedAnalysisRequest(**values)


async def _prepared_retrieval(db_path):
    capture, _, review = await _reviewed_memory(db_path)
    context, current_records = _new_current_context(db_path, capture.records)
    retrieval = _retrieval_service(db_path).start(
        _retrieval_request(review.review.review_id, context.snapshot_id)
    )
    return retrieval, context, current_records


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_memory_informed_fixture_rereads_current_evidence_without_authority(
    tmp_path,
):
    db_path = tmp_path / "memory-informed.db"
    protected_tables = (
        "oms_orders",
        "ledger_entries",
        "risk_decisions",
        "runtime_controls",
        "capital_authorizations",
        "decision_handoffs",
    )
    with closing(sqlite3.connect(db_path)) as conn, conn:
        for table in protected_tables:
            conn.execute(
                f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, marker TEXT NOT NULL)"
            )
            conn.execute(f"INSERT INTO {table} (marker) VALUES ('protected')")

    retrieval, context, current_records = await _prepared_retrieval(db_path)
    result = _service(db_path).start(_request(retrieval.stored.retrieval_id))
    payload = result.to_dict()

    assert payload["workflow_status"] == "completed"
    assert payload["binding_validity"] == "valid"
    assert payload["context_snapshot_id"] == context.snapshot_id
    assert payload["valuation_snapshot_id"] == "valuation-current-002"
    assert payload["current_evidence_reads_complete"] is True
    assert payload["expected_current_evidence_count"] == len(current_records)
    assert payload["current_evidence_read_count"] == len(current_records)
    assert [item["kind"] for item in payload["artifacts"]] == [
        "claim",
        "debate",
        "report",
    ]
    assert all(
        set(item["evidence_reference_ids"])
        == {record.reference_id for record in current_records}
        for item in payload["artifacts"]
    )
    claim = payload["artifacts"][0]["content"]
    assert claim["memory_input_is_current_fact"] is False
    assert claim["current_evidence_must_be_read"] is True
    assert len(claim["memory_inputs"]) == 1
    assert claim["memory_inputs"][0]["role"] == ("historical_reviewed_research_input")
    assert claim["memory_inputs"][0]["is_current_fact"] is False
    assert all(item["status"] == "completed" for item in payload["tool_calls"])
    assert all(
        item["stage_id"] == "current_evidence_claim" for item in payload["tool_calls"]
    )
    assert payload["provider_id"] == MEMORY_INFORMED_PROVIDER_ID
    assert payload["model_id"] == MEMORY_INFORMED_MODEL_ID
    assert payload["fixture_stage_run_count"] == 3
    assert payload["network_io_used"] is False
    assert payload["external_model_invocation_count"] == 0
    assert payload["retrieval_tool_registered"] is False
    assert payload["automatic_recall_enabled"] is False
    assert payload["memory_artifact_created"] is False
    assert payload["decision_handoff_enabled"] is False
    assert payload["trade_plan_created"] is False
    assert payload["authority_effect"] == "none"
    assert result.replay().valid is True

    with closing(sqlite3.connect(db_path)) as conn:
        for table in protected_tables:
            assert conn.execute(f"SELECT marker FROM {table}").fetchone()[0] == (
                "protected"
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_informed_analysis_is_restart_and_concurrency_idempotent(
    tmp_path,
):
    db_path = tmp_path / "memory-informed-concurrent.db"
    retrieval, _, _ = await _prepared_retrieval(db_path)
    request = _request(retrieval.stored.retrieval_id)

    def start():
        return _service(db_path).start(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: start(), range(2)))

    assert results[0].record.analysis_id == results[1].record.analysis_id
    assert sorted(item.reused for item in results) == [False, True]
    completed = _service(db_path).start(request)
    assert completed.reused is True
    assert completed.workflow.status.value == "completed"
    assert completed.replay().valid is True
    ai_store = AiAuditStore(db_path)
    assert len(ai_store.list_agent_runs(completed.workflow.workflow_id)) == 3
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_memory_informed_fixture_analyses"
            ).fetchone()[0]
            == 1
        )

    with pytest.raises(IdempotencyConflict, match="different input"):
        _service(db_path).start(
            _request(
                retrieval.stored.retrieval_id,
                research_question="A changed question must not reuse the key.",
            )
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fixture_stage_failure_is_terminal_and_not_retried(tmp_path):
    db_path = tmp_path / "memory-informed-failure.db"
    retrieval, _, current_records = await _prepared_retrieval(db_path)
    request = _request(retrieval.stored.retrieval_id)
    failed = _service(
        db_path,
        fixture_failures={
            ("current_evidence_claim", 1): RuntimeError("fixture failure")
        },
    ).start(request)

    assert failed.workflow.status.value == "failed"
    assert failed.workflow.failure_code == "runtime"
    assert failed.artifacts == ()
    assert len(failed.tool_calls) == len(current_records)
    assert failed.current_evidence_reads_complete is True
    assert failed.replay().valid is False

    exact_retry = _service(db_path).start(request)
    assert exact_retry.reused is True
    assert exact_retry.workflow.status.value == "failed"
    assert exact_retry.fixture_stage_run_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_partial_stage_is_explicit_and_does_not_create_report(tmp_path):
    db_path = tmp_path / "memory-informed-partial.db"
    retrieval, _, _ = await _prepared_retrieval(db_path)
    result = _service(
        db_path,
        partial_stage_id="memory_evidence_debate",
    ).start(_request(retrieval.stored.retrieval_id))

    assert result.workflow.status.value == "partial"
    assert result.workflow.partial_result is True
    assert [item.kind.value for item in result.artifacts] == ["claim", "debate"]
    assert result.current_evidence_reads_complete is True
    assert result.replay().valid is False
    assert "workflow_not_completed:partial" in result.replay().errors


@pytest.mark.unit
@pytest.mark.asyncio
async def test_later_current_evidence_drift_invalidates_without_deleting_history(
    tmp_path,
):
    db_path = tmp_path / "memory-informed-drift.db"
    retrieval, _, current_records = await _prepared_retrieval(db_path)
    service = _service(db_path)
    completed = service.start(_request(retrieval.stored.retrieval_id))
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_canonical_evidence SET payload_json = ? "
            "WHERE reference_id = ?",
            ('{"tampered":true}', current_records[0].reference_id),
        )

    invalidated = service.get(completed.record.analysis_id)

    assert invalidated.workflow.status.value == "completed"
    assert invalidated.binding_validity == "invalidated_by_drift"
    assert invalidated.replay().valid is False
    assert "retrieval_or_current_evidence_invalid" in invalidated.binding_errors
    assert len(invalidated.artifacts) == 3
    assert invalidated.to_dict()["research_output_is_account_fact"] is False

    exact_retry = _service(db_path).start(_request(retrieval.stored.retrieval_id))
    assert exact_retry.reused is True
    assert exact_retry.binding_validity == "invalidated_by_drift"
    assert len(exact_retry.artifacts) == 3


@pytest.mark.unit
def test_memory_informed_request_and_store_fail_closed_without_schema(tmp_path):
    with pytest.raises(ValueError, match="explicit offline"):
        _request("retrieval-1", confirmation="wrong")
    with pytest.raises(ValueError, match="partial_stage_id"):
        HumanMemoryInformedFixtureAnalysisService(
            retrieval_service=object(),
            ai_store=object(),
            evidence_repository=object(),
            analysis_store=object(),
            now=lambda: NOW,
            partial_stage_id="unknown",
        )

    db_path = tmp_path / "memory-informed-read.db"
    store = MemoryInformedAnalysisStore(db_path)
    assert store.list() == ()
    with pytest.raises(LookupError, match="not found"):
        store.get("ai-memory-analysis-missing")
    with closing(sqlite3.connect(db_path)) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "ai_memory_informed_fixture_analyses" not in tables
