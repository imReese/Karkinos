"""Canonical projection helpers for canonical backtest results.

The HTTP route, AI research runtime, and background research automation all
serialize the same backtest facts through this projection.  Keeping the projection
outside ``server.routes`` prevents application code from depending on the
presentation layer.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from server.models import BacktestRequest

logger = logging.getLogger(__name__)


def json_object(raw: Any) -> dict[str, Any]:
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


def fill_to_response(fill: Any) -> dict[str, Any]:
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


def backtest_evidence_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    evidence_json = json_object(payload.get("evidence_json"))
    if evidence_json:
        return evidence_json
    metrics_json = json_object(payload.get("metrics_json"))
    return json_object(metrics_json.get("evidence_bundle"))


def strategy_metadata_snapshot(request: BacktestRequest) -> dict[str, Any]:
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


def build_backtest_report_metrics_json(
    request: BacktestRequest,
    bt_result: dict[str, Any],
) -> dict[str, Any]:
    """Attach canonical evidence and strategy identity to persisted metrics."""
    from analytics.research_evidence import build_research_evidence_bundle

    metrics_json = dict(bt_result.get("metrics_json") or {})
    metrics_json["evidence_bundle"] = backtest_evidence_from_payload(bt_result)
    strategy_metadata = strategy_metadata_snapshot(request)
    metrics_json["strategy_metadata"] = strategy_metadata
    metrics_json["research_evidence_bundle"] = build_research_evidence_bundle(
        metrics_json=metrics_json,
        cost_summary_json=dict(bt_result.get("cost_summary_json") or {}),
        evidence_json=metrics_json["evidence_bundle"],
        strategy_metadata=strategy_metadata,
        fills=list(bt_result.get("fills") or []),
    )
    return metrics_json
