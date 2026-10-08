"""Frozen corporate-action observations flow through the real Dataset/API owners."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from analytics.dataset_snapshot import (
    backtest_dataset_snapshot_content_id,
    verify_backtest_dataset_snapshot_replay,
)
from core.types import InstrumentKey, InstrumentType
from data.dataset.manifest import (
    publish_daily_bar_dataset_manifest,
    serialize_daily_bar_dataset_manifest,
)
from data.dataset.model import DatasetRef
from data.dataset.reader import (
    DatasetReaderIntegrityError,
    read_daily_bar_dataset,
    read_dataset_corporate_action_evidence,
)
from data.market.contracts import DailyBarRequest
from data.providers import tushare_corporate_actions as provider_module
from data.providers.tdx import TdxDailyBarProvider, TdxRuntimeSettings
from data.storage.objects import ContentAddressedObjectStore
from server.config import ServerConfig
from server.db import AppDatabase
from server.dependencies import AppState, AppStateContextMiddleware
from server.routes.backtest import create_router
from server.services.backtest_dataset_inputs import load_dataset_backtest_inputs
from server.services.research_datasets import (
    ResearchDatasetError,
    ResearchDatasetService,
    prepare_daily_dataset,
)
from tests.data.dataset.test_manifest import _snapshot
from tests.data.dataset.test_verified_manifest_v2 import _verified_snapshot
from tests.server.test_research_datasets import _DAYS, _backtest_request, _publish

CAPTURED = datetime(2026, 10, 1, 8, tzinfo=timezone.utc)
STOCK = InstrumentKey("600000", InstrumentType.STOCK)


def _response(symbol="600000.SH"):
    row = dict.fromkeys(provider_module.DIVIDEND_FIELDS.split(","))
    row.update(
        ts_code=symbol,
        div_proc="实施",
        end_date="20251231",
        ann_date="20260820",
        imp_ann_date="20260901",
        record_date="20260908",
        ex_date="20260909",
        pay_date="20260909",
        cash_div_tax="0.1",
        cash_div="0.09",
        stk_div="0",
        stk_bo_rate="0",
        stk_co_rate="0",
    )
    return pd.DataFrame([row])


def _observe(store, *, instrument=STOCK, at=CAPTURED):
    return provider_module.collect_tushare_dividend_observation(
        store,
        instrument=instrument,
        client=SimpleNamespace(
            dividend=lambda **_: _response(f"{instrument.symbol}.SH")
        ),
        clock=lambda: at,
    )


@pytest.fixture
def client_context(tmp_path, monkeypatch):
    root = tmp_path / "research"
    original = _publish(root)
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    state = AppState()
    state.db = db
    state.config = ServerConfig(tushare_token="fixture-secret")
    state.research_datasets = ResearchDatasetService(root, TdxRuntimeSettings())
    app = FastAPI()
    app.add_middleware(AppStateContextMiddleware, app_state=state)
    app.include_router(create_router())
    monkeypatch.setenv("KARKINOS_BACKTEST_REPORT_DIR", str(tmp_path / "reports"))
    with TestClient(app) as client:
        yield client, state, original, ContentAddressedObjectStore(root / "objects")


def _fake_external_call(monkeypatch):
    calls = []
    collect = provider_module.collect_tushare_dividend_observation

    def observed(store, *, instrument, token):
        calls.append((instrument, token))
        return collect(
            store,
            instrument=instrument,
            client=SimpleNamespace(dividend=lambda **_: _response()),
            clock=lambda: CAPTURED + timedelta(minutes=len(calls)),
        )

    monkeypatch.setattr(
        provider_module, "collect_tushare_dividend_observation", observed
    )
    return calls


@pytest.mark.parametrize(
    "verified,expected_digest",
    [
        (False, "e736716012b75dc5331dfe61c8277f1131dee36c04237c6914b516c462af92bb"),
        (True, "9aa7b956eaed68f8695513e5ff528bcb195aff460c5592d1ff248c92029be05f"),
    ],
)
def test_legacy_manifest_bytes_match_pre_corporate_action_serializer(
    verified, expected_digest
):
    # Golden digests were generated from the committed v1/v2 serializer.
    snapshot = _snapshot()
    if verified:
        snapshot = replace(
            snapshot,
            partitions=tuple(
                replace(item, verification_id="sha256:" + "e" * 64)
                for item in snapshot.partitions
            ),
        )
    assert (
        hashlib.sha256(serialize_daily_bar_dataset_manifest(snapshot)).hexdigest()
        == expected_digest
    )


@pytest.mark.parametrize("verified", [False, True])
def test_v3_binding_preserves_original_v1_v2_bytes_and_bar_lineage(tmp_path, verified):
    store = ContentAddressedObjectStore(tmp_path / "objects")
    if verified:
        snapshot, _ = _verified_snapshot(store)
        original = publish_daily_bar_dataset_manifest(store, snapshot)
    else:
        original = _publish(tmp_path)
    before = read_daily_bar_dataset(store, original)
    original_bytes = store.read_bytes(original.manifest_ref)
    old_manifest = json.loads(original_bytes)
    assert (
        old_manifest["schema_version"]
        == f"karkinos.dataset_manifest.v{2 if verified else 1}"
    )
    assert "corporate_action_observation_ids" not in old_manifest
    observation = _observe(store)
    updated = replace(
        before.snapshot,
        cutoff=CAPTURED,
        corporate_action_observation_ids=(observation.object_id,),
    )
    bound = publish_daily_bar_dataset_manifest(store, updated)
    replayed = read_daily_bar_dataset(store, bound)
    manifest = json.loads(store.read_bytes(bound.manifest_ref))
    assert manifest["schema_version"] == "karkinos.dataset_manifest.v3"
    assert manifest["partitions"] == old_manifest["partitions"]
    assert bound != original
    assert replayed.bars == before.bars
    assert replayed.snapshot == updated
    assert replayed.corporate_action_evidence["returns_modeled"] is False
    assert store.read_bytes(original.manifest_ref) == original_bytes
    assert publish_daily_bar_dataset_manifest(store, before.snapshot) == original


def test_explicit_capture_refresh_and_offline_backtest_product_flow(
    client_context, monkeypatch
):
    client, state, original, store = client_context
    before = read_daily_bar_dataset(store, original)
    calls = _fake_external_call(monkeypatch)
    path = f"/api/backtest/datasets/{original.dataset_id}/corporate-actions"
    response = client.post(path, json={})
    assert response.status_code == 200, response.text
    prepared = response.json()
    bound = DatasetRef(store.resolve_ref(prepared["dataset_id"]))
    assert len(calls) == 1
    assert prepared["reused"] is False
    assert bound != original
    summary = dict(prepared["corporate_action_evidence"])
    assert summary.pop("oldest_captured_at") == summary["captured_at"]
    # Operational freshness is not added to persisted research-report bindings.
    assert summary["matched_event_count"] == 1
    assert summary["coverage_status"] == "provider_reported_only"
    assert summary["historical_availability_verified"] is False
    assert summary["returns_modeled"] is False
    assert prepared["point_in_time_verified"] is False
    assert datetime.fromisoformat(prepared["cutoff"]) == CAPTURED + timedelta(minutes=1)
    assert "fixture-secret" not in response.text
    assert read_daily_bar_dataset(store, original) == before

    # Already-bound data can be reused without a token; browsing and running are offline.
    state.config.tushare_token = ""
    bound_path = f"/api/backtest/datasets/{bound.dataset_id}/corporate-actions"
    reused = client.post(bound_path, json={"refresh": False})
    assert reused.status_code == 200
    assert reused.json()["dataset_id"] == bound.dataset_id
    assert reused.json()["reused"] is True
    listed = client.get("/api/backtest/datasets").json()
    assert {item["dataset_id"] for item in listed["datasets"]} == {
        original.dataset_id,
        bound.dataset_id,
    }
    result = client.post(
        "/api/backtest/run", json=_backtest_request(bound).model_dump(mode="json")
    )
    assert result.status_code == 200, result.text
    report = result.json()
    saved = client.get(f"/api/backtest/results/{report['id']}").json()
    snapshot = saved["metrics_json"]["dataset_snapshot"]
    assert (
        saved["metrics_json"]["dataset_binding"]["corporate_action_evidence"] == summary
    )
    assert snapshot["corporate_action_evidence"] == summary
    assert snapshot["research_use"] == "exploratory_backtest"
    replay = verify_backtest_dataset_snapshot_replay(
        snapshot, store_root=state.db.path.parent
    )
    assert replay["status"] == "pass", replay
    for mutation in ("remove", "count"):
        edited = deepcopy(snapshot)
        if mutation == "remove":
            del edited["corporate_action_evidence"]
        else:
            edited["corporate_action_evidence"]["matched_event_count"] += 1
        # A freshly signed report still cannot disagree with its frozen Dataset.
        edited.pop("snapshot_id")
        edited["snapshot_id"] = backtest_dataset_snapshot_content_id(edited)
        rejected = verify_backtest_dataset_snapshot_replay(
            edited, store_root=state.db.path.parent
        )
        assert rejected["status"] == "blocked"
        assert rejected["blockers"] == [
            "dataset_replay_immutable_dataset_binding_mismatch"
        ]
    assert len(calls) == 1

    state.config.tushare_token = "fixture-secret"
    refreshed = client.post(bound_path, json={"refresh": True})
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["dataset_id"] != bound.dataset_id
    assert len(calls) == 2
    assert read_daily_bar_dataset(store, bound).corporate_action_evidence == summary


@pytest.mark.parametrize(
    "defect", ["after_cutoff", "wrong_instrument", "missing", "duplicate"]
)
def test_reader_rejects_invalid_observation_binding(tmp_path, defect):
    original = _publish(tmp_path)
    store = ContentAddressedObjectStore(tmp_path / "objects")
    snapshot = read_daily_bar_dataset(store, original).snapshot
    observation = _observe(
        store,
        instrument=InstrumentKey("600001", InstrumentType.STOCK)
        if defect == "wrong_instrument"
        else STOCK,
    )
    ids = (observation.object_id,)
    if defect == "missing":
        ids = ("sha256:" + "f" * 64,)
    elif defect == "duplicate":
        ids += (_observe(store, at=CAPTURED + timedelta(minutes=1)).object_id,)
    bound = publish_daily_bar_dataset_manifest(
        store,
        replace(
            snapshot,
            cutoff=snapshot.cutoff
            if defect == "after_cutoff"
            else CAPTURED + timedelta(days=1),
            corporate_action_observation_ids=ids,
        ),
    )
    with pytest.raises(DatasetReaderIntegrityError):
        read_daily_bar_dataset(store, bound)


def test_multi_stock_evidence_requires_exact_coverage_and_aggregates_latest_capture(
    tmp_path,
):
    original = _publish(tmp_path)
    store = ContentAddressedObjectStore(tmp_path / "objects")
    second = InstrumentKey("600001", InstrumentType.STOCK)
    snapshot = replace(
        read_daily_bar_dataset(store, original).snapshot,
        instruments=(STOCK, second),
        cutoff=CAPTURED + timedelta(days=1),
        corporate_action_observation_ids=(_observe(store).object_id,),
    )
    with pytest.raises(DatasetReaderIntegrityError, match="coverage_mismatch"):
        read_dataset_corporate_action_evidence(store, snapshot)
    latest = CAPTURED + timedelta(minutes=1)
    snapshot = replace(
        snapshot,
        corporate_action_observation_ids=(
            *snapshot.corporate_action_observation_ids,
            _observe(store, instrument=second, at=latest).object_id,
        ),
    )
    summary = read_dataset_corporate_action_evidence(store, snapshot)
    assert summary["matched_event_count"] == 2
    assert summary["total_record_count"] == 2
    assert summary["available_at"] == summary["captured_at"] == latest.isoformat()
    assert "oldest_captured_at" not in summary
    fresh = read_dataset_corporate_action_evidence(
        store, snapshot, include_capture_freshness=True
    )
    assert fresh.pop("oldest_captured_at") == CAPTURED.isoformat()
    assert fresh == summary
    assert {event["symbol"] for event in summary["events"]} == {"600000", "600001"}
    assert summary["returns_modeled"] is False


def test_etf_capture_is_rejected_before_any_provider_call(client_context, monkeypatch):
    client, state, _, _ = client_context
    response = {
        field: pd.DataFrame([[value]], index=[_DAYS[0]], columns=["510300.SH"])
        for field, value in zip(
            ("Open", "High", "Low", "Close", "Volume", "Amount"),
            (10.4, 11, 10, 10.5, 10000, 10.5),
            strict=True,
        )
    }
    provider = TdxDailyBarProvider(
        SimpleNamespace(get_market_data=lambda **_: response), clock=lambda: CAPTURED
    )
    etf = prepare_daily_dataset(
        state.research_datasets.root,
        request=DailyBarRequest(
            (InstrumentKey("510300", InstrumentType.ETF),), _DAYS[0], _DAYS[0]
        ),
        dates=(_DAYS[0],),
        provider=provider,
    )
    calls = _fake_external_call(monkeypatch)
    response = client.post(
        f"/api/backtest/datasets/{etf.dataset_id}/corporate-actions", json={}
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "dataset_corporate_actions_stock_only"
    assert calls == []


def test_corrupt_observation_blocks_browse_and_backtest_without_recapture(
    client_context, monkeypatch
):
    client, _, original, store = client_context
    calls = _fake_external_call(monkeypatch)
    prepared = client.post(
        f"/api/backtest/datasets/{original.dataset_id}/corporate-actions", json={}
    ).json()
    bound = DatasetRef(store.resolve_ref(prepared["dataset_id"]))
    observation_id = prepared["corporate_action_evidence"]["observation_ids"][0]
    digest = observation_id.removeprefix("sha256:")
    path = store.root / "sha256" / digest[:2] / digest[2:]
    path.chmod(0o600)
    path.write_bytes(b"corrupt")
    status = client.get("/api/backtest/datasets").json()
    assert status["unreadable_dataset_count"] == 1
    assert [item["dataset_id"] for item in status["datasets"]] == [original.dataset_id]
    with pytest.raises(ResearchDatasetError, match="dataset_unreadable"):
        load_dataset_backtest_inputs(store.root.parent, _backtest_request(bound))
    assert len(calls) == 1


def test_capture_errors_are_explicit_and_do_not_leak_credentials(
    client_context, monkeypatch
):
    client, state, original, _ = client_context
    calls = []

    def denied(*args, **kwargs):
        calls.append(True)
        raise RuntimeError("SDK failure fixture-secret https://private.invalid/token")

    monkeypatch.setattr(provider_module, "collect_tushare_dividend_observation", denied)
    path = f"/api/backtest/datasets/{original.dataset_id}/corporate-actions"
    state.config.tushare_token = ""
    response = client.post(path, json={})
    assert response.status_code == 422
    assert response.json()["detail"] == "tushare_token_missing"
    assert calls == []
    state.config.tushare_token = "fixture-secret"
    response = client.post(path, json={})
    assert response.status_code == 409
    assert response.json()["detail"] == "dataset_corporate_actions_collection_failed"
    assert "fixture-secret" not in response.text
    assert len(calls) == 1
    assert len(client.get("/api/backtest/datasets").json()["datasets"]) == 1
    assert client.post(path, json={"refresh": "false"}).status_code == 422
    assert client.post(path, json={"token": "forbidden"}).status_code == 422
