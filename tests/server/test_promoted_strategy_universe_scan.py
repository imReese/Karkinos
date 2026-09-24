from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from core.types import InstrumentType
from data.store import DataStore
from server.ai_runtime.contracts import content_fingerprint
from server.db import AppDatabase
from server.projections.account_action_recommendation import (
    resolve_latest_verified_promoted_strategy_scan,
)
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactRejected,
    DailyStrategyArtifactStore,
)
from server.services.decision_portfolio_projection import portfolio_state_summary
from server.services.market_universe_truth import (
    MarketUniversePolicy,
    normalize_a_share_members,
)
from server.services.promoted_strategy_universe_scan import (
    PromotedStrategyUniverseScanService,
)
from server.services.promoted_strategy_universe_scan_support import (
    account_eligible_signals,
)


def _calendar(db: AppDatabase) -> list[str]:
    dates = [
        value.date().isoformat()
        for value in pd.bdate_range(end="2026-08-21", periods=80)
    ]
    dates.append("2026-08-24")
    trading_date_values = set(dates)
    current = date(2026, 1, 1)
    calendar_days = []
    while current.year == 2026:
        market_date = current.isoformat()
        is_trading_day = market_date in trading_date_values
        calendar_days.append(
            {
                "date": market_date,
                "is_trading_day": is_trading_day,
                "day_type": "trading" if is_trading_day else "closed",
                "reason_code": (
                    "scheduled_trading_day" if is_trading_day else "scheduled_closed"
                ),
            }
        )
        current += timedelta(days=1)
    source_fingerprint = "c" * 64
    db.upsert_market_calendar_snapshot_sync(
        {
            "exchange": "SSE",
            "year": 2026,
            "provider": "fixture",
            "status": "available",
            "trading_day_count": len(trading_date_values),
            "closed_day_count": len(calendar_days) - len(trading_date_values),
            "source_fingerprint": source_fingerprint,
            "days": calendar_days,
            "limitations": [],
        }
    )
    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2026,
        source_fingerprint=source_fingerprint,
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="d" * 64,
        verified_by="unit-test",
    )
    return dates[:-1]


def _freeze_market(
    store: DataStore,
    market_dates: list[str],
    *,
    special_symbol: str | None = None,
) -> list[str]:
    symbols = [f"{600000 + index:06d}" for index in range(1, 51)]
    if special_symbol is not None:
        symbols[-1] = special_symbol
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


def _service(
    tmp_path,
    *,
    produces_signals: bool,
    kill_switch_enabled: bool = False,
    active_strategy_count: int = 1,
    special_symbol: str | None = None,
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    market_dates = _calendar(db)
    store = DataStore(tmp_path / "market")
    symbols = _freeze_market(store, market_dates, special_symbol=special_symbol)
    strategy_ids = [
        (
            "ai_formula_shadow:fixture-winner"
            if index == 0
            else f"ai_formula_shadow:fixture-winner-{index + 1}"
        )
        for index in range(active_strategy_count)
    ]
    strategy_sources = {
        strategy_id: (
            "fixture-winner" if index == 0 else f"fixture-winner-{index + 1}",
            "fixture-run" if index == 0 else f"fixture-run-{index + 1}",
        )
        for index, strategy_id in enumerate(strategy_ids)
    }
    for strategy_id in strategy_ids:
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
        assert requested_strategy_id in strategy_sources
        assert as_of_date == "2026-08-24"
        candidate_id, run_id = strategy_sources[requested_strategy_id]
        return {
            "status": "pass",
            "promotion": {
                "daily_strategy_artifact_binding": {
                    "winner_candidate_id": candidate_id,
                    "run_id": run_id,
                    "operating_constraints": {
                        "strategy_artifact_fingerprint": strategy_fingerprint,
                    },
                }
            },
        }, []

    def strategy_loader(*, candidate_id, run_id):
        assert (candidate_id, run_id) in set(strategy_sources.values())
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


def _board_permissions(board: str, status: str) -> dict:
    return {
        "status": "current",
        "resolved_for_date": "2026-08-24",
        "evidence_fingerprint": "sha256:" + "a" * 64,
        "boards": {board: status},
    }


def test_decision_portfolio_summary_carries_exact_instrument_types() -> None:
    summary = portfolio_state_summary(
        SimpleNamespace(),
        portfolio_context={
            "portfolio": SimpleNamespace(
                cash=1_000,
                positions={
                    "600001": SimpleNamespace(market_value=100),
                    "019999": SimpleNamespace(market_value=200),
                },
                valuation_status="complete",
            ),
            "instruments": {
                "600001": SimpleNamespace(instrument_type=InstrumentType.STOCK),
                "019999": SimpleNamespace(instrument_type=InstrumentType.OPEN_END_FUND),
            },
            "valuation_snapshot": None,
            "authority": "fixture",
        },
    )

    assert summary["instrument_types"] == {
        "600001": "stock",
        "019999": "open_end_fund",
    }


def test_promoted_strategy_scans_full_stock_pool_and_persists_ranked_tasks(
    tmp_path,
) -> None:
    db, service, symbols = _service(tmp_path, produces_signals=True)
    portfolio = {
        "total_equity": 100_000,
        "cash": 100_000,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "complete",
        "symbols": [symbols[0], "019999"],
        "instrument_types": {symbols[0]: "stock", "019999": "open_end_fund"},
        "valuation_snapshot_id": "valuation-fixture",
    }

    first = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)
    second = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)

    assert first["status"] == "completed"
    assert first["blockers"] == []
    assert first["selected_signal_count"] == 5
    assert first["selected_signals"][0]["symbol"] == symbols[0]
    assert first["selected_signals"][0]["direction"] == "sell"
    assert [
        item["symbol"]
        for item in first["selected_signals"]
        if item["direction"] == "sell"
    ] == [symbols[0]]
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
    assert all(int(item["action_id"]) > 0 for item in first["action_tasks"])
    assert len(db.list_signal_journal_sync(limit=20)) == 5
    assert all(
        str(item["timestamp"]).startswith("2026-08-24T09:35:00")
        for item in first["action_tasks"]
    )
    reopened = resolve_latest_verified_promoted_strategy_scan(
        db,
        decision_date="2026-08-24",
    )
    assert reopened["verified"] is True
    assert len(reopened["action_task_ids"]) == 5


def test_chinext_research_signal_needs_current_account_permission_before_ranking(
    tmp_path,
) -> None:
    db, service, symbols = _service(
        tmp_path, produces_signals=True, special_symbol="301251"
    )
    portfolio = {
        "total_equity": 100_000,
        "cash": 100_000,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "complete",
        "symbols": [],
        "instrument_types": {},
        "valuation_snapshot_id": "valuation-fixture",
    }

    unknown = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary=portfolio,
        persist_actions=False,
    )
    assert unknown["status"] == "prepared"
    assert any(item["symbol"] == "301251" for item in unknown["raw_signals"])
    assert unknown["account_blocked_buys"] == [
        {
            "strategy_id": "ai_formula_shadow:fixture-winner",
            "symbol": "301251",
            "board": "chinext",
            "reason": "board_permission_unknown",
        }
    ]
    assert [item["symbol"] for item in unknown["selected_signals"]] == list(
        reversed(symbols[-5:-1])
    )
    assert (
        service.current_input_blockers(scan=unknown, portfolio_summary=portfolio) == []
    )

    permitted_portfolio = {
        **portfolio,
        "board_buy_permissions": _board_permissions("chinext", "enabled"),
    }
    assert "promoted_strategy_scan_current_portfolio_changed" in (
        service.current_input_blockers(
            scan=unknown, portfolio_summary=permitted_portfolio
        )
    )
    permitted = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary=permitted_portfolio,
    )
    assert permitted["status"] == "completed"
    assert permitted["selected_signals"][0]["symbol"] == "301251"
    assert permitted["account_blocked_buys"] == []
    assert (
        resolve_latest_verified_promoted_strategy_scan(db, decision_date="2026-08-24")[
            "verified"
        ]
        is True
    )


def test_cash_capacity_blocks_buys_without_erasing_held_stock_exit(tmp_path) -> None:
    db, service, symbols = _service(tmp_path, produces_signals=True)
    portfolio = {
        "total_equity": 100_000,
        "cash": 4_000,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "complete",
        "symbols": [symbols[0]],
        "instrument_types": {symbols[0]: "stock"},
        "valuation_snapshot_id": "valuation-fixture",
    }

    result = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)

    assert result["status"] == "completed"
    assert result["selected_signal_count"] == 1
    assert result["selected_signals"][0]["direction"] == "sell"
    assert result["raw_signal_count"] > 1
    assert {item["reason"] for item in result["account_blocked_buys"]} == {
        "insufficient_cash_for_one_lot"
    }
    assert len(db.get_action_tasks_sync(statuses=["pending"], limit=20)) == 1


def test_minimum_commission_is_included_in_one_lot_cash_gate() -> None:
    signal = {
        "strategy_id": "ai_formula_shadow:fixture-winner",
        "symbol": "600001",
        "direction": "buy",
        "ranking_liquidity": 1_000_000,
        "frozen_close": 1.0,
    }
    portfolio = {
        "cash": 132,
        "total_equity": 1_000,
        "fact_authority": "persisted_valuation_snapshot",
    }
    inputs = {
        "config": SimpleNamespace(),
        "decision_date": "2026-08-24",
        "policy": MarketUniversePolicy(minimum_master_member_count=40),
        "cash_buffer_ratio": Decimal("0.03"),
    }

    selected, blocked = account_eligible_signals(
        [signal], portfolio=portfolio, **inputs
    )
    assert selected == []
    assert blocked[0]["reason"] == "insufficient_cash_for_one_lot"

    affordable, unblocked = account_eligible_signals(
        [signal], portfolio={**portfolio, "cash": 136}, **inputs
    )
    assert affordable == [signal]
    assert unblocked == []


@pytest.mark.parametrize(
    ("cash", "fact_authority"),
    [(None, "persisted_valuation_snapshot"), (100_000, "legacy_fallback")],
)
def test_untrusted_cash_is_account_blocked_not_a_normal_no_signal_day(
    tmp_path, cash, fact_authority
) -> None:
    db, service, _ = _service(tmp_path, produces_signals=True)
    portfolio = {
        "total_equity": 100_000,
        "cash": cash,
        "fact_authority": fact_authority,
        "valuation_status": "complete",
        "symbols": [],
        "instrument_types": {},
        "valuation_snapshot_id": "valuation-fixture",
    }

    result = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)

    assert result["status"] == "completed_no_signal"
    assert result["normal_no_signal"] is False
    assert result["raw_signal_count"] > 0
    assert result["selected_signal_count"] == 0
    assert {item["reason"] for item in result["account_blocked_buys"]} == {
        "cash_evidence_missing"
    }
    assert db.get_action_tasks_sync(statuses=["pending"], limit=20) == []


def test_star_buy_stays_blocked_until_downstream_trade_unit_support(tmp_path) -> None:
    _, service, _ = _service(tmp_path, produces_signals=True, special_symbol="688001")
    portfolio = {
        "total_equity": 100_000,
        "cash": 100_000,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "complete",
        "symbols": [],
        "instrument_types": {},
        "valuation_snapshot_id": "valuation-fixture",
        "board_buy_permissions": _board_permissions("star", "enabled"),
    }

    result = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary=portfolio,
        persist_actions=False,
    )

    assert any(item["symbol"] == "688001" for item in result["raw_signals"])
    assert result["account_blocked_buys"][0] == {
        "strategy_id": "ai_formula_shadow:fixture-winner",
        "symbol": "688001",
        "board": "star",
        "reason": "unsupported_trade_unit",
    }
    assert all(item["symbol"] != "688001" for item in result["selected_signals"])


@pytest.mark.parametrize(
    ("calendar_failure", "expected_blocker"),
    [
        ("missing_history", "verified_market_history_window_incomplete"),
        ("missing_decision", "strategy_scan_decision_date_not_verified_trading_day"),
        ("stale_verification", "strategy_scan_decision_date_not_verified_trading_day"),
    ],
)
def test_scan_calendar_failure_blocks_new_and_prepared_recommendations(
    tmp_path, monkeypatch, calendar_failure, expected_blocker
) -> None:
    db, service, _ = _service(tmp_path, produces_signals=True)
    portfolio = {
        "total_equity": 100_000,
        "cash": 100_000,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "complete",
        "symbols": [],
        "instrument_types": {},
        "valuation_snapshot_id": "valuation-fixture",
    }
    prepared = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary=portfolio,
        persist_actions=False,
    )
    assert prepared["status"] == "prepared"
    assert (
        service.current_input_blockers(scan=prepared, portfolio_summary=portfolio) == []
    )

    if calendar_failure == "missing_history":
        service._config.start_date = "2025-01-02"
    else:
        read_calendar = db.get_market_calendar_snapshot_sync

        def unavailable_calendar(**kwargs):
            if calendar_failure == "missing_decision":
                return None
            return {
                **read_calendar(**kwargs),
                "verification_source_fingerprint": "a" * 64,
            }

        monkeypatch.setattr(
            db, "get_market_calendar_snapshot_sync", unavailable_calendar
        )

    result = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)

    assert result["status"] == "blocked"
    assert expected_blocker in result["blockers"]
    assert result["normal_no_signal"] is False
    assert result["selected_signal_count"] == 0
    assert "promoted_strategy_scan_current_market_replay_failed" in (
        service.current_input_blockers(scan=prepared, portfolio_summary=portfolio)
    )
    assert db.get_action_tasks_sync(statuses=["pending"], limit=20) == []
    assert db.list_signal_journal_sync(limit=20) == []


def test_multi_strategy_exit_for_same_account_holding_fails_closed(
    tmp_path,
) -> None:
    db, service, symbols = _service(
        tmp_path,
        produces_signals=True,
        active_strategy_count=2,
    )
    portfolio = {
        "total_equity": 100_000,
        "valuation_status": "complete",
        "symbols": [symbols[0]],
        "instrument_types": {symbols[0]: "stock"},
        "valuation_snapshot_id": "valuation-fixture",
    }

    result = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary=portfolio,
    )

    assert result["status"] == "blocked"
    assert result["blockers"] == [
        "promoted_strategy_exit_signal_conflict:"
        f"{symbols[0]}:ai_formula_shadow:fixture-winner,"
        "ai_formula_shadow:fixture-winner-2"
    ]
    assert [
        item["strategy_id"]
        for item in result["selected_signals"]
        if item["direction"] == "sell" and item["symbol"] == symbols[0]
    ] == [
        "ai_formula_shadow:fixture-winner",
        "ai_formula_shadow:fixture-winner-2",
    ]
    assert result["action_tasks"] == []
    assert result["creates_oms_order"] is False
    assert result["submits_broker_order"] is False
    assert db.get_action_tasks_sync(statuses=["pending"], limit=20) == []
    assert db.list_signal_journal_sync(limit=20) == []
    assert db.list_orders_sync(limit=20) == []
    assert db.list_oms_orders_sync(limit=20) == []
    reopened = resolve_latest_verified_promoted_strategy_scan(
        db,
        decision_date="2026-08-24",
    )
    assert reopened["verified"] is True
    assert reopened["status"] == "blocked"
    assert reopened["blockers"] == result["blockers"]
    assert reopened["action_task_ids"] == []
    assert (
        service.current_input_blockers(
            scan=reopened,
            portfolio_summary=portfolio,
        )
        == result["blockers"]
    )


def test_complete_full_market_scan_without_signal_is_normal_no_action(tmp_path) -> None:
    db, service, _ = _service(tmp_path, produces_signals=False)

    result = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary={
            "total_equity": 100_000,
            "valuation_status": "complete",
            "symbols": ["019999"],
            "instrument_types": {"019999": "open_end_fund"},
            "valuation_snapshot_id": "valuation-fixture",
        },
    )

    assert result["status"] == "completed_no_signal"
    assert result["normal_no_signal"] is True
    assert result["blockers"] == []
    assert result["selected_signal_count"] == 0
    assert db.get_action_tasks_sync(statuses=["pending"], limit=20) == []


def test_held_stock_outside_active_universe_blocks_instead_of_no_action(
    tmp_path,
) -> None:
    db, service, _ = _service(tmp_path, produces_signals=False)

    result = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary={
            "total_equity": 100_000,
            "valuation_status": "complete",
            "symbols": ["000001", "019999"],
            "instrument_types": {
                "000001": "stock",
                "019999": "open_end_fund",
            },
            "valuation_snapshot_id": "valuation-fixture",
        },
    )

    assert result["status"] == "blocked"
    assert result["normal_no_signal"] is False
    assert any(
        item.endswith("holding_outside_active_stock_universe:000001")
        for item in result["blockers"]
    )
    assert result["portfolio_binding"]["held_stock_count"] == 1
    assert db.get_action_tasks_sync(statuses=["pending"], limit=20) == []


def test_portfolio_instrument_type_must_be_authoritative_before_scan(tmp_path) -> None:
    db, service, symbols = _service(tmp_path, produces_signals=False)

    result = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary={
            "total_equity": 100_000,
            "valuation_status": "complete",
            "symbols": [symbols[0]],
            "instrument_types": {},
            "valuation_snapshot_id": "valuation-fixture",
        },
    )

    assert result["status"] == "blocked"
    assert f"portfolio_instrument_type_unresolved:{symbols[0]}" in result["blockers"]
    assert result["normal_no_signal"] is False
    assert db.get_action_tasks_sync(statuses=["pending"], limit=20) == []


def test_persisted_scan_is_rejected_after_current_input_drift(tmp_path) -> None:
    db, service, _ = _service(tmp_path, produces_signals=False)
    portfolio = {
        "total_equity": 100_000,
        "valuation_status": "complete",
        "symbols": ["019999"],
        "instrument_types": {"019999": "open_end_fund"},
        "valuation_snapshot_id": "valuation-fixture",
    }
    scan = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary=portfolio,
    )

    assert (
        service.current_input_blockers(
            scan=scan,
            portfolio_summary=portfolio,
        )
        == []
    )

    changed_portfolio = {**portfolio, "total_equity": 100_001}
    assert "promoted_strategy_scan_current_portfolio_changed" in (
        service.current_input_blockers(
            scan=scan,
            portfolio_summary=changed_portfolio,
        )
    )

    prior_gate_resolver = service._strategy_gate_resolver

    def changed_gate_resolver(*args, **kwargs):
        gate, blockers = prior_gate_resolver(*args, **kwargs)
        return {**gate, "current_revision": "changed"}, blockers

    service._strategy_gate_resolver = changed_gate_resolver
    assert "promoted_strategy_scan_current_strategy_binding_changed" in (
        service.current_input_blockers(
            scan=scan,
            portfolio_summary=portfolio,
        )
    )

    service._strategy_gate_resolver = prior_gate_resolver
    service._safety_gate_reader = lambda: {
        "default_execution_mode": "manual_confirmation",
        "manual_confirmation_required": True,
        "broker_submission_enabled": False,
        "kill_switch_enabled": True,
    }
    safety_blockers = service.current_input_blockers(
        scan=scan,
        portfolio_summary=portfolio,
    )
    assert "promoted_strategy_scan_current_safety_gate_blocked" in safety_blockers
    assert "promoted_strategy_scan_safety_gate_changed" in safety_blockers


def test_persisted_scan_rejects_same_id_universe_payload_tamper(tmp_path) -> None:
    _, service, _ = _service(tmp_path, produces_signals=False)
    portfolio = {
        "total_equity": 100_000,
        "valuation_status": "complete",
        "symbols": ["019999"],
        "instrument_types": {"019999": "open_end_fund"},
        "valuation_snapshot_id": "valuation-fixture",
    }
    scan = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary=portfolio,
    )
    with sqlite3.connect(service._data_store._meta_path) as conn:
        row = conn.execute(
            "SELECT snapshot_json FROM market_universe_snapshots WHERE trade_date = ?",
            ("2026-08-21",),
        ).fetchone()
        assert row is not None
        payload = json.loads(str(row[0]))
        payload["members"] = payload["members"][:-1]
        conn.execute(
            "UPDATE market_universe_snapshots SET snapshot_json = ? WHERE trade_date = ?",
            (json.dumps(payload), "2026-08-21"),
        )

    blockers = service.current_input_blockers(
        scan=scan,
        portfolio_summary=portfolio,
    )

    assert "promoted_strategy_scan_current_market_replay_failed" in blockers


def test_persisted_scan_rejects_current_evaluation_policy_change(tmp_path) -> None:
    _, service, _ = _service(tmp_path, produces_signals=False)
    portfolio = {
        "total_equity": 100_000,
        "valuation_status": "complete",
        "symbols": ["019999"],
        "instrument_types": {"019999": "open_end_fund"},
        "valuation_snapshot_id": "valuation-fixture",
    }
    scan = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary=portfolio,
    )
    service._policy = MarketUniversePolicy(
        minimum_master_member_count=40,
        allocation_slots=5,
    )

    blockers = service.current_input_blockers(
        scan=scan,
        portfolio_summary=portfolio,
    )

    assert "promoted_strategy_scan_evaluation_policy_changed" in blockers


def test_prepared_scan_writes_nothing_until_exact_selection_is_committed(
    tmp_path,
) -> None:
    db, service, _ = _service(tmp_path, produces_signals=True)
    portfolio = {
        "total_equity": 100_000,
        "cash": 100_000,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "complete",
        "symbols": [],
        "instrument_types": {},
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
            "valuation_status": "complete",
            "symbols": [],
            "instrument_types": {},
            "valuation_snapshot_id": "valuation-fixture",
        },
    )

    assert result["status"] == "blocked"
    assert "strategy_scan_kill_switch_not_clear" in result["blockers"]
    assert db.get_action_tasks_sync(statuses=["pending"], limit=20) == []
    assert db.list_signal_journal_sync(limit=20) == []


def test_strategy_scan_requires_complete_valuation_before_signal_writes(
    tmp_path,
) -> None:
    db, service, _ = _service(tmp_path, produces_signals=True)

    result = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary={
            "total_equity": 100_000,
            "valuation_status": "degraded",
            "symbols": [],
            "instrument_types": {},
            "valuation_snapshot_id": "valuation-fixture",
        },
    )

    assert result["status"] == "blocked"
    assert "valuation_snapshot_not_complete" in result["blockers"]
    assert result["portfolio_binding"]["valuation_status"] == "degraded"
    assert db.get_action_tasks_sync(statuses=["pending"], limit=20) == []
    assert db.list_signal_journal_sync(limit=20) == []


def test_strategy_loader_accepts_only_verified_normalized_source_fallback(
    tmp_path,
    monkeypatch,
) -> None:
    service = object.__new__(PromotedStrategyUniverseScanService)
    service._db = SimpleNamespace(path=tmp_path / "app.db")
    expected = {
        "candidate_id": "normalized-candidate",
        "run_id": "normalized-run",
        "strategy_artifact_fingerprint": "sha256:verified-source",
        "strategy": {"formula_ast": _formula(produces_signals=True)},
    }

    def reject_legacy_winner(self, *, candidate_id, run_id):
        raise DailyStrategyArtifactRejected("candidate_is_not_verified_daily_winner")

    def load_normalized_source(self, *, candidate_id, run_id):
        assert candidate_id == "normalized-candidate"
        assert run_id == "normalized-run"
        return expected

    monkeypatch.setattr(
        DailyStrategyArtifactStore,
        "load_verified_winner_strategy",
        reject_legacy_winner,
    )
    monkeypatch.setattr(
        DailyStrategyArtifactStore,
        "require_verified_research_candidate",
        load_normalized_source,
    )

    assert (
        service._load_strategy(
            candidate_id="normalized-candidate",
            run_id="normalized-run",
        )
        == expected
    )
