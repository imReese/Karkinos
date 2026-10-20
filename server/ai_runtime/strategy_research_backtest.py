"""Deterministic Formula DSL adapter over canonical persisted backtest inputs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from analytics.backtest_capacity_evidence import build_backtest_capacity_evidence
from analytics.backtest_drawdown_evidence import build_backtest_drawdown_evidence
from analytics.backtest_fee_tax_evidence import (
    BACKTEST_FEE_TAX_EVIDENCE_SCHEMA_VERSION,
    build_backtest_fee_tax_evidence,
)
from analytics.backtest_market_regime_evidence import (
    build_backtest_market_regime_evidence,
)
from analytics.dataset_snapshot import (
    build_backtest_dataset_snapshot,
    verify_backtest_dataset_snapshot_replay,
)
from analytics.oos_validation import build_rolling_out_of_sample_validation
from analytics.research_account_capital_evidence import (
    build_research_account_capital_evidence,
    is_valid_passed_research_account_capital_evidence,
)
from analytics.sweep_robustness import build_sweep_robustness_evidence
from backtest.costs import (
    RESEARCH_COST_STRESS_BPS,
    research_friction_assumptions,
)
from backtest.distributions import StockDistribution, distributions_from_evidence
from backtest.engine import BacktestEngine, research_execution_config
from backtest.result import BacktestResult
from core.events import MarketEvent
from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from data.dataset.reader import daily_bar_dataset_read_scope
from data.handler import DataHandler
from data.manager import DataManager
from data.research_market_data import load_research_market_frames
from data.store import DataStore
from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
from server.ai_runtime.contracts import JsonObject, content_fingerprint
from server.ai_runtime.formula_dsl import (
    CANONICAL_COST_MODEL_REFERENCE,
    FORMULA_AST_CONTRACT,
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
from server.projections.normalized_research_operation_preview import (
    build_normalized_research_operation_preview,
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
        strategy_id: str = "ai_formula_research",
        portfolio_policy_id: str | None = None,
        retain_session_decisions: bool = False,
    ) -> None:
        super().__init__(strategy_id, _NullEventBus())
        self._formula_ast = formula_ast
        self._universe_size = universe_size
        self._allocation_slots = (
            max(allocation_slots, 1)
            if portfolio_policy_id
            else min(max(allocation_slots, 1), universe_size)
        )
        self._canonical_target_weight = 1.0 / self._allocation_slots
        self._frames: dict[Symbol, list[dict[str, Any]]] = {}
        self._active: dict[Symbol, bool] = {}
        self._position_quantity: dict[Symbol, Decimal] = {}
        self._entry_signal_count = 0
        self._exit_signal_count = 0
        self._entry_target_count = 0
        self._portfolio_policy_id = portfolio_policy_id
        self._prepared_sessions = None
        self._retain_session_decisions = retain_session_decisions
        self.session_decisions: list[dict[str, Any]] = []
        self.session_books: list[dict[str, Any]] = []

    def on_init(self, symbols: list[Symbol]) -> None:
        self._frames = {symbol: [] for symbol in symbols}
        self._active = {symbol: False for symbol in symbols}
        self._position_quantity = {symbol: Decimal("0") for symbol in symbols}

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        if self._portfolio_policy_id is not None:
            return
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
            self.emit_signal(event.symbol, 0.0, price=float(event.close))
        elif not active and should_enter and not should_exit:
            self._entry_signal_count += 1
            self._entry_target_count += 1
            self.emit_signal(
                event.symbol, self._canonical_target_weight, price=float(event.close)
            )

    def on_position_update(self, symbol: Symbol, quantity: Decimal) -> None:
        self._position_quantity[symbol] = quantity
        self._active[symbol] = quantity > 0

    def bind_portfolio_engine(
        self,
        engine: BacktestEngine,
        handlers,
        *,
        slippage_bps=Decimal("5"),
        session_memberships=None,
        session_nontrading_instruments=None,
        minimum_history_rows=60,
        entry_board_policy=None,
    ) -> None:
        """Opt into the new version without changing saved legacy strategy runs."""
        if self._portfolio_policy_id is None:
            return
        if self._portfolio_policy_id != FORMULA_PORTFOLIO_POLICY_ID:
            raise StrategyResearchRejected("formula_portfolio_policy_unsupported")
        from server.ai_runtime.formula_portfolio import (
            formula_session_targets,
            prepare_formula_sessions,
        )

        self._prepared_sessions = prepare_formula_sessions(
            self._formula_ast,
            {str(symbol): handler._df for symbol, handler in handlers.items()},
            universe_size=self._universe_size,
        )

        def decide(day):
            # The selected set is resolved before any next-session execution;
            # fills, not yesterday's desired weights, supply the active book.
            eligible = (
                session_memberships(day)
                if session_memberships
                else [
                    symbol
                    for symbol, frame in self._prepared_sessions.items()
                    if day in frame.index
                ]
            )
            decision = formula_session_targets(
                prepared=self._prepared_sessions,
                decision_session=day,
                quantities={
                    str(s): p.quantity for s, p in engine.portfolio.positions.items()
                },
                cash=engine.portfolio.cash,
                equity=engine.portfolio.total_equity,
                instruments=engine.instruments,
                commission_calc=engine.execution.commission_calc,
                eligible_symbols=eligible,
                slippage_bps=slippage_bps,
                minimum_history_rows=minimum_history_rows,
                max_positions=self._allocation_slots,
                max_symbol_weight=Decimal(str(self._canonical_target_weight)),
                entry_board_policy=entry_board_policy,
                nontrading_symbols=(
                    session_nontrading_instruments(day)
                    if session_nontrading_instruments
                    else None
                ),
            )
            if not engine._warming_up:
                self.session_books.append(
                    {
                        "session": day.isoformat(),
                        "equity": str(engine.portfolio.total_equity),
                        "cash": str(engine.portfolio.cash),
                        "position_values": {
                            str(s): str(p.market_value)
                            for s, p in engine.portfolio.positions.items()
                            if p.quantity > 0
                        },
                        **(
                            {
                                "nontrading_valuations": [
                                    {
                                        "symbol": row["symbol"],
                                        "valuation_basis": row["valuation_basis"],
                                        "observation_session": row[
                                            "observation_session"
                                        ],
                                        "reference_close": row["reference_close"],
                                        "tradable": False,
                                    }
                                    for row in decision["forecasts"]
                                    if row.get("valuation_basis")
                                ]
                            }
                            if any(
                                row.get("valuation_basis")
                                for row in decision["forecasts"]
                            )
                            else {}
                        ),
                    }
                )
            if self._retain_session_decisions:
                self.session_decisions.append(decision)
            self._entry_signal_count += len(decision["selected_entries"])
            self._entry_target_count += len(decision["selected_entries"])
            self._exit_signal_count += len(decision["exit_symbols"])
            # A held weight describes the actual book, not a maintenance trade.
            # Reapplying it at the next close would rebalance on price drift.
            for symbol in [*decision["exit_symbols"], *decision["selected_entries"]]:
                weight = decision["target_weights"][symbol]
                frame = self._prepared_sessions[symbol]
                self.emit_signal(
                    Symbol(symbol),
                    weight,
                    Decimal(str(frame.loc[:day, "close"].iloc[-1])),
                )

        engine._session_decision = decide

    def execution_evidence(
        self, *, fill_count: int, execution_timing: Mapping[str, Any] | None = None
    ) -> JsonObject:
        """Return privacy-minimized signal-to-fill diagnostics for critique."""
        timing = execution_timing or {}
        core = {
            "schema_version": "karkinos.ai.formula_signal_execution.v1",
            "entry_signal_count": self._entry_signal_count,
            "exit_signal_count": self._exit_signal_count,
            "entry_target_count": self._entry_target_count,
            "fill_count": int(fill_count),
            "limit_blocked_count": timing.get("limit_blocked_count", 0),
            "suspension_blocked_count": timing.get("suspension_blocked_count", 0),
            "zero_fill_after_entry_targets": bool(
                self._entry_target_count and not fill_count
            ),
            "allocation_slots": self._allocation_slots,
            "canonical_target_weight": self._canonical_target_weight,
            "execution_policy": "karkinos.research.next_bar_close.four_slots.v1",
            "model_position_size_ignored": True,
            "contains_absolute_balance": False,
            "contains_holding_quantity": False,
            "authority_effect": "none",
        }
        if self._portfolio_policy_id is not None:
            core["portfolio_policy_id"] = self._portfolio_policy_id
            core["execution_policy"] = self._portfolio_policy_id
        return {**core, "evidence_fingerprint": content_fingerprint(core)}


class _NullEventBus:
    def subscribe(self, *args: Any, **kwargs: Any) -> None:
        return None

    def publish(self, *args: Any, **kwargs: Any) -> None:
        return None


class RestrictedFormulaBacktestAdapter:
    """Feed validated signals to the canonical engine from persisted bars only."""

    def __init__(
        self, *, data_store: DataStore, research_root: Path | None = None
    ) -> None:
        self._data_store = data_store
        root = Path(data_store._root)
        self._research_root = (
            Path(research_root)
            if research_root is not None
            else root
            if (root / "objects").is_dir()
            else root / "research"
        )

    @daily_bar_dataset_read_scope(join_existing=True)
    def run(
        self,
        *,
        selection: StrategyResearchSelection,
        draft: JsonObject,
        expected_dataset_snapshot: Mapping[str, Any] | None = None,
        reviewed_fee_schedule_resolution: Any | None = None,
        account_capital_evidence: Mapping[str, Any] | None = None,
        entry_board_policy: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], BacktestRequest]:
        if entry_board_policy is not None:
            from server.contracts.recommendation_publication import (
                validate_entry_board_policy,
            )

            entry_board_policy = validate_entry_board_policy(entry_board_policy)
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
            research_root=self._research_root,
        )
        session_memberships = session_nontrading_instruments = distributions = None
        if selection.portfolio_policy_id and snapshot.get("immutable_dataset_id"):
            session_memberships, session_nontrading_instruments, distributions = (
                _bound_formula_portfolio_inputs(self._research_root, snapshot)
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

        allocation_slots = (
            (selection.deployment_scope or {})
            .get("universe_policy", {})
            .get("allocation_slots", 4)
            if selection.portfolio_policy_id
            else min(4, len(selection.universe))
        )
        target_weight = Decimal("1") / Decimal(allocation_slots)
        if selection.portfolio_policy_id:
            from domain.instrument import make_research_stock

            instruments = {
                s: make_research_stock(str(s), i.name) for s, i in instruments.items()
            }
        formula_strategy = _FormulaSignalStrategy(
            formula_ast,
            len(selection.universe),
            allocation_slots=allocation_slots,
            portfolio_policy_id=selection.portfolio_policy_id,
        )
        engine = BacktestEngine(
            strategy=formula_strategy,
            instruments=instruments,
            data_handlers=handlers,
            initial_cash=Decimal(str(selection.initial_cash)),
            commission_calc=commission_calc,
            execution_config=research_execution_config(
                commission_calc,
                stream_sorted_data_handlers=bool(selection.deployment_scope),
            ),
            db=None,
            cash_dividends=distributions,
            include_share_distributions=distributions is not None,
            strict_event_errors=bool(selection.deployment_scope),
        )
        formula_strategy.bind_portfolio_engine(
            engine,
            handlers,
            entry_board_policy=entry_board_policy,
            session_memberships=session_memberships,
            session_nontrading_instruments=session_nontrading_instruments,
            minimum_history_rows=(selection.deployment_scope or {})
            .get("universe_policy", {})
            .get("minimum_history_rows", 60),
        )
        result = engine.run()
        formula_strategy._prepared_sessions = None
        del engine
        metrics = result.metrics
        evidence_json = (
            result.evidence_bundle.to_json_dict()
            if result.evidence_bundle is not None
            else {}
        )
        metrics_json = metrics.to_json_dict()
        if result.cash_dividend_accounting is not None:
            metrics_json["cash_dividend_accounting"] = result.cash_dividend_accounting
        if selection.simulation_validation_binding is not None:
            metrics_json["simulation_validation_binding"] = (
                selection.simulation_validation_binding
            )
        if entry_board_policy is not None:
            metrics_json["entry_board_policy"] = dict(entry_board_policy)
        metrics_json["execution_timing"] = result.execution_timing
        metrics_json["cost_assumptions"] = {
            **research_friction_assumptions(),
            "commission_model_reference": selection.cost_model_reference,
        }
        metrics_json["cost_sensitivity"] = _run_cost_stress_scenarios(
            formula_ast=formula_ast,
            instruments=instruments,
            handlers=handlers,
            selection=selection,
            allocation_slots=allocation_slots,
            commission_calc=commission_calc,
            entry_board_policy=entry_board_policy,
            session_memberships=session_memberships,
            session_nontrading_instruments=session_nontrading_instruments,
            distributions=distributions,
        )
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
                portfolio_policy_id=selection.portfolio_policy_id,
                allocation_slots=allocation_slots,
                entry_board_policy=entry_board_policy,
                session_memberships=session_memberships,
                session_nontrading_instruments=session_nontrading_instruments,
                distributions=distributions,
                strict_event_errors=bool(selection.deployment_scope),
                minimum_history_rows=(selection.deployment_scope or {})
                .get("universe_policy", {})
                .get("minimum_history_rows", 60),
            )
        )
        metrics_json.update(
            {
                "evidence_bundle": evidence_json,
                "dataset_snapshot": snapshot,
                "oos_validation": oos_validation,
                "formula_binding": binding.to_dict(),
                **(
                    {"source_selection": selection.to_dict()}
                    if selection.portfolio_policy_id
                    else {}
                ),
                "formula_fingerprint": binding.fingerprint,
                **(
                    {"entry_board_policy": dict(entry_board_policy)}
                    if entry_board_policy is not None
                    else {}
                ),
                **(
                    {
                        "deployment_scope": selection.deployment_scope,
                        "portfolio_policy_id": selection.portfolio_policy_id,
                    }
                    if selection.deployment_scope
                    else {}
                ),
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
                    max_daily_volume_participation=Decimal(
                        research_friction_assumptions()["max_volume_participation"]
                    ),
                ),
                "drawdown_evidence": build_backtest_drawdown_evidence(
                    equity_curve=result.equity_curve,
                    initial_cash=result.initial_cash,
                ),
                "account_capital_constraint": resolved_account_capital_evidence,
                "market_regime_robustness": build_backtest_market_regime_evidence(
                    result=result,
                    data_handlers=handlers,
                ),
                "signal_execution_evidence": formula_strategy.execution_evidence(
                    fill_count=len(result.fills),
                    execution_timing=result.execution_timing,
                ),
                "lot_feasibility_evidence": _research_lot_feasibility_evidence(
                    handlers=handlers,
                    initial_cash=Decimal(str(selection.initial_cash)),
                    target_weight=target_weight,
                ),
                "normalized_research_operation_preview": (
                    build_normalized_research_operation_preview(
                        formula_ast=formula_ast,
                        frames={
                            str(symbol): handler._df
                            for symbol, handler in handlers.items()
                        },
                        dataset_snapshot_id=selection.dataset_snapshot_id,
                        formula_fingerprint=binding.fingerprint,
                        research_window_end_date=selection.end_date,
                        allocation_slots=allocation_slots,
                    )
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
                **(
                    {"entry_board_policy": dict(entry_board_policy)}
                    if entry_board_policy is not None
                    else {}
                ),
                **(
                    {
                        "deployment_scope": selection.deployment_scope,
                        "portfolio_policy_id": selection.portfolio_policy_id,
                    }
                    if selection.deployment_scope
                    else {}
                ),
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
            research_root=self._research_root,
        )
        return snapshot

    @daily_bar_dataset_read_scope(join_existing=True)
    def run_sealed(
        self,
        *,
        selection: StrategyResearchSelection,
        draft: JsonObject,
        sealed_end_date: str,
        reviewed_fee_schedule_resolution: Any | None = None,
        expected_dataset_snapshot: Mapping[str, Any] | None = None,
        expected_trading_dates: list[str] | None = None,
        initial_cash_override: Decimal | None = None,
        evaluation_dataset_snapshot: Mapping[str, Any] | None = None,
        commission_calc_override: Any = None,
        entry_board_policy: Mapping[str, Any] | None = None,
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
        extended_snapshot = expected_dataset_snapshot
        if evaluation_dataset_snapshot is not None:
            extended_snapshot = evaluation_dataset_snapshot
        if (
            expected_dataset_snapshot is not None
            and expected_dataset_snapshot.get("immutable_dataset_id")
            and evaluation_dataset_snapshot is None
        ):
            raise StrategyResearchRejected(
                "sealed_immutable_dataset_extension_unsupported"
            )
        if expected_dataset_snapshot is not None:
            # Verify the research prefix before admitting any newly observed bars.
            prefix_handlers, _, _ = _load_bound_inputs(
                self._data_store,
                selection,
                expected_dataset_snapshot=expected_dataset_snapshot,
                research_root=self._research_root,
            )
            old_binding = expected_dataset_snapshot.get("market_data_binding")
            if old_binding is not None and evaluation_dataset_snapshot is None:
                from data.research_market_data import research_market_binding

                providers = {ref["provider_name"] for ref in old_binding["receipts"]}
                receipts = [
                    row
                    for row in self._data_store.list_market_daily_ingestion_receipts(
                        start_date=selection.start_date,
                        end_date=sealed_end_date,
                    )
                    if row["provider_name"] in providers
                ]
                full_binding = research_market_binding(receipts)
                prefix = [
                    ref
                    for ref in full_binding["receipts"]
                    if ref["trade_date"] <= selection.end_date
                ]
                if prefix != old_binding["receipts"]:
                    raise StrategyResearchRejected("sealed_research_prefix_drift")
                extended_snapshot = {
                    **expected_dataset_snapshot,
                    "market_data_binding": full_binding,
                }
        handlers, instruments, snapshot = _load_bound_inputs(
            self._data_store,
            selection,
            expected_dataset_snapshot=extended_snapshot,
            research_root=self._research_root,
            end_date=sealed_end_date,
            verify_snapshot=False,
            allow_extended_binding=True,
        )
        if (
            evaluation_dataset_snapshot is None
            and expected_dataset_snapshot is not None
            and any(
                handler._df["timestamp"].iloc[-1].date().isoformat()
                != (
                    expected_trading_dates[-1]
                    if expected_trading_dates
                    else sealed_end_date
                )
                for handler in handlers.values()
            )
        ):
            raise StrategyResearchRejected("sealed_window_not_complete")
        if (
            evaluation_dataset_snapshot is None
            and expected_trading_dates is not None
            and any(
                handler._df["timestamp"]
                .dt.date.map(lambda value: value.isoformat())
                .tolist()
                != expected_trading_dates
                for handler in handlers.values()
            )
        ):
            raise StrategyResearchRejected(
                "sealed_trading_calendar_coverage_incomplete"
            )
        if expected_dataset_snapshot is not None:
            for symbol, prefix_handler in prefix_handlers.items():
                expected_frame = prefix_handler._df
                if symbol not in handlers:
                    if evaluation_dataset_snapshot is not None:
                        continue
                    raise StrategyResearchRejected("sealed_research_prefix_drift")
                actual_frame = _slice_frame(
                    handlers[symbol]._df, selection.start_date, selection.end_date
                )
                if evaluation_dataset_snapshot is not None:
                    if actual_frame.empty:
                        continue
                    # Bounded warmup is permitted only under the new scope;
                    # every overlapping original observation remains identical.
                    expected_frame = expected_frame.loc[
                        expected_frame["timestamp"].dt.date.isin(
                            actual_frame["timestamp"].dt.date
                        )
                    ].copy()
                    actual_frame = actual_frame.copy()
                    for frame in (expected_frame, actual_frame):
                        frame["timestamp"] = frame["timestamp"].dt.date
                        for name in (
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                            "amount",
                        ):
                            if name in frame:
                                frame[name] = frame[name].map(
                                    lambda value: Decimal(str(value))
                                )
                columns = [
                    name
                    for name in (
                        "timestamp",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "amount",
                    )
                    if name in expected_frame
                ]
                if (
                    not expected_frame[columns]
                    .reset_index(drop=True)
                    .equals(actual_frame[columns].reset_index(drop=True))
                ):
                    raise StrategyResearchRejected("sealed_research_prefix_drift")
        commission_calc, _ = validated_fee_schedule_resolution(
            selection,
            reviewed_fee_schedule_resolution,
        )
        if commission_calc_override is not None:
            if not selection.deployment_scope or evaluation_dataset_snapshot is None:
                raise StrategyResearchRejected(
                    "sealed_commission_override_not_admitted"
                )
            commission_calc = commission_calc_override
        allocation_slots = (
            (selection.deployment_scope or {})
            .get("universe_policy", {})
            .get("allocation_slots", 4)
            if selection.portfolio_policy_id
            else min(4, len(instruments))
        )
        session_memberships = None
        session_nontrading_instruments = None
        distributions = None
        if evaluation_dataset_snapshot is not None:
            session_memberships, session_nontrading_instruments, distributions = (
                _bound_formula_portfolio_inputs(
                    self._research_root,
                    evaluation_dataset_snapshot,
                    require_distributions=True,
                )
            )
        if selection.portfolio_policy_id:
            from domain.instrument import make_research_stock

            instruments = {
                s: make_research_stock(str(s), i.name) for s, i in instruments.items()
            }
        formula_strategy = _FormulaSignalStrategy(
            formula_ast,
            len(selection.universe),
            allocation_slots=allocation_slots,
            portfolio_policy_id=selection.portfolio_policy_id,
        )
        engine = BacktestEngine(
            strategy=formula_strategy,
            instruments=instruments,
            data_handlers=handlers,
            initial_cash=initial_cash_override or Decimal(str(selection.initial_cash)),
            commission_calc=commission_calc,
            execution_config=research_execution_config(
                commission_calc,
                stream_sorted_data_handlers=bool(selection.deployment_scope),
            ),
            db=None,
            evaluation_start=date.fromisoformat(selection.end_date) + timedelta(days=1),
            warmup_final_bar_targets=True,
            cash_dividends=distributions,
            include_share_distributions=distributions is not None,
            strict_event_errors=bool(selection.deployment_scope),
        )
        formula_strategy.bind_portfolio_engine(
            engine,
            handlers,
            entry_board_policy=entry_board_policy,
            session_memberships=session_memberships,
            session_nontrading_instruments=session_nontrading_instruments,
            minimum_history_rows=(selection.deployment_scope or {})
            .get("universe_policy", {})
            .get("minimum_history_rows", 60),
        )
        result = engine.run()
        formula_strategy._prepared_sessions = None
        del engine
        result.dataset_snapshot = snapshot
        result.portfolio_observations = formula_strategy.session_books
        return result


def _bound_formula_portfolio_inputs(
    root: Path,
    snapshot: Mapping[str, Any],
    *,
    require_distributions: bool = False,
) -> tuple[
    Callable[[date], list[str]],
    Callable[[date], list[str]],
    tuple[StockDistribution, ...] | None,
]:
    """Replay the frozen Dataset's entry scope, status proof and distributions."""
    from data.dataset.model import DatasetRef
    from data.dataset.reader import (
        dataset_session_nontrading_instruments,
        read_daily_bar_dataset,
    )
    from data.storage.objects import ContentAddressedObjectStore

    objects = ContentAddressedObjectStore(root / "objects")
    restored = read_daily_bar_dataset(
        objects, DatasetRef(objects.resolve_ref(snapshot["immutable_dataset_id"]))
    )
    memberships = {
        item.partition_date: [key.symbol for key in item.instruments]
        for item in restored.snapshot.session_memberships
    }

    def session_memberships(day: date) -> list[str]:
        if not memberships:
            return [key.symbol for key in restored.snapshot.instruments]
        if day not in memberships:
            raise ValueError("dataset_session_membership_missing")
        return memberships[day]

    nontrading = dataset_session_nontrading_instruments(objects, restored.snapshot)
    distributions = (
        distributions_from_evidence(
            restored.corporate_action_evidence, include_shares=True
        )
        if restored.corporate_action_evidence is not None or require_distributions
        else None
    )
    return (
        session_memberships,
        lambda day: [key.symbol for key in nontrading.get(day, ())],
        distributions,
    )


def _run_cost_stress_scenarios(
    *,
    formula_ast: Mapping[str, Any],
    instruments: Mapping[Symbol, Any],
    handlers: Mapping[Symbol, DataHandler],
    selection: StrategyResearchSelection,
    allocation_slots: int,
    commission_calc: Any | None,
    entry_board_policy: Mapping[str, Any] | None,
    session_memberships: Callable[[date], list[str]] | None,
    session_nontrading_instruments: Callable[[date], list[str]] | None,
    distributions: tuple[StockDistribution, ...] | None,
) -> list[dict[str, Any]]:
    sensitivity: list[dict[str, Any]] = []
    for bps in RESEARCH_COST_STRESS_BPS:
        stress_strategy = _FormulaSignalStrategy(
            formula_ast,
            len(instruments),
            allocation_slots=allocation_slots,
            portfolio_policy_id=selection.portfolio_policy_id,
        )
        stressed_engine = BacktestEngine(
            strategy=stress_strategy,
            instruments=instruments,
            data_handlers=handlers,
            initial_cash=Decimal(str(selection.initial_cash)),
            execution_config=research_execution_config(
                commission_calc,
                slippage_bps=bps,
                stream_sorted_data_handlers=bool(selection.deployment_scope),
            ),
            cash_dividends=distributions,
            include_share_distributions=distributions is not None,
            strict_event_errors=bool(selection.deployment_scope),
        )
        stress_strategy.bind_portfolio_engine(
            stressed_engine,
            handlers,
            entry_board_policy=entry_board_policy,
            slippage_bps=Decimal(str(bps)),
            session_memberships=session_memberships,
            session_nontrading_instruments=session_nontrading_instruments,
            minimum_history_rows=(selection.deployment_scope or {})
            .get("universe_policy", {})
            .get("minimum_history_rows", 60),
        )
        stressed = stressed_engine.run()
        stress_strategy._prepared_sessions = None
        del stressed_engine, stress_strategy
        sensitivity.append(
            {
                **research_friction_assumptions(bps),
                "total_return": float(stressed.total_return),
                "max_drawdown": stressed.metrics.max_drawdown,
                "fill_count": len(stressed.fills),
            }
        )
    return sensitivity


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
    portfolio_policy_id: str | None = None,
    allocation_slots: int = 4,
    minimum_history_rows: int = 60,
    entry_board_policy: Mapping[str, Any] | None = None,
    session_memberships: Callable[[date], list[str]] | None = None,
    session_nontrading_instruments: Callable[[date], list[str]] | None = None,
    distributions: tuple[StockDistribution, ...] | None = None,
    strict_event_errors: bool = False,
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
            variant_strategy = _FormulaSignalStrategy(
                variant.formula_ast,
                len(instruments),
                allocation_slots=allocation_slots,
                portfolio_policy_id=portfolio_policy_id,
            )
            variant_engine = BacktestEngine(
                strategy=variant_strategy,
                instruments=instruments,
                data_handlers=handlers,
                initial_cash=initial_cash,
                commission_calc=commission_calc,
                execution_config=research_execution_config(
                    commission_calc,
                    stream_sorted_data_handlers=bool(portfolio_policy_id),
                ),
                db=None,
                cash_dividends=distributions,
                include_share_distributions=distributions is not None,
                strict_event_errors=strict_event_errors,
            )
            variant_strategy.bind_portfolio_engine(
                variant_engine,
                handlers,
                minimum_history_rows=minimum_history_rows,
                entry_board_policy=entry_board_policy,
                session_memberships=session_memberships,
                session_nontrading_instruments=session_nontrading_instruments,
            )
            variant_result = variant_engine.run()
            variant_strategy._prepared_sessions = None
            del variant_engine, variant_strategy
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
        "fee_schedule_reviewed_asset_classes",
    }
    expected_binding = {
        key: expected.get(key) for key in binding_keys if expected.get(key) is not None
    }
    # Older v1 reports omitted this provenance field. They remain readable for
    # critique; publication separately requires the full current review binding.
    if (
        persisted.get("schema_version") == BACKTEST_FEE_TAX_EVIDENCE_SCHEMA_VERSION
        and "fee_schedule_reviewed_asset_classes" not in persisted_binding
    ):
        expected_binding.pop("fee_schedule_reviewed_asset_classes", None)
    if (
        persisted.get("cost_model_reference") != selection.cost_model_reference
        or persisted.get("account_specific") is not True
        or persisted.get("broker_statement_reconciled") is not True
        or persisted.get("fee_schedule_fingerprint")
        != expected.get("fee_schedule_fingerprint")
        or persisted_binding != expected_binding
    ):
        raise StrategyResearchRejected("persisted_fee_schedule_binding_drift")


def build_dual_ma_research_strategy(
    params: Mapping[str, Any],
    universe_size: int,
    *,
    portfolio_policy_id: str | None = None,
) -> _FormulaSignalStrategy:
    """Run the fixed MA hypothesis under the candidate's exact execution policy."""

    def average(window: int) -> dict[str, Any]:
        field = {"op": "field", "name": "close"}
        return (
            field
            if window == 1
            else {"op": "rolling_mean", "input": field, "window": window}
        )

    short = average(int(params["short_period"]))
    long = average(int(params["long_period"]))
    return _FormulaSignalStrategy(
        {
            "schema_version": FORMULA_AST_CONTRACT,
            "entry": {"op": "cross", "left": short, "right": long},
            "exit": {"op": "lte", "left": short, "right": long},
            "position_size": {"op": "equal_weight"},
        },
        universe_size,
        strategy_id="dual_ma",
        portfolio_policy_id=portfolio_policy_id,
    )


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
    timezone = result["timestamp"].dt.tz
    start = pd.Timestamp(start_date, tz=timezone)
    end = (
        pd.Timestamp(end_date, tz=timezone)
        + pd.Timedelta(days=1)
        - pd.Timedelta(microseconds=1)
    )
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
    allow_extended_binding: bool = False,
    research_root: Path | None = None,
) -> tuple[dict[Symbol, DataHandler], dict[Symbol, Any], JsonObject]:
    effective_end = end_date or selection.end_date
    immutable_dataset_id = (expected_dataset_snapshot or {}).get("immutable_dataset_id")
    if immutable_dataset_id is not None:
        if effective_end > selection.end_date and not allow_extended_binding:
            raise StrategyResearchRejected(
                "sealed_immutable_dataset_extension_unsupported"
            )
        store_root = Path(getattr(data_store, "root", getattr(data_store, "_root", "")))
        research_root = (
            Path(research_root)
            if research_root is not None
            else store_root
            if (store_root / "objects").is_dir()
            else store_root / "research"
        )
        from analytics.dataset_snapshot import load_immutable_dataset_inputs

        try:
            instruments, handlers, binding = load_immutable_dataset_inputs(
                research_root, expected_dataset_snapshot
            )
        except StrategyResearchRejected:
            raise
        except ValueError as exc:
            reason = (
                str(exc)
                if str(exc)
                in ("immutable_dataset_id_missing", "immutable_dataset_unreadable")
                else "immutable_dataset_unreadable"
            )
            raise StrategyResearchRejected(reason) from exc
        except Exception as exc:
            raise StrategyResearchRejected("immutable_dataset_unreadable") from exc

        if effective_end != selection.end_date:
            sliced_handlers = {}
            for sym, handler in handlers.items():
                sliced_df = _slice_frame(
                    handler._df, selection.start_date, effective_end
                )
                if sliced_df.empty:
                    raise StrategyResearchRejected(f"persisted_window_empty:{sym}")
                sliced_handlers[sym] = DataHandler(
                    sliced_df,
                    sym,
                    BarFrequency.DAILY,
                    handler._asset_class,
                    handler._instrument_type,
                )
            handlers = sliced_handlers

        sources = binding.get("source_names") or []
        store_flag = (
            data_store
            if (expected_dataset_snapshot or {})
            .get("cache", {})
            .get("store_available", False)
            else None
        )
        snapshot = build_backtest_dataset_snapshot(
            start_date=(
                expected_dataset_snapshot["date_range"]["start"]
                if allow_extended_binding
                else selection.start_date
            ),
            end_date=(
                expected_dataset_snapshot["date_range"]["end"]
                if allow_extended_binding
                else effective_end
            ),
            configured_source=sources[0] if len(sources) == 1 else None,
            data_handlers=handlers,
            store=store_flag,
            source_names=sources,
            research_dataset_binding=binding,
        )
        if verify_snapshot and effective_end == selection.end_date:
            if snapshot.get("snapshot_id") != selection.dataset_snapshot_id:
                raise StrategyResearchRejected("dataset_snapshot_drift")
            replay = verify_backtest_dataset_snapshot_replay(
                expected_dataset_snapshot,
                store_root=store_root,
                research_root=research_root,
            )
            if replay is None or replay.get("status") != "pass":
                raise StrategyResearchRejected("dataset_snapshot_drift")
            snapshot = dict(expected_dataset_snapshot)
        if snapshot.get("data_quality", {}).get("status") != "ok":
            raise StrategyResearchRejected("dataset_quality_not_complete")
        return handlers, instruments, snapshot

    handlers: dict[Symbol, DataHandler] = {}
    instruments: dict[Symbol, Any] = {}
    market_binding = (expected_dataset_snapshot or {}).get("market_data_binding")
    frozen_frames = None
    if market_binding is not None:
        if effective_end > selection.end_date and not allow_extended_binding:
            raise StrategyResearchRejected(
                "research_snapshot_extension_requires_new_binding"
            )
        frozen_frames = load_research_market_frames(
            data_store._root,
            binding=market_binding,
            symbols=selection.universe,
            start_date=selection.start_date,
            end_date=effective_end,
        )
    for symbol_text, asset_class_text in zip(
        selection.universe, selection.asset_classes, strict=True
    ):
        symbol = Symbol(symbol_text)
        try:
            instrument_type = InstrumentType.from_persisted(asset_class_text)
            asset_class = (
                AssetClass.FUND
                if instrument_type in {InstrumentType.ETF, InstrumentType.OPEN_END_FUND}
                else AssetClass(instrument_type.value)
            )
        except ValueError as exc:
            raise StrategyResearchRejected("asset_class_invalid") from exc
        frame = (
            frozen_frames.get(symbol_text)
            if frozen_frames is not None
            else data_store.load_bars(
                symbol,
                BarFrequency.DAILY,
                instrument_type=instrument_type,
            )
        )
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
            instrument_type,
        )
        instruments[symbol] = DataManager.get_instrument_by_type(
            symbol,
            instrument_type,
        )
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
        market_data_binding=market_binding,
    )
    if verify_snapshot and snapshot.get("snapshot_id") != selection.dataset_snapshot_id:
        store_root = getattr(data_store, "root", getattr(data_store, "_root", ""))
        replay = (
            verify_backtest_dataset_snapshot_replay(
                expected_dataset_snapshot,
                store_root=store_root,
            )
            if expected_dataset_snapshot is not None
            and expected_dataset_snapshot.get("snapshot_id")
            == selection.dataset_snapshot_id
            and effective_end == selection.end_date
            else None
        )
        if replay is not None and replay.get("status") == "pass":
            snapshot = dict(expected_dataset_snapshot)
        else:
            raise StrategyResearchRejected("dataset_snapshot_drift")
    if snapshot.get("data_quality", {}).get("status") != "ok":
        raise StrategyResearchRejected("dataset_quality_not_complete")
    return handlers, instruments, snapshot
