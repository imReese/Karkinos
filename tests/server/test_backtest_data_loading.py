"""Exact instrument identity at exploratory backtest data-loading boundaries."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from data.manager import DataManager
from data.store import DataStore
from server.contracts.http.backtest import StrategySignalPreviewRequest
from server.models import BacktestRequest
from server.services.backtest_views.execution import (
    prepare_retrieved_dataset_backtest_inputs,
)
from server.services.backtest_views.strategy_inputs import load_signal_preview_bars

_SYMBOL = Symbol("000001")
_START = "2026-06-01"
_END = "2026-06-04"


@pytest.fixture
def market_store(monkeypatch, tmp_path):
    store = DataStore(tmp_path / "market")
    monkeypatch.setattr("data.store.DataStore", lambda: store)
    monkeypatch.setattr(
        "server.services.backtest_views.strategy_inputs.resolve_backtest_data_plane",
        lambda config: ({"akshare": object()}, None, "akshare"),
    )
    return store


def _load(loader: str, instrument_type: InstrumentType):
    config = SimpleNamespace(data_source="akshare")
    if loader == "preview":
        bars, snapshot = load_signal_preview_bars(
            StrategySignalPreviewRequest(
                strategy="dual_ma",
                symbol=str(_SYMBOL),
                asset_class=instrument_type.value,
                start_date=_START,
                end_date=_END,
            ),
            config,
        )
        return bars, snapshot, None
    instruments, handlers, _, snapshot = prepare_retrieved_dataset_backtest_inputs(
        BacktestRequest(
            start_date=_START,
            end_date=_END,
            assets=[{"symbol": str(_SYMBOL), "instrument_type": instrument_type.value}],
        ),
        config,
    )
    return tuple(handlers[_SYMBOL]), snapshot, instruments[_SYMBOL]


@pytest.mark.parametrize("loader", ["preview", "retrieved"])
@pytest.mark.parametrize(
    "instrument_type",
    [InstrumentType.STOCK, InstrumentType.ETF, InstrumentType.OPEN_END_FUND],
)
def test_internal_type_error_never_retries_without_exact_identity(
    monkeypatch, market_store, loader, instrument_type
) -> None:
    calls = []
    get_bars = DataManager.get_bars

    def traced_get_bars(self, *args, **kwargs):
        calls.append((kwargs.get("asset_class"), kwargs.get("instrument_type")))
        return get_bars(self, *args, **kwargs)

    def broken_cache(*args, **kwargs):
        raise TypeError("synthetic internal cache failure")

    monkeypatch.setattr(DataManager, "get_bars", traced_get_bars)
    monkeypatch.setattr(market_store, "load_bars", broken_cache)

    with pytest.raises(TypeError, match="synthetic internal cache failure"):
        _load(loader, instrument_type)

    asset_class = (
        AssetClass.STOCK if instrument_type is InstrumentType.STOCK else AssetClass.FUND
    )
    assert calls == [(asset_class, instrument_type)]


@pytest.mark.parametrize("loader", ["preview", "retrieved"])
@pytest.mark.parametrize(
    "instrument_type", [InstrumentType.ETF, InstrumentType.OPEN_END_FUND]
)
def test_cached_fund_loading_preserves_exact_identity_and_broad_group(
    monkeypatch, market_store, loader, instrument_type
) -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range(_START, _END),
            "open": [10, 11, 12, 13],
            "high": [10, 11, 12, 13],
            "low": [10, 11, 12, 13],
            "close": [10, 11, 12, 13],
            "volume": [1000] * 4,
        }
    )
    market_store.save_bars(
        _SYMBOL,
        BarFrequency.DAILY,
        frame,
        instrument_type=instrument_type,
        provider_name="fixture",
        data_source="fixture",
    )

    def reject_legacy_instrument(*args, **kwargs):
        pytest.fail("exact identity must not use the broad-class instrument factory")

    monkeypatch.setattr(DataManager, "get_instrument", reject_legacy_instrument)
    bars, snapshot, instrument = _load(loader, instrument_type)

    assert len(bars) == 4
    assert all(bar.instrument_type is instrument_type for bar in bars)
    assert all(bar.asset_class is AssetClass.FUND for bar in bars)
    assert snapshot["symbol_universe"][0]["instrument_type"] == instrument_type.value
    assert snapshot["symbol_universe"][0]["asset_class"] == AssetClass.FUND.value
    if instrument is not None:
        assert instrument.instrument_type is instrument_type
        assert instrument.asset_class is AssetClass.FUND
