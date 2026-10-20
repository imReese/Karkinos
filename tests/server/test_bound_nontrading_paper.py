"""Real immutable status inputs admit valuation, never a synthetic trading bar."""

from dataclasses import replace
from datetime import date, datetime, time, timezone
from decimal import Decimal

import pytest

from backtest.engine import BacktestExecutionConfig
from backtest.paper_replay import PublishedPaperTarget, replay_paper_book
from core.events import MarketEvent
from core.types import ZERO, InstrumentKey, InstrumentType, Symbol
from data.dataset.manifest import (
    bind_stock_master_observation,
    publish_daily_bar_dataset_manifest,
)
from data.dataset.model import DailyBarDatasetMembership
from data.dataset.reader import (
    dataset_session_nontrading_instruments,
    read_daily_bar_dataset,
)
from data.storage.objects import ContentAddressedObjectStore
from data.store import DataStore
from domain.instrument import make_stock
from execution.commission import StockACommission
from execution.slippage import FixedSlippage
from server.services.market.market_universe_truth import normalize_a_share_members
from tests.data.providers import test_official_stock_master as official
from tests.server.test_verified_interval_dataset import _verified_day


def test_real_bound_halt_keeps_price_and_target_until_real_resumption(
    tmp_path, monkeypatch
):
    root = tmp_path / "research"
    objects = ContentAddressedObjectStore(root / "objects")
    halted = InstrumentKey("000001", InstrumentType.STOCK)
    other = InstrumentKey("600000", InstrumentType.STOCK)
    days = [date(2026, 9, value) for value in (16, 17, 18, 21)]
    captured = datetime(2026, 9, 18, 8, 6, tzinfo=timezone.utc)
    monkeypatch.setattr(official, "NOW", captured)
    rows, refs, started, completed = official._capture(objects)
    market = DataStore(tmp_path)
    master = market.save_market_universe_snapshot(
        trade_date=days[2].isoformat(),
        provider_name="akshare",
        members=normalize_a_share_members([r["symbol"] for r in rows]),
        capture_started_at=started,
        capture_completed_at=completed,
        source_metadata=rows,
        source_capture_ids=refs,
    )
    master_ref = bind_stock_master_observation(objects, master)
    partitions, memberships = [], []
    latest = None
    for day in days:
        instruments = (other,) if day == days[2] else (halted, other)
        ref = _verified_day(
            root,
            day,
            instruments=instruments,
            close="11.00" if day == days[-1] else "10.48",
        )
        latest = read_daily_bar_dataset(objects, ref).snapshot
        partitions.append(replace(latest.partitions[0], instruments=instruments))
        memberships.append(
            DailyBarDatasetMembership(
                day,
                instruments,
                completed if day == days[2] else latest.cutoff,
                (master_ref,) if day == days[2] else (),
                completed if day == days[2] else None,
            )
        )
    snapshot = replace(
        latest,
        start_date=days[0],
        instruments=(halted, other),
        partitions=tuple(partitions),
        session_memberships=tuple(memberships),
        universe_policy_id="fixture.full_active_market",
    )
    result = read_daily_bar_dataset(
        objects, publish_daily_bar_dataset_manifest(objects, snapshot)
    )
    nontrading = dataset_session_nontrading_instruments(objects, result.snapshot)
    assert nontrading[days[2]] == (halted,)
    assert all(
        not (bar.instrument == halted and bar.session_date == days[2])
        for bar in result.bars
    )
    bars = [
        MarketEvent(
            timestamp=bar.event_time,
            symbol=Symbol(bar.instrument.symbol),
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            available_at=bar.available_at,
            instrument_type=bar.instrument.instrument_type,
        )
        for bar in result.bars
    ]
    kwargs = dict(
        book_id="actual-status-fixture",
        initial_cash=Decimal("10480"),
        instruments={
            Symbol(key.symbol): make_stock(key.symbol, key.symbol)
            for key in (halted, other)
        },
        bars=bars,
        publications=[
            PublishedPaperTarget(
                "buy",
                datetime.combine(days[0], time(8, 10), timezone.utc),
                days[1],
                {halted.symbol: Decimal(1)},
            ),
            PublishedPaperTarget(
                "exit-before-halt",
                datetime.combine(days[1], time(8, 10), timezone.utc),
                days[2],
                {halted.symbol: ZERO},
            ),
        ],
        evaluation_start=days[1],
        through_session=days[-1],
        session_instruments={
            m.partition_date: [Symbol(k.symbol) for k in m.instruments]
            for m in memberships
        },
        cost_config=BacktestExecutionConfig(
            commission_calc=StockACommission(
                commission_rate=ZERO,
                min_commission=ZERO,
                stamp_tax_rate=ZERO,
                transfer_fee_rate=ZERO,
            ),
            slippage_model=FixedSlippage(ZERO),
        ),
    )
    with pytest.raises(ValueError, match="holding_valuation_missing"):
        replay_paper_book(**kwargs)
    replay = replay_paper_book(
        **kwargs,
        session_nontrading_instruments={
            day: [Symbol(k.symbol) for k in keys] for day, keys in nontrading.items()
        },
    )
    suspension = replay["sessions"][1]
    assert suspension["equity"] == "10480" and suspension["cash"] == "0"
    assert suspension["fills"] == []
    assert (
        suspension["nontrading_valuations"][0]["observation_session"]
        == days[1].isoformat()
    )
    assert [
        (f["session"], f["side"], f["publication_id"]) for f in replay["fills"]
    ] == [
        (days[1].isoformat(), "buy", "buy"),
        (days[-1].isoformat(), "sell", "exit-before-halt"),
    ]
    assert replay["sessions"][-1]["cash"] == "11000"
