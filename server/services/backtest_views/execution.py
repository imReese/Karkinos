"""Canonical backtest execution projections."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from server.bootstrap import build_strategy, build_watchlist
from server.config import BacktestConfig
from server.models import (
    BacktestRequest,
)
from server.services.backtest_result_projection import (
    backtest_evidence_from_payload as _backtest_evidence_from_payload,
)
from server.services.backtest_result_projection import (
    fill_to_response as _fill_to_response,
)
from server.services.backtest_result_projection import json_object as _json_object
from server.services.backtest_result_projection import (
    strategy_metadata_snapshot as _strategy_metadata_snapshot,
)
from server.services.backtest_views.parameter_sweep import (
    build_oos_validation_payload,
    last_equity_from_curve,
)
from server.services.backtest_views.strategy_inputs import (
    backtest_metrics_from_payload,
    resolve_backtest_data_plane,
)

_DEFAULT_BACKTEST_REPORT_DIR = Path("reports/backtest")


def normalize_backtest_payload_from_equity_curve(
    payload: dict[str, Any],
    *,
    metrics_json: dict[str, Any],
    cost_summary_json: dict[str, Any] | None,
    equity_data: list[Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Correct legacy stored metrics when final_equity disagrees with curve end."""
    curve_final_equity = last_equity_from_curve(equity_data)
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


def backtest_report_dir() -> Path:
    return Path(
        os.environ.get("KARKINOS_BACKTEST_REPORT_DIR") or _DEFAULT_BACKTEST_REPORT_DIR
    )


def write_backtest_report_file(
    *,
    result_id: int,
    request: BacktestRequest,
    bt_result: dict[str, Any],
    metrics_json: dict[str, Any],
) -> Path:
    report_dir = backtest_report_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"backtest-result-{result_id}.json"
    payload = {
        "schema_version": "karkinos.backtest_report.v1",
        "id": result_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": request.model_dump(mode="json"),
        "metrics": backtest_metrics_from_payload(
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


def run_single_backtest(
    request: BacktestRequest,
    config: Any,
    db=None,
    *,
    history_end: date | None = None,
    evaluation_start: date | None = None,
    preloaded_dataset_inputs: tuple[dict, dict, dict, dict] | None = None,
) -> dict[str, Any]:
    """同步运行单次回测（在线程池中执行），供 run 和 compare 共用。"""
    from datetime import datetime

    from analytics.backtest_capacity_evidence import build_backtest_capacity_evidence
    from analytics.dataset_snapshot import build_backtest_dataset_snapshot
    from backtest.distributions import distributions_from_evidence
    from backtest.engine import BacktestEngine
    from data.manager import DataManager
    from data.store import DataStore
    from server.contracts.http.strategy_models import BacktestCostAssumptions
    from server.services.backtest_costs import resolve_backtest_costs
    from server.services.research_datasets import ResearchDatasetError

    dataset_binding = None
    cash_dividend_mode = getattr(request, "corporate_action_mode", "price_only")
    if (
        history_end is not None
        or evaluation_start is not None
        or preloaded_dataset_inputs is not None
    ) and not request.dataset_id:
        raise ResearchDatasetError("backtest_execution_window_dataset_required")
    if cash_dividend_mode != "price_only" and not request.dataset_id:
        raise ResearchDatasetError("cash_dividend_dataset_required")
    if getattr(request, "dataset_id", None) is not None:
        inputs = preloaded_dataset_inputs or prepare_dataset_backtest_inputs(
            request, db
        )
        instruments, data_handlers, dataset_binding, dataset_snapshot_json = inputs
        _require_preloaded_dataset_request(request, inputs)
    else:
        assets = request.assets or config.assets
        store = None
        try:
            store = DataStore()
        except Exception:
            pass

        sources, source_policy, configured_source = resolve_backtest_data_plane(config)
        dm = DataManager(
            sources=sources,
            store=store,
            source_policy=source_policy,
            default_source=(
                None
                if source_policy is not None
                else str(getattr(config, "data_source", "") or "") or None
            ),
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

        source_names = list(sources.keys())
        dataset_snapshot_json = build_backtest_dataset_snapshot(
            start_date=request.start_date,
            end_date=request.end_date,
            configured_source=configured_source,
            data_handlers=data_handlers,
            store=store,
            source_names=source_names,
        )
    data_handlers, execution_window = _windowed_data_handlers(
        request,
        data_handlers,
        dataset_snapshot_json,
        history_end=history_end,
        evaluation_start=evaluation_start,
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

    cash_dividends = None
    if cash_dividend_mode != "price_only":
        try:
            cash_dividends = distributions_from_evidence(
                (dataset_binding or {}).get("corporate_action_evidence"),
                include_shares=cash_dividend_mode == "reported_distributions_gross",
            )
            if history_end is not None:
                cash_dividends = tuple(
                    item for item in cash_dividends if item.ex_date <= history_end
                )
        except ValueError as exc:
            raise ResearchDatasetError(str(exc)) from None
    execution_config, cost_assumptions = resolve_backtest_costs(
        request.cost_assumptions
    )
    engine = BacktestEngine(
        strategy=strategy,
        instruments=instruments,
        data_handlers=data_handlers,
        initial_cash=Decimal(str(request.initial_cash)),
        execution_config=execution_config,
        db=db,
        cash_dividends=cash_dividends,
        include_share_distributions=cash_dividend_mode
        == "reported_distributions_gross",
        **(
            {"evaluation_start": evaluation_start}
            if evaluation_start is not None
            else {}
        ),
    )

    try:
        result = engine.run()
    except ValueError as exc:
        if str(exc).startswith(
            ("cash_dividend_", "share_distribution_", "portfolio_share_distribution_")
        ):
            raise ResearchDatasetError(str(exc)) from None
        raise

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
    metrics_json["execution_timing"] = result.execution_timing
    metrics_json["cost_assumptions"] = cost_assumptions
    # Two explicit adverse scenarios reuse the frozen bars, rules and fresh book;
    # stress replay never persists additional Orders/Fills or tunes parameters.
    inputs = request.cost_assumptions or BacktestCostAssumptions()
    base_bps = inputs.slippage_bps
    metrics_json["cost_sensitivity"] = []
    stress_levels = sorted(
        {min(9999.0, max(10.0, base_bps * 2)), min(9999.0, max(25.0, base_bps * 5))}
    )
    for bps in stress_levels:
        if bps <= base_bps:
            continue
        stress_config, stress_assumptions = resolve_backtest_costs(
            inputs.model_copy(update={"slippage_bps": bps})
        )
        stressed = BacktestEngine(
            strategy=build_strategy(strategy_config, event_bus_placeholder),
            instruments=instruments,
            data_handlers=data_handlers,
            initial_cash=result.initial_cash,
            execution_config=stress_config,
            cash_dividends=cash_dividends,
            include_share_distributions=cash_dividend_mode
            == "reported_distributions_gross",
            evaluation_start=evaluation_start,
        ).run()
        metrics_json["cost_sensitivity"].append(
            {
                "cost_assumptions": stress_assumptions,
                "total_return": float(stressed.total_return),
                "max_drawdown": stressed.metrics.max_drawdown,
                "fill_count": len(stressed.fills),
            }
        )
    metrics_json["capacity_review"] = build_backtest_capacity_evidence(
        fills=result.fills,
        data_handlers=data_handlers,
        initial_cash=result.initial_cash,
        max_daily_volume_participation=Decimal(
            cost_assumptions["max_volume_participation"]
        ),
    )
    if result.cash_dividend_accounting is not None:
        metrics_json["cash_dividend_accounting"] = result.cash_dividend_accounting
    metrics_json["evidence_bundle"] = evidence_json
    metrics_json["dataset_snapshot"] = dataset_snapshot_json
    if execution_window is not None:
        metrics_json["execution_window"] = execution_window
    if dataset_binding is not None:
        metrics_json["dataset_binding"] = dataset_binding
    metrics_json["strategy_metadata"] = _strategy_metadata_snapshot(request)
    oos_validation_json = build_oos_validation_payload(request, result)
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


def prepare_dataset_backtest_inputs(
    request: BacktestRequest, db=None
) -> tuple[dict, dict, dict, dict]:
    """Read and bind one full immutable source for repeated sequential runs."""
    from analytics.dataset_snapshot import build_backtest_dataset_snapshot
    from server.runtime_paths import resolve_data_dir
    from server.services.backtest_dataset_inputs import load_dataset_backtest_inputs
    from server.services.research_datasets import ResearchDatasetError

    if not request.dataset_id:
        raise ResearchDatasetError("backtest_execution_window_dataset_required")
    root = (
        db.path.resolve().parent
        if db is not None
        else Path(resolve_data_dir()).resolve()
    ) / "research"
    instruments, handlers, binding = load_dataset_backtest_inputs(root, request)
    sources = binding["source_names"]
    snapshot = build_backtest_dataset_snapshot(
        start_date=request.start_date,
        end_date=request.end_date,
        configured_source=sources[0] if len(sources) == 1 else None,
        data_handlers=handlers,
        store=None,
        source_names=sources,
        research_dataset_binding=binding,
    )
    return instruments, handlers, binding, snapshot


def _require_preloaded_dataset_request(request, inputs):
    from server.services.research_datasets import ResearchDatasetError

    instruments, _, binding, snapshot = inputs
    matches = (
        binding.get("dataset_id") == request.dataset_id
        and snapshot.get("immutable_dataset_id") == request.dataset_id
        and snapshot.get("date_range")
        == {"start": request.start_date, "end": request.end_date}
    )
    if request.assets:
        try:
            matches = matches and sorted(
                (item["symbol"], item.get("instrument_type") or item["asset_class"])
                for item in request.assets
            ) == sorted(
                (str(symbol), instrument.instrument_type.value)
                for symbol, instrument in instruments.items()
            )
        except (KeyError, TypeError, ValueError):
            matches = False
    if not matches:
        raise ResearchDatasetError("backtest_preloaded_dataset_request_mismatch")


def _windowed_data_handlers(
    request, handlers, snapshot, *, history_end, evaluation_start
):
    from data.handler import DataHandler
    from server.contracts.content_identity import content_fingerprint
    from server.services.research_datasets import ResearchDatasetError

    if history_end is None and evaluation_start is None:
        return handlers, None
    start, end = (
        date.fromisoformat(request.start_date),
        date.fromisoformat(request.end_date),
    )
    through = history_end if history_end is not None else end
    evaluate_from = evaluation_start if evaluation_start is not None else start
    if (
        type(through) is not date
        or type(evaluate_from) is not date
        or not start <= evaluate_from <= through <= end
    ):
        raise ResearchDatasetError("backtest_execution_window_invalid")
    sliced, metric_dates = {}, []
    for symbol, handler in handlers.items():
        timestamps = handler._df["timestamp"]
        if timestamps.dt.tz is not None:
            timestamps = timestamps.dt.tz_convert("Asia/Shanghai")
        dates = timestamps.dt.date
        evaluated = dates[(dates >= evaluate_from) & (dates <= through)]
        if evaluated.empty:
            raise ResearchDatasetError("backtest_execution_window_empty")
        metric_dates.extend((evaluated.min(), evaluated.max()))
        sliced[symbol] = DataHandler(
            handler._df.loc[dates <= through].copy(),
            symbol,
            frequency=handler._frequency,
            asset_class=handler._asset_class,
            instrument_type=handler.instrument_type,
        )
    if not metric_dates:
        raise ResearchDatasetError("backtest_execution_window_empty")
    window = {
        "schema_version": "karkinos.backtest_execution_window.v1",
        "source_dataset_id": request.dataset_id,
        "source_snapshot_id": snapshot["snapshot_id"],
        "source_start_date": start.isoformat(),
        "source_end_date": end.isoformat(),
        "history_end_date": through.isoformat(),
        "evaluation_start_date": evaluate_from.isoformat(),
        "evaluation_end_date": through.isoformat(),
        "metric_start_date": min(metric_dates).isoformat(),
        "metric_end_date": max(metric_dates).isoformat(),
        "warmup_policy": "strategy_state_only_no_orders_or_book_carry",
        "independent_initial_cash": True,
        "exploratory": True,
        "independent_final": False,
    }
    return sliced, {**window, "fingerprint": content_fingerprint(window)}


__all__ = (
    "backtest_report_dir",
    "normalize_backtest_payload_from_equity_curve",
    "prepare_dataset_backtest_inputs",
    "run_single_backtest",
    "write_backtest_report_file",
)
