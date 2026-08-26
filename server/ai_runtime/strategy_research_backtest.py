"""Deterministic Formula DSL adapter over canonical persisted backtest inputs."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pandas as pd

from analytics.backtest_capacity_evidence import build_backtest_capacity_evidence
from analytics.backtest_drawdown_evidence import build_backtest_drawdown_evidence
from analytics.backtest_fee_tax_evidence import build_backtest_fee_tax_evidence
from analytics.backtest_market_regime_evidence import (
    build_backtest_market_regime_evidence,
)
from analytics.dataset_snapshot import build_backtest_dataset_snapshot
from analytics.oos_validation import build_rolling_out_of_sample_validation
from analytics.research_account_capital_evidence import (
    build_research_account_capital_evidence,
    is_valid_passed_research_account_capital_evidence,
)
from analytics.sweep_robustness import build_sweep_robustness_evidence
from backtest.engine import BacktestEngine
from backtest.result import BacktestResult
from core.events import MarketEvent
from core.types import AssetClass, BarFrequency, Symbol
from data.handler import DataHandler
from data.manager import DataManager
from data.store import DataStore
from analytics.a_share_limits import (
    is_limit_down,
    is_limit_up,
    is_suspended,
    limit_rate_for_symbol,
)
from server.ai_runtime.contracts import JsonObject, content_fingerprint
from server.ai_runtime.formula_dsl import (
    CANONICAL_COST_MODEL_REFERENCE,
    FormulaBinding,
    FormulaValidationError,
    evaluate_formula,
)
from server.ai_runtime.formula_parameter_sweep import build_formula_parameter_variants
from server.ai_runtime.strategy_research_support import strategy_research_json_object
from server.contracts.strategy_research import (
    StrategyResearchRejected,
    StrategyResearchSelection,
)
from server.models import BacktestRequest
from server.projections.backtest_result import (
    build_backtest_report_metrics_json,
    fill_to_response,
)
from strategy.base import Strategy


class _FormulaSignalStrategy(Strategy):
    """Translate a validated formula into target-weight signals only."""

    def __init__(
        self,
        formula_ast: JsonObject,
        universe_size: int,
        *,
        allocation_slots: int = 4,
    ) -> None:
        super().__init__("ai_formula_research", _NullEventBus())
        self._formula_ast = formula_ast
        self._universe_size = universe_size
        self._allocation_slots = min(max(allocation_slots, 1), universe_size)
        self._canonical_target_weight = 1.0 / self._allocation_slots
        self._frames: dict[Symbol, list[dict[str, Any]]] = {}
        self._active: dict[Symbol, bool] = {}
        self._pending_target: dict[Symbol, float | None] = {}
        self._entry_signal_count = 0
        self._exit_signal_count = 0
        self._entry_target_count = 0
        self._limit_blocked_count = 0
        self._suspension_blocked_count = 0

    def on_init(self, symbols: list[Symbol]) -> None:
        self._frames = {symbol: [] for symbol in symbols}
        self._active = {symbol: False for symbol in symbols}
        self._pending_target = {symbol: None for symbol in symbols}

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        pending_target = self._pending_target[event.symbol]
        if pending_target is not None:
            if self._is_tradeable(event, pending_target):
                self.emit_signal(
                    event.symbol,
                    pending_target,
                    price=float(event.close),
                )
                self._active[event.symbol] = pending_target > 0.0
            self._pending_target[event.symbol] = None

        rows = self._frames[event.symbol]
        rows.append(
            {
                "timestamp": event.timestamp,
                "open": float(event.open),
                "high": float(event.high),
                "low": float(event.low),
                "close": float(event.close),
                "volume": float(event.volume),
            }
        )
        frame = pd.DataFrame(rows)
        entry, exit_signal, _provider_sizing_ignored = evaluate_formula(
            self._formula_ast,
            frame,
            universe_size=self._universe_size,
        )
        should_exit = bool(exit_signal.iloc[-1])
        should_enter = bool(entry.iloc[-1])
        active = self._active[event.symbol]
        if active and should_exit:
            self._exit_signal_count += 1
            self._pending_target[event.symbol] = 0.0
        elif not active and should_enter and not should_exit:
            self._entry_signal_count += 1
            self._entry_target_count += 1
            self._pending_target[event.symbol] = self._canonical_target_weight

    def _is_tradeable(self, event: MarketEvent, target: float) -> bool:
        """Apply A-share limit-up/down and suspension constraints to a fill."""

        if is_suspended(Decimal(str(event.volume))):
            self._suspension_blocked_count += 1
            return False
        frames = self._frames[event.symbol]
        if not frames:
            return True
        prev_close = Decimal(str(frames[-1]["close"]))
        rate = limit_rate_for_symbol(str(event.symbol))
        close = Decimal(str(event.close))
        if target > 0.0 and is_limit_up(close, prev_close, rate):
            self._limit_blocked_count += 1
            return False
        if target <= 0.0 and is_limit_down(close, prev_close, rate):
            self._limit_blocked_count += 1
            return False
        return True

    def execution_evidence(self, *, fill_count: int) -> JsonObject:
        """Return privacy-minimized signal-to-fill diagnostics for critique."""
        core = {
            "schema_version": "karkinos.ai.formula_signal_execution.v1",
            "entry_signal_count": self._entry_signal_count,
            "exit_signal_count": self._exit_signal_count,
            "entry_target_count": self._entry_target_count,
            "fill_count": int(fill_count),
            "limit_blocked_count": self._limit_blocked_count,
            "suspension_blocked_count": self._suspension_blocked_count,
            "zero_fill_after_entry_targets": bool(
                self._entry_target_count and not fill_count
            ),
            "allocation_slots": self._allocation_slots,
            "canonical_target_weight": self._canonical_target_weight,
            "model_position_size_ignored": True,
            "contains_absolute_balance": False,
            "contains_holding_quantity": False,
            "authority_effect": "none",
        }
        return {**core, "evidence_fingerprint": content_fingerprint(core)}


class _NullEventBus:
    def subscribe(self, *args: Any, **kwargs: Any) -> None:
        return None

    def publish(self, *args: Any, **kwargs: Any) -> None:
        return None


class RestrictedFormulaBacktestAdapter:
    """Feed validated signals to the canonical engine from persisted bars only."""

    def __init__(self, *, data_store: DataStore) -> None:
        self._data_store = data_store

    def run(
        self,
        *,
        selection: StrategyResearchSelection,
        draft: JsonObject,
        expected_dataset_snapshot: Mapping[str, Any] | None = None,
        reviewed_fee_schedule_resolution: Any | None = None,
        account_capital_evidence: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], BacktestRequest]:
        formula_ast = draft.get("formula_ast")
        if not isinstance(formula_ast, dict):
            raise StrategyResearchRejected("validated_formula_missing")
        expected_draft_binding = {
            "selected_universe": list(selection.universe),
            "dataset_snapshot_id": selection.dataset_snapshot_id,
            "test_window": {
                "start_date": selection.start_date,
                "end_date": selection.end_date,
            },
            "frequency": selection.frequency,
            "cost_model_reference": selection.cost_model_reference,
        }
        if any(
            draft.get(key) != expected
            for key, expected in expected_draft_binding.items()
        ):
            raise StrategyResearchRejected("formula_draft_binding_drift")
        binding = FormulaBinding(
            formula_ast=formula_ast,
            universe=selection.universe,
            dataset_snapshot_id=selection.dataset_snapshot_id,
            start_date=selection.start_date,
            end_date=selection.end_date,
            frequency=selection.frequency,
            cost_model_reference=selection.cost_model_reference,
            anti_lookahead_assumptions=tuple(
                str(item) for item in draft.get("anti_lookahead_assumptions") or []
            ),
            parameter_values=dict(draft.get("parameter_values") or {}),
            parameter_ranges=dict(draft.get("parameter_ranges") or {}),
            initial_cash=selection.initial_cash,
        )
        if draft.get("formula_fingerprint") != binding.fingerprint:
            raise StrategyResearchRejected("formula_binding_drift")

        handlers, instruments, snapshot = _load_bound_inputs(
            self._data_store,
            selection,
            expected_dataset_snapshot=expected_dataset_snapshot,
        )
        commission_calc, fee_schedule_evidence = validated_fee_schedule_resolution(
            selection,
            reviewed_fee_schedule_resolution,
        )
        resolved_account_capital_evidence = dict(
            account_capital_evidence
            or build_research_account_capital_evidence(
                initial_cash=selection.initial_cash,
                account_evidence=None,
                fee_schedule_evidence=fee_schedule_evidence,
                expected_valuation_snapshot_id=selection.valuation_snapshot_id,
                expected_ledger_cutoff_id=selection.ledger_cutoff_id,
            )
        )
        if account_capital_evidence is not None and not (
            is_valid_passed_research_account_capital_evidence(
                resolved_account_capital_evidence,
                expected_initial_cash=selection.initial_cash,
                expected_valuation_snapshot_id=selection.valuation_snapshot_id,
                expected_ledger_cutoff_id=selection.ledger_cutoff_id,
            )
        ):
            raise StrategyResearchRejected(
                "research_account_capital_evidence_not_passing"
            )

        allocation_slots = min(4, len(selection.universe))
        target_weight = Decimal("1") / Decimal(allocation_slots)
        formula_strategy = _FormulaSignalStrategy(
            formula_ast,
            len(selection.universe),
            allocation_slots=allocation_slots,
        )
        engine = BacktestEngine(
            strategy=formula_strategy,
            instruments=instruments,
            data_handlers=handlers,
            initial_cash=Decimal(str(selection.initial_cash)),
            commission_calc=commission_calc,
            db=None,
        )
        result = engine.run()
        metrics = result.metrics
        evidence_json = (
            result.evidence_bundle.to_json_dict()
            if result.evidence_bundle is not None
            else {}
        )
        metrics_json = metrics.to_json_dict()
        min_train_points, test_window_points, step_points = rolling_oos_parameters(
            len(result.equity_curve)
        )
        oos_validation = build_rolling_out_of_sample_validation(
            strategy_id="ai_formula_research",
            benchmark_role="formula_candidate",
            result=result,
            min_train_points=min_train_points,
            test_window_points=test_window_points,
            step_points=step_points,
        ).to_json_dict()
        parameter_robustness, parameter_sweep_failure_code = (
            _formula_parameter_robustness(
                formula_ast=formula_ast,
                parameter_values=binding.parameter_values,
                parameter_ranges=binding.parameter_ranges,
                selected_result=result,
                handlers=handlers,
                instruments=instruments,
                initial_cash=Decimal(str(selection.initial_cash)),
                commission_calc=commission_calc,
            )
        )
        metrics_json.update(
            {
                "evidence_bundle": evidence_json,
                "dataset_snapshot": snapshot,
                "oos_validation": oos_validation,
                "formula_binding": binding.to_dict(),
                "formula_fingerprint": binding.fingerprint,
                "parameter_robustness": parameter_robustness,
                "parameter_sweep_failure_code": parameter_sweep_failure_code,
                "fee_component_evidence": build_backtest_fee_tax_evidence(
                    fills=result.fills,
                    cost_model_reference=binding.cost_model_reference,
                    account_specific=bool(
                        fee_schedule_evidence.get("account_specific", False)
                    ),
                    fee_schedule_source=str(
                        fee_schedule_evidence.get("fee_schedule_source")
                        or "canonical_default_estimate"
                    ),
                    fee_schedule_fingerprint=str(
                        fee_schedule_evidence.get("fee_schedule_fingerprint") or ""
                    ),
                    broker_statement_reconciled=bool(
                        fee_schedule_evidence.get("broker_statement_reconciled", False)
                    ),
                    fee_schedule_binding=fee_schedule_evidence,
                ),
                "capacity_review": build_backtest_capacity_evidence(
                    fills=result.fills,
                    data_handlers=handlers,
                    initial_cash=result.initial_cash,
                ),
                "drawdown_evidence": build_backtest_drawdown_evidence(
                    equity_curve=result.equity_curve,
                ),
                "account_capital_constraint": resolved_account_capital_evidence,
                "market_regime_robustness": build_backtest_market_regime_evidence(
                    result=result,
                    data_handlers=handlers,
                ),
                "signal_execution_evidence": formula_strategy.execution_evidence(
                    fill_count=len(result.fills)
                ),
                "lot_feasibility_evidence": _research_lot_feasibility_evidence(
                    handlers=handlers,
                    initial_cash=Decimal(str(selection.initial_cash)),
                    target_weight=target_weight,
                ),
                "research_only": True,
                "authority_effect": "none",
            }
        )
        bt_result = {
            "initial_cash": float(result.initial_cash),
            "final_equity": float(result.final_equity),
            "total_return": float(result.total_return),
            "annual_return": metrics.annual_return,
            "sharpe": metrics.sharpe,
            "sortino": metrics.sortino,
            "max_drawdown": metrics.max_drawdown,
            "win_rate": metrics.win_rate,
            "duration_days": result.duration_days,
            "equity_curve": [
                {"timestamp": ts.isoformat(), "equity": float(value)}
                for ts, value in result.equity_curve
            ],
            "metrics_json": metrics_json,
            "cost_summary_json": result.cost_summary.to_json_dict(),
            "evidence_json": evidence_json,
            "fills": [fill_to_response(fill) for fill in result.fills],
        }
        request = BacktestRequest(
            start_date=selection.start_date,
            end_date=selection.end_date,
            initial_cash=selection.initial_cash,
            strategy="ai_formula_research",
            params={
                "draft_id": draft["draft_id"],
                "formula_fingerprint": binding.fingerprint,
                "research_only": True,
            },
            assets=[
                {"symbol": symbol, "asset_class": asset_class}
                for symbol, asset_class in zip(
                    selection.universe, selection.asset_classes, strict=True
                )
            ],
            oos_mode="rolling",
            oos_min_train_points=min_train_points,
            oos_test_window_points=test_window_points,
            oos_step_points=step_points,
        )
        bt_result["metrics_json"] = build_backtest_report_metrics_json(
            request,
            bt_result,
        )
        return bt_result, request

    def validate_selection(
        self,
        selection: StrategyResearchSelection,
        *,
        expected_dataset_snapshot: Mapping[str, Any] | None = None,
        reviewed_fee_schedule_resolution: Any | None = None,
    ) -> JsonObject:
        """Recompute persisted dataset identity without running a strategy."""
        validated_fee_schedule_resolution(
            selection,
            reviewed_fee_schedule_resolution,
        )
        _, _, snapshot = _load_bound_inputs(
            self._data_store,
            selection,
            expected_dataset_snapshot=expected_dataset_snapshot,
        )
        return snapshot

    def run_sealed(
        self,
        *,
        selection: StrategyResearchSelection,
        draft: JsonObject,
        sealed_end_date: str,
        reviewed_fee_schedule_resolution: Any | None = None,
    ) -> BacktestResult:
        """Run the frozen champion on [start, sealed_end] for one-time holdout.

        Unlike :meth:`run`, this does not enforce the operator-frozen research
        snapshot identity: the full window reaches past the research end into
        unseen future data, so the snapshot is derived and recorded by the
        caller rather than compared against the research-window snapshot.
        """
        formula_ast = draft.get("formula_ast")
        if not isinstance(formula_ast, dict):
            raise StrategyResearchRejected("validated_formula_missing")
        handlers, instruments, _ = _load_bound_inputs(
            self._data_store,
            selection,
            end_date=sealed_end_date,
            verify_snapshot=False,
        )
        commission_calc, _ = validated_fee_schedule_resolution(
            selection,
            reviewed_fee_schedule_resolution,
        )
        allocation_slots = min(4, len(selection.universe))
        formula_strategy = _FormulaSignalStrategy(
            formula_ast,
            len(selection.universe),
            allocation_slots=allocation_slots,
        )
        engine = BacktestEngine(
            strategy=formula_strategy,
            instruments=instruments,
            data_handlers=handlers,
            initial_cash=Decimal(str(selection.initial_cash)),
            commission_calc=commission_calc,
            db=None,
        )
        return engine.run()


def _formula_parameter_robustness(
    *,
    formula_ast: Mapping[str, Any],
    parameter_values: Mapping[str, Any],
    parameter_ranges: Mapping[str, Any],
    selected_result: Any,
    handlers: dict[Symbol, DataHandler],
    instruments: dict[Symbol, Any],
    initial_cash: Decimal,
    commission_calc: Any | None,
) -> tuple[dict[str, Any], str | None]:
    try:
        variants = build_formula_parameter_variants(
            formula_ast=formula_ast,
            parameter_values=parameter_values,
            parameter_ranges=parameter_ranges,
        )
    except FormulaValidationError as exc:
        return (
            build_sweep_robustness_evidence(
                results=[],
                rank_by="after_cost_total_return",
                rank_direction="desc",
                selected_params=dict(parameter_values),
            ),
            f"{exc.code}:{exc.path}",
        )

    results = []
    for variant in variants:
        if dict(variant.params) == dict(parameter_values):
            variant_result = selected_result
        else:
            variant_result = BacktestEngine(
                strategy=_FormulaSignalStrategy(
                    variant.formula_ast,
                    len(instruments),
                    allocation_slots=4,
                ),
                instruments=instruments,
                data_handlers=handlers,
                initial_cash=initial_cash,
                commission_calc=commission_calc,
                db=None,
            ).run()
        results.append(
            {
                "params": dict(variant.params),
                "score": float(variant_result.total_return),
            }
        )
    return (
        build_sweep_robustness_evidence(
            results=results,
            rank_by="after_cost_total_return",
            rank_direction="desc",
            selected_params=dict(parameter_values),
        ),
        None,
    )


def _research_lot_feasibility_evidence(
    *,
    handlers: Mapping[Symbol, DataHandler],
    initial_cash: Decimal,
    target_weight: Decimal,
) -> JsonObject:
    """Summarize whether the local fixed sizing can purchase one stock lot."""
    lot_size = Decimal("100")
    fee_buffer = Decimal("1.01")
    per_name_budget = initial_cash * target_weight
    feasible_count = 0
    invalid_price_count = 0
    one_lot_too_expensive_count = 0
    for handler in handlers.values():
        frame = getattr(handler, "_df", None)
        if (
            not isinstance(frame, pd.DataFrame)
            or frame.empty
            or "close" not in frame.columns
        ):
            invalid_price_count += 1
            continue
        try:
            close = Decimal(str(frame["close"].iloc[-1]))
        except Exception:
            invalid_price_count += 1
            continue
        if not close.is_finite() or close <= 0:
            invalid_price_count += 1
        elif close * lot_size * fee_buffer <= per_name_budget:
            feasible_count += 1
        else:
            one_lot_too_expensive_count += 1
    core = {
        "schema_version": "karkinos.ai.research_lot_feasibility.v1",
        "symbol_count": len(handlers),
        "feasible_symbol_count": feasible_count,
        "invalid_price_count": invalid_price_count,
        "one_lot_too_expensive_count": one_lot_too_expensive_count,
        "lot_size": int(lot_size),
        "allocation_slots": int(Decimal("1") / target_weight),
        "target_weight": float(target_weight),
        "fee_buffer_rate": 0.01,
        "model_controls_position_size": False,
        "contains_absolute_balance": False,
        "contains_holding_quantity": False,
        "authority_effect": "none",
    }
    return {**core, "evidence_fingerprint": content_fingerprint(core)}


def validated_fee_schedule_resolution(
    selection: StrategyResearchSelection,
    resolution: Any | None,
) -> tuple[Any | None, dict[str, Any]]:
    """Bind a reviewed reference to the exact calculator and persisted review."""
    reviewed = selection.cost_model_reference != CANONICAL_COST_MODEL_REFERENCE
    if not reviewed:
        if resolution is not None:
            raise StrategyResearchRejected("unexpected_reviewed_fee_schedule")
        return None, {}
    if resolution is None:
        raise StrategyResearchRejected("reviewed_fee_schedule_resolution_missing")
    if (
        str(getattr(resolution, "cost_model_reference", ""))
        != selection.cost_model_reference
    ):
        raise StrategyResearchRejected("reviewed_fee_schedule_resolution_drift")
    calculator = getattr(resolution, "commission_calc", None)
    evidence = getattr(resolution, "fee_evidence", None)
    if calculator is None or not isinstance(evidence, Mapping):
        raise StrategyResearchRejected("reviewed_fee_schedule_resolution_invalid")
    return calculator, dict(evidence)


def validate_persisted_fee_schedule_binding(
    selection: StrategyResearchSelection,
    metrics: Mapping[str, Any],
    resolution: Any | None,
) -> None:
    """Reject critique when persisted costs no longer bind to the active review."""

    if selection.cost_model_reference == CANONICAL_COST_MODEL_REFERENCE:
        if resolution is not None:
            raise StrategyResearchRejected("unexpected_reviewed_fee_schedule")
        return
    _, expected = validated_fee_schedule_resolution(selection, resolution)
    persisted = strategy_research_json_object(metrics.get("fee_component_evidence"))
    persisted_binding = strategy_research_json_object(
        persisted.get("fee_schedule_binding")
    )
    binding_keys = {
        "fee_schedule_review_id",
        "fee_schedule_review_fingerprint",
        "fee_schedule_preview_fingerprint",
        "account_truth_import_run_id",
        "account_truth_source_fingerprint",
        "account_truth_scope_fingerprint",
        "effective_start_date",
        "effective_end_date",
        "fee_notional_envelope_enforced",
        "fee_notional_envelope_fingerprint",
        "fee_notional_covered_asset_classes",
    }
    expected_binding = {
        key: expected.get(key) for key in binding_keys if expected.get(key) is not None
    }
    if (
        persisted.get("cost_model_reference") != selection.cost_model_reference
        or persisted.get("account_specific") is not True
        or persisted.get("broker_statement_reconciled") is not True
        or persisted.get("fee_schedule_fingerprint")
        != expected.get("fee_schedule_fingerprint")
        or persisted_binding != expected_binding
    ):
        raise StrategyResearchRejected("persisted_fee_schedule_binding_drift")


def rolling_oos_parameters(equity_point_count: int) -> tuple[int, int, int]:
    """Choose deterministic rolling windows while requiring real holdout data."""
    if equity_point_count < 6:
        raise StrategyResearchRejected("oos_history_too_short")
    test_window = max(2, equity_point_count // 5)
    min_train = max(4, equity_point_count - (test_window * 2))
    if min_train + test_window > equity_point_count:
        min_train = equity_point_count - test_window
    return min_train, test_window, test_window


def _slice_frame(frame: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    result = frame.copy()
    if "timestamp" not in result.columns:
        raise StrategyResearchRejected("persisted_bars_timestamp_missing")
    result["timestamp"] = pd.to_datetime(result["timestamp"])
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    return (
        result.loc[(result["timestamp"] >= start) & (result["timestamp"] <= end)]
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def _load_bound_inputs(
    data_store: DataStore,
    selection: StrategyResearchSelection,
    *,
    expected_dataset_snapshot: Mapping[str, Any] | None = None,
    end_date: str | None = None,
    verify_snapshot: bool = True,
) -> tuple[dict[Symbol, DataHandler], dict[Symbol, Any], JsonObject]:
    effective_end = end_date or selection.end_date
    handlers: dict[Symbol, DataHandler] = {}
    instruments: dict[Symbol, Any] = {}
    for symbol_text, asset_class_text in zip(
        selection.universe, selection.asset_classes, strict=True
    ):
        symbol = Symbol(symbol_text)
        try:
            asset_class = (
                AssetClass.FUND
                if asset_class_text == "etf"
                else AssetClass(asset_class_text)
            )
        except ValueError as exc:
            raise StrategyResearchRejected("asset_class_invalid") from exc
        frame = data_store.load_bars(symbol, BarFrequency.DAILY)
        if frame is None:
            raise StrategyResearchRejected(f"persisted_bars_missing:{symbol_text}")
        sliced = _slice_frame(frame, selection.start_date, effective_end)
        if sliced.empty:
            raise StrategyResearchRejected(f"persisted_window_empty:{symbol_text}")
        handlers[symbol] = DataHandler(
            sliced,
            symbol,
            BarFrequency.DAILY,
            asset_class,
        )
        instruments[symbol] = DataManager.get_instrument(symbol, asset_class)
    configured_source: str | None = None
    source_names: list[str] = []
    if expected_dataset_snapshot is not None:
        if (
            expected_dataset_snapshot.get("snapshot_id")
            != selection.dataset_snapshot_id
        ):
            raise StrategyResearchRejected("saved_dataset_snapshot_drift")
        provider = expected_dataset_snapshot.get("provider")
        if not isinstance(provider, Mapping):
            raise StrategyResearchRejected("saved_dataset_provider_missing")
        configured_source_value = provider.get("configured_source")
        if configured_source_value is not None and not isinstance(
            configured_source_value, str
        ):
            raise StrategyResearchRejected("saved_dataset_provider_invalid")
        available_sources = provider.get("available_sources")
        if not isinstance(available_sources, list) or not all(
            isinstance(item, str) for item in available_sources
        ):
            raise StrategyResearchRejected("saved_dataset_provider_invalid")
        configured_source = configured_source_value
        source_names = list(available_sources)
    snapshot = build_backtest_dataset_snapshot(
        start_date=selection.start_date,
        end_date=effective_end,
        configured_source=configured_source,
        data_handlers=handlers,
        store=data_store,
        source_names=source_names,
    )
    if verify_snapshot and snapshot.get("snapshot_id") != selection.dataset_snapshot_id:
        raise StrategyResearchRejected("dataset_snapshot_drift")
    if snapshot.get("data_quality", {}).get("status") != "ok":
        raise StrategyResearchRejected("dataset_quality_not_complete")
    return handlers, instruments, snapshot
