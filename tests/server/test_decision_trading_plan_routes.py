from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

from fastapi.routing import APIRoute

from server.routes import decision as decision_routes


def _endpoint(path: str, method: str = "GET"):
    router = decision_routes.create_router()
    return next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


class FakeDecisionDb:
    def __init__(self) -> None:
        self.manual_orders: list[dict] = []
        self.order_facts: list[dict] = []
        self.ledger_entries: list[dict] = []

    def get_action_tasks_sync(self, statuses=None, limit=50, offset=0):
        return [
            {
                "id": 7,
                "source_signal_id": 17,
                "symbol": "600519",
                "title": "买入候选",
                "detail": "dual_ma 触发，目标仓位 20%",
                "direction": "buy",
                "urgency": "high",
                "target_weight": 0.2,
                "price": 10.0,
                "strategy_id": "dual_ma",
                "timestamp": "2026-07-01T09:45:00+08:00",
                "asset_class": "stock",
                "risk_gate_status": "passed",
                "risk_gate_passed": True,
                "risk_gate_severity": "info",
                "risk_gate_reasons": [],
                "manual_confirmation_required": True,
                "manual_confirmation_status": "ready_for_manual_confirmation",
                "manual_confirmation_reason": (
                    "Risk gate passed; manual confirmation is required."
                ),
            }
        ][offset : offset + limit]

    def list_signal_journal_sync(self, limit=50, offset=0):
        return []

    async def get_backtest_results(self):
        return []

    def get_account_truth_score_sync(self):
        return {
            "gate_status": "pass",
            "score": 98,
            "has_evidence": True,
            "unresolved_mismatch_count": 0,
        }

    def get_runtime_control_sync(self, key):
        return None

    def get_latest_quote_sync(self, symbol, asset_type=None):
        return {
            "symbol": symbol,
            "asset_type": asset_type or "stock",
            "price": 10.0,
            "quote_status": "live",
            "quote_timestamp": "2026-07-01T09:45:00+08:00",
            "quote_source": "fixture",
        }

    def list_latest_quotes_sync(self):
        return [self.get_latest_quote_sync("600519", asset_type="stock")]

    def save_manual_order_sync(self, *args, **kwargs):
        raise AssertionError("trading plan must not save manual orders")

    def record_order_sync(self, *args, **kwargs):
        raise AssertionError("trading plan must not record order facts")

    def save_ledger_entry_sync(self, *args, **kwargs):
        raise AssertionError("trading plan must not write ledger entries")


def test_decision_account_truth_gate_uses_current_promotion_evidence(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "server.account_truth_gate.build_latest_account_truth_promotion_evidence",
        lambda state: {
            "schema_version": "karkinos.account_truth.promotion_evidence.v1",
            "status": "blocked",
            "gate_status": "pass",
            "score": 100,
            "import_run_id": "import-stale",
            "source_fingerprint": "a" * 64,
            "captured_at": "2026-07-01T15:00:00+08:00",
            "current_age_seconds": 90000,
            "max_age_seconds": 86400,
            "data_freshness_status": "stale",
            "unresolved_mismatch_count": 0,
            "reconciliation_status": "pass",
            "ledger_coverage": {"status": "covered"},
            "blockers": ["account_truth_import_stale"],
        },
    )

    result = decision_routes._account_truth_gate_evidence(SimpleNamespace())

    assert result["gate_status"] == "blocked"
    assert result["promotion_status"] == "blocked"
    assert result["data_freshness_status"] == "stale"
    assert result["blocking_reasons"] == ["account_truth_import_stale"]
    assert result["source_fingerprint"] == "a" * 64


def test_decision_trading_plan_route_returns_read_only_order_intent(monkeypatch):
    fake_db = FakeDecisionDb()
    fake_state = SimpleNamespace(
        db=fake_db,
        config=SimpleNamespace(
            assets=[],
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
        ),
        scheduler=SimpleNamespace(
            watchlist=[],
            latest_quotes={},
            portfolio=SimpleNamespace(
                cash=30000.0,
                positions={
                    "600519": SimpleNamespace(
                        quantity=200.0,
                        avg_cost=8.0,
                        market_value=2000.0,
                    )
                },
                total_equity=lambda: 50000.0,
            ),
        ),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        decision_routes,
        "_account_truth_gate_evidence",
        lambda state: {
            "gate_status": "pass",
            "data_freshness_status": "fresh",
            "unresolved_mismatch_count": 0,
            "import_run_id": "fixture-import",
        },
    )
    monkeypatch.setattr(
        decision_routes,
        "resolve_strategy_order_generation_gate",
        lambda db, strategy_id, *, as_of_date=None: (
            {
                "status": "pass",
                "strategy_id": strategy_id,
                "paper_shadow_evaluation_only": True,
                "does_not_authorize_execution": True,
                "promotion": {
                    "strategy_advancement_gate_fingerprint": "fixture-gate",
                },
            },
            [],
        ),
    )

    endpoint = _endpoint("/api/decision/trading-plan")
    response = asyncio.run(endpoint())

    assert response["schema_version"] == "karkinos.daily_trading_plan.v1"
    generated_at = datetime.fromisoformat(response["generated_at"])
    assert generated_at.tzinfo is not None
    assert generated_at.utcoffset() is not None
    assert response["conclusion_status"] == "paper_shadow_required"
    assert response["candidate_pool_count"] == 1
    assert response["manual_ready_count"] == 0
    assert response["paper_shadow_ready_count"] == 1
    assert response["order_intent_count"] == 1
    assert response["default_execution_mode"] == "manual_confirmation"
    assert response["broker_bridge_status"] == "disabled"

    intent = response["order_intents"][0]
    assert intent["action_id"] == 7
    assert intent["symbol"] == "600519"
    assert intent["side"] == "buy"
    assert intent["estimated_quantity"] == 800.0
    assert intent["estimated_net_cash_impact"] == -8005.08
    assert intent["position_effect"]["current_quantity"] == 200.0
    assert intent["position_effect"]["estimated_quantity_after"] == 1000.0
    assert intent["position_effect"]["cost_basis_method"] == "weighted_average_preview"
    assert intent["submission_status"] == "paper_shadow_required"
    assert intent["does_not_submit_broker_order"] is True
    assert fake_db.manual_orders == []
    assert fake_db.order_facts == []
    assert fake_db.ledger_entries == []
