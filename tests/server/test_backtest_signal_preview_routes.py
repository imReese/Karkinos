"""Backtest strategy signal-preview route tests."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute


def _route(router, path: str, method: str = "GET"):
    return next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


def test_backtest_signal_preview_route_returns_research_only_candidate() -> None:
    from server.routes import backtest as backtest_routes

    router = backtest_routes.create_router()
    endpoint = _route(router, "/api/backtest/signal-preview", "POST").endpoint

    response = asyncio.run(
        endpoint(
            backtest_routes.StrategySignalPreviewRequest(
                strategy="dual_ma",
                symbol="600000",
                params={"short_period": "2", "long_period": "3"},
                bars=[
                    {"timestamp": "2026-06-01T15:00:00+00:00", "close": 3},
                    {"timestamp": "2026-06-02T15:00:00+00:00", "close": 2},
                    {"timestamp": "2026-06-03T15:00:00+00:00", "close": 1},
                    {"timestamp": "2026-06-04T15:00:00+00:00", "close": 4},
                ],
                dataset_snapshot={
                    "schema_version": "karkinos.dataset_snapshot.v1",
                    "snapshot_id": "route-snapshot-001",
                    "data_quality": {"status": "pass"},
                },
            )
        )
    )

    assert response.schema_version == "karkinos.strategy_signal_preview.v1"
    assert response.strategy_id == "dual_ma"
    assert response.symbol == "600000"
    assert response.params == {"short_period": 2, "long_period": 3}
    assert response.dataset_snapshot_id == "route-snapshot-001"
    assert response.record_count == 1
    assert response.does_not_enable_execution is True

    record = response.outputs[0]
    assert record["output_type"] == "buy_candidate"
    assert record["record_kind"] == "candidate_action"
    assert record["requires_risk_gate"] is True
    assert record["requires_account_truth_gate"] is True
    assert record["requires_paper_shadow_review"] is True
    assert record["requires_manual_review"] is True
    assert record["does_not_enable_execution"] is True


def test_backtest_signal_preview_route_can_load_server_side_bars(monkeypatch) -> None:
    import pandas as pd

    from core.types import AssetClass, BarFrequency, Symbol
    from data.handler import DataHandler
    from server.routes import backtest as backtest_routes

    class FakeStore:
        pass

    class FakeDataManager:
        def __init__(self, *args, **kwargs):
            pass

        def get_bars(self, symbol, start, end, asset_class):
            assert symbol == Symbol("600000")
            assert asset_class == AssetClass.STOCK
            assert start.strftime("%Y-%m-%d") == "2026-06-01"
            assert end.strftime("%Y-%m-%d") == "2026-06-04"
            prices = [3, 2, 1, 4]
            df = pd.DataFrame(
                {
                    "timestamp": pd.date_range("2026-06-01", periods=4),
                    "open": prices,
                    "high": prices,
                    "low": prices,
                    "close": prices,
                    "volume": [1000] * 4,
                }
            )
            return DataHandler(
                df,
                symbol,
                frequency=BarFrequency.DAILY,
                asset_class=asset_class,
            )

    monkeypatch.setattr("data.store.DataStore", FakeStore)
    monkeypatch.setattr("data.manager.DataManager", FakeDataManager)
    monkeypatch.setattr(
        "data.manager.build_sources", lambda **kwargs: {"fixture": object()}
    )

    router = backtest_routes.create_router()
    endpoint = _route(router, "/api/backtest/signal-preview", "POST").endpoint

    response = asyncio.run(
        endpoint(
            backtest_routes.StrategySignalPreviewRequest(
                strategy="dual_ma",
                symbol="600000",
                asset_class="stock",
                start_date="2026-06-01",
                end_date="2026-06-04",
                params={"short_period": "2", "long_period": "3"},
            )
        )
    )

    assert response.dataset_snapshot_id is not None
    assert response.record_count == 1
    record = response.outputs[0]
    assert record["output_type"] == "buy_candidate"
    assert record["evidence"]["bar_count"] == 4
    assert record["evidence"]["data_quality_status"] == "ok"
    assert record["requires_risk_gate"] is True
    assert record["does_not_enable_execution"] is True


def test_backtest_signal_preview_route_rejects_unknown_params_before_running(
    monkeypatch,
) -> None:
    from fastapi import HTTPException

    from server.routes import backtest as backtest_routes

    router = backtest_routes.create_router()
    endpoint = _route(router, "/api/backtest/signal-preview", "POST").endpoint

    def fail_if_called(*args, **kwargs):
        raise AssertionError("signal preview should not run invalid params")

    monkeypatch.setattr(backtest_routes, "_run_strategy_signal_preview", fail_if_called)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            endpoint(
                backtest_routes.StrategySignalPreviewRequest(
                    strategy="dual_ma",
                    symbol="600000",
                    params={"unknown": 1},
                    bars=[
                        {"timestamp": "2026-06-01T15:00:00+00:00", "close": 3},
                    ],
                )
            )
        )

    assert error.value.status_code == 422
    assert error.value.detail == {
        "strategy": "dual_ma",
        "errors": [
            {
                "field": "unknown",
                "code": "unknown_parameter",
                "message": "Unknown parameter 'unknown' for strategy 'dual_ma'.",
            }
        ],
    }


def test_backtest_risk_preview_route_evaluates_without_order_or_audit_writes(
    monkeypatch,
) -> None:
    from core.event_bus import EventBus
    from domain.portfolio import Portfolio
    from server.routes import backtest as backtest_routes
    from server.services.trading_controls import TradingControlState

    controls = TradingControlState()
    controls.set_kill_switch(True, "operator stop")
    portfolio = Portfolio(EventBus(), initial_cash=Decimal("100000"))
    forbidden_calls: list[str] = []

    def forbid(name: str):
        def _inner(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError(f"{name} should not be called by risk preview")

        return _inner

    fake_state = SimpleNamespace(
        scheduler=SimpleNamespace(portfolio=portfolio),
        trading_controls=controls,
        db=SimpleNamespace(
            save_risk_decision_sync=forbid("save_risk_decision_sync"),
            record_order_sync=forbid("record_order_sync"),
        ),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    router = backtest_routes.create_router()
    endpoint = _route(router, "/api/backtest/risk-preview", "POST").endpoint

    response = asyncio.run(
        endpoint(
            backtest_routes.BacktestRiskPreviewRequest(
                strategy="dual_ma",
                symbol="600000",
                asset_class="stock",
                action="buy",
                quantity=100,
                reference_price=10,
                target_weight="1.0",
                data_quality_status="pass",
            )
        )
    )

    assert response["schema_version"] == "karkinos.pre_trade_risk_preview.v1"
    assert response["passed"] is False
    assert response["status"] == "blocked"
    assert response["reasons"] == ["kill switch is enabled: buy orders are blocked"]
    assert response["manual_confirmation_required"] is True
    assert response["does_not_create_order"] is True
    assert response["does_not_persist_decision"] is True
    assert response["metadata"]["quantity"] == "100"
    assert response["metadata"]["reference_price"] == "10"
    assert response["metadata"]["target_weight"] == "1.0"
    assert response["metadata"]["order_value"] == "1000"
    assert forbidden_calls == []


def test_backtest_paper_shadow_preview_route_simulates_without_order_or_fill_writes(
    monkeypatch,
) -> None:
    from server.routes import backtest as backtest_routes

    forbidden_calls: list[str] = []

    def forbid(name: str):
        def _inner(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError(f"{name} should not be called by paper/shadow preview")

        return _inner

    fake_state = SimpleNamespace(
        db=SimpleNamespace(
            record_order_sync=forbid("record_order_sync"),
            record_fill_sync=forbid("record_fill_sync"),
            record_shadow_divergence_review_sync=forbid(
                "record_shadow_divergence_review_sync"
            ),
        ),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    router = backtest_routes.create_router()
    endpoint = _route(router, "/api/backtest/paper-shadow-preview", "POST").endpoint

    response = asyncio.run(
        endpoint(
            backtest_routes.BacktestPaperShadowPreviewRequest(
                strategy="dual_ma",
                symbol="600000",
                asset_class="stock",
                action="buy",
                quantity=100,
                reference_price=10,
                target_weight="1.0",
                signal_id="preview-run-001:0001:buy_candidate",
                dataset_snapshot_id="sha256:preview-dataset",
                risk_preview_passed=True,
                risk_reasons=["approved"],
            )
        )
    )

    assert response["schema_version"] == "karkinos.paper_shadow_preview.v1"
    assert response["status"] == "simulated"
    assert response["execution_mode"] == "paper_shadow_preview"
    assert response["manual_confirmation_required"] is True
    assert response["does_not_create_order"] is True
    assert response["does_not_create_fill"] is True
    assert response["does_not_mutate_ledger"] is True
    assert response["order"]["execution_mode"] == "paper_shadow_preview"
    assert response["order"]["status"] == "filled"
    assert response["order"]["symbol"] == "600000"
    assert response["order"]["context"]["strategy_id"] == "dual_ma"
    assert response["order"]["context"]["signal_id"] == (
        "preview-run-001:0001:buy_candidate"
    )
    assert response["order"]["context"]["dataset_id"] == "sha256:preview-dataset"
    assert response["fill"]["execution_mode"] == "paper_shadow_preview"
    assert response["fill"]["fill_price"] == "10"
    assert response["fill"]["fill_quantity"] == "100"
    assert response["fill"]["fee_breakdown"]["gross_amount"] == "1000"
    assert Decimal(response["fill"]["fee_breakdown"]["total_fee"]) == Decimal("5.010")
    assert response["shadow_review"]["candidate_count"] == 1
    assert response["shadow_review"]["supported_match_count"] == 0
    assert forbidden_calls == []
