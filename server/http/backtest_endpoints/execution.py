"""Backtest execution HTTP endpoints."""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, HTTPException

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
from server.services.research_datasets import ResearchDatasetError


def raise_strategy_input_error(exc: ValueError) -> NoReturn:
    """Translate only the ETF strategy's declared input errors at HTTP delivery."""
    detail = str(exc)
    known = {
        "etf_rotation_universe_invalid",
        "etf_rotation_lookback_period_invalid",
        "etf_rotation_volatility_window_invalid",
        "etf_rotation_top_k_invalid",
        "etf_rotation_rebalance_interval_invalid",
        "etf_rotation_trend_filter_period_invalid",
        "etf_rotation_min_momentum_invalid",
    }
    if detail in known or detail.startswith(
        ("etf_rotation_cash_proxy_input_missing:", "etf_rotation_price_invalid:")
    ):
        raise HTTPException(status_code=400, detail=detail) from None
    raise exc


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

    async def save_result(db, request, bt_result):
        metrics_json = _backtest_report_metrics_json(request, bt_result)
        result_id = await db.save_backtest_result(
            config_json=request.model_dump_json(),
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
        return result_id, metrics_json

    @r.post("/run", response_model=BacktestResponse)
    async def run_backtest(request: BacktestRequest) -> BacktestResponse:
        """运行回测（在线程池中执行，不阻塞事件循环）。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        config = state.config
        request = _validate_backtest_strategy_params(request)

        try:
            bt_result = await asyncio.to_thread(
                _run_backtest, request, config, state.db
            )
        except ResearchDatasetError as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError as exc:
            raise_strategy_input_error(exc)
        result_id, metrics_json = await save_result(state.db, request, bt_result)

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

        def candidate_request(params):
            return _validate_backtest_strategy_params(
                BacktestRequest(
                    dataset_id=request.dataset_id,
                    corporate_action_mode=request.corporate_action_mode,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    initial_cash=request.initial_cash,
                    cost_assumptions=request.cost_assumptions,
                    strategy=request.strategy,
                    assets=request.assets,
                    params=params,
                )
            )

        chronology = None
        if request.test_start_date is not None:
            from server.services.chronological_backtest import run_chronological_sweep

            candidates = [candidate_request(params) for params in parameter_payloads]
            try:
                chronology = await asyncio.to_thread(
                    run_chronological_sweep,
                    request,
                    candidates,
                    config,
                    state.db,
                    rank_direction=_SWEEP_RANK_DIRECTIONS[request.rank_by],
                )
            except ResearchDatasetError as exc:
                raise HTTPException(409, str(exc)) from None
            except ValueError as exc:
                raise_strategy_input_error(exc)
            parameter_payloads = [item.params for item in chronology["requests"]]

        sweep_results: list[BacktestSweepResult] = []
        for index, params in enumerate(parameter_payloads):
            bt_request = candidate_request(params)

            try:
                bt_result = (
                    chronology["training"][index]
                    if chronology is not None
                    else await asyncio.to_thread(
                        _run_backtest, bt_request, config, state.db
                    )
                )
            except ResearchDatasetError as exc:
                raise HTTPException(409, str(exc)) from None
            except ValueError as exc:
                raise_strategy_input_error(exc)
            result_id, metrics_json = await save_result(state.db, bt_request, bt_result)

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
        ranked_results = (
            [sweep_results[index] for index in chronology["ranked_indices"]]
            if chronology is not None
            else sorted(
                sweep_results,
                key=lambda result: (result.score, -result.result_id),
                reverse=reverse,
            )
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
        selected_test_result_id = None
        selection = None
        if chronology is not None:
            from server.contracts.content_identity import content_fingerprint

            selection = {
                **chronology["selection"],
                "selected_training_result_id": sweep_results[
                    chronology["winner_index"]
                ].result_id,
                "training_result_ids": [item.result_id for item in sweep_results],
            }
            # Storage identities supplement the frozen selection; its original
            # fingerprint still binds the choice made before test execution.
            selection["storage_binding_fingerprint"] = content_fingerprint(selection)
            chronology["test"]["metrics_json"]["chronological_validation"] = {
                **selection,
                "role": "test",
            }
            selected_test_result_id, _ = await save_result(
                state.db,
                chronology["requests"][chronology["winner_index"]],
                chronology["test"],
            )
        return BacktestSweepResponse(
            strategy=request.strategy,
            rank_by=request.rank_by,
            tested_count=len(ranked_results),
            results=ranked_results,
            robustness_evidence=robustness_evidence,
            warnings=(
                selection["limitations"]
                if selection is not None
                else list(_SWEEP_WARNINGS)
            ),
            selected_test_result_id=selected_test_result_id,
            chronological_validation=selection,
        )

    return r
