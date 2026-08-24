"""Canonical backtest strategy inputs projections."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException

from core.events import MarketEvent
from core.types import AssetClass, BarFrequency, Symbol
from server.bootstrap import build_watchlist
from server.config import BacktestConfig
from server.contracts.http.backtest import (
    StrategySignalPreviewBar,
    StrategySignalPreviewRequest,
)
from server.models import (
    BacktestMetrics,
    BacktestRequest,
)
from server.services.backtest_result_projection import json_object as _json_object


def backtest_metrics_from_payload(payload: dict[str, Any]) -> BacktestMetrics:
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


def validate_backtest_strategy_params(request: BacktestRequest) -> BacktestRequest:
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


def validate_signal_preview_strategy_params(
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


def preview_bar_to_market_event(
    bar: StrategySignalPreviewBar,
    *,
    symbol: str,
    asset_class: str | None,
) -> MarketEvent:
    close = bar.close
    _, parsed_asset_class = signal_preview_symbol_asset_class(symbol, asset_class)
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


def signal_preview_symbol_asset_class(
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


def load_signal_preview_bars(
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

    symbol, asset_class = signal_preview_symbol_asset_class(
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


def run_strategy_signal_preview(
    request: StrategySignalPreviewRequest,
    config: Any,
) -> dict[str, Any]:
    """Run a research-only strategy signal preview from bars or data config."""
    from analytics.strategy_signal_preview import build_strategy_signal_preview

    if request.bars:
        bars = tuple(
            preview_bar_to_market_event(
                bar,
                symbol=request.symbol,
                asset_class=request.asset_class,
            )
            for bar in request.bars
        )
        dataset_snapshot = request.dataset_snapshot
    else:
        bars, dataset_snapshot = load_signal_preview_bars(request, config)

    return build_strategy_signal_preview(
        strategy_id=request.strategy,
        symbol=request.symbol,
        params=request.params,
        bars=bars,
        dataset_snapshot=dataset_snapshot,
    )


__all__ = (
    "backtest_metrics_from_payload",
    "load_signal_preview_bars",
    "preview_bar_to_market_event",
    "run_strategy_signal_preview",
    "signal_preview_symbol_asset_class",
    "validate_backtest_strategy_params",
    "validate_signal_preview_strategy_params",
)
