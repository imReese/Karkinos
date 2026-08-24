"""Canonical backtest parameter sweep projections."""

from __future__ import annotations

import itertools
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from server.models import (
    BacktestMetrics,
    BacktestRequest,
    BacktestSweepRequest,
)
from server.services.backtest_result_projection import json_object as _json_object

_SWEEP_RANK_DIRECTIONS = {
    "total_return": "desc",
    "annual_return": "desc",
    "sharpe": "desc",
    "sortino": "desc",
    "win_rate": "desc",
    "max_drawdown": "asc",
}


def build_parameter_grid(
    request: BacktestSweepRequest,
) -> list[dict[str, Any]]:
    """Expand a bounded parameter grid into deterministic parameter payloads."""
    errors: list[dict[str, Any]] = []
    if request.rank_by not in _SWEEP_RANK_DIRECTIONS:
        allowed = sorted(_SWEEP_RANK_DIRECTIONS)
        errors.append(
            {
                "field": "rank_by",
                "code": "unsupported_rank_metric",
                "message": f"rank_by must be one of: {allowed}.",
            }
        )

    if not request.param_grid:
        errors.append(
            {
                "field": "param_grid",
                "code": "required_field_missing",
                "message": "Parameter sweep requires at least one grid field.",
            }
        )

    combination_count = 1
    for name, values in request.param_grid.items():
        if not isinstance(values, list) or len(values) == 0:
            errors.append(
                {
                    "field": name,
                    "code": "invalid_parameter_grid",
                    "message": "Each sweep parameter must provide a non-empty list.",
                }
            )
            continue
        combination_count *= len(values)

    if combination_count > request.max_combinations:
        errors.append(
            {
                "field": "param_grid",
                "code": "parameter_grid_too_large",
                "message": (
                    f"Parameter grid expands to {combination_count} combinations, "
                    f"which exceeds max_combinations={request.max_combinations}."
                ),
            }
        )

    if errors:
        raise HTTPException(
            status_code=422,
            detail={"strategy": request.strategy, "errors": errors},
        )

    names = list(request.param_grid.keys())
    base_params = dict(request.params or {})
    return [
        {**base_params, **dict(zip(names, values))}
        for values in itertools.product(*(request.param_grid[name] for name in names))
    ]


def sweep_score(metrics: BacktestMetrics, rank_by: str) -> float:
    return float(getattr(metrics, rank_by))


def dataset_snapshot_from_result(result: dict[str, Any]) -> dict[str, Any]:
    metrics_json = _json_object(result.get("metrics_json"))
    return _json_object(metrics_json.get("dataset_snapshot"))


def dataset_snapshot_id(snapshot: dict[str, Any]) -> str | None:
    snapshot_id = snapshot.get("snapshot_id")
    return str(snapshot_id) if snapshot_id else None


def build_oos_validation_payload(
    request: BacktestRequest,
    result: Any,
) -> dict[str, Any]:
    if request.oos_mode == "rolling":
        return build_rolling_oos_validation_payload(request, result)

    if not request.oos_split_date:
        return {}

    from datetime import datetime

    import strategy.builtins  # noqa: F401
    from analytics.oos_validation import build_out_of_sample_validation
    from strategy.registry import StrategyRegistry

    strategy_info = StrategyRegistry.get(request.strategy) or {}
    benchmark_role = strategy_info.get("benchmark_role") or request.strategy
    benchmark_return = (
        Decimal(str(request.benchmark_return))
        if request.benchmark_return is not None
        else None
    )
    evidence = build_out_of_sample_validation(
        strategy_id=request.strategy,
        benchmark_role=benchmark_role,
        result=result,
        split_timestamp=datetime.strptime(request.oos_split_date, "%Y-%m-%d"),
        benchmark_return=benchmark_return,
    )
    return evidence.to_json_dict()


def build_rolling_oos_validation_payload(
    request: BacktestRequest,
    result: Any,
) -> dict[str, Any]:
    import strategy.builtins  # noqa: F401
    from analytics.oos_validation import build_rolling_out_of_sample_validation
    from strategy.registry import StrategyRegistry

    strategy_info = StrategyRegistry.get(request.strategy) or {}
    benchmark_role = strategy_info.get("benchmark_role") or request.strategy
    benchmark_return = (
        Decimal(str(request.benchmark_return))
        if request.benchmark_return is not None
        else None
    )
    evidence = build_rolling_out_of_sample_validation(
        strategy_id=request.strategy,
        benchmark_role=benchmark_role,
        result=result,
        min_train_points=request.oos_min_train_points,
        test_window_points=request.oos_test_window_points,
        step_points=request.oos_step_points,
        benchmark_return=benchmark_return,
    )
    return evidence.to_json_dict()


def last_equity_from_curve(equity_data: list[Any]) -> float | None:
    if not equity_data:
        return None
    last_point = equity_data[-1]
    if not isinstance(last_point, dict):
        return None
    try:
        return float(last_point["equity"])
    except (KeyError, TypeError, ValueError):
        return None


__all__ = (
    "build_oos_validation_payload",
    "build_parameter_grid",
    "build_rolling_oos_validation_payload",
    "dataset_snapshot_from_result",
    "dataset_snapshot_id",
    "last_equity_from_curve",
    "sweep_score",
)
