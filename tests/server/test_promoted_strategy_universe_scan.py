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
from server.services.account.valuation_snapshot import build_current_valuation_snapshot
from server.services.ai_shadow.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactRejected,
    DailyStrategyArtifactStore,
)
from server.services.decision.decision_portfolio_projection import (
    portfolio_state_summary,
)
from server.services.market_universe_truth import (
    MarketUniversePolicy,
    normalize_a_share_members,
)
from server.services.strategy_scan.promoted_strategy_universe_scan import (
    PromotedStrategyUniverseScanService,
)
from server.services.strategy_scan.promoted_strategy_universe_scan_support import (
    account_eligible_signals,
)


def _valuation_id(db):
    return build_current_valuation_snapshot(
        db,
        persist=False,
        now=datetime(2026, 8, 24, 9, 36, tzinfo=ZoneInfo("Asia/Shanghai")),
    )["snapshot_id"]


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
    snapshot_provider: str = "fixture",
    daily_provider: str = "fixture",
) -> list[str]:
    symbols = [f"{600000 + index:06d}" for index in range(1, 51)]
    if special_symbol is not None:
        symbols[-1] = special_symbol
    members = normalize_a_share_members(symbols)
    store.save_market_universe_snapshot(
        trade_date="2026-08-21",
        provider_name=snapshot_provider,
        members=members,
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
    for market_date in market_dates:
        closes = [10.0 if symbol == symbols[0] else 20.0 for symbol in symbols]
        store.ingest_market_daily_batch(
            trade_date=market_date,
            provider_name=daily_provider,
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
    snapshot_provider: str = "fixture",
    daily_provider: str = "fixture",
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    market_dates = _calendar(db)
    store = DataStore(tmp_path / "market")
    symbols = _freeze_market(
        store,
        market_dates,
        special_symbol=special_symbol,
        snapshot_provider=snapshot_provider,
        daily_provider=daily_provider,
    )
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


def _board_review(board, status):
    return {
        "source": "self_reported_broker_account",
        "reviewed_by": "human:fixture",
        "reviewed_at": "2026-08-24T09:00:00+08:00",
        "boards": {board: status},
    }


@pytest.mark.parametrize("change", ["revoke", "generation", "pause"])
@pytest.mark.parametrize("source_kind", ["policy", "human"])
def test_authority_change_after_evaluation_is_checked_before_atomic_task_write(
    tmp_path, monkeypatch, change, source_kind
):
    from uuid import uuid4

    from server.persistence.ai_shadow_research import ShadowResearchStore
    from tests.server.test_recommendation_publication import _grant

    db, service, symbols = _service(tmp_path, produces_signals=True)
    store = ShadowResearchStore(db.path)
    store.init()
    grant = _grant()
    store.configure_publication_grant(
        policy=grant, expected_generation=None, now="2026-08-24T01:35:00+00:00"
    )
    strategy_id = "ai_formula_shadow:fixture-winner"
    payload = (
        {
            "decision_source": "policy",
            "publication_decision": {
                "grant_id": grant["grant_id"],
                "generation": grant["generation"],
            },
        }
        if source_kind == "policy"
        else {
            "human_review": {
                "reviewer": "human:fixture-owner",
                "review_note": "Explicit fixture source",
                "confirmation_recorded": True,
            }
        }
    )
    db.upsert_strategy_promotion_state_sync(
        strategy_id=strategy_id,
        stage="paper_shadow",
        gate_status="paper_shadow_enabled",
        live_like_enabled=False,
        missing_requirements=[],
        backtest_result_id=1,
        payload=payload,
    )
    evaluate = service._evaluate_promoted_strategies

    def evaluate_then_change(**kwargs):
        result = evaluate(**kwargs)
        assert result[1]
        if change == "pause":
            db.upsert_strategy_promotion_state_sync(
                strategy_id=strategy_id,
                stage="paused",
                gate_status="lifecycle_paused",
                live_like_enabled=False,
                missing_requirements=[],
                backtest_result_id=1,
                payload=payload,
            )
        else:
            store.configure_publication_grant(
                policy={
                    **grant,
                    "generation": str(uuid4()),
                    "enabled": change != "revoke",
                },
                expected_generation=grant["generation"],
                now="2026-08-24T01:36:00+00:00",
            )
        return result

    monkeypatch.setattr(service, "_evaluate_promoted_strategies", evaluate_then_change)
    result = service.run_once(
        decision_date="2026-08-24",
        portfolio_summary={
            "total_equity": 100000,
            "cash": 100000,
            "fact_authority": "persisted_valuation_snapshot",
            "valuation_status": "complete",
            "symbols": [symbols[0]],
            "instrument_types": {symbols[0]: "stock"},
            "valuation_snapshot_id": _valuation_id(db),
        },
    )
    if source_kind == "human" and change != "pause":
        assert result["status"] == "completed", result
        assert result["action_tasks"]
    else:
        assert result["status"] == "blocked", result
        assert any(
            item.startswith("promoted_strategy_scan_authority_changed_before_persist")
            for item in result["blockers"]
        )
        assert result["raw_signals"] and result["selected_signals"]
        assert result["action_tasks"] == []
        assert db.get_action_tasks_sync(statuses=["pending"], limit=100) == []
        assert db.list_signal_journal_sync(limit=100) == []


@pytest.mark.parametrize("change", ["cash_withdrawal", "held_quote", "daily_receipt"])
def test_current_account_and_market_change_after_evaluation_blocks_atomic_tasks(
    tmp_path, monkeypatch, change
):
    db, service, symbols = _service(tmp_path, produces_signals=True)
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-08-24T09:00:00+08:00",
        amount=100000,
        asset_class="cash",
    )
    held = symbols[0] if change == "held_quote" else None
    if held:
        db.insert_ledger_entry_sync(
            entry_type="trade_buy",
            timestamp="2026-08-24T09:01:00+08:00",
            symbol=held,
            quantity=100,
            price=10,
            asset_class="stock",
        )
        db.save_quote_snapshot_sync(
            symbol=held,
            asset_class="stock",
            price=10,
            volume=100000,
            timestamp="2026-08-24T09:35:00+08:00",
            quote_status="live",
        )
    snapshot_id = _valuation_id(db)
    portfolio = {
        "total_equity": 100000,
        "cash": 99000 if held else 100000,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "complete",
        "valuation_snapshot_id": snapshot_id,
        "symbols": [held] if held else [],
        "instrument_types": {held: "stock"} if held else {},
        "stock_position_market_values": {held: 1000} if held else {},
    }
    evaluate = service._evaluate_promoted_strategies

    def evaluate_then_change(**kwargs):
        result = evaluate(**kwargs)
        assert result[1]
        if change == "cash_withdrawal":
            db.insert_ledger_entry_sync(
                entry_type="cash_withdrawal",
                timestamp="2026-08-24T09:36:00+08:00",
                amount=100000,
                asset_class="cash",
            )
        elif change == "held_quote":
            db.save_quote_snapshot_sync(
                symbol=held,
                asset_class="stock",
                price=9,
                volume=100000,
                timestamp="2026-08-24T09:36:00+08:00",
                quote_status="live",
            )
        else:
            with sqlite3.connect(service._data_store._meta_path) as conn:
                conn.execute(
                    "UPDATE market_bars SET amount=amount+1 "
                    "WHERE timestamp >= '2026-08-21' AND timestamp < '2026-08-22'"
                )
        return result

    monkeypatch.setattr(service, "_evaluate_promoted_strategies", evaluate_then_change)
    result = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)
    assert result["status"] == "blocked", result
    assert any(
        item.startswith("promoted_strategy_scan_authority_changed_before_persist")
        for item in result["blockers"]
    )
    assert result["action_tasks"] == []
    with sqlite3.connect(db.path) as conn:
        assert conn.execute("SELECT count(*) FROM signals").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM action_tasks").fetchone()[0] == 0


def test_current_board_permission_revoked_after_evaluation_blocks_atomic_tasks(
    tmp_path, monkeypatch
):
    from server.services.account.account_board_permissions import (
        resolve_board_buy_permissions,
    )

    db, service, _ = _service(tmp_path, produces_signals=True, special_symbol="301251")
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-08-24T09:00:00+08:00",
        amount=100000,
        asset_class="cash",
    )
    service._config.account_board_permissions = _board_review("chinext", "enabled")
    portfolio = {
        "total_equity": 100000,
        "cash": 100000,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "complete",
        "valuation_snapshot_id": _valuation_id(db),
        "symbols": [],
        "instrument_types": {},
        "board_buy_permissions": resolve_board_buy_permissions(
            service._config, "2026-08-24"
        ),
    }
    evaluate = service._evaluate_promoted_strategies

    def evaluate_then_revoke(**kwargs):
        result = evaluate(**kwargs)
        assert any(row["symbol"] == "301251" for row in result[1])
        service._config.account_board_permissions = _board_review("chinext", "disabled")
        return result

    monkeypatch.setattr(service, "_evaluate_promoted_strategies", evaluate_then_revoke)
    result = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)
    assert result["status"] == "blocked"
    assert any(
        "current_board_permission_changed:board_permission_disabled" in item
        for item in result["blockers"]
    )
    assert result["action_tasks"] == []
    with sqlite3.connect(db.path) as conn:
        assert conn.execute("SELECT count(*) FROM signals").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM action_tasks").fetchone()[0] == 0


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
        "valuation_snapshot_id": _valuation_id(db),
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
        "valuation_snapshot_id": _valuation_id(db),
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

    from server.services.account.account_board_permissions import (
        resolve_board_buy_permissions,
    )

    service._config.account_board_permissions = _board_review("chinext", "enabled")
    permitted_portfolio = {
        **portfolio,
        "board_buy_permissions": resolve_board_buy_permissions(
            service._config, "2026-08-24"
        ),
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
        "valuation_snapshot_id": _valuation_id(db),
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


@pytest.mark.parametrize("change", ["quote_blocked", "outside_window", "selection"])
def test_successful_scan_cache_does_not_override_current_blockers(tmp_path, change):
    db, service, symbols = _service(tmp_path, produces_signals=True)
    portfolio = {
        "total_equity": 100000,
        "cash": 100000,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "complete",
        "symbols": [symbols[0]],
        "instrument_types": {symbols[0]: "stock"},
        "valuation_snapshot_id": _valuation_id(db),
    }
    first = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)
    assert first["status"] == "completed" and first["action_tasks"]
    original_run = db.get_automation_run_sync(first["run_id"])
    original_tasks = db.get_action_tasks_sync(statuses=["pending"], limit=100)
    original_signals = db.list_signal_journal_sync(limit=100)
    inputs = {}
    if change == "outside_window":
        service._clock = lambda: datetime(
            2026, 8, 24, 9, 46, tzinfo=ZoneInfo("Asia/Shanghai")
        )
        blocker = "strategy_scan_outside_reviewed_decision_window"
    elif change == "quote_blocked":
        blocker = "daily_candidate_quote_freeze:current_quote_unavailable"
        inputs["additional_blockers"] = [blocker]
    else:
        blocker = "signal_selection_changed_after_quote_freeze"
        inputs["expected_signal_selection_fingerprint"] = "sha256:" + "0" * 64
    current = service.run_once(
        decision_date="2026-08-24", portfolio_summary=portfolio, **inputs
    )
    assert current["status"] == "blocked"
    assert current["blockers"] == [blocker]
    assert current["action_tasks"] == [] and current["reused"] is True
    assert current["run_id"] == first["run_id"]
    core = {
        key: value
        for key, value in current.items()
        if key not in {"run_id", "reused", "output_fingerprint"}
    }
    assert current["output_fingerprint"] == "sha256:" + content_fingerprint(core)
    assert db.get_automation_run_sync(first["run_id"]) == original_run
    assert db.get_action_tasks_sync(statuses=["pending"], limit=100) == original_tasks
    assert db.list_signal_journal_sync(limit=100) == original_signals


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


@pytest.mark.parametrize("permission_enabled", [False, True])
def test_portfolio_policy_filters_frozen_board_universe_before_ranking(
    tmp_path, monkeypatch, permission_enabled
):
    from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
    from execution.commission import StockACommission
    from server.persistence.strategy_research import StrategyResearchAuditStore
    from server.services.account.account_board_permissions import (
        freeze_entry_board_policy,
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    strategy_id = "ai_formula_shadow:complete-market"
    db.upsert_strategy_promotion_state_sync(
        strategy_id=strategy_id,
        stage="paper_shadow",
        gate_status="paper_shadow_enabled",
        live_like_enabled=False,
        missing_requirements=[],
        backtest_result_id=1,
        payload={
            "readiness": {
                "deployment_validation": {
                    "final_evaluation_id": "sealed-fixture",
                    "initial_cash": "32000",
                    "entry_board_policy": freeze_entry_board_policy(None, "2026-08-24"),
                }
            }
        },
    )
    monkeypatch.setattr(
        StrategyResearchAuditStore,
        "get_sealed_test",
        lambda self, identity: {
            "evidence": {
                "reservation": {
                    "fee_schedule": {},
                    "publication_grant": {
                        "risk_limits": {
                            "max_positions": 4,
                            "max_gross_weight": "0.97",
                            "max_symbol_weight": "0.30",
                        }
                    },
                }
            }
        },
    )
    monkeypatch.setattr(
        "server.services.account.reviewed_fee_schedule.resolve_frozen_deployment_fee_schedule",
        lambda *args: SimpleNamespace(
            commission_calc=StockACommission(),
            review=SimpleNamespace(
                effective_start_date="2026-01-01", effective_end_date="2026-12-31"
            ),
        ),
    )
    symbols = ["688001", "600000", "600001", "600002", "600003"]
    signals = [
        {
            "strategy_id": strategy_id,
            "symbol": symbol,
            "direction": "buy",
            "ranking_liquidity": 10_000_000 - index,
            "frozen_close": 10,
            "portfolio_policy_id": FORMULA_PORTFOLIO_POLICY_ID,
        }
        for index, symbol in enumerate(symbols)
    ]
    selected, blocked = account_eligible_signals(
        signals,
        config=SimpleNamespace(),
        decision_date="2026-08-24",
        portfolio={
            "cash": 32000,
            "total_equity": 32000,
            "fact_authority": "persisted_valuation_snapshot",
            "stock_position_market_values": {},
            "stock_symbols": [],
            "board_buy_permissions": {
                "status": "current",
                "resolved_for_date": "2026-08-24",
                "evidence_fingerprint": "sha256:" + "a" * 64,
                "boards": {"star": "enabled"},
            }
            if permission_enabled
            else None,
        },
        policy=MarketUniversePolicy(),
        cash_buffer_ratio=Decimal("0.03"),
        db=db,
    )
    assert [row["symbol"] for row in selected] == symbols[1:]
    assert {row["symbol"]: row["reason"] for row in blocked} == {
        symbols[0]: "frozen_entry_board_policy",
    }


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
        "valuation_snapshot_id": _valuation_id(db),
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
    db, service, _ = _service(tmp_path, produces_signals=True, special_symbol="688001")
    portfolio = {
        "total_equity": 100_000,
        "cash": 100_000,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "complete",
        "symbols": [],
        "instrument_types": {},
        "valuation_snapshot_id": _valuation_id(db),
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
        "valuation_snapshot_id": _valuation_id(db),
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
        "valuation_snapshot_id": _valuation_id(db),
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
            "valuation_snapshot_id": _valuation_id(db),
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
            "valuation_snapshot_id": _valuation_id(db),
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
            "valuation_snapshot_id": _valuation_id(db),
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
        "valuation_snapshot_id": _valuation_id(db),
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
    db, service, _ = _service(tmp_path, produces_signals=False)
    portfolio = {
        "total_equity": 100_000,
        "valuation_status": "complete",
        "symbols": ["019999"],
        "instrument_types": {"019999": "open_end_fund"},
        "valuation_snapshot_id": _valuation_id(db),
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
    db, service, _ = _service(tmp_path, produces_signals=False)
    portfolio = {
        "total_equity": 100_000,
        "valuation_status": "complete",
        "symbols": ["019999"],
        "instrument_types": {"019999": "open_end_fund"},
        "valuation_snapshot_id": _valuation_id(db),
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
        "valuation_snapshot_id": _valuation_id(db),
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
            "valuation_snapshot_id": _valuation_id(db),
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
            "valuation_snapshot_id": _valuation_id(db),
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


def test_scan_outside_decision_window_evaluates_signals_without_persisting_action_tasks(
    tmp_path,
) -> None:
    db, service, symbols = _service(tmp_path, produces_signals=True)
    service._clock = lambda: datetime(
        2026,
        8,
        24,
        11,
        30,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )
    portfolio = {
        "total_equity": 100_000,
        "cash": 100_000,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "complete",
        "symbols": [symbols[0], "019999"],
        "instrument_types": {symbols[0]: "stock", "019999": "open_end_fund"},
        "valuation_snapshot_id": _valuation_id(db),
    }

    result = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)

    assert result["status"] == "blocked"
    assert "strategy_scan_outside_reviewed_decision_window" in result["blockers"]
    assert result["selected_signal_count"] == 5
    assert len(result["selected_signals"]) == 5
    assert result["selected_signals"][0]["symbol"] == symbols[0]
    assert result["selected_signals"][0]["direction"] == "sell"
    assert result["action_tasks"] == []
    assert db.get_action_tasks_sync(statuses=["pending"], limit=20) == []
    assert db.list_signal_journal_sync(limit=20) == []


def test_asset_class_valuation_health_isolation() -> None:
    from server.projections.valuation_snapshot import is_asset_class_valuation_healthy

    assert is_asset_class_valuation_healthy({"valuation_status": "complete"}, "stock")
    assert is_asset_class_valuation_healthy({"status": "complete"}, "fund")

    degraded_portfolio = {
        "valuation_status": "missing",
        "valuation_lanes": [
            {"asset_class": "stock", "status": "complete"},
            {"asset_class": "fund", "status": "missing"},
        ],
    }
    assert is_asset_class_valuation_healthy(degraded_portfolio, "stock") is True
    assert is_asset_class_valuation_healthy(degraded_portfolio, "fund") is False

    cash_only_portfolio = {
        "valuation_status": "missing",
        "valuation_lanes": [
            {"asset_class": "stock", "status": "not_applicable"},
            {"asset_class": "fund", "status": "missing"},
        ],
    }
    assert is_asset_class_valuation_healthy(cash_only_portfolio, "stock") is True

    unhealthy_stock_portfolio = {
        "valuation_status": "missing",
        "valuation_lanes": [
            {"asset_class": "stock", "status": "missing"},
            {"asset_class": "fund", "status": "complete"},
        ],
    }
    assert is_asset_class_valuation_healthy(unhealthy_stock_portfolio, "stock") is False


def test_scan_succeeds_when_fund_valuation_lane_is_missing_but_stock_lane_is_complete(
    tmp_path,
) -> None:
    db, service, symbols = _service(tmp_path, produces_signals=True)
    portfolio = {
        "total_equity": None,
        "stock_equity": 100_000,
        "cash": 100_000,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "missing",
        "valuation_lanes": [
            {
                "asset_class": "stock",
                "status": "complete",
                "quote_count": 1,
                "complete_quote_count": 1,
                "review_required_quote_count": 0,
                "blocker_statuses": [],
            },
            {
                "asset_class": "fund",
                "status": "missing",
                "quote_count": 3,
                "complete_quote_count": 0,
                "review_required_quote_count": 3,
                "blocker_statuses": ["missing"],
            },
        ],
        "symbols": [symbols[0], "019999"],
        "instrument_types": {symbols[0]: "stock", "019999": "open_end_fund"},
        "valuation_snapshot_id": _valuation_id(db),
    }

    result = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)

    assert result["status"] == "completed"
    assert "valuation_snapshot_not_complete" not in result["blockers"]
    assert "portfolio_total_equity_invalid" not in result["blockers"]
    assert result["selected_signal_count"] == 5
    assert len(result["action_tasks"]) == 5


def test_promoted_strategy_scan_succeeds_with_heterogeneous_providers(
    tmp_path,
) -> None:
    db, service, symbols = _service(
        tmp_path,
        produces_signals=True,
        snapshot_provider="akshare",
        daily_provider="tushare",
    )
    portfolio = {
        "total_equity": 100_000,
        "cash": 100_000,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "complete",
        "symbols": [symbols[0], "019999"],
        "instrument_types": {symbols[0]: "stock", "019999": "open_end_fund"},
        "valuation_snapshot_id": _valuation_id(db),
    }

    first = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)
    second = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)

    assert first["status"] == "completed"
    assert first["blockers"] == []
    assert first["selected_signal_count"] == 5
    assert second["reused"] is True
    assert second["blockers"] == []


def test_resolve_daily_bar_receipt_provider_resolution(tmp_path) -> None:
    from server.services.strategy_scan.promoted_strategy_universe_scan_support import (
        resolve_daily_bar_receipt_provider,
    )

    store = DataStore(tmp_path / "market")
    # Empty store fallback
    resolved = resolve_daily_bar_receipt_provider(
        data_store=store,
        start_date="2026-01-01",
        end_date="2026-08-24",
        snapshot={"provider_name": "akshare"},
    )
    assert resolved == "akshare"

    # Store with tushare receipts
    store.ingest_market_daily_batch(
        trade_date="2026-08-21",
        provider_name="tushare",
        bars=pd.DataFrame(
            {
                "symbol": ["600001"],
                "timestamp": [pd.Timestamp("2026-08-21")],
                "open": [10.0],
                "high": [10.2],
                "low": [9.8],
                "close": [10.0],
                "volume": [1_000_000],
                "amount": [10_000_000],
            }
        ),
    )

    # When snapshot provider matches available
    assert (
        resolve_daily_bar_receipt_provider(
            data_store=store,
            start_date="2026-01-01",
            end_date="2026-08-24",
            snapshot={"provider_name": "tushare"},
        )
        == "tushare"
    )

    # Heterogeneous: snapshot is akshare, receipts are tushare -> resolves to tushare
    assert (
        resolve_daily_bar_receipt_provider(
            data_store=store,
            start_date="2026-01-01",
            end_date="2026-08-24",
            snapshot={"provider_name": "akshare"},
        )
        == "tushare"
    )

    # Explicit preferred override
    assert (
        resolve_daily_bar_receipt_provider(
            data_store=store,
            start_date="2026-01-01",
            end_date="2026-08-24",
            snapshot={"provider_name": "akshare"},
            preferred_provider="custom_override",
        )
        == "custom_override"
    )


def test_resolve_daily_bar_receipts_heterogeneous_window(tmp_path) -> None:
    from server.services.strategy_scan.promoted_strategy_universe_scan_support import (
        resolve_daily_bar_receipts,
    )

    store = DataStore(tmp_path / "market")

    def _ingest(date: str, provider: str, close: float) -> None:
        store.ingest_market_daily_batch(
            trade_date=date,
            provider_name=provider,
            bars=pd.DataFrame(
                {
                    "symbol": ["600001"],
                    "timestamp": [pd.Timestamp(date)],
                    "open": [close],
                    "high": [close + 0.2],
                    "low": [close - 0.2],
                    "close": [close],
                    "volume": [1_000_000],
                    "amount": [10_000_000],
                }
            ),
        )

    # Date 1: tushare, Date 2: akshare
    _ingest("2026-08-20", "tushare", 10.0)
    _ingest("2026-08-21", "akshare", 10.5)

    receipts = resolve_daily_bar_receipts(
        data_store=store,
        start_date="2026-08-20",
        end_date="2026-08-21",
    )
    assert len(receipts) == 2
    assert receipts[0]["trade_date"] == "2026-08-20"
    assert receipts[0]["provider_name"] == "tushare"
    assert receipts[1]["trade_date"] == "2026-08-21"
    assert receipts[1]["provider_name"] == "akshare"

    # Date 2 now also has tushare; config prioritizes tushare over akshare
    _ingest("2026-08-21", "tushare", 10.5)
    receipts_priority = resolve_daily_bar_receipts(
        data_store=store,
        start_date="2026-08-20",
        end_date="2026-08-21",
        config=SimpleNamespace(data_source="tushare"),
    )
    assert len(receipts_priority) == 2
    assert receipts_priority[1]["trade_date"] == "2026-08-21"
    assert receipts_priority[1]["provider_name"] == "tushare"


def test_promoted_strategy_scan_succeeds_with_multi_source_daily_receipts(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    market_dates = _calendar(db)
    store = DataStore(tmp_path / "market")

    symbols = [f"{600000 + index:06d}" for index in range(1, 51)]
    members = normalize_a_share_members(symbols)
    store.save_market_universe_snapshot(
        trade_date="2026-08-21",
        provider_name="master_fixture",
        members=members,
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
    # Split dates across two different daily providers: half tushare, half akshare
    mid = len(market_dates) // 2
    for index, market_date in enumerate(market_dates):
        provider = "tushare_daily" if index < mid else "akshare_daily"
        closes = [10.0 if symbol == symbols[0] else 20.0 for symbol in symbols]
        store.ingest_market_daily_batch(
            trade_date=market_date,
            provider_name=provider,
            bars=pd.DataFrame(
                {
                    "symbol": symbols,
                    "timestamp": [pd.Timestamp(market_date)] * len(symbols),
                    "open": closes,
                    "high": [value + 0.2 for value in closes],
                    "low": [value - 0.2 for value in closes],
                    "close": closes,
                    "volume": [1_000_000 + idx for idx in range(len(symbols))],
                    "amount": [10_000_000 + idx * 1_000 for idx in range(len(symbols))],
                }
            ),
        )

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
        "formula_ast": _formula(produces_signals=True),
        "formula_fingerprint": "sha256:fixture-formula",
        "selected_universe": symbols[:40],
    }
    strategy_fingerprint = content_fingerprint(strategy)

    def gate_resolver(_db, requested_strategy_id, *, as_of_date):
        return {
            "status": "pass",
            "promotion": {
                "daily_strategy_artifact_binding": {
                    "winner_candidate_id": "winner",
                    "run_id": "run-1",
                    "operating_constraints": {
                        "strategy_artifact_fingerprint": strategy_fingerprint,
                    },
                }
            },
        }, []

    def strategy_loader(*, candidate_id, run_id):
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
            "kill_switch_enabled": False,
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

    portfolio = {
        "total_equity": 100_000,
        "cash": 100_000,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "complete",
        "symbols": [symbols[0], "019999"],
        "instrument_types": {symbols[0]: "stock", "019999": "open_end_fund"},
        "valuation_snapshot_id": _valuation_id(db),
    }

    first = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)
    second = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)

    assert first["status"] == "completed"
    assert first["blockers"] == []
    assert first["selected_signal_count"] == 5
    assert second["reused"] is True
    assert second["blockers"] == []


def test_full_market_truth_incomplete_allows_held_stock_exit_while_blocking_buys(
    tmp_path,
    monkeypatch,
) -> None:
    db, service, symbols = _service(tmp_path, produces_signals=True)
    portfolio = {
        "total_equity": 100_000,
        "cash": 100_000,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "complete",
        "symbols": [symbols[0]],
        "instrument_types": {symbols[0]: "stock"},
        "valuation_snapshot_id": _valuation_id(db),
    }

    original_evaluate = service._evaluate_promoted_strategies

    def evaluate_with_incomplete_market_truth(*args, **kwargs):
        truths, raw_signals, blockers = original_evaluate(*args, **kwargs)
        for strategy_id, truth in truths.items():
            truth["status"] = "blocked"
            truth["blockers"] = ["full_market_evidence_incomplete"]
            truth["eligible_symbols"] = []
        blockers = [
            f"strategy_full_market_truth:{strategy_id}:full_market_evidence_incomplete"
            for strategy_id in truths
        ]
        # Re-evaluate with empty eligible_symbols but preserved maintenance_symbols
        re_truths, re_signals, _ = original_evaluate(*args, **kwargs)
        # Sells from maintenance_symbols should be retained, buys suppressed
        sells = [s for s in re_signals if s.get("direction") == "sell"]
        return truths, sells, blockers

    monkeypatch.setattr(
        service,
        "_evaluate_promoted_strategies",
        evaluate_with_incomplete_market_truth,
    )

    result = service.run_once(decision_date="2026-08-24", portfolio_summary=portfolio)

    assert result["status"] == "completed"
    assert result["blockers"] == []
    assert result["selected_signal_count"] == 1
    assert result["selected_signals"][0]["symbol"] == symbols[0]
    assert result["selected_signals"][0]["direction"] == "sell"
    assert len(result["action_tasks"]) == 1
    assert result["action_tasks"][0]["symbol"] == symbols[0]
    assert result["action_tasks"][0]["direction"] == "sell"
    assert result["full_market_truths"][0]["status"] == "blocked"
    assert result["full_market_truths"][0]["blockers"] == [
        "full_market_evidence_incomplete"
    ]

    # Verify that if no stocks are held, the scan fails closed as blocked
    empty_portfolio = {
        **portfolio,
        "symbols": [],
        "instrument_types": {},
    }
    blocked_result = service.run_once(
        decision_date="2026-08-24", portfolio_summary=empty_portfolio
    )
    assert blocked_result["status"] == "blocked"
    assert any(
        "full_market_evidence_incomplete" in b for b in blocked_result["blockers"]
    )
    assert blocked_result["action_tasks"] == []
    assert blocked_result["selected_signal_count"] == 0
