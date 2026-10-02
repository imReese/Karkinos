"""Exercise sealed replay against real local stores and frozen input identities."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal

import pandas as pd
import pytest

from analytics.dataset_snapshot import (
    build_backtest_dataset_snapshot,
    verify_backtest_dataset_snapshot_replay,
)
from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from data.handler import DataHandler
from data.research_market_data import (
    load_research_market_frames,
    research_market_binding,
)
from data.store import DataStore
from server.ai_runtime.formula_dsl import FORMULA_AST_CONTRACT
from server.ai_runtime.strategy_research_backtest import (
    RestrictedFormulaBacktestAdapter,
)
from server.ai_runtime.strategy_research_privacy import NORMALIZED_RESEARCH_NOTIONAL
from server.contracts.strategy_research import (
    StrategyResearchRejected,
    StrategyResearchSelection,
)

_SYMBOL = Symbol("600000")
_DATES = pd.bdate_range("2026-01-05", periods=8).strftime("%Y-%m-%d").tolist()
_RESEARCH_END = _DATES[5]
_DRAFT = {
    "formula_ast": {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": {
            "op": "cross",
            "left": {"op": "field", "name": "close"},
            "right": {
                "op": "rolling_mean",
                "input": {"op": "field", "name": "close"},
                "window": 3,
            },
        },
        "exit": {
            "op": "lt",
            "left": {"op": "field", "name": "close"},
            "right": {
                "op": "rolling_mean",
                "input": {"op": "field", "name": "close"},
                "window": 3,
            },
        },
        "position_size": {"op": "equal_weight"},
    }
}


def _receipt_inputs(tmp_path, *, missing_day=None):
    store = DataStore(tmp_path / "market")
    receipts = []
    for day, close in zip(
        _DATES, [10, 9.9, 9.8, 10.1, 10.2, 10.3, 10, 9.9], strict=True
    ):
        if day == missing_day:
            continue
        receipts.append(
            store.ingest_market_daily_batch(
                trade_date=day,
                provider_name="fixture",
                bars=pd.DataFrame(
                    {
                        "symbol": [str(_SYMBOL)],
                        "timestamp": [pd.Timestamp(day)],
                        "open": [close],
                        "high": [close + 0.1],
                        "low": [close - 0.1],
                        "close": [close],
                        "volume": [100_000],
                        "amount": [close * 100_000],
                    }
                ),
            )
        )
    binding = research_market_binding(
        [receipt for receipt in receipts if receipt["trade_date"] <= _RESEARCH_END]
    )
    frames = load_research_market_frames(
        store._root,
        binding=binding,
        symbols=[str(_SYMBOL)],
        start_date=_DATES[0],
        end_date=_RESEARCH_END,
    )
    snapshot = build_backtest_dataset_snapshot(
        start_date=_DATES[0],
        end_date=_RESEARCH_END,
        configured_source="fixture",
        source_names=["fixture"],
        data_handlers={
            _SYMBOL: DataHandler(
                frames[str(_SYMBOL)],
                _SYMBOL,
                asset_class=AssetClass.STOCK,
                instrument_type=InstrumentType.STOCK,
            )
        },
        store=store,
        market_data_binding=binding,
    )
    selection = StrategyResearchSelection(
        saved_backtest_result_id=1,
        universe=(str(_SYMBOL),),
        asset_classes=("stock",),
        dataset_snapshot_id=snapshot["snapshot_id"],
        start_date=_DATES[0],
        end_date=_RESEARCH_END,
        sealed_end_date=_DATES[-1],
        frequency="1d",
        initial_cash=NORMALIZED_RESEARCH_NOTIONAL,
    )
    return store, selection, snapshot


def test_receipt_history_still_replays_but_new_results_declare_price_return_limits(
    tmp_path,
):
    store, _, snapshot = _receipt_inputs(tmp_path)
    assert snapshot["research_use"] == "exploratory_backtest"
    assert snapshot["price_basis"] == "unadjusted"
    assert snapshot["point_in_time_verified"] is False
    assert "unadjusted_corporate_actions_unmodeled" in {
        item["code"] for item in snapshot["research_limitations"]
    }
    # Persisted v1 receipt reports predate these annotations. Their original
    # content address remains replayable; current admission is checked separately.
    legacy = {
        key: value
        for key, value in snapshot.items()
        if key
        not in {
            "snapshot_id",
            "research_use",
            "price_basis",
            "point_in_time_verified",
            "research_limitations",
        }
    }
    legacy["snapshot_id"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(legacy, sort_keys=True, default=str, ensure_ascii=False).encode()
        ).hexdigest()
    )
    assert legacy["snapshot_id"] != snapshot["snapshot_id"]
    for value in (legacy, snapshot):
        assert (
            verify_backtest_dataset_snapshot_replay(value, store_root=store._root)[
                "status"
            ]
            == "pass"
        )


def test_sealed_replay_binds_complete_input_without_rewriting_research_prefix(tmp_path):
    store, selection, snapshot = _receipt_inputs(tmp_path)
    result = RestrictedFormulaBacktestAdapter(data_store=store).run_sealed(
        selection=selection,
        draft=_DRAFT,
        sealed_end_date=selection.sealed_end_date,
        expected_dataset_snapshot=snapshot,
        expected_trading_dates=_DATES,
    )
    full = result.dataset_snapshot
    assert full["snapshot_id"] != snapshot["snapshot_id"]
    assert full["date_range"] == {"start": _DATES[0], "end": _DATES[-1]}
    assert (
        full["market_data_binding"]["receipts"][:6]
        == snapshot["market_data_binding"]["receipts"]
    )
    assert len(full["market_data_binding"]["receipts"]) == len(_DATES)
    assert result.fills
    assert any(
        fill.timestamp.date().isoformat() > _RESEARCH_END for fill in result.fills
    )
    for bound in (snapshot, full):
        assert (
            verify_backtest_dataset_snapshot_replay(bound, store_root=store._root)[
                "status"
            ]
            == "pass"
        )


@pytest.mark.parametrize("expected_dates", [_DATES, []])
def test_sealed_replay_rejects_missing_middle_session_even_with_final_bar(
    tmp_path, expected_dates
):
    store, selection, snapshot = _receipt_inputs(tmp_path, missing_day=_DATES[6])
    assert (
        store.load_bars(_SYMBOL, instrument_type="stock")
        .iloc[-1]["timestamp"]
        .date()
        .isoformat()
        == _DATES[-1]
    )
    with pytest.raises(
        StrategyResearchRejected, match="sealed_trading_calendar_coverage_incomplete"
    ):
        RestrictedFormulaBacktestAdapter(data_store=store).run_sealed(
            selection=selection,
            draft=_DRAFT,
            sealed_end_date=selection.sealed_end_date,
            expected_dataset_snapshot=snapshot,
            expected_trading_dates=expected_dates,
        )


def test_sealed_replay_rejects_changed_frozen_research_observation(tmp_path):
    store, selection, snapshot = _receipt_inputs(tmp_path)
    with sqlite3.connect(store._meta_path) as conn:
        conn.execute(
            "UPDATE market_bars_v2 SET close=9.95 WHERE symbol=? AND substr(timestamp,1,10)=?",
            (str(_SYMBOL), _DATES[0]),
        )
    with pytest.raises(ValueError, match="research_market_receipt_drift"):
        RestrictedFormulaBacktestAdapter(data_store=store).run_sealed(
            selection=selection,
            draft=_DRAFT,
            sealed_end_date=selection.sealed_end_date,
            expected_dataset_snapshot=snapshot,
            expected_trading_dates=_DATES,
        )


def test_sealed_replay_cannot_replace_immutable_dataset_with_current_store_rows(
    tmp_path,
):
    # Reuse the deterministic published-Dataset fixture: its provider is local,
    # while capture, revisions, manifests and DatasetReader are real.
    from server.services.backtest_dataset_inputs import load_dataset_backtest_inputs
    from tests.server.test_research_datasets import _backtest_request, _publish

    store = DataStore(tmp_path / "market")
    research_root = store._root / "research"
    ref = _publish(research_root)
    request = _backtest_request(ref)
    _, handlers, binding = load_dataset_backtest_inputs(research_root, request)
    snapshot = build_backtest_dataset_snapshot(
        start_date=request.start_date,
        end_date=request.end_date,
        configured_source="tdx",
        source_names=["tdx"],
        data_handlers=handlers,
        store=store,
        research_dataset_binding=binding,
    )
    current = handlers[_SYMBOL]._df.copy()
    current.loc[0, "close"] += Decimal("0.1")
    store.save_bars(_SYMBOL, BarFrequency.DAILY, current, instrument_type="stock")
    assert (
        verify_backtest_dataset_snapshot_replay(snapshot, store_root=store._root)[
            "status"
        ]
        == "pass"
    )
    selection = StrategyResearchSelection(
        saved_backtest_result_id=1,
        universe=(str(_SYMBOL),),
        asset_classes=("stock",),
        dataset_snapshot_id=snapshot["snapshot_id"],
        start_date=request.start_date,
        end_date=request.end_date,
        sealed_end_date="2026-09-15",
        frequency="1d",
        initial_cash=NORMALIZED_RESEARCH_NOTIONAL,
    )
    with pytest.raises(
        StrategyResearchRejected, match="sealed_immutable_dataset_extension_unsupported"
    ):
        RestrictedFormulaBacktestAdapter(data_store=store).run_sealed(
            selection=selection,
            draft=_DRAFT,
            sealed_end_date=selection.sealed_end_date,
            expected_dataset_snapshot=snapshot,
        )
