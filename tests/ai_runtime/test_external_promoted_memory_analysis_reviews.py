from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from server.ai_runtime.external_analysis_reviews import (
    ExternalAnalysisQualityRubric,
    ExternalAnalysisReviewDecision,
    ProviderPricingSnapshot,
)
from server.ai_runtime.external_promoted_memory_analysis_reviews import (
    EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONFIRMATION,
    ExternalPromotedMemoryAnalysisReviewRejected,
    ExternalPromotedMemoryAnalysisReviewStore,
    HumanExternalPromotedMemoryAnalysisReviewRequest,
    HumanExternalPromotedMemoryAnalysisReviewService,
)
from server.ai_runtime.store import IdempotencyConflict
from tests.ai_runtime.test_external_memory_informed_analysis import (
    EvidenceAwareTransport,
)
from tests.ai_runtime.test_external_promoted_memory_analysis import (
    _prepared_promoted_retrieval,
)
from tests.ai_runtime.test_external_promoted_memory_analysis import (
    _request as _analysis_request,
)
from tests.ai_runtime.test_external_promoted_memory_analysis import (
    _service as _analysis_service,
)
from tests.ai_runtime.test_external_reviewed_memory import _revocation_request
from tests.ai_runtime.test_research_tasks import NOW


def _service(db_path, analysis_service, *, initialize=True):
    store = ExternalPromotedMemoryAnalysisReviewStore(db_path)
    if initialize:
        store.init()
    return HumanExternalPromotedMemoryAnalysisReviewService(
        analysis_service=analysis_service,
        review_store=store,
        now=lambda: NOW,
    )


def _pricing() -> ProviderPricingSnapshot:
    return ProviderPricingSnapshot(
        currency="cny",
        prompt_price_per_million_tokens="1.00",
        completion_price_per_million_tokens="2.00",
        source="human-reviewed promoted-memory fixture pricing terms",
        effective_at="2026-07-14T00:00:00+00:00",
    )


def _request(**overrides) -> HumanExternalPromotedMemoryAnalysisReviewRequest:
    values = {
        "idempotency_key": "external-promoted-analysis-review-001",
        "reviewed_by": "human:reese",
        "decision": ExternalAnalysisReviewDecision.ACCEPT_AS_REVIEWED_RESEARCH,
        "note": "逐项复核当前证据、历史记忆来源、反方观点、局限和成本。",
        "quality_rubric": ExternalAnalysisQualityRubric(
            evidence_grounding=5,
            contradiction_handling=4,
            uncertainty_calibration=4,
            decision_usefulness=4,
        ),
        "factual_error_count": 0,
        "unsupported_claim_count": 0,
        "pricing_snapshot": _pricing(),
        "pricing_unavailable_reason": None,
        "confirmation": EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONFIRMATION,
    }
    values.update(overrides)
    return HumanExternalPromotedMemoryAnalysisReviewRequest(**values)


async def _completed_analysis(db_path):
    retrieval, promotions, promotion, _, retrievals = (
        await _prepared_promoted_retrieval(db_path)
    )
    transport = EvidenceAwareTransport()
    analyses = _analysis_service(db_path, retrievals, transport)
    analysis = analyses.start(_analysis_request(retrieval.stored.retrieval_id))
    assert analysis.analysis.workflow.status.value == "completed"
    return analyses, analysis, transport, promotions, promotion


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_promoted_analysis_review_binds_quality_source_and_cost_without_authority(
    tmp_path,
):
    db_path = tmp_path / "external-promoted-analysis-review.db"
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

    analyses, analysis, transport, _, promotion = await _completed_analysis(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        legacy_review_count = conn.execute(
            "SELECT COUNT(*) FROM ai_external_analysis_reviews"
        ).fetchone()[0]
        artifact_count = conn.execute("SELECT COUNT(*) FROM ai_artifacts").fetchone()[0]

    reviewed = _service(db_path, analyses).review(
        analysis.analysis.record.analysis_id,
        _request(),
    )
    payload = reviewed.to_dict()

    assert payload["schema_version"] == (
        "karkinos.ai.external_promoted_memory_analysis_review.v1"
    )
    assert payload["effective_status"] == "reviewed_research"
    assert payload["analysis_target_binding_valid"] is True
    assert payload["analysis_acceptance_eligible"] is True
    assert payload["reviewed_research_eligible"] is True
    assert payload["retrieval_id"] == analysis.analysis.record.request.retrieval_id
    assert payload["promotion_ids"] == [promotion.promotion.promotion_id]
    assert payload["selected_memory_sources"] == [
        {
            "promotion_id": promotion.promotion.promotion_id,
            "review_id": promotion.promotion.review_id,
            "source_analysis_id": promotion.promotion.analysis_id,
            "source_context_snapshot_id": (
                analysis.source_retrieval.current_target.selections[
                    0
                ].source_context_snapshot_id
            ),
            "memory_artifact_id": promotion.promotion.memory_artifact_id,
            "memory_artifact_fingerprint": (
                promotion.promotion.memory_artifact_fingerprint
            ),
            "selection_fingerprint": (
                analysis.source_retrieval.current_target.selections[0].fingerprint
            ),
        }
    ]
    assert payload["quality_evidence"]["status"] == "complete"
    assert payload["quality_evidence"]["prompt_tokens"] == 2_100
    assert payload["quality_evidence"]["completion_tokens"] == 720
    assert payload["quality_evidence"]["total_tokens"] == 2_820
    assert payload["quality_evidence"]["total_latency_ms"] == 3_000
    assert payload["quality_evidence"]["human_rubric_total"] == 17
    assert payload["quality_evidence"]["citation_status"] == "complete"
    assert payload["quality_evidence_binding_valid"] is True
    assert payload["cost_evidence"]["status"] == "priced_estimate"
    assert payload["cost_evidence"]["estimated_cost"] == "0.00354"
    assert payload["review_external_model_invocation_count"] == 0
    assert payload["memory_artifact_created"] is False
    assert payload["memory_recall_eligible"] is False
    assert payload["automatic_memory_promotion_enabled"] is False
    assert payload["provider_promotion_eligible"] is False
    assert payload["decision_handoff_enabled"] is False
    assert payload["trade_plan_created"] is False
    assert payload["authority_effect"] == "none"
    assert reviewed.replay().valid is True
    assert len(transport.calls) == 3

    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_analysis_reviews"
            ).fetchone()[0]
            == legacy_review_count
        )
        assert conn.execute("SELECT COUNT(*) FROM ai_artifacts").fetchone()[0] == (
            artifact_count
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) " "FROM ai_external_promoted_memory_analysis_reviews"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) "
                "FROM ai_external_promoted_memory_analysis_review_events"
            ).fetchone()[0]
            == 1
        )
        for table in protected_tables:
            assert conn.execute(f"SELECT marker FROM {table}").fetchone()[0] == (
                "protected"
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_promoted_analysis_review_is_restart_and_concurrency_idempotent(
    tmp_path,
):
    db_path = tmp_path / "external-promoted-analysis-review-concurrent.db"
    analyses, analysis, transport, _, _ = await _completed_analysis(db_path)
    service = _service(db_path, analyses)
    request = _request()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: service.review(
                    analysis.analysis.record.analysis_id,
                    request,
                ),
                range(2),
            )
        )

    assert sorted(item.reused for item in results) == [False, True]
    assert results[0].review == results[1].review
    restarted = _service(
        db_path,
        analyses,
        initialize=False,
    ).review(analysis.analysis.record.analysis_id, request)
    assert restarted.reused is True
    assert restarted.replay().valid is True
    assert len(transport.calls) == 3

    with pytest.raises(IdempotencyConflict, match="different input"):
        service.review(
            analysis.analysis.record.analysis_id,
            _request(note="同一幂等键不能修改复核说明。"),
        )
    with pytest.raises(
        ExternalPromotedMemoryAnalysisReviewRejected,
        match="already final",
    ):
        service.review(
            analysis.analysis.record.analysis_id,
            _request(
                idempotency_key="external-promoted-analysis-review-002",
                decision=ExternalAnalysisReviewDecision.REJECT,
                note="第二个最终处置必须被拒绝。",
            ),
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_blocking_human_errors_prevent_acceptance_but_allow_revision(tmp_path):
    db_path = tmp_path / "external-promoted-analysis-review-errors.db"
    analyses, analysis, transport, _, _ = await _completed_analysis(db_path)
    service = _service(db_path, analyses)

    with pytest.raises(
        ExternalPromotedMemoryAnalysisReviewRejected,
        match="reviewer_identified_factual_errors",
    ):
        service.review(
            analysis.analysis.record.analysis_id,
            _request(factual_error_count=1, unsupported_claim_count=2),
        )

    revision = service.review(
        analysis.analysis.record.analysis_id,
        _request(
            idempotency_key="external-promoted-analysis-review-revision",
            decision=ExternalAnalysisReviewDecision.REQUEST_REVISION,
            factual_error_count=1,
            unsupported_claim_count=2,
            pricing_snapshot=None,
            pricing_unavailable_reason="provider pricing terms not reviewed",
            note="发现事实错误和无证据主张，需要修订。",
        ),
    )
    assert revision.effective_status.value == "revision_requested"
    assert revision.reviewed_research_eligible is False
    assert revision.review.cost_evidence["status"] == "unpriced"
    assert len(transport.calls) == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_source_revocation_invalidates_accepted_review_without_history_loss(
    tmp_path,
):
    db_path = tmp_path / "external-promoted-analysis-review-source-drift.db"
    analyses, analysis, _, promotions, promotion = await _completed_analysis(db_path)
    service = _service(db_path, analyses)
    accepted = service.review(
        analysis.analysis.record.analysis_id,
        _request(),
    )

    promotions.revoke(promotion.promotion.promotion_id, _revocation_request())
    invalidated = service.get(accepted.review.review_id)

    assert invalidated.effective_status.value == "invalidated_by_evidence_drift"
    assert invalidated.target_binding_valid is False
    assert invalidated.reviewed_research_eligible is False
    assert invalidated.replay().valid is False
    assert "source_promoted_memory_retrieval_not_eligible" in (
        invalidated.invalidation_reasons
    )
    assert "external_promoted_memory_analysis_target_fingerprint_drift" in (
        invalidated.invalidation_reasons
    )
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) " "FROM ai_external_promoted_memory_analysis_reviews"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_usage_drift_invalidates_review_and_preserves_frozen_cost_evidence(
    tmp_path,
):
    db_path = tmp_path / "external-promoted-analysis-review-usage-drift.db"
    analyses, analysis, _, _, _ = await _completed_analysis(db_path)
    service = _service(db_path, analyses)
    accepted = service.review(analysis.analysis.record.analysis_id, _request())
    first_call = analysis.analysis.model_calls[0]
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_external_promoted_memory_model_calls SET usage_json = ? "
            "WHERE workflow_id = ? AND stage_id = ?",
            (
                '{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}',
                analysis.analysis.workflow.workflow_id,
                first_call.stage_id,
            ),
        )

    invalidated = service.get(accepted.review.review_id)
    payload = invalidated.to_dict()

    assert invalidated.effective_status.value == "invalidated_by_evidence_drift"
    assert invalidated.target_binding_valid is False
    assert invalidated.reviewed_research_eligible is False
    assert invalidated.replay().valid is False
    assert payload["quality_evidence"]["prompt_tokens"] == 2_100
    assert payload["current_quality_evidence"]["prompt_tokens"] == 1_401
    assert payload["quality_evidence_binding_valid"] is False
    assert payload["cost_evidence"]["estimated_cost"] == "0.00354"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_analysis_cannot_be_accepted_but_rejection_is_auditable(
    tmp_path,
):
    db_path = tmp_path / "external-promoted-analysis-review-failed.db"
    retrieval, _, _, _, retrievals = await _prepared_promoted_retrieval(db_path)
    transport = EvidenceAwareTransport(invalid_stage="external_current_evidence_claim")
    analyses = _analysis_service(db_path, retrievals, transport)
    failed = analyses.start(_analysis_request(retrieval.stored.retrieval_id))
    assert failed.analysis.workflow.status.value == "failed"
    service = _service(db_path, analyses)

    with pytest.raises(
        ExternalPromotedMemoryAnalysisReviewRejected,
        match="analysis_workflow_not_completed",
    ):
        service.review(failed.analysis.record.analysis_id, _request())

    rejected = service.review(
        failed.analysis.record.analysis_id,
        _request(
            idempotency_key="external-promoted-analysis-review-reject",
            decision=ExternalAnalysisReviewDecision.REJECT,
            note="模型输出没有通过结构校验，拒绝该分析。",
        ),
    )
    assert rejected.effective_status.value == "rejected"
    assert rejected.reviewed_research_eligible is False
    assert rejected.replay().valid is True
    assert len(transport.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_review_audit_tampering_fails_replay_and_read_store_is_non_mutating(
    tmp_path,
):
    db_path = tmp_path / "external-promoted-analysis-review-audit.db"
    analyses, analysis, _, _, _ = await _completed_analysis(db_path)
    service = _service(db_path, analyses)
    reviewed = service.review(analysis.analysis.record.analysis_id, _request())
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_external_promoted_memory_analysis_reviews "
            "SET cost_evidence_json = ? WHERE review_id = ?",
            ('{"status":"unpriced"}', reviewed.review.review_id),
        )

    replayed = _service(db_path, analyses, initialize=False).get(
        reviewed.review.review_id
    )
    assert replayed.audit_replay.valid is False
    assert replayed.replay().valid is False
    assert any(
        "cost_evidence_fingerprint drifted" in error
        for error in replayed.audit_replay.errors
    )

    empty_path = tmp_path / "external-promoted-analysis-review-read.db"
    store = ExternalPromotedMemoryAnalysisReviewStore(empty_path)
    assert store.list() == ()
    assert store.get_by_idempotency_key("missing") is None
    with pytest.raises(LookupError, match="not found"):
        store.get("missing-review")
    with closing(sqlite3.connect(empty_path)) as conn:
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            == []
        )

    with pytest.raises(ValueError, match="explicit promoted-memory"):
        _request(confirmation="wrong")
