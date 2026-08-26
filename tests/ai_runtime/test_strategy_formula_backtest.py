from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from analytics.dataset_snapshot import build_backtest_dataset_snapshot
from core.events import MarketEvent
from core.types import AssetClass, BarFrequency, CommissionType, Symbol
from data.handler import DataHandler
from data.store import DataStore
from execution.commission import MultiAssetCommission, StockACommission
from server.ai_runtime.formula_dsl import (
    CANONICAL_COST_MODEL_REFERENCE,
    FORMULA_AST_CONTRACT,
    FormulaBinding,
)
from server.ai_runtime.strategy_research import (
    RestrictedFormulaBacktestAdapter,
    StrategyResearchRejected,
    StrategyResearchSelection,
)


def _bars() -> pd.DataFrame:
    start = datetime(2025, 1, 2)
    closes = [10, 9, 8, 12, 13, 14, 7, 6]
    return pd.DataFrame(
        {
            "timestamp": [
                start + timedelta(days=index) for index in range(len(closes))
            ],
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
            "volume": [100_000] * len(closes),
        }
    )


def _formula() -> dict:
    average = {
        "op": "rolling_mean",
        "input": {"op": "field", "name": "close"},
        "window": 3,
    }
    return {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": {
            "op": "cross",
            "left": {"op": "field", "name": "close"},
            "right": average,
        },
        "exit": {
            "op": "lt",
            "left": {"op": "field", "name": "close"},
            "right": average,
        },
        "position_size": {"op": "equal_weight"},
    }


def test_strategy_selection_binds_or_compatibly_derives_account_truth_clock() -> None:
    bound = StrategyResearchSelection(
        saved_backtest_result_id=1,
        universe=("600000",),
        asset_classes=("stock",),
        dataset_snapshot_id="sha256:" + "a" * 64,
        start_date="2026-01-02",
        end_date="2026-08-21",
        frequency="1d",
        initial_cash=100_000,
        account_truth_freshness_as_of="2026-08-21T15:45:00+08:00",
    )
    assert bound.account_truth_freshness_datetime.isoformat() == (
        "2026-08-21T15:45:00+08:00"
    )
    assert bound.to_external_dict()["account_truth_freshness_as_of"] == (
        "2026-08-21T15:45:00+08:00"
    )

    legacy = StrategyResearchSelection(
        saved_backtest_result_id=1,
        universe=("600000",),
        asset_classes=("stock",),
        dataset_snapshot_id="sha256:" + "b" * 64,
        start_date="2026-01-02",
        end_date="2026-08-21",
        frequency="1d",
        initial_cash=100_000,
    )
    assert legacy.account_truth_freshness_datetime.isoformat() == (
        "2026-08-21T15:30:00+08:00"
    )
    assert "account_truth_freshness_as_of" not in legacy.to_dict()

    with pytest.raises(
        StrategyResearchRejected,
        match="account_truth_freshness_as_of_date_mismatch",
    ):
        StrategyResearchSelection(
            saved_backtest_result_id=1,
            universe=("600000",),
            asset_classes=("stock",),
            dataset_snapshot_id="sha256:" + "c" * 64,
            start_date="2026-01-02",
            end_date="2026-08-21",
            frequency="1d",
            initial_cash=100_000,
            account_truth_freshness_as_of="2026-08-22T15:30:00+08:00",
        )


def test_strategy_selection_sealed_holdout_is_hidden_from_external_view() -> None:
    sealed = StrategyResearchSelection(
        saved_backtest_result_id=1,
        universe=("600000",),
        asset_classes=("stock",),
        dataset_snapshot_id="sha256:" + "d" * 64,
        start_date="2026-01-02",
        end_date="2026-08-21",
        frequency="1d",
        initial_cash=100_000,
        sealed_end_date="2026-12-31",
    )
    assert sealed.has_sealed_holdout is True
    assert sealed.sealed_start_date == "2026-08-22"
    assert sealed.to_dict()["sealed_end_date"] == "2026-12-31"
    # The external (model-visible) selection must not leak the holdout boundary.
    assert "sealed_end_date" not in sealed.to_external_dict()
    assert sealed.to_external_dict()["end_date"] == "2026-08-21"

    plain = StrategyResearchSelection(
        saved_backtest_result_id=1,
        universe=("600000",),
        asset_classes=("stock",),
        dataset_snapshot_id="sha256:" + "e" * 64,
        start_date="2026-01-02",
        end_date="2026-08-21",
        frequency="1d",
        initial_cash=100_000,
    )
    assert plain.has_sealed_holdout is False
    assert plain.sealed_start_date is None
    assert "sealed_end_date" not in plain.to_dict()


def test_strategy_selection_rejects_invalid_sealed_holdout() -> None:
    with pytest.raises(StrategyResearchRejected, match="sealed_end_date_not_future"):
        StrategyResearchSelection(
            saved_backtest_result_id=1,
            universe=("600000",),
            asset_classes=("stock",),
            dataset_snapshot_id="sha256:" + "f" * 64,
            start_date="2026-01-02",
            end_date="2026-08-21",
            frequency="1d",
            initial_cash=100_000,
            sealed_end_date="2026-08-21",
        )
    with pytest.raises(StrategyResearchRejected, match="sealed_end_date_invalid"):
        StrategyResearchSelection(
            saved_backtest_result_id=1,
            universe=("600000",),
            asset_classes=("stock",),
            dataset_snapshot_id="sha256:" + "0" * 64,
            start_date="2026-01-02",
            end_date="2026-08-21",
            frequency="1d",
            initial_cash=100_000,
            sealed_end_date="not-a-date",
        )


def test_restricted_formula_adapter_uses_canonical_after_cost_engine_without_db_sink(
    tmp_path,
) -> None:
    store = DataStore(tmp_path / "market")
    symbol = Symbol("600000")
    bars = _bars()
    store.save_bars(
        symbol,
        BarFrequency.DAILY,
        bars,
        provider_name="deterministic_fixture",
        data_source="deterministic_fixture",
        adjustment_mode="none",
    )
    handler = DataHandler(bars, symbol, BarFrequency.DAILY, AssetClass.STOCK)
    snapshot = build_backtest_dataset_snapshot(
        start_date="2025-01-02",
        end_date="2025-01-09",
        configured_source="deterministic_fixture",
        data_handlers={symbol: handler},
        store=store,
        source_names=["akshare", "deterministic_fixture"],
    )
    selection = StrategyResearchSelection(
        saved_backtest_result_id=1,
        universe=("600000",),
        asset_classes=("stock",),
        dataset_snapshot_id=snapshot["snapshot_id"],
        start_date="2025-01-02",
        end_date="2025-01-09",
        frequency="1d",
        initial_cash=100_000,
    )
    assumptions = (
        "Signals use completed daily bars and never use a future timestamp.",
    )
    binding = FormulaBinding(
        formula_ast=_formula(),
        universe=selection.universe,
        dataset_snapshot_id=selection.dataset_snapshot_id,
        start_date=selection.start_date,
        end_date=selection.end_date,
        frequency=selection.frequency,
        cost_model_reference=CANONICAL_COST_MODEL_REFERENCE,
        anti_lookahead_assumptions=assumptions,
        parameter_values={"window": 3},
        parameter_ranges={"window": [2, 3, 5]},
        initial_cash=selection.initial_cash,
    )
    draft = {
        "draft_id": "fixture-draft",
        "formula_ast": _formula(),
        "formula_fingerprint": binding.fingerprint,
        "selected_universe": list(selection.universe),
        "dataset_snapshot_id": selection.dataset_snapshot_id,
        "test_window": {
            "start_date": selection.start_date,
            "end_date": selection.end_date,
        },
        "frequency": selection.frequency,
        "cost_model_reference": selection.cost_model_reference,
        "anti_lookahead_assumptions": list(assumptions),
        "parameter_values": {"window": 3},
        "parameter_ranges": {"window": [2, 3, 5]},
    }

    result, request = RestrictedFormulaBacktestAdapter(data_store=store).run(
        selection=selection,
        draft=draft,
        expected_dataset_snapshot=snapshot,
    )

    assert request.strategy == "ai_formula_research"
    assert result["metrics_json"]["formula_fingerprint"] == binding.fingerprint
    assert (
        result["metrics_json"]["dataset_snapshot"]["snapshot_id"]
        == snapshot["snapshot_id"]
    )
    assert result["metrics_json"]["research_only"] is True
    assert result["metrics_json"]["authority_effect"] == "none"
    assert result["metrics_json"]["oos_validation"]["validation_mode"] == "rolling"
    assert result["metrics_json"]["oos_validation"]["fold_count"] >= 1
    fee_evidence = result["metrics_json"]["fee_component_evidence"]
    assert fee_evidence["status"] == "complete"
    assert fee_evidence["includes_taxes"] is True
    assert fee_evidence["fill_count"] == len(result["fills"])
    assert fee_evidence["components"]["commission"]
    assert fee_evidence["components"]["stamp_tax"]
    assert fee_evidence["components"]["transfer_fee"]
    assert fee_evidence["components"]["slippage"]
    assert len(fee_evidence["evidence_fingerprint"]) == 64
    capacity = result["metrics_json"]["capacity_review"]
    assert capacity["status"] == "pass"
    assert capacity["observation_count"] == len(result["fills"])
    assert (
        float(capacity["gross_turnover"])
        == result["cost_summary_json"]["gross_turnover"]
    )
    assert len(capacity["evidence_fingerprint"]) == 64
    assert capacity["authorizes_execution"] is False
    drawdown = result["metrics_json"]["drawdown_evidence"]
    assert drawdown["status"] == "complete"
    assert drawdown["point_count"] == len(result["equity_curve"])
    assert float(drawdown["max_drawdown_pct"]) == result["max_drawdown"]
    assert len(drawdown["evidence_fingerprint"]) == 64
    parameter = result["metrics_json"]["parameter_robustness"]
    assert parameter["tested_count"] == 3
    assert parameter["selected_params"] == {"window": 3}
    assert len(parameter["evidence_fingerprint"]) == 64
    assert result["metrics_json"]["parameter_sweep_failure_code"] is None
    regimes = result["metrics_json"]["market_regime_robustness"]
    assert regimes["schema_version"] == "karkinos.market_regime_robustness.v2"
    assert len(regimes["evidence_fingerprint"]) == 64
    assert regimes["authorizes_execution"] is False
    assert request.oos_mode == "rolling"
    assert result["cost_summary_json"]["total_trades"] == len(result["fills"])
    assert result["metrics_json"]["research_evidence_bundle"]["schema_version"]
    assert result["fills"]
    assert result["fills"][0]["timestamp"].startswith("2025-01-06")

    adapter = RestrictedFormulaBacktestAdapter(data_store=store)
    for changed_field, changed_value in (
        ("selected_universe", ["000001"]),
        ("dataset_snapshot_id", "sha256:drifted"),
        ("test_window", {"start_date": "2025-01-03", "end_date": "2025-01-09"}),
        ("frequency", "1m"),
        ("cost_model_reference", "ai-selected-cost"),
    ):
        with pytest.raises(StrategyResearchRejected, match="draft_binding_drift"):
            adapter.run(
                selection=selection,
                draft={**draft, changed_field: changed_value},
            )

    drifted_formula = _formula()
    drifted_formula["entry"] = {
        "op": "gt",
        "left": {"op": "field", "name": "close"},
        "right": {"op": "constant", "value": 999},
    }
    with pytest.raises(StrategyResearchRejected, match="formula_binding_drift"):
        adapter.run(
            selection=selection,
            draft={**draft, "formula_ast": drifted_formula},
        )


def test_restricted_formula_adapter_calculates_with_exact_reviewed_fee_binding(
    tmp_path,
) -> None:
    store = DataStore(tmp_path / "market")
    symbol = Symbol("600000")
    bars = _bars()
    store.save_bars(
        symbol,
        BarFrequency.DAILY,
        bars,
        provider_name="deterministic_fixture",
        data_source="deterministic_fixture",
        adjustment_mode="none",
    )
    snapshot = build_backtest_dataset_snapshot(
        start_date="2025-01-02",
        end_date="2025-01-09",
        configured_source="deterministic_fixture",
        data_handlers={
            symbol: DataHandler(bars, symbol, BarFrequency.DAILY, AssetClass.STOCK)
        },
        store=store,
        source_names=["deterministic_fixture"],
    )
    review_id = "fee_review_" + "a" * 32
    review_fingerprint = "sha256:" + "b" * 64
    cost_model_reference = (
        "karkinos.backtest.reviewed_account_fee_schedule.v1:"
        f"{review_id}:{review_fingerprint.removeprefix('sha256:')}"
    )
    selection = StrategyResearchSelection(
        saved_backtest_result_id=1,
        universe=(str(symbol),),
        asset_classes=("stock",),
        dataset_snapshot_id=snapshot["snapshot_id"],
        start_date="2025-01-02",
        end_date="2025-01-09",
        frequency="1d",
        initial_cash=100_000,
        cost_model_reference=cost_model_reference,
    )
    assumptions = (
        "Signals use completed daily bars and never use a future timestamp.",
    )
    binding = FormulaBinding(
        formula_ast=_formula(),
        universe=selection.universe,
        dataset_snapshot_id=selection.dataset_snapshot_id,
        start_date=selection.start_date,
        end_date=selection.end_date,
        frequency=selection.frequency,
        cost_model_reference=cost_model_reference,
        anti_lookahead_assumptions=assumptions,
        parameter_values={"window": 3},
        parameter_ranges={"window": [2, 3, 5]},
        initial_cash=selection.initial_cash,
    )
    draft = {
        "draft_id": "reviewed-fee-draft",
        "formula_ast": _formula(),
        "formula_fingerprint": binding.fingerprint,
        "selected_universe": list(selection.universe),
        "dataset_snapshot_id": selection.dataset_snapshot_id,
        "test_window": {
            "start_date": selection.start_date,
            "end_date": selection.end_date,
        },
        "frequency": selection.frequency,
        "cost_model_reference": cost_model_reference,
        "anti_lookahead_assumptions": list(assumptions),
        "parameter_values": {"window": 3},
        "parameter_ranges": {"window": [2, 3, 5]},
    }
    calculator = MultiAssetCommission(fee_rule_version=cost_model_reference)
    calculator.set_commission(
        CommissionType.STOCK_A,
        StockACommission(
            commission_rate=Decimal("0.01"),
            min_commission=Decimal("0"),
            fee_rule_id="reviewed-account-fee-rule",
        ),
    )
    fee_schedule_binding = {
        "fee_schedule_review_id": review_id,
        "fee_schedule_review_fingerprint": review_fingerprint,
        "fee_schedule_preview_fingerprint": "sha256:" + "c" * 64,
        "account_truth_import_run_id": "import_fixture",
        "account_truth_source_fingerprint": "sha256:" + "d" * 64,
        "account_truth_scope_fingerprint": "sha256:" + "e" * 64,
        "effective_start_date": "2025-01-01",
        "effective_end_date": "2025-12-31",
        "fee_notional_envelope_enforced": True,
        "fee_notional_envelope_fingerprint": "sha256:" + "9" * 64,
        "fee_notional_covered_asset_classes": ["stock"],
    }
    resolution = SimpleNamespace(
        cost_model_reference=cost_model_reference,
        commission_calc=calculator,
        fee_evidence={
            "account_specific": True,
            "fee_schedule_source": (
                "reviewed_account_truth_or_reconciled_fee_schedule"
            ),
            "fee_schedule_fingerprint": "sha256:" + "f" * 64,
            "broker_statement_reconciled": True,
            **fee_schedule_binding,
        },
    )

    result, _ = RestrictedFormulaBacktestAdapter(data_store=store).run(
        selection=selection,
        draft=draft,
        expected_dataset_snapshot=snapshot,
        reviewed_fee_schedule_resolution=resolution,
    )

    assert result["fills"]
    assert all(
        fill["fee_rule_version"] == cost_model_reference for fill in result["fills"]
    )
    fee_evidence = result["metrics_json"]["fee_component_evidence"]
    assert fee_evidence["account_specific"] is True
    assert fee_evidence["fee_rule_version"] == cost_model_reference
    assert fee_evidence["fee_schedule_binding"] == fee_schedule_binding


def test_formula_signal_strategy_blocks_limit_up_and_suspension() -> None:
    from server.ai_runtime.strategy_research_backtest import _FormulaSignalStrategy

    strategy = _FormulaSignalStrategy(_formula(), universe_size=1, allocation_slots=1)
    symbol = Symbol("600000")
    strategy.on_init([symbol])
    strategy._frames[symbol] = [
        {
            "timestamp": datetime(2025, 1, 2),
            "open": 10.0,
            "high": 10.0,
            "low": 10.0,
            "close": 10.0,
            "volume": 100_000.0,
        }
    ]

    limit_up = MarketEvent(
        timestamp=datetime(2025, 1, 3),
        symbol=symbol,
        open=Decimal("11.0"),
        high=Decimal("11.0"),
        low=Decimal("11.0"),
        close=Decimal("11.0"),
        volume=Decimal("100000"),
    )
    assert strategy._is_tradeable(limit_up, target=1.0) is False
    assert strategy._limit_blocked_count == 1

    suspended = MarketEvent(
        timestamp=datetime(2025, 1, 3),
        symbol=symbol,
        open=Decimal("10.0"),
        high=Decimal("10.0"),
        low=Decimal("10.0"),
        close=Decimal("10.0"),
        volume=Decimal("0"),
    )
    assert strategy._is_tradeable(suspended, target=1.0) is False
    assert strategy._suspension_blocked_count == 1

    normal = MarketEvent(
        timestamp=datetime(2025, 1, 3),
        symbol=symbol,
        open=Decimal("10.5"),
        high=Decimal("10.5"),
        low=Decimal("10.5"),
        close=Decimal("10.5"),
        volume=Decimal("100000"),
    )
    assert strategy._is_tradeable(normal, target=1.0) is True


def test_restricted_formula_adapter_run_sealed_reaches_future_window(tmp_path) -> None:
    store = DataStore(tmp_path / "market")
    symbol = Symbol("600000")
    start = datetime(2025, 1, 2)
    closes = [10, 9, 8, 12, 13, 14, 7, 6, 11, 12, 13, 14, 15, 16, 17]
    bars = pd.DataFrame(
        {
            "timestamp": [
                start + timedelta(days=index) for index in range(len(closes))
            ],
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
            "volume": [100_000] * len(closes),
        }
    )
    store.save_bars(
        symbol,
        BarFrequency.DAILY,
        bars,
        provider_name="deterministic_fixture",
        data_source="deterministic_fixture",
        adjustment_mode="none",
    )
    selection = StrategyResearchSelection(
        saved_backtest_result_id=1,
        universe=("600000",),
        asset_classes=("stock",),
        dataset_snapshot_id="sha256:" + "a" * 64,
        start_date="2025-01-02",
        end_date="2025-01-09",
        frequency="1d",
        initial_cash=100_000,
        sealed_end_date="2025-01-16",
    )
    result = RestrictedFormulaBacktestAdapter(data_store=store).run_sealed(
        selection=selection,
        draft={"formula_ast": _formula()},
        sealed_end_date="2025-01-16",
    )
    sealed_boundary = datetime(2025, 1, 10)
    assert result.equity_curve[-1][0].date() >= sealed_boundary.date()
    sealed_bars = [
        ts for ts, _ in result.equity_curve if ts.date() >= sealed_boundary.date()
    ]
    assert sealed_bars
