from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from data.store import DataStore
from server.db import AppDatabase
from server.persistence.jobs import SQLiteJobStore
from server.services.market.market_universe_truth import normalize_a_share_members
from server.services.market.sync import MarketSyncRequest, MarketSyncService


@pytest.fixture
def history(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    days = []
    current = date(2025, 1, 1)
    while current.year == 2025:
        trading = current.isoformat() in {"2025-01-02", "2025-01-03"}
        days.append(
            {
                "date": current.isoformat(),
                "is_trading_day": trading,
                "day_type": "trading" if trading else "closed",
            }
        )
        current += timedelta(days=1)
    row = db.upsert_market_calendar_snapshot_sync(
        {
            "year": 2025,
            "exchange": "SSE",
            "provider": "fixture",
            "status": "available",
            "days": days,
            "trading_day_count": 2,
            "closed_day_count": 363,
            "source_fingerprint": "a" * 64,
            "limitations": [],
        }
    )
    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2025,
        source_fingerprint=row["source_fingerprint"],
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="b" * 64,
        verified_by="fixture",
    )
    store = DataStore(tmp_path)
    symbols = [str(600000 + index) for index in range(998)] + [
        "000001",
        "601999",
        "920001",
    ]
    captured = datetime(2026, 10, 19, tzinfo=timezone.utc)
    snapshot = store.save_market_universe_snapshot(
        trade_date="2026-10-19",
        provider_name="fixture",
        members=normalize_a_share_members(symbols),
        capture_started_at=captured,
        capture_completed_at=captured,
        source_metadata=[
            {
                "symbol": symbol,
                "display_name": "示例股票",
                "list_status": "L",
                "list_date": "2025-01-03" if symbol == "601999" else "2010-01-01",
            }
            for symbol in symbols
        ],
    )
    config = SimpleNamespace(
        market_data_source_policy="karkinos.market.source.cn_research.v1",
        market_data_verification_source_policy="karkinos.market.source.free_cn_research.v1",
        data_source="free",
        tushare_token="",
    )
    return tmp_path, db, store, config, snapshot


def _request(**overrides):
    return MarketSyncRequest(
        **{
            "universe": "full-market",
            "start_date": "2025-01-01",
            "end_date": "2025-01-03",
            "skip_calendar": True,
            **overrides,
        }
    )


def _partial_receipt(store, day):
    return store.ingest_market_daily_batch(
        trade_date=day,
        provider_name="tushare",
        bars=pd.DataFrame(
            [
                {
                    "symbol": "600000",
                    "timestamp": pd.Timestamp(day),
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10,
                    "volume": 1000,
                    "amount": 10000,
                }
            ]
        ),
    )


def test_partial_daily_receipts_never_complete_full_history_and_jobs_survive_restart(
    history,
):
    root, db, store, config, snapshot = history
    original = {
        day: _partial_receipt(store, day) for day in ("2025-01-02", "2025-01-03")
    }
    first = MarketSyncService(
        data_dir=root, db=db, data_store=store, config=config
    ).sync(_request())
    assert first.status == "queued"
    assert first.successful_targets == 0
    assert first.total_targets == 1000
    assert len(first.jobs) == 25
    assert first.scope["exchanges"] == ["SSE", "SZSE"]
    assert first.scope["historical_membership_verified"] is False
    assert first.scope["market_universe_snapshot_id"] == snapshot["snapshot_id"]
    jobs = SQLiteJobStore(db.path)
    planned = [jobs.get(item["job_id"]) for item in first.jobs]
    assert all(job is not None for job in planned)
    members = {row["symbol"] for job in planned for row in job.payload["instruments"]}
    assert "000001" in members
    assert "920001" not in members
    for job in planned:
        if any(row["symbol"] == "601999" for row in job.payload["instruments"]):
            memberships = job.payload["session_memberships"]
            assert "601999" not in str(memberships[0])
            assert "601999" in str(memberships[1])
    again = MarketSyncService(
        data_dir=root, db=AppDatabase(db.path), config=config
    ).sync(_request())
    assert [item["job_id"] for item in again.jobs] == [
        item["job_id"] for item in first.jobs
    ]
    assert all(jobs.get(item["job_id"]).attempt == 0 for item in first.jobs)
    assert {
        day: store.get_market_daily_ingestion_receipt(
            trade_date=day, provider_name="tushare"
        )
        for day in original
    } == original


def test_bse_requires_explicit_scope_and_force_creates_observation_not_overwrite(
    history,
):
    root, db, store, config, _ = history
    service = MarketSyncService(data_dir=root, db=db, config=config, data_store=store)
    base = service.sync(_request())
    forced = service.sync(_request(force=True))
    assert {item["job_id"] for item in base.jobs}.isdisjoint(
        item["job_id"] for item in forced.jobs
    )
    with_bse = service.sync(_request(exchanges=("SSE", "SZSE", "BSE")))
    assert with_bse.total_targets == 1001
    assert any("920001" in item["symbols"] for item in with_bse.jobs)


@pytest.mark.parametrize(
    "change",
    [
        "calendar",
        "calendar_year",
        "closed",
        "listing_dates",
        "exchange",
        "master",
        "scope",
    ],
)
def test_full_history_blocks_invalid_planning_facts_before_queue_mutation(
    history, change, monkeypatch
):
    root, db, store, config, snapshot = history
    req = _request()
    if change == "calendar":
        monkeypatch.setattr(db, "get_market_calendar_snapshot_sync", lambda **kw: None)
    elif change == "listing_dates":
        captured = datetime(2026, 10, 19, 1, tzinfo=timezone.utc)
        store.save_market_universe_snapshot(
            trade_date="2026-10-19",
            provider_name="fixture",
            members=snapshot["members"],
            capture_started_at=captured,
            capture_completed_at=captured,
            source_metadata=[
                {"symbol": row["symbol"], "display_name": "示例股票"}
                for row in snapshot["members"]
            ],
        )
    elif change == "calendar_year":
        req.start_date = "2024-01-01"
    elif change == "closed":
        req.end_date = "2025-01-01"
    elif change == "master":
        req.universe_snapshot_id = "sha256:" + "f" * 64
    elif change == "exchange":
        req.exchanges = ("UNKNOWN",)
    else:
        req.symbols = ["600000"]
    summary = MarketSyncService(
        data_dir=root, db=db, data_store=store, config=config
    ).sync(req)
    assert summary.status == "failed"
    assert summary.error
    assert summary.jobs == []
    assert SQLiteJobStore(db.path).list_recent("market_daily_verified") == []


def test_status_reads_durable_failure_and_rejects_missing_dataset_after_success(
    history,
):
    root, db, store, config, _ = history
    service = MarketSyncService(data_dir=root, db=db, data_store=store, config=config)
    submitted = service.sync(_request())
    jobs = SQLiteJobStore(db.path)
    now = datetime.now(timezone.utc)
    claimed = jobs.claim(
        "market_daily_verified", "fixture", now=now, job_id=submitted.jobs[0]["job_id"]
    )
    jobs.fail(claimed.lease, now=now, error="source_conflict", retryable=False)
    status = service.get_last_summary()
    assert status.status == "failed"
    assert status.jobs[0]["error"] == "source_conflict"
    claimed = jobs.claim(
        "market_daily_verified", "fixture", now=now, job_id=submitted.jobs[1]["job_id"]
    )
    jobs.finish(claimed.lease, now=now, result_ref="dataset:sha256:" + "e" * 64)
    status = service.get_last_summary()
    assert status.jobs[1]["status"] == "failed"
    assert status.jobs[1]["dataset_id"] is None


def test_unknown_sync_universe_never_reports_empty_success(history):
    root, db, store, config, _ = history
    service = MarketSyncService(data_dir=root, db=db, data_store=store, config=config)
    with pytest.raises(ValueError, match="market_sync_universe_invalid"):
        service.sync(MarketSyncRequest(universe="typo", skip_calendar=True))


def test_real_range_publication_is_recognized_only_after_catalog_and_replay(
    history, monkeypatch
):
    from tests.server import test_verified_daily_market_range as ranges

    root, db, store, config, _ = history
    monkeypatch.setattr(ranges, "DAYS", (date(2025, 1, 2), date(2025, 1, 3)))
    verification, primary, comparison = ranges._service(root, monkeypatch)
    service = MarketSyncService(data_dir=root, db=db, data_store=store, config=config)
    summary = service.sync(_request())
    queue = SQLiteJobStore(db.path)
    now = datetime.now(timezone.utc)
    job = queue.claim(
        "market_daily_verified", "fixture", now=now, job_id=summary.jobs[0]["job_id"]
    )
    publication = verification.run(job.payload, checked_at=now)
    queue.finish(job.lease, now=now, result_ref=publication.result_ref)
    status = service.get_last_summary()
    assert status.status == "queued"
    assert status.successful_targets == 40
    assert status.jobs[0]["status"] == "succeeded"
    assert status.jobs[0]["dataset_id"] == publication.dataset_id
    assert len(primary.calls) == len(comparison.calls) == 1

    # A different shard cannot reuse the successful shard's Dataset identity.
    other = queue.claim(
        "market_daily_verified", "fixture", now=now, job_id=summary.jobs[1]["job_id"]
    )
    queue.finish(other.lease, now=now, result_ref=publication.result_ref)
    status = service.get_last_summary()
    assert status.jobs[1]["status"] == "failed"
    assert status.jobs[1]["error"] == "market_history_dataset_scope_mismatch"
    # Further status reads are offline and never contact either provider.
    service.get_last_summary()
    assert len(primary.calls) == len(comparison.calls) == 1


def test_http_full_market_submits_same_durable_plan_and_reports_current_state(
    history, monkeypatch
):
    import asyncio
    import uuid

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from server.http.market_endpoints.dependencies import RefreshEndpointDependencies
    from server.http.market_endpoints.refresh import create_router

    root, db, store, config, snapshot = history
    service = MarketSyncService(data_dir=root, db=db, data_store=store, config=config)
    monkeypatch.setattr(
        "server.services.market.sync.get_market_sync_service", lambda **kw: service
    )
    monkeypatch.setattr(
        "server.dependencies.get_app_state",
        lambda: SimpleNamespace(data_dir=root, db=db, config=config),
    )

    def unused(*args, **kwargs):
        pytest.fail("history sync cannot invoke quote refresh")

    dependencies = RefreshEndpointDependencies(
        asset_class_map={},
        create_manual_quote_fetch_run=unused,
        default_refresh_symbols=unused,
        finish_manual_quote_fetch_run=unused,
        merged_watchlist_assets=unused,
        normalize_refresh_symbols=unused,
        publish_committed_runtime_quotes=unused,
        quote_fetch_run_asset_type=unused,
        quote_fetch_run_metadata=unused,
        refresh_one_quote=unused,
        with_default_market_indices=unused,
        asyncio_provider=lambda: asyncio,
        datetime_provider=lambda: datetime,
        uuid_provider=lambda: uuid,
        is_cn_trading_session=unused,
    )
    app = FastAPI()
    app.include_router(create_router(dependencies))
    with TestClient(app) as client:
        response = client.post(
            "/api/market/sync",
            json={
                "universe": "full-market",
                "start": "2025-01-01",
                "end": "2025-01-03",
                "skip_calendar": True,
                "exchanges": ["SSE", "SZSE"],
                "universe_snapshot_id": snapshot["snapshot_id"],
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "queued"
        assert result["scope"]["market_universe_snapshot_id"] == snapshot["snapshot_id"]
        direct = service.sync(_request(universe_snapshot_id=snapshot["snapshot_id"]))
        assert [job["job_id"] for job in result["jobs"]] == [
            job["job_id"] for job in direct.jobs
        ]
        queue = SQLiteJobStore(db.path)
        now = datetime.now(timezone.utc)
        job = queue.claim(
            "market_daily_verified",
            "fixture",
            now=now,
            job_id=result["jobs"][0]["job_id"],
        )
        queue.fail(job.lease, now=now, error="source_conflict", retryable=False)
        current = client.get("/api/market/sync/status").json()
        assert current["status"] == "failed"
        assert current["jobs"][0]["error"] == "source_conflict"
