from __future__ import annotations

import pandas as pd
import pytest

from server.ai_runtime.formula_dsl import (
    FORMULA_AST_CONTRACT,
    FormulaValidationError,
    evaluate_formula,
)
from server.ai_runtime.formula_portfolio import prepare_formula_sessions
from server.projections.normalized_research_operation_preview import (
    build_normalized_research_operation_preview,
)
from server.services.strategy_scan.universe.evaluation import evaluate_strategy_signals


def _build_test_frames(
    market_date: str = "2025-01-05",
) -> dict[str, pd.DataFrame]:
    """Build 3 stocks with closes 10, 20, 30 on market_date with prior history."""
    dates = [
        "2025-01-01",
        "2025-01-02",
        "2025-01-03",
        "2025-01-04",
        market_date,
    ]
    prices = {
        "000001": [8.0, 9.0, 9.5, 9.8, 10.0],
        "000002": [16.0, 17.0, 18.0, 19.0, 20.0],
        "000003": [24.0, 26.0, 27.0, 28.5, 30.0],
    }
    frames = {}
    for sym, p_list in prices.items():
        frames[sym] = pd.DataFrame(
            {
                "timestamp": [f"{d}T15:00:00" for d in dates],
                "open": p_list,
                "high": [p * 1.02 for p in p_list],
                "low": [p * 0.98 for p in p_list],
                "close": p_list,
                "volume": [100000.0] * len(dates),
                "amount": [p * 100000.0 for p in p_list],
            }
        )
    return frames


def _make_formula(entry_op: dict) -> dict:
    return {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": entry_op,
        "exit": {"op": "constant", "value": 0},
        "position_size": {
            "op": "max_weight",
            "input": {"op": "equal_weight"},
            "value": 0.33,
        },
    }


def test_cross_sectional_rank_parity_across_entrypoints() -> None:
    """cs_rank(close) > 0.8 must select only stock 3 across backtest, scan, and preview."""
    frames = _build_test_frames("2025-01-05")
    formula = _make_formula(
        {
            "op": "gt",
            "left": {
                "op": "cs_rank",
                "input": {"op": "field", "name": "close"},
            },
            "right": {"op": "constant", "value": 0.8},
        }
    )

    # 1. Backtest / Session Targets entrypoint
    prepared = prepare_formula_sessions(formula, frames, universe_size=3)
    date_val = pd.Timestamp("2025-01-05").date()
    assert bool(prepared["000003"].loc[date_val, "entry"]) is True
    assert bool(prepared["000002"].loc[date_val, "entry"]) is False
    assert bool(prepared["000001"].loc[date_val, "entry"]) is False

    # 2. Recommendation scan entrypoint
    signals = evaluate_strategy_signals(
        strategy_id="test_cs_strat",
        formula_ast=formula,
        universe_size=3,
        target_weight=0.33,
        frames=frames,
        eligible_symbols=["000001", "000002", "000003"],
        maintenance_symbols=[],
        held_symbols=set(),
        market_date="2025-01-05",
    )
    buy_symbols = [s["symbol"] for s in signals if s["direction"] == "buy"]
    assert buy_symbols == ["000003"], (
        f"Expected only 000003 to be bought, got {buy_symbols}"
    )

    # 3. Research Operation Preview entrypoint
    preview = build_normalized_research_operation_preview(
        frames=frames,
        formula_ast=formula,
        dataset_snapshot_id="sha256:test",
        formula_fingerprint="sha256:fp",
        research_window_end_date="2025-01-05",
        allocation_slots=3,
    )
    preview_buys = [
        op["symbol"] for op in preview["operations"] if op["signal_type"] == "entry"
    ]
    assert preview_buys == ["000003"], (
        f"Expected only 000003 in preview, got {preview_buys}"
    )


def test_cross_sectional_zscore_parity_across_entrypoints() -> None:
    """cs_zscore(close) > 0.5 must select only stock 3 across backtest, scan, and preview."""
    frames = _build_test_frames("2025-01-05")
    formula = _make_formula(
        {
            "op": "gt",
            "left": {
                "op": "cs_zscore",
                "input": {"op": "field", "name": "close"},
            },
            "right": {"op": "constant", "value": 0.5},
        }
    )

    # 1. Backtest entrypoint
    prepared = prepare_formula_sessions(formula, frames, universe_size=3)
    date_val = pd.Timestamp("2025-01-05").date()
    assert bool(prepared["000003"].loc[date_val, "entry"]) is True
    assert bool(prepared["000002"].loc[date_val, "entry"]) is False
    assert bool(prepared["000001"].loc[date_val, "entry"]) is False

    # 2. Recommendation scan entrypoint
    signals = evaluate_strategy_signals(
        strategy_id="test_cs_strat",
        formula_ast=formula,
        universe_size=3,
        target_weight=0.33,
        frames=frames,
        eligible_symbols=["000001", "000002", "000003"],
        maintenance_symbols=[],
        held_symbols=set(),
        market_date="2025-01-05",
    )
    buy_symbols = [s["symbol"] for s in signals if s["direction"] == "buy"]
    assert buy_symbols == ["000003"], (
        f"Expected only 000003 to be bought, got {buy_symbols}"
    )

    # 3. Preview entrypoint
    preview = build_normalized_research_operation_preview(
        frames=frames,
        formula_ast=formula,
        dataset_snapshot_id="sha256:test",
        formula_fingerprint="sha256:fp",
        research_window_end_date="2025-01-05",
        allocation_slots=3,
    )
    preview_buys = [
        op["symbol"] for op in preview["operations"] if op["signal_type"] == "entry"
    ]
    assert preview_buys == ["000003"], (
        f"Expected only 000003 in preview, got {preview_buys}"
    )


def test_multi_symbol_formula_without_context_raises_error() -> None:
    """When universe_size > 1 and cross_sectional_frames is missing, reject fail-closed."""
    frames = _build_test_frames("2025-01-05")
    formula = _make_formula(
        {
            "op": "gt",
            "left": {
                "op": "cs_rank",
                "input": {"op": "field", "name": "close"},
            },
            "right": {"op": "constant", "value": 0.8},
        }
    )

    with pytest.raises(FormulaValidationError) as exc_info:
        evaluate_formula(formula, frames["000001"], universe_size=3)
    assert exc_info.value.code == "cross_sectional_context_required"


def test_ineligible_symbol_does_not_distort_ranking_denominator() -> None:
    """Removing an ineligible symbol must NOT change ranking denominator of eligible ones."""
    frames = _build_test_frames("2025-01-05")
    formula = _make_formula(
        {
            "op": "gt",
            "left": {
                "op": "cs_rank",
                "input": {"op": "field", "name": "close"},
            },
            "right": {"op": "constant", "value": 0.8},
        }
    )

    # 000003 has rank 1.0, but is NOT eligible to buy (e.g. limit-up).
    # 000002 has rank 0.67 < 0.8.
    # If 000003 were removed before rank calculation, 000002 would wrongly get rank 1.0!
    signals = evaluate_strategy_signals(
        strategy_id="test_cs_strat",
        formula_ast=formula,
        universe_size=3,
        target_weight=0.33,
        frames=frames,
        eligible_symbols=["000001", "000002"],  # 000003 not eligible
        maintenance_symbols=[],
        held_symbols=set(),
        market_date="2025-01-05",
    )
    buy_symbols = [s["symbol"] for s in signals if s["direction"] == "buy"]
    assert buy_symbols == [], (
        f"Expected no buys because 000002 rank is 0.67, got {buy_symbols}"
    )
