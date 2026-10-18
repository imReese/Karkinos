"""Verifier CLI uses exact stored identities and reports actual bar differences."""

from __future__ import annotations

import json
from datetime import datetime, time

import pandas as pd
import pytest

from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from data.store import DataStore
from scripts.data import verify_market_bars as cli

SYMBOL = Symbol("019999")


def _bars(prices, *, intraday=False):
    timestamps = (
        pd.to_datetime(["2026-06-15T09:30:00", "2026-06-15T09:35:00"])
        if intraday
        else pd.to_datetime(["2026-06-12", "2026-06-15"])
    )
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1000.0, 1100.0],
        }
    )


class _Source:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def fetch_bars(self, symbol, start, end, frequency, asset_class):
        self.calls.append((symbol, start, end, frequency, asset_class))
        mask = (self.frame["timestamp"] >= pd.Timestamp(start)) & (
            self.frame["timestamp"] <= pd.Timestamp(end)
        )
        return self.frame.loc[mask].copy()


def _arguments(root):
    return [
        "--root",
        str(root),
        "--symbol",
        str(SYMBOL),
        "--start",
        "2026-06-12",
        "--end",
        "2026-06-15",
        "--provider",
        "akshare",
    ]


@pytest.mark.parametrize(
    "selected, other, asset_class",
    [
        (InstrumentType.ETF, InstrumentType.OPEN_END_FUND, AssetClass.FUND),
        (InstrumentType.OPEN_END_FUND, InstrumentType.ETF, AssetClass.FUND),
        (InstrumentType.STOCK, InstrumentType.INDEX, AssetClass.STOCK),
        (InstrumentType.INDEX, InstrumentType.STOCK, AssetClass.INDEX),
    ],
)
@pytest.mark.parametrize("explicit_asset_class", [False, True])
def test_cli_verifies_exact_cached_identity_without_overwriting(
    tmp_path, monkeypatch, capsys, selected, other, asset_class, explicit_asset_class
):
    store = DataStore(tmp_path / "data")
    frame = _bars([1.25, 1.30])
    other_frame = _bars([9.0, 9.5])
    store.save_bars(SYMBOL, BarFrequency.DAILY, frame, instrument_type=selected)
    store.save_bars(SYMBOL, BarFrequency.DAILY, other_frame, instrument_type=other)
    before_selected = store.load_bars(
        SYMBOL, BarFrequency.DAILY, instrument_type=selected
    )
    before_other = store.load_bars(SYMBOL, BarFrequency.DAILY, instrument_type=other)
    source = _Source(frame)
    monkeypatch.setattr(cli, "build_sources", lambda **kwargs: {"akshare": source})
    monkeypatch.setattr(
        DataStore,
        "save_bars",
        lambda *args, **kwargs: pytest.fail("verification must not overwrite bars"),
    )
    arguments = _arguments(tmp_path / "data") + ["--instrument-type", selected.value]
    if explicit_asset_class:
        arguments += ["--asset-class", asset_class.value]

    assert cli.main(arguments) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "matched"
    assert report["checked_rows"] == 2
    assert report["mismatch_count"] == 0
    assert len(source.calls) == 1
    assert source.calls[0][-1] is asset_class
    pd.testing.assert_frame_equal(
        store.load_bars(SYMBOL, BarFrequency.DAILY, instrument_type=selected),
        before_selected,
    )
    pd.testing.assert_frame_equal(
        store.load_bars(SYMBOL, BarFrequency.DAILY, instrument_type=other), before_other
    )


@pytest.mark.parametrize(
    "identity_args",
    [
        ["--asset-class", "fund"],
        ["--asset-class", "stock", "--instrument-type", "etf"],
        ["--asset-class", "fund", "--instrument-type", "stock"],
        ["--asset-class", "index", "--instrument-type", "stock"],
        ["--instrument-type", "unknown"],
    ],
)
def test_cli_rejects_ambiguous_or_conflicting_identity_before_io(
    tmp_path, monkeypatch, identity_args
):
    monkeypatch.setattr(
        cli,
        "build_sources",
        lambda **kwargs: pytest.fail("invalid identity must not construct providers"),
    )
    root = tmp_path / "absent"

    with pytest.raises(SystemExit) as error:
        cli.main(_arguments(root) + identity_args)

    assert error.value.code == 2
    assert not root.exists()


def test_cli_default_identity_remains_stock(tmp_path, monkeypatch, capsys):
    store = DataStore(tmp_path / "data")
    frame = _bars([10.0, 11.0])
    store.save_bars(
        SYMBOL, BarFrequency.DAILY, frame, instrument_type=InstrumentType.STOCK
    )
    store.save_bars(
        SYMBOL,
        BarFrequency.DAILY,
        _bars([90.0, 99.0]),
        instrument_type=InstrumentType.INDEX,
    )
    source = _Source(frame)
    monkeypatch.setattr(cli, "build_sources", lambda **kwargs: {"akshare": source})

    assert cli.main(_arguments(tmp_path / "data")) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "matched"
    assert source.calls[0][-1] is AssetClass.STOCK


@pytest.mark.parametrize(
    "case, status, checked_rows, expected_exit",
    [
        ("match", "matched", 2, 0),
        ("earlier_difference", "mismatched", 2, 1),
        ("missing_minute", "mismatched", 1, 1),
        ("both_empty", "missing_both", 0, 1),
    ],
)
def test_cli_intraday_status_and_exit_reflect_all_bar_evidence(
    tmp_path, monkeypatch, capsys, case, status, checked_rows, expected_exit
):
    store = DataStore(tmp_path / "data")
    frame = _bars([10.0, 11.0], intraday=True)
    if case != "both_empty":
        store.save_bars(
            SYMBOL, BarFrequency.MIN_1, frame, instrument_type=InstrumentType.STOCK
        )
    provider = frame.copy()
    if case == "earlier_difference":
        provider.loc[0, "close"] = 99.0
    elif case == "missing_minute":
        provider = provider.iloc[1:]
    elif case == "both_empty":
        provider = provider.iloc[:0]
    source = _Source(provider)
    monkeypatch.setattr(cli, "build_sources", lambda **kwargs: {"akshare": source})
    arguments = _arguments(tmp_path / "data")
    arguments[arguments.index("--start") + 1] = "2026-06-15T09:30:00"
    arguments[arguments.index("--end") + 1] = "2026-06-15T09:35:00"

    assert cli.main(arguments + ["--frequency", "1m"]) == expected_exit

    report = json.loads(capsys.readouterr().out)
    assert report["status"] == status
    assert report["checked_rows"] == checked_rows
    assert report["mismatch_count"] == (1 if status == "mismatched" else 0)
    assert len(source.calls) == 1


@pytest.mark.parametrize(
    "end_argument, expected_end, expected_rows",
    [
        ("2026-06-15", datetime.combine(datetime(2026, 6, 15).date(), time.max), 2),
        ("2026-06-15T09:30:00", datetime(2026, 6, 15, 9, 30), 1),
    ],
)
def test_cli_date_end_includes_whole_day_but_datetime_keeps_exact_boundary(
    tmp_path, monkeypatch, capsys, end_argument, expected_end, expected_rows
):
    root = tmp_path / "data"
    store = DataStore(root)
    frame = _bars([10.0, 11.0], intraday=True)
    store.save_bars(
        SYMBOL, BarFrequency.MIN_1, frame, instrument_type=InstrumentType.STOCK
    )
    before = store.load_bars(
        SYMBOL, BarFrequency.MIN_1, instrument_type=InstrumentType.STOCK
    )
    source = _Source(frame)
    monkeypatch.setattr(cli, "build_sources", lambda **kwargs: {"akshare": source})
    monkeypatch.setattr(
        DataStore,
        "save_bars",
        lambda *args, **kwargs: pytest.fail("verification must not overwrite bars"),
    )
    arguments = _arguments(root)
    arguments[arguments.index("--start") + 1] = "2026-06-15"
    arguments[arguments.index("--end") + 1] = end_argument

    assert cli.main(arguments + ["--frequency", "1m"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "matched"
    assert report["local_rows"] == report["provider_rows"] == expected_rows
    assert report["checked_rows"] == expected_rows
    assert source.calls == [
        (
            SYMBOL,
            datetime(2026, 6, 15),
            expected_end,
            BarFrequency.MIN_1,
            AssetClass.STOCK,
        )
    ]
    pd.testing.assert_frame_equal(
        store.load_bars(
            SYMBOL, BarFrequency.MIN_1, instrument_type=InstrumentType.STOCK
        ),
        before,
    )
