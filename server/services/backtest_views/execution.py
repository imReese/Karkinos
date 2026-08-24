"""Canonical backtest execution projections."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
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


__all__ = (
    "backtest_report_dir",
    "normalize_backtest_payload_from_equity_curve",
    "run_single_backtest",
    "write_backtest_report_file",
)
