from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.services.daily_trading_plan import build_daily_trading_plan


def _fee_config() -> SimpleNamespace:
    return SimpleNamespace(
        account_commission_rate=0.00015,
        account_min_commission=5.0,
        broker_fee_schedule=SimpleNamespace(
            stock_a_commission_rate=0.00015,
            stock_a_min_commission=5.0,
            fund_etf_commission_rate=0.00012,
            fund_etf_min_commission=3.0,
            stamp_tax_rate=0.0005,
            transfer_fee_rate=0.00001,
            other_fee_rate=0,
            limitations=("broker_regulatory_fees_assumed_absorbed",),
        ),
    )


def _plan(
    *,
    candidate: dict | None = None,
    cash: float = 30000.0,
    total_equity: float = 50000.0,
    portfolio_extra: dict | None = None,
    positions: dict | None = None,
) -> dict:
    portfolio = {
        "cash": cash,
        "total_equity": total_equity,
        "position_count": len(positions or {}),
    }
    portfolio.update(portfolio_extra or {})
    return build_daily_trading_plan(
        decision_payload={
            "decision_date": "2026-07-01",
            "decision": (candidate or {}).get("action", "buy"),
            "summary": {
                "candidate_count": 1,
                "ready_for_manual_confirmation_count": 1,
                "portfolio": portfolio,
                "account_truth": {"gate_status": "pass"},
                "market_data": {"source_health": "live"},
            },
            "candidates": [candidate or _candidate()],
        },
        config=_fee_config(),
        positions=positions or {},
    )


def _candidate(
    *,
    action_id: int = 1,
    action: str = "buy",
    symbol: str = "600519",
    asset_class: str = "stock",
    target_weight: float = 0.2,
    price: float = 10.0,
    risk_status: str = "passed",
    manual_status: str = "ready_for_manual_confirmation",
    risk_reasons: list[str] | None = None,
    risk_decision_id: str | None = None,
    account_truth_import_run_id: str | None = None,
) -> dict:
    return {
        "action_id": action_id,
        "action": action,
        "symbol": symbol,
        "asset_class": asset_class,
        "title": f"{action} candidate",
        "target_weight": target_weight,
        "price": price,
        "risk_gate_status": risk_status,
        "risk_gate_reasons": risk_reasons or [],
        "manual_confirmation_required": True,
        "manual_confirmation_status": manual_status,
        "evidence": {
            "strategy": {"strategy_id": "dual_ma"},
            "risk_gate": {
                "status": risk_status,
                "passed": risk_status == "passed",
                "decision_id": risk_decision_id,
            },
            "account_truth": {
                "gate_status": "pass",
                "import_run_id": account_truth_import_run_id,
            },
            "data_freshness": {"status": "live"},
        },
    }


def test_trading_plan_carries_risk_and_account_truth_evidence_refs() -> None:
    plan = _plan(
        candidate=_candidate(
            risk_decision_id="RISK-123",
            account_truth_import_run_id="import-456",
        )
    )

    refs = plan["order_intents"][0]["evidence_refs"]
    assert "risk:RISK-123" in refs
    assert "account_truth:import-456" in refs


def test_trading_plan_blocker_summary_preserves_specific_risk_gate_reasons() -> None:
    plan = build_daily_trading_plan(
        decision_payload={
            "decision_date": "2026-07-01",
            "decision": "review_required",
            "summary": {
                "candidate_count": 2,
                "ready_for_manual_confirmation_count": 0,
                "portfolio": {"cash": 30000.0, "total_equity": 50000.0},
                "account_truth": {"gate_status": "pass"},
                "market_data": {"source_health": "live"},
            },
            "candidates": [
                _candidate(
                    action_id=1,
                    symbol="510300",
                    risk_status="blocked",
                    manual_status="blocked_by_risk_gate",
                    risk_reasons=["cash reserve would fall below min_cash_reserve"],
                ),
                _candidate(
                    action_id=2,
                    symbol="600519",
                    risk_status="blocked",
                    manual_status="blocked_by_risk_gate",
                    risk_reasons=[
                        "projected position weight exceeds max_position_weight"
                    ],
                ),
            ],
        },
        config=_fee_config(),
    )

    assert plan["conclusion_status"] == "risk_blocked"
    assert plan["blocker_summary"] == [
        {
            "category": "risk",
            "target": "risk",
            "count": 2,
            "reasons": [
                "cash reserve would fall below min_cash_reserve",
                "projected position weight exceeds max_position_weight",
            ],
            "sample_symbols": ["510300", "600519"],
        }
    ]


def _constraint_map(intent: dict) -> dict[str, dict]:
    return {item["id"]: item for item in intent["constraint_checks"]}


def test_trading_plan_turns_manual_ready_candidate_into_order_intent_preview() -> None:
    plan = build_daily_trading_plan(
        decision_payload={
            "decision_date": "2026-07-01",
            "decision": "buy",
            "summary": {
                "candidate_count": 1,
                "ready_for_manual_confirmation_count": 1,
                "portfolio": {
                    "cash": 30000.0,
                    "total_equity": 50000.0,
                    "position_count": 0,
                },
                "account_truth": {"gate_status": "pass"},
                "market_data": {"source_health": "live"},
            },
            "candidates": [_candidate()],
        },
        config=_fee_config(),
        positions={
            "600519": {
                "quantity": 200.0,
                "avg_cost": 8.0,
                "market_value": 2000.0,
            }
        },
    )

    assert plan["schema_version"] == "karkinos.daily_trading_plan.v1"
    assert plan["conclusion_status"] == "manual_confirmation_ready"
    assert plan["candidate_pool_count"] == 1
    assert plan["manual_ready_count"] == 1
    assert plan["order_intent_count"] == 1
    assert plan["account_truth"]["gate_status"] == "pass"
    assert plan["account_truth"]["has_evidence"] is True
    assert plan["account_truth"]["blocking_reasons"] == []

    intent = plan["order_intents"][0]
    assert intent["action_id"] == 1
    assert intent["symbol"] == "600519"
    assert intent["side"] == "buy"
    assert intent["target_weight"] == pytest.approx(0.2)
    assert intent["estimated_price"] == pytest.approx(10.0)
    assert intent["estimated_quantity"] == pytest.approx(800.0)
    assert intent["estimated_gross_amount"] == pytest.approx(8000.0)
    assert intent["fee_breakdown"]["commission"] == "5.00"
    assert intent["fee_breakdown"]["transfer_fee"] == "0.080000"
    assert intent["estimated_total_fee"] == pytest.approx(5.08)
    assert intent["estimated_net_cash_impact"] == pytest.approx(-8005.08)
    assert intent["quantity_basis"] == "target_position_delta_lot_rounded"
    assert intent["position_effect"] == {
        "current_quantity": 200.0,
        "current_avg_cost": 8.0,
        "current_market_value": 2000.0,
        "estimated_quantity_after": 1000.0,
        "estimated_avg_cost_after": pytest.approx(9.6),
        "cost_basis_method": "weighted_average_preview",
    }
    assert intent["submission_status"] == "manual_confirmation_required"
    assert intent["cash_status"] == "sufficient"
    assert intent["cash_shortfall"] == 0.0
    checks = _constraint_map(intent)
    assert checks["trading_unit"]["status"] == "pass"
    assert checks["fee_tax_preview"]["status"] == "pass"
    assert checks["cash_buffer"]["status"] == "pass"
    assert checks["concentration"]["status"] == "pass"
    assert intent["does_not_submit_broker_order"] is True


def test_trading_plan_blocks_buy_intent_when_cash_is_insufficient() -> None:
    plan = build_daily_trading_plan(
        decision_payload={
            "decision_date": "2026-07-01",
            "decision": "buy",
            "summary": {
                "candidate_count": 1,
                "ready_for_manual_confirmation_count": 1,
                "portfolio": {
                    "cash": 1000.0,
                    "total_equity": 50000.0,
                    "position_count": 0,
                },
                "account_truth": {"gate_status": "pass"},
                "market_data": {"source_health": "live"},
            },
            "candidates": [_candidate()],
        },
        config=_fee_config(),
    )

    assert plan["conclusion_status"] == "cash_shortfall"
    assert plan["primary_target"] == "portfolio"
    assert plan["manual_ready_count"] == 0
    assert plan["order_intent_count"] == 1
    assert plan["blocked_count"] == 1

    intent = plan["order_intents"][0]
    assert intent["cash_status"] == "insufficient_cash"
    assert intent["cash_shortfall"] == pytest.approx(9005.1)
    assert intent["submission_status"] == "blocked_by_cash_shortfall"
    assert plan["blockers"][0]["reason"] == "insufficient_cash"
    assert plan["blockers"][0]["target"] == "portfolio"


def test_trading_plan_blocks_buy_intent_when_cash_buffer_would_be_breached() -> None:
    plan = _plan(cash=11500.0)

    assert plan["conclusion_status"] == "portfolio_blocked"
    assert plan["manual_ready_count"] == 0
    assert plan["blocked_count"] == 1

    intent = plan["order_intents"][0]
    assert intent["submission_status"] == "blocked_by_cash_buffer"
    assert intent["cash_status"] == "cash_buffer_breached"
    checks = _constraint_map(intent)
    assert checks["cash_buffer"]["status"] == "blocked"
    assert checks["cash_buffer"]["required_cash"] == pytest.approx(1500.0)
    assert plan["blockers"][0]["reason"] == "cash_buffer_breached"


def test_trading_plan_blocks_intent_when_concentration_limit_would_be_breached() -> (
    None
):
    plan = _plan(
        candidate=_candidate(target_weight=0.5),
        cash=40000.0,
        positions={
            "600519": {
                "quantity": 1000.0,
                "avg_cost": 10.0,
                "market_value": 10000.0,
            }
        },
    )

    assert plan["conclusion_status"] == "portfolio_blocked"
    intent = plan["order_intents"][0]
    assert intent["submission_status"] == "blocked_by_concentration"
    checks = _constraint_map(intent)
    assert checks["concentration"]["status"] == "blocked"
    assert checks["concentration"]["estimated_weight_after"] > 0.35
    assert plan["blockers"][0]["reason"] == "concentration_limit_breached"


def test_trading_plan_blocks_sell_when_t1_available_quantity_is_insufficient() -> None:
    plan = _plan(
        candidate=_candidate(action="sell", target_weight=0.0, price=12.0),
        positions={
            "600519": {
                "quantity": 300.0,
                "avg_cost": 8.0,
                "market_value": 3600.0,
                "t1_available_quantity": 100.0,
            }
        },
    )

    intent = plan["order_intents"][0]
    assert intent["submission_status"] == "blocked_by_t1_available_quantity"
    checks = _constraint_map(intent)
    assert checks["t1_available_quantity"]["status"] == "blocked"
    assert checks["t1_available_quantity"]["available_quantity"] == 100.0
    assert plan["blockers"][0]["reason"] == "t1_available_quantity_insufficient"


def test_trading_plan_blocks_china_market_price_and_status_constraints() -> None:
    scenarios = [
        (
            _candidate(action="buy", symbol="600001") | {"limit_status": "limit_up"},
            "blocked_by_limit_up",
            "limit_up_blocked",
        ),
        (
            _candidate(action="sell", symbol="600002")
            | {
                "limit_status": "limit_down",
                "quantity": 100,
                "t1_available_quantity": 100,
            },
            "blocked_by_limit_down",
            "limit_down_blocked",
        ),
        (
            _candidate(symbol="600003") | {"trading_status": "suspended"},
            "blocked_by_suspension",
            "security_suspended",
        ),
        (
            _candidate(symbol="600004", asset_class="stock")
            | {"special_treatment": True},
            "blocked_by_special_treatment",
            "special_treatment_risk",
        ),
    ]

    for candidate, submission_status, blocker_reason in scenarios:
        plan = _plan(candidate=candidate)
        intent = plan["order_intents"][0]
        assert intent["submission_status"] == submission_status
        assert plan["blockers"][0]["reason"] == blocker_reason


def test_trading_plan_blocks_when_drawdown_risk_threshold_is_breached() -> None:
    plan = _plan(portfolio_extra={"current_drawdown": 0.12})

    assert plan["conclusion_status"] == "risk_blocked"
    intent = plan["order_intents"][0]
    assert intent["submission_status"] == "blocked_by_drawdown"
    checks = _constraint_map(intent)
    assert checks["drawdown"]["status"] == "blocked"
    assert checks["drawdown"]["current_drawdown"] == pytest.approx(0.12)
    assert plan["blockers"][0]["reason"] == "drawdown_limit_breached"


def test_trading_plan_keeps_large_candidate_pool_out_of_manual_order_intents() -> None:
    candidates = [
        _candidate(
            action_id=index + 1,
            risk_status="not_checked",
            manual_status="awaiting_risk_gate",
        )
        for index in range(50)
    ]

    plan = build_daily_trading_plan(
        decision_payload={
            "decision_date": "2026-07-01",
            "decision": "review_required",
            "summary": {
                "candidate_count": 50,
                "ready_for_manual_confirmation_count": 0,
                "portfolio": {"cash": 30000.0, "total_equity": 50000.0},
                "account_truth": {"gate_status": "pass"},
                "market_data": {"source_health": "live"},
            },
            "candidates": candidates,
        },
        config=_fee_config(),
    )

    assert plan["candidate_pool_count"] == 50
    assert plan["manual_ready_count"] == 0
    assert plan["order_intent_count"] == 0
    assert plan["conclusion_status"] == "no_manual_action"
    assert plan["blocked_count"] == 50
    assert {item["reason"] for item in plan["blockers"]} == {"awaiting_risk_gate"}
    assert plan["blocker_summary"] == [
        {
            "category": "evidence_not_ready",
            "target": "risk",
            "count": 50,
            "reasons": ["awaiting_risk_gate"],
            "sample_symbols": ["600519"],
        }
    ]


def test_trading_plan_sell_intent_uses_current_position_for_remaining_quantity() -> (
    None
):
    plan = build_daily_trading_plan(
        decision_payload={
            "decision_date": "2026-07-01",
            "decision": "sell",
            "summary": {
                "candidate_count": 1,
                "ready_for_manual_confirmation_count": 1,
                "portfolio": {
                    "cash": 30000.0,
                    "total_equity": 50000.0,
                },
                "account_truth": {"gate_status": "pass"},
                "market_data": {"source_health": "live"},
            },
            "candidates": [
                _candidate(action_id=3, action="sell", target_weight=0.0, price=12.0)
            ],
        },
        config=_fee_config(),
        positions={
            "600519": {
                "quantity": 300.0,
                "avg_cost": 8.0,
                "market_value": 3600.0,
            }
        },
    )

    intent = plan["order_intents"][0]
    assert intent["side"] == "sell"
    assert intent["estimated_quantity"] == 300.0
    assert intent["estimated_net_cash_impact"] == pytest.approx(3593.164)
    assert intent["position_effect"] == {
        "current_quantity": 300.0,
        "current_avg_cost": 8.0,
        "current_market_value": 3600.0,
        "estimated_quantity_after": 0.0,
        "estimated_avg_cost_after": None,
        "cost_basis_method": "sell_reduces_position_preview",
    }


def test_trading_plan_blocks_manual_intents_when_account_truth_is_blocked() -> None:
    plan = build_daily_trading_plan(
        decision_payload={
            "decision_date": "2026-07-01",
            "decision": "review_required",
            "summary": {
                "candidate_count": 1,
                "ready_for_manual_confirmation_count": 1,
                "portfolio": {"cash": 30000.0, "total_equity": 50000.0},
                "account_truth": {"gate_status": "blocked"},
                "market_data": {"source_health": "live"},
            },
            "candidates": [_candidate()],
        },
        config=_fee_config(),
    )

    assert plan["manual_ready_count"] == 0
    assert plan["order_intent_count"] == 0
    assert plan["conclusion_status"] == "account_truth_blocked"
    assert plan["primary_target"] == "account-truth"
    assert plan["blockers"][0]["reason"] == "account_truth_blocked"
    assert plan["blocker_summary"] == [
        {
            "category": "account_truth",
            "target": "account-truth",
            "count": 1,
            "reasons": ["account_truth_blocked"],
            "sample_symbols": ["600519"],
        }
    ]
