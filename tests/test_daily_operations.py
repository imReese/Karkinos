from __future__ import annotations

from server.services.daily_operations import build_daily_operations_summary


def _candidate(
    *,
    risk: str = "passed",
    manual: str = "awaiting_manual_confirmation",
    data: str = "live",
    research: str = "attached",
    account_truth: str = "pass",
) -> dict:
    return {
        "risk_gate_status": risk,
        "manual_confirmation_status": manual,
        "evidence": {
            "data_freshness": {"status": data},
            "after_cost_oos_validation": {"status": research},
            "account_truth": {"gate_status": account_truth},
        },
    }


def test_summary_keeps_large_candidate_pool_out_of_manual_actions() -> None:
    candidates = [
        _candidate(risk="passed", manual="awaiting_manual_confirmation")
        for _ in range(3)
    ] + [_candidate(risk="not_checked", manual="awaiting_risk_gate") for _ in range(47)]

    summary = build_daily_operations_summary(
        decision_summary={
            "candidate_count": 50,
            "risk_blocked_count": 0,
            "ready_for_manual_confirmation_count": 0,
            "market_data": {"source_health": "live"},
            "account_truth": {"gate_status": "pass"},
        },
        candidates=candidates,
        pending_manual_orders=[],
        order_facts=[],
        fill_facts=[],
        ledger_review_count=0,
    )

    assert summary.candidate_pool_count == 50
    assert summary.risk_passed_count == 3
    assert summary.manual_ready_count == 0
    assert summary.pending_manual_order_count == 0
    assert summary.conclusion_status == "no_manual_action"
    assert summary.primary_target == "decision"
    assert summary.default_execution_mode == "manual_confirmation"
    assert summary.broker_bridge_status == "disabled"


def test_account_truth_block_blocks_manual_readiness() -> None:
    summary = build_daily_operations_summary(
        decision_summary={
            "candidate_count": 1,
            "risk_blocked_count": 0,
            "ready_for_manual_confirmation_count": 1,
            "market_data": {"source_health": "live"},
            "account_truth": {"gate_status": "blocked"},
        },
        candidates=[
            _candidate(
                risk="passed",
                manual="ready_for_manual_confirmation",
                account_truth="blocked",
            )
        ],
        pending_manual_orders=[],
        order_facts=[],
        fill_facts=[],
        ledger_review_count=0,
    )

    assert summary.manual_ready_count == 0
    assert summary.conclusion_status == "account_truth_blocked"
    assert summary.primary_target == "account-truth"


def test_pending_manual_orders_route_to_trading() -> None:
    summary = build_daily_operations_summary(
        decision_summary={
            "candidate_count": 1,
            "risk_blocked_count": 0,
            "ready_for_manual_confirmation_count": 1,
            "market_data": {"source_health": "live"},
            "account_truth": {"gate_status": "pass"},
        },
        candidates=[
            _candidate(
                risk="passed",
                manual="ready_for_manual_confirmation",
            )
        ],
        pending_manual_orders=[{"order_id": "ACTION-1-MANUAL"}],
        order_facts=[{"order_id": "ACTION-1-MANUAL", "status": "pending_confirm"}],
        fill_facts=[],
        ledger_review_count=0,
    )

    assert summary.manual_ready_count == 1
    assert summary.pending_manual_order_count == 1
    assert summary.conclusion_status == "pending_manual_confirmation"
    assert summary.primary_target == "trading"


def test_risk_block_routes_to_risk_before_candidate_watch() -> None:
    summary = build_daily_operations_summary(
        decision_summary={
            "candidate_count": 2,
            "risk_blocked_count": 1,
            "ready_for_manual_confirmation_count": 0,
            "market_data": {"source_health": "live"},
            "account_truth": {"gate_status": "pass"},
        },
        candidates=[
            _candidate(risk="blocked", manual="risk_blocked"),
            _candidate(risk="passed", manual="awaiting_manual_confirmation"),
        ],
        pending_manual_orders=[],
        order_facts=[],
        fill_facts=[],
        ledger_review_count=0,
    )

    assert summary.risk_blocked_count == 1
    assert summary.conclusion_status == "risk_blocked"
    assert summary.primary_target == "risk"
