"""Tests for unified account paper/shadow orchestration."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from server.services.account_paper_shadow import orchestrate_account_paper_shadow


def test_orchestrate_rejects_uninitialized_database() -> None:
    fake_state = SimpleNamespace(db=None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(orchestrate_account_paper_shadow(fake_state))

    assert exc.value.status_code == 503
    assert "Database is not initialized" in exc.value.detail


def test_orchestrate_rejects_caller_supplied_base_equity() -> None:
    fake_state = SimpleNamespace(db=object())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            orchestrate_account_paper_shadow(
                fake_state,
                base_equity=50000.0,
            )
        )

    assert exc.value.status_code == 409
    assert "caller-supplied shadow base_equity is disabled" in exc.value.detail


def test_orchestrate_rejects_mismatched_run_date(monkeypatch) -> None:
    fake_state = SimpleNamespace(db=object(), config=None)
    trading_plan = {"plan_date": "2026-07-02", "order_intents": []}

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            orchestrate_account_paper_shadow(
                fake_state,
                trading_plan=trading_plan,
                run_date="2026-07-01",
            )
        )

    assert exc.value.status_code == 409
    assert "requested shadow run_date does not match" in exc.value.detail


def test_orchestrate_executes_simulation_and_emits_event(monkeypatch) -> None:
    fake_db = object()
    broadcast_events = []

    class FakeHub:
        async def broadcast(self, event):
            broadcast_events.append(event)

    fake_state = SimpleNamespace(db=fake_db, config=None, hub=FakeHub())
    trading_plan = {
        "plan_date": "2026-07-02",
        "generated_at": "2026-07-02T15:00:00+08:00",
        "order_intents": [],
    }
    canonical_run = {
        "run_id": "shadow:2026-07-02:1",
        "status": "within_expectations",
    }

    monkeypatch.setattr(
        "server.services.paper_shadow_run.run_paper_shadow_from_trading_plan",
        lambda db, trading_plan, generated_at: canonical_run,
    )

    result = asyncio.run(
        orchestrate_account_paper_shadow(
            fake_state,
            trading_plan=trading_plan,
            run_date="2026-07-02",
            broadcast_event=True,
        )
    )

    assert result == canonical_run
    assert len(broadcast_events) == 1
    assert broadcast_events[0]["event_type"] == "DailyShadowRunRecorded"
    assert broadcast_events[0]["payload"] == canonical_run


def test_orchestrate_records_automation_run(monkeypatch) -> None:
    fake_db = object()
    fake_state = SimpleNamespace(db=fake_db, config=None, hub=None)
    trading_plan = {
        "plan_date": "2026-07-02",
        "generated_at": "2026-07-02T15:00:00+08:00",
        "order_intents": [],
    }
    canonical_run = {
        "run_id": "shadow:2026-07-02:1",
        "status": "within_expectations",
    }

    recorded = []

    class FakeAutomationService:
        def record_paper_shadow_run(self, *, run_date, source_ref, paper_shadow_run):
            recorded.append((run_date, source_ref, paper_shadow_run))
            return {"automation_id": "auto:1"}

    monkeypatch.setattr(
        "server.services.paper_shadow_run.run_paper_shadow_from_trading_plan",
        lambda db, trading_plan, generated_at: canonical_run,
    )

    result = asyncio.run(
        orchestrate_account_paper_shadow(
            fake_state,
            trading_plan=trading_plan,
            automation_service=FakeAutomationService(),
        )
    )

    assert result["automation_run"] == {"automation_id": "auto:1"}
    assert result["paper_shadow_run"] == canonical_run
    assert result["broker_submission_enabled"] is False
    assert result["does_not_submit_broker_order"] is True
    assert len(recorded) == 1
    assert recorded[0] == ("2026-07-02", "shadow:2026-07-02:1", canonical_run)
