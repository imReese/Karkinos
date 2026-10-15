"""Recommendation writes share SQLite authority serialization and rollback."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from server.db import AppDatabase
from server.persistence.signal_journal import SignalJournalRepository
from server.services.promoted_strategy_universe_scan_persistence import (
    persist_recommendation_tasks,
)


def _signals():
    return [
        {
            "strategy_id": "ai_formula_shadow:fixture",
            "symbol": symbol,
            "direction": "buy",
            "target_weight": 0.25,
            "frozen_close": 10,
        }
        for symbol in ("600000", "600001")
    ]


def test_authority_validator_holds_sqlite_writer_lock(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    def competing_authority_writer():
        with sqlite3.connect(db.path, timeout=0) as conn:
            conn.execute("BEGIN IMMEDIATE")

    def validate():
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(competing_authority_writer)
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                future.result(timeout=2)

    tasks = persist_recommendation_tasks(
        db=db,
        decision_date="2026-08-24",
        signals=_signals(),
        current_authority_validator=validate,
    )
    assert len(tasks) == 2
    # The competing grant/source writer can acquire the same lock after commit.
    competing_authority_writer()


def test_signal_task_and_event_batch_rolls_back_together(tmp_path, monkeypatch):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    write = SignalJournalRepository.upsert_action_task_sync
    count = 0

    def fail_second(self, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("interrupted recommendation batch")
        return write(self, **kwargs)

    monkeypatch.setattr(SignalJournalRepository, "upsert_action_task_sync", fail_second)
    with pytest.raises(RuntimeError, match="interrupted recommendation batch"):
        persist_recommendation_tasks(
            db=db,
            decision_date="2026-08-24",
            signals=_signals(),
            current_authority_validator=lambda: None,
        )
    with sqlite3.connect(db.path) as conn:
        assert conn.execute("SELECT count(*) FROM signals").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM action_tasks").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT count(*) FROM event_log WHERE event_type='task.action.created'"
            ).fetchone()[0]
            == 0
        )
