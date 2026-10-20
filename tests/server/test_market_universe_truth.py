from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from core.types import BarFrequency, InstrumentType, Symbol
from data.store import DataStore
from server.services.market.market_universe_truth import (
    MarketUniversePolicy,
    MarketUniverseRejected,
    build_market_universe_truth,
    market_master_buy_instruments,
    normalize_a_share_members,
    preliminary_research_panel_symbols,
)


def test_new_master_applies_observed_listing_status_and_dates_without_guessing(
    tmp_path,
):
    from datetime import timezone

    store = DataStore(tmp_path)
    symbols = [f"60000{index}" for index in range(8)]
    now = datetime(2026, 8, 24, 8, tzinfo=timezone.utc)
    master = store.save_market_universe_snapshot(
        trade_date="2026-08-21",
        provider_name="fixture",
        members=normalize_a_share_members(symbols),
        capture_started_at=now,
        capture_completed_at=now,
        source_metadata=[
            {
                "symbol": symbols[0],
                "display_name": "正常股票",
                "list_status": "L",
                "list_date": "20200821",
            },
            {"symbol": symbols[1], "display_name": "历史公司", "list_status": "D"},
            {"symbol": symbols[2], "display_name": "暂缓上市", "list_status": "P"},
            {
                "symbol": symbols[3],
                "display_name": "下日上市",
                "list_status": "L",
                "list_date": "20260824",
            },
            # Missing status/date keeps the previously supported observed-name
            # path; missing price rows never become inactive-listing evidence.
            {"symbol": symbols[4], "display_name": "状态未提供"},
            {
                "symbol": symbols[5],
                "display_name": "同日上市",
                "list_status": "L",
                "list_date": "20260821",
            },
            {
                "symbol": symbols[6],
                "display_name": "拟合并公司",
                "list_status": "D",
                "delist_date": "20260824",
            },
            {
                "symbol": symbols[7],
                "display_name": "当日退市",
                "list_status": "L",
                "delist_date": "20260821",
            },
        ],
    )
    policy = MarketUniversePolicy(minimum_master_member_count=1)
    assert [key.symbol for key in market_master_buy_instruments(master, policy)] == [
        symbols[0],
        symbols[4],
        symbols[5],
        symbols[6],
    ]
    assert len(master["members"]) == 8
    assert (
        len(market_master_buy_instruments(master, MarketUniversePolicy.legacy())) == 8
    )
    assert all("delist_date" not in row for row in master["member_metadata"][:6])
    assert master["member_metadata"][-2]["delist_date"] == "2026-08-24"
    assert (
        store.get_market_universe_snapshot(snapshot_id=master["snapshot_id"]) == master
    )


def _symbols() -> list[str]:
    return [f"{600000 + index:06d}" for index in range(1_000)]


def _bars(*, end: str = "2026-08-21", close: float = 10.0) -> pd.DataFrame:
    dates = pd.bdate_range(end=end, periods=80)
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": [close] * len(dates),
            "high": [close * 1.01] * len(dates),
            "low": [close * 0.99] * len(dates),
            "close": [close] * len(dates),
            "volume": [1_000_000] * len(dates),
            "amount": [close * 1_000_000] * len(dates),
        }
    )


def _snapshot(store: DataStore) -> dict[str, object]:
    return store.save_market_universe_snapshot(
        trade_date="2026-08-21",
        provider_name="unit_fixture",
        members=normalize_a_share_members(_symbols()),
    )


def test_market_universe_snapshot_is_immutable_stock_only_and_content_addressed(
    tmp_path,
) -> None:
    store = DataStore(tmp_path / "market")
    members = normalize_a_share_members([*_symbols(), "012710", "510300", "BJ.430001"])

    first = store.save_market_universe_snapshot(
        trade_date="2026-08-21",
        provider_name="unit_fixture",
        members=members,
    )
    replay = store.save_market_universe_snapshot(
        trade_date="2026-08-21",
        provider_name="unit_fixture",
        members=list(reversed(members)),
    )

    assert first == replay
    assert first["member_count"] == 1_000
    assert all(member["asset_class"] == "stock" for member in first["members"])
    assert {member["exchange"] for member in first["members"]} == {"SSE"}
    assert first["snapshot_id"].startswith("sha256:")
    with pytest.raises(ValueError, match="market_universe_snapshot_conflict"):
        store.save_market_universe_snapshot(
            trade_date="2026-08-21",
            provider_name="unit_fixture",
            members=members[:-1],
        )


def test_research_panel_is_exactly_40_lot_feasible_and_deterministic(tmp_path) -> None:
    store = DataStore(tmp_path / "market")
    snapshot = _snapshot(store)
    policy = MarketUniversePolicy.legacy()
    preliminary = preliminary_research_panel_symbols(snapshot, policy=policy)
    assert len(preliminary) == 160
    for symbol in preliminary:
        store.save_bars(
            Symbol(symbol),
            BarFrequency.DAILY,
            _bars(),
            provider_name="unit_fixture",
            data_source="unit_fixture",
            adjustment_mode="none",
            instrument_type=InstrumentType.STOCK,
        )

    first = build_market_universe_truth(
        data_store=store,
        snapshot=snapshot,
        start_date="2026-04-01",
        end_date="2026-08-21",
        initial_cash=100_000,
        policy=policy,
    )
    second = build_market_universe_truth(
        data_store=store,
        snapshot=snapshot,
        start_date="2026-04-01",
        end_date="2026-08-21",
        initial_cash=100_000,
        policy=policy,
    )

    assert first == second
    panel = first["research_panel"]
    assert panel["member_count"] == 40
    assert len(panel["symbols"]) == len(set(panel["symbols"])) == 40
    assert panel["contains_absolute_balance"] is False
    assert first["position_sizing_policy"] == {
        "schema_version": "karkinos.research_position_sizing_policy.v1",
        "allocation_slots": 4,
        "target_weight": "0.25",
        "lot_size": 100,
        "fee_buffer_rate": "0.01",
        "model_controls_position_size": False,
        "capital_binding_fingerprint": panel["capital_binding_fingerprint"],
    }
    assert first["etf_or_fund_candidate_count"] == 0


def test_research_panel_fails_closed_before_model_when_one_lot_is_not_feasible(
    tmp_path,
) -> None:
    store = DataStore(tmp_path / "market")
    snapshot = _snapshot(store)
    preliminary = preliminary_research_panel_symbols(
        snapshot,
        policy=MarketUniversePolicy.legacy(),
    )
    for index, symbol in enumerate(preliminary):
        store.save_bars(
            Symbol(symbol),
            BarFrequency.DAILY,
            _bars(close=10.0 if index < 39 else 1_000.0),
            provider_name="unit_fixture",
            data_source="unit_fixture",
            adjustment_mode="none",
            instrument_type=InstrumentType.STOCK,
        )

    with pytest.raises(MarketUniverseRejected, match="research_panel_incomplete"):
        build_market_universe_truth(
            data_store=store,
            snapshot=snapshot,
            start_date="2026-04-01",
            end_date="2026-08-21",
            initial_cash=100_000,
            policy=MarketUniversePolicy.legacy(),
        )


def test_market_universe_rejects_previous_day_or_short_history(tmp_path) -> None:
    store = DataStore(tmp_path / "market")
    snapshot = _snapshot(store)
    preliminary = preliminary_research_panel_symbols(
        snapshot,
        policy=MarketUniversePolicy(),
    )
    for symbol in preliminary:
        store.save_bars(
            Symbol(symbol),
            BarFrequency.DAILY,
            _bars(end="2026-08-20").tail(20),
            provider_name="unit_fixture",
            data_source="unit_fixture",
            adjustment_mode="none",
            instrument_type=InstrumentType.STOCK,
        )

    with pytest.raises(MarketUniverseRejected, match="research_panel_incomplete"):
        build_market_universe_truth(
            data_store=store,
            snapshot=snapshot,
            start_date="2026-04-01",
            end_date="2026-08-21",
            initial_cash=100_000,
        )


def test_research_panel_hard_filters_the_full_stock_directory(tmp_path) -> None:
    store = DataStore(tmp_path / "market")
    snapshot = _snapshot(store)
    policy = MarketUniversePolicy.legacy()
    preliminary = set(preliminary_research_panel_symbols(snapshot, policy=policy))
    eligible_outside_preliminary = [
        symbol for symbol in _symbols() if symbol not in preliminary
    ][:40]
    for symbol in eligible_outside_preliminary:
        store.save_bars(
            Symbol(symbol),
            BarFrequency.DAILY,
            _bars(),
            provider_name="unit_fixture",
            data_source="unit_fixture",
            adjustment_mode="none",
            instrument_type=InstrumentType.STOCK,
        )

    result = build_market_universe_truth(
        data_store=store,
        snapshot=snapshot,
        start_date="2026-04-01",
        end_date="2026-08-21",
        initial_cash=100_000,
        policy=policy,
    )

    assert result["research_screened_stock_count"] == 1_000
    assert result["research_eligible_count"] == 40
    assert set(result["research_panel"]["symbols"]) == set(eligible_outside_preliminary)
