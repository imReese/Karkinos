from __future__ import annotations

from server.models import DailyOperationsSummary
from server.services.operations_today import build_operations_today_summary


def _operations(manual_ready_count: int = 1) -> DailyOperationsSummary:
    return DailyOperationsSummary(
        candidate_pool_count=1,
        evidence_passed_count=1,
        risk_checked_count=1,
        risk_passed_count=1,
        risk_blocked_count=0,
        paper_shadow_review_count=1,
        manual_ready_count=manual_ready_count,
        pending_manual_order_count=0,
        execution_record_count=0,
        fill_record_count=0,
        ledger_review_count=0,
        execution_exception_count=0,
        default_execution_mode="manual_confirmation",
        broker_bridge_status="disabled",
        conclusion_status="pending_manual_confirmation",
        primary_target="trading",
        limitations=[],
    )


def _decision() -> dict:
    return {
        "decision_date": "2026-07-01",
        "generated_at": "2026-07-01T09:31:00+08:00",
        "summary": {
            "candidate_count": 1,
            "market_data": {
                "source_health": "live",
                "latest_quote_timestamp": "2026-07-01T09:30:00+08:00",
            },
            "account_truth": {"gate_status": "pass", "limitations": []},
        },
        "candidates": [],
    }


def _plan(order_intent_count: int = 1) -> dict:
    return {
        "plan_date": "2026-07-01",
        "generated_at": "2026-07-01T09:31:30+08:00",
        "conclusion_status": "manual_confirmation_ready",
        "candidate_pool_count": 1,
        "manual_ready_count": 1,
        "blocked_count": 0,
        "order_intent_count": order_intent_count,
        "limitations": [
            "Order intents are manual-confirmation previews, not broker submissions."
        ],
    }


def test_operations_today_requires_shadow_run_for_order_intents() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[],
        fill_facts=[],
        generated_at="2026-07-01T09:32:00+08:00",
    )

    assert summary["conclusion_status"] == "manual_action_required"
    assert summary["primary_target"] == "paper-shadow"
    assert summary["daily_plan"]["order_intent_count"] == 1
    assert summary["paper_shadow"]["status"] == "not_run"
    assert summary["paper_shadow"]["next_manual_review_step"] == (
        "run_paper_shadow_daily"
    )
    assert summary["health"]["manual_action_required"] == 2


def test_operations_today_requires_shadow_divergence_review() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[
            {
                "order_id": "SHADOW-2026-07-01-7",
                "symbol": "600519",
                "status": "shadow_recorded",
                "execution_mode": "paper_shadow",
                "payload_json": '{"run_id": "shadow:2026-07-01"}',
                "timestamp": "2026-07-01T09:33:00+08:00",
            }
        ],
        fill_facts=[],
    )

    assert summary["paper_shadow"]["status"] == "review_required"
    assert summary["paper_shadow"]["simulated_order_count"] == 1
    assert summary["paper_shadow"]["divergence_reviewed_count"] == 0
    assert summary["paper_shadow"]["next_manual_review_step"] == (
        "review_shadow_divergence"
    )


def test_operations_today_marks_shadow_review_within_expectations() -> None:
    summary = build_operations_today_summary(
        decision_payload=_decision(),
        trading_plan=_plan(),
        daily_operations=_operations(),
        order_facts=[
            {
                "order_id": "SHADOW-2026-07-01-7",
                "symbol": "600519",
                "status": "shadow_recorded",
                "execution_mode": "paper_shadow",
                "payload_json": (
                    '{"run_id": "shadow:2026-07-01", '
                    '"divergence_status": "within_expectations"}'
                ),
                "updated_at": "2026-07-01T09:35:00+08:00",
            }
        ],
        fill_facts=[
            {
                "fill_id": "FILL-1",
                "order_id": "SHADOW-2026-07-01-7",
                "execution_mode": "paper_shadow",
                "timestamp": "2026-07-01T09:34:00+08:00",
            }
        ],
    )

    assert summary["paper_shadow"]["status"] == "within_expectations"
    assert summary["paper_shadow"]["simulated_fill_count"] == 1
    assert summary["paper_shadow"]["divergence_reviewed_count"] == 1
    assert summary["paper_shadow"]["next_manual_review_step"] == (
        "review_manual_confirmation"
    )
