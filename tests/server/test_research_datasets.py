"""验证项目的持久数据准备、重启复用及现有回测入口，不请求真实数据服务。"""

from __future__ import annotations

import asyncio
import json
import subprocess
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import DatasetCatalog
from data.dataset.reader import read_daily_bar_dataset
from data.market.contracts import DailyBarRequest
from data.market.serving import MarketServingStore
from data.providers.tdx import TdxDailyBarProvider
from data.providers.tdx_runtime import TdxRuntimeSettings
from data.storage.objects import ContentAddressedObjectStore
from server.config import ServerConfig
from server.contracts.http.strategy_models import BacktestRequest
from server.db import AppDatabase
from server.dependencies import AppState, AppStateContextMiddleware
from server.routes.backtest import create_router
from server.services.backtest_dataset_inputs import load_dataset_backtest_inputs
from server.services.research_datasets import (
    ResearchDatasetError,
    ResearchDatasetService,
    _verified_dates,
    dataset_summary,
    prepare_daily_dataset,
)

_DAYS = tuple(date(2026, 9, day) for day in (7, 8, 9, 10, 11))
_REQUEST = DailyBarRequest(
    (InstrumentKey("600000", InstrumentType.STOCK),), _DAYS[0], _DAYS[-1]
)


class _Provider:
    """仅替换外部请求；Adapter、质量评估、落盘和发布都使用真实实现。"""

    def __init__(self, *, correction=False, fail_day=None):
        self.calls = []
        self.correction = correction
        self.fail_day = fail_day

    def fetch_daily_bars(self, request):
        day = request.start_date
        self.calls.append(day)
        if day == self.fail_day:
            raise RuntimeError("controlled network failure")
        close = Decimal("10.3") + Decimal(day.day % 3) / 10
        if self.correction:
            close += Decimal("0.1")
        response = {
            field: pd.DataFrame([[value]], index=[day], columns=["600000.SH"])
            for field, value in zip(
                ("Open", "High", "Low", "Close", "Volume", "Amount"),
                (10.4, 11, 10, close, 10000, 10.5),
                strict=True,
            )
        }
        client = SimpleNamespace(get_market_data=lambda **kwargs: response)
        instant = datetime(2026, 9, 16, 8, int(self.correction), tzinfo=timezone.utc)
        return TdxDailyBarProvider(client, clock=lambda: instant).fetch_daily_bars(
            request
        )


def _publish(root, provider=None, *, refresh=False):
    return prepare_daily_dataset(
        root,
        request=_REQUEST,
        dates=_DAYS,
        provider=provider or _Provider(),
        refresh=refresh,
    )


def _backtest_request(ref, **changes):
    return BacktestRequest(
        **{
            "dataset_id": ref.dataset_id,
            "start_date": _REQUEST.start_date.isoformat(),
            "end_date": _REQUEST.end_date.isoformat(),
            "assets": [{"symbol": "600000", "asset_class": "stock"}],
            "short_period": 2,
            "long_period": 3,
            **changes,
        }
    )


def test_persistent_publication_survives_restart_and_reuses_without_credentials(
    tmp_path,
):
    provider = _Provider()
    ref = _publish(tmp_path, provider)
    assert provider.calls == list(_DAYS)
    catalog = DatasetCatalog(tmp_path)
    assert catalog.path.is_file()
    assert MarketServingStore(tmp_path).path.is_file()
    restarted = ResearchDatasetService(tmp_path, TdxRuntimeSettings())
    assert restarted.status()["datasets"][0]["dataset_id"] == ref.dataset_id
    assert restarted.prepare(_REQUEST, db=None)["reused"] is True
    # 完整缓存复用无需日历查询、SDK 初始化或 Key。
    replay = read_daily_bar_dataset(
        ContentAddressedObjectStore(tmp_path / "objects"), ref
    )
    assert replay.row_count == len(_DAYS)
    assert _publish(tmp_path, _Provider(fail_day=_DAYS[0])) == ref


def test_failed_preparation_resumes_only_missing_sessions(tmp_path):
    first = _Provider(fail_day=_DAYS[2])
    with pytest.raises(RuntimeError, match="controlled network failure"):
        _publish(tmp_path, first)
    assert not DatasetCatalog(tmp_path).path.exists()
    assert DatasetCatalog(tmp_path / "checkpoints").path.exists()
    second = _Provider()
    ref = _publish(tmp_path, second)
    assert second.calls == list(_DAYS[2:])
    assert dataset_summary(tmp_path, ref)["partition_count"] == len(_DAYS)


def test_explicit_refresh_preserves_old_dataset_and_updates_serving(tmp_path):
    old = _publish(tmp_path)
    store = ContentAddressedObjectStore(tmp_path / "objects")
    before = read_daily_bar_dataset(store, old)
    new = _publish(tmp_path, _Provider(correction=True), refresh=True)
    assert new != old
    assert read_daily_bar_dataset(store, old) == before
    current = MarketServingStore(tmp_path).read_daily_bars(
        provider="tdx", start_date=_DAYS[0], end_date=_DAYS[-1]
    )
    assert current[0].close == before.bars[0].close + Decimal("0.1")


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"start_date": "2026-09-08"}, "dataset_request_date_mismatch"),
        ({"start_date": "not-a-date"}, "dataset_request_date_invalid"),
        (
            {"assets": [{"symbol": "000001", "asset_class": "stock"}]},
            "dataset_request_universe_mismatch",
        ),
    ],
)
def test_bound_backtest_rejects_input_mismatch(tmp_path, changes, code):
    ref = _publish(tmp_path)
    with pytest.raises(ResearchDatasetError, match=code):
        load_dataset_backtest_inputs(tmp_path, _backtest_request(ref, **changes))


def test_corrupted_dataset_fails_without_remote_fallback(tmp_path):
    ref = _publish(tmp_path)
    path = (
        tmp_path
        / "objects"
        / "sha256"
        / ref.manifest_ref.digest[:2]
        / ref.manifest_ref.digest[2:]
    )
    path.chmod(0o600)
    path.write_bytes(b"broken")
    with pytest.raises(
        ResearchDatasetError, match="dataset_unreadable_no_remote_fallback"
    ):
        load_dataset_backtest_inputs(tmp_path, _backtest_request(ref))


def _calendar():
    days = []
    day = date(2026, 1, 1)
    while day.year == 2026:
        # 固定测试日历只开放我们提供行情的五天，不能作为生产工作日推断。
        days.append({"date": day.isoformat(), "is_trading_day": day in _DAYS})
        day += timedelta(days=1)
    return {
        "year": 2026,
        "exchange": "SSE",
        "days": days,
        "trading_day_count": 5,
        "closed_day_count": 360,
        "source_fingerprint": "a" * 64,
        "verification_source_fingerprint": "a" * 64,
        "official_source_fingerprint": "b" * 64,
        "official_source_url": "https://example.test/calendar",
        "official_verified_at": "2026-09-16T08:00:00Z",
        "official_verified_by": "fixture",
        "official_verification_status": "verified",
    }


def test_calendar_is_verified_and_does_not_infer_weekdays(monkeypatch):
    row = _calendar()
    db = SimpleNamespace(get_market_calendar_snapshot_sync=lambda **kwargs: row)
    assert _verified_dates(db, _DAYS[0], _DAYS[-1]) == _DAYS
    row["official_verification_status"] = "needs_review"
    with pytest.raises(ResearchDatasetError, match="dataset_calendar_unavailable:2026"):
        _verified_dates(db, _DAYS[0], _DAYS[-1])

    def sync(self, year):
        assert year == 2026
        row["official_verification_status"] = "verified"

    monkeypatch.setattr(
        "server.services.market_calendar_automation.MarketCalendarAutomationService.sync_year",
        sync,
    )
    assert _verified_dates(db, _DAYS[0], _DAYS[-1], config=SimpleNamespace()) == _DAYS


def test_project_http_preparation_and_existing_backtest_save_bound_dataset(
    tmp_path, monkeypatch
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    service = ResearchDatasetService(
        tmp_path / "research", TdxRuntimeSettings("test-only")
    )
    monkeypatch.setattr(
        db, "get_market_calendar_snapshot_sync", lambda **kwargs: _calendar()
    )
    provider = _Provider()

    def prepare(request, dates, refresh):
        ref = prepare_daily_dataset(
            service.root,
            request=request,
            dates=dates,
            provider=provider,
            refresh=refresh,
        )
        return {**dataset_summary(service.root, ref), "reused": False}

    monkeypatch.setattr(service, "_prepare_in_child", prepare)

    def deny_remote(*args, **kwargs):
        raise AssertionError("A bound backtest must never fetch legacy data")

    monkeypatch.setattr("data.manager.build_sources", deny_remote)
    monkeypatch.setattr("data.manager.DataManager.get_bars", deny_remote)
    monkeypatch.setenv("KARKINOS_BACKTEST_REPORT_DIR", str(tmp_path / "reports"))
    state = AppState()
    state.db, state.config, state.research_datasets = db, ServerConfig(), service
    app = FastAPI()
    app.add_middleware(AppStateContextMiddleware, app_state=state)
    app.include_router(create_router())
    with TestClient(app) as client:
        assert client.get("/api/backtest/datasets").json()["datasets"] == []
        prepared = client.post(
            "/api/backtest/datasets",
            json={
                "symbol": "600000",
                "instrument_type": "stock",
                "start_date": _DAYS[0].isoformat(),
                "end_date": _DAYS[-1].isoformat(),
            },
        )
        assert prepared.status_code == 200, prepared.text
        dataset_id = prepared.json()["dataset_id"]
        body = {
            "dataset_id": dataset_id,
            "assets": [{"symbol": "600000", "asset_class": "stock"}],
            "start_date": _DAYS[0].isoformat(),
            "end_date": _DAYS[-1].isoformat(),
            "short_period": 2,
            "long_period": 3,
        }
        result = client.post("/api/backtest/run", json=body)
        assert result.status_code == 200, result.text
        result = result.json()
        assert result["config"]["dataset_id"] == dataset_id
        assert (
            result["metrics_json"]["dataset_binding"]["point_in_time_verified"] is False
        )
        assert (
            result["metrics_json"]["dataset_snapshot"]["immutable_dataset_id"]
            == dataset_id
        )
        saved = client.get(f"/api/backtest/results/{result['id']}").json()
        assert saved["config"]["dataset_id"] == dataset_id
        repeated = client.post("/api/backtest/run", json=body)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["equity_curve"] == result["equity_curve"]
        assert repeated.json()["metrics"] == result["metrics"]
        assert provider.calls == list(_DAYS)
    stored = asyncio.run(db.get_backtest_result(result["id"]))
    assert json.loads(stored["config_json"])["dataset_id"] == dataset_id


@pytest.mark.parametrize(
    "outcome,expected",
    [
        ("timeout", "dataset_preparation_timeout"),
        ("bad_report", "dataset_worker_failed"),
        ("no_data", "dataset_provider_no_data"),
    ],
)
def test_worker_delivery_is_private_and_cleanup_survives_failure(
    tmp_path, monkeypatch, outcome, expected
):
    service = ResearchDatasetService(
        tmp_path / "research", TdxRuntimeSettings("private-test-value")
    )
    library = tmp_path / "private-sdk" / "libTdxAiData.so"

    @contextmanager
    def prepare(settings):
        library.parent.mkdir()
        library.touch()
        try:
            yield library
        finally:
            library.unlink()
            library.parent.rmdir()

    monkeypatch.setattr(
        "server.services.research_datasets.prepare_tdx_runtime", prepare
    )
    monkeypatch.setenv("KARKINOS_AI_API_KEY", "must-not-leak")

    def run(command, **kwargs):
        assert "private-test-value" not in kwargs["input"]
        assert not any(key.startswith("KARKINOS_") for key in kwargs["env"])
        assert kwargs["env"]["TDX_AI_DATA_LIB"] == str(library)
        assert kwargs["stdout"] == subprocess.DEVNULL
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, 900)
        report = Path(json.loads(kwargs["input"])["report"])
        report.write_text(
            "invalid"
            if outcome == "bad_report"
            else json.dumps(
                {"status": "error", "error_code": "dataset_provider_no_data"}
            )
        )
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr("server.services.research_datasets.subprocess.run", run)
    with pytest.raises(ResearchDatasetError, match=expected):
        service._prepare_in_child(_REQUEST, _DAYS, False)
    assert not library.parent.exists()
