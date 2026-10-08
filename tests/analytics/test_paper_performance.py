from decimal import Decimal

from analytics.paper_performance import evaluate_paper_health, paper_book_performance
from tests.backtest.test_paper_replay import DAYS, _bar, _cost, _replay, _target


def _book(replay):
    rows = replay["sessions"]
    for row in rows:
        row["benchmark"] = {"equity": replay["initial_cash"]}
    return {
        "id": replay["book_id"],
        "version": 1,
        "initial_cash": replay["initial_cash"],
        "evaluation_start": replay["evaluation_start"],
        "last_settled_session": replay["through_session"],
        "steps": [{"projection": row} for row in rows],
        "state": rows[-1],
        "fills": replay["fills"],
        "attempts": replay["attempts"],
        "policy": {
            "benchmark": {"policy_id": "sanitized_cash_comparator"},
            "corporate_action_mode": "price_only",
            "limitations": [],
        },
    }


def test_initial_cash_peak_and_fee_slippage_are_counted_once():
    replay = _replay(
        [_bar(day) for day in DAYS[:2]],
        [_target(1)],
        initial_cash=Decimal("2050"),
        cost_config=_cost(minimum="5", slip="1"),
    )
    report = paper_book_performance(_book(replay))
    assert report["equity"] == "1945"
    assert report["net_pnl"] == "-105"
    assert report["fees_paid"] == "5"
    assert report["slippage_cost"] == "100"
    assert Decimal(report["net_return"]) == Decimal("-0.051219512195")
    assert Decimal(report["max_drawdown"]) == -Decimal(report["net_return"])
    assert report["position_contributions"][0]["net_pnl"] == "-105"
    assert report["pnl_reconciliation_residual"] == "0"
    assert report["equity_series"][0]["equity"] == "2050"
    assert report["corporate_action_coverage_complete"] is False


def test_health_requires_enough_settled_evidence_and_pauses_only_simulation():
    report = paper_book_performance(
        _book(
            _replay(
                [_bar(day) for day in DAYS[:2]],
                [_target(1)],
                initial_cash=Decimal("2050"),
                cost_config=_cost(minimum="5", slip="1"),
            )
        )
    )
    policy = {
        "mode": "pause_on_breach",
        "minimum_settled_sessions": 2,
        "maximum_drawdown": "0.01",
        "minimum_net_excess_return": "-0.01",
    }
    assert evaluate_paper_health(report, policy)["status"] == "insufficient_evidence"
    policy["minimum_settled_sessions"] = 1
    health = evaluate_paper_health(report, policy)
    assert health["status"] == "threshold_breached"
    assert health["action"] == "pause_paper_target_acceptance"
    assert health["account_authority"] is False
    assert health["qualification_authority"] is False
    unavailable = {**report, "benchmark_status": "unavailable"}
    assert evaluate_paper_health(unavailable, policy)["action"] == "none"


def test_cash_days_before_any_accepted_target_cannot_satisfy_health_sample_requirement():
    report = paper_book_performance(_book(_replay([_bar(day) for day in DAYS[:3]], [])))
    policy = {
        "mode": "pause_on_breach",
        "minimum_settled_sessions": 1,
        "maximum_drawdown": "1",
        "minimum_net_excess_return": "0",
    }
    assert report["settled_sessions"] == 2
    assert report["accepted_publication_count"] == 0
    assert evaluate_paper_health(report, policy)["status"] == "insufficient_evidence"
    assert evaluate_paper_health(report, policy)["action"] == "none"
