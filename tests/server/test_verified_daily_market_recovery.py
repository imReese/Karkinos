"""Recovery links preserve original jobs and feed the real BK readiness owner."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from server.db import AppDatabase
from server.persistence.jobs import SQLiteJobStore
from server.persistence.market_daily_call_budget import BUDGET_DEFERRED_CODE
from server.services.market.verified_daily_market_data import (
    provider_fallback_recovery_payload,
)
from server.services.market.verified_daily_market_jobs import (
    enqueue_verified_daily_market_recovery,
)
from server.services.research.datasets import (
    ResearchDatasetError,
    _forward_seed_jobs,
    verified_daily_job_successor,
)
from tests.server.test_job_queues import raw
from tests.server.test_verified_daily_market_fallback import (
    CHECKED,
    DAY,
    DESCRIPTORS,
    STOCKS,
    CoverageProvider,
    payload,
    service_with_sources,
)
from tests.server.test_verified_daily_market_jobs import _config


def recover(store, original, **kwargs):
    return enqueue_verified_daily_market_recovery(
        store,
        original.job_id,
        now=CHECKED + timedelta(seconds=1),
        actor="operator",
        reason="Bounded recovery",
        **kwargs,
    )


def publication(tmp_path, monkeypatch, request, *, old_capture=False):
    class FreshProvider(CoverageProvider):
        def fetch_daily_bars(self, request):
            batch = super().fetch_daily_bars(request)
            return (
                batch
                if old_capture
                else replace(
                    batch,
                    started_at=CHECKED + timedelta(seconds=3),
                    completed_at=CHECKED + timedelta(seconds=4),
                )
            )

    service = service_with_sources(
        tmp_path, monkeypatch, [FreshProvider(d) for d in DESCRIPTORS[:2]]
    )
    return service.run(request, checked_at=CHECKED + timedelta(seconds=5))


@pytest.mark.parametrize("original_state", ["queued", "budget_deferred", "failed"])
@pytest.mark.parametrize("outcome", ["succeeded", "failed"])
def test_recovery_readiness_counts_once_and_retains_all_original_history(
    tmp_path, monkeypatch, original_state, outcome
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    jobs = SQLiteJobStore(db.path)
    original = jobs.enqueue("market_daily_verified", payload(), now=CHECKED)
    if original_state != "queued":
        claimed = jobs.claim(original.kind, "original", now=CHECKED)
        jobs.fail(
            claimed.lease,
            now=CHECKED,
            error=BUDGET_DEFERRED_CODE
            if original_state == "budget_deferred"
            else "WorkerExecutionAborted",
            retryable=original_state == "budget_deferred",
            preserve_retry_allowance=original_state == "budget_deferred",
        )
    jobs.set_queue_paused(
        "bk_recovery",
        paused=True,
        expected_revision=0,
        now=CHECKED,
        actor="operator",
        reason="Keep the historical queue paused",
        job_ids=(original.job_id,),
    )
    jobs.set_queue_paused(
        "selected_recovery",
        paused=False,
        expected_revision=0,
        now=CHECKED,
        actor="operator",
        reason="Only the selected recovery may run",
    )
    original = jobs.get(original.job_id)
    before = raw(jobs, original.job_id)
    monkeypatch.setattr(
        "server.services.market.verified_daily_market_jobs.resolve_verified_closed_trading_dates_in_range",
        lambda *_args, **_kwargs: (
            SimpleNamespace(
                trade_date=DAY.isoformat(),
                calendar_evidence_refs=("calendar:fixture",),
            ),
        ),
    )

    def gate():
        return _forward_seed_jobs(
            db,
            _config(),
            expected={DAY: STOCKS},
            prefix=SimpleNamespace(end_date=DAY - timedelta(days=1)),
            through=DAY,
            now=CHECKED + timedelta(seconds=7),
            replacements={},
        )

    assert gate()["job_ids"] == [original.job_id]
    successor = recover(jobs, original, queue_name="selected_recovery")
    assert recover(jobs, original, queue_name="selected_recovery") == successor
    assert verified_daily_job_successor(jobs, original) == successor
    assert gate()["status"] == "waiting"
    assert gate()["job_ids"] == [successor.job_id]
    assert (
        jobs.claim(
            original.kind,
            "ordinary-worker",
            now=CHECKED + timedelta(days=1),
            job_id=original.job_id,
        )
        is None
    )
    claimed = jobs.claim(original.kind, "recovery", now=CHECKED + timedelta(seconds=2))
    assert claimed.job_id == successor.job_id
    assert gate()["job_ids"] == [successor.job_id]
    if outcome == "failed":
        jobs.fail(
            claimed.lease,
            now=CHECKED + timedelta(seconds=6),
            error="verified_daily_market_cross_source_conflict",
            retryable=False,
            failure_evidence_ref="verification:fixture-conflict",
        )
        report = gate()
        assert report["status"] == "blocked"
        assert report["job_ids"] == [successor.job_id]
        assert verified_daily_job_successor(jobs, original).status == "failed"
    else:
        result = publication(tmp_path, monkeypatch, successor.payload)
        jobs.finish(
            claimed.lease,
            now=CHECKED + timedelta(seconds=6),
            result_ref=result.result_ref,
        )
        ready = gate()
        assert len(ready) == 1 and ready[0].job_id == successor.job_id
        assert ready[0].status == "succeeded"
        assert gate() == ready
    assert recover(jobs, original, queue_name="selected_recovery") == jobs.get(
        successor.job_id
    )
    assert raw(jobs, original.job_id) == before
    assert jobs.queue_status("bk_recovery")["paused"] is True
    with sqlite3.connect(jobs.path) as conn:
        assert conn.execute("SELECT count(*) FROM job_runs").fetchone()[0] == 2


@pytest.mark.parametrize("case", ["old_capture", "wrong_scope", "unassociated"])
def test_queued_recovery_requires_fenced_parent_and_exact_fresh_verified_scope(
    tmp_path, monkeypatch, case
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    jobs = SQLiteJobStore(db.path)
    original = jobs.enqueue("market_daily_verified", payload(), now=CHECKED)
    before = raw(jobs, original.job_id)
    successor = (
        jobs.enqueue(
            original.kind,
            provider_fallback_recovery_payload(original.payload),
            now=CHECKED + timedelta(seconds=1),
        )
        if case == "unassociated"
        else recover(jobs, original)
    )
    claimed = jobs.claim(
        original.kind,
        "recovery",
        now=CHECKED + timedelta(seconds=2),
        job_id=successor.job_id,
    )
    request = successor.payload
    if case == "wrong_scope":
        request = {**request, "instruments": request["instruments"][:1]}
    result = publication(
        tmp_path, monkeypatch, request, old_capture=case == "old_capture"
    )
    jobs.finish(
        claimed.lease,
        now=CHECKED + timedelta(seconds=6),
        result_ref=result.result_ref,
    )
    if case == "unassociated":
        assert verified_daily_job_successor(jobs, original) == original
    else:
        with pytest.raises(ResearchDatasetError, match="scope"):
            verified_daily_job_successor(jobs, original)
    assert raw(jobs, original.job_id) == before


@pytest.mark.parametrize("state", ["running", "succeeded", "conflict"])
def test_recovery_rejects_active_completed_or_conflicting_originals(tmp_path, state):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    jobs = SQLiteJobStore(db.path)
    original = jobs.enqueue("market_daily_verified", payload(), now=CHECKED)
    claimed = jobs.claim(original.kind, "original", now=CHECKED)
    if state == "succeeded":
        jobs.finish(claimed.lease, now=CHECKED, result_ref="dataset:existing")
    elif state == "conflict":
        jobs.fail(
            claimed.lease,
            now=CHECKED,
            error="verified_daily_market_cross_source_conflict",
            retryable=True,
            failure_evidence_ref="verification:existing-conflict",
        )
    before = raw(jobs, original.job_id)
    with pytest.raises(ValueError, match="original_ineligible"):
        recover(jobs, original)
    assert jobs.get_successor(original.job_id) is None
    assert raw(jobs, original.job_id) == before
