from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from server.ai_runtime.external_analysis_reviews import ExternalAnalysisReviewDecision
from server.ai_runtime.external_promoted_analysis_memory import (
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_PROMOTION_CONFIRMATION,
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REVOCATION_CONFIRMATION,
    ExternalPromotedAnalysisMemoryPromotionRequest,
    ExternalPromotedAnalysisMemoryPromotionService,
    ExternalPromotedAnalysisMemoryRejected,
    ExternalPromotedAnalysisMemoryRevocationRequest,
    ExternalPromotedAnalysisMemoryStore,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from tests.ai_runtime.test_external_promoted_memory_analysis_reviews import (
    _completed_analysis,
)
from tests.ai_runtime.test_external_promoted_memory_analysis_reviews import (
    _request as _review_request,
)
from tests.ai_runtime.test_external_promoted_memory_analysis_reviews import (
    _service as _review_service,
)
from tests.ai_runtime.test_external_reviewed_memory import _revocation_request
from tests.ai_runtime.test_research_tasks import NOW


def _service(db_path, reviews, *, initialize=True):
    store = ExternalPromotedAnalysisMemoryStore(db_path)
    if initialize:
        store.init()
    return ExternalPromotedAnalysisMemoryPromotionService(
        review_service=reviews,
        ai_store=AiAuditStore(db_path),
        promotion_store=store,
        now=lambda: NOW,
    )


def _promotion_request(**overrides):
    values = {
        "idempotency_key": "external-promoted-analysis-memory-promotion-001",
        "promoted_by": "human:reese",
        "rationale": "保留已复核分析及其完整来源链，供未来显式重绑定复核。",
        "confirmation": (EXTERNAL_PROMOTED_ANALYSIS_MEMORY_PROMOTION_CONFIRMATION),
    }
    values.update(overrides)
    return ExternalPromotedAnalysisMemoryPromotionRequest(**values)


def _memory_revocation_request(**overrides):
    values = {
        "idempotency_key": "external-promoted-analysis-memory-revocation-001",
        "revoked_by": "human:reese",
        "reason": "撤销未来召回资格，但保留历史复核和来源证据。",
        "confirmation": (EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REVOCATION_CONFIRMATION),
    }
    values.update(overrides)
    return ExternalPromotedAnalysisMemoryRevocationRequest(**values)


async def _accepted_review(db_path):
    analyses, analysis, transport, source_promotions, source_promotion = (
        await _completed_analysis(db_path)
    )
    reviews = _review_service(db_path, analyses)
    review = reviews.review(
        analysis.analysis.record.analysis_id,
        _review_request(),
    )
    assert review.reviewed_research_eligible is True
    return (
        reviews,
        review,
        transport,
        source_promotions,
        source_promotion,
    )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_promotes_exact_reviewed_analysis_without_authority_or_legacy_mutation(
    tmp_path,
):
    db_path = tmp_path / "external-promoted-analysis-memory.db"
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

    reviews, review, transport, _, source_promotion = await _accepted_review(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        legacy_columns = conn.execute(
            "PRAGMA table_info(ai_external_reviewed_memory_promotions)"
        ).fetchall()
        legacy_rows = conn.execute(
            "SELECT COUNT(*) FROM ai_external_reviewed_memory_promotions"
        ).fetchone()[0]
        artifact_rows = conn.execute("SELECT COUNT(*) FROM ai_artifacts").fetchone()[0]

    promoted = _service(db_path, reviews).promote(
        review.review.review_id,
        _promotion_request(),
    )
    payload = promoted.to_dict()

    assert payload["schema_version"] == (
        "karkinos.ai.external_promoted_analysis_memory_promotion.v1"
    )
    assert payload["effective_status"] == "recall_eligible"
    assert payload["promotion_binding_valid"] is True
    assert payload["source_binding_valid"] is True
    assert payload["memory_artifact_binding_valid"] is True
    assert payload["memory_recall_eligible"] is True
    assert payload["source_promotion_ids"] == [source_promotion.promotion.promotion_id]
    assert payload["memory_artifact"]["content"]["historical_report"]
    assert payload["memory_artifact"]["content"]["is_current_fact"] is False
    assert (
        payload["memory_artifact"]["content"]["requires_current_evidence_rebinding"]
        is True
    )
    assert payload["automatic_memory_promotion_enabled"] is False
    assert payload["automatic_recall_enabled"] is False
    assert payload["retrieval_contract_available"] is True
    assert payload["retrieval_contract_version"] == (
        "karkinos.ai.external_promoted_analysis_memory_retrieval.v1"
    )
    assert payload["legacy_phase_1_12_contract_modified"] is False
    assert payload["external_model_invocation_count"] == 0
    assert payload["provider_promotion_eligible"] is False
    assert payload["decision_handoff_enabled"] is False
    assert payload["trade_plan_created"] is False
    assert payload["authority_effect"] == "none"
    assert promoted.replay().valid is True
    assert len(transport.calls) == 3

    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "PRAGMA table_info(ai_external_reviewed_memory_promotions)"
            ).fetchall()
            == legacy_columns
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_reviewed_memory_promotions"
            ).fetchone()[0]
            == legacy_rows
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_artifacts").fetchone()[0]
            == artifact_rows
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) "
                "FROM ai_external_promoted_analysis_memory_promotions"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) " "FROM ai_external_promoted_analysis_memory_events"
            ).fetchone()[0]
            == 1
        )
        for table in protected_tables:
            assert conn.execute(f"SELECT marker FROM {table}").fetchone()[0] == (
                "protected"
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_promotion_is_restart_and_concurrency_idempotent(tmp_path):
    db_path = tmp_path / "external-promoted-analysis-memory-concurrent.db"
    reviews, review, transport, _, _ = await _accepted_review(db_path)
    service = _service(db_path, reviews)
    request = _promotion_request()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: service.promote(review.review.review_id, request),
                range(2),
            )
        )

    assert sorted(item.reused for item in results) == [False, True]
    assert results[0].promotion == results[1].promotion
    restarted = _service(db_path, reviews, initialize=False).promote(
        review.review.review_id,
        request,
    )
    assert restarted.reused is True
    assert restarted.replay().valid is True
    assert len(transport.calls) == 3

    with pytest.raises(IdempotencyConflict, match="different input"):
        service.promote(
            review.review.review_id,
            _promotion_request(rationale="同一幂等键不能修改提升理由。"),
        )
    with pytest.raises(
        ExternalPromotedAnalysisMemoryRejected,
        match="already has a final",
    ):
        service.promote(
            review.review.review_id,
            _promotion_request(
                idempotency_key="external-promoted-analysis-memory-promotion-002"
            ),
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_revision_or_rejected_review_cannot_be_promoted(tmp_path):
    db_path = tmp_path / "external-promoted-analysis-memory-rejected.db"
    analyses, analysis, _, _, _ = await _completed_analysis(db_path)
    reviews = _review_service(db_path, analyses)
    revision = reviews.review(
        analysis.analysis.record.analysis_id,
        _review_request(
            decision=ExternalAnalysisReviewDecision.REQUEST_REVISION,
            note="证据论证仍需修订。",
        ),
    )

    with pytest.raises(
        ExternalPromotedAnalysisMemoryRejected,
        match="review_not_eligible:revision_requested",
    ):
        _service(db_path, reviews).promote(
            revision.review.review_id,
            _promotion_request(),
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_source_revocation_invalidates_memory_without_deleting_history(
    tmp_path,
):
    db_path = tmp_path / "external-promoted-analysis-memory-source-drift.db"
    reviews, review, _, source_promotions, source_promotion = await _accepted_review(
        db_path
    )
    service = _service(db_path, reviews)
    promoted = service.promote(review.review.review_id, _promotion_request())

    source_promotions.revoke(
        source_promotion.promotion.promotion_id,
        _revocation_request(),
    )
    invalidated = service.get(promoted.promotion.promotion_id)

    assert invalidated.effective_status.value == "invalidated_by_source_drift"
    assert invalidated.source_binding_valid is False
    assert invalidated.memory_recall_eligible is False
    assert invalidated.to_dict()["memory_artifact"]["content"] is None
    assert invalidated.replay().valid is False
    assert "promoted_analysis_memory_source_binding_drift" in (
        invalidated.invalidation_reasons
    )
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) "
                "FROM ai_external_promoted_analysis_memory_promotions"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_revocation_is_idempotent_append_only_and_hides_content(tmp_path):
    db_path = tmp_path / "external-promoted-analysis-memory-revocation.db"
    reviews, review, transport, _, _ = await _accepted_review(db_path)
    service = _service(db_path, reviews)
    promoted = service.promote(review.review.review_id, _promotion_request())
    request = _memory_revocation_request()

    revoked = service.revoke(promoted.promotion.promotion_id, request)
    restarted = _service(db_path, reviews, initialize=False).revoke(
        promoted.promotion.promotion_id,
        request,
    )

    assert revoked.effective_status.value == "revoked"
    assert revoked.memory_recall_eligible is False
    assert revoked.historical_record_valid is True
    assert revoked.to_dict()["memory_artifact"]["content"] is None
    assert revoked.replay().valid is True
    assert revoked.replay().event_count == 2
    assert restarted.reused is True
    assert len(transport.calls) == 3

    with pytest.raises(IdempotencyConflict, match="different input"):
        service.revoke(
            promoted.promotion.promotion_id,
            _memory_revocation_request(reason="同一幂等键不得改写撤销原因。"),
        )
    with pytest.raises(
        ExternalPromotedAnalysisMemoryRejected,
        match="already revoked",
    ):
        service.revoke(
            promoted.promotion.promotion_id,
            _memory_revocation_request(
                idempotency_key="external-promoted-analysis-memory-revocation-002"
            ),
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_report_and_audit_drift_fail_closed(tmp_path):
    db_path = tmp_path / "external-promoted-analysis-memory-drift.db"
    reviews, review, _, _, _ = await _accepted_review(db_path)
    service = _service(db_path, reviews)
    promoted = service.promote(review.review.review_id, _promotion_request())

    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_artifacts SET content_json = ? WHERE artifact_id = ?",
            ("{}", promoted.promotion.report_artifact_id),
        )
    report_drift = service.get(promoted.promotion.promotion_id)
    assert report_drift.memory_recall_eligible is False
    assert report_drift.to_dict()["memory_artifact"]["content"] is None
    assert "report_authority_flag_invalid" in report_drift.current_target.errors

    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_external_promoted_analysis_memory_events "
            "SET event_hash = ? WHERE promotion_id = ? AND sequence = 1",
            ("tampered", promoted.promotion.promotion_id),
        )
    audit_drift = service.get(promoted.promotion.promotion_id)
    assert audit_drift.audit_replay.valid is False
    assert audit_drift.replay().event_chain_valid is False
    assert "promoted-analysis memory audit event hash drifted" in (
        audit_drift.invalidation_reasons
    )


@pytest.mark.unit
def test_reads_do_not_initialize_schema_and_confirmations_are_exact(tmp_path):
    db_path = tmp_path / "external-promoted-analysis-memory-read.db"
    store = ExternalPromotedAnalysisMemoryStore(db_path)

    assert store.list() == ()
    assert store.get_by_idempotency_key("missing") is None
    with pytest.raises(LookupError, match="not found"):
        store.get("missing-promotion")
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            == []
        )

    with pytest.raises(ValueError, match="explicit promoted-analysis memory"):
        _promotion_request(confirmation="wrong")
    with pytest.raises(ValueError, match="revocation confirmation"):
        _memory_revocation_request(confirmation="wrong")
