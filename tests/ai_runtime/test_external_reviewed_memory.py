from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from server.ai_runtime.external_analysis_reviews import (
    ExternalAnalysisReviewDecision,
)
from server.ai_runtime.external_reviewed_memory import (
    EXTERNAL_REVIEWED_MEMORY_PROMOTION_CONFIRMATION,
    EXTERNAL_REVIEWED_MEMORY_REVOCATION_CONFIRMATION,
    ExternalReviewedMemoryPromotionRejected,
    ExternalReviewedMemoryPromotionRequest,
    ExternalReviewedMemoryPromotionService,
    ExternalReviewedMemoryRevocationRequest,
    ExternalReviewedMemoryStore,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from tests.ai_runtime.test_external_analysis_reviews import (
    _completed_analysis,
)
from tests.ai_runtime.test_external_analysis_reviews import _request as _review_request
from tests.ai_runtime.test_external_analysis_reviews import _service as _review_service
from tests.ai_runtime.test_research_tasks import NOW


def _service(db_path, review_service, *, initialize=True):
    store = ExternalReviewedMemoryStore(db_path)
    if initialize:
        store.init()
    return ExternalReviewedMemoryPromotionService(
        review_service=review_service,
        ai_store=AiAuditStore(db_path),
        promotion_store=store,
        now=lambda: NOW,
    )


def _promotion_request(**overrides):
    values = {
        "idempotency_key": "external-reviewed-memory-promotion-001",
        "promoted_by": "human:reese",
        "rationale": "复核通过后保留为可撤销的历史研究先例。",
        "confirmation": EXTERNAL_REVIEWED_MEMORY_PROMOTION_CONFIRMATION,
    }
    values.update(overrides)
    return ExternalReviewedMemoryPromotionRequest(**values)


def _revocation_request(**overrides):
    values = {
        "idempotency_key": "external-reviewed-memory-revocation-001",
        "revoked_by": "human:reese",
        "reason": "该历史研究不再适合作为后续召回输入。",
        "confirmation": EXTERNAL_REVIEWED_MEMORY_REVOCATION_CONFIRMATION,
    }
    values.update(overrides)
    return ExternalReviewedMemoryRevocationRequest(**values)


async def _reviewed_analysis(db_path):
    analysis_service, analysis, transport = await _completed_analysis(db_path)
    reviews = _review_service(db_path, analysis_service)
    review = reviews.review(analysis.record.analysis_id, _review_request())
    assert review.reviewed_research_eligible is True
    return analysis, transport, reviews, review


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_promotes_exact_reviewed_report_to_non_authoritative_memory(tmp_path):
    db_path = tmp_path / "external-reviewed-memory.db"
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

    analysis, transport, reviews, review = await _reviewed_analysis(db_path)
    result = _service(db_path, reviews).promote(
        review.review.review_id,
        _promotion_request(),
    )
    payload = result.to_dict()

    assert payload["effective_status"] == "recall_eligible"
    assert payload["memory_recall_eligible"] is True
    assert payload["source_binding_valid"] is True
    assert payload["memory_artifact_binding_valid"] is True
    assert payload["memory_artifact"]["kind"] == "memory"
    assert payload["memory_artifact"]["is_current_fact"] is False
    assert payload["memory_artifact"]["requires_current_evidence_rebinding"] is True
    assert payload["memory_artifact"]["content_hidden"] is False
    memory = payload["memory_artifact"]["content"]
    assert memory["historical_report"]["title"] == (
        analysis.artifacts[-1].content["title"]
    )
    assert memory["automatic_recall_allowed"] is False
    assert memory["decision_input_created"] is False
    assert memory["trade_plan_created"] is False
    assert memory["authority_effect"] == "none"
    assert isinstance(
        memory["provider_provenance"]["reasoning_mode_requested"],
        bool,
    )
    assert memory["provider_provenance"]["reasoning_content_present"] is True
    assert memory["provider_provenance"]["reasoning_content_persisted"] is False
    assert "RAW_PRIVATE_REASONING_MUST_NOT_PERSIST" not in str(payload)
    assert payload["legacy_retrieval_contract_modified"] is False
    assert payload["external_model_invocation_count"] == 0
    assert payload["decision_handoff_enabled"] is False
    assert payload["provider_promotion_eligible"] is False
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
async def test_promotion_and_revocation_are_restart_concurrency_idempotent(tmp_path):
    db_path = tmp_path / "external-reviewed-memory-idempotent.db"
    _, transport, reviews, review = await _reviewed_analysis(db_path)
    request = _promotion_request()

    def promote():
        return _service(db_path, reviews).promote(review.review.review_id, request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: promote(), range(2)))

    assert sorted(item.reused for item in results) == [False, True]
    assert results[0].promotion == results[1].promotion
    promotion_id = results[0].promotion.promotion_id
    restarted = _service(db_path, reviews, initialize=False).promote(
        review.review.review_id,
        request,
    )
    assert restarted.reused is True
    assert len(transport.calls) == 3

    with pytest.raises(IdempotencyConflict, match="different input"):
        _service(db_path, reviews).promote(
            review.review.review_id,
            _promotion_request(rationale="同一幂等键不能改变提升理由。"),
        )

    revocation_request = _revocation_request()

    def revoke():
        return _service(db_path, reviews).revoke(
            promotion_id,
            revocation_request,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        revoked = list(executor.map(lambda _: revoke(), range(2)))

    assert sorted(item.reused for item in revoked) == [False, True]
    assert all(item.effective_status.value == "revoked" for item in revoked)
    assert all(item.memory_recall_eligible is False for item in revoked)
    assert all(item.to_dict()["memory_artifact"]["content"] is None for item in revoked)
    assert all(item.replay().valid is True for item in revoked)
    assert all(item.replay().event_count == 2 for item in revoked)

    with pytest.raises(
        ExternalReviewedMemoryPromotionRejected,
        match="already revoked",
    ):
        _service(db_path, reviews).revoke(
            promotion_id,
            _revocation_request(
                idempotency_key="external-reviewed-memory-revocation-002"
            ),
        )

    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_reviewed_memory_promotions"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_reviewed_memory_revocations"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_reviewed_memory_events"
            ).fetchone()[0]
            == 2
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_artifacts WHERE workflow_id = ?",
                (results[0].promotion.workflow_id,),
            ).fetchone()[0]
            == 3
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_only_current_eligible_external_review_can_be_promoted(tmp_path):
    db_path = tmp_path / "external-reviewed-memory-gate.db"
    analysis_service, analysis, _ = await _completed_analysis(db_path)
    reviews = _review_service(db_path, analysis_service)
    revision = reviews.review(
        analysis.record.analysis_id,
        _review_request(
            decision=ExternalAnalysisReviewDecision.REQUEST_REVISION,
            note="该报告仍需修订，不能提升为历史记忆。",
        ),
    )

    with pytest.raises(
        ExternalReviewedMemoryPromotionRejected,
        match="review_not_eligible:revision_requested",
    ):
        _service(db_path, reviews).promote(
            revision.review.review_id,
            _promotion_request(),
        )

    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_reviewed_memory_promotions"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_source_or_audit_drift_hides_memory_without_deleting_history(tmp_path):
    db_path = tmp_path / "external-reviewed-memory-drift.db"
    _, _, reviews, review = await _reviewed_analysis(db_path)
    service = _service(db_path, reviews)
    promoted = service.promote(review.review.review_id, _promotion_request())

    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_artifacts SET content_json = ? WHERE artifact_id = ?",
            ('{"tampered":true}', promoted.promotion.report_artifact_id),
        )

    invalidated = service.get(promoted.promotion.promotion_id)
    payload = invalidated.to_dict()
    assert invalidated.effective_status.value == "invalidated_by_source_drift"
    assert invalidated.memory_recall_eligible is False
    assert payload["memory_artifact"]["content"] is None
    assert payload["memory_artifact"]["content_hidden"] is True
    assert "memory_promotion_source_binding_drift" in payload["invalidation_reasons"]
    assert invalidated.replay().valid is False
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_reviewed_memory_promotions"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_external_analysis_reviews"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_promotion_audit_drift_hides_memory(tmp_path):
    db_path = tmp_path / "external-reviewed-memory-audit.db"
    _, _, reviews, review = await _reviewed_analysis(db_path)
    service = _service(db_path, reviews)
    promoted = service.promote(review.review.review_id, _promotion_request())
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_external_reviewed_memory_events SET event_hash = ? "
            "WHERE promotion_id = ? AND sequence = 1",
            ("tampered", promoted.promotion.promotion_id),
        )

    invalidated = service.get(promoted.promotion.promotion_id)
    assert invalidated.memory_recall_eligible is False
    assert invalidated.to_dict()["memory_artifact"]["content"] is None
    assert "memory promotion audit event hash drifted" in (
        invalidated.invalidation_reasons
    )
    assert invalidated.replay().event_chain_valid is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stored_source_artifact_or_revocation_drift_fails_closed(tmp_path):
    db_path = tmp_path / "external-reviewed-memory-row-drift.db"
    _, _, reviews, review = await _reviewed_analysis(db_path)
    service = _service(db_path, reviews)
    promoted = service.promote(review.review.review_id, _promotion_request())
    promotion_id = promoted.promotion.promotion_id

    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_external_reviewed_memory_promotions "
            "SET memory_artifact_id = ? WHERE promotion_id = ?",
            ("tampered-memory-artifact-id", promotion_id),
        )

    invalid_artifact = service.get(promotion_id)
    assert invalid_artifact.memory_artifact_binding_valid is False
    assert invalid_artifact.memory_recall_eligible is False
    assert invalid_artifact.to_dict()["memory_artifact"]["content"] is None

    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_external_reviewed_memory_promotions "
            "SET memory_artifact_id = ? WHERE promotion_id = ?",
            (promoted.promotion.memory_artifact_id, promotion_id),
        )
    revoked = service.revoke(promotion_id, _revocation_request())
    assert revoked.revocation_binding_valid is True
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_external_reviewed_memory_revocations "
            "SET promotion_target_fingerprint = ? WHERE promotion_id = ?",
            ("tampered-target", promotion_id),
        )

    invalid_revocation = service.get(promotion_id)
    assert invalid_revocation.revocation_binding_valid is False
    assert invalid_revocation.historical_record_valid is False
    assert "memory_revocation_binding_drift" in (
        invalid_revocation.invalidation_reasons
    )
    assert invalid_revocation.to_dict()["memory_artifact"]["content"] is None


@pytest.mark.unit
def test_external_reviewed_memory_reads_do_not_initialize_schema(tmp_path):
    db_path = tmp_path / "external-reviewed-memory-read.db"
    store = ExternalReviewedMemoryStore(db_path)

    assert store.list() == ()
    with pytest.raises(LookupError, match="not found"):
        store.get("ai-external-memory-missing")

    with closing(sqlite3.connect(db_path)) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "ai_external_reviewed_memory_promotions" not in tables
