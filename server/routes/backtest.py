"""Backtest routes — /api/backtest/*"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, HTTPException

from core.events import MarketEvent, OrderIntentEvent
from core.types import AssetClass, BarFrequency, OrderSide, Symbol
from server.bootstrap import build_strategy, build_watchlist
from server.config import BacktestConfig
from server.contracts.http.backtest import (
    BacktestAttributionPreviewRequest,
    BacktestPaperShadowPreviewRequest,
    BacktestRiskPreviewRequest,
    StrategyInfoResponse,
    StrategyPromotionReadinessResponse,
    StrategyPromotionReadinessRowResponse,
    StrategySignalPreviewBar,
    StrategySignalPreviewRequest,
    StrategySignalPreviewResponse,
    StrategyValidationMatrixResponse,
    StrategyValidationRowResponse,
)
from server.http.backtest_endpoints.dependencies import (
    ExecutionEndpointDependencies,
    PreviewEndpointDependencies,
    ResultEndpointDependencies,
    StrategyCatalogEndpointDependencies,
)
from server.http.backtest_endpoints.execution import (
    create_router as _create_execution_router,
)
from server.http.backtest_endpoints.previews import (
    create_router as _create_previews_router,
)
from server.http.backtest_endpoints.results import (
    create_router as _create_results_router,
)
from server.http.backtest_endpoints.strategy_catalog import (
    create_router as _create_strategy_catalog_router,
)
from server.models import (
    BacktestFill,
    BacktestMetrics,
    BacktestRequest,
    BacktestResponse,
    BacktestSummary,
    BacktestSweepRequest,
    BacktestSweepResponse,
    BacktestSweepResult,
    CompareRequest,
    CompareResponse,
    EquityPoint,
    StrategyCompareItem,
)
from server.services.backtest_result_projection import (
    backtest_evidence_from_payload as _backtest_evidence_from_payload,
)
from server.services.backtest_result_projection import (
    build_backtest_report_metrics_json as _backtest_report_metrics_json,
)
from server.services.backtest_result_projection import (
    fill_to_response as _fill_to_response,
)
from server.services.backtest_result_projection import json_object as _json_object
from server.services.backtest_result_projection import (
    strategy_metadata_snapshot as _strategy_metadata_snapshot,
)
from server.services.backtest_views.attribution import (
    build_attribution_review_linkage_candidate as _build_attribution_review_linkage_candidate,
)
from server.services.backtest_views.attribution import payload_value as _payload_value
from server.services.backtest_views.attribution import preview_ref as _preview_ref
from server.services.backtest_views.attribution import (
    run_backtest_attribution_preview as _run_backtest_attribution_preview,
)
from server.services.backtest_views.execution import (
    backtest_report_dir as _backtest_report_dir,
)
from server.services.backtest_views.execution import (
    normalize_backtest_payload_from_equity_curve as _normalize_backtest_payload_from_equity_curve,
)
from server.services.backtest_views.execution import (
    run_single_backtest as _run_single_backtest,
)
from server.services.backtest_views.execution import (
    write_backtest_report_file as _write_backtest_report_file,
)
from server.services.backtest_views.parameter_sweep import (
    build_oos_validation_payload as _build_oos_validation_payload,
)
from server.services.backtest_views.parameter_sweep import (
    build_parameter_grid as _build_parameter_grid,
)
from server.services.backtest_views.parameter_sweep import (
    build_rolling_oos_validation_payload as _build_rolling_oos_validation_payload,
)
from server.services.backtest_views.parameter_sweep import (
    dataset_snapshot_from_result as _dataset_snapshot_from_result,
)
from server.services.backtest_views.parameter_sweep import (
    dataset_snapshot_id as _dataset_snapshot_id,
)
from server.services.backtest_views.parameter_sweep import (
    last_equity_from_curve as _last_equity_from_curve,
)
from server.services.backtest_views.parameter_sweep import sweep_score as _sweep_score
from server.services.backtest_views.risk_preview import (
    paper_shadow_commission_calculator as _paper_shadow_commission_calculator,
)
from server.services.backtest_views.risk_preview import (
    paper_shadow_payload as _paper_shadow_payload,
)
from server.services.backtest_views.risk_preview import (
    risk_preview_data_quality_issues as _risk_preview_data_quality_issues,
)
from server.services.backtest_views.risk_preview import (
    risk_preview_order_side as _risk_preview_order_side,
)
from server.services.backtest_views.risk_preview import (
    run_backtest_paper_shadow_preview as _run_backtest_paper_shadow_preview,
)
from server.services.backtest_views.risk_preview import (
    run_backtest_risk_preview as _run_backtest_risk_preview,
)
from server.services.backtest_views.strategy_inputs import (
    backtest_metrics_from_payload as _backtest_metrics_from_payload,
)
from server.services.backtest_views.strategy_inputs import (
    load_signal_preview_bars as _load_signal_preview_bars,
)
from server.services.backtest_views.strategy_inputs import (
    preview_bar_to_market_event as _preview_bar_to_market_event,
)
from server.services.backtest_views.strategy_inputs import (
    run_strategy_signal_preview as _run_strategy_signal_preview,
)
from server.services.backtest_views.strategy_inputs import (
    signal_preview_symbol_asset_class as _signal_preview_symbol_asset_class,
)
from server.services.backtest_views.strategy_inputs import (
    validate_backtest_strategy_params as _validate_backtest_strategy_params,
)
from server.services.backtest_views.strategy_inputs import (
    validate_signal_preview_strategy_params as _validate_signal_preview_strategy_params,
)

logger = logging.getLogger(__name__)

_SWEEP_WARNINGS = [
    "Parameter sweep rankings are research evidence, not investment advice.",
    "Multiple testing can overfit historical data; require OOS and after-cost review before promotion.",
]

_SWEEP_RANK_DIRECTIONS = {
    "total_return": "desc",
    "annual_return": "desc",
    "sharpe": "desc",
    "sortino": "desc",
    "win_rate": "desc",
    "max_drawdown": "asc",
}

_COMPARE_WARNINGS = [
    "Strategy comparison results are research evidence, not investment advice.",
    "Comparison is valid only when every run uses the same frozen dataset snapshot.",
]

_DEFAULT_BACKTEST_REPORT_DIR = Path("reports/backtest")


# Keep backward-compatible alias
_run_backtest = _run_single_backtest


def create_router() -> APIRouter:
    router = APIRouter()
    router.routes.extend(
        _create_strategy_catalog_router(
            StrategyCatalogEndpointDependencies(
                run_strategy_signal_preview=lambda *args, **kwargs: (
                    _run_strategy_signal_preview(*args, **kwargs)
                ),
                validate_signal_preview_strategy_params=lambda *args, **kwargs: (
                    _validate_signal_preview_strategy_params(*args, **kwargs)
                ),
                asyncio_provider=lambda: asyncio,
            )
        ).routes
    )
    router.routes.extend(
        _create_previews_router(
            PreviewEndpointDependencies(
                run_backtest_attribution_preview=lambda *args, **kwargs: (
                    _run_backtest_attribution_preview(*args, **kwargs)
                ),
                run_backtest_paper_shadow_preview=lambda *args, **kwargs: (
                    _run_backtest_paper_shadow_preview(*args, **kwargs)
                ),
                run_backtest_risk_preview=lambda *args, **kwargs: (
                    _run_backtest_risk_preview(*args, **kwargs)
                ),
            )
        ).routes
    )
    router.routes.extend(
        _create_execution_router(
            ExecutionEndpointDependencies(
                sweep_rank_directions=_SWEEP_RANK_DIRECTIONS,
                sweep_warnings=_SWEEP_WARNINGS,
                backtest_evidence_from_payload=lambda *args, **kwargs: (
                    _backtest_evidence_from_payload(*args, **kwargs)
                ),
                backtest_metrics_from_payload=lambda *args, **kwargs: (
                    _backtest_metrics_from_payload(*args, **kwargs)
                ),
                backtest_report_metrics_json=lambda *args, **kwargs: (
                    _backtest_report_metrics_json(*args, **kwargs)
                ),
                build_parameter_grid=lambda *args, **kwargs: _build_parameter_grid(
                    *args, **kwargs
                ),
                json_object=lambda *args, **kwargs: _json_object(*args, **kwargs),
                run_backtest=lambda *args, **kwargs: _run_backtest(*args, **kwargs),
                sweep_score=lambda *args, **kwargs: _sweep_score(*args, **kwargs),
                validate_backtest_strategy_params=lambda *args, **kwargs: (
                    _validate_backtest_strategy_params(*args, **kwargs)
                ),
                write_backtest_report_file=lambda *args, **kwargs: (
                    _write_backtest_report_file(*args, **kwargs)
                ),
                asyncio_provider=lambda: asyncio,
                json_provider=lambda: json,
                logger_provider=lambda: logger,
            )
        ).routes
    )
    router.routes.extend(
        _create_results_router(
            ResultEndpointDependencies(
                compare_warnings=_COMPARE_WARNINGS,
                backtest_metrics_from_payload=lambda *args, **kwargs: (
                    _backtest_metrics_from_payload(*args, **kwargs)
                ),
                backtest_report_metrics_json=lambda *args, **kwargs: (
                    _backtest_report_metrics_json(*args, **kwargs)
                ),
                dataset_snapshot_from_result=lambda *args, **kwargs: (
                    _dataset_snapshot_from_result(*args, **kwargs)
                ),
                dataset_snapshot_id=lambda *args, **kwargs: _dataset_snapshot_id(
                    *args, **kwargs
                ),
                json_object=lambda *args, **kwargs: _json_object(*args, **kwargs),
                normalize_backtest_payload_from_equity_curve=lambda *args, **kwargs: (
                    _normalize_backtest_payload_from_equity_curve(*args, **kwargs)
                ),
                run_single_backtest=lambda *args, **kwargs: _run_single_backtest(
                    *args, **kwargs
                ),
                validate_backtest_strategy_params=lambda *args, **kwargs: (
                    _validate_backtest_strategy_params(*args, **kwargs)
                ),
                write_backtest_report_file=lambda *args, **kwargs: (
                    _write_backtest_report_file(*args, **kwargs)
                ),
                asyncio_provider=lambda: asyncio,
                json_provider=lambda: json,
                logger_provider=lambda: logger,
            )
        ).routes
    )
    return router
