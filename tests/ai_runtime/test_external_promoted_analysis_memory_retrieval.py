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
from server.ai_runtime.external_promoted_analysis_memory_retrieval import (
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_CONFIRMATION,
    ExternalPromotedAnalysisMemoryRetrievalRejected,
    ExternalPromotedAnalysisMemoryRetrievalStore,
    HumanExternalPromotedAnalysisMemoryRetrievalRequest,
    HumanExternalPromotedAnalysisMemoryRetrievalService,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from tests.ai_runtime.test_external_promoted_analysis_memory import (
    _accepted_review,
    _memory_revocation_request,
    _promotion_request,
)
from tests.ai_runtime.test_external_promoted_analysis_memory import (
    _service as _promotion_service,
)
from tests.ai_runtime.test_external_reviewed_memory_retrieval import (
    _new_current_context,
)
from tests.ai_runtime.test_memory_retrieval import _retrieval_service
from tests.ai_runtime.test_research_tasks import NOW


def _service(db_path, promotion_service, *, initialize=True):
    store = ExternalPromotedAnalysisMemoryRetrievalStore(db_path)
    if initialize:
        store.init()
    legacy_retrieval = _retrieval_service(db_path)
    return HumanExternalPromotedAnalysisMemoryRetrievalService(
        promotion_service=promotion_service,
        ai_store=AiAuditStore(db_path),
        evidence_repository=CanonicalEvidenceRepository(db_path),
        current_context_validator=legacy_retrieval._validate_current_context,
        retrieval_store=store,
        now=lambda: NOW,
    )


def _request(promotion_id: str, context_snapshot_id: str, **overrides):
    values = {
        "idempotency_key": "external-promoted-analysis-memory-retrieval-001",
        "requested_by": "human:reese",
        "purpose": "Rebind reviewed multi-role research to current evidence.",
        "current_context_snapshot_id": context_snapshot_id,
        "promotion_ids": (promotion_id,),
        "confirmation": (EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_CONFIRMATION),
    }
    values.update(overrides)
    return HumanExternalPromotedAnalysisMemoryRetrievalRequest(**values)


async def _promoted_memory(db_path):
    reviews, review, transport, _, _ = await _accepted_review(db_path)
    promotions = _promotion_service(db_path, reviews)
    promotion = promotions.promote(
        review.review.review_id,
        _promotion_request(),
    )
    evidence = CanonicalEvidenceRepository(db_path)
    source_records = tuple(
        record
        for reference_id in promotion.promotion.evidence_reference_ids
        if (record := evidence.get(reference_id)) is not None
    )
    assert len(source_records) == len(promotion.promotion.evidence_reference_ids)
    return transport, promotions, promotion, source_records


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_retrieves_exact_promoted_analysis_with_current_evidence_only(
    tmp_path,
):
    db_path = tmp_path / "external-promoted-analysis-memory-retrieval.db"
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
    current_context, current_records = _new_current_context(db_path, source_records)
    with closing(sqlite3.connect(db_path)) as conn:
        phase_1_13_columns = conn.execute(
            "PRAGMA table_info(ai_external_reviewed_memory_retrievals)"
        ).fetchall()
        phase_1_13_rows = conn.execute(
            "SELECT COUNT(*) FROM ai_external_reviewed_memory_retrievals"
        ).fetchone()[0]

    result = _service(db_path, promotions).start(
        _request(promotion.promotion.promotion_id, current_context.snapshot_id)
    )
    payload = result.to_dict()

    assert payload["schema_version"] == (
        "karkinos.ai.external_promoted_analysis_memory_retrieval.v1"
    )
    assert payload["retrieval_eligible"] is True
    assert payload["status"] == "ready_for_evidence_bound_research_context"
    assert payload["valuation_snapshot_id"] == "valuation-retrieval-013"
    assert payload["ledger_cutoff_id"] == 146
    assert payload["ledger_fingerprint"] == "ledger-retrieval-fingerprint-013"
    assert payload["selected_memory_count"] == 1
    memory = payload["selected_memories"][0]
    assert memory["source_type"] == "external_promoted_analysis_memory"
    assert memory["promotion_id"] == promotion.promotion.promotion_id
    assert memory["review_id"] == promotion.promotion.review_id
    assert memory["provider_id"] == promotion.promotion.provider_id
    assert memory["model_id"] == promotion.promotion.model_id
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
        item["current_status"] == "complete" for item in memory["evidence_rebindings"]
    )
    assert payload["automatic_recall_enabled"] is False
    assert payload["external_model_consumption_enabled"] is False
    assert payload["provider_tool_registered"] is False
    assert payload["network_io_used"] is False
    assert payload["external_model_invocation_count"] == 0
    assert payload["phase_1_8_retrieval_modified"] is False
    assert payload["phase_1_13_retrieval_modified"] is False
    assert payload["decision_handoff_enabled"] is False
    assert payload["trade_plan_created"] is False
    assert payload["authority_effect"] == "none"
    assert result.replay().valid is True
    assert len(transport.calls) == 3

    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "PRAGMA table_info(ai_external_reviewed_memory_retrievals)"
            ).fetchall()
            == phase_1_13_columns
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_reviewed_memory_retrievals"
            ).fetchone()[0]
            == phase_1_13_rows
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM "
                "ai_external_promoted_analysis_memory_retrievals"
            ).fetchone()[0]
            == 1
        )
        for table in protected_tables:
            assert conn.execute(f"SELECT marker FROM {table}").fetchone()[0] == (
                "protected"
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retrieval_is_restart_concurrency_and_request_idempotent(tmp_path):
    db_path = tmp_path / "external-promoted-analysis-memory-retrieval-idempotent.db"
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
                "SELECT COUNT(*) FROM "
                "ai_external_promoted_analysis_memory_retrievals"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM "
                "ai_external_promoted_analysis_memory_retrieval_events"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_source_revocation_and_report_drift_hide_retrieved_content(tmp_path):
    db_path = tmp_path / "external-promoted-analysis-memory-retrieval-drift.db"
    _, promotions, promotion, source_records = await _promoted_memory(db_path)
    current_context, _ = _new_current_context(db_path, source_records)
    service = _service(db_path, promotions)
    result = service.start(
        _request(promotion.promotion.promotion_id, current_context.snapshot_id)
    )

    promotions.revoke(
        promotion.promotion.promotion_id,
        _memory_revocation_request(),
    )
    revoked = service.get(result.stored.retrieval_id)
    assert revoked.retrieval_eligible is False
    assert revoked.to_dict()["selected_memories"] == []
    assert any(
        "promotion_not_retrievable" in reason for reason in revoked.invalidation_reasons
    )
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM "
                "ai_external_promoted_analysis_memory_retrievals"
            ).fetchone()[0]
            == 1
        )

    second_db = tmp_path / "external-promoted-analysis-memory-report-drift.db"
    _, second_promotions, second_promotion, second_sources = await _promoted_memory(
        second_db
    )
    second_context, _ = _new_current_context(second_db, second_sources)
    second_service = _service(second_db, second_promotions)
    second_result = second_service.start(
        _request(
            second_promotion.promotion.promotion_id,
            second_context.snapshot_id,
        )
    )
    with closing(sqlite3.connect(second_db)) as conn, conn:
        conn.execute(
            "UPDATE ai_artifacts SET content_json = ? WHERE artifact_id = ?",
            ('{"tampered":true}', second_promotion.promotion.report_artifact_id),
        )
    invalidated = second_service.get(second_result.stored.retrieval_id)
    assert invalidated.retrieval_eligible is False
    assert invalidated.to_dict()["selected_memories"] == []
    assert any(
        "promoted_analysis_memory_source_binding_drift" in reason
        for reason in invalidated.invalidation_reasons
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_partial_current_evidence_blocks_and_later_drift_invalidates(tmp_path):
    db_path = tmp_path / "external-promoted-analysis-memory-current-drift.db"
    _, promotions, promotion, source_records = await _promoted_memory(db_path)
    partial_context, _ = _new_current_context(
        db_path,
        source_records,
        status_by_tool={source_records[0].tool_name: "partial"},
    )
    service = _service(db_path, promotions)
    with pytest.raises(
        ExternalPromotedAnalysisMemoryRetrievalRejected,
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
                "SELECT COUNT(*) FROM "
                "ai_external_promoted_analysis_memory_retrievals"
            ).fetchone()[0]
            == 0
        )

    current_context, current_records = _new_current_context(db_path, source_records)
    result = service.start(
        _request(
            promotion.promotion.promotion_id,
            current_context.snapshot_id,
            idempotency_key="external-promoted-analysis-memory-retrieval-002",
        )
    )
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_canonical_evidence SET payload_json = ?, "
            "record_fingerprint = ? WHERE reference_id = ?",
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
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_duplicate_current_tool_mapping_fails_closed(tmp_path):
    db_path = tmp_path / "external-promoted-analysis-memory-duplicate-tool.db"
    _, promotions, promotion, source_records = await _promoted_memory(db_path)
    _, current_records = _new_current_context(db_path, source_records)
    first = current_records[0]
    duplicate = CanonicalEvidenceRepository(db_path).persist(
        CanonicalEvidenceRecord.capture(
            tool_name=first.tool_name,
            valuation_snapshot_id=first.valuation_snapshot_id,
            ledger_cutoff_id=first.ledger_cutoff_id,
            ledger_fingerprint=first.ledger_fingerprint,
            status="complete",
            as_of=first.as_of,
            source_schema_version=first.source_schema_version,
            payload={
                "fixture": "phase-1.17-ambiguous-current-tool",
                "tool_name": first.tool_name,
                "persisted_facts_only": True,
            },
            captured_at="2026-07-14T02:01:30+00:00",
        )
    )
    ambiguous_context = EvidenceContextBuilder().build(
        account_alias="primary",
        records=(*current_records, duplicate),
        created_at="2026-07-14T02:03:00+00:00",
    )
    AiAuditStore(db_path).save_context(ambiguous_context)
    service = _service(db_path, promotions)

    with pytest.raises(
        ExternalPromotedAnalysisMemoryRetrievalRejected,
        match="ambiguous duplicate canonical tools",
    ):
        service.start(
            _request(
                promotion.promotion.promotion_id,
                ambiguous_context.snapshot_id,
            )
        )
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM "
                "ai_external_promoted_analysis_memory_retrievals"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_audit_drift_invalidates_replay(tmp_path):
    db_path = tmp_path / "external-promoted-analysis-memory-retrieval-audit.db"
    _, promotions, promotion, source_records = await _promoted_memory(db_path)
    current_context, _ = _new_current_context(db_path, source_records)
    service = _service(db_path, promotions)
    result = service.start(
        _request(promotion.promotion.promotion_id, current_context.snapshot_id)
    )
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_external_promoted_analysis_memory_retrieval_events "
            "SET event_hash = ? WHERE retrieval_id = ?",
            ("tampered", result.stored.retrieval_id),
        )

    invalidated = service.get(result.stored.retrieval_id)
    replay = invalidated.replay()
    assert invalidated.retrieval_eligible is False
    assert invalidated.to_dict()["selected_memories"] == []
    assert replay.valid is False
    assert replay.event_chain_valid is False
    assert "promoted-analysis memory retrieval event hash drifted" in replay.errors


@pytest.mark.unit
def test_reads_are_lazy_and_request_confirmation_is_exact(tmp_path):
    db_path = tmp_path / "external-promoted-analysis-memory-retrieval-read.db"
    store = ExternalPromotedAnalysisMemoryRetrievalStore(db_path)

    assert store.list() == ()
    assert store.get_by_idempotency_key("missing") is None
    with pytest.raises(LookupError, match="not found"):
        store.get("ai-external-promoted-analysis-memory-retrieval-missing")
    with closing(sqlite3.connect(db_path)) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "ai_external_promoted_analysis_memory_retrievals" not in tables

    with pytest.raises(ValueError, match="explicit promoted-analysis memory"):
        _request("promotion", "context", confirmation="wrong")
    with pytest.raises(ValueError, match="must be unique"):
        HumanExternalPromotedAnalysisMemoryRetrievalRequest(
            idempotency_key="duplicate",
            requested_by="human:test",
            purpose="Reject duplicate promotion ids.",
            current_context_snapshot_id="context",
            promotion_ids=("promotion", "promotion"),
            confirmation=(EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_CONFIRMATION),
        )
