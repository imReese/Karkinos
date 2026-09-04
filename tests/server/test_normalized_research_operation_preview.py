"""Normalized Formula operation previews never cross into trading authority."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

import pandas as pd
import pytest

from analytics.dataset_snapshot import build_backtest_dataset_snapshot
from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from data.handler import DataHandler
from data.store import DataStore
from server.ai_runtime.formula_dsl import (
    CANONICAL_COST_MODEL_REFERENCE,
    FormulaBinding,
)
from server.ai_runtime.strategy_research import (
    RestrictedFormulaBacktestAdapter,
    StrategyResearchSelection,
)
from server.contracts.content_identity import content_fingerprint
from server.projections.normalized_research_operation_preview import (
    bind_research_winner_operation_preview,
    build_normalized_research_operation_preview,
    is_valid_research_operation_recommendation,
    project_normalized_research_operation_preview,
)


def _formula() -> dict:
    close = {"op": "field", "name": "close"}
    return {
        "schema_version": "karkinos.ai.formula_ast.v1",
        "entry": {
            "op": "gt",
            "left": close,
            "right": {"op": "constant", "value": 10},
        },
        "exit": {
            "op": "lt",
            "left": close,
            "right": {"op": "constant", "value": 9},
        },
        "position_size": {"op": "equal_weight"},
    }


def _frame(close: float, *, date: str = "2026-08-28") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [date],
            "open": [close],
            "high": [close],
            "low": [close],
            "close": [close],
            "volume": [100_000],
        }
    )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_final_frozen_bar_preview_prioritizes_exits_and_bounds_buys() -> None:
    preview = build_normalized_research_operation_preview(
        formula_ast=_formula(),
        frames={
            "600004": _frame(14),
            "600003": _frame(13),
            "600002": _frame(12),
            "600001": _frame(8),
        },
        dataset_snapshot_id="sha256:" + "d" * 64,
        formula_fingerprint="sha256:" + "f" * 64,
        research_window_end_date="2026-08-28",
        allocation_slots=2,
    )

    assert preview["status"] == "available"
    assert [item["operation"] for item in preview["operations"]] == [
        "exit_if_held_candidate",
        "buy_candidate",
        "buy_candidate",
    ]
    assert [item["symbol"] for item in preview["operations"]] == [
        "600001",
        "600002",
        "600003",
    ]
    assert preview["selected_buy_candidate_count"] == 2
    assert preview["omitted_buy_candidate_count"] == 1
    exit_candidate = preview["operations"][0]
    assert exit_candidate["account_position_status"] == "not_evaluated"
    assert exit_candidate["executable"] is False
    assert "sell" not in str(preview).lower()
    assert "quantity" not in str(preview).lower()
    assert project_normalized_research_operation_preview(preview) == preview
    assert (
        project_normalized_research_operation_preview(
            {**preview, "account_cash": 123_456}
        )
        is None
    )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_stale_final_bar_fails_closed_without_operation_candidates() -> None:
    preview = build_normalized_research_operation_preview(
        formula_ast=_formula(),
        frames={"600001": _frame(12, date="2026-08-27")},
        dataset_snapshot_id="sha256:" + "d" * 64,
        formula_fingerprint="sha256:" + "f" * 64,
        research_window_end_date="2026-08-28",
        allocation_slots=1,
    )

    assert preview["status"] == "unavailable"
    assert preview["operations"] == []
    assert preview["blockers"] == ["frozen_bar_end_date_mismatch:600001"]


@pytest.mark.unit
@pytest.mark.trading_safety
def test_winner_binding_rejects_tampered_preview() -> None:
    preview = build_normalized_research_operation_preview(
        formula_ast=_formula(),
        frames={"600001": _frame(12)},
        dataset_snapshot_id="sha256:" + "d" * 64,
        formula_fingerprint="sha256:" + "f" * 64,
        research_window_end_date="2026-08-28",
        allocation_slots=1,
    )
    recommendation = bind_research_winner_operation_preview(
        preview=preview,
        candidate_id="candidate-1",
        run_id="run-1",
        market_date="2026-08-28",
    )

    assert recommendation["status"] == "available"
    assert recommendation["research_winner_candidate_id"] == "candidate-1"
    assert is_valid_research_operation_recommendation(recommendation)

    tampered = deepcopy(recommendation)
    tampered["operations"][0]["executable"] = True
    core = dict(tampered)
    core.pop("evidence_fingerprint")
    tampered["evidence_fingerprint"] = content_fingerprint(core)
    assert is_valid_research_operation_recommendation(tampered) is False


@pytest.mark.unit
@pytest.mark.trading_safety
def test_restricted_formula_backtest_persists_preview_in_canonical_metrics(
    tmp_path,
) -> None:
    store = DataStore(tmp_path / "market")
    symbol = Symbol("600001")
    start = datetime(2026, 8, 21)
    bars = pd.DataFrame(
        {
            "timestamp": [start + timedelta(days=index) for index in range(8)],
            "open": [8, 9, 10, 11, 12, 11, 10, 12],
            "high": [9, 10, 11, 12, 13, 12, 11, 13],
            "low": [7, 8, 9, 10, 11, 10, 9, 11],
            "close": [8, 9, 10, 11, 12, 11, 10, 12],
            "volume": [1_000_000] * 8,
        }
    )
    store.save_bars(
        symbol,
        BarFrequency.DAILY,
        bars,
        provider_name="deterministic_fixture",
        data_source="deterministic_fixture",
        adjustment_mode="none",
        instrument_type=InstrumentType.STOCK,
    )
    handler = DataHandler(
        bars,
        symbol,
        BarFrequency.DAILY,
        AssetClass.STOCK,
        InstrumentType.STOCK,
    )
    snapshot = build_backtest_dataset_snapshot(
        start_date="2026-08-21",
        end_date="2026-08-28",
        configured_source="deterministic_fixture",
        data_handlers={symbol: handler},
        store=store,
        source_names=["deterministic_fixture"],
    )
    selection = StrategyResearchSelection(
        saved_backtest_result_id=1,
        universe=(str(symbol),),
        asset_classes=("stock",),
        dataset_snapshot_id=snapshot["snapshot_id"],
        start_date="2026-08-21",
        end_date="2026-08-28",
        frequency="1d",
        initial_cash=1_000_000,
    )
    binding = FormulaBinding(
        formula_ast=_formula(),
        universe=selection.universe,
        dataset_snapshot_id=selection.dataset_snapshot_id,
        start_date=selection.start_date,
        end_date=selection.end_date,
        frequency=selection.frequency,
        cost_model_reference=CANONICAL_COST_MODEL_REFERENCE,
        anti_lookahead_assumptions=("Signals use completed daily bars.",),
        parameter_values={},
        parameter_ranges={},
        initial_cash=selection.initial_cash,
    )
    draft = {
        "draft_id": "draft-preview",
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
        "anti_lookahead_assumptions": ["Signals use completed daily bars."],
        "parameter_values": {},
        "parameter_ranges": {},
    }

    result, _ = RestrictedFormulaBacktestAdapter(data_store=store).run(
        selection=selection,
        draft=draft,
        expected_dataset_snapshot=snapshot,
    )

    persisted_preview = result["metrics_json"]["normalized_research_operation_preview"]
    assert persisted_preview["status"] == "available"
    assert persisted_preview["operations"][0]["operation"] == "buy_candidate"
    assert persisted_preview["operations"][0]["target_weight"] == 1.0
    assert project_normalized_research_operation_preview(persisted_preview) == (
        persisted_preview
    )
