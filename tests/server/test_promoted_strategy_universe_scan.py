from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

from data.store import DataStore
from server.ai_runtime.contracts import content_fingerprint
from server.db import AppDatabase
from server.services.market_universe_truth import (
    MarketUniversePolicy,
    normalize_a_share_members,
)
from server.services.promoted_strategy_universe_scan import (
    PromotedStrategyUniverseScanService,
)


def _calendar(db: AppDatabase) -> list[str]:
    dates = [
        value.date().isoformat()
        for value in pd.bdate_range(end="2026-08-21", periods=80)
    ]
    dates.append("2026-08-24")
    db.upsert_market_calendar_snapshot_sync(
        {
            "exchange": "SSE",
            "year": 2026,
            "provider": "fixture",
            "status": "available",
            "trading_day_count": len(dates),
            "closed_day_count": 0,
            "source_fingerprint": "fixture-calendar",
            "days": [
                {
                    "date": market_date,
                    "is_trading_day": True,
                    "day_type": "trading",
                    "reason_code": "scheduled_trading_day",
                }
                for market_date in dates
            ],
            "limitations": [],
        }
    )
    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2026,
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        verified_by="unit-test",
    )
    return dates[:-1]


def _freeze_market(store: DataStore, market_dates: list[str]) -> list[str]:
    symbols = [f"{600000 + index:06d}" for index in range(1, 51)]
    members = normalize_a_share_members(symbols)
    store.save_market_universe_snapshot(
        trade_date="2026-08-21",
        provider_name="fixture",
        members=members,
    )
    for market_date in market_dates:
        closes = [10.0 if symbol == symbols[0] else 20.0 for symbol in symbols]
        store.ingest_market_daily_batch(
            trade_date=market_date,
            provider_name="fixture",
            bars=pd.DataFrame(
                {
                    "symbol": symbols,
                    "timestamp": [pd.Timestamp(market_date)] * len(symbols),
                    "open": closes,
                    "high": [value + 0.2 for value in closes],
                    "low": [value - 0.2 for value in closes],
                    "close": closes,
                    "volume": [1_000_000 + index for index in range(len(symbols))],
                    "amount": [
                        10_000_000 + index * 1_000 for index in range(len(symbols))
                    ],
                }
            ),
        )
    return symbols


def _formula(*, produces_signals: bool) -> dict:
    return {
        "schema_version": "karkinos.ai.formula_ast.v1",
        "entry": {
            "op": "gt" if produces_signals else "lt",
            "left": {"op": "field", "name": "close"},
            "right": {"op": "constant", "value": 0},
        },
        "exit": {
            "op": "lt" if produces_signals else "gt",
            "left": {"op": "field", "name": "close"},
            "right": {"op": "constant", "value": 11 if produces_signals else 1_000},
        },
        "position_size": {
            "op": "max_weight",
            "input": {"op": "equal_weight"},
            "value": 0.1,
        },
    }


def _service(tmp_path, *, produces_signals: bool, kill_switch_enabled: bool = False):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    market_dates = _calendar(db)
    store = DataStore(tmp_path / "market")
    symbols = _freeze_market(store, market_dates)
    strategy_id = "ai_formula_shadow:fixture-winner"
    db.upsert_strategy_promotion_state_sync(
        strategy_id=strategy_id,
        stage="paper_shadow",
        gate_status="paper_shadow_enabled",
        live_like_enabled=False,
        missing_requirements=[],
        backtest_result_id=1,
        payload={},
    )
    strategy = {
        "formula_ast": _formula(produces_signals=produces_signals),
        "formula_fingerprint": "sha256:fixture-formula",
        "selected_universe": symbols[:40],
    }
    strategy_fingerprint = content_fingerprint(strategy)

    def gate_resolver(_db, requested_strategy_id, *, as_of_date):
        assert requested_strategy_id == strategy_id
        assert as_of_date == "2026-08-24"
        return {
            "status": "pass",
            "promotion": {
                "daily_strategy_artifact_binding": {
                    "winner_candidate_id": "fixture-winner",
                    "run_id": "fixture-run",
                    "operating_constraints": {
                        "strategy_artifact_fingerprint": strategy_fingerprint,
                    },
                }
            },
        }, []

    def strategy_loader(*, candidate_id, run_id):
        assert candidate_id == "fixture-winner"
        assert run_id == "fixture-run"
        return {
            "candidate_id": candidate_id,
            "run_id": run_id,
            "strategy_artifact_fingerprint": strategy_fingerprint,
            "strategy": strategy,
        }

    service = PromotedStrategyUniverseScanService(
        db=db,
        config=SimpleNamespace(data_source="fixture", start_date="2026-04-01"),
        data_store=store,
        policy=MarketUniversePolicy(minimum_master_member_count=40),
        strategy_gate_resolver=gate_resolver,
        strategy_loader=strategy_loader,
        safety_gate_reader=lambda: {
            "default_execution_mode": "manual_confirmation",
            "manual_confirmation_required": True,
            "broker_submission_enabled": False,
            "kill_switch_enabled": kill_switch_enabled,
        },
        clock=lambda: datetime(
            2026,
            8,
            24,
            9,
            36,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ),
    )
    return db, service, symbols


def test_promoted_strategy_scans_full_stock_pool_and_persists_ranked_tasks(
    tmp_path,
) -> None:
    db, service, symbols = _service(tmp_path, produces_signals=True)
    portfolio = {
        "total_equity": 100_000,
        "symbols": [symbols[0], "012710"],
        "valuation_snapshot_id": "valuation-fixture",
    }

    first = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)
    second = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)

    assert first["status"] == "completed"
    assert first["blockers"] == []
    assert first["selected_signal_count"] == 5
    assert first["selected_signals"][0]["symbol"] == symbols[0]
    assert first["selected_signals"][0]["direction"] == "sell"
    assert {
        item["target_weight"]
        for item in first["selected_signals"]
        if item["direction"] == "buy"
    } == {0.25}
    assert [item["symbol"] for item in first["selected_signals"][1:]] == list(
        reversed(symbols[-4:])
    )
    assert first["full_market_truths"][0]["active_stock_member_count"] == 50
    assert first["full_market_truths"][0]["maintenance_symbols"] == [symbols[0]]
    assert second["reused"] is True
    assert len(db.get_action_tasks_sync(statuses=["pending"], limit=20)) == 5
    assert len(db.list_signal_journal_sync(limit=20)) == 5
    assert all(
        str(item["timestamp"]).startswith("2026-08-24T09:35:00")
        for item in first["action_tasks"]
    )


def test_complete_full_market_scan_without_signal_is_normal_no_action(tmp_path) -> None:
    db, service, _ = _service(tmp_path, produces_signals=False)

    result = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary={
            "total_equity": 100_000,
            "symbols": ["012710"],
            "valuation_snapshot_id": "valuation-fixture",
        },
    )

    assert result["status"] == "completed_no_signal"
    assert result["normal_no_signal"] is True
    assert result["blockers"] == []
    assert result["selected_signal_count"] == 0
    assert db.get_action_tasks_sync(statuses=["pending"], limit=20) == []


def test_prepared_scan_writes_nothing_until_exact_selection_is_committed(
    tmp_path,
) -> None:
    db, service, _ = _service(tmp_path, produces_signals=True)
    portfolio = {
        "total_equity": 100_000,
        "symbols": [],
        "valuation_snapshot_id": "valuation-fixture",
    }

    prepared = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary=portfolio,
        persist_actions=False,
    )

    assert prepared["status"] == "prepared"
    assert prepared["preview_only"] is True
    assert db.get_action_tasks_sync(statuses=["pending"], limit=20) == []
    assert db.list_signal_journal_sync(limit=20) == []
    assert db.get_automation_run_sync(prepared["run_id"]) is None

    committed = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary=portfolio,
        expected_signal_selection_fingerprint=prepared["signal_selection_fingerprint"],
    )

    assert committed["status"] == "completed"
    assert committed["preview_only"] is False
    assert len(db.get_action_tasks_sync(statuses=["pending"], limit=20)) == 4


def test_strategy_scan_obeys_kill_switch_before_signal_writes(tmp_path) -> None:
    db, service, _ = _service(
        tmp_path,
        produces_signals=True,
        kill_switch_enabled=True,
    )

    result = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary={
            "total_equity": 100_000,
            "symbols": [],
            "valuation_snapshot_id": "valuation-fixture",
        },
    )

    assert result["status"] == "blocked"
    assert "strategy_scan_kill_switch_not_clear" in result["blockers"]
    assert db.get_action_tasks_sync(statuses=["pending"], limit=20) == []
    assert db.list_signal_journal_sync(limit=20) == []
