"""Backtest routes — /api/backtest/*"""

from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from config import BacktestConfig
from core.types import Symbol
from server.bootstrap import build_strategy, build_watchlist
from server.models import (
    BacktestFill,
    BacktestMetrics,
    BacktestRequest,
    BacktestResponse,
    BacktestSummary,
    CompareRequest,
    CompareResponse,
    EquityPoint,
    StrategyCompareItem,
)

logger = logging.getLogger(__name__)


class StrategyInfoResponse(BaseModel):
    name: str
    description: str
    params: list[dict[str, Any]]


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


def _run_single_backtest(request: BacktestRequest, config: Any) -> dict[str, Any]:
    """同步运行单次回测（在线程池中执行），供 run 和 compare 共用。"""
    from datetime import datetime

    from backtest.engine import BacktestEngine
    from data.manager import DataManager, build_sources
    from data.store import DataStore

    assets = request.assets or config.assets
    store = None
    try:
        store = DataStore()
    except Exception:
        pass

    dm = DataManager(
        sources=build_sources(
            data_source=config.data_source,
            tushare_token=config.tushare_token,
        ),
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

    event_bus_placeholder = type(
        "EventBus", (), {"subscribe": lambda *a: None, "publish": lambda *a: None}
    )()
    strategy_config = BacktestConfig(
        strategy=request.strategy,
        short_period=request.short_period,
        long_period=request.long_period,
    )
    strategy = build_strategy(strategy_config, event_bus_placeholder)

    engine = BacktestEngine(
        strategy=strategy,
        instruments=instruments,
        data_handlers=data_handlers,
        initial_cash=Decimal(str(request.initial_cash)),
    )

    result = engine.run()

    equity_curve = [
        {"timestamp": ts.isoformat(), "equity": float(eq)}
        for ts, eq in result.equity_curve
    ]
    metrics = result.metrics

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
        "metrics_json": metrics.to_json_dict(),
        "cost_summary_json": result.cost_summary.to_json_dict(),
        "fills": [_fill_to_response(fill) for fill in result.fills],
    }


# Keep backward-compatible alias
_run_backtest = _run_single_backtest


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/backtest", tags=["backtest"])

    @r.get("/strategies", response_model=list[StrategyInfoResponse])
    async def list_strategies() -> list[StrategyInfoResponse]:
        """获取所有已注册策略及参数信息。"""
        from strategy.registry import StrategyRegistry

        return [StrategyInfoResponse(**s) for s in StrategyRegistry.get_info()]

    @r.post("/run", response_model=BacktestResponse)
    async def run_backtest(request: BacktestRequest) -> BacktestResponse:
        """运行回测（在线程池中执行，不阻塞事件循环）。"""
        from server.app import get_app_state

        state = get_app_state()
        config = state.config

        bt_result = await asyncio.to_thread(_run_backtest, request, config)

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
            metrics_json=json.dumps(bt_result["metrics_json"], ensure_ascii=False),
            cost_summary_json=json.dumps(
                bt_result["cost_summary_json"], ensure_ascii=False
            ),
        )

        return BacktestResponse(
            id=result_id,
            created_at="",
            config=request,
            metrics=_backtest_metrics_from_payload(bt_result),
            equity_curve=[EquityPoint(**p) for p in bt_result["equity_curve"]],
            metrics_json=bt_result["metrics_json"],
            cost_summary_json=bt_result["cost_summary_json"],
            fills=[BacktestFill(**fill) for fill in bt_result.get("fills", [])],
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
            summaries.append(
                BacktestSummary(
                    id=row["id"],
                    created_at=row["created_at"],
                    strategy=config_data.get("strategy", "dual_ma"),
                    total_return=row.get("total_return", 0),
                    sharpe=row.get("sharpe", 0),
                    max_drawdown=row.get("max_drawdown", 0),
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

        return BacktestResponse(
            id=row["id"],
            created_at=row["created_at"],
            config=BacktestRequest(**config_data),
            metrics=_backtest_metrics_from_payload(metrics_payload),
            equity_curve=[EquityPoint(**p) for p in equity_data],
            metrics_json=metrics_json,
            cost_summary_json=cost_summary_json,
            fills=[],
        )

    @r.post("/compare", response_model=CompareResponse)
    async def compare_strategies(request: CompareRequest) -> CompareResponse:
        """多策略对比回测：遍历指定策略（或全部），每个策略运行一次回测。"""
        from server.app import get_app_state
        from strategy.registry import StrategyRegistry

        state = get_app_state()
        config = state.config

        # 确定要对比的策略列表
        all_strategies = StrategyRegistry.get_info()
        if request.strategies:
            strategy_names = [
                s
                for s in request.strategies
                if any(a["name"] == s for a in all_strategies)
            ]
        else:
            strategy_names = [s["name"] for s in all_strategies]

        if not strategy_names:
            return CompareResponse(results=[])

        results: list[StrategyCompareItem] = []
        for strat_name in strategy_names:
            strat_info = next(
                (s for s in all_strategies if s["name"] == strat_name), None
            )
            if not strat_info:
                continue

            # 构造 BacktestRequest：使用默认策略参数
            bt_request = BacktestRequest(
                start_date=request.start_date,
                end_date=request.end_date,
                initial_cash=request.initial_cash,
                strategy=strat_name,
                assets=request.assets,
                **{p["name"]: p["default"] for p in strat_info["params"]},
            )

            bt_result = await asyncio.to_thread(
                _run_single_backtest, bt_request, config
            )

            # 保存到数据库
            config_json = bt_request.model_dump_json()
            equity_curve_json = json.dumps(bt_result["equity_curve"])
            await state.db.save_backtest_result(
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
                metrics_json=json.dumps(bt_result["metrics_json"], ensure_ascii=False),
                cost_summary_json=json.dumps(
                    bt_result["cost_summary_json"], ensure_ascii=False
                ),
            )

            results.append(
                StrategyCompareItem(
                    strategy=strat_name,
                    description=strat_info.get("description", strat_name),
                    metrics=_backtest_metrics_from_payload(bt_result),
                    equity_curve=[EquityPoint(**p) for p in bt_result["equity_curve"]],
                )
            )

        return CompareResponse(results=results)

    return r
