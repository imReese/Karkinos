from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

from core.types import Symbol
from risk.pre_trade import PreTradeContext, PreTradePolicy
from server.db import AppDatabase
from server.services.pre_trade_batch import run_pre_trade_risk_batch


@dataclass
class StaticContextProvider:
    context: PreTradeContext

    def snapshot(self) -> PreTradeContext:
        return self.context


def _context(*, cash: str = "5000", total_equity: str = "100000") -> PreTradeContext:
    return PreTradeContext(
        cash=Decimal(cash),
        total_equity=Decimal(total_equity),
        peak_equity=Decimal(total_equity),
        positions={},
        instruments={},
        blacklist=set(),
        st_symbols=set(),
    )


def _add_action(
    db: AppDatabase,
    *,
    source_signal_id: int,
    symbol: str,
    target_weight: float,
    price: float,
) -> None:
    db.save_signal_sync(
        timestamp="2026-07-02T09:30:00",
        strategy_id="dual_ma",
        symbol=symbol,
        direction="buy",
        target_weight=target_weight,
        price=price,
        asset_class="stock",
    )
    db.upsert_action_task_sync(
        source_signal_id=source_signal_id,
        symbol=symbol,
        title=f"候选买入 {symbol}",
        detail="batch pre-trade risk test",
        direction="buy",
        urgency="normal",
        target_weight=target_weight,
        price=price,
        strategy_id="dual_ma",
        timestamp="2026-07-02T09:30:00",
        asset_class="stock",
    )


def test_batch_pre_trade_risk_persists_passed_and_blocked_action_results(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _add_action(
        db,
        source_signal_id=1,
        symbol="510300",
        target_weight=0.01,
        price=10.0,
    )
    _add_action(
        db,
        source_signal_id=2,
        symbol="600519",
        target_weight=0.10,
        price=100.0,
    )

    result = run_pre_trade_risk_batch(
        db=db,
        context_provider=StaticContextProvider(_context()),
        policy=PreTradePolicy(execution_mode="manual"),
        evidence_binding={
            "valuation_snapshot_id": "valuation-fixture",
            "ledger_cutoff_id": 7,
            "valuation_status": "complete",
            "fact_authority": "persisted_valuation_snapshot",
        },
    )

    assert result["schema_version"] == "karkinos.pre_trade_risk_batch.v1"
    assert result["processed_count"] == 2
    assert result["passed_count"] == 1
    assert result["blocked_count"] == 1
    assert result["does_not_create_order"] is True
    assert result["default_execution_mode"] == "manual_confirmation"
    stored_decision = db.get_risk_decisions_sync(limit=10)[0]
    stored_payload = json.loads(stored_decision["payload_json"])
    assert stored_payload["decision"]["metadata"]["evidence_binding"] == {
        "valuation_snapshot_id": "valuation-fixture",
        "ledger_cutoff_id": 7,
        "valuation_status": "complete",
        "fact_authority": "persisted_valuation_snapshot",
    }

    tasks = {task["symbol"]: task for task in db.get_action_tasks_sync(limit=10)}
    assert tasks["510300"]["risk_gate_status"] == "passed"
    assert (
        tasks["510300"]["manual_confirmation_status"] == "ready_for_manual_confirmation"
    )
    assert tasks["600519"]["risk_gate_status"] == "blocked"
    assert (
        "cash reserve would fall below min_cash_reserve"
        in tasks["600519"]["risk_gate_reasons"]
    )
    assert tasks["600519"]["manual_confirmation_status"] == "blocked_by_risk_gate"
    assert db.list_manual_orders_sync() == []


def test_batch_pre_trade_risk_skips_already_checked_actions(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _add_action(
        db,
        source_signal_id=1,
        symbol="510300",
        target_weight=0.01,
        price=10.0,
    )
    provider = StaticContextProvider(_context())

    first = run_pre_trade_risk_batch(
        db=db,
        context_provider=provider,
        policy=PreTradePolicy(execution_mode="manual"),
    )
    second = run_pre_trade_risk_batch(
        db=db,
        context_provider=provider,
        policy=PreTradePolicy(execution_mode="manual"),
    )

    assert first["processed_count"] == 1
    assert second["processed_count"] == 0
    assert second["skipped_count"] == 1
    assert len(db.get_risk_decisions_sync()) == 1


def test_batch_pre_trade_risk_defaults_match_daily_portfolio_controls(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _add_action(
        db,
        source_signal_id=1,
        symbol="510300",
        target_weight=0.03,
        price=10.0,
    )

    result = run_pre_trade_risk_batch(
        db=db,
        context_provider=StaticContextProvider(
            _context(cash="5000", total_equity="100000")
        ),
    )

    assert result["processed_count"] == 1
    assert result["blocked_count"] == 1
    task = db.get_action_tasks_sync()[0]
    assert task["risk_gate_status"] == "blocked"
    assert "cash reserve would fall below min_cash_reserve" in task["risk_gate_reasons"]


def test_batch_pre_trade_risk_accepts_configured_cash_buffer(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _add_action(
        db,
        source_signal_id=1,
        symbol="510300",
        target_weight=0.01,
        price=10.0,
    )

    result = run_pre_trade_risk_batch(
        db=db,
        context_provider=StaticContextProvider(
            _context(cash="5000", total_equity="100000")
        ),
        config=SimpleNamespace(trading_plan_min_cash_buffer_ratio=0.05),
    )

    assert result["processed_count"] == 1
    assert result["blocked_count"] == 1
    task = db.get_action_tasks_sync()[0]
    assert "cash reserve would fall below min_cash_reserve" in task["risk_gate_reasons"]
