from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

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


def test_full_market_universe_truth_verifies_session_state_before_excluding_untraded_stocks(
    tmp_path,
) -> None:
    from server.services.market.market_universe_truth import (
        build_full_market_universe_truth,
    )

    store = DataStore(tmp_path / "market")
    symbols = _symbols()  # 1000 symbols: 600000 .. 600999
    symbol_b = "600999"
    active_symbols_21 = [s for s in symbols if s != symbol_b]

    # Save bars for all symbols up to 2026-08-20 (80 bars)
    full_bars_20 = _bars(end="2026-08-20")
    frames = {s: full_bars_20.copy() for s in symbols}

    # Bars on 2026-08-21: only for active_symbols_21 (omits symbol_b)
    bar_21 = pd.DataFrame(
        {
            "symbol": active_symbols_21,
            "timestamp": [pd.Timestamp("2026-08-21")] * len(active_symbols_21),
            "open": [10.0] * len(active_symbols_21),
            "high": [10.1] * len(active_symbols_21),
            "low": [9.9] * len(active_symbols_21),
            "close": [10.0] * len(active_symbols_21),
            "volume": [1_000_000] * len(active_symbols_21),
            "amount": [10_000_000.0] * len(active_symbols_21),
        }
    )
    receipt_20 = store.ingest_market_daily_batch(
        trade_date="2026-08-20",
        provider_name="unit_fixture",
        bars=pd.DataFrame(
            {
                "symbol": symbols,
                "timestamp": [pd.Timestamp("2026-08-20")] * len(symbols),
                "open": [10.0] * len(symbols),
                "high": [10.1] * len(symbols),
                "low": [9.9] * len(symbols),
                "close": [10.0] * len(symbols),
                "volume": [1_000_000] * len(symbols),
                "amount": [10_000_000.0] * len(symbols),
            }
        ),
    )
    receipt_21_omitted = store.ingest_market_daily_batch(
        trade_date="2026-08-21",
        provider_name="unit_fixture",
        bars=bar_21,
    )
    receipts_omitted = [receipt_20, receipt_21_omitted]
    required_dates = ["2026-08-20", "2026-08-21"]

    # Add 2026-08-21 bar to frames for active_symbols_21
    row_21 = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-08-21"),
                "open": 10.0,
                "high": 10.1,
                "low": 9.9,
                "close": 10.0,
                "volume": 1_000_000,
                "amount": 10_000_000.0,
            }
        ]
    )
    for s in active_symbols_21:
        frames[s] = pd.concat([frames[s], row_21], ignore_index=True)

    # Base source metadata giving each symbol a valid display name and active listing
    capture_time = datetime(2026, 8, 21, 15, tzinfo=timezone.utc)
    base_source_metadata = [
        {"symbol": s, "display_name": f"股票{s}", "list_status": "L"} for s in symbols
    ]

    # -------------------------------------------------------------------------
    # Case 1: symbol_b omitted from provider receipt, status unknown (no trade_status)
    # -> Must NOT guess non-trading; B is market_date_missing; universe is blocked.
    # -------------------------------------------------------------------------
    snap_unknown = store.save_market_universe_snapshot(
        trade_date="2026-08-21",
        provider_name="unit_fixture",
        members=normalize_a_share_members(symbols),
        source_metadata=base_source_metadata,
        capture_started_at=capture_time,
        capture_completed_at=capture_time,
    )
    truth_unknown = build_full_market_universe_truth(
        snapshot=snap_unknown,
        frames=frames,
        receipts=receipts_omitted,
        required_trading_dates=required_dates,
        start_date="2026-04-01",
        end_date="2026-08-21",
        initial_cash=100_000.0,
        target_weight=0.25,
        held_symbols=[symbol_b],
        minimum_history_rows=60,
    )
    assert truth_unknown["status"] == "blocked"
    assert "full_market_evidence_incomplete" in truth_unknown["blockers"]
    assert truth_unknown["coverage"]["unresolved"] >= 1
    assert any(
        f"holding_exit_evidence_incomplete:{symbol_b}:market_date_missing" in b
        for b in truth_unknown["blockers"]
    )
    assert truth_unknown["excluded_reason_counts"].get("market_date_missing") == 1

    from data.store import normalize_stock_master_metadata

    def _snapshot_with_metadata(base_snapshot, source_meta, capture_ids=()):
        core = dict(base_snapshot)
        core.pop("snapshot_id", None)
        core["member_metadata"] = normalize_stock_master_metadata(
            source_meta, base_snapshot["members"]
        )
        if capture_ids:
            core["source_capture_ids"] = list(capture_ids)
        snap_id = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    core, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
        )
        return {**core, "snapshot_id": snap_id}

    # -------------------------------------------------------------------------
    # Case 2: symbol_b has trade_status="1" (trading) with matching session and capture ID
    # but still lacks the target-date bar -> Must remain blocked; forbidden to classify as non-trading.
    # -------------------------------------------------------------------------
    capture_id = "sha256:" + "a" * 64
    source_meta_trading = [
        {"symbol": s, "display_name": f"股票{s}", "list_status": "L"}
        for s in active_symbols_21
    ] + [
        {
            "symbol": symbol_b,
            "display_name": f"股票{symbol_b}",
            "list_status": "L",
            "trade_status": "1",
            "status_session_date": "2026-08-21",
            "status_capture_id": capture_id,
        }
    ]
    snap_trading = _snapshot_with_metadata(
        snap_unknown, source_meta_trading, capture_ids=[capture_id]
    )
    truth_trading = build_full_market_universe_truth(
        snapshot=snap_trading,
        frames=frames,
        receipts=receipts_omitted,
        required_trading_dates=required_dates,
        start_date="2026-04-01",
        end_date="2026-08-21",
        initial_cash=100_000.0,
        target_weight=0.25,
        held_symbols=[symbol_b],
        minimum_history_rows=60,
    )
    assert truth_trading["status"] == "blocked"
    assert "full_market_evidence_incomplete" in truth_trading["blockers"]
    assert truth_trading["coverage"]["unresolved"] >= 1
    assert truth_trading["excluded_reason_counts"].get("market_date_missing") == 1

    # -------------------------------------------------------------------------
    # Case 3: symbol_b has matching explicit suspension evidence (trade_status="0")
    # -> Legally excluded as nontrading_session_excluded; 0 unresolved; complete!
    # -------------------------------------------------------------------------
    source_meta_halted = [
        {"symbol": s, "display_name": f"股票{s}", "list_status": "L"}
        for s in active_symbols_21
    ] + [
        {
            "symbol": symbol_b,
            "display_name": f"股票{symbol_b}",
            "list_status": "L",
            "trade_status": "0",
            "status_session_date": "2026-08-21",
            "status_capture_id": capture_id,
        }
    ]
    snap_halted = _snapshot_with_metadata(
        snap_unknown, source_meta_halted, capture_ids=[capture_id]
    )
    truth_halted = build_full_market_universe_truth(
        snapshot=snap_halted,
        frames=frames,
        receipts=receipts_omitted,
        required_trading_dates=required_dates,
        start_date="2026-04-01",
        end_date="2026-08-21",
        initial_cash=100_000.0,
        target_weight=0.25,
        held_symbols=[],  # no held symbol blocker
        minimum_history_rows=60,
    )
    assert truth_halted["status"] == "complete"
    assert truth_halted["coverage"]["unresolved"] == 0
    assert (
        truth_halted["excluded_reason_counts"].get("nontrading_session_excluded") == 1
    )
    assert "market_date_missing" not in truth_halted["excluded_reason_counts"]

    # -------------------------------------------------------------------------
    # Case 4: Receipt contains symbol_b, but local frames missing symbol_b's 2026-08-21 bar
    # -> Must block with market_date_missing.
    # -------------------------------------------------------------------------
    bar_21_with_b = pd.concat(
        [
            bar_21,
            pd.DataFrame(
                [
                    {
                        "symbol": symbol_b,
                        "timestamp": pd.Timestamp("2026-08-21"),
                        "open": 10.0,
                        "high": 10.1,
                        "low": 9.9,
                        "close": 10.0,
                        "volume": 1_000_000,
                        "amount": 10_000_000.0,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    receipt_21_with_b = store.ingest_market_daily_batch(
        trade_date="2026-08-21",
        provider_name="unit_fixture_full",
        bars=bar_21_with_b,
    )
    truth_local_missing = build_full_market_universe_truth(
        snapshot=snap_unknown,
        frames=frames,  # frames[symbol_b] still lacks 2026-08-21
        receipts=[receipt_20, receipt_21_with_b],
        required_trading_dates=required_dates,
        start_date="2026-04-01",
        end_date="2026-08-21",
        initial_cash=100_000.0,
        target_weight=0.25,
        held_symbols=[symbol_b],
        minimum_history_rows=60,
    )
    assert truth_local_missing["status"] == "blocked"
    assert "full_market_evidence_incomplete" in truth_local_missing["blockers"]
    assert truth_local_missing["coverage"]["unresolved"] >= 1
    assert truth_local_missing["excluded_reason_counts"].get("market_date_missing") == 1

    # -------------------------------------------------------------------------
    # Case 5: Complete universe: symbol_b has 2026-08-21 bar in frame as well
    # -> Must pass with status complete and 0 unresolved.
    # -------------------------------------------------------------------------
    frames_complete = {
        **frames,
        symbol_b: pd.concat([frames[symbol_b], row_21], ignore_index=True),
    }
    truth_complete = build_full_market_universe_truth(
        snapshot=snap_unknown,
        frames=frames_complete,
        receipts=[receipt_20, receipt_21_with_b],
        required_trading_dates=required_dates,
        start_date="2026-04-01",
        end_date="2026-08-21",
        initial_cash=100_000.0,
        target_weight=0.25,
        held_symbols=[symbol_b],
        minimum_history_rows=60,
    )
    assert truth_complete["status"] == "complete"
    assert truth_complete["coverage"]["unresolved"] == 0
    assert not truth_complete["blockers"]
