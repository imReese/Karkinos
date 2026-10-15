"""One session uses real holdings and only the explicitly eligible price history."""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from core.types import Symbol
from domain.instrument import make_stock
from server.ai_runtime.formula_portfolio import (
    formula_session_targets,
    prepare_formula_sessions,
)

pytestmark = pytest.mark.unit


def frame(days, *, volume=100000):
    return pd.DataFrame(
        {"timestamp": pd.to_datetime(days), "close": 10, "volume": volume}
    )


def prepared(frames):
    from server.ai_runtime.formula_dsl import FORMULA_AST_CONTRACT

    field = {"op": "field", "name": "close"}
    return prepare_formula_sessions(
        {
            "schema_version": FORMULA_AST_CONTRACT,
            "entry": {
                "op": "gt",
                "left": field,
                "right": {"op": "constant", "value": 0},
            },
            "exit": {
                "op": "lt",
                "left": field,
                "right": {"op": "constant", "value": 0},
            },
            "position_size": {
                "op": "max_weight",
                "input": {"op": "equal_weight"},
                "value": 0.25,
            },
        },
        frames,
        universe_size=len(frames),
    )


def decide(data, **changes):
    return formula_session_targets(
        prepared=data,
        decision_session=date(2026, 9, 18),
        quantities={},
        cash=Decimal("10000"),
        equity=Decimal("10000"),
        instruments={Symbol(s): make_stock(s, s) for s in data},
        minimum_history_rows=2,
        **changes,
    )


def test_scope_history_and_suspension_gate_entries_without_inventing_positions():
    data = prepared(
        {
            "600000": frame(["2026-09-17", "2026-09-18"]),
            "600001": frame(["2026-09-18"]),
            "600002": frame(["2026-09-17", "2026-09-18"], volume=0),
            "600003": frame(["2026-09-17", "2026-09-18"]),
        }
    )
    result = decide(data, eligible_symbols=["600000", "600001", "600002"])
    assert result["selected_entries"] == ["600000"]
    assert set(result["target_weights"]) == {"600000"}
    assert result["target_weights"]["600000"] == Decimal("0.2")


def test_missing_today_held_is_carried_at_last_known_price_and_consumes_slot():
    data = prepared(
        {"600000": frame(["2026-09-17"]), "600001": frame(["2026-09-17", "2026-09-18"])}
    )
    result = formula_session_targets(
        prepared=data,
        decision_session=date(2026, 9, 18),
        quantities={"600000": Decimal(100)},
        cash=Decimal(9000),
        equity=Decimal(10000),
        instruments={Symbol(s): make_stock(s, s) for s in data},
        eligible_symbols=["600001"],
        minimum_history_rows=2,
        max_positions=1,
    )
    assert result["target_weights"] == {"600000": Decimal("0.1")}
    assert result["rejected_entries"] == {"600001": "position_limit"}
    assert result["forecasts"][0]["data_available"] is False
    assert result["forecasts"][0]["observation_session"] == "2026-09-17"
    with pytest.raises(ValueError, match="formula_session_observation_missing"):
        formula_session_targets(
            prepared={},
            decision_session=date(2026, 9, 18),
            quantities={"600000": Decimal(100)},
            cash=Decimal(0),
            equity=Decimal(1000),
            instruments={},
        )


def test_account_entry_mask_preserves_full_forecasts_and_allows_maintenance_exit():
    from server.services.account_board_permissions import freeze_entry_board_policy

    symbols = ["600000", "300001", "688001", "920001"]
    data = prepared({s: frame(["2026-09-17", "2026-09-18"]) for s in symbols})
    mask = freeze_entry_board_policy(None, "2026-09-18")
    result = decide(data, eligible_symbols=symbols, entry_board_policy=mask)
    assert result["selected_entries"] == ["600000"]
    assert {row["symbol"] for row in result["forecasts"]} == set(symbols)
    assert {row["action"] for row in result["forecasts"]} == {"enter"}
    assert result["rejected_entries"] == {
        s: "frozen_entry_board_policy" for s in symbols[1:]
    }
    data["688001"].loc[:, "exit"] = True
    exited = formula_session_targets(
        prepared=data,
        decision_session=date(2026, 9, 18),
        quantities={"688001": Decimal(200)},
        cash=Decimal(8000),
        equity=Decimal(10000),
        instruments={Symbol(s): make_stock(s, s) for s in symbols},
        minimum_history_rows=2,
        entry_board_policy=mask,
    )
    assert exited["exit_symbols"] == ["688001"]
    assert exited["target_weights"]["688001"] == 0
