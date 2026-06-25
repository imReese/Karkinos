"""Backtest strategy signal-preview route tests."""

from __future__ import annotations

import asyncio

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
