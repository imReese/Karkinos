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


def _run_single_backtest(request: BacktestRequest, config: Any) -> dict[str, Any]:
    """同步运行单次回测（在线程池中执行），供 run 和 compare 共用。"""
    from datetime import datetime

    from analytics.metrics import (
        AnnualizedReturn,
        MaxDrawdown,
        SharpeRatio,
        SortinoRatio,
        WinRate,
    )
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

    # 计算指标
    equities = [float(e) for _, e in result.equity_curve]
    returns = [
        Decimal(str((equities[i] - equities[i - 1]) / equities[i - 1]))
        for i in range(1, len(equities))
        if equities[i - 1] != 0
    ]

    sharpe = SharpeRatio.calculate(returns)
    sortino = SortinoRatio.calculate(returns)
    max_dd = MaxDrawdown.calculate(equities)
    win_rate = WinRate.calculate(returns)
    annual_return = AnnualizedReturn.calculate(equities)

    equity_curve = [
        {"timestamp": ts.isoformat(), "equity": float(eq)}
        for ts, eq in result.equity_curve
    ]

    return {
        "initial_cash": float(result.initial_cash),
        "final_equity": float(result.final_equity),
        "total_return": float(result.total_return),
        "annual_return": annual_return,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "duration_days": result.duration_days,
        "equity_curve": equity_curve,
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
        )

        return BacktestResponse(
            id=result_id,
            created_at="",
            config=request,
            metrics=BacktestMetrics(
                initial_cash=bt_result["initial_cash"],
                final_equity=bt_result["final_equity"],
                total_return=bt_result["total_return"],
                annual_return=bt_result["annual_return"],
                sharpe=bt_result["sharpe"],
                sortino=bt_result["sortino"],
                max_drawdown=bt_result["max_drawdown"],
                win_rate=bt_result["win_rate"],
                duration_days=bt_result["duration_days"],
            ),
            equity_curve=[EquityPoint(**p) for p in bt_result["equity_curve"]],
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

        return BacktestResponse(
            id=row["id"],
            created_at=row["created_at"],
            config=BacktestRequest(**config_data),
            metrics=BacktestMetrics(
                initial_cash=row["initial_cash"],
                final_equity=row["final_equity"],
                total_return=row["total_return"],
                annual_return=row.get("annual_return", 0),
                sharpe=row["sharpe"],
                sortino=row.get("sortino", 0),
                max_drawdown=row.get("max_drawdown", 0),
                win_rate=row.get("win_rate", 0),
                duration_days=row.get("duration_days", 0),
            ),
            equity_curve=[EquityPoint(**p) for p in equity_data],
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
            )

            results.append(
                StrategyCompareItem(
                    strategy=strat_name,
                    description=strat_info.get("description", strat_name),
                    metrics=BacktestMetrics(
                        initial_cash=bt_result["initial_cash"],
                        final_equity=bt_result["final_equity"],
                        total_return=bt_result["total_return"],
                        annual_return=bt_result["annual_return"],
                        sharpe=bt_result["sharpe"],
                        sortino=bt_result["sortino"],
                        max_drawdown=bt_result["max_drawdown"],
                        win_rate=bt_result["win_rate"],
                        duration_days=bt_result["duration_days"],
                    ),
                    equity_curve=[EquityPoint(**p) for p in bt_result["equity_curve"]],
                )
            )

        return CompareResponse(results=results)

    return r
