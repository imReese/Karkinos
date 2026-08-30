"""Canonical normalized-notional payloads for external strategy research."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from server.ai_runtime.contracts import JsonObject

NORMALIZED_RESEARCH_NOTIONAL = 1_000_000.0
NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID = (
    "karkinos.ai.normalized_research_notional.cny_1m.v1"
)
NORMALIZED_RESEARCH_PACK_SCHEMA = "karkinos.ai.normalized_research_pack.v1"
_FORBIDDEN_EXTERNAL_KEYS = {
    "cash",
    "final_equity",
    "gross_pnl_before_costs",
    "gross_turnover",
    "initial_cash",
    "ledger_cutoff_id",
    "ledger_fingerprint",
    "lot_size",
    "market_value",
    "net_pnl",
    "positions",
    "quantity",
    "total_commission",
    "total_cost",
    "total_equity",
    "total_slippage",
    "valuation_snapshot_id",
}
_STRATEGY_PARAMETER_KEYS = (
    "bb_period",
    "entry_window",
    "entry_z",
    "exit_return",
    "exit_window",
    "exit_z",
    "long_period",
    "lookback_period",
    "max_weight",
    "min_momentum",
    "min_return",
    "neutral_weight",
    "num_std",
    "overbought",
    "oversold",
    "pair_weight",
    "rebalance_threshold",
    "rsi_period",
    "short_period",
    "symbol_a",
    "symbol_b",
    "target_annual_volatility",
    "target_weight",
    "volatility_window",
    "window",
)


def build_normalized_research_pack(
    *,
    performance: Mapping[str, Any],
    after_cost_evidence: Mapping[str, Any],
    cost_summary: Mapping[str, Any],
    research_evidence_bundle: Mapping[str, Any],
    oos_validation: Mapping[str, Any] | None = None,
) -> JsonObject:
    """Convert persisted backtest facts to ratios, basis points, and counts."""

    initial_notional = _positive_decimal(performance.get("initial_cash"))
    total_commission = _decimal(cost_summary.get("total_commission"))
    total_slippage = _decimal(cost_summary.get("total_slippage"))
    total_cost = _decimal(after_cost_evidence.get("total_cost"))
    if (
        total_cost is None
        and total_commission is not None
        and total_slippage is not None
    ):
        total_cost = total_commission + total_slippage

    pack: JsonObject = {
        "schema_version": NORMALIZED_RESEARCH_PACK_SCHEMA,
        "notional_policy_id": NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID,
        "performance_summary": _performance_summary(performance),
        "after_cost_summary": {
            "net_return_after_costs": _relative(
                after_cost_evidence.get("net_pnl"), initial_notional
            ),
            "gross_return_before_costs": _relative(
                after_cost_evidence.get("gross_pnl_before_costs"),
                initial_notional,
            ),
            "total_cost_bps": _basis_points(total_cost, initial_notional),
            "fill_count": _integer(after_cost_evidence.get("fill_count")),
            "gross_turnover_ratio": _relative(
                after_cost_evidence.get("gross_turnover")
                or cost_summary.get("gross_turnover"),
                initial_notional,
            ),
            "limitations": _strings(after_cost_evidence.get("limitations")),
        },
        "cost_summary": {
            "total_commission_bps": _basis_points(total_commission, initial_notional),
            "total_slippage_bps": _basis_points(total_slippage, initial_notional),
            "total_cost_bps": _basis_points(total_cost, initial_notional),
            "total_trades": _integer(cost_summary.get("total_trades")),
            "gross_turnover_ratio": _relative(
                cost_summary.get("gross_turnover"), initial_notional
            ),
        },
        "research_evidence_bundle": _normalized_bundle(
            research_evidence_bundle,
            initial_notional=initial_notional,
        ),
        "oos_validation": _normalized_oos(oos_validation or {}),
        "absolute_notional_values_redacted": True,
        "account_facts_included": False,
        "broker_facts_included": False,
        "authority_effect": "research_only",
    }
    return pack


def research_pack_privacy_violations(value: Any) -> list[str]:
    """Return exact forbidden-key paths from the final outbound payload."""

    violations: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for raw_key, child in item.items():
                key = str(raw_key)
                child_path = f"{path}.{key}" if path else key
                if key in _FORBIDDEN_EXTERNAL_KEYS:
                    violations.append(child_path)
                visit(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")

    visit(value, "")
    return violations


def build_normalized_signal_execution_evidence(value: Any) -> JsonObject:
    """Project the signal diagnostics through a fixed outbound field set."""

    source = value if isinstance(value, Mapping) else {}
    return {
        "schema_version": _text(source.get("schema_version")),
        "entry_signal_count": _integer(source.get("entry_signal_count")),
        "exit_signal_count": _integer(source.get("exit_signal_count")),
        "entry_target_count": _integer(source.get("entry_target_count")),
        "fill_count": _integer(source.get("fill_count")),
        "limit_blocked_count": _integer(source.get("limit_blocked_count")),
        "suspension_blocked_count": _integer(source.get("suspension_blocked_count")),
        "zero_fill_after_entry_targets": _boolean(
            source.get("zero_fill_after_entry_targets")
        ),
        "allocation_slots": _integer(source.get("allocation_slots")),
        "canonical_target_weight": _finite_float(source.get("canonical_target_weight")),
        "model_position_size_ignored": _boolean(
            source.get("model_position_size_ignored")
        ),
        "contains_absolute_balance": _boolean(source.get("contains_absolute_balance")),
        "contains_holding_quantity": _boolean(source.get("contains_holding_quantity")),
        "authority_effect": _text(source.get("authority_effect")),
        "source_evidence_fingerprint": _text(source.get("evidence_fingerprint")),
    }


def build_normalized_lot_feasibility_evidence(value: Any) -> JsonObject:
    """Expose normalized feasibility diagnostics without the absolute lot size."""

    source = value if isinstance(value, Mapping) else {}
    return {
        "schema_version": _text(source.get("schema_version")),
        "symbol_count": _integer(source.get("symbol_count")),
        "feasible_symbol_count": _integer(source.get("feasible_symbol_count")),
        "invalid_price_count": _integer(source.get("invalid_price_count")),
        "one_lot_too_expensive_count": _integer(
            source.get("one_lot_too_expensive_count")
        ),
        "allocation_slots": _integer(source.get("allocation_slots")),
        "target_weight": _finite_float(source.get("target_weight")),
        "fee_buffer_rate": _finite_float(source.get("fee_buffer_rate")),
        "model_controls_position_size": _boolean(
            source.get("model_controls_position_size")
        ),
        "contains_absolute_balance": _boolean(source.get("contains_absolute_balance")),
        "contains_holding_quantity": _boolean(source.get("contains_holding_quantity")),
        "authority_effect": _text(source.get("authority_effect")),
        "source_evidence_fingerprint": _text(source.get("evidence_fingerprint")),
    }


def _performance_summary(performance: Mapping[str, Any]) -> JsonObject:
    return {
        key: performance.get(key)
        for key in (
            "total_return",
            "annual_return",
            "sharpe",
            "sortino",
            "max_drawdown",
            "win_rate",
            "duration_days",
        )
    }


def _normalized_bundle(
    value: Mapping[str, Any],
    *,
    initial_notional: Decimal | None,
) -> JsonObject:
    analyzers = []
    raw_analyzers = value.get("analyzers")
    if isinstance(raw_analyzers, list):
        for item in raw_analyzers:
            if isinstance(item, Mapping):
                analyzers.append(
                    {
                        key: item.get(key)
                        for key in (
                            "name",
                            "status",
                            "summary",
                            "warnings",
                            "limitations",
                        )
                    }
                )
    references = value.get("evidence_references")
    safe_references = {}
    if isinstance(references, Mapping):
        safe_references = {
            key: references.get(key)
            for key in (
                "dataset_snapshot_id",
                "strategy_metadata_available",
                "after_cost_evidence_available",
                "oos_evidence_available",
                "cost_summary_available",
                "fill_count",
                "trade_count",
                "limitation_count",
            )
        }
    trade_statistics = value.get("trade_statistics")
    normalized_statistics: JsonObject = {}
    if isinstance(trade_statistics, Mapping):
        normalized_statistics = {
            "fill_count": _integer(trade_statistics.get("fill_count")),
            "trade_count": _integer(trade_statistics.get("trade_count")),
            "gross_turnover_ratio": _relative(
                trade_statistics.get("gross_turnover"), initial_notional
            ),
            "total_commission_bps": _basis_points(
                trade_statistics.get("total_commission"), initial_notional
            ),
            "total_slippage_bps": _basis_points(
                trade_statistics.get("total_slippage"), initial_notional
            ),
        }
    return {
        "schema_version": value.get("schema_version"),
        "bundle_id": value.get("bundle_id"),
        "gate_status": value.get("gate_status"),
        "dataset_snapshot_id": value.get("dataset_snapshot_id"),
        "strategy": _normalized_strategy(value.get("strategy")),
        "analyzers": analyzers,
        "evidence_references": safe_references,
        "trade_statistics": normalized_statistics,
        "china_market_assumptions": value.get("china_market_assumptions"),
        "promotion_gate": _normalized_promotion_gate(value.get("promotion_gate")),
        "limitations": _strings(value.get("limitations")),
    }


def _normalized_oos(value: Mapping[str, Any]) -> JsonObject:
    folds = value.get("folds")
    aggregate = value.get("aggregate")
    aggregate = aggregate if isinstance(aggregate, Mapping) else {}
    return {
        "strategy_id": value.get("strategy_id"),
        "benchmark_role": value.get("benchmark_role"),
        "validation_mode": value.get("validation_mode"),
        "validation_status": value.get("validation_status"),
        "fold_count": len(folds) if isinstance(folds, list) else 0,
        "equity_point_count": _integer(value.get("equity_point_count")),
        "mean_out_of_sample_return": _first_present(
            value.get("mean_out_of_sample_return"),
            aggregate.get("mean_out_of_sample_return"),
        ),
        "worst_out_of_sample_return": _first_present(
            value.get("worst_out_of_sample_return"),
            aggregate.get("worst_out_of_sample_return"),
        ),
        "pass_rate": value.get("pass_rate"),
        "assumptions": _strings(value.get("assumptions")),
        "limitations": _strings(value.get("limitations")),
    }


def _normalized_strategy(value: Any) -> JsonObject:
    source = value if isinstance(value, Mapping) else {}
    raw_params = source.get("params")
    params = raw_params if isinstance(raw_params, Mapping) else {}
    normalized_params: JsonObject = {}
    for key in _STRATEGY_PARAMETER_KEYS:
        if key not in params:
            continue
        scalar = _json_scalar(params.get(key))
        if scalar is not None:
            normalized_params[key] = scalar
    return {
        "strategy_id": _text(source.get("strategy_id")),
        "name": _text(source.get("name")),
        "display_name": _text(source.get("display_name")),
        "params": normalized_params,
    }


def _normalized_promotion_gate(value: Any) -> JsonObject:
    source = value if isinstance(value, Mapping) else {}
    return {
        "status": _text(source.get("status")),
        "manual_confirmation_required": _boolean(
            source.get("manual_confirmation_required")
        ),
        "does_not_enable_execution": _boolean(source.get("does_not_enable_execution")),
        "next_review": _text(source.get("next_review")),
    }


def _first_present(primary: Any, fallback: Any) -> Any:
    return fallback if primary is None else primary


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _positive_decimal(value: Any) -> Decimal | None:
    parsed = _decimal(value)
    return parsed if parsed is not None and parsed > 0 else None


def _relative(value: Any, initial_notional: Decimal | None) -> float | None:
    parsed = _decimal(value)
    return (
        float(parsed / initial_notional)
        if parsed is not None and initial_notional is not None
        else None
    )


def _basis_points(value: Any, initial_notional: Decimal | None) -> float | None:
    parsed = _decimal(value)
    return (
        float((parsed / initial_notional) * Decimal("10000"))
        if parsed is not None and initial_notional is not None
        else None
    )


def _integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _finite_float(value: Any) -> float | None:
    parsed = _decimal(value)
    return float(parsed) if parsed is not None else None


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _text(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _json_scalar(value: Any) -> str | int | float | bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _finite_float(value)
    return None


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]
