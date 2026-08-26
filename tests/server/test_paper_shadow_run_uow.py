"""Atomicity, replay, and authority tests for paper-shadow persistence."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest

import server.persistence.paper_shadow_run_uow as paper_shadow_uow
import server.services.paper_shadow_run as paper_shadow_service
from server.contracts.paper_shadow import PaperShadowRunCommand
from server.db import AppDatabase


def test_paper_shadow_run_rolls_back_every_fact_and_recovers_after_crash(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    original_insert_fill = paper_shadow_uow._insert_fill

    def fail_after_orders(*_: Any, **__: Any) -> None:
        raise RuntimeError("simulated crash before fill persistence")

    monkeypatch.setattr(paper_shadow_uow, "_insert_fill", fail_after_orders)
    with pytest.raises(RuntimeError, match="simulated crash"):
        paper_shadow_service.run_paper_shadow_from_trading_plan(
            db=db,
            trading_plan=_trading_plan(),
            generated_at="2026-07-02T09:35:00",
        )

    assert _counts(db) == {
        "paper_shadow_runs": 0,
        "orders": 0,
        "fills": 0,
        "oms_orders": 0,
        "oms_transitions": 0,
        "order_state_command_claims": 0,
        "event_log": 0,
        "ledger_entries": 0,
    }

    monkeypatch.setattr(paper_shadow_uow, "_insert_fill", original_insert_fill)
    recovered = paper_shadow_service.run_paper_shadow_from_trading_plan(
        db=db,
        trading_plan=_trading_plan(),
        generated_at="2026-07-02T09:35:00",
    )
    assert recovered["status"] == "within_expectations"
    assert _counts(db) == {
        "paper_shadow_runs": 1,
        "orders": 1,
        "fills": 1,
        "oms_orders": 1,
        "oms_transitions": 4,
        "order_state_command_claims": 4,
        "event_log": 7,
        "ledger_entries": 0,
    }


def test_concurrent_identical_shadow_commands_persist_one_aggregate(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    monkeypatch.setattr(
        paper_shadow_service, "_matching_latest_run", lambda *_a, **_k: None
    )

    def run() -> dict[str, Any]:
        return paper_shadow_service.run_paper_shadow_from_trading_plan(
            db=db,
            trading_plan=_trading_plan(),
            generated_at="2026-07-02T09:35:00",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(run)
        second_future = executor.submit(run)
        first = first_future.result()
        second = second_future.result()

    assert first["run_id"] == second["run_id"]
    counts = _counts(db)
    assert counts["paper_shadow_runs"] == 1
    assert counts["orders"] == 1
    assert counts["fills"] == 1
    assert counts["oms_orders"] == 1
    assert counts["oms_transitions"] == 4
    assert counts["order_state_command_claims"] == 4
    assert counts["event_log"] == 7


def test_shadow_command_exact_replay_is_a_noop_and_payload_drift_fails_closed(
    tmp_path,
) -> None:
    capture = _CommandCapture()
    paper_shadow_service.run_paper_shadow_from_trading_plan(
        db=capture,
        trading_plan=_trading_plan(),
        generated_at="2026-07-02T09:35:00",
    )
    command = capture.command
    assert command is not None

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    first = db.record_paper_shadow_run_sync(command)
    before = _counts(db)
    replay = db.record_paper_shadow_run_sync(command)

    assert replay["id"] == first["id"]
    assert _counts(db) == before

    drifted = replace(
        command,
        payload={**command.payload, "generated_at": "2026-07-02T09:35:01"},
    )
    with pytest.raises(ValueError, match="command payload changed"):
        db.record_paper_shadow_run_sync(drifted)
    assert _counts(db) == before


class _CommandCapture:
    command: PaperShadowRunCommand | None = None

    def latest_paper_shadow_run_sync(
        self,
        *,
        plan_date: str | None = None,
    ) -> None:
        return None

    def record_paper_shadow_run_sync(
        self,
        command: PaperShadowRunCommand,
    ) -> dict[str, Any]:
        self.command = command
        return {"run_id": command.run_id}


def _counts(db: AppDatabase) -> dict[str, int]:
    tables = (
        "paper_shadow_runs",
        "orders",
        "fills",
        "oms_orders",
        "oms_transitions",
        "order_state_command_claims",
        "event_log",
        "ledger_entries",
    )
    with sqlite3.connect(db._path) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }


def _trading_plan() -> dict[str, Any]:
    return {
        "schema_version": "karkinos.daily_trading_plan.v1",
        "plan_date": "2026-07-02",
        "generated_at": "2026-07-02T09:30:00",
        "source_decision": "buy",
        "available_cash": 5000.0,
        "account_truth": {
            "gate_status": "pass",
            "has_evidence": True,
            "blocking_reasons": [],
        },
        "order_intents": [
            {
                "action_id": "ACTION-1",
                "symbol": "600519",
                "asset_class": "stock",
                "side": "buy",
                "estimated_price": 10.0,
                "estimated_quantity": 100.0,
                "risk_gate_status": "passed",
                "manual_confirmation_status": "ready_for_manual_confirmation",
                "submission_status": "manual_confirmation_required",
                "does_not_submit_broker_order": True,
                "evidence_refs": ["strategy:dual_ma", "risk:risk-001"],
            }
        ],
    }
