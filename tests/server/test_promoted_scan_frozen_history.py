"""A deployed recursive formula keeps its frozen Dataset initialization."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

from data.research_market_data import resolve_daily_bar_receipts
from data.store import DataStore
from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
from server.services.market.market_universe_truth import (
    MarketUniversePolicy,
    normalize_a_share_members,
)
from server.services.strategy_scan.promoted_strategy_universe_scan_support import (
    evaluate_promoted_strategy_market,
    promoted_history_start,
)


def test_frozen_ema_initialization_survives_runtime_start_and_mixed_source_windows(
    tmp_path,
):
    store = DataStore(tmp_path / "market")
    dates = [
        day.date().isoformat() for day in pd.bdate_range(end="2026-08-21", periods=240)
    ]
    symbols = [str(600000 + index) for index in range(40)]
    snapshot = store.save_market_universe_snapshot(
        trade_date=dates[-1],
        provider_name="fixture",
        members=normalize_a_share_members(symbols),
        capture_started_at=datetime(
            2026, 8, 21, 15, 59, tzinfo=ZoneInfo("Asia/Shanghai")
        ),
        capture_completed_at=datetime(
            2026, 8, 21, 16, tzinfo=ZoneInfo("Asia/Shanghai")
        ),
        source_metadata=[
            {"symbol": symbol, "display_name": f"合成股票{symbol}"}
            for symbol in symbols
        ],
    )
    prices = [200.0] * 120 + [100.0] * 119 + [100.5]
    for day, price in zip(dates, prices, strict=True):
        store.ingest_market_daily_batch(
            trade_date=day,
            provider_name="fixture",
            bars=pd.DataFrame(
                {
                    "symbol": symbols,
                    "timestamp": [pd.Timestamp(day)] * len(symbols),
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 1000000,
                    "amount": price * 1000000,
                }
            ),
        )
    config = SimpleNamespace(data_source="fixture", start_date=dates[120])
    receipts = resolve_daily_bar_receipts(
        data_store=store,
        start_date=dates[0],
        end_date=dates[-1],
        config=config,
        snapshot=snapshot,
    )
    frames = store.load_market_bar_windows(
        symbols=symbols, start_date=dates[0], end_date=dates[-1], receipts=receipts
    )
    strategy = {
        "selected_universe": symbols,
        "formula_ast": {
            "schema_version": "karkinos.ai.formula_ast.v1",
            "entry": {
                "op": "gt",
                "left": {"op": "field", "name": "close"},
                "right": {
                    "op": "ema",
                    "input": {"op": "field", "name": "close"},
                    "window": 60,
                },
            },
            "exit": {
                "op": "lt",
                "left": {"op": "field", "name": "close"},
                "right": {"op": "constant", "value": 0},
            },
            "position_size": {
                "op": "max_weight",
                "input": {"op": "equal_weight"},
                "value": 0.25,
            },
        },
    }
    policy = {
        "strategy_id": "policy",
        "strategy": strategy,
        "portfolio_policy_id": FORMULA_PORTFOLIO_POLICY_ID,
        "history_start": dates[0],
    }
    human = {"strategy_id": "human", "strategy": strategy, "history_start": dates[120]}
    assert promoted_history_start([policy], config, dates[-1]) == dates[0]
    assert promoted_history_start([human], config, dates[-1]) == dates[120]
    truth, signals, blockers = evaluate_promoted_strategy_market(
        promoted=[policy, human],
        market_date=dates[-1],
        snapshot=snapshot,
        frames=frames,
        receipts=receipts,
        trading_dates=dates,
        start_date=dates[0],
        total_equity=100000,
        held_stock_symbols=[],
        policy=MarketUniversePolicy(
            minimum_master_member_count=40, minimum_history_rows=120
        ),
    )
    assert blockers == []
    assert truth["policy"]["status"] == truth["human"]["status"] == "complete"
    # 240-row EMA initialization rejects the entry; the intentionally independent
    # human source uses its existing shorter runtime window and enters.
    assert {row["strategy_id"] for row in signals} == {"human"}
    _, signals, blockers = evaluate_promoted_strategy_market(
        promoted=[policy],
        market_date=dates[-1],
        snapshot=snapshot,
        frames={s: f.iloc[120:] for s, f in frames.items()},
        receipts=receipts[120:],
        trading_dates=dates,
        start_date=dates[0],
        total_equity=100000,
        held_stock_symbols=[],
        policy=MarketUniversePolicy(
            minimum_master_member_count=40, minimum_history_rows=120
        ),
    )
    assert signals == []
    assert blockers == ["strategy_frozen_history_unavailable:policy"]
    truth, signals, blockers = evaluate_promoted_strategy_market(
        promoted=[policy, human],
        market_date=dates[-1],
        snapshot=snapshot,
        frames={s: f.iloc[120:] for s, f in frames.items()},
        receipts=receipts[120:],
        trading_dates=dates,
        start_date=dates[0],
        total_equity=100000,
        held_stock_symbols=[],
        policy=MarketUniversePolicy(
            minimum_master_member_count=40, minimum_history_rows=120
        ),
    )
    assert truth["policy"]["status"] == "blocked"
    assert truth["policy"]["blockers"] == ["strategy_frozen_history_unavailable:policy"]
    assert truth["human"]["status"] == "complete" and blockers == []
    assert {row["strategy_id"] for row in signals} == {"human"}
