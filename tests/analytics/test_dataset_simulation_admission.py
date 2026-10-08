"""Verified exploratory inputs can support simulation without account admission."""

from copy import deepcopy

import pandas as pd

from analytics.dataset_snapshot import (
    backtest_dataset_snapshot_content_id,
    build_backtest_dataset_snapshot,
    dataset_simulation_admission,
)
from analytics.normalized_research_gate import (
    build_normalized_research_advancement_gate,
)
from analytics.strategy_advancement_gate import build_strategy_advancement_gate
from backtest.costs import research_friction_assumptions
from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from data.handler import DataHandler
from tests.analytics.test_strategy_advancement_gate import _view


def _snapshot():
    symbol = Symbol("600000")
    frame = pd.DataFrame(
        {
            "timestamp": pd.bdate_range("2026-01-05", periods=3),
            "open": [10, 11, 12],
            "high": [10, 11, 12],
            "low": [10, 11, 12],
            "close": [10, 11, 12],
            "volume": [100000] * 3,
        }
    )
    snapshot = build_backtest_dataset_snapshot(
        start_date="2026-01-05",
        end_date="2026-01-07",
        configured_source="fixture",
        data_handlers={
            symbol: DataHandler(
                frame,
                symbol,
                BarFrequency.DAILY,
                AssetClass.STOCK,
                InstrumentType.STOCK,
            )
        },
        store=None,
        source_names=["fixture"],
    )
    snapshot.pop("snapshot_id")
    snapshot.update(
        research_use="exploratory_backtest",
        point_in_time_verified=False,
        research_limitations=[{"code": "historical_availability_unverified"}],
    )
    snapshot["snapshot_id"] = backtest_dataset_snapshot_content_id(snapshot)
    return snapshot


def test_simulation_admits_exact_content_without_claiming_pit_or_account_rights():
    snapshot = _snapshot()
    result = dataset_simulation_admission(snapshot)
    assert result["status"] == "admitted"
    assert result["historical_pit_verified"] is False
    assert result["account_publication_admitted"] is False
    assert result["limitations"] == snapshot["research_limitations"]
    for field, replacement in (
        ("snapshot_id", "sha256:" + "0" * 64),
        ("content_identity", {}),
        ("data_quality", {"status": "warning"}),
    ):
        tampered = {**snapshot, field: replacement}
        assert dataset_simulation_admission(tampered)["status"] == "blocked"


def test_typed_input_only_advances_research_with_explicit_frozen_costs():
    baseline, candidate = _view(candidate=False), _view(candidate=True)
    snapshot = _snapshot()
    for view in (baseline, candidate):
        view.update(
            dataset_research_use="exploratory_backtest",
            dataset_snapshot=deepcopy(snapshot),
            dataset_snapshot_id=snapshot["snapshot_id"],
            cost_assumptions=research_friction_assumptions(),
        )
    gate = build_normalized_research_advancement_gate(
        baseline=baseline, candidate=candidate, critique_evidence={}
    )
    frozen = next(
        item for item in gate.checks if item["name"] == "frozen_dataset_identity"
    )
    assert frozen["status"] == "pass"
    assert (
        frozen["evidence"]["candidate_simulation_admission"][
            "account_publication_admitted"
        ]
        is False
    )
    account_gate = build_strategy_advancement_gate(
        baseline=baseline, candidate=candidate, critique_evidence={}
    )
    assert "candidate_dataset_exploratory_only" in account_gate.blockers
    candidate["cost_assumptions"]["slippage_bps"] = "0"
    gate = build_normalized_research_advancement_gate(
        baseline=baseline, candidate=candidate, critique_evidence={}
    )
    assert gate.status == "blocked"
