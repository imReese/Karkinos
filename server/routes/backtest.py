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
from pydantic import BaseModel, Field

from core.events import MarketEvent
from core.types import AssetClass, BarFrequency, Symbol
from server.bootstrap import build_strategy, build_watchlist
from server.config import BacktestConfig
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


class StrategyInfoResponse(BaseModel):
    registry_contract_version: str = "karkinos.strategy_registry.v1"
    schema_version: str = "karkinos.strategy.v1"
    strategy_id: str
    name: str
    display_name: str
    description: str
    source_type: str = "builtin"
    is_extension: bool = False
    params: list[dict[str, Any]]
    parameter_schema: list[dict[str, Any]]
    asset_universe: list[str] = Field(default_factory=list)
    supported_frequencies: list[str] = Field(default_factory=list)
    benchmark_role: str | None = None
    benchmark_universe: list[str] = Field(default_factory=list)
    requires_out_of_sample_validation: bool = False
    requires_after_cost_report: bool = False
    validation_notes: list[str] = Field(default_factory=list)
    execution_boundary: dict[str, Any] = Field(default_factory=dict)


class StrategyValidationRowResponse(BaseModel):
    strategy_id: str
    benchmark_role: str
    requires_out_of_sample_validation: bool
    requires_after_cost_report: bool
    has_out_of_sample_validation: bool
    has_after_cost_report: bool
    validation_status: str | None = None
    backtest_result_id: int | None = None
    missing_requirements: list[str] = Field(default_factory=list)
    is_ready: bool


class StrategyValidationMatrixResponse(BaseModel):
    required_strategy_count: int
    ready_strategy_count: int
    is_complete: bool
    rows: list[StrategyValidationRowResponse]
    limitations: list[str] = Field(default_factory=list)


class StrategyPromotionReadinessRowResponse(BaseModel):
    strategy_id: str
    benchmark_role: str
    backtest_result_id: int | None = None
    has_after_cost_and_oos_evidence: bool
    has_risk_block_evidence: bool
    has_paper_shadow_evidence: bool
    has_paper_shadow_divergence_review: bool
    has_account_truth_evidence: bool = True
    account_truth_gate_status: str = "not_evaluated"
    account_truth_score: int | None = None
    has_strategy_attribution_evidence: bool = True
    strategy_attribution_status: str = "not_evaluated"
    missing_requirements: list[str] = Field(default_factory=list)
    promotion_status: str
    is_promotable: bool


class StrategyPromotionReadinessResponse(BaseModel):
    required_strategy_count: int
    promotable_strategy_count: int
    is_complete: bool
    rows: list[StrategyPromotionReadinessRowResponse]
    limitations: list[str] = Field(default_factory=list)


class StrategySignalPreviewBar(BaseModel):
    timestamp: datetime
    close: Decimal
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    volume: Decimal = Decimal("0")
    frequency: str = BarFrequency.DAILY.value
    data_status: str = "confirmed"


class StrategySignalPreviewRequest(BaseModel):
    strategy: str = "dual_ma"
    symbol: str
    asset_class: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    params: dict[str, Any] | None = None
    bars: list[StrategySignalPreviewBar] = Field(default_factory=list)
    dataset_snapshot: dict[str, Any] = Field(default_factory=dict)


class StrategySignalPreviewResponse(BaseModel):
    schema_version: str
    strategy_id: str
    symbol: str
    params: dict[str, Any] = Field(default_factory=dict)
    run_id: str
    dataset_snapshot_id: str | None = None
    record_count: int
    outputs: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    does_not_enable_execution: bool = True


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        logger.warning("Failed to parse backtest JSON payload", exc_info=True)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _fill_to_response(fill: Any) -> dict[str, Any]:
    timestamp = getattr(fill, "timestamp", None)
    raw_side = getattr(fill, "side", "")
    side = getattr(raw_side, "value", str(raw_side))
    return {
        "fill_id": getattr(fill, "fill_id", None),
        "order_id": getattr(fill, "order_id", None),
        "timestamp": timestamp.isoformat() if timestamp is not None else None,
        "symbol": str(getattr(fill, "symbol", "")),
        "side": side,
        "fill_price": float(getattr(fill, "fill_price", 0)),
        "fill_quantity": float(getattr(fill, "fill_quantity", 0)),
        "commission": float(getattr(fill, "commission", 0)),
        "slippage": float(getattr(fill, "slippage", 0)),
        "fee_breakdown": getattr(fill, "fee_breakdown", None),
        "fee_rule_id": getattr(fill, "fee_rule_id", None),
        "fee_rule_version": getattr(fill, "fee_rule_version", None),
    }


def _backtest_metrics_from_payload(payload: dict[str, Any]) -> BacktestMetrics:
    metrics_json = _json_object(payload.get("metrics_json"))
    return BacktestMetrics(
        initial_cash=payload["initial_cash"],
        final_equity=payload["final_equity"],
        total_return=payload["total_return"],
        annual_return=payload.get("annual_return", 0),
        sharpe=payload["sharpe"],
        sortino=payload.get("sortino", 0),
        max_drawdown=payload.get("max_drawdown", payload.get("max_dd", 0)),
        calmar=metrics_json.get("calmar", 0.0),
        volatility=metrics_json.get("volatility", 0.0),
        win_rate=payload.get("win_rate", 0),
        duration_days=payload.get("duration_days", 0),
        total_commission=metrics_json.get("total_commission", 0.0),
        total_slippage=metrics_json.get("total_slippage", 0.0),
        total_trades=metrics_json.get("total_trades", 0),
        gross_turnover=metrics_json.get("gross_turnover", 0.0),
    )


def _backtest_evidence_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    evidence_json = _json_object(payload.get("evidence_json"))
    if evidence_json:
        return evidence_json
    metrics_json = _json_object(payload.get("metrics_json"))
    return _json_object(metrics_json.get("evidence_bundle"))


def _validate_backtest_strategy_params(request: BacktestRequest) -> BacktestRequest:
    """Return a request copy with validated generic strategy params."""
    import strategy.builtins  # noqa: F401
    from strategy.registry import StrategyRegistry
    from strategy.schema import StrategyParameterValidationError

    strategy_info = StrategyRegistry.get(request.strategy)
    if strategy_info is None:
        available = StrategyRegistry.list_strategies()
        raise HTTPException(
            status_code=422,
            detail={
                "strategy": request.strategy,
                "errors": [
                    {
                        "field": "strategy",
                        "code": "unknown_strategy",
                        "message": (
                            f"Unknown strategy '{request.strategy}'. "
                            f"Available strategies: {available}."
                        ),
                    }
                ],
            },
        )

    raw_params = request.params
    if raw_params is None:
        legacy_params = {}
        for param in strategy_info.get("params", []):
            name = param["name"]
            if hasattr(request, name):
                legacy_params[name] = getattr(request, name)
        raw_params = legacy_params or None

    try:
        validated = StrategyRegistry.validate_params(request.strategy, raw_params)
    except StrategyParameterValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"strategy": request.strategy, "errors": exc.errors},
        ) from exc

    updates: dict[str, Any] = {"params": validated}
    for legacy_name in ("short_period", "long_period"):
        if legacy_name in validated:
            updates[legacy_name] = validated[legacy_name]
    return request.model_copy(update=updates)


def _validate_signal_preview_strategy_params(
    request: StrategySignalPreviewRequest,
) -> StrategySignalPreviewRequest:
    """Return a signal-preview request copy with validated strategy params."""
    import strategy.builtins  # noqa: F401
    from strategy.registry import StrategyRegistry
    from strategy.schema import StrategyParameterValidationError

    strategy_info = StrategyRegistry.get(request.strategy)
    if strategy_info is None:
        available = StrategyRegistry.list_strategies()
        raise HTTPException(
            status_code=422,
            detail={
                "strategy": request.strategy,
                "errors": [
                    {
                        "field": "strategy",
                        "code": "unknown_strategy",
                        "message": (
                            f"Unknown strategy '{request.strategy}'. "
                            f"Available strategies: {available}."
                        ),
                    }
                ],
            },
        )

    try:
        validated = StrategyRegistry.validate_params(request.strategy, request.params)
    except StrategyParameterValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"strategy": request.strategy, "errors": exc.errors},
        ) from exc
    return request.model_copy(update={"params": validated})


def _preview_bar_to_market_event(
    bar: StrategySignalPreviewBar,
    *,
    symbol: str,
    asset_class: str | None,
) -> MarketEvent:
    close = bar.close
    _, parsed_asset_class = _signal_preview_symbol_asset_class(symbol, asset_class)
    return MarketEvent(
        timestamp=bar.timestamp,
        symbol=Symbol(symbol),
        open=bar.open if bar.open is not None else close,
        high=bar.high if bar.high is not None else close,
        low=bar.low if bar.low is not None else close,
        close=close,
        volume=bar.volume,
        frequency=BarFrequency(bar.frequency),
        asset_class=parsed_asset_class,
    )


def _signal_preview_symbol_asset_class(
    symbol: str,
    asset_class: str | None,
) -> tuple[Symbol, AssetClass]:
    return build_watchlist(
        BacktestConfig(
            assets=[
                {
                    "symbol": symbol,
                    "asset_class": asset_class or AssetClass.STOCK.value,
                }
            ]
        )
    )[0]


def _load_signal_preview_bars(
    request: StrategySignalPreviewRequest,
    config: Any,
) -> tuple[tuple[MarketEvent, ...], dict[str, Any]]:
    """Load single-symbol preview bars through the backtest data plane."""
    from analytics.dataset_snapshot import build_backtest_dataset_snapshot
    from data.manager import DataManager, build_sources
    from data.store import DataStore

    start_date = request.start_date or getattr(config, "start_date", None)
    end_date = request.end_date or getattr(config, "end_date", None)
    if not start_date or not end_date:
        raise HTTPException(
            status_code=422,
            detail={
                "strategy": request.strategy,
                "errors": [
                    {
                        "field": "start_date",
                        "code": "required_field_missing",
                        "message": (
                            "start_date and end_date are required when bars are "
                            "not supplied explicitly."
                        ),
                    }
                ],
            },
        )

    symbol, asset_class = _signal_preview_symbol_asset_class(
        request.symbol,
        request.asset_class,
    )
    store = None
    try:
        store = DataStore()
    except Exception:
        pass

    sources = build_sources(
        data_source=getattr(config, "data_source", "akshare"),
        tushare_token=getattr(config, "tushare_token", ""),
    )
    manager = DataManager(
        sources=sources,
        store=store,
        default_source=getattr(config, "data_source", "akshare"),
    )
    handler = manager.get_bars(
        symbol,
        datetime.strptime(start_date, "%Y-%m-%d"),
        datetime.strptime(end_date, "%Y-%m-%d"),
        asset_class=asset_class,
    )
    snapshot = build_backtest_dataset_snapshot(
        start_date=start_date,
        end_date=end_date,
        configured_source=getattr(config, "data_source", None),
        data_handlers={symbol: handler},
        store=store,
        source_names=list(sources.keys()),
    )
    return tuple(handler), snapshot


def _run_strategy_signal_preview(
    request: StrategySignalPreviewRequest,
    config: Any,
) -> dict[str, Any]:
    """Run a research-only strategy signal preview from bars or data config."""
    from analytics.strategy_signal_preview import build_strategy_signal_preview

    if request.bars:
        bars = tuple(
            _preview_bar_to_market_event(
                bar,
                symbol=request.symbol,
                asset_class=request.asset_class,
            )
            for bar in request.bars
        )
        dataset_snapshot = request.dataset_snapshot
    else:
        bars, dataset_snapshot = _load_signal_preview_bars(request, config)

    return build_strategy_signal_preview(
        strategy_id=request.strategy,
        symbol=request.symbol,
        params=request.params,
        bars=bars,
        dataset_snapshot=dataset_snapshot,
    )


def _build_parameter_grid(
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


def _sweep_score(metrics: BacktestMetrics, rank_by: str) -> float:
    return float(getattr(metrics, rank_by))


def _dataset_snapshot_from_result(result: dict[str, Any]) -> dict[str, Any]:
    metrics_json = _json_object(result.get("metrics_json"))
    return _json_object(metrics_json.get("dataset_snapshot"))


def _dataset_snapshot_id(snapshot: dict[str, Any]) -> str | None:
    snapshot_id = snapshot.get("snapshot_id")
    return str(snapshot_id) if snapshot_id else None


def _build_oos_validation_payload(
    request: BacktestRequest,
    result: Any,
) -> dict[str, Any]:
    if request.oos_mode == "rolling":
        return _build_rolling_oos_validation_payload(request, result)

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


def _build_rolling_oos_validation_payload(
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


def _strategy_metadata_snapshot(request: BacktestRequest) -> dict[str, Any]:
    """Build a persisted strategy metadata snapshot for backtest audit."""
    import strategy.builtins  # noqa: F401
    from strategy.registry import StrategyRegistry

    strategies = StrategyRegistry.get_info()
    strategy_info = next(
        (
            item
            for item in strategies
            if item["name"] == request.strategy
            or item["strategy_id"] == request.strategy
        ),
        None,
    )
    if strategy_info is None:
        return {
            "schema_version": "karkinos.strategy_metadata.v1",
            "strategy_id": request.strategy,
            "name": request.strategy,
            "params": dict(request.params or {}),
            "parameter_schema": [],
        }
    return {
        "schema_version": "karkinos.strategy_metadata.v1",
        "strategy_id": strategy_info["strategy_id"],
        "name": strategy_info["name"],
        "display_name": strategy_info["display_name"],
        "description": strategy_info["description"],
        "asset_universe": list(strategy_info.get("asset_universe", [])),
        "supported_frequencies": list(strategy_info.get("supported_frequencies", [])),
        "benchmark_role": strategy_info.get("benchmark_role"),
        "benchmark_universe": list(strategy_info.get("benchmark_universe", [])),
        "requires_out_of_sample_validation": bool(
            strategy_info.get("requires_out_of_sample_validation", False)
        ),
        "requires_after_cost_report": bool(
            strategy_info.get("requires_after_cost_report", False)
        ),
        "validation_notes": list(strategy_info.get("validation_notes", [])),
        "parameter_schema": list(strategy_info.get("parameter_schema", [])),
        "params": dict(request.params or {}),
    }


def _backtest_report_metrics_json(
    request: BacktestRequest,
    bt_result: dict[str, Any],
) -> dict[str, Any]:
    from analytics.research_evidence import build_research_evidence_bundle

    metrics_json = dict(bt_result.get("metrics_json") or {})
    metrics_json["evidence_bundle"] = _backtest_evidence_from_payload(bt_result)
    strategy_metadata = _strategy_metadata_snapshot(request)
    metrics_json["strategy_metadata"] = strategy_metadata
    metrics_json["research_evidence_bundle"] = build_research_evidence_bundle(
        metrics_json=metrics_json,
        cost_summary_json=dict(bt_result.get("cost_summary_json") or {}),
        evidence_json=metrics_json["evidence_bundle"],
        strategy_metadata=strategy_metadata,
        fills=list(bt_result.get("fills") or []),
    )
    return metrics_json


def _last_equity_from_curve(equity_data: list[Any]) -> float | None:
    if not equity_data:
        return None
    last_point = equity_data[-1]
    if not isinstance(last_point, dict):
        return None
    try:
        return float(last_point["equity"])
    except (KeyError, TypeError, ValueError):
        return None


def _normalize_backtest_payload_from_equity_curve(
    payload: dict[str, Any],
    *,
    metrics_json: dict[str, Any],
    cost_summary_json: dict[str, Any] | None,
    equity_data: list[Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Correct legacy stored metrics when final_equity disagrees with curve end."""
    curve_final_equity = _last_equity_from_curve(equity_data)
    if curve_final_equity is None:
        return payload, metrics_json

    normalized = dict(payload)
    normalized_metrics = dict(metrics_json)
    stored_final = normalized.get(
        "final_equity", normalized_metrics.get("final_equity")
    )
    try:
        stored_final_float = float(stored_final)
    except (TypeError, ValueError):
        stored_final_float = None

    if stored_final_float is not None and abs(
        stored_final_float - curve_final_equity
    ) <= max(0.01, abs(curve_final_equity) * 1e-9):
        return normalized, normalized_metrics

    try:
        initial_cash = float(
            normalized.get("initial_cash", normalized_metrics.get("initial_cash", 0))
        )
    except (TypeError, ValueError):
        initial_cash = 0.0
    corrected_total_return = (
        (curve_final_equity - initial_cash) / initial_cash if initial_cash else 0.0
    )

    normalized["final_equity"] = curve_final_equity
    normalized["total_return"] = corrected_total_return
    normalized_metrics["initial_cash"] = initial_cash
    normalized_metrics["final_equity"] = curve_final_equity
    normalized_metrics["total_return"] = corrected_total_return
    normalized_metrics["legacy_correction"] = {
        "reason": "stored_final_equity_mismatched_equity_curve",
        "stored_final_equity": stored_final_float,
        "curve_final_equity": curve_final_equity,
    }

    evidence = _json_object(normalized_metrics.get("evidence_bundle"))
    if evidence:
        costs = cost_summary_json or {}
        total_cost = float(costs.get("total_commission", 0) or 0) + float(
            costs.get("total_slippage", 0) or 0
        )
        net_pnl = curve_final_equity - initial_cash
        gross_pnl = net_pnl + total_cost
        evidence.update(
            {
                "net_pnl": net_pnl,
                "gross_pnl_before_costs": gross_pnl,
                "net_return": corrected_total_return,
                "gross_return_before_costs": (
                    gross_pnl / initial_cash if initial_cash else 0.0
                ),
                "cost_to_initial_cash": (
                    total_cost / initial_cash if initial_cash else 0.0
                ),
            }
        )
        normalized_metrics["evidence_bundle"] = evidence

    return normalized, normalized_metrics


def _backtest_report_dir() -> Path:
    return Path(
        os.environ.get("KARKINOS_BACKTEST_REPORT_DIR") or _DEFAULT_BACKTEST_REPORT_DIR
    )


def _write_backtest_report_file(
    *,
    result_id: int,
    request: BacktestRequest,
    bt_result: dict[str, Any],
    metrics_json: dict[str, Any],
) -> Path:
    report_dir = _backtest_report_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"backtest-result-{result_id}.json"
    payload = {
        "schema_version": "karkinos.backtest_report.v1",
        "id": result_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": request.model_dump(mode="json"),
        "metrics": _backtest_metrics_from_payload(
            {**bt_result, "metrics_json": metrics_json}
        ).model_dump(mode="json"),
        "equity_curve": bt_result["equity_curve"],
        "metrics_json": metrics_json,
        "research_evidence_bundle": _json_object(
            metrics_json.get("research_evidence_bundle")
        ),
        "cost_summary": bt_result["cost_summary_json"],
        "evidence": _backtest_evidence_from_payload(
            {**bt_result, "metrics_json": metrics_json}
        ),
        "fills": bt_result.get("fills", []),
    }
    tmp_path = report_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(report_path)
    return report_path


def _run_single_backtest(
    request: BacktestRequest,
    config: Any,
    db=None,
) -> dict[str, Any]:
    """同步运行单次回测（在线程池中执行），供 run 和 compare 共用。"""
    from datetime import datetime

    from analytics.dataset_snapshot import build_backtest_dataset_snapshot
    from backtest.engine import BacktestEngine
    from data.manager import DataManager, build_sources
    from data.store import DataStore

    assets = request.assets or config.assets
    store = None
    try:
        store = DataStore()
    except Exception:
        pass

    sources = build_sources(
        data_source=config.data_source,
        tushare_token=config.tushare_token,
    )
    dm = DataManager(
        sources=sources,
        store=store,
        default_source=config.data_source,
    )

    watchlist = build_watchlist(BacktestConfig(assets=assets))
    instruments = {}
    data_handlers = {}
    for sym, ac in watchlist:
        instrument = DataManager.get_instrument(sym, ac)
        instruments[sym] = instrument

        handler = dm.get_bars(
            sym,
            datetime.strptime(request.start_date, "%Y-%m-%d"),
            datetime.strptime(request.end_date, "%Y-%m-%d"),
            asset_class=ac,
        )
        data_handlers[sym] = handler

    dataset_snapshot_json = build_backtest_dataset_snapshot(
        start_date=request.start_date,
        end_date=request.end_date,
        configured_source=getattr(config, "data_source", None),
        data_handlers=data_handlers,
        store=store,
        source_names=list(sources.keys()),
    )

    event_bus_placeholder = type(
        "EventBus", (), {"subscribe": lambda *a: None, "publish": lambda *a: None}
    )()
    strategy_config = SimpleNamespace(
        strategy=request.strategy,
        short_period=request.short_period,
        long_period=request.long_period,
        params=request.params,
    )
    strategy = build_strategy(strategy_config, event_bus_placeholder)

    engine = BacktestEngine(
        strategy=strategy,
        instruments=instruments,
        data_handlers=data_handlers,
        initial_cash=Decimal(str(request.initial_cash)),
        db=db,
    )

    result = engine.run()

    equity_curve = [
        {"timestamp": ts.isoformat(), "equity": float(eq)}
        for ts, eq in result.equity_curve
    ]
    metrics = result.metrics
    evidence_json = (
        result.evidence_bundle.to_json_dict()
        if result.evidence_bundle is not None
        else {}
    )
    metrics_json = metrics.to_json_dict()
    metrics_json["evidence_bundle"] = evidence_json
    metrics_json["dataset_snapshot"] = dataset_snapshot_json
    metrics_json["strategy_metadata"] = _strategy_metadata_snapshot(request)
    oos_validation_json = _build_oos_validation_payload(request, result)
    if oos_validation_json:
        metrics_json["oos_validation"] = oos_validation_json

    return {
        "initial_cash": float(result.initial_cash),
        "final_equity": float(result.final_equity),
        "total_return": float(result.total_return),
        "annual_return": metrics.annual_return,
        "sharpe": metrics.sharpe,
        "sortino": metrics.sortino,
        "max_drawdown": metrics.max_drawdown,
        "win_rate": metrics.win_rate,
        "duration_days": result.duration_days,
        "equity_curve": equity_curve,
        "metrics_json": metrics_json,
        "cost_summary_json": result.cost_summary.to_json_dict(),
        "evidence_json": evidence_json,
        "oos_validation_json": oos_validation_json,
        "fills": [_fill_to_response(fill) for fill in result.fills],
    }


# Keep backward-compatible alias
_run_backtest = _run_single_backtest


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/backtest", tags=["backtest"])

    @r.get("/strategies", response_model=list[StrategyInfoResponse])
    async def list_strategies() -> list[StrategyInfoResponse]:
        """获取所有已注册策略及参数信息。"""
        import strategy.builtins  # noqa: F401
        from strategy.registry import StrategyRegistry

        return [StrategyInfoResponse(**s) for s in StrategyRegistry.get_info()]

    @r.get(
        "/strategy-validation",
        response_model=StrategyValidationMatrixResponse,
    )
    async def get_strategy_validation() -> StrategyValidationMatrixResponse:
        """获取 v0.2 基准策略 after-cost / OOS 证据矩阵。"""
        import strategy.builtins  # noqa: F401
        from analytics.strategy_validation_matrix import (
            build_strategy_validation_matrix,
        )
        from server.app import get_app_state
        from strategy.registry import StrategyRegistry

        state = get_app_state()
        rows = await state.db.get_backtest_results()
        matrix = build_strategy_validation_matrix(StrategyRegistry.get_info(), rows)
        return StrategyValidationMatrixResponse(**matrix.to_json_dict())

    @r.get(
        "/strategy-promotion-readiness",
        response_model=StrategyPromotionReadinessResponse,
    )
    async def get_strategy_promotion_readiness() -> StrategyPromotionReadinessResponse:
        """获取 v0.2 策略晋级证据闸门，不自动晋级或执行。"""
        import strategy.builtins  # noqa: F401
        from analytics.strategy_promotion_readiness import (
            build_strategy_promotion_readiness,
        )
        from server.account_truth_gate import build_latest_account_truth_score_payload
        from server.app import get_app_state
        from server.routes.account_strategy import (
            _assignment_from_payload,
            _build_attribution_summary,
            _build_contribution_report,
        )
        from strategy.registry import StrategyRegistry

        state = get_app_state()
        rows = await state.db.get_backtest_results()
        risk_decisions = state.db.get_risk_decisions_sync(limit=500)
        order_facts = state.db.list_orders_sync(limit=500)
        runtime_reader = getattr(state.db, "get_runtime_control_sync", None)
        assignment_payload = (
            runtime_reader("account_strategy_assignment")
            if callable(runtime_reader)
            else None
        )
        account_strategy_assignments: list[dict[str, Any]] = []
        account_strategy_attributions: list[dict[str, Any]] = []
        if isinstance(assignment_payload, dict):
            assignment = _assignment_from_payload(
                assignment_payload,
                fallback_config=state.config,
            )
            account_strategy_assignments.append(assignment.model_dump())
            attribution_payload = _build_attribution_summary(
                state.db,
                assignment,
            ).model_dump()
            contribution_payload = _build_contribution_report(
                state.db,
                assignment,
            ).model_dump()
            account_strategy_attributions.append(
                {**attribution_payload, **contribution_payload}
            )
        account_truth_payload = build_latest_account_truth_score_payload(state)
        account_truth_scores = (
            [account_truth_payload]
            if account_truth_payload.get("status") == "available"
            else None
        )
        readiness = build_strategy_promotion_readiness(
            StrategyRegistry.get_info(),
            rows,
            risk_decisions,
            order_facts,
            account_truth_scores=account_truth_scores,
            account_strategy_assignments=account_strategy_assignments,
            account_strategy_attributions=account_strategy_attributions,
        )
        return StrategyPromotionReadinessResponse(**readiness.to_json_dict())

    @r.post("/signal-preview", response_model=StrategySignalPreviewResponse)
    async def preview_strategy_signal(
        request: StrategySignalPreviewRequest,
    ) -> StrategySignalPreviewResponse:
        """Preview strategy outputs as research evidence without persistence."""
        from server.app import get_app_state

        state = get_app_state()
        config = state.config or BacktestConfig()
        request = _validate_signal_preview_strategy_params(request)
        preview = await asyncio.to_thread(_run_strategy_signal_preview, request, config)
        return StrategySignalPreviewResponse(**preview)

    @r.post("/run", response_model=BacktestResponse)
    async def run_backtest(request: BacktestRequest) -> BacktestResponse:
        """运行回测（在线程池中执行，不阻塞事件循环）。"""
        from server.app import get_app_state

        state = get_app_state()
        config = state.config
        request = _validate_backtest_strategy_params(request)

        bt_result = await asyncio.to_thread(_run_backtest, request, config, state.db)
        metrics_json = _backtest_report_metrics_json(request, bt_result)

        # 保存到数据库
        config_json = request.model_dump_json()
        equity_curve_json = json.dumps(bt_result["equity_curve"])

        result_id = await state.db.save_backtest_result(
            config_json=config_json,
            initial_cash=bt_result["initial_cash"],
            final_equity=bt_result["final_equity"],
            total_return=bt_result["total_return"],
            sharpe=bt_result["sharpe"],
            max_dd=bt_result["max_drawdown"],
            equity_curve_json=equity_curve_json,
            annual_return=bt_result["annual_return"],
            sortino=bt_result["sortino"],
            win_rate=bt_result["win_rate"],
            duration_days=bt_result["duration_days"],
            metrics_json=json.dumps(metrics_json, ensure_ascii=False),
            cost_summary_json=json.dumps(
                bt_result["cost_summary_json"], ensure_ascii=False
            ),
        )
        try:
            _write_backtest_report_file(
                result_id=result_id,
                request=request,
                bt_result=bt_result,
                metrics_json=metrics_json,
            )
        except OSError:
            logger.warning("Failed to write local backtest report", exc_info=True)

        return BacktestResponse(
            id=result_id,
            created_at="",
            config=request,
            metrics=_backtest_metrics_from_payload(bt_result),
            equity_curve=[EquityPoint(**p) for p in bt_result["equity_curve"]],
            metrics_json=metrics_json,
            research_evidence_bundle=_json_object(
                metrics_json.get("research_evidence_bundle")
            ),
            cost_summary_json=bt_result["cost_summary_json"],
            evidence_json=_backtest_evidence_from_payload(bt_result),
            fills=[BacktestFill(**fill) for fill in bt_result.get("fills", [])],
        )

    @r.post("/sweep", response_model=BacktestSweepResponse)
    async def sweep_backtest_parameters(
        request: BacktestSweepRequest,
    ) -> BacktestSweepResponse:
        """Run a bounded deterministic parameter sweep for one registered strategy."""
        from server.app import get_app_state

        state = get_app_state()
        config = state.config
        parameter_payloads = _build_parameter_grid(request)

        sweep_results: list[BacktestSweepResult] = []
        for params in parameter_payloads:
            bt_request = _validate_backtest_strategy_params(
                BacktestRequest(
                    start_date=request.start_date,
                    end_date=request.end_date,
                    initial_cash=request.initial_cash,
                    strategy=request.strategy,
                    assets=request.assets,
                    params=params,
                )
            )

            bt_result = await asyncio.to_thread(
                _run_backtest,
                bt_request,
                config,
                state.db,
            )
            metrics_json = _backtest_report_metrics_json(bt_request, bt_result)
            result_id = await state.db.save_backtest_result(
                config_json=bt_request.model_dump_json(),
                initial_cash=bt_result["initial_cash"],
                final_equity=bt_result["final_equity"],
                total_return=bt_result["total_return"],
                sharpe=bt_result["sharpe"],
                max_dd=bt_result["max_drawdown"],
                equity_curve_json=json.dumps(bt_result["equity_curve"]),
                annual_return=bt_result["annual_return"],
                sortino=bt_result["sortino"],
                win_rate=bt_result["win_rate"],
                duration_days=bt_result["duration_days"],
                metrics_json=json.dumps(metrics_json, ensure_ascii=False),
                cost_summary_json=json.dumps(
                    bt_result["cost_summary_json"],
                    ensure_ascii=False,
                ),
            )
            try:
                _write_backtest_report_file(
                    result_id=result_id,
                    request=bt_request,
                    bt_result=bt_result,
                    metrics_json=metrics_json,
                )
            except OSError:
                logger.warning("Failed to write local backtest report", exc_info=True)

            metrics = _backtest_metrics_from_payload(bt_result)
            sweep_results.append(
                BacktestSweepResult(
                    rank=0,
                    result_id=result_id,
                    strategy=request.strategy,
                    params=dict(bt_request.params or {}),
                    metrics=metrics,
                    score=_sweep_score(metrics, request.rank_by),
                    research_evidence_bundle=_json_object(
                        metrics_json.get("research_evidence_bundle")
                    ),
                )
            )

        reverse = _SWEEP_RANK_DIRECTIONS[request.rank_by] == "desc"
        ranked_results = sorted(
            sweep_results,
            key=lambda result: (result.score, -result.result_id),
            reverse=reverse,
        )
        ranked_results = [
            result.model_copy(update={"rank": index})
            for index, result in enumerate(ranked_results, start=1)
        ]
        from analytics.sweep_robustness import build_sweep_robustness_evidence

        robustness_evidence = build_sweep_robustness_evidence(
            results=[
                {
                    "params": dict(result.params),
                    "score": result.score,
                }
                for result in ranked_results
            ],
            rank_by=request.rank_by,
            rank_direction=_SWEEP_RANK_DIRECTIONS[request.rank_by],
        )
        return BacktestSweepResponse(
            strategy=request.strategy,
            rank_by=request.rank_by,
            tested_count=len(ranked_results),
            results=ranked_results,
            robustness_evidence=robustness_evidence,
            warnings=list(_SWEEP_WARNINGS),
        )

    @r.get("/results", response_model=list[BacktestSummary])
    async def list_backtest_results() -> list[BacktestSummary]:
        """获取回测结果列表。"""
        from server.app import get_app_state

        state = get_app_state()
        rows = await state.db.get_backtest_results()
        summaries: list[BacktestSummary] = []
        for row in rows:
            config_data = json.loads(row.get("config_json", "{}"))
            equity_data = json.loads(row.get("equity_curve_json", "[]"))
            metrics_json = _json_object(row.get("metrics_json"))
            cost_summary_json = _json_object(row.get("cost_summary_json"))
            metrics_payload, _ = _normalize_backtest_payload_from_equity_curve(
                row,
                metrics_json=metrics_json,
                cost_summary_json=cost_summary_json,
                equity_data=equity_data,
            )
            summaries.append(
                BacktestSummary(
                    id=row["id"],
                    created_at=row["created_at"],
                    strategy=config_data.get("strategy", "dual_ma"),
                    total_return=metrics_payload.get("total_return", 0),
                    sharpe=metrics_payload.get("sharpe", 0),
                    max_drawdown=metrics_payload.get("max_drawdown", 0),
                )
            )
        return summaries

    @r.get("/results/{result_id}", response_model=BacktestResponse)
    async def get_backtest_result(result_id: int) -> BacktestResponse:
        """获取单个回测详情 + 权益曲线。"""
        from server.app import get_app_state

        state = get_app_state()
        row = await state.db.get_backtest_result(result_id)
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Backtest result not found")

        config_data = json.loads(row.get("config_json", "{}"))
        equity_data = json.loads(row.get("equity_curve_json", "[]"))
        metrics_json = _json_object(row.get("metrics_json"))
        cost_summary_json = _json_object(row.get("cost_summary_json"))
        metrics_payload = {
            **row,
            "metrics_json": metrics_json,
            "max_drawdown": row.get("max_drawdown", row.get("max_dd", 0)),
        }
        metrics_payload, metrics_json = _normalize_backtest_payload_from_equity_curve(
            metrics_payload,
            metrics_json=metrics_json,
            cost_summary_json=cost_summary_json,
            equity_data=equity_data,
        )
        evidence_json = _json_object(metrics_json.get("evidence_bundle"))

        return BacktestResponse(
            id=row["id"],
            created_at=row["created_at"],
            config=BacktestRequest(**config_data),
            metrics=_backtest_metrics_from_payload(metrics_payload),
            equity_curve=[EquityPoint(**p) for p in equity_data],
            metrics_json=metrics_json,
            research_evidence_bundle=_json_object(
                metrics_json.get("research_evidence_bundle")
            ),
            cost_summary_json=cost_summary_json,
            evidence_json=evidence_json,
            fills=[],
        )

    @r.post("/compare", response_model=CompareResponse)
    async def compare_strategies(request: CompareRequest) -> CompareResponse:
        """Compare strategies or parameter sets on one frozen dataset snapshot."""
        from server.app import get_app_state

        import strategy.builtins  # noqa: F401
        from strategy.registry import StrategyRegistry

        state = get_app_state()
        config = state.config

        all_strategies = StrategyRegistry.get_info()
        strategy_by_name = {s["name"]: s for s in all_strategies}
        strategy_by_id = {s["strategy_id"]: s for s in all_strategies}

        if request.runs:
            run_specs = [
                {
                    "strategy": run.strategy,
                    "params": run.params,
                }
                for run in request.runs
            ]
        elif request.strategies:
            run_specs = [
                {"strategy": strategy, "params": None}
                for strategy in request.strategies
            ]
        else:
            run_specs = [
                {"strategy": strategy["name"], "params": None}
                for strategy in all_strategies
            ]

        if not run_specs:
            return CompareResponse(results=[], warnings=list(_COMPARE_WARNINGS))

        prepared_runs: list[tuple[dict[str, Any], BacktestRequest, dict[str, Any]]] = []
        snapshots: list[dict[str, Any]] = []
        snapshot_ids: list[str | None] = []
        for run_spec in run_specs:
            strat_name = str(run_spec["strategy"])
            strat_info = strategy_by_name.get(strat_name) or strategy_by_id.get(
                strat_name
            )
            if not strat_info:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "strategy": strat_name,
                        "errors": [
                            {
                                "field": "strategy",
                                "code": "unknown_strategy",
                                "message": f"Unknown strategy '{strat_name}'.",
                            }
                        ],
                    },
                )

            raw_params = run_spec["params"]
            if raw_params is None:
                raw_params = {
                    p["name"]: p.get("default")
                    for p in strat_info.get("parameter_schema", strat_info["params"])
                }
            bt_request = _validate_backtest_strategy_params(
                BacktestRequest(
                    start_date=request.start_date,
                    end_date=request.end_date,
                    initial_cash=request.initial_cash,
                    strategy=strat_info["name"],
                    assets=request.assets,
                    params=raw_params,
                )
            )

            bt_result = await asyncio.to_thread(
                _run_single_backtest, bt_request, config, state.db
            )
            metrics_json = _backtest_report_metrics_json(bt_request, bt_result)
            bt_result = {**bt_result, "metrics_json": metrics_json}
            snapshot = _dataset_snapshot_from_result(bt_result)
            snapshots.append(snapshot)
            snapshot_ids.append(_dataset_snapshot_id(snapshot))
            prepared_runs.append((strat_info, bt_request, bt_result))

        unique_snapshot_ids = {
            snapshot_id for snapshot_id in snapshot_ids if snapshot_id
        }
        if len(unique_snapshot_ids) != 1 or len(unique_snapshot_ids) != len(
            set(snapshot_ids)
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "dataset_snapshot_mismatch",
                    "message": (
                        "Strategy comparison requires every run to use the same "
                        "frozen dataset snapshot."
                    ),
                    "snapshot_ids": snapshot_ids,
                },
            )

        dataset_snapshot = snapshots[0] if snapshots else {}
        dataset_snapshot_id = _dataset_snapshot_id(dataset_snapshot)

        results: list[StrategyCompareItem] = []
        for strat_info, bt_request, bt_result in prepared_runs:
            config_json = bt_request.model_dump_json()
            equity_curve_json = json.dumps(bt_result["equity_curve"])
            metrics_json = dict(bt_result["metrics_json"])
            result_id = await state.db.save_backtest_result(
                config_json=config_json,
                initial_cash=bt_result["initial_cash"],
                final_equity=bt_result["final_equity"],
                total_return=bt_result["total_return"],
                sharpe=bt_result["sharpe"],
                max_dd=bt_result["max_drawdown"],
                equity_curve_json=equity_curve_json,
                annual_return=bt_result["annual_return"],
                sortino=bt_result["sortino"],
                win_rate=bt_result["win_rate"],
                duration_days=bt_result["duration_days"],
                metrics_json=json.dumps(metrics_json, ensure_ascii=False),
                cost_summary_json=json.dumps(
                    bt_result["cost_summary_json"], ensure_ascii=False
                ),
            )
            try:
                _write_backtest_report_file(
                    result_id=result_id,
                    request=bt_request,
                    bt_result=bt_result,
                    metrics_json=metrics_json,
                )
            except OSError:
                logger.warning("Failed to write local backtest report", exc_info=True)

            results.append(
                StrategyCompareItem(
                    strategy=bt_request.strategy,
                    description=strat_info.get("description", bt_request.strategy),
                    result_id=result_id,
                    params=dict(bt_request.params or {}),
                    dataset_snapshot_id=dataset_snapshot_id,
                    dataset_snapshot=dataset_snapshot,
                    research_evidence_bundle=_json_object(
                        metrics_json.get("research_evidence_bundle")
                    ),
                    metrics=_backtest_metrics_from_payload(bt_result),
                    equity_curve=[EquityPoint(**p) for p in bt_result["equity_curve"]],
                )
            )

        return CompareResponse(
            results=results,
            compared_count=len(results),
            dataset_snapshot_id=dataset_snapshot_id,
            dataset_snapshot=dataset_snapshot,
            warnings=list(_COMPARE_WARNINGS),
        )

    return r
