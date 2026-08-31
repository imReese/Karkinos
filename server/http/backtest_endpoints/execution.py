"""Backtest execution HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from server.contracts.http.ledger_models import EquityPoint
from server.contracts.http.strategy_models import (
    BacktestFill,
    BacktestRequest,
    BacktestResponse,
    BacktestSweepRequest,
    BacktestSweepResponse,
    BacktestSweepResult,
)
from server.http.backtest_endpoints.dependencies import ExecutionEndpointDependencies


def create_router(dependencies: ExecutionEndpointDependencies) -> APIRouter:
    r = APIRouter(prefix="/api/backtest", tags=["backtest"])
    _SWEEP_RANK_DIRECTIONS = dependencies.sweep_rank_directions
    _SWEEP_WARNINGS = dependencies.sweep_warnings
    _backtest_evidence_from_payload = dependencies.backtest_evidence_from_payload
    _backtest_metrics_from_payload = dependencies.backtest_metrics_from_payload
    _backtest_report_metrics_json = dependencies.backtest_report_metrics_json
    _build_parameter_grid = dependencies.build_parameter_grid
    _json_object = dependencies.json_object
    _run_backtest = dependencies.run_backtest
    _sweep_score = dependencies.sweep_score
    _validate_backtest_strategy_params = dependencies.validate_backtest_strategy_params
    _write_backtest_report_file = dependencies.write_backtest_report_file
    asyncio = dependencies.asyncio_provider()
    json = dependencies.json_provider()
    logger = dependencies.logger_provider()

    @r.post("/run", response_model=BacktestResponse)
    async def run_backtest(request: BacktestRequest) -> BacktestResponse:
        """运行回测（在线程池中执行，不阻塞事件循环）。"""
        from server.dependencies import get_app_state

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
        from server.dependencies import get_app_state

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

    return r
