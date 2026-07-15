from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from analytics.dataset_snapshot import build_backtest_dataset_snapshot
from core.types import AssetClass, BarFrequency, Symbol
from data.handler import DataHandler
from data.store import DataStore
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
        configured_source=None,
        data_handlers={symbol: handler},
        store=store,
        source_names=[],
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
        parameter_ranges={"window": [3, 5]},
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
        "parameter_ranges": {"window": [3, 5]},
    }

    result, request = RestrictedFormulaBacktestAdapter(data_store=store).run(
        selection=selection,
        draft=draft,
    )

    assert request.strategy == "ai_formula_research"
    assert result["metrics_json"]["formula_fingerprint"] == binding.fingerprint
    assert (
        result["metrics_json"]["dataset_snapshot"]["snapshot_id"]
        == snapshot["snapshot_id"]
    )
    assert result["metrics_json"]["research_only"] is True
    assert result["metrics_json"]["authority_effect"] == "none"
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
