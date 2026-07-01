from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi.routing import APIRoute

from server.routes import operations as operations_routes


def _endpoint(path: str, method: str = "GET"):
    router = operations_routes.create_router()
    return next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


class FakeOperationsDb:
    def __init__(self) -> None:
        self.saved_manual_orders: list[dict] = []
        self.recorded_orders: list[dict] = []
        self.ledger_writes: list[dict] = []

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

    def list_manual_orders_sync(self, status=None, limit=50, offset=0):
        return []

    def list_orders_sync(self, status=None, symbol=None, limit=100, offset=0):
        return []

    def list_fills_sync(self, order_id=None, symbol=None, limit=100, offset=0):
        return []

    def get_ledger_entries_sync(self, limit=50, offset=0):
        return []

    def save_manual_order_sync(self, *args, **kwargs):
        raise AssertionError("operations route must not save manual orders")

    def record_order_sync(self, *args, **kwargs):
        raise AssertionError("operations route must not record orders")

    def save_ledger_entry_sync(self, *args, **kwargs):
        raise AssertionError("operations route must not write ledger entries")


def test_today_operations_route_returns_read_only_runbook(monkeypatch):
    fake_db = FakeOperationsDb()
    fake_state = SimpleNamespace(
        db=fake_db,
        config=SimpleNamespace(
            assets=[],
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

    endpoint = _endpoint("/api/operations/today")
    response = asyncio.run(endpoint())

    assert response["schema_version"] == "karkinos.operations_today.v1"
    assert response["conclusion_status"] == "manual_action_required"
    assert response["daily_plan"]["order_intent_count"] == 1
    assert response["paper_shadow"]["status"] == "not_run"
    assert response["paper_shadow"]["next_manual_review_step"] == (
        "run_paper_shadow_daily"
    )
    assert response["limitations"][0].startswith("Operations summary is read-only")
    assert fake_db.saved_manual_orders == []
    assert fake_db.recorded_orders == []
    assert fake_db.ledger_writes == []
