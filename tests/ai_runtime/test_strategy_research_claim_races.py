from __future__ import annotations

import asyncio
import sqlite3
from threading import Event, Lock
from types import SimpleNamespace

import pytest

from server.contracts.strategy_research import (
    BACKTEST_CONFIRMATION,
    CRITIQUE_EXPORT_CONFIRMATION,
    HYPOTHESIS_EXPORT_CONFIRMATION,
    CritiqueRequest,
    FormulaBacktestRequest,
    HypothesisGenerationRequest,
)
from server.db import AppDatabase
from server.persistence.strategy_research import StrategyResearchAuditStore
from tests.ai_runtime.test_strategy_research_workflow import (
    BlockingFixtureTransport,
    _service,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def research_case(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    service, selection, transport, _ = _service(tmp_path, bind_account=False)
    baseline = {**service._db.rows[17], "equity_curve_json": "[]"}
    columns = tuple(baseline)
    with sqlite3.connect(db.path) as connection:
        connection.execute(
            "INSERT INTO backtest_results ("
            + ",".join(columns)
            + ") VALUES ("
            + ",".join("?" for _ in columns)
            + ")",
            tuple(baseline[column] for column in columns),
        )
    service._db = db
    return SimpleNamespace(
        db=db,
        service=service,
        transport=transport,
        hypothesis=HypothesisGenerationRequest(
            idempotency_key="claim-race-hypothesis",
            requested_by="human:fixture-owner",
            account_alias="strategy-only",
            research_question="Evaluate the synthetic pending claim race.",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        ),
    )


def _assert_audit(case, entity_id, workflow_id):
    assert case.service._research_store.verify_events(entity_id) == (True, [])
    assert case.service._ai_store.verify_replay(workflow_id).valid


@pytest.mark.parametrize("winner_finishes_first", [False, True])
async def test_pending_hypothesis_claim_loser_only_reads_winner(
    research_case, monkeypatch, winner_finishes_first
):
    case = research_case
    transport = BlockingFixtureTransport(list(case.transport._responses))
    monkeypatch.setattr(case.service, "_transport", transport)
    captured, release = asyncio.Event(), asyncio.Event()
    capture = case.service._capture_service.capture
    capture_calls = 0

    async def held_capture(request):
        nonlocal capture_calls
        result = await capture(request)
        capture_calls += 1
        if capture_calls == 1:
            captured.set()
            await release.wait()
        return result

    finishes = []
    finish = case.service._research_store.finish_session

    def record_finish(*args, **kwargs):
        finishes.append(kwargs["status"])
        return finish(*args, **kwargs)

    monkeypatch.setattr(case.service._capture_service, "capture", held_capture)
    monkeypatch.setattr(case.service._research_store, "finish_session", record_finish)
    first = asyncio.create_task(case.service.generate_hypotheses(case.hypothesis))
    winner = None
    try:
        await asyncio.wait_for(captured.wait(), 5)
        with sqlite3.connect(case.db.path) as connection:
            assert connection.execute(
                "SELECT status FROM ai_strategy_research_sessions"
            ).fetchone() == ("pending",)
        winner = asyncio.create_task(case.service.generate_hypotheses(case.hypothesis))
        assert await asyncio.to_thread(transport.started.wait, 5)
        if winner_finishes_first:
            transport.release.set()
            await winner
        release.set()
        loser = await first
        assert loser["status"] == ("completed" if winner_finishes_first else "running")
        assert loser["reused"] is True
        assert finishes == (["completed"] if winner_finishes_first else [])
        transport.release.set()
        completed = await winner
    finally:
        release.set()
        transport.release.set()
        await asyncio.gather(
            *(task for task in (first, winner) if task is not None),
            return_exceptions=True,
        )

    assert completed["status"] == "completed"
    assert completed["session_id"] == loser["session_id"]
    assert len(transport.calls) == 1
    assert finishes == ["completed"]
    case.service._research_store = StrategyResearchAuditStore(case.db.path)
    reopened = case.service.get_session(completed["session_id"])
    assert reopened["status"] == "completed"
    assert reopened["drafts"] == completed["drafts"]
    _assert_audit(case, completed["session_id"], completed["workflow"]["workflow_id"])


@pytest.mark.parametrize("winner_finishes_first", [False, True])
async def test_pending_critique_claim_loser_only_reads_winner(
    research_case, monkeypatch, winner_finishes_first
):
    case = research_case
    hypotheses = await case.service.generate_hypotheses(case.hypothesis)
    draft_id = hypotheses["drafts"][0]["draft_id"]
    backtest = await case.service.run_formula_backtest(
        FormulaBacktestRequest(
            idempotency_key="claim-race-backtest",
            requested_by="human:fixture-owner",
            session_id=hypotheses["session_id"],
            draft_id=draft_id,
            confirmation=BACKTEST_CONFIRMATION,
        )
    )
    request = CritiqueRequest(
        idempotency_key="claim-race-critique",
        requested_by="human:fixture-owner",
        session_id=hypotheses["session_id"],
        draft_id=draft_id,
        backtest_run_id=backtest["backtest_run_id"],
        confirmation=CRITIQUE_EXPORT_CONFIRMATION,
    )
    transport = BlockingFixtureTransport(list(case.transport._responses))
    monkeypatch.setattr(case.service, "_transport", transport)
    entered, release, lock = Event(), Event(), Lock()
    resolve = case.service._resolve_reviewed_fee_schedule
    resolve_calls = 0

    def held_resolve(*args, **kwargs):
        nonlocal resolve_calls
        with lock:
            resolve_calls += 1
            ordinal = resolve_calls
        if ordinal == 1:
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("fixture fee resolution was not released")
        return resolve(*args, **kwargs)

    finishes = []
    finish = case.service._research_store.finish_critique

    def record_finish(*args, **kwargs):
        finishes.append(kwargs["status"])
        return finish(*args, **kwargs)

    monkeypatch.setattr(case.service, "_resolve_reviewed_fee_schedule", held_resolve)
    monkeypatch.setattr(case.service._research_store, "finish_critique", record_finish)
    first = asyncio.create_task(case.service.critique(request))
    winner = None
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        with sqlite3.connect(case.db.path) as connection:
            assert connection.execute(
                "SELECT status FROM ai_strategy_backtest_critiques"
            ).fetchone() == ("pending",)
        winner = asyncio.create_task(case.service.critique(request))
        assert await asyncio.to_thread(transport.started.wait, 5)
        if winner_finishes_first:
            transport.release.set()
            await winner
        release.set()
        loser = await first
        assert loser["status"] == ("completed" if winner_finishes_first else "running")
        assert loser["reused"] is True
        assert finishes == (["completed"] if winner_finishes_first else [])
        transport.release.set()
        completed = await winner
    finally:
        release.set()
        transport.release.set()
        await asyncio.gather(
            *(task for task in (first, winner) if task is not None),
            return_exceptions=True,
        )

    assert completed["status"] == "completed"
    assert completed["critique_id"] == loser["critique_id"]
    assert len(transport.calls) == 1
    assert finishes == ["completed"]
    case.service._research_store = StrategyResearchAuditStore(case.db.path)
    reopened = case.service._research_store.get_critique(completed["critique_id"])
    assert reopened["status"] == "completed"
    assert reopened["artifact"] == completed["artifact"]
    _assert_audit(case, completed["critique_id"], reopened["workflow_id"])
