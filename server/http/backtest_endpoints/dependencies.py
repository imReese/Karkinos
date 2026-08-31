"""Explicit dependency contracts for backtest HTTP endpoint registration."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

Operation = Callable[..., Any]
ValueProvider = Callable[[], Any]


@dataclass(frozen=True, slots=True)
class StrategyCatalogEndpointDependencies:
    run_strategy_signal_preview: Operation
    validate_signal_preview_strategy_params: Operation
    asyncio_provider: ValueProvider


@dataclass(frozen=True, slots=True)
class PreviewEndpointDependencies:
    run_backtest_attribution_preview: Operation
    run_backtest_paper_shadow_preview: Operation
    run_backtest_risk_preview: Operation


@dataclass(frozen=True, slots=True)
class ExecutionEndpointDependencies:
    sweep_rank_directions: Mapping[str, str]
    sweep_warnings: Sequence[str]
    backtest_evidence_from_payload: Operation
    backtest_metrics_from_payload: Operation
    backtest_report_metrics_json: Operation
    build_parameter_grid: Operation
    json_object: Operation
    run_backtest: Operation
    sweep_score: Operation
    validate_backtest_strategy_params: Operation
    write_backtest_report_file: Operation
    asyncio_provider: ValueProvider
    json_provider: ValueProvider
    logger_provider: ValueProvider


@dataclass(frozen=True, slots=True)
class ResultEndpointDependencies:
    compare_warnings: Sequence[str]
    backtest_metrics_from_payload: Operation
    backtest_report_metrics_json: Operation
    dataset_snapshot_from_result: Operation
    dataset_snapshot_id: Operation
    json_object: Operation
    normalize_backtest_payload_from_equity_curve: Operation
    run_single_backtest: Operation
    validate_backtest_strategy_params: Operation
    write_backtest_report_file: Operation
    asyncio_provider: ValueProvider
    json_provider: ValueProvider
    logger_provider: ValueProvider


__all__ = [
    "ExecutionEndpointDependencies",
    "PreviewEndpointDependencies",
    "ResultEndpointDependencies",
    "StrategyCatalogEndpointDependencies",
]
