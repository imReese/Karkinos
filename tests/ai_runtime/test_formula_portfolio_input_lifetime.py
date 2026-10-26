"""A portfolio's date lookup must not keep the canonical bar graph alive."""

import gc
import weakref
from dataclasses import fields, replace
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset import reader
from data.storage.objects import ContentAddressedObjectStore, ObjectRef
from server.ai_runtime.strategy_research_backtest import (
    _bound_formula_portfolio_inputs,
)


@pytest.mark.parametrize("dated_memberships", [True, False])
def test_membership_lookup_releases_bars_and_preserves_date_contract(
    monkeypatch, tmp_path, dated_memberships
):
    class BarGraph:
        pass

    day = date(2026, 1, 2)
    keys = tuple(
        InstrumentKey(symbol, InstrumentType.STOCK) for symbol in ("600000", "600001")
    )
    references = []

    def read(*_args):
        graph = BarGraph()
        references.append(weakref.ref(graph))
        return SimpleNamespace(
            bars=(graph,),
            snapshot=SimpleNamespace(
                instruments=keys,
                session_memberships=(
                    (SimpleNamespace(partition_date=day, instruments=keys[:1]),)
                    if dated_memberships
                    else ()
                ),
            ),
            corporate_action_evidence=None,
        )

    monkeypatch.setattr(reader, "read_daily_bar_dataset", read)
    monkeypatch.setattr(
        reader,
        "dataset_session_nontrading_instruments",
        lambda *_args: {day: keys[1:]},
    )
    monkeypatch.setattr(
        ContentAddressedObjectStore,
        "resolve_ref",
        lambda *_args: ObjectRef(object_id="sha256:" + "1" * 64, size_bytes=0),
    )
    members, nontrading, distributions = _bound_formula_portfolio_inputs(
        tmp_path, {"immutable_dataset_id": "sha256:" + "1" * 64}
    )
    assert distributions is None
    expected = ["600000"] if dated_memberships else ["600000", "600001"]
    assert members(day) == expected
    returned = members(day)
    returned.append("unrelated-caller-value")
    assert members(day) == expected
    assert nontrading(day) == ["600001"]
    assert nontrading(day + timedelta(days=1)) == []
    if dated_memberships:
        with pytest.raises(ValueError, match="dataset_session_membership_missing"):
            members(day + timedelta(days=1))
    else:
        assert members(day + timedelta(days=1)) == expected
    gc.collect()
    assert len(references) == 1 and references[0]() is None


@pytest.mark.parametrize("prepare_caller_snapshot", [False, True])
def test_verified_bar_graph_is_released_before_every_engine_replay(
    monkeypatch, tmp_path, prepare_caller_snapshot
):
    from analytics.dataset_snapshot import (
        build_backtest_dataset_snapshot,
        load_immutable_dataset_inputs,
    )
    from backtest.engine import BacktestEngine
    from data.market.model import DailyBarObservation
    from tests.ai_runtime.test_strategy_sealed_backtest_inputs import (
        _scoped_formula_inputs,
    )

    # A subclass permits weak references without changing any native bar fields.
    class TrackedBar(DailyBarObservation):
        pass

    adapter, selection, draft, snapshot, _ = _scoped_formula_inputs(
        tmp_path, monkeypatch, halt=True, actions=True
    )
    references, cold_reads, engine_runs = [], [], []
    cold_read = reader._read_daily_bar_dataset
    run_engine = BacktestEngine.run

    def tracked_cold_read(objects, ref):
        assert not engine_runs, "Engine replays must not reopen the Dataset"
        restored = cold_read(objects, ref)
        bars = tuple(
            TrackedBar(
                **{field.name: getattr(bar, field.name) for field in fields(bar)}
            )
            for bar in restored.bars
        )
        references.extend(weakref.ref(bar) for bar in bars)
        cold_reads.append(ref)
        return replace(restored, bars=bars)

    def tracked_engine_run(engine):
        gc.collect()
        assert references and all(ref() is None for ref in references)
        engine_runs.append(1)
        return run_engine(engine)

    monkeypatch.setattr(reader, "_read_daily_bar_dataset", tracked_cold_read)
    monkeypatch.setattr(BacktestEngine, "run", tracked_engine_run)
    if prepare_caller_snapshot:
        with reader.daily_bar_dataset_read_scope():
            instruments, handlers, binding = load_immutable_dataset_inputs(
                adapter._research_root, snapshot
            )
            prepared_snapshot = build_backtest_dataset_snapshot(
                start_date=selection.start_date,
                end_date=selection.end_date,
                configured_source=binding["source_names"][0],
                source_names=binding["source_names"],
                data_handlers=handlers,
                store=None,
                research_dataset_binding=binding,
            )
            assert prepared_snapshot == snapshot
            del handlers, instruments
        gc.collect()
        assert references and all(ref() is None for ref in references)
    result, _ = adapter.run(
        selection=selection, draft=draft, expected_dataset_snapshot=snapshot
    )
    assert len(cold_reads) == (2 if prepare_caller_snapshot else 1)
    assert len(engine_runs) == 5
    assert result["metrics_json"]["cash_dividend_accounting"] is not None
