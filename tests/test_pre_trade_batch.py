from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.types import Symbol
from risk.pre_trade import PreTradeContext, PreTradePolicy
from server.db import AppDatabase
from server.services.decision_candidate_market_evidence import (
    candidate_market_evidence,
)
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
    asset_class: str = "stock",
) -> None:
    db.save_signal_sync(
        timestamp="2026-07-02T09:30:00",
        strategy_id="dual_ma",
        symbol=symbol,
        direction="buy",
        target_weight=target_weight,
        price=price,
        asset_class=asset_class,
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
        asset_class=asset_class,
    )


def _persisted_evidence_binding(db: AppDatabase) -> dict:
    tasks = db.get_action_tasks_sync(limit=50)
    if not db.get_ledger_entries_sync(limit=1):
        db.insert_ledger_entry_sync(
            entry_type="cash_deposit",
            timestamp="2026-07-02T09:00:00+08:00",
            amount=100000.0,
            created_at="2026-07-02T09:00:01+08:00",
        )
    for task in tasks:
        db.upsert_latest_quote_sync(
            symbol=str(task["symbol"]),
            asset_type=str(task["asset_class"]),
            price=float(task["price"]),
            quote_timestamp="2026-07-02T09:30:00+08:00",
            quote_source="deterministic_fixture",
            quote_status="confirmed",
        )
    published = db.publish_current_valuation_snapshot_sync(
        now=datetime(2026, 7, 2, 1, 31, tzinfo=timezone.utc)
    )
    candidate = candidate_market_evidence(
        db,
        tasks,
        now=datetime(2026, 7, 2, 1, 31, tzinfo=timezone.utc),
    )
    guard = db.capture_pre_trade_risk_guard_sync(tasks=tasks)
    assert guard["status"] == "ready"
    return {
        "valuation_snapshot_id": published["snapshot_id"],
        "ledger_cutoff_id": published["ledger_cutoff_id"],
        "valuation_status": published["status"],
        "fact_authority": "persisted_valuation_snapshot",
        "candidate_market_evidence_fingerprint": candidate["fingerprint"],
        "candidate_quote_bindings": candidate["bindings"],
        "quote_current_revision": guard["quote_current_revision"],
        "action_task_bindings": guard["action_task_bindings"],
    }


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

    evidence_binding = _persisted_evidence_binding(db)
    result = run_pre_trade_risk_batch(
        db=db,
        context_provider=StaticContextProvider(_context()),
        policy=PreTradePolicy(execution_mode="manual"),
        evidence_binding=evidence_binding,
    )

    assert result["schema_version"] == "karkinos.pre_trade_risk_batch.v1"
    assert result["processed_count"] == 2
    assert result["passed_count"] == 1
    assert result["blocked_count"] == 1
    assert result["does_not_create_order"] is True
    assert result["default_execution_mode"] == "manual_confirmation"
    stored_decision = db.get_risk_decisions_sync(limit=10)[0]
    stored_payload = json.loads(stored_decision["payload_json"])
    assert (
        stored_payload["decision"]["metadata"]["evidence_binding"] == evidence_binding
    )

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
    assert len(db.list_events_sync(source="risk_decisions")) == 2
    assert db.list_manual_orders_sync() == []


def test_batch_pre_trade_risk_binds_exact_etf_candidate_identity(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _add_action(
        db,
        source_signal_id=1,
        symbol="510300",
        target_weight=0.01,
        price=10.0,
        asset_class="etf",
    )
    evidence_binding = _persisted_evidence_binding(db)

    result = run_pre_trade_risk_batch(
        db=db,
        context_provider=StaticContextProvider(_context(cash="100000")),
        policy=PreTradePolicy(execution_mode="manual"),
        evidence_binding=evidence_binding,
    )

    assert result["status"] == "completed"
    assert result["passed_count"] == 1
    assert evidence_binding["candidate_quote_bindings"][0]["instrument_type"] == "etf"
    assert db.get_risk_decisions_sync()[0]["symbol"] == "510300"


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
    evidence_binding = _persisted_evidence_binding(db)

    first = run_pre_trade_risk_batch(
        db=db,
        context_provider=provider,
        policy=PreTradePolicy(execution_mode="manual"),
        evidence_binding=evidence_binding,
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
    evidence_binding = _persisted_evidence_binding(db)

    result = run_pre_trade_risk_batch(
        db=db,
        context_provider=StaticContextProvider(
            _context(cash="5000", total_equity="100000")
        ),
        evidence_binding=evidence_binding,
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
    evidence_binding = _persisted_evidence_binding(db)

    result = run_pre_trade_risk_batch(
        db=db,
        context_provider=StaticContextProvider(
            _context(cash="5000", total_equity="100000")
        ),
        config=SimpleNamespace(trading_plan_min_cash_buffer_ratio=0.05),
        evidence_binding=evidence_binding,
    )

    assert result["processed_count"] == 1
    assert result["blocked_count"] == 1
    task = db.get_action_tasks_sync()[0]
    assert "cash reserve would fall below min_cash_reserve" in task["risk_gate_reasons"]


def test_batch_pre_trade_risk_rejects_invalid_action_timestamp_without_write(
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
    task = {**db.get_action_tasks_sync()[0], "timestamp": "not-a-timestamp"}

    result = run_pre_trade_risk_batch(
        db=db,
        context_provider=StaticContextProvider(_context()),
        policy=PreTradePolicy(execution_mode="manual"),
        tasks=[task],
    )

    assert result["processed_count"] == 0
    assert result["skipped_count"] == 1
    assert result["results"][0]["reasons"] == ["invalid_action_timestamp"]
    assert db.get_risk_decisions_sync() == []
    assert db.get_action_tasks_sync()[0]["risk_gate_status"] == "not_checked"


def test_batch_pre_trade_risk_rolls_back_whole_batch_on_action_drift(tmp_path) -> None:
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
    stale_tasks = db.get_action_tasks_sync(limit=10)
    evidence_binding = _persisted_evidence_binding(db)

    db.upsert_action_task_sync(
        source_signal_id=1,
        symbol="510300",
        title="候选买入 510300",
        detail="drifted after evidence gate",
        direction="buy",
        urgency="high",
        target_weight=0.05,
        price=10.0,
        strategy_id="dual_ma",
        timestamp="2026-07-02T09:30:00",
        asset_class="stock",
    )
    result = run_pre_trade_risk_batch(
        db=db,
        context_provider=StaticContextProvider(_context(cash="100000")),
        policy=PreTradePolicy(execution_mode="manual"),
        tasks=stale_tasks,
        evidence_binding=evidence_binding,
    )

    assert result["status"] == "blocked_by_evidence_drift"
    assert result["processed_count"] == 0
    assert {item["code"] for item in result["blockers"]} >= {
        "action_task_identity_drift"
    }
    _assert_no_risk_batch_writes(db)


def test_batch_pre_trade_risk_rolls_back_whole_batch_on_quote_drift(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _add_action(
        db,
        source_signal_id=1,
        symbol="510300",
        target_weight=0.01,
        price=10.0,
    )
    stale_tasks = db.get_action_tasks_sync(limit=10)
    evidence_binding = _persisted_evidence_binding(db)

    db.upsert_latest_quote_sync(
        symbol="510300",
        asset_type="stock",
        price=10.1,
        quote_timestamp="2026-07-02T09:31:00+08:00",
        quote_source="deterministic_fixture",
        quote_status="confirmed",
    )
    result = run_pre_trade_risk_batch(
        db=db,
        context_provider=StaticContextProvider(_context(cash="100000")),
        policy=PreTradePolicy(execution_mode="manual"),
        tasks=stale_tasks,
        evidence_binding=evidence_binding,
    )

    assert result["status"] == "blocked_by_evidence_drift"
    assert result["processed_count"] == 0
    assert {item["code"] for item in result["blockers"]} >= {
        "quote_current_materialization_revision_drift",
        "candidate_quote_content_drift",
    }
    _assert_no_risk_batch_writes(db)


def test_final_risk_transaction_observes_failure_after_capture_without_quote_drift(
    tmp_path,
):
    from server.persistence.financial_facts_valuation import (
        record_valuation_publication_failure_on_connection,
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _add_action(db, source_signal_id=1, symbol="600001", target_weight=0.01, price=10)
    evidence = _persisted_evidence_binding(db)
    publication = db.get_runtime_control_sync("valuation_snapshot_publication")
    db.create_quote_fetch_run(
        run_id="late-failure",
        started_at="2026-07-02T10:00:00+08:00",
        trigger="replay",
        status="running",
        asset_type="stock",
        symbol_count=1,
        metadata={"symbols": ["600001"]},
    )
    with sqlite3.connect(db.path) as other:
        other.row_factory = sqlite3.Row
        other.execute("BEGIN IMMEDIATE")
        record_valuation_publication_failure_on_connection(
            other,
            updated_at="2026-07-02T10:01:00+08:00",
            reason="close_conflict",
            quote_fetch_run_id="late-failure",
        )
    assert db.get_runtime_control_sync("valuation_snapshot_publication") == publication
    assert (
        db.capture_pre_trade_risk_guard_sync(tasks=[])["quote_current_revision"]
        == evidence["quote_current_revision"]
    )
    result = run_pre_trade_risk_batch(
        db=db,
        context_provider=StaticContextProvider(_context(cash="100000")),
        policy=PreTradePolicy(execution_mode="manual"),
        evidence_binding=evidence,
    )
    assert result["status"] == "blocked_by_evidence_drift"
    assert {"code": "valuation_publication_recovery_required"} in result["blockers"]
    _assert_no_risk_batch_writes(db)


def test_final_risk_transaction_rejects_intent_instrument_type_drift(
    tmp_path, monkeypatch
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _add_action(db, source_signal_id=1, symbol="600001", target_weight=0.01, price=10)
    evidence = _persisted_evidence_binding(db)
    commit = db.commit_pre_trade_risk_batch_sync

    def drift(*, writes, evidence_binding):
        writes[0][0].metadata["instrument_type"] = "etf"
        return commit(writes=writes, evidence_binding=evidence_binding)

    monkeypatch.setattr(db, "commit_pre_trade_risk_batch_sync", drift)
    result = run_pre_trade_risk_batch(
        db=db,
        context_provider=StaticContextProvider(_context(cash="100000")),
        policy=PreTradePolicy(execution_mode="manual"),
        evidence_binding=evidence,
    )
    assert result["status"] == "blocked_by_evidence_drift"
    assert "risk_batch_action_intent_drift" in {
        item["code"] for item in result["blockers"]
    }
    _assert_no_risk_batch_writes(db)


def test_batch_pre_trade_risk_rolls_back_whole_batch_on_valuation_drift(
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
    stale_tasks = db.get_action_tasks_sync(limit=10)
    evidence_binding = _persisted_evidence_binding(db)

    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-07-02T09:05:00+08:00",
        amount=1.0,
        created_at="2026-07-02T09:05:01+08:00",
    )
    result = run_pre_trade_risk_batch(
        db=db,
        context_provider=StaticContextProvider(_context(cash="100000")),
        policy=PreTradePolicy(execution_mode="manual"),
        tasks=stale_tasks,
        evidence_binding=evidence_binding,
    )

    assert result["status"] == "blocked_by_evidence_drift"
    assert result["processed_count"] == 0
    assert {item["code"] for item in result["blockers"]} >= {
        "valuation_publication_snapshot_drift",
        "valuation_publication_ledger_cutoff_drift",
        "valuation_ledger_head_drift",
    }
    _assert_no_risk_batch_writes(db)


def test_batch_pre_trade_risk_rejects_duplicate_decision_identity_before_writes(
    tmp_path,
    monkeypatch,
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
    evidence_binding = _persisted_evidence_binding(db)
    monkeypatch.setattr(
        "server.services.pre_trade_batch.uuid.uuid4",
        lambda: SimpleNamespace(hex="same-decision-id"),
    )

    result = run_pre_trade_risk_batch(
        db=db,
        context_provider=StaticContextProvider(_context(cash="100000")),
        policy=PreTradePolicy(execution_mode="manual"),
        evidence_binding=evidence_binding,
    )

    assert result["status"] == "blocked_by_evidence_drift"
    assert {item["code"] for item in result["blockers"]} >= {
        "risk_decision_identity_duplicate"
    }
    _assert_no_risk_batch_writes(db)


def test_batch_pre_trade_risk_rolls_back_first_write_when_second_insert_fails(
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
    evidence_binding = _persisted_evidence_binding(db)
    with sqlite3.connect(db.path) as conn:
        conn.execute("""
            CREATE TRIGGER reject_second_risk_fixture
            BEFORE INSERT ON risk_decisions
            WHEN NEW.symbol = '510300'
            BEGIN
                SELECT RAISE(ABORT, 'reject second risk fixture');
            END
            """)

    with pytest.raises(sqlite3.IntegrityError, match="reject second risk fixture"):
        run_pre_trade_risk_batch(
            db=db,
            context_provider=StaticContextProvider(_context(cash="100000")),
            policy=PreTradePolicy(execution_mode="manual"),
            evidence_binding=evidence_binding,
        )

    _assert_no_risk_batch_writes(db)


def test_batch_pre_trade_risk_rejects_prior_risk_decision_without_new_writes(
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
    stale_tasks = db.get_action_tasks_sync(limit=10)
    evidence_binding = _persisted_evidence_binding(db)
    first = run_pre_trade_risk_batch(
        db=db,
        context_provider=StaticContextProvider(_context(cash="100000")),
        policy=PreTradePolicy(execution_mode="manual"),
        tasks=stale_tasks,
        evidence_binding=evidence_binding,
    )
    risk_count = len(db.get_risk_decisions_sync())
    event_count = len(db.list_events_sync(source="risk_decisions"))

    second = run_pre_trade_risk_batch(
        db=db,
        context_provider=StaticContextProvider(_context(cash="100000")),
        policy=PreTradePolicy(execution_mode="manual"),
        tasks=stale_tasks,
        evidence_binding=evidence_binding,
    )

    assert first["status"] == "completed"
    assert second["status"] == "blocked_by_evidence_drift"
    assert {item["code"] for item in second["blockers"]} >= {
        "action_task_risk_gate_drift",
        "risk_decision_identity_conflict",
    }
    assert len(db.get_risk_decisions_sync()) == risk_count == 1
    assert len(db.list_events_sync(source="risk_decisions")) == event_count == 1


def _assert_no_risk_batch_writes(db: AppDatabase) -> None:
    assert db.get_risk_decisions_sync() == []
    assert db.list_events_sync(source="risk_decisions") == []
