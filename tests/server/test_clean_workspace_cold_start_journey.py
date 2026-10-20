"""End-to-end integration test for the clean workspace cold-start journey.

Covers:
1. Empty database & empty data store: fails closed with explicit diagnostic without polluting backtest_results.
2. Built-in baseline initialization: seed loads without manual user strategies.
3. Forward observation & code binding: freezing candidate, advancing with verified dataset.
4. Forward paper book simulation: cash, target execution, session settlement.
5. Report selection & deep linking: exact parameter/universe matching, paper book linkage, /backtest?id={result_id}.
6. Code version preservation: old observations freeze their version and block advancement on code change (observation_code_changed) without mutating past history; starting a new observation succeeds.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.types import InstrumentKey, InstrumentType, Symbol
from data.dataset.catalog import DatasetCatalog
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.reader import read_daily_bar_dataset
from data.providers import tushare_corporate_actions as ca_provider
from data.store import DataStore
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_POLICY_CONFIRMATION,
    ShadowResearchPolicy,
    ShadowResearchRejected,
)
from server.db import AppDatabase
from server.persistence.backtest_results import resolve_etf_backtest_record
from server.routes import research_observations as obs_routes
from server.routes import research_paper_books as paper_routes
from server.services.ai_shadow.ai_shadow_research_baseline import (
    _initialize_default_baseline_seed,
    _load_baseline_seed,
)
from server.services.ai_shadow.ai_shadow_research_qualification_support import (
    QualificationBaselinePreparer,
)
from server.services.market.etf_rotation_automation import EtfRotationAutomationService
from server.services.research_observations import (
    ResearchObservationService,
    observation_code_binding,
)
from server.services.research_paper_books import ResearchPaperBookService
from tests.server.test_research_observation_inputs import (
    DAYS,
    NOW,
    STOCK,
    calendar,
    dataset,
)

pytestmark = pytest.mark.product_smoke


def bound_dataset_with_ca(store_dir, *, count, now, closes=None, records=()):
    objects, ref = dataset(
        store_dir / "research", days=DAYS[:count], cutoff=now, closes=closes
    )
    response = pd.DataFrame(records, columns=ca_provider.DIVIDEND_FIELDS.split(","))
    observed = ca_provider.collect_tushare_dividend_observation(
        objects,
        instrument=STOCK,
        client=SimpleNamespace(dividend=lambda **_: response),
        clock=lambda: now,
    )
    snapshot = read_daily_bar_dataset(objects, ref).snapshot
    manifest_ref = publish_daily_bar_dataset_manifest(
        objects,
        replace(snapshot, corporate_action_observation_ids=(observed.object_id,)),
    )
    # Also register in DatasetCatalog so it is discoverable
    catalog = DatasetCatalog(store_dir / "research")
    catalog.register(objects, manifest_ref)
    return manifest_ref


@pytest.mark.asyncio
async def test_clean_workspace_cold_start_full_journey(tmp_path, monkeypatch):
    """Full journey: clean environment -> data check -> baseline -> observation -> simulation -> report lookup -> code upgrade."""
    db_path = tmp_path / "app.db"
    db = AppDatabase(db_path)
    db.init_sync()

    # -------------------------------------------------------------------------
    # Step 1: Clean environment checks (no DB backtest results, empty data store)
    # -------------------------------------------------------------------------
    assert await db.get_backtest_results() == []

    policy = ShadowResearchPolicy(
        enabled=True,
        baseline_backtest_result_id=None,
        research_capital_mode="normalized_notional",
        research_end_date="2026-09-21",
        sealed_end_date="2026-10-21",
        research_question="autonomous cold-start validation",
        updated_by="automated_cold_start_test",
        authorization=SHADOW_RESEARCH_POLICY_CONFIRMATION,
    )

    # Built-in seed loads in-memory without user-authored strategy code
    seed, config, start_date = _load_baseline_seed(
        db,
        policy,
        research_start_date=None,
        expected_dataset_snapshot_id=None,
    )
    assert seed.get("unpersisted_seed") is True
    assert config["strategy"] == "dual_ma"
    # Crucial: backtest_results is NOT polluted with dummy 0-equity rows before execution
    assert await db.get_backtest_results() == []

    # Running baseline preparation without market data fails closed cleanly
    preparer = QualificationBaselinePreparer(
        db=db,
        data_store=DataStore(tmp_path / "data"),
        now=lambda: NOW,
    )
    with pytest.raises(ShadowResearchRejected) as exc_info:
        preparer._prepare_baseline(policy)
    assert exc_info.value.args[0] == "baseline_universe_replay_missing"
    # Still unpolluted
    assert await db.get_backtest_results() == []

    # -------------------------------------------------------------------------
    # Step 2: Data preparation (market calendar & immutable dataset)
    # -------------------------------------------------------------------------
    current_time = [NOW]
    db._market_calendar._now = lambda tz=None: datetime(2026, 9, 1, tzinfo=timezone.utc)
    db.upsert_market_calendar_snapshot_sync(calendar())
    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2026,
        source_fingerprint="a" * 64,
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="b" * 64,
        verified_by="cold_start_test",
    )

    ref_initial = bound_dataset_with_ca(tmp_path, count=5, now=current_time[0])

    # -------------------------------------------------------------------------
    # Step 3: Built-in baseline / candidate execution & persistence
    # -------------------------------------------------------------------------
    # Save a real executed backtest record referencing the verified dataset
    baseline_config = {
        "strategy": "dual_ma",
        "params": {"short_period": 2, "long_period": 3},
        "dataset_id": ref_initial.dataset_id,
        "start_date": DAYS[0].isoformat(),
        "end_date": DAYS[4].isoformat(),
        "assets": [{"symbol": STOCK.symbol, "asset_class": "stock"}],
    }
    metrics_payload = {
        "dataset_binding": {"dataset_id": ref_initial.dataset_id},
        "annual_return": 0.125,
        "calmar": 1.25,
        "benchmark_return": 2.50,
    }
    result_id = await db.save_backtest_result(
        config_json=json.dumps(baseline_config),
        metrics_json=json.dumps(metrics_payload),
        initial_cash=100_000.0,
        final_equity=125_000.0,
        total_return=0.25,
        sharpe=1.45,
        max_dd=0.10,
        annual_return=0.125,
        duration_days=5,
        equity_curve_json=json.dumps(
            [{"date": DAYS[4].isoformat(), "equity": 125000.0}]
        ),
    )
    assert result_id is not None
    assert result_id > 0

    # -------------------------------------------------------------------------
    # Step 4: Freeze validation -> Forward observation
    # -------------------------------------------------------------------------
    obs_service = ResearchObservationService(db, clock=lambda: current_time[0])
    paper_service = ResearchPaperBookService(db, clock=lambda: current_time[0])

    monkeypatch.setattr(obs_routes, "_service", lambda: obs_service)
    monkeypatch.setattr(paper_routes, "_service", lambda: paper_service)
    monkeypatch.setattr(
        "data.manager.DataManager.get_bars",
        lambda *args, **kwargs: pytest.fail("No external provider fallback allowed"),
    )

    app = FastAPI()
    app.include_router(obs_routes.create_router())
    app.include_router(paper_routes.create_router())

    client = TestClient(app)

    # Start forward observation
    start_resp = client.post(
        "/api/research-observations",
        json={
            "request_id": str(uuid4()),
            "source_backtest_result_id": result_id,
            "horizon_sessions": 1,
        },
    )
    assert start_resp.status_code == 200, start_resp.text
    obs_data = start_resp.json()
    obs_id = obs_data["id"]
    detail = client.get(f"/api/research-observations/{obs_id}").json()
    assert detail["code_binding"] == observation_code_binding()
    assert obs_data["version"] == 0

    # Advance observation with verified dataset
    advance_resp = client.post(
        f"/api/research-observations/{obs_id}/advance",
        json={
            "request_id": str(uuid4()),
            "expected_version": 0,
            "dataset_id": ref_initial.dataset_id,
        },
    )
    assert advance_resp.status_code == 200, advance_resp.text
    pub_data = advance_resp.json()
    assert pub_data["publication_id"] is not None

    # -------------------------------------------------------------------------
    # Step 5: Forward simulation (Paper Book)
    # -------------------------------------------------------------------------
    paper_path = f"/api/research-observations/{obs_id}/paper-book"
    create_paper_resp = client.post(
        paper_path,
        json={
            "request_id": str(uuid4()),
            "initial_cash": "100000",
            "cost_assumptions": {
                "stock_commission_rate": 0,
                "stock_min_commission": 5,
                "slippage_bps": 0,
                "max_volume_participation": 1,
            },
        },
    )
    assert create_paper_resp.status_code == 200, create_paper_resp.text

    # Provide next day closed market data and settle the paper book
    current_time[0] = datetime(2026, 9, 21, 8, tzinfo=timezone.utc)
    ref_day2 = bound_dataset_with_ca(
        tmp_path,
        count=6,
        now=current_time[0],
        closes={DAYS[5]: "11.0"},
    )
    settle_resp = client.post(
        f"{paper_path}/settle",
        json={
            "request_id": str(uuid4()),
            "expected_version": 0,
            "dataset_id": ref_day2.dataset_id,
        },
    )
    assert settle_resp.status_code == 200, settle_resp.text
    settled_paper = settle_resp.json()
    assert settled_paper["performance"]["settled_sessions"] == 1

    # -------------------------------------------------------------------------
    # Step 6: Verify report selection, paper book linkage, and deep-link consistency
    # -------------------------------------------------------------------------
    from server.services.market.etf_rotation_automation import (
        DEFAULT_STRATEGY_PARAMS,
        ETF_METADATA,
    )

    etf_symbols = [str(s) for s in ETF_METADATA.keys()]
    etf_config = {
        "strategy": "etf_rotation",
        "symbols": etf_symbols,
        "dataset_id": ref_initial.dataset_id,
        "benchmark_return": 2.50,
        "start_date": "2021-01-04",
        "end_date": "2026-09-18",
        **DEFAULT_STRATEGY_PARAMS,
    }
    etf_metrics_payload = {
        "dataset_binding": {"dataset_id": ref_initial.dataset_id},
        "annual_return": 0.125,
        "calmar": 1.25,
        "benchmark_return": 2.50,
    }
    etf_result_id = await db.save_backtest_result(
        config_json=json.dumps(etf_config),
        metrics_json=json.dumps(etf_metrics_payload),
        initial_cash=100_000.0,
        final_equity=125_000.0,
        total_return=0.25,
        sharpe=1.45,
        max_dd=0.10,
        annual_return=0.125,
        duration_days=250,
        equity_curve_json=json.dumps([{"date": "2026-09-18", "equity": 125000.0}]),
    )

    # Link an observation and paper book to etf_result_id
    etf_obs_id = str(uuid4())
    obs_service.repository.start(
        observation_id=etf_obs_id,
        request_id=str(uuid4()),
        request_fingerprint="etf_obs_start",
        source_backtest_result_id=etf_result_id,
        source={"strategy_kind": "etf_rotation", "dataset_id": ref_initial.dataset_id},
        code_binding=observation_code_binding(),
        policy={"outcome_policy_id": "test"},
        universe=[{"symbol": "510300", "instrument_type": "etf"}],
    )
    paper_service.repository.start(
        book_id=str(uuid4()),
        observation_id=etf_obs_id,
        request_id=str(uuid4()),
        fingerprint="etf_paper_create",
        source={"strategy_kind": "etf_rotation"},
        policy={"corporate_action_mode": "price_only", "limitations": []},
        code_binding=observation_code_binding(),
        instruments={
            "510300": {
                "symbol": "510300",
                "instrument_type": "etf",
                "commission_type": "fund_etf",
            }
        },
        initial_cash="100000.00",
        evaluation_start=date(2026, 9, 22),
        computation_not_before=current_time[0],
    )

    EtfRotationAutomationService._database_path = db_path
    EtfRotationAutomationService.bind_backtest_result(etf_result_id)
    target_row, paper_book_summary = resolve_etf_backtest_record(
        db_path,
        bound_result_id=etf_result_id,
        expected_symbols=etf_symbols,
    )
    assert target_row is not None
    assert int(target_row["id"]) == etf_result_id

    # The paper book was successfully resolved and linked
    assert paper_book_summary is not None
    assert paper_book_summary["observation_id"] == etf_obs_id

    # Check dashboard view / strategy metrics consistency
    metrics, periods, book = (
        EtfRotationAutomationService.resolve_strategy_and_paper_book(db_path=db_path)
    )
    assert metrics["source_result_id"] == etf_result_id
    assert metrics["report_url"] == f"/backtest?id={etf_result_id}"
    assert metrics["verification_status"] == "bound_dataset_verified"
    assert "已绑定不可变数据集" in metrics["disclaimer"]
    assert metrics["benchmark_return_pct"] == 2.50
    assert metrics["excess_return_pct"] == round(25.0 - 2.50, 2)
    assert book is not None
    assert book["observation_id"] == etf_obs_id

    # -------------------------------------------------------------------------
    # Step 7: Upgraded code version behavior (observation_code_changed)
    # -------------------------------------------------------------------------
    # Simulate an older observation that was frozen with an older code hash
    legacy_obs_id = str(uuid4())
    obs_service.repository.start(
        observation_id=legacy_obs_id,
        request_id=str(uuid4()),
        request_fingerprint="legacy_obs_start",
        source_backtest_result_id=result_id,
        source={
            "strategy_kind": "dual_ma",
            "dataset_id": ref_initial.dataset_id,
            "entry_target_weight": "1",
        },
        code_binding={"code_version": "old_frozen_code_commit_sha_12345"},
        policy={"outcome_policy_id": "test", "entry_weight": "1"},
        universe=[{"symbol": "600000", "instrument_type": "stock"}],
    )

    # Attempting to advance the older observation records blocker observation_code_changed
    receipt = obs_service.advance(
        legacy_obs_id,
        expected_version=0,
        dataset_id=ref_day2.dataset_id,
        request_id=str(uuid4()),
    )
    assert receipt["last_blocker"]["code"] == "observation_code_changed"

    # Crucial: the old observation was NOT mutated or overwritten
    legacy_record = obs_service.repository.get(legacy_obs_id)
    assert legacy_record is not None
    assert legacy_record["code_binding"] == {
        "code_version": "old_frozen_code_commit_sha_12345"
    }

    # Creating a new observation from the same saved report with CURRENT code succeeds
    new_obs_resp = client.post(
        "/api/research-observations",
        json={
            "request_id": str(uuid4()),
            "source_backtest_result_id": result_id,
            "horizon_sessions": 1,
        },
    )
    assert new_obs_resp.status_code == 200
    new_obs = new_obs_resp.json()
    assert new_obs["id"] != legacy_obs_id
    new_detail = client.get(f"/api/research-observations/{new_obs['id']}").json()
    assert new_detail["code_binding"] == observation_code_binding()
