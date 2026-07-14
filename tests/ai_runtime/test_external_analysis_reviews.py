from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from server.ai_runtime.external_analysis_reviews import (
    EXTERNAL_ANALYSIS_REVIEW_CONFIRMATION,
    ExternalAnalysisQualityRubric,
    ExternalAnalysisReviewDecision,
    ExternalAnalysisReviewRejected,
    ExternalAnalysisReviewStore,
    HumanExternalAnalysisReviewRequest,
    HumanExternalAnalysisReviewService,
    ProviderPricingSnapshot,
)
from server.ai_runtime.store import IdempotencyConflict
from tests.ai_runtime.test_external_memory_informed_analysis import (
    EvidenceAwareTransport,
)
from tests.ai_runtime.test_external_memory_informed_analysis import (
    _request as _analysis_request,
)
from tests.ai_runtime.test_external_memory_informed_analysis import (
    _service as _analysis_service,
)
from tests.ai_runtime.test_memory_informed_analysis import _prepared_retrieval
from tests.ai_runtime.test_research_tasks import NOW


def _service(db_path, analysis_service, *, initialize=True):
    store = ExternalAnalysisReviewStore(db_path)
    if initialize:
        store.init()
    return HumanExternalAnalysisReviewService(
        analysis_service=analysis_service,
        review_store=store,
        now=lambda: NOW,
    )


def _pricing() -> ProviderPricingSnapshot:
    return ProviderPricingSnapshot(
        currency="cny",
        prompt_price_per_million_tokens="1.00",
        completion_price_per_million_tokens="2.00",
        source="human-reviewed fixture pricing terms",
        effective_at="2026-07-14T00:00:00+00:00",
    )


def _request(**overrides) -> HumanExternalAnalysisReviewRequest:
    values = {
        "idempotency_key": "external-analysis-review-001",
        "reviewed_by": "human:reese",
        "decision": ExternalAnalysisReviewDecision.ACCEPT_AS_REVIEWED_RESEARCH,
        "note": "逐项复核证据引用、反方观点、局限和成本证据。",
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
        "confirmation": EXTERNAL_ANALYSIS_REVIEW_CONFIRMATION,
    }
    values.update(overrides)
    return HumanExternalAnalysisReviewRequest(**values)


async def _completed_analysis(db_path):
    retrieval, _, _ = await _prepared_retrieval(db_path)
    transport = EvidenceAwareTransport()
    analysis_service = _analysis_service(db_path, transport)
    analysis = analysis_service.start(_analysis_request(retrieval.stored.retrieval_id))
    assert analysis.workflow.status.value == "completed"
    return analysis_service, analysis, transport


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_human_review_records_quality_and_cost_without_memory_or_authority(
    tmp_path,
):
    db_path = tmp_path / "external-analysis-review.db"
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

    analysis_service, analysis, transport = await _completed_analysis(db_path)
    result = _service(db_path, analysis_service).review(
        analysis.record.analysis_id,
        _request(),
    )
    payload = result.to_dict()

    assert payload["decision"] == "accept_as_reviewed_research"
    assert payload["effective_status"] == "reviewed_research"
    assert payload["analysis_target_binding_valid"] is True
    assert payload["analysis_acceptance_eligible"] is True
    assert payload["reviewed_research_eligible"] is True
    assert payload["report_artifact_id"] == analysis.artifacts[-1].artifact_id
    assert payload["quality_evidence"]["status"] == "complete"
    assert payload["quality_evidence"]["prompt_tokens"] == 2_100
    assert payload["quality_evidence"]["completion_tokens"] == 720
    assert payload["quality_evidence"]["total_tokens"] == 2_820
    assert payload["quality_evidence"]["total_latency_ms"] == 3_000
    assert payload["quality_evidence"]["maximum_stage_latency_ms"] == 1_000
    assert payload["quality_evidence"]["human_rubric_total"] == 17
    assert payload["quality_evidence"]["citation_status"] == "complete"
    assert payload["quality_evidence_binding_valid"] is True
    assert payload["current_quality_evidence"] == {
        key: value
        for key, value in payload["quality_evidence"].items()
        if key
        not in {
            "human_rubric",
            "human_rubric_total",
            "human_rubric_maximum",
            "factual_error_count",
            "unsupported_claim_count",
        }
    }
    assert payload["cost_evidence"] == {
        "status": "priced_estimate",
        "currency": "CNY",
        "estimated_cost": "0.00354",
        "prompt_cost": "0.0021",
        "completion_cost": "0.00144",
        "pricing_source": "human-reviewed fixture pricing terms",
        "pricing_effective_at": "2026-07-14T00:00:00+00:00",
        "pricing_unavailable_reason": None,
        "calculation": "reviewer_pricing_x_provider_reported_tokens",
        "provider_invoice": False,
    }
    assert payload["review_external_model_invocation_count"] == 0
    assert payload["memory_artifact_created"] is False
    assert payload["memory_recall_eligible"] is False
    assert payload["provider_promotion_eligible"] is False
    assert payload["decision_handoff_enabled"] is False
    assert payload["trade_plan_created"] is False
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
async def test_review_is_restart_and_concurrency_idempotent_without_model_io(
    tmp_path,
):
    db_path = tmp_path / "external-analysis-review-concurrent.db"
    analysis_service, analysis, transport = await _completed_analysis(db_path)
    service = _service(db_path, analysis_service)
    request = _request()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: service.review(analysis.record.analysis_id, request),
                range(2),
            )
        )

    assert sorted(item.reused for item in results) == [False, True]
    assert results[0].review == results[1].review
    restarted = _service(
        db_path,
        analysis_service,
        initialize=False,
    ).review(analysis.record.analysis_id, request)
    assert restarted.reused is True
    assert len(transport.calls) == 3
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_analysis_reviews"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_analysis_review_events"
            ).fetchone()[0]
            == 1
        )

    with pytest.raises(IdempotencyConflict, match="different input"):
        service.review(
            analysis.record.analysis_id,
            _request(note="同一幂等键不能修改复核说明。"),
        )
    with pytest.raises(ExternalAnalysisReviewRejected, match="already final"):
        service.review(
            analysis.record.analysis_id,
            _request(
                idempotency_key="external-analysis-review-002",
                decision=ExternalAnalysisReviewDecision.REJECT,
                note="第二个最终处置必须被拒绝。",
            ),
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_known_factual_or_unsupported_errors_block_acceptance_but_allow_revision(
    tmp_path,
):
    db_path = tmp_path / "external-analysis-review-errors.db"
    analysis_service, analysis, transport = await _completed_analysis(db_path)
    service = _service(db_path, analysis_service)

    with pytest.raises(
        ExternalAnalysisReviewRejected,
        match="reviewer_identified_factual_errors",
    ):
        service.review(
            analysis.record.analysis_id,
            _request(factual_error_count=1, unsupported_claim_count=2),
        )

    revision = service.review(
        analysis.record.analysis_id,
        _request(
            idempotency_key="external-analysis-review-revision",
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
    assert revision.cost_evidence["status"] == "unpriced"
    assert "reviewer_identified_factual_errors" in revision.invalidation_reasons
    assert "reviewer_identified_unsupported_claims" in (revision.invalidation_reasons)
    assert len(transport.calls) == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_later_evidence_or_usage_drift_invalidates_review_without_deleting_it(
    tmp_path,
):
    db_path = tmp_path / "external-analysis-review-drift.db"
    analysis_service, analysis, _ = await _completed_analysis(db_path)
    service = _service(db_path, analysis_service)
    accepted = service.review(analysis.record.analysis_id, _request())
    first_call = analysis.model_calls[0]
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_external_memory_model_calls SET usage_json = ? "
            "WHERE workflow_id = ? AND stage_id = ?",
            (
                '{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}',
                analysis.workflow.workflow_id,
                first_call.stage_id,
            ),
        )

    invalidated = service.get(accepted.review.review_id)
    payload = invalidated.to_dict()

    assert invalidated.effective_status.value == "invalidated_by_evidence_drift"
    assert invalidated.target_binding_valid is False
    assert invalidated.reviewed_research_eligible is False
    assert "external_analysis_target_fingerprint_drift" in (
        invalidated.invalidation_reasons
    )
    assert invalidated.replay().valid is False
    assert payload["quality_evidence"]["prompt_tokens"] == 2_100
    assert payload["current_quality_evidence"]["prompt_tokens"] == 1_401
    assert payload["quality_evidence_binding_valid"] is False
    assert payload["cost_evidence"]["estimated_cost"] == "0.00354"
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_analysis_reviews"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persisted_quality_or_cost_snapshot_tampering_breaks_audit_replay(
    tmp_path,
):
    db_path = tmp_path / "external-analysis-review-audit-drift.db"
    analysis_service, analysis, _ = await _completed_analysis(db_path)
    reviewed = _service(db_path, analysis_service).review(
        analysis.record.analysis_id,
        _request(),
    )
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_external_analysis_reviews "
            "SET cost_evidence_json = ? WHERE review_id = ?",
            ('{"status":"unpriced"}', reviewed.review.review_id),
        )

    replayed = _service(
        db_path,
        analysis_service,
        initialize=False,
    ).get(reviewed.review.review_id)

    assert replayed.audit_replay.valid is False
    assert replayed.replay().valid is False
    assert "external analysis review cost_evidence_fingerprint drifted" in (
        replayed.audit_replay.errors
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_analysis_cannot_be_accepted_but_rejection_is_auditable(
    tmp_path,
):
    db_path = tmp_path / "external-analysis-review-invalid.db"
    retrieval, _, _ = await _prepared_retrieval(db_path)
    transport = EvidenceAwareTransport(invalid_stage="external_current_evidence_claim")
    analysis_service = _analysis_service(db_path, transport)
    analysis = analysis_service.start(_analysis_request(retrieval.stored.retrieval_id))
    service = _service(db_path, analysis_service)

    with pytest.raises(
        ExternalAnalysisReviewRejected,
        match="analysis_workflow_not_completed",
    ):
        service.review(analysis.record.analysis_id, _request())

    rejected = service.review(
        analysis.record.analysis_id,
        _request(
            idempotency_key="external-analysis-review-reject",
            decision=ExternalAnalysisReviewDecision.REJECT,
            note="模型输出未通过结构校验，拒绝该分析。",
        ),
    )
    assert rejected.effective_status.value == "rejected"
    assert rejected.reviewed_research_eligible is False
    assert rejected.replay().valid is True
    assert len(transport.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_usage_blocks_cost_estimate_without_blocking_human_disposition(
    tmp_path,
):
    db_path = tmp_path / "external-analysis-review-partial-cost.db"
    analysis_service, analysis, _ = await _completed_analysis(db_path)
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_external_memory_model_calls SET usage_json = '{}' "
            "WHERE workflow_id = ?",
            (analysis.workflow.workflow_id,),
        )

    reviewed = _service(db_path, analysis_service).review(
        analysis.record.analysis_id,
        _request(),
    )

    assert reviewed.reviewed_research_eligible is True
    assert reviewed.current_target.quality_evidence["status"] == "partial"
    assert reviewed.cost_evidence["status"] == "partial_usage"
    assert reviewed.cost_evidence["estimated_cost"] is None


@pytest.mark.unit
def test_request_pricing_and_read_store_fail_closed_without_schema(tmp_path):
    with pytest.raises(ValueError, match="between 1 and 5"):
        ExternalAnalysisQualityRubric(
            evidence_grounding=0,
            contradiction_handling=4,
            uncertainty_calibration=4,
            decision_usefulness=4,
        )
    with pytest.raises(ValueError, match="three-letter"):
        ProviderPricingSnapshot(
            currency="人民币",
            prompt_price_per_million_tokens="1",
            completion_price_per_million_tokens="2",
            source="fixture",
            effective_at="2026-07-14T00:00:00+00:00",
        )
    with pytest.raises(ValueError, match="timezone"):
        ProviderPricingSnapshot(
            currency="CNY",
            prompt_price_per_million_tokens="1",
            completion_price_per_million_tokens="2",
            source="fixture",
            effective_at="2026-07-14T00:00:00",
        )
    with pytest.raises(ValueError, match="pricing_unavailable_reason"):
        _request(pricing_snapshot=None, pricing_unavailable_reason=None)
    with pytest.raises(ValueError, match="explicit external"):
        _request(confirmation="wrong")

    db_path = tmp_path / "external-analysis-review-read.db"
    store = ExternalAnalysisReviewStore(db_path)
    assert store.list() == ()
    assert store.get_by_idempotency_key("missing") is None
    with pytest.raises(LookupError, match="not found"):
        store.get("missing-review")
    with closing(sqlite3.connect(db_path)) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "ai_external_analysis_reviews" not in tables
