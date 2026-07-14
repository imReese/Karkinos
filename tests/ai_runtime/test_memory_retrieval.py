from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from server.ai_runtime.analysis_reviews import AnalysisReviewDecision
from server.ai_runtime.evidence import (
    CanonicalEvidenceRecord,
    CanonicalEvidenceRepository,
    EvidenceContextBuilder,
)
from server.ai_runtime.memory_retrieval import (
    REVIEWED_MEMORY_RETRIEVAL_CONFIRMATION,
    HumanReviewedMemoryRetrievalRequest,
    HumanReviewedMemoryRetrievalService,
    ReviewedMemoryRetrievalRejected,
    ReviewedMemoryRetrievalStore,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from tests.ai_runtime.test_analysis_reviews import (
    _review_request,
    _review_service,
)
from tests.ai_runtime.test_research_tasks import NOW
from tests.ai_runtime.test_task_fixture_analysis import (
    _accepted_task,
    _analysis_service,
)
from tests.ai_runtime.test_task_fixture_analysis import _request as _analysis_request


def _retrieval_service(db_path):
    store = ReviewedMemoryRetrievalStore(db_path)
    store.init()
    return HumanReviewedMemoryRetrievalService(
        review_service=_review_service(db_path),
        analysis_service=_analysis_service(db_path),
        ai_store=AiAuditStore(db_path),
        evidence_repository=CanonicalEvidenceRepository(db_path),
        retrieval_store=store,
        now=lambda: NOW,
    )


def _retrieval_request(review_id: str, context_snapshot_id: str, **overrides):
    values = {
        "idempotency_key": "reviewed-memory-retrieval-001",
        "requested_by": "human:reese",
        "purpose": "Compare a reviewed research precedent with current evidence.",
        "current_context_snapshot_id": context_snapshot_id,
        "review_ids": (review_id,),
        "confirmation": REVIEWED_MEMORY_RETRIEVAL_CONFIRMATION,
    }
    values.update(overrides)
    return HumanReviewedMemoryRetrievalRequest(**values)


def _new_current_context(db_path, source_records, *, status_by_tool=None):
    evidence = CanonicalEvidenceRepository(db_path)
    context_store = AiAuditStore(db_path)
    status_by_tool = status_by_tool or {}
    records = tuple(
        evidence.persist(
            CanonicalEvidenceRecord.capture(
                tool_name=source.tool_name,
                valuation_snapshot_id="valuation-current-002",
                ledger_cutoff_id=145,
                ledger_fingerprint="ledger-current-fingerprint-002",
                status=status_by_tool.get(source.tool_name, "complete"),
                as_of="2026-07-14T01:00:00+00:00",
                source_schema_version=source.source_schema_version,
                payload={
                    "fixture": "current",
                    "tool_name": source.tool_name,
                    "persisted_facts_only": True,
                },
                captured_at="2026-07-14T01:01:00+00:00",
            )
        )
        for source in source_records
    )
    context = EvidenceContextBuilder().build(
        account_alias="primary",
        records=records,
        created_at="2026-07-14T01:02:00+00:00",
    )
    context_store.save_context(context)
    return context, records


async def _reviewed_memory(db_path):
    capture, task = await _accepted_task(db_path)
    analysis = _analysis_service(db_path).start(_analysis_request(task.task_id))
    review = _review_service(db_path).review(
        analysis.record.analysis_id,
        _review_request(),
    )
    return capture, analysis, review


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_explicit_retrieval_rebinds_reviewed_memory_without_authority(
    tmp_path,
):
    db_path = tmp_path / "memory-retrieval.db"
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

    capture, _, review = await _reviewed_memory(db_path)
    current_context, current_records = _new_current_context(
        db_path,
        capture.records,
    )
    result = _retrieval_service(db_path).start(
        _retrieval_request(review.review.review_id, current_context.snapshot_id)
    )
    payload = result.to_dict()

    assert payload["retrieval_eligible"] is True
    assert payload["status"] == "ready_for_evidence_bound_research_context"
    assert payload["valuation_snapshot_id"] == "valuation-current-002"
    assert payload["ledger_cutoff_id"] == 145
    assert payload["selected_memory_count"] == 1
    memory = payload["selected_memories"][0]
    assert memory["memory_role"] == "historical_reviewed_research_input"
    assert memory["memory_is_current_fact"] is False
    assert memory["current_evidence_must_be_read"] is True
    assert {item["source_reference_id"] for item in memory["evidence_rebindings"]} == {
        item.reference_id for item in capture.records
    }
    assert {item["current_reference_id"] for item in memory["evidence_rebindings"]} == {
        item.reference_id for item in current_records
    }
    assert all(
        item["same_evidence_identity"] is False
        for item in memory["evidence_rebindings"]
    )
    assert payload["automatic_recall_enabled"] is False
    assert payload["provider_tool_registered"] is False
    assert payload["external_model_invocation_count"] == 0
    assert payload["decision_handoff_enabled"] is False
    assert payload["authority_effect"] == "none"
    assert result.replay().valid is True

    with closing(sqlite3.connect(db_path)) as conn:
        for table in protected_tables:
            assert conn.execute(f"SELECT marker FROM {table}").fetchone()[0] == (
                "protected"
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retrieval_is_restart_idempotent_and_concurrent_safe(tmp_path):
    db_path = tmp_path / "memory-retrieval-concurrent.db"
    capture, _, review = await _reviewed_memory(db_path)
    request = _retrieval_request(
        review.review.review_id,
        capture.context.snapshot_id,
    )

    def start():
        return _retrieval_service(db_path).start(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: start(), range(2)))

    assert sorted(item.reused for item in results) == [False, True]
    assert results[0].stored == results[1].stored
    restarted = _retrieval_service(db_path).start(request)
    assert restarted.reused is True
    assert restarted.retrieval_eligible is True
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_reviewed_memory_retrievals"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_reviewed_memory_retrieval_events"
            ).fetchone()[0]
            == 1
        )

    with pytest.raises(IdempotencyConflict, match="different input"):
        _retrieval_service(db_path).start(
            _retrieval_request(
                review.review.review_id,
                capture.context.snapshot_id,
                purpose="A different purpose must not reuse the key.",
            )
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_only_current_reviewed_memory_is_retrievable(tmp_path):
    db_path = tmp_path / "memory-retrieval-review-gate.db"
    capture, task = await _accepted_task(db_path)
    analysis = _analysis_service(db_path).start(_analysis_request(task.task_id))
    revision = _review_service(db_path).review(
        analysis.record.analysis_id,
        _review_request(
            decision=AnalysisReviewDecision.REQUEST_REVISION,
            note="Evidence is insufficient for reviewed memory.",
        ),
    )

    with pytest.raises(
        ReviewedMemoryRetrievalRejected,
        match="effective_status:revision_requested",
    ):
        _retrieval_service(db_path).start(
            _retrieval_request(
                revision.review.review_id,
                capture.context.snapshot_id,
            )
        )

    with pytest.raises(ValueError, match="review_ids must be unique"):
        _retrieval_request(
            revision.review.review_id,
            capture.context.snapshot_id,
            review_ids=(revision.review.review_id, revision.review.review_id),
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_current_evidence_drift_invalidates_and_hides_memory(tmp_path):
    db_path = tmp_path / "memory-retrieval-drift.db"
    capture, _, review = await _reviewed_memory(db_path)
    current_context, current_records = _new_current_context(
        db_path,
        capture.records,
    )
    service = _retrieval_service(db_path)
    retrieved = service.start(
        _retrieval_request(review.review.review_id, current_context.snapshot_id)
    )
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_canonical_evidence SET payload_json = ? "
            "WHERE reference_id = ?",
            ('{"tampered":true}', current_records[0].reference_id),
        )

    invalidated = service.get(retrieved.stored.retrieval_id)
    payload = invalidated.to_dict()

    assert invalidated.retrieval_eligible is False
    assert payload["status"] == "invalidated"
    assert payload["selected_memories"] == []
    assert payload["selected_memory_count"] == 0
    assert "retrieval_target_fingerprint_drift" in payload["invalidation_reasons"]
    assert any(
        reason.startswith("current_context_invalid:")
        for reason in payload["invalidation_reasons"]
    )
    assert invalidated.replay().valid is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_partial_current_evidence_blocks_before_audit_write(tmp_path):
    db_path = tmp_path / "memory-retrieval-partial.db"
    capture, _, review = await _reviewed_memory(db_path)
    partial_tool = capture.records[0].tool_name
    current_context, _ = _new_current_context(
        db_path,
        capture.records,
        status_by_tool={partial_tool: "partial"},
    )

    with pytest.raises(
        ReviewedMemoryRetrievalRejected,
        match="current evidence is not complete",
    ):
        _retrieval_service(db_path).start(
            _retrieval_request(
                review.review.review_id,
                current_context.snapshot_id,
            )
        )

    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_reviewed_memory_retrievals"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retrieval_audit_drift_hides_memory(tmp_path):
    db_path = tmp_path / "memory-retrieval-audit-drift.db"
    capture, _, review = await _reviewed_memory(db_path)
    service = _retrieval_service(db_path)
    retrieved = service.start(
        _retrieval_request(
            review.review.review_id,
            capture.context.snapshot_id,
        )
    )
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_reviewed_memory_retrieval_events SET event_hash = ? "
            "WHERE retrieval_id = ?",
            ("tampered", retrieved.stored.retrieval_id),
        )

    invalidated = service.get(retrieved.stored.retrieval_id)

    assert invalidated.retrieval_eligible is False
    assert invalidated.to_dict()["selected_memories"] == []
    assert "retrieval audit event hash drifted" in invalidated.invalidation_reasons
    assert invalidated.replay().event_chain_valid is False


@pytest.mark.unit
def test_retrieval_read_store_does_not_initialize_schema(tmp_path):
    db_path = tmp_path / "memory-retrieval-read.db"
    store = ReviewedMemoryRetrievalStore(db_path)

    assert store.list() == ()
    with pytest.raises(LookupError, match="not found"):
        store.get("ai-memory-retrieval-missing")

    with closing(sqlite3.connect(db_path)) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "ai_reviewed_memory_retrievals" not in tables
