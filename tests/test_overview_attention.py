from __future__ import annotations

import pytest

from server.models import PortfolioSnapshot, PositionResponse
from server.services.current_holding_market_evidence_review import (
    build_current_holding_market_evidence_review,
)
from server.services.operations_today import build_overview_attention_items
from server.services.operations_today_values import attention_items


def _review(quote_status: str = "confirmed"):
    return build_current_holding_market_evidence_review(
        PortfolioSnapshot(
            cash=100,
            total_equity=200,
            positions=[
                PositionResponse(
                    symbol="600000",
                    asset_class="stock",
                    quantity=10,
                    available_qty=10,
                    frozen_qty=0,
                    avg_cost=9,
                    latest_price=10,
                    market_value=100,
                    unrealized_pnl=10,
                    realized_pnl=0,
                    commission_paid=0,
                    quote_status=quote_status,
                    quote_timestamp="2026-09-11T15:00:00+08:00",
                    using_persistent_cache=True,
                )
            ],
            allocation=[],
            valuation_snapshot_id="valuation-friday",
            valuation_as_of="2026-09-11T15:00:00+08:00",
            valuation_trade_date="2026-09-11",
            valuation_status="complete" if quote_status == "confirmed" else "degraded",
            ledger_cutoff_id=1,
            ledger_fingerprint="ledger-friday",
            quote_set_fingerprint="quotes-friday",
        )
    )


def _attention(subsystem: str, action: str) -> dict:
    return attention_items(
        [
            {
                "id": subsystem,
                "status": "blocked",
                "next_action": action,
                "target": "market" if subsystem == "market_data" else "decision",
                "detail_status": "blocked",
            }
        ]
    )[0]


def test_latest_published_valuation_has_no_refresh_diagnostic_attention() -> None:
    review = _review()
    failed_refresh = _attention("market_data", "repair_market_data_source")
    operations = {
        "attention_items": [failed_refresh],
        "subsystems": [{"id": "market_data", "status": "blocked"}],
        "conclusion_status": "blocked",
    }

    result = build_overview_attention_items(
        operations=operations,
        market_evidence_review=review,
    )

    assert review.status == "complete"
    assert result == []
    assert operations["attention_items"] == [failed_refresh]
    assert operations["subsystems"][0]["status"] == "blocked"
    assert operations["conclusion_status"] == "blocked"


@pytest.mark.parametrize("quote_status", ["stale", "missing", "error", "conflicting"])
def test_unusable_holding_remains_actionable(quote_status: str) -> None:
    review = _review(quote_status)
    result = build_overview_attention_items(
        operations={"attention_items": []},
        market_evidence_review=review,
    )

    assert len(result) == 1
    assert result[0]["subsystem_id"] == "market_data"
    assert result[0]["next_action"] == "review_current_holding_market_evidence"
    assert result[0]["authorizes_execution"] is False
    assert review.items[0].blocks_authoritative_decisions is True


def test_market_root_consolidates_downstream_plan_block_without_clearing_domain_state() -> (
    None
):
    operations = {
        "attention_items": [
            _attention("market_data", "review_market_data_freshness"),
            _attention("daily_trading_plan", "resolve_daily_plan_blockers"),
        ],
        "daily_plan": {
            "blocked_count": 3,
            "blocker_summary": [{"category": "market_data", "count": 3}],
        },
    }

    result = build_overview_attention_items(
        operations=operations,
        market_evidence_review=_review("stale"),
    )

    assert [item["subsystem_id"] for item in result] == ["market_data"]
    assert operations["daily_plan"]["blocked_count"] == 3
    assert len(operations["attention_items"]) == 2


def test_independent_plan_blocker_is_not_deduplicated_with_market_repair() -> None:
    result = build_overview_attention_items(
        operations={
            "attention_items": [
                _attention("daily_trading_plan", "resolve_daily_plan_blockers"),
            ],
            "daily_plan": {
                "blocker_summary": [
                    {"category": "market_data", "count": 1},
                    {"category": "portfolio", "count": 1},
                ]
            },
        },
        market_evidence_review=_review("stale"),
    )

    assert [item["subsystem_id"] for item in result] == [
        "market_data",
        "daily_trading_plan",
    ]


def test_decision_market_repair_remains_when_holdings_are_usable() -> None:
    result = build_overview_attention_items(
        operations={
            "attention_items": [
                _attention("market_data", "repair_market_data_source"),
                _attention("daily_trading_plan", "resolve_daily_plan_blockers"),
            ],
            "daily_plan": {
                "blocker_summary": [{"category": "market_data", "count": 1}]
            },
        },
        market_evidence_review=_review(),
    )

    assert [item["subsystem_id"] for item in result] == ["market_data"]


def test_missing_nav_without_publication_wait_evidence_still_requires_review() -> None:
    result = build_overview_attention_items(
        operations={"attention_items": []},
        market_evidence_review=_review("confirmed_nav_missing"),
    )

    assert len(result) == 1
    assert result[0]["next_action"] == "review_current_holding_market_evidence"


def test_unconfigured_account_and_absent_scheduler_do_not_create_work() -> None:
    setup = _attention("account_truth", "attach_account_truth_evidence")
    setup["evidence"]["status"] = "missing"
    operations = {
        "attention_items": [setup, _attention("scheduler", "review_scheduler_run")],
        "daily_plan": {"candidate_pool_count": 0, "order_intent_count": 0},
        "scheduler": {"run_id": None},
    }

    result = build_overview_attention_items(
        operations=operations,
        market_evidence_review=_review(),
    )

    assert result == []
    assert len(operations["attention_items"]) == 2


def test_account_setup_remains_required_for_pending_manual_order() -> None:
    setup = _attention("account_truth", "attach_account_truth_evidence")
    setup["evidence"]["status"] = "missing"
    result = build_overview_attention_items(
        operations={
            "attention_items": [setup],
            "daily_plan": {"candidate_pool_count": 0, "order_intent_count": 0},
            "daily_operations": {"pending_manual_order_count": 1},
        },
        market_evidence_review=_review(),
    )

    assert result == [setup]


def test_account_mismatch_and_real_scheduler_failure_remain_actionable() -> None:
    mismatch = _attention("account_truth", "resolve_account_truth_mismatch")
    failure = _attention("scheduler", "inspect_scheduler_failure")
    result = build_overview_attention_items(
        operations={
            "attention_items": [mismatch, failure],
            "daily_plan": {"candidate_pool_count": 0, "order_intent_count": 0},
            "scheduler": {"run_id": "paper-shadow-failed"},
        },
        market_evidence_review=_review(),
    )

    assert result == [mismatch, failure]


def test_expected_nav_publication_wait_is_not_an_overview_task() -> None:
    review = _review("stale")
    review.items[0].requires_user_attention = False
    result = build_overview_attention_items(
        operations={
            "attention_items": [
                _attention("market_data", "review_market_data_freshness")
            ]
        },
        market_evidence_review=review,
    )
    assert result == []
    assert review.items[0].blocks_authoritative_decisions is True
    assert review.review_required_count == 1
