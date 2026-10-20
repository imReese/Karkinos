"""Exercise sealed replay against real local stores and frozen input identities."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

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
from server.ai_runtime.formula_dsl import (
    CANONICAL_COST_MODEL_REFERENCE,
    FORMULA_AST_CONTRACT,
    FormulaBinding,
)
from server.ai_runtime.strategy_research_backtest import (
    RestrictedFormulaBacktestAdapter,
)
from server.ai_runtime.strategy_research_privacy import NORMALIZED_RESEARCH_NOTIONAL
from server.contracts.strategy_research import (
    StrategyResearchRejected,
    StrategyResearchSelection,
)


def _scoped_formula_inputs(
    tmp_path, monkeypatch, *, gap=False, halt=False, actions=False
):
    """Real immutable inputs without a catalog, application DB or provider I/O."""
    from analytics.dataset_snapshot import load_immutable_dataset_inputs
    from core.types import InstrumentKey
    from data.dataset.manifest import publish_daily_bar_dataset_manifest
    from data.dataset.model import DailyBarDatasetMembership, DailyBarDatasetPartition
    from data.dataset.reader import read_daily_bar_dataset
    from data.providers import tushare_corporate_actions as dividends
    from data.providers.tdx import TDX_PROVIDER_DESCRIPTOR
    from data.storage.objects import ContentAddressedObjectStore
    from data.store import normalize_stock_master_metadata
    from server.services.market.market_universe_truth import (
        MarketUniversePolicy,
        market_deployment_scope,
        normalize_a_share_members,
    )
    from tests.data.providers import test_official_stock_master as official
    from tests.server.test_dataset_corporate_actions import _response
    from tests.server.test_verified_interval_dataset import _side

    root = tmp_path / "research"
    objects = ContentAddressedObjectStore(root / "objects")
    days = tuple(day.date() for day in pd.bdate_range("2026-09-14", periods=6))
    held, other = (
        InstrumentKey(symbol, InstrumentType.STOCK) for symbol in ("000001", "600000")
    )
    cutoff = datetime(2026, 9, 21, 8, 10, tzinfo=timezone.utc)
    status_refs = ()
    status_at = datetime(2026, 9, 18, 8, 6, tzinfo=timezone.utc)
    if halt:
        monkeypatch.setattr(official, "NOW", status_at)
        rows, refs, started, completed = official._capture(objects)
        members = normalize_a_share_members([row["symbol"] for row in rows])
        # The real reader verifies the projection against the captured bytes.
        master = {
            "schema_version": "karkinos.market_universe_snapshot.v3",
            "trade_date": days[4].isoformat(),
            "membership_basis": "current_active_stock_master",
            "availability_basis": "capture_completed_at",
            "observation_basis": "adapter_response",
            "capture_started_at": started.isoformat(),
            "capture_completed_at": completed.isoformat(),
            "available_at": completed.isoformat(),
            "source_capture_ids": sorted(refs),
            "members": members,
            "member_metadata": normalize_stock_master_metadata(rows, members),
        }
        status_refs = (objects.put_bytes(json.dumps(master).encode()).object_id,)
    partitions, memberships = [], []
    for day in days:
        instruments = (other,) if gap and day == days[4] else (held, other)
        revision, materialization, _ = _side(
            objects, day, TDX_PROVIDER_DESCRIPTOR, instruments=instruments
        )
        partitions.append(
            DailyBarDatasetPartition(
                partition_date=day,
                provider=revision.provider,
                revision_id=revision.ref.revision_id,
                materialization_id=materialization.materialization_id,
                instruments=instruments,
            )
        )
        at = datetime.combine(
            day, datetime.min.time(), tzinfo=timezone.utc
        ) + timedelta(hours=8, minutes=5)
        memberships.append(
            DailyBarDatasetMembership(
                day,
                instruments if gap else (other,),
                status_at if status_refs and day == days[4] else at,
                status_refs if day == days[4] else (),
                status_at if status_refs and day == days[4] else None,
                () if gap else (held,),
            )
        )
    from data.dataset.model import DailyBarDatasetSnapshot
    from data.market.schema import DAILY_BAR_SCHEMA_VERSION

    action_ids = ()
    if actions:
        response = _response("000001.SZ")
        response.loc[:, "record_date"] = "20260916"
        response.loc[:, "ex_date"] = "20260917"
        response.loc[:, "pay_date"] = "20260921"
        action_ids = tuple(
            dividends.collect_tushare_dividend_observation(
                objects,
                instrument=instrument,
                client=SimpleNamespace(
                    dividend=lambda instrument=instrument, **_: (
                        response if instrument == held else pd.DataFrame()
                    )
                ),
                clock=lambda: cutoff,
            ).object_id
            for instrument in (held, other)
        )
    ref = publish_daily_bar_dataset_manifest(
        objects,
        DailyBarDatasetSnapshot(
            start_date=days[0],
            end_date=days[-1],
            cutoff=cutoff,
            instruments=(held, other),
            resolver_policy_id="fixture.formula.dated.v1",
            market_schema_version=DAILY_BAR_SCHEMA_VERSION,
            partitions=tuple(partitions),
            session_memberships=tuple(memberships),
            universe_policy_id="fixture.formula.dated.v1",
            corporate_action_observation_ids=action_ids,
        ),
    )
    read_daily_bar_dataset(objects, ref)
    _, handlers, binding = load_immutable_dataset_inputs(
        root, {"immutable_dataset_id": ref.dataset_id}
    )
    snapshot = build_backtest_dataset_snapshot(
        start_date=days[0].isoformat(),
        end_date=days[-1].isoformat(),
        configured_source="tdx",
        source_names=["tdx"],
        data_handlers=handlers,
        store=None,
        research_dataset_binding=binding,
    )
    scope = market_deployment_scope(
        MarketUniversePolicy(
            minimum_master_member_count=2, minimum_history_rows=2, allocation_slots=2
        )
    )
    selection = StrategyResearchSelection(
        saved_backtest_result_id=1,
        universe=(held.symbol, other.symbol),
        asset_classes=("stock", "stock"),
        dataset_snapshot_id=snapshot["snapshot_id"],
        start_date=days[0].isoformat(),
        end_date=days[-1].isoformat(),
        frequency="1d",
        initial_cash=NORMALIZED_RESEARCH_NOTIONAL,
        deployment_scope=scope,
        portfolio_policy_id=scope["portfolio_policy_id"],
    )
    formula = {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": {
            "op": "gt",
            "left": {
                "op": "rolling_mean",
                "input": {"op": "field", "name": "close"},
                "window": 2,
            },
            "right": {"op": "constant", "value": 0},
        },
        "exit": {
            "op": "lt",
            "left": {"op": "field", "name": "close"},
            "right": {"op": "constant", "value": 0},
        },
        "position_size": {"op": "equal_weight"},
    }
    draft = {
        "draft_id": "dated-formula-fixture",
        "formula_ast": formula,
        "selected_universe": list(selection.universe),
        "dataset_snapshot_id": selection.dataset_snapshot_id,
        "test_window": {
            "start_date": selection.start_date,
            "end_date": selection.end_date,
        },
        "frequency": "1d",
        "cost_model_reference": selection.cost_model_reference,
        "anti_lookahead_assumptions": ["Only completed daily bars."],
        "parameter_values": {"window": 2},
        "parameter_ranges": {"window": [2, 3, 4]},
    }
    draft["formula_fingerprint"] = FormulaBinding(
        formula_ast=formula,
        universe=selection.universe,
        dataset_snapshot_id=selection.dataset_snapshot_id,
        start_date=selection.start_date,
        end_date=selection.end_date,
        frequency=selection.frequency,
        cost_model_reference=selection.cost_model_reference,
        anti_lookahead_assumptions=tuple(draft["anti_lookahead_assumptions"]),
        parameter_values=draft["parameter_values"],
        parameter_ranges=draft["parameter_ranges"],
        initial_cash=selection.initial_cash,
    ).fingerprint
    adapter = RestrictedFormulaBacktestAdapter(
        data_store=SimpleNamespace(_root=tmp_path / "unused-market"), research_root=root
    )
    return adapter, selection, draft, snapshot, days


def _record_formula_replays(monkeypatch):
    from backtest.engine import BacktestEngine

    runs = []
    original = BacktestEngine.run

    def recorded(engine):
        assert all(
            previous.strategy._prepared_sessions is None for previous, _ in runs
        ), "Completed replay frames must be released before the next panel"
        result = original(engine)
        runs.append((engine, result))
        return result

    monkeypatch.setattr(BacktestEngine, "run", recorded)
    return runs


def test_formula_research_respects_dated_entry_scope_in_all_replays(
    tmp_path, monkeypatch
):
    from backtest.costs import RESEARCH_COST_STRESS_BPS
    from tests.data.dataset.test_read_scope import _track_cold_reads

    adapter, selection, draft, snapshot, _ = _scoped_formula_inputs(
        tmp_path, monkeypatch
    )
    runs = _record_formula_replays(monkeypatch)
    cold_reads = _track_cold_reads(monkeypatch)
    actual, _ = adapter.run(
        selection=selection, draft=draft, expected_dataset_snapshot=snapshot
    )

    assert len(runs) == 1 + len(RESEARCH_COST_STRESS_BPS) + 2
    assert len(cold_reads) == 1
    assert actual["metrics_json"]["parameter_robustness"]["tested_count"] == 3
    for engine, result in runs:
        assert result.fills
        assert {str(fill.symbol) for fill in result.fills} == {"600000"}
        assert engine.strategy._allocation_slots == 2
        assert engine.event_bus._raise_handler_errors is True
        assert engine._stream_sorted_data_handlers is True
        assert engine.strategy.session_decisions == []
        assert engine.strategy._prepared_sessions is None
        assert result.cash_dividend_accounting is None
    assert actual["metrics_json"]["dataset_snapshot"]["point_in_time_verified"] is False
    assert (
        actual["metrics_json"]["dataset_snapshot"]["research_use"]
        == "exploratory_backtest"
    )


def test_formula_research_rejects_unproved_holding_gap(tmp_path, monkeypatch):
    adapter, selection, draft, snapshot, _ = _scoped_formula_inputs(
        tmp_path, monkeypatch, gap=True
    )
    with pytest.raises(
        ValueError, match="formula_session_holding_valuation_missing:000001"
    ):
        adapter.run(
            selection=selection, draft=draft, expected_dataset_snapshot=snapshot
        )


def test_formula_research_replays_proven_halt_and_bound_distributions(
    tmp_path, monkeypatch
):
    adapter, selection, draft, snapshot, days = _scoped_formula_inputs(
        tmp_path, monkeypatch, gap=True, halt=True, actions=True
    )
    runs = _record_formula_replays(monkeypatch)
    actual, _ = adapter.run(
        selection=selection, draft=draft, expected_dataset_snapshot=snapshot
    )

    for engine, result in runs:
        assert not any(
            fill.timestamp.date() == days[4] and str(fill.symbol) == "000001"
            for fill in result.fills
        )
        books = {row["session"]: row for row in engine.strategy.session_books}
        before, halted = books[days[3].isoformat()], books[days[4].isoformat()]
        if "000001" in before["position_values"]:
            assert (
                halted["position_values"]["000001"]
                == before["position_values"]["000001"]
            )
            assert halted["nontrading_valuations"] == [
                {
                    "symbol": "000001",
                    "valuation_basis": "last_observed_close_bound_nontrading",
                    "observation_session": days[3].isoformat(),
                    "reference_close": "10.48000000",
                    "tradable": False,
                }
            ]
        accounting = result.cash_dividend_accounting
        assert accounting is not None
        distribution = accounting["distributions"][0]
        assert Decimal(accounting["gross_income"]) == Decimal(
            distribution["eligible_quantity"]
        ) * Decimal("0.1")
        assert accounting["cash_paid"] == accounting["gross_income"]
        assert accounting["taxes_modeled"] is False
    accounting = actual["metrics_json"]["cash_dividend_accounting"]
    assert Decimal(accounting["gross_income"]) > 0
    assert accounting["coverage_verified"] is False


@pytest.mark.parametrize("full_scope", [False, True])
def test_formula_research_strict_fill_errors_preserve_legacy_behavior(
    tmp_path, monkeypatch, full_scope
):
    from server.ai_runtime.strategy_research_backtest import _FormulaSignalStrategy

    adapter, selection, draft, snapshot, _ = _scoped_formula_inputs(
        tmp_path, monkeypatch
    )
    if not full_scope:
        selection = replace(selection, deployment_scope=None, portfolio_policy_id=None)

    def failed_update(*_args):
        raise RuntimeError("fixture_position_update_failed")

    monkeypatch.setattr(_FormulaSignalStrategy, "on_position_update", failed_update)
    if full_scope:
        with pytest.raises(RuntimeError, match="fixture_position_update_failed"):
            adapter.run(
                selection=selection, draft=draft, expected_dataset_snapshot=snapshot
            )
    else:
        result, _ = adapter.run(
            selection=selection, draft=draft, expected_dataset_snapshot=snapshot
        )
        assert result["fills"]


@pytest.mark.parametrize("actions", [False, True])
def test_sealed_formula_keeps_bound_distribution_requirement(
    tmp_path, monkeypatch, actions
):
    from tests.data.dataset.test_read_scope import _track_cold_reads

    adapter, selection, draft, snapshot, days = _scoped_formula_inputs(
        tmp_path, monkeypatch, gap=True, halt=True, actions=actions
    )
    selection = replace(selection, end_date=days[0].isoformat())
    cold_reads = _track_cold_reads(monkeypatch)
    kwargs = dict(
        selection=selection,
        draft=draft,
        sealed_end_date=days[-1].isoformat(),
        evaluation_dataset_snapshot=snapshot,
    )
    if actions:
        result = adapter.run_sealed(**kwargs)
        assert Decimal(result.cash_dividend_accounting["gross_income"]) > 0
        assert any(
            row.get("nontrading_valuations") for row in result.portfolio_observations
        )
    else:
        with pytest.raises(ValueError, match="cash_dividend_evidence_required"):
            adapter.run_sealed(**kwargs)
    assert len(cold_reads) == 1


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
    # A crossover in the research history is not a carried sealed position.
    assert not result.fills
    assert (
        result.initial_cash
        == result.final_equity
        == Decimal(str(selection.initial_cash))
    )
    assert result.execution_timing["warmup_final_bar_targets"] is True
    assert all(
        stamp.date().isoformat() > _RESEARCH_END for stamp, _ in result.equity_curve
    )
    for bound in (snapshot, full):
        assert (
            verify_backtest_dataset_snapshot_replay(bound, store_root=store._root)[
                "status"
            ]
            == "pass"
        )


def test_final_comparison_has_same_fresh_cash_despite_different_research_entries(
    tmp_path,
):
    from analytics.sealed_holdout import (
        build_sealed_partition,
        sealed_return_from_result,
    )

    store, selection, snapshot = _receipt_inputs(tmp_path)
    adapter = RestrictedFormulaBacktestAdapter(data_store=store)
    measured = []
    for threshold in (9, 10.25):
        formula = {
            "schema_version": FORMULA_AST_CONTRACT,
            "entry": {
                "op": "gt",
                "left": {"op": "field", "name": "close"},
                "right": {"op": "constant", "value": threshold},
            },
            "exit": {
                "op": "lt",
                "left": {"op": "field", "name": "close"},
                "right": {"op": "constant", "value": 0},
            },
            "position_size": {"op": "equal_weight"},
        }
        measured.append(
            adapter.run_sealed(
                selection=selection,
                draft={"formula_ast": formula},
                sealed_end_date=selection.sealed_end_date,
                expected_dataset_snapshot=snapshot,
                expected_trading_dates=_DATES,
            )
        )
    partition = build_sealed_partition(
        research_start=selection.start_date,
        research_end=selection.end_date,
        sealed_end=selection.sealed_end_date,
    )
    assert (
        measured[0].initial_cash
        == measured[1].initial_cash
        == Decimal(str(selection.initial_cash))
    )
    assert measured[0].final_equity == measured[1].final_equity
    assert measured[0].equity_curve == measured[1].equity_curve
    assert sealed_return_from_result(
        measured[0], partition
    ) == sealed_return_from_result(measured[1], partition)
    for result in measured:
        assert len(result.fills) == 1
        assert result.fills[0].fill_quantity == 1000
        assert result.fills[0].timestamp.date().isoformat() == _DATES[6]


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
            "UPDATE market_bars SET close=9.95 WHERE symbol=? AND substr(timestamp,1,10)=?",
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
    from server.services.research.dataset_inputs import load_dataset_backtest_inputs
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


def test_formula_adapter_consumes_immutable_dataset_regardless_of_mutated_cache_bars(
    tmp_path,
):
    from server.ai_runtime.strategy_research_backtest import _load_bound_inputs
    from server.services.research.dataset_inputs import load_dataset_backtest_inputs
    from tests.server.test_research_datasets import _backtest_request, _publish

    store = DataStore(tmp_path / "market")
    research_root = store._root / "research"
    ref = _publish(research_root)
    request = _backtest_request(ref)
    _, original_handlers, binding = load_dataset_backtest_inputs(research_root, request)
    original_close = float(original_handlers[_SYMBOL]._df["close"].iloc[0])

    snapshot = build_backtest_dataset_snapshot(
        start_date=request.start_date,
        end_date=request.end_date,
        configured_source="tdx",
        source_names=["tdx"],
        data_handlers=original_handlers,
        store=store,
        research_dataset_binding=binding,
    )

    # Mutate the mutable store cache with doubled prices.
    mutated = original_handlers[_SYMBOL]._df.copy()
    mutated["close"] = mutated["close"].astype(float) * 2.0
    mutated["open"] = mutated["open"].astype(float) * 2.0
    store.save_bars(
        _SYMBOL,
        BarFrequency.DAILY,
        mutated,
        provider_name="tdx",
        data_source="tdx",
        instrument_type="stock",
    )

    selection = StrategyResearchSelection(
        saved_backtest_result_id=1,
        universe=(str(_SYMBOL),),
        asset_classes=("stock",),
        dataset_snapshot_id=snapshot["snapshot_id"],
        start_date=request.start_date,
        end_date=request.end_date,
        frequency="1d",
        initial_cash=NORMALIZED_RESEARCH_NOTIONAL,
    )

    handlers, instruments, returned_snapshot = _load_bound_inputs(
        store,
        selection,
        expected_dataset_snapshot=snapshot,
    )

    # Execution handlers must consume the immutable dataset, NOT the mutated cache.
    loaded_close = float(handlers[_SYMBOL]._df["close"].iloc[0])
    assert loaded_close == pytest.approx(original_close)
    assert loaded_close != pytest.approx(original_close * 2.0)
    assert returned_snapshot["snapshot_id"] == snapshot["snapshot_id"]

    validated = RestrictedFormulaBacktestAdapter(data_store=store).validate_selection(
        selection,
        expected_dataset_snapshot=snapshot,
    )
    assert validated["snapshot_id"] == snapshot["snapshot_id"]


def test_explicit_application_research_root_is_independent_of_market_cache(tmp_path):
    import shutil

    from server.services.research.dataset_inputs import load_dataset_backtest_inputs
    from tests.server.test_research_datasets import _backtest_request, _publish

    market = DataStore(tmp_path / "external-market-data")
    research_root = tmp_path / "application" / "research"
    ref = _publish(research_root)
    request = _backtest_request(ref)
    _, handlers, binding = load_dataset_backtest_inputs(research_root, request)
    snapshot = build_backtest_dataset_snapshot(
        start_date=request.start_date,
        end_date=request.end_date,
        configured_source="tdx",
        source_names=["tdx"],
        data_handlers=handlers,
        store=market,
        research_dataset_binding=binding,
    )
    selection = StrategyResearchSelection(
        saved_backtest_result_id=1,
        universe=(str(_SYMBOL),),
        asset_classes=("stock",),
        dataset_snapshot_id=snapshot["snapshot_id"],
        start_date=request.start_date,
        end_date=request.end_date,
        frequency="1d",
        initial_cash=NORMALIZED_RESEARCH_NOTIONAL,
    )
    actual = RestrictedFormulaBacktestAdapter(
        data_store=market, research_root=research_root
    ).validate_selection(selection, expected_dataset_snapshot=snapshot)
    assert actual == snapshot
    # A valid cache-side duplicate cannot override an explicitly selected CAS.
    shutil.copytree(research_root, market._root / "research")
    with pytest.raises(StrategyResearchRejected, match="immutable_dataset_unreadable"):
        RestrictedFormulaBacktestAdapter(
            data_store=market, research_root=tmp_path / "missing-research"
        ).validate_selection(selection, expected_dataset_snapshot=snapshot)


def test_formula_adapter_rejects_missing_or_corrupted_immutable_dataset(tmp_path):
    from server.ai_runtime.strategy_research_backtest import _load_bound_inputs
    from server.services.research.dataset_inputs import load_dataset_backtest_inputs
    from tests.server.test_research_datasets import _backtest_request, _publish

    store = DataStore(tmp_path / "market")
    research_root = store._root / "research"
    ref = _publish(research_root)
    request = _backtest_request(ref)
    _, original_handlers, binding = load_dataset_backtest_inputs(research_root, request)

    snapshot = build_backtest_dataset_snapshot(
        start_date=request.start_date,
        end_date=request.end_date,
        configured_source="tdx",
        source_names=["tdx"],
        data_handlers=original_handlers,
        store=store,
        research_dataset_binding=binding,
    )

    selection = StrategyResearchSelection(
        saved_backtest_result_id=1,
        universe=(str(_SYMBOL),),
        asset_classes=("stock",),
        dataset_snapshot_id=snapshot["snapshot_id"],
        start_date=request.start_date,
        end_date=request.end_date,
        frequency="1d",
        initial_cash=NORMALIZED_RESEARCH_NOTIONAL,
    )

    # 1. Non-existent immutable dataset ID in object store
    missing_snapshot = dict(snapshot)
    missing_snapshot["immutable_dataset_id"] = "sha256:" + "0" * 64
    with pytest.raises(StrategyResearchRejected, match="immutable_dataset_unreadable"):
        _load_bound_inputs(
            store,
            selection,
            expected_dataset_snapshot=missing_snapshot,
        )

    # 2. Corrupted immutable dataset payload on disk
    raw_id = ref.dataset_id
    hex_digest = raw_id.split(":", 1)[1]
    object_file = research_root / "objects" / "sha256" / hex_digest[:2] / hex_digest[2:]
    assert object_file.is_file()
    object_file.chmod(0o644)
    object_file.write_bytes(b"corrupted-invalid-object-bytes")
    object_file.chmod(0o444)
    with pytest.raises(StrategyResearchRejected, match="immutable_dataset_unreadable"):
        _load_bound_inputs(
            store,
            selection,
            expected_dataset_snapshot=snapshot,
        )
