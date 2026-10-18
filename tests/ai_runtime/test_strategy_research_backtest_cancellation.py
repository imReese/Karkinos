from __future__ import annotations

import asyncio
import sqlite3
from threading import Event
from types import SimpleNamespace

import pytest
import pytest_asyncio

from server.ai_runtime import strategy_research_backtest_workflow
from server.ai_runtime.strategy_research import (
    BACKTEST_CONFIRMATION,
    HYPOTHESIS_EXPORT_CONFIRMATION,
    FormulaBacktestRequest,
    HypothesisGenerationRequest,
)
from server.ai_runtime.strategy_research_backtest import (
    RestrictedFormulaBacktestAdapter,
)
from server.db import AppDatabase
from server.persistence.strategy_research import StrategyResearchAuditStore
from tests.ai_runtime.test_strategy_research_workflow import _service

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def research_case(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    service, selection, _, _ = _service(tmp_path, bind_account=False)
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
    hypotheses = await service.generate_hypotheses(
        HypothesisGenerationRequest(
            idempotency_key="cancellation-hypothesis",
            requested_by="human:fixture-owner",
            account_alias="strategy-only",
            research_question="Evaluate the synthetic cancellation lifecycle.",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        )
    )
    return SimpleNamespace(
        db=db,
        service=service,
        selection=selection,
        request=FormulaBacktestRequest(
            idempotency_key="cancellation-backtest",
            requested_by="human:fixture-owner",
            session_id=hypotheses["session_id"],
            draft_id=hypotheses["drafts"][0]["draft_id"],
            confirmation=BACKTEST_CONFIRMATION,
        ),
    )


async def _reopen_backtest(case):
    case.service._research_store = StrategyResearchAuditStore(case.db.path)
    return await case.service.run_formula_backtest(case.request)


def _scored_result_count(case):
    with sqlite3.connect(case.db.path) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM backtest_results WHERE id != 17"
        ).fetchone()[0]


def _assert_scored_trial_link(case, response, *, status):
    store = case.service._research_store
    row = store.get_backtest(response["backtest_run_id"])
    assert row["status"] == status
    assert row["canonical_backtest_result_id"] == 18
    assert _scored_result_count(case) == 1
    # The fixture scores three semantic parameter variants. A failed attempt
    # with persisted scores still consumes all three, even without a response.
    assert store.research_trial_family(case.selection)["nominal_trial_count"] == 3
    assert store.verify_events(response["backtest_run_id"]) == (True, [])
    assert response["reused"] is True


async def test_compute_cancellation_is_terminal_after_worker_and_store_reopen(
    research_case, monkeypatch
):
    case = research_case
    started, release, finished = Event(), Event(), Event()
    original = RestrictedFormulaBacktestAdapter.run
    calls = []

    def blocking_run(self, **kwargs):
        calls.append("run")
        started.set()
        try:
            if not release.wait(timeout=5):
                raise TimeoutError("fixture computation was not released")
            return original(self, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(RestrictedFormulaBacktestAdapter, "run", blocking_run)
    task = asyncio.create_task(case.service.run_formula_backtest(case.request))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)

    response = await _reopen_backtest(case)
    assert response["status"] == "failed"
    assert response["failure_code"] == "formula_backtest_cancelled"
    assert response["canonical_backtest"] is None
    assert response["reused"] is True
    assert calls == ["run"]
    assert _scored_result_count(case) == 0
    assert (
        case.service._research_store.research_trial_family(case.selection)[
            "nominal_trial_count"
        ]
        == 0
    )
    assert case.service._research_store.verify_events(response["backtest_run_id"]) == (
        True,
        [],
    )


@pytest.mark.parametrize("pause_after_commit", [False, True])
async def test_cancellation_waits_for_result_and_terminal_audit(
    research_case, monkeypatch, pause_after_commit
):
    """The native SQLite save has no await; this wrapper exercises the async port."""
    case = research_case
    entered, release = asyncio.Event(), asyncio.Event()
    original_save = case.db.save_backtest_result
    original_run = RestrictedFormulaBacktestAdapter.run
    calls = []

    def counted_run(self, **kwargs):
        calls.append("run")
        return original_run(self, **kwargs)

    async def paused_save(**kwargs):
        if not pause_after_commit:
            entered.set()
            await release.wait()
        result_id = await original_save(**kwargs)
        if pause_after_commit:
            entered.set()
            await release.wait()
        return result_id

    monkeypatch.setattr(RestrictedFormulaBacktestAdapter, "run", counted_run)
    monkeypatch.setattr(case.db, "save_backtest_result", paused_save)
    task = asyncio.create_task(case.service.run_formula_backtest(case.request))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        pending = await case.service.run_formula_backtest(case.request)
        assert pending["status"] == "running"
        assert pending["reused"] is True
        task.cancel()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    response = await _reopen_backtest(case)
    assert response["status"] == "completed"
    assert calls == ["run"]
    _assert_scored_trial_link(case, response, status="completed")


async def test_cancellation_before_synchronous_finish_preserves_completed_score(
    research_case, monkeypatch
):
    case = research_case
    original_finish = case.service._research_store.finish_backtest
    task = None

    def finish(*args, **kwargs):
        if kwargs["status"] == "completed":
            assert task is not None
            task.cancel()
        return original_finish(*args, **kwargs)

    monkeypatch.setattr(case.service._research_store, "finish_backtest", finish)
    task = asyncio.create_task(case.service.run_formula_backtest(case.request))
    with pytest.raises(asyncio.CancelledError):
        await task

    response = await _reopen_backtest(case)
    _assert_scored_trial_link(case, response, status="completed")


async def test_finish_failure_keeps_persisted_result_and_consumed_trials(
    research_case, monkeypatch
):
    case = research_case
    original_finish = case.service._research_store.finish_backtest

    def finish(*args, **kwargs):
        if kwargs["status"] == "completed":
            raise OSError("fixture first terminal write failed")
        return original_finish(*args, **kwargs)

    monkeypatch.setattr(case.service._research_store, "finish_backtest", finish)
    with pytest.raises(OSError, match="fixture first terminal write failed"):
        await case.service.run_formula_backtest(case.request)

    response = await _reopen_backtest(case)
    _assert_scored_trial_link(case, response, status="failed")


async def test_internal_cancellation_after_result_id_keeps_scored_trials(
    research_case, monkeypatch
):
    case = research_case

    def cancelled_fingerprint(_value):
        raise asyncio.CancelledError

    monkeypatch.setattr(
        strategy_research_backtest_workflow,
        "content_fingerprint",
        cancelled_fingerprint,
    )
    with pytest.raises(asyncio.CancelledError):
        await case.service.run_formula_backtest(case.request)

    response = await _reopen_backtest(case)
    assert response["failure_code"] == "formula_backtest_cancelled"
    _assert_scored_trial_link(case, response, status="failed")


@pytest.mark.parametrize("commit_first", [False, True])
async def test_unknown_internal_save_cancellation_remains_fail_closed(
    research_case, monkeypatch, commit_first
):
    """An injected port cancellation cannot prove whether its write committed."""
    case = research_case
    original_save = case.db.save_backtest_result

    async def interrupted_save(**kwargs):
        if commit_first:
            await original_save(**kwargs)
        raise asyncio.CancelledError

    monkeypatch.setattr(case.db, "save_backtest_result", interrupted_save)
    with pytest.raises(asyncio.CancelledError):
        await case.service.run_formula_backtest(case.request)

    response = await _reopen_backtest(case)
    assert response["status"] == "running"
    assert response["reused"] is True
    assert _scored_result_count(case) == int(commit_first)
    with pytest.raises(ValueError, match="research_trial_family_incomplete"):
        case.service._research_store.research_trial_family(case.selection)
