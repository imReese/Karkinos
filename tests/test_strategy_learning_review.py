from __future__ import annotations

import sqlite3
from dataclasses import replace

from server.db import AppDatabase
from server.services.decision_outcome_review import (
    DECISION_OUTCOME_REVIEW_CONFIRMATION,
    DecisionOutcomeReviewReplay,
    DecisionOutcomeReviewRequest,
    DecisionOutcomeReviewResult,
    DecisionOutcomeReviewService,
    DecisionOutcomeReviewStore,
    DecisionOutcomeReviewTarget,
    StoredDecisionOutcomeReview,
)
from server.services.strategy_learning_review import StrategyLearningReviewService


class FakeReviewStore:
    def __init__(self, rows: list[StoredDecisionOutcomeReview]) -> None:
        self.rows = rows

    def list_latest_by_signal(
        self,
        *,
        limit: int = 100,
    ) -> list[StoredDecisionOutcomeReview]:
        return self.rows[:limit]


class FakeReviewService:
    def __init__(self, results: list[DecisionOutcomeReviewResult]) -> None:
        self.results = {result.review.review_id: result for result in results}

    def get(self, review_id: str) -> DecisionOutcomeReviewResult:
        return self.results[review_id]


def _result(
    *,
    signal_id: int,
    strategy_id: str,
    outcome: str,
    current: bool = True,
    audit_valid: bool = True,
) -> DecisionOutcomeReviewResult:
    stored_fingerprint = f"{signal_id:064x}"
    current_fingerprint = stored_fingerprint if current else f"{signal_id + 100:064x}"
    target = DecisionOutcomeReviewTarget(
        signal_id=signal_id,
        signal={
            "id": signal_id,
            "strategy_id": strategy_id,
            "symbol": "510300",
        },
        signal_fingerprint=f"{signal_id + 200:064x}",
        action_task=None,
        risk_decision=None,
        execution_evidence={"status": "fills_linked"},
        strategy_contribution_report={
            "valuation_snapshot_id": "valuation-learning-1",
            "ledger_cutoff_id": 17,
            "contribution_fingerprint": "a" * 64,
        },
        financial_evidence_status="bound",
        allowed_outcomes=("inconclusive", outcome),
        blockers=(),
        limitations=("fixture",),
        fingerprint=current_fingerprint,
    )
    stored_target = target.to_dict()
    stored_target["target_fingerprint"] = stored_fingerprint
    review = StoredDecisionOutcomeReview(
        review_id=f"decision-review-fixture-{signal_id}",
        signal_id=signal_id,
        idempotency_key=f"learning-review-{signal_id}",
        request={
            "reviewed_by": "owner",
            "user_decision": "acted",
            "outcome": outcome,
            "note": "private note must not enter the learning queue",
        },
        request_fingerprint=f"{signal_id + 300:064x}",
        target=stored_target,
        target_fingerprint=stored_fingerprint,
        created_at=f"2026-07-{signal_id:02d}T10:00:00+00:00",
    )
    replay = DecisionOutcomeReviewReplay(
        review_id=review.review_id,
        valid=audit_valid,
        event_count=1,
        last_event_hash="f" * 64,
        errors=() if audit_valid else ("stored_review_target_fingerprint_mismatch",),
    )
    return DecisionOutcomeReviewResult(
        review=review,
        current_target=target,
        audit_replay=replay,
        reused=True,
    )


def test_learning_queue_classifies_reviewed_evidence_without_authority() -> None:
    unsupported = _result(
        signal_id=1,
        strategy_id="dual_ma",
        outcome="evidence_not_supported",
    )
    stale = _result(
        signal_id=2,
        strategy_id="dual_ma",
        outcome="evidence_supported",
        current=False,
    )
    tampered = _result(
        signal_id=3,
        strategy_id="rotation",
        outcome="inconclusive",
        audit_valid=False,
    )
    supported = _result(
        signal_id=4,
        strategy_id="rotation",
        outcome="evidence_supported",
    )
    results = [unsupported, stale, tampered, supported]
    service = StrategyLearningReviewService(
        review_store=FakeReviewStore([item.review for item in results]),
        review_service=FakeReviewService(results),
        now=lambda: "2026-07-18T12:00:00+00:00",
    )

    queue = service.build()

    assert queue["status"] == "blocked"
    assert queue["reviewed_signal_count"] == 4
    assert queue["action_item_count"] == 3
    assert queue["critical_item_count"] == 1
    assert queue["provider_contacted"] is False
    assert queue["database_writes_performed"] is False
    assert queue["financial_recalculation_performed"] is False
    assert queue["ai_invoked"] is False
    assert queue["memory_created"] is False
    assert queue["strategy_changed"] is False
    assert queue["authorizes_execution"] is False
    assert queue["capital_authority_changed"] is False
    by_signal = {item["signal_id"]: item for item in queue["items"]}
    assert by_signal[1]["learning_status"] == "strategy_research_required"
    assert by_signal[1]["research_handoff"]["invokes_ai"] is False
    assert by_signal[1]["research_handoff"]["requires_human_started_capture"] is True
    assert by_signal[2]["learning_status"] == "evidence_refresh_required"
    assert by_signal[2]["research_handoff"] is None
    assert by_signal[3]["learning_status"] == "audit_integrity_blocked"
    assert by_signal[4]["safe_next_action"] == "none"
    assert all("private note" not in str(item) for item in queue["items"])


def test_learning_queue_is_stable_and_read_only_for_real_review(tmp_path) -> None:
    db = AppDatabase(tmp_path / "learning.db")
    db.init_sync()
    signal_id = db.save_signal_sync(
        timestamp="2026-07-18T09:30:00+08:00",
        strategy_id="dual_ma",
        symbol="510300",
        direction="buy",
        target_weight=0.2,
        price=4.6,
        asset_class="fund",
    )
    store = DecisionOutcomeReviewStore(db._path)
    review_service = DecisionOutcomeReviewService(
        db=db,
        store=store,
        now=lambda: "2026-07-18T10:00:00+00:00",
    )
    target = review_service.preview(signal_id)
    review_service.review(
        signal_id,
        DecisionOutcomeReviewRequest(
            idempotency_key="learning-real-review",
            reviewed_by="owner",
            user_decision="deferred",
            outcome="not_executed",
            note="Waiting for a later decision-process review.",
            expected_target_fingerprint=target.fingerprint,
            confirmation=DECISION_OUTCOME_REVIEW_CONFIRMATION,
        ),
    )
    service = StrategyLearningReviewService(
        review_store=store,
        review_service=review_service,
        now=lambda: "2026-07-18T12:00:00+00:00",
    )
    with sqlite3.connect(db._path) as conn:
        before = {
            "reviews": conn.execute(
                "SELECT COUNT(*) FROM decision_outcome_reviews"
            ).fetchone()[0],
            "review_events": conn.execute(
                "SELECT COUNT(*) FROM decision_outcome_review_events"
            ).fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM event_log").fetchone()[0],
        }

    first = service.build()
    second = service.build()

    with sqlite3.connect(db._path) as conn:
        after = {
            "reviews": conn.execute(
                "SELECT COUNT(*) FROM decision_outcome_reviews"
            ).fetchone()[0],
            "review_events": conn.execute(
                "SELECT COUNT(*) FROM decision_outcome_review_events"
            ).fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM event_log").fetchone()[0],
        }
    assert first["status"] == "review_required"
    assert first["items"][0]["learning_status"] == "decision_process_review"
    assert first["items"][0]["research_handoff"] is None
    assert first["queue_fingerprint"] == second["queue_fingerprint"]
    assert before == after


def test_learning_queue_blocks_tampered_review_and_empty_read_creates_no_schema(
    tmp_path,
) -> None:
    empty_path = tmp_path / "empty.db"
    sqlite3.connect(empty_path).close()
    empty_store = DecisionOutcomeReviewStore(empty_path)
    empty_service = StrategyLearningReviewService(
        review_store=empty_store,
        review_service=FakeReviewService([]),
        now=lambda: "2026-07-18T12:00:00+00:00",
    )
    assert empty_service.build()["status"] == "not_configured"
    with sqlite3.connect(empty_path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0]
            == 0
        )

    result = _result(
        signal_id=5,
        strategy_id="dual_ma",
        outcome="evidence_not_supported",
    )
    invalid = replace(
        result,
        audit_replay=replace(
            result.audit_replay,
            valid=False,
            errors=("stored_review_request_fingerprint_mismatch",),
        ),
    )
    queue = StrategyLearningReviewService(
        review_store=FakeReviewStore([invalid.review]),
        review_service=FakeReviewService([invalid]),
        now=lambda: "2026-07-18T12:00:00+00:00",
    ).build()
    assert queue["status"] == "blocked"
    assert queue["items"][0]["research_handoff"] is None
    assert queue["items"][0]["blockers"] == [
        "stored_review_request_fingerprint_mismatch"
    ]
