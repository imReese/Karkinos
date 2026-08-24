"""Backtest routes — /api/backtest/*"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import sys
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
    facade = sys.modules[__name__]
    router = APIRouter()
    router.routes.extend(_create_strategy_catalog_router(facade).routes)
    router.routes.extend(_create_previews_router(facade).routes)
    router.routes.extend(_create_execution_router(facade).routes)
    router.routes.extend(_create_results_router(facade).routes)
    return router
