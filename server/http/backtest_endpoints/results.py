"""Backtest results HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def create_router(facade: Any) -> APIRouter:
    r = APIRouter(prefix="/api/backtest", tags=["backtest"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    Any = dependency("Any")
    BacktestRequest = dependency("BacktestRequest")
    BacktestResponse = dependency("BacktestResponse")
    BacktestSummary = dependency("BacktestSummary")
    CompareRequest = dependency("CompareRequest")
    CompareResponse = dependency("CompareResponse")
    EquityPoint = dependency("EquityPoint")
    HTTPException = dependency("HTTPException")
    StrategyCompareItem = dependency("StrategyCompareItem")
    _COMPARE_WARNINGS = dependency("_COMPARE_WARNINGS")
    _backtest_metrics_from_payload = dependency("_backtest_metrics_from_payload")
    _backtest_report_metrics_json = dependency("_backtest_report_metrics_json")
    _dataset_snapshot_from_result = dependency("_dataset_snapshot_from_result")
    _dataset_snapshot_id = dependency("_dataset_snapshot_id")
    _json_object = dependency("_json_object")
    _normalize_backtest_payload_from_equity_curve = dependency(
        "_normalize_backtest_payload_from_equity_curve"
    )
    _run_single_backtest = dependency("_run_single_backtest")
    _validate_backtest_strategy_params = dependency(
        "_validate_backtest_strategy_params"
    )
    _write_backtest_report_file = dependency("_write_backtest_report_file")
    asyncio = dependency("asyncio")
    json = dependency("json")
    logger = dependency("logger")

    @r.get("/results", response_model=list[BacktestSummary])
    async def list_backtest_results() -> list[BacktestSummary]:
        """获取回测结果列表。"""
        from server.dependencies import get_app_state

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
        from server.dependencies import get_app_state

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
        import strategy.builtins  # noqa: F401
        from server.dependencies import get_app_state
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
