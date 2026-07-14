from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from server.ai_runtime.evidence import (
    CanonicalEvidenceRecord,
    CanonicalEvidenceRepository,
    EvidenceContextBuilder,
)
from server.ai_runtime.external_reviewed_memory_retrieval import (
    EXTERNAL_REVIEWED_MEMORY_RETRIEVAL_CONFIRMATION,
    ExternalReviewedMemoryRetrievalRejected,
    ExternalReviewedMemoryRetrievalStore,
    HumanExternalReviewedMemoryRetrievalRequest,
    HumanExternalReviewedMemoryRetrievalService,
)
from server.ai_runtime.memory_retrieval import (
    REVIEWED_MEMORY_RETRIEVAL_CONFIRMATION,
    HumanReviewedMemoryRetrievalRequest,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from tests.ai_runtime.test_external_reviewed_memory import (
    _promotion_request,
    _reviewed_analysis,
    _revocation_request,
)
from tests.ai_runtime.test_external_reviewed_memory import (
    _service as _promotion_service,
)
from tests.ai_runtime.test_memory_retrieval import _retrieval_service
from tests.ai_runtime.test_research_tasks import NOW


def _service(db_path, promotion_service, *, initialize=True):
    store = ExternalReviewedMemoryRetrievalStore(db_path)
    if initialize:
        store.init()
    legacy_retrieval = _retrieval_service(db_path)
    return HumanExternalReviewedMemoryRetrievalService(
        promotion_service=promotion_service,
        ai_store=AiAuditStore(db_path),
        evidence_repository=CanonicalEvidenceRepository(db_path),
        current_context_validator=legacy_retrieval._validate_current_context,
        retrieval_store=store,
        now=lambda: NOW,
    )


def _request(promotion_id: str, context_snapshot_id: str, **overrides):
    values = {
        "idempotency_key": "external-reviewed-memory-retrieval-001",
        "requested_by": "human:reese",
        "purpose": "Rebind one promoted research precedent to current evidence.",
        "current_context_snapshot_id": context_snapshot_id,
        "promotion_ids": (promotion_id,),
        "confirmation": EXTERNAL_REVIEWED_MEMORY_RETRIEVAL_CONFIRMATION,
    }
    values.update(overrides)
    return HumanExternalReviewedMemoryRetrievalRequest(**values)


def _new_current_context(db_path, source_records, *, status_by_tool=None):
    evidence = CanonicalEvidenceRepository(db_path)
    context_store = AiAuditStore(db_path)
    status_by_tool = status_by_tool or {}
    records = tuple(
        evidence.persist(
            CanonicalEvidenceRecord.capture(
                tool_name=source.tool_name,
                valuation_snapshot_id="valuation-retrieval-013",
                ledger_cutoff_id=146,
                ledger_fingerprint="ledger-retrieval-fingerprint-013",
                status=status_by_tool.get(source.tool_name, "complete"),
                as_of="2026-07-14T02:00:00+00:00",
                source_schema_version=source.source_schema_version,
                payload={
                    "fixture": "phase-1.13-current",
                    "tool_name": source.tool_name,
                    "persisted_facts_only": True,
                },
                captured_at="2026-07-14T02:01:00+00:00",
            )
        )
        for source in source_records
    )
    context = EvidenceContextBuilder().build(
        account_alias="primary",
        records=records,
        created_at="2026-07-14T02:02:00+00:00",
    )
    context_store.save_context(context)
    return context, records


async def _promoted_memory(db_path):
    _, transport, reviews, review = await _reviewed_analysis(db_path)
    promotions = _promotion_service(db_path, reviews)
    promotion = promotions.promote(
        review.review.review_id,
        _promotion_request(),
    )
    source_records = tuple(
        record
        for reference_id in promotion.promotion.evidence_reference_ids
        if (record := CanonicalEvidenceRepository(db_path).get(reference_id))
        is not None
    )
    assert len(source_records) == len(promotion.promotion.evidence_reference_ids)
    return transport, promotions, promotion, source_records


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_retrieves_promoted_memory_with_current_evidence_without_authority(
    tmp_path,
):
    db_path = tmp_path / "external-reviewed-memory-retrieval.db"
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

    transport, promotions, promotion, source_records = await _promoted_memory(db_path)
    current_context, current_records = _new_current_context(
        db_path,
        source_records,
    )
    result = _service(db_path, promotions).start(
        _request(promotion.promotion.promotion_id, current_context.snapshot_id)
    )
    payload = result.to_dict()

    assert payload["retrieval_eligible"] is True
    assert payload["status"] == "ready_for_evidence_bound_research_context"
    assert payload["valuation_snapshot_id"] == "valuation-retrieval-013"
    assert payload["ledger_cutoff_id"] == 146
    assert payload["selected_memory_count"] == 1
    memory = payload["selected_memories"][0]
    assert memory["source_type"] == "external_reviewed_memory_promotion"
    assert memory["promotion_id"] == promotion.promotion.promotion_id
    assert memory["memory_role"] == "historical_reviewed_research_input"
    assert memory["memory_is_current_fact"] is False
    assert memory["current_evidence_must_be_read"] is True
    assert {item["source_reference_id"] for item in memory["evidence_rebindings"]} == {
        item.reference_id for item in source_records
    }
    assert {item["current_reference_id"] for item in memory["evidence_rebindings"]} == {
        item.reference_id for item in current_records
    }
    assert all(
        item["same_evidence_identity"] is False
        for item in memory["evidence_rebindings"]
    )
    assert payload["automatic_recall_enabled"] is False
    assert payload["external_model_consumption_enabled"] is False
    assert payload["external_model_invocation_count"] == 0
    assert payload["decision_handoff_enabled"] is False
    assert payload["authority_effect"] == "none"
    assert result.replay().valid is True
    assert len(transport.calls) == 3

    with closing(sqlite3.connect(db_path)) as conn:
        for table in protected_tables:
            assert conn.execute(f"SELECT marker FROM {table}").fetchone()[0] == (
                "protected"
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retrieval_is_restart_concurrency_and_request_idempotent(tmp_path):
    db_path = tmp_path / "external-reviewed-memory-retrieval-idempotent.db"
    transport, promotions, promotion, source_records = await _promoted_memory(db_path)
    current_context, _ = _new_current_context(db_path, source_records)
    request = _request(promotion.promotion.promotion_id, current_context.snapshot_id)

    def retrieve():
        return _service(db_path, promotions).start(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: retrieve(), range(2)))

    assert sorted(item.reused for item in results) == [False, True]
    assert results[0].stored == results[1].stored
    restarted = _service(
        db_path,
        promotions,
        initialize=False,
    ).start(request)
    assert restarted.reused is True
    assert restarted.retrieval_eligible is True
    assert len(transport.calls) == 3

    with pytest.raises(IdempotencyConflict, match="different input"):
        _service(db_path, promotions).start(
            _request(
                promotion.promotion.promotion_id,
                current_context.snapshot_id,
                purpose="A reused key cannot change the purpose.",
            )
        )

    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_reviewed_memory_retrievals"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_reviewed_memory_retrieval_events"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_revocation_hides_retrieved_memory(tmp_path):
    db_path = tmp_path / "external-reviewed-memory-retrieval-revoked.db"
    _, promotions, promotion, source_records = await _promoted_memory(db_path)
    current_context, _ = _new_current_context(db_path, source_records)
    service = _service(db_path, promotions)
    result = service.start(
        _request(promotion.promotion.promotion_id, current_context.snapshot_id)
    )

    promotions.revoke(promotion.promotion.promotion_id, _revocation_request())
    revoked = service.get(result.stored.retrieval_id)
    assert revoked.retrieval_eligible is False
    assert revoked.to_dict()["selected_memories"] == []
    assert any(
        "promotion_not_retrievable" in reason for reason in revoked.invalidation_reasons
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_source_report_drift_hides_retrieved_memory(tmp_path):
    db_path = tmp_path / "external-reviewed-memory-retrieval-report-drift.db"
    _, promotions, promotion, source_records = await _promoted_memory(db_path)
    current_context, _ = _new_current_context(db_path, source_records)
    service = _service(db_path, promotions)
    result = service.start(
        _request(promotion.promotion.promotion_id, current_context.snapshot_id)
    )
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_artifacts SET content_json = ? WHERE artifact_id = ?",
            ('{"tampered":true}', promotion.promotion.report_artifact_id),
        )

    invalidated = service.get(result.stored.retrieval_id)
    assert invalidated.retrieval_eligible is False
    assert invalidated.to_dict()["selected_memories"] == []
    assert any(
        "memory_promotion_source_binding_drift" in reason
        for reason in invalidated.invalidation_reasons
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_current_evidence_partial_or_drift_fails_closed(tmp_path):
    db_path = tmp_path / "external-reviewed-memory-retrieval-current-drift.db"
    _, promotions, promotion, source_records = await _promoted_memory(db_path)
    partial_context, _ = _new_current_context(
        db_path,
        source_records,
        status_by_tool={source_records[0].tool_name: "partial"},
    )
    service = _service(db_path, promotions)
    with pytest.raises(
        ExternalReviewedMemoryRetrievalRejected,
        match="current evidence is not complete",
    ):
        service.start(
            _request(
                promotion.promotion.promotion_id,
                partial_context.snapshot_id,
            )
        )
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_reviewed_memory_retrievals"
            ).fetchone()[0]
            == 0
        )

    current_context, current_records = _new_current_context(db_path, source_records)
    result = service.start(
        _request(
            promotion.promotion.promotion_id,
            current_context.snapshot_id,
            idempotency_key="external-reviewed-memory-retrieval-002",
        )
    )
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_canonical_evidence SET payload_json = ?, "
            "record_fingerprint = ? "
            "WHERE reference_id = ?",
            (
                '{"tampered":true}',
                "tampered-current-evidence-fingerprint",
                current_records[0].reference_id,
            ),
        )
    invalidated = service.get(result.stored.retrieval_id)
    assert invalidated.retrieval_eligible is False
    assert invalidated.to_dict()["selected_memories"] == []
    assert any(
        "canonical evidence payload fingerprint drift" in reason
        for reason in invalidated.invalidation_reasons
    ), invalidated.invalidation_reasons


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retrieval_audit_drift_invalidates_replay(tmp_path):
    db_path = tmp_path / "external-reviewed-memory-retrieval-audit.db"
    _, promotions, promotion, source_records = await _promoted_memory(db_path)
    current_context, _ = _new_current_context(db_path, source_records)
    service = _service(db_path, promotions)
    result = service.start(
        _request(promotion.promotion.promotion_id, current_context.snapshot_id)
    )
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_external_reviewed_memory_retrieval_events "
            "SET event_hash = ? WHERE retrieval_id = ?",
            ("tampered", result.stored.retrieval_id),
        )

    invalidated = service.get(result.stored.retrieval_id)
    assert invalidated.retrieval_eligible is False
    assert invalidated.to_dict()["selected_memories"] == []
    replay = invalidated.replay()
    assert replay.valid is False
    assert replay.event_chain_valid is False
    assert "external memory retrieval event hash drifted" in replay.errors


@pytest.mark.unit
def test_external_reviewed_memory_retrieval_reads_do_not_initialize_schema(
    tmp_path,
):
    db_path = tmp_path / "external-reviewed-memory-retrieval-read.db"
    store = ExternalReviewedMemoryRetrievalStore(db_path)

    assert store.list() == ()
    with pytest.raises(LookupError, match="not found"):
        store.get("ai-external-memory-retrieval-missing")

    with closing(sqlite3.connect(db_path)) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "ai_external_reviewed_memory_retrievals" not in tables


@pytest.mark.unit
def test_legacy_reviewed_memory_request_v1_fingerprint_is_unchanged():
    request = HumanReviewedMemoryRetrievalRequest(
        idempotency_key="v1-regression",
        requested_by="human:test",
        purpose="preserve v1",
        current_context_snapshot_id="ai-context-example",
        review_ids=("ai-review-example",),
        confirmation=REVIEWED_MEMORY_RETRIEVAL_CONFIRMATION,
    )

    assert request.fingerprint == (
        "1a5e64e7720569004fa1c0ad4e8a0ed84475317c05634abff17a17e21a58e41c"
    )
    assert set(request.to_dict()) == {
        "idempotency_key",
        "requested_by",
        "purpose",
        "current_context_snapshot_id",
        "review_ids",
        "confirmation",
        "schema_version",
    }
