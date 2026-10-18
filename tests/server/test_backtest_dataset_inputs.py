"""Verified Dataset adaptation preserves replay values without repeated full scans."""

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from core.events import MarketEvent
from core.types import (
    AssetClass,
    BarFrequency,
    CommissionType,
    InstrumentKey,
    InstrumentType,
    Settlement,
)
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.reader import read_daily_bar_dataset
from data.storage.objects import ContentAddressedObjectStore
from server.services import backtest_dataset_inputs as inputs
from server.services.research_datasets import ResearchDatasetError
from tests.server.test_dataset_corporate_actions import CAPTURED, _observe
from tests.server.test_deployment_scope_datasets import _composed
from tests.server.test_verified_interval_dataset import DAYS, _verified_day

STOCK = InstrumentKey("600000", InstrumentType.STOCK)
ETF = InstrumentKey("510300", InstrumentType.ETF)


def _mixed(root):
    store = ContentAddressedObjectStore(root / "objects")
    partitions = []
    for day, close in zip(DAYS, ("10.12345678", "10.87654321"), strict=True):
        ref = _verified_day(root, day, instruments=(STOCK, ETF), close=close)
        daily = read_daily_bar_dataset(store, ref)
        partitions.extend(daily.snapshot.partitions)
    ref = publish_daily_bar_dataset_manifest(
        store,
        replace(daily.snapshot, start_date=DAYS[0], partitions=tuple(partitions)),
    )
    return read_daily_bar_dataset(store, ref)


def _request(result):
    return SimpleNamespace(
        dataset_id=result.ref.dataset_id,
        start_date=result.snapshot.start_date.isoformat(),
        end_date=result.snapshot.end_date.isoformat(),
        assets=[
            {"symbol": key.symbol, "instrument_type": key.instrument_type.value}
            for key in result.snapshot.instruments
        ],
    )


class _CountedBars(tuple):
    def __init__(self, bars):
        self.visits = 0

    def __iter__(self):
        for bar in super().__iter__():
            self.visits += 1
            yield bar


@pytest.mark.parametrize("shape", ["mixed", "sparse"])
def test_verified_inputs_preserve_values_identity_and_replay_order(tmp_path, shape):
    root = tmp_path / "research"
    result = _mixed(root) if shape == "mixed" else _composed(tmp_path)[1]
    instruments, handlers, binding = inputs.load_dataset_backtest_inputs(
        root, _request(result)
    )

    assert list(handlers) == [key.symbol for key in result.snapshot.instruments]
    assert list(instruments) == list(handlers)
    columns = [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "available_at",
        "captured_at",
    ]
    fields = ["event_time", *columns[1:]]
    for key in result.snapshot.instruments:
        bars = tuple(bar for bar in result.bars if bar.instrument == key)
        handler, instrument = handlers[key.symbol], instruments[key.symbol]
        expected = pd.DataFrame(
            [[getattr(bar, field) for field in fields] for bar in bars],
            columns=columns,
        )
        expected.attrs.update(
            provider_name="tdx",
            data_source="tdx",
            adjustment_mode="none",
            dataset_id=result.ref.dataset_id,
        )
        pd.testing.assert_frame_equal(handler._df, expected, check_exact=True)
        assert handler._df.attrs == expected.attrs
        for column in columns[1:7]:
            assert all(isinstance(value, Decimal) for value in handler._df[column])
        is_stock = key.instrument_type is InstrumentType.STOCK
        assert instrument.asset_class is (
            AssetClass.STOCK if is_stock else AssetClass.FUND
        )
        assert (
            instrument.instrument_type is handler.instrument_type is key.instrument_type
        )
        assert instrument.symbol == instrument.name == key.symbol
        assert instrument.commission_type is (
            CommissionType.STOCK_A if is_stock else CommissionType.FUND_ETF
        )
        assert instrument.settlement is Settlement.T_PLUS_1
        assert instrument.lot_size == Decimal("100")
        assert instrument.price_tick == Decimal("0.01" if is_stock else "0.001")
        events = tuple(
            MarketEvent(
                timestamp=bar.event_time,
                symbol=key.symbol,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                frequency=BarFrequency.DAILY,
                asset_class=instrument.asset_class,
                instrument_type=key.instrument_type,
                available_at=bar.available_at,
            )
            for bar in bars
        )
        assert tuple(handler) == events
        assert tuple(handler.stream()) == events
    assert [handler.total_bars for handler in handlers.values()] == (
        [2, 2] if shape == "mixed" else [2, 1]
    )
    assert binding["dataset_id"] == result.ref.dataset_id
    assert binding["cutoff"] == result.snapshot.cutoff.isoformat()
    assert binding["source_names"] == ["tdx"]
    assert binding["price_basis"] == "unadjusted"
    assert binding["cross_source_verified"] is True
    assert binding["offline_replay"] is True
    assert binding["point_in_time_verified"] is False
    assert "corporate_action_evidence" not in binding
    audit = binding["decision_availability"]
    assert audit["status"] == "blocked"
    assert audit["checked_bar_count"] == len(result.bars)
    assert (
        audit["late_bar_count"] == audit["late_verification_count"] == len(result.bars)
    )


def test_inputs_retain_bound_corporate_action_evidence(tmp_path):
    store = ContentAddressedObjectStore(tmp_path / "objects")
    original = _verified_day(tmp_path, DAYS[0])
    before = read_daily_bar_dataset(store, original)
    observation = _observe(store)
    ref = publish_daily_bar_dataset_manifest(
        store,
        replace(
            before.snapshot,
            cutoff=CAPTURED,
            corporate_action_observation_ids=(observation.object_id,),
        ),
    )
    result = read_daily_bar_dataset(store, ref)

    _, handlers, binding = inputs.load_dataset_backtest_inputs(
        tmp_path, _request(result)
    )

    assert ref != original
    assert binding["dataset_id"] == ref.dataset_id
    assert binding["corporate_action_evidence"] == result.corporate_action_evidence
    assert binding["corporate_action_evidence"]["observation_ids"] == [
        observation.object_id
    ]
    assert binding["corporate_action_evidence"]["returns_modeled"] is False
    assert handlers[STOCK.symbol]._df["close"].tolist() == [before.bars[0].close]
    assert read_daily_bar_dataset(store, original) == before


def test_missing_instrument_rows_still_fail_closed(tmp_path, monkeypatch):
    result = _mixed(tmp_path)

    def missing_read(store, ref):
        restored = read_daily_bar_dataset(store, ref)
        return replace(
            restored,
            bars=tuple(bar for bar in restored.bars if bar.instrument != STOCK),
        )

    monkeypatch.setattr(inputs, "read_daily_bar_dataset", missing_read)
    with pytest.raises(ResearchDatasetError, match="^dataset_instrument_has_no_rows$"):
        inputs.load_dataset_backtest_inputs(tmp_path, _request(result))


def test_input_bar_visits_stay_bounded_as_instrument_count_grows(tmp_path, monkeypatch):
    keys = tuple(
        InstrumentKey(str(600000 + index), InstrumentType.STOCK) for index in range(6)
    )
    ref = _verified_day(tmp_path, DAYS[0], instruments=keys)
    result = read_daily_bar_dataset(
        ContentAddressedObjectStore(tmp_path / "objects"), ref
    )
    observed = []

    def counted_read(store, dataset_ref):
        restored = read_daily_bar_dataset(store, dataset_ref)
        bars = _CountedBars(restored.bars)
        observed.append(bars)
        return replace(restored, bars=bars)

    monkeypatch.setattr(inputs, "read_daily_bar_dataset", counted_read)
    _, handlers, binding = inputs.load_dataset_backtest_inputs(
        tmp_path, _request(result)
    )

    assert len(handlers) == len(keys)
    assert binding["decision_availability"]["checked_bar_count"] == len(result.bars)
    assert len(observed) == 1
    # Include the availability audit, but never scan all bars for each symbol.
    assert observed[0].visits <= 3 * len(result.bars)
