from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from server.ai_runtime.analysis_reviews import (
    ANALYSIS_REVIEW_CONFIRMATION,
    AnalysisReviewDecision,
    AnalysisReviewRejected,
    AnalysisReviewStore,
    HumanAnalysisReviewRequest,
    HumanAnalysisReviewService,
)
from server.ai_runtime.store import IdempotencyConflict
from tests.ai_runtime.test_research_tasks import NOW
from tests.ai_runtime.test_task_fixture_analysis import (
    _accepted_task,
    _analysis_service,
)
from tests.ai_runtime.test_task_fixture_analysis import _request as _analysis_request


def _review_service(db_path):
    analysis_service = _analysis_service(db_path)
    review_store = AnalysisReviewStore(db_path)
    review_store.init()
    return HumanAnalysisReviewService(
        analysis_service=analysis_service,
        review_store=review_store,
        now=lambda: NOW,
    )


def _review_request(
    *,
    decision: AnalysisReviewDecision = (
        AnalysisReviewDecision.ACCEPT_AS_REVIEWED_MEMORY
    ),
    idempotency_key: str = "fixture-analysis-review-001",
    note: str = "Reviewed exact fixture evidence and limitations.",
):
    return HumanAnalysisReviewRequest(
        idempotency_key=idempotency_key,
        reviewed_by="human:reese",
        decision=decision,
        note=note,
        confirmation=ANALYSIS_REVIEW_CONFIRMATION,
    )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_human_review_makes_exact_memory_recall_eligible_without_authority(
    tmp_path,
):
    db_path = tmp_path / "analysis-review.db"
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

    _, task = await _accepted_task(db_path)
    analysis = _analysis_service(db_path).start(_analysis_request(task.task_id))
    result = _review_service(db_path).review(
        analysis.record.analysis_id,
        _review_request(),
    )
    payload = result.to_dict()

    assert payload["decision"] == "accept_as_reviewed_memory"
    assert payload["effective_status"] == "reviewed_memory"
    assert payload["analysis_target_binding_valid"] is True
    assert payload["analysis_acceptance_eligible"] is True
    assert payload["memory_recall_eligible"] is True
    assert payload["memory_artifact_id"] == analysis.artifacts[-1].artifact_id
    assert payload["audit_replay"]["valid"] is True
    assert payload["research_memory_only"] is True
    assert payload["research_output_is_account_fact"] is False
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
async def test_analysis_review_is_idempotent_across_restart_and_final_per_analysis(
    tmp_path,
):
    db_path = tmp_path / "analysis-review.db"
    _, task = await _accepted_task(db_path)
    analysis = _analysis_service(db_path).start(_analysis_request(task.task_id))
    first = _review_service(db_path).review(
        analysis.record.analysis_id,
        _review_request(),
    )
    restarted = _review_service(db_path).review(
        analysis.record.analysis_id,
        _review_request(),
    )

    assert first.reused is False
    assert restarted.reused is True
    assert restarted.review == first.review
    assert restarted.current_target == first.current_target
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_research_task_analysis_reviews"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_research_task_analysis_review_events"
            ).fetchone()[0]
            == 1
        )

    with pytest.raises(IdempotencyConflict, match="different input"):
        _review_service(db_path).review(
            analysis.record.analysis_id,
            _review_request(note="Changed review note."),
        )
    with pytest.raises(AnalysisReviewRejected, match="already final"):
        _review_service(db_path).review(
            analysis.record.analysis_id,
            _review_request(
                decision=AnalysisReviewDecision.REJECT,
                idempotency_key="fixture-analysis-review-002",
                note="Reject the fixture output.",
            ),
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_exact_analysis_review_records_one_audit_fact(tmp_path):
    db_path = tmp_path / "analysis-review-concurrent.db"
    _, task = await _accepted_task(db_path)
    analysis = _analysis_service(db_path).start(_analysis_request(task.task_id))

    def record_review():
        return _review_service(db_path).review(
            analysis.record.analysis_id,
            _review_request(),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: record_review(), range(2)))

    assert sorted(item.reused for item in results) == [False, True]
    assert results[0].review == results[1].review
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_research_task_analysis_reviews"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_research_task_analysis_review_events"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evidence_drift_blocks_memory_acceptance_but_allows_revision_record(
    tmp_path,
):
    db_path = tmp_path / "analysis-review.db"
    capture, task = await _accepted_task(db_path)
    analysis = _analysis_service(db_path).start(_analysis_request(task.task_id))
    service = _review_service(db_path)
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_canonical_evidence SET payload_json = ? "
            "WHERE reference_id = ?",
            ('{"tampered":true}', capture.records[0].reference_id),
        )

    with pytest.raises(AnalysisReviewRejected, match="cannot become reviewed"):
        service.review(analysis.record.analysis_id, _review_request())

    revision = service.review(
        analysis.record.analysis_id,
        _review_request(
            decision=AnalysisReviewDecision.REQUEST_REVISION,
            idempotency_key="fixture-analysis-review-revision",
            note="Refresh and recapture the drifted evidence.",
        ),
    )
    assert revision.effective_status.value == "revision_requested"
    assert revision.memory_recall_eligible is False
    assert revision.target_binding_valid is True
    assert "analysis_binding_invalid:evidence_drift" in (
        revision.current_target.acceptance_errors
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reviewed_memory_is_invalidated_after_later_evidence_drift(tmp_path):
    db_path = tmp_path / "analysis-review.db"
    capture, task = await _accepted_task(db_path)
    analysis = _analysis_service(db_path).start(_analysis_request(task.task_id))
    service = _review_service(db_path)
    accepted = service.review(analysis.record.analysis_id, _review_request())
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_canonical_evidence SET payload_json = ? "
            "WHERE reference_id = ?",
            ('{"tampered":true}', capture.records[-1].reference_id),
        )

    invalidated = service.get(accepted.review.review_id)
    replay = service.replay(accepted.review.review_id)

    assert invalidated.effective_status.value == "invalidated_by_evidence_drift"
    assert invalidated.memory_recall_eligible is False
    assert invalidated.target_binding_valid is False
    assert "analysis_target_fingerprint_drift" in invalidated.invalidation_reasons
    assert replay.valid is False
    assert replay.analysis_target_binding_valid is False
    assert replay.memory_recall_eligible is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_artifact_payload_drift_blocks_reviewed_memory(tmp_path):
    db_path = tmp_path / "analysis-review.db"
    _, task = await _accepted_task(db_path)
    analysis = _analysis_service(db_path).start(_analysis_request(task.task_id))
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_artifacts SET content_json = ? WHERE artifact_id = ?",
            ('{"tampered":true}', analysis.artifacts[0].artifact_id),
        )

    with pytest.raises(AnalysisReviewRejected, match="artifact_fingerprint_drift"):
        _review_service(db_path).review(
            analysis.record.analysis_id,
            _review_request(),
        )


@pytest.mark.unit
def test_analysis_review_reads_do_not_initialize_database_schema(tmp_path):
    db_path = tmp_path / "analysis-review-read.db"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("CREATE TABLE existing_financial_fact (id INTEGER PRIMARY KEY)")
        before = conn.execute("PRAGMA schema_version").fetchone()[0]

    store = AnalysisReviewStore(db_path)

    assert store.list() == ()
    assert store.get_by_idempotency_key("missing") is None
    with pytest.raises(LookupError, match="fixture analysis review not found"):
        store.get("missing-review")
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
def test_analysis_review_request_requires_explicit_confirmation():
    with pytest.raises(ValueError, match="explicit non-authoritative"):
        HumanAnalysisReviewRequest(
            idempotency_key="review-invalid",
            reviewed_by="human:reese",
            decision=AnalysisReviewDecision.REJECT,
            note="Reject invalid fixture output.",
            confirmation="",
        )
