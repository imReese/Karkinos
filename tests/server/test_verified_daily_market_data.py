from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from analytics.dataset_snapshot import (
    build_backtest_dataset_snapshot,
    verify_backtest_dataset_snapshot_replay,
)
from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import DatasetCatalog
from data.dataset.reader import read_daily_bar_dataset
from data.market.contracts import (
    DailyBarProviderUnavailableError,
    DailyBarRequest,
    MarketDataProviderDescriptor,
    ProviderDailyBarBatch,
    ProviderDailyBarRow,
)
from data.market.quality import MarketQualityStatus
from data.market.quality_evidence import read_market_quality_evidence
from data.market.serving import MarketServingStore
from data.provider_registry import ProviderRegistration, ProviderRegistry
from data.providers.akshare_daily import AKSHARE_DAILY_BAR_DESCRIPTOR
from data.providers.akshare_tencent_daily import (
    AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR,
)
from data.providers.baostock_daily import BAOSTOCK_DAILY_BAR_DESCRIPTOR
from data.storage.objects import ContentAddressedObjectStore
from server.db import AppDatabase
from server.dependencies import AppState, AppStateContextMiddleware
from server.persistence.jobs import SQLiteJobStore
from server.routes import market
from server.services.backtest_dataset_inputs import load_dataset_backtest_inputs
from server.services.daily_market_collection import (
    DAILY_MARKET_COLLECTION_JOB,
    DailyMarketCollectionJobRequest,
    DailyMarketCollectionService,
)
from server.services.research_datasets import dataset_summary
from server.services.verified_daily_market_data import (
    VERIFIED_DAILY_MARKET_JOB_SCHEMA_VERSION,
    VerifiedDailyMarketDataNotPublishable,
    VerifiedDailyMarketDataRequestError,
    VerifiedDailyMarketDataService,
    VerifiedDailyMarketJobRequest,
)

DAY = date(2026, 9, 17)
CAPTURED = datetime(2026, 9, 17, 8, 0, tzinfo=timezone.utc)
CHECKED = datetime(2026, 9, 17, 8, 5, tzinfo=timezone.utc)
STOCK = InstrumentKey("600000", InstrumentType.STOCK)
ETF = InstrumentKey("510300", InstrumentType.ETF)


class FakeDailyProvider:
    def __init__(
        self,
        descriptor: MarketDataProviderDescriptor,
        *,
        close_offset: Decimal = Decimal("0"),
        unavailable: bool = False,
        call_log: list[str] | None = None,
    ) -> None:
        self._descriptor = descriptor
        self._close_offset = close_offset
        self._unavailable = unavailable
        self._call_log = call_log
        self.calls: list[DailyBarRequest] = []

    @property
    def descriptor(self) -> MarketDataProviderDescriptor:
        return self._descriptor

    def fetch_daily_bars(self, request: DailyBarRequest) -> ProviderDailyBarBatch:
        self.calls.append(request)
        if self._call_log is not None:
            self._call_log.append(self._descriptor.provider)
        if self._unavailable:
            raise DailyBarProviderUnavailableError(
                f"fixture_unavailable:{self._descriptor.provider}"
            )
        rows = tuple(self._row(instrument) for instrument in request.instruments)
        return ProviderDailyBarBatch(
            provider=self._descriptor.provider,
            adapter_version=self._descriptor.adapter_version,
            payload_format=f"{self._descriptor.provider}.fixture.v1",
            started_at=datetime(2026, 9, 17, 7, 59, 59, tzinfo=timezone.utc),
            completed_at=CAPTURED,
            raw_payload=(
                f"{self._descriptor.provider}:"
                + ",".join(item.symbol for item in request.instruments)
            ).encode(),
            rows=rows,
        )

    def _row(self, instrument: InstrumentKey) -> ProviderDailyBarRow:
        if instrument is ETF or instrument == ETF:
            base = Decimal("4.532")
            volume = (
                Decimal("507546102")
                if self._descriptor.provider == "baostock"
                else Decimal("507546100")
            )
            amount = (
                Decimal("2304178588")
                if self._descriptor.provider == "baostock"
                else Decimal("2304178600")
            )
        else:
            base = Decimal("9.06")
            volume = (
                Decimal("45671103")
                if self._descriptor.provider == "baostock"
                else Decimal("45671100")
            )
            amount = (
                Decimal("414887057.39")
                if self._descriptor.provider == "baostock"
                else Decimal("414887100")
            )
        close = base + self._close_offset
        return ProviderDailyBarRow(
            instrument=instrument,
            session_date=DAY,
            event_time=datetime(2026, 9, 17, 7, 0, tzinfo=timezone.utc),
            available_at=None,
            open_value=close,
            high_value=close + Decimal("0.01"),
            low_value=close - Decimal("0.01"),
            close_value=close,
            volume=volume,
            amount=amount,
            suspended=False,
        )


def _registry(
    *,
    comparison_close_offset: Decimal = Decimal("0"),
    baostock_unavailable: bool = False,
    include_eastmoney: bool = False,
    eastmoney_close_offset: Decimal = Decimal("0"),
    call_log: list[str] | None = None,
) -> ProviderRegistry:
    registrations = [
        ProviderRegistration(
            name="baostock",
            upstream_group="baostock",
            daily_bar_factory=lambda: FakeDailyProvider(
                BAOSTOCK_DAILY_BAR_DESCRIPTOR,
                unavailable=baostock_unavailable,
                call_log=call_log,
            ),
        ),
        ProviderRegistration(
            name="akshare_tencent",
            upstream_group="tencent",
            daily_bar_factory=lambda: FakeDailyProvider(
                AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR,
                close_offset=comparison_close_offset,
                call_log=call_log,
            ),
        ),
    ]
    if include_eastmoney:
        registrations.append(
            ProviderRegistration(
                name="akshare",
                upstream_group="eastmoney",
                daily_bar_factory=lambda: FakeDailyProvider(
                    AKSHARE_DAILY_BAR_DESCRIPTOR,
                    close_offset=eastmoney_close_offset,
                    call_log=call_log,
                ),
            )
        )
    return ProviderRegistry(tuple(registrations))


def _payload() -> dict:
    return VerifiedDailyMarketJobRequest(
        trade_date=DAY,
        instruments=(STOCK, ETF),
        source_policy_id="karkinos.market.source.free_cn_research.v1",
        calendar_evidence_refs=("calendar:2026:sse:fixture",),
    ).to_payload()


def _service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    comparison_close_offset: Decimal = Decimal("0"),
    baostock_unavailable: bool = False,
    include_eastmoney: bool = False,
    eastmoney_close_offset: Decimal = Decimal("0"),
    call_log: list[str] | None = None,
) -> VerifiedDailyMarketDataService:
    registry = _registry(
        comparison_close_offset=comparison_close_offset,
        baostock_unavailable=baostock_unavailable,
        include_eastmoney=include_eastmoney,
        eastmoney_close_offset=eastmoney_close_offset,
        call_log=call_log,
    )
    monkeypatch.setattr(
        "server.services.verified_daily_market_data.provider_registry_for_config",
        lambda config, include_tdx=False: registry,
    )
    return VerifiedDailyMarketDataService(
        tmp_path / "research",
        SimpleNamespace(tushare_token=""),
    )


def _collection_service(tmp_path, monkeypatch, registry):
    monkeypatch.setattr(
        "server.services.daily_market_collection.provider_registry_for_config",
        lambda config, include_tdx=False: registry,
    )
    return DailyMarketCollectionService(
        tmp_path / "research", SimpleNamespace(tushare_token="")
    )


def _collection_payload():
    return DailyMarketCollectionJobRequest(
        trade_date=DAY,
        instrument=STOCK,
        source_policy_id="karkinos.market.source.free_cn_research.v1",
        calendar_evidence_refs=("calendar:2026:sse:fixture",),
    ).to_payload()


def _collection_api(tmp_path: Path) -> tuple[TestClient, SQLiteJobStore]:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    state = AppState()
    state.db = db
    app = FastAPI()
    app.add_middleware(AppStateContextMiddleware, app_state=state)
    app.include_router(market.create_router())
    return TestClient(app), SQLiteJobStore(db.path)


def _complete_collection_job(
    store: SQLiteJobStore,
    service: DailyMarketCollectionService,
) -> tuple[str, str]:
    queued = store.enqueue(
        DAILY_MARKET_COLLECTION_JOB, _collection_payload(), now=CHECKED
    )
    claimed = store.claim(DAILY_MARKET_COLLECTION_JOB, "fixture", now=CHECKED)
    assert claimed is not None
    result_ref = service.run(_collection_payload(), checked_at=CHECKED)
    store.finish(claimed.lease, now=CHECKED, result_ref=result_ref)
    return queued.job_id, result_ref


@pytest.mark.parametrize("blocked", [False, True])
def test_collection_quality_http_separates_job_success_from_report_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    blocked: bool,
) -> None:
    calls: list[str] = []
    if blocked:
        original_row = FakeDailyProvider._row

        def wrong_instrument_row(self, instrument):
            return replace(
                original_row(self, instrument),
                instrument=InstrumentKey("000001", InstrumentType.STOCK),
            )

        monkeypatch.setattr(FakeDailyProvider, "_row", wrong_instrument_row)
    service = _collection_service(tmp_path, monkeypatch, _registry(call_log=calls))
    client, store = _collection_api(tmp_path)
    job_id, result_ref = _complete_collection_job(store, service)
    assert calls == ["baostock"]

    with client:
        response = client.get("/api/market/daily-collection-quality?limit=20")

    assert response.status_code == 200, response.text
    assert calls == ["baostock"]
    rows = response.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["job_id"] == job_id
    assert row["trade_date"] == DAY.isoformat()
    assert row["instrument"] == {"symbol": "600000", "instrument_type": "stock"}
    assert row["source_policy_id"] == _collection_payload()["source_policy_id"]
    assert row["job_status"] == "succeeded"
    assert row["attempt"] == 1
    assert row["created_at"]
    assert row["updated_at"]
    assert row["error"] is None
    assert row["result_ref"] == result_ref
    assert row["quality_read_status"] == "available"
    assert row["quality_attribution_status"] == "verified"
    quality = row["quality"]
    assert quality["quality_id"] == result_ref.removeprefix("quality:")
    assert quality["status"] == ("blocked" if blocked else "pass")
    assert quality["policy_id"] == "karkinos.market_quality.daily.research_strict.v1"
    assert (
        datetime.fromisoformat(quality["checked_at"].replace("Z", "+00:00")) == CHECKED
    )
    assert quality["provider"] == "baostock"
    assert quality["revision_id"].startswith("sha256:")
    assert quality["materialization_id"].startswith("sha256:")
    assert quality["observed_instrument_count"] == 1
    assert quality["expected_instrument_count"] == 1
    assert bool(quality["diagnostics"]) is blocked
    assert not DatasetCatalog(tmp_path / "research").path.exists()


@pytest.mark.parametrize("damage", ["missing", "corrupted"])
def test_collection_quality_http_fails_closed_for_unreadable_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    client, store = _collection_api(tmp_path)
    if damage == "missing":
        queued = store.enqueue(
            DAILY_MARKET_COLLECTION_JOB, _collection_payload(), now=CHECKED
        )
        claimed = store.claim(DAILY_MARKET_COLLECTION_JOB, "fixture", now=CHECKED)
        assert claimed is not None
        job_id = queued.job_id
        result_ref = "quality:sha256:" + "0" * 64
        store.finish(claimed.lease, now=CHECKED, result_ref=result_ref)
    else:
        service = _collection_service(tmp_path, monkeypatch, _registry())
        job_id, result_ref = _complete_collection_job(store, service)
        object_id = result_ref.removeprefix("quality:")
        path = (
            tmp_path
            / "research"
            / "objects"
            / "sha256"
            / object_id[7:9]
            / object_id[9:]
        )
        path.chmod(0o600)
        path.write_bytes(b"corrupted quality evidence")

    with client:
        response = client.get("/api/market/daily-collection-quality")

    assert response.status_code == 200, response.text
    row = response.json()[0]
    assert row["job_id"] == job_id
    assert row["job_status"] == "succeeded"
    assert row["result_ref"] == result_ref
    assert row["quality_read_status"] == "unreadable"
    assert row["quality_attribution_status"] == "not_checked"
    assert row["quality"] is None


def test_collection_quality_http_rejects_another_jobs_valid_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _collection_service(tmp_path, monkeypatch, _registry())
    client, store = _collection_api(tmp_path)
    other_payload = DailyMarketCollectionJobRequest(
        trade_date=DAY,
        instrument=ETF,
        source_policy_id=_collection_payload()["source_policy_id"],
        calendar_evidence_refs=("calendar:2026:sse:fixture",),
    ).to_payload()
    other_quality_ref = service.run(other_payload, checked_at=CHECKED)
    queued = store.enqueue(
        DAILY_MARKET_COLLECTION_JOB, _collection_payload(), now=CHECKED
    )
    claimed = store.claim(DAILY_MARKET_COLLECTION_JOB, "fixture", now=CHECKED)
    assert claimed is not None
    store.finish(claimed.lease, now=CHECKED, result_ref=other_quality_ref)

    with client:
        response = client.get("/api/market/daily-collection-quality")

    assert response.status_code == 200, response.text
    row = response.json()[0]
    assert row["job_id"] == queued.job_id
    assert row["job_status"] == "succeeded"
    assert row["result_ref"] == other_quality_ref
    assert row["quality_read_status"] == "available"
    assert row["quality_attribution_status"] == "mismatch"
    assert row["quality"]["status"] == "pass"
    assert row["quality"]["provider"] is None


def test_collection_quality_http_rejects_report_outside_jobs_source_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _collection_service(tmp_path, monkeypatch, _registry())
    client, store = _collection_api(tmp_path)
    free_policy_ref = service.run(_collection_payload(), checked_at=CHECKED)
    cn_policy_payload = DailyMarketCollectionJobRequest(
        trade_date=DAY,
        instrument=STOCK,
        source_policy_id="karkinos.market.source.cn_research.v1",
        calendar_evidence_refs=("calendar:2026:sse:fixture",),
    ).to_payload()
    queued = store.enqueue(DAILY_MARKET_COLLECTION_JOB, cn_policy_payload, now=CHECKED)
    claimed = store.claim(DAILY_MARKET_COLLECTION_JOB, "fixture", now=CHECKED)
    assert claimed is not None
    store.finish(claimed.lease, now=CHECKED, result_ref=free_policy_ref)

    with client:
        response = client.get("/api/market/daily-collection-quality")

    assert response.status_code == 200, response.text
    row = response.json()[0]
    assert row["job_id"] == queued.job_id
    assert row["trade_date"] == DAY.isoformat()
    assert row["instrument"] == {"symbol": "600000", "instrument_type": "stock"}
    assert row["source_policy_id"] == cn_policy_payload["source_policy_id"]
    assert row["job_status"] == "succeeded"
    assert row["result_ref"] == free_policy_ref
    assert row["quality_read_status"] == "available"
    assert row["quality_attribution_status"] == "mismatch"
    assert row["quality"]["status"] == "pass"
    assert row["quality"]["provider"] is None


def test_collection_quality_http_preserves_report_when_attribution_is_unreadable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_row = FakeDailyProvider._row

    def wrong_instrument_row(self, instrument):
        return replace(
            original_row(self, instrument),
            instrument=InstrumentKey("000001", InstrumentType.STOCK),
        )

    monkeypatch.setattr(FakeDailyProvider, "_row", wrong_instrument_row)
    service = _collection_service(tmp_path, monkeypatch, _registry())
    client, store = _collection_api(tmp_path)
    job_id, result_ref = _complete_collection_job(store, service)
    objects = ContentAddressedObjectStore(tmp_path / "research" / "objects")
    quality = read_market_quality_evidence(
        objects, objects.resolve_ref(result_ref.removeprefix("quality:"))
    )
    assert quality.report.status is MarketQualityStatus.BLOCKED
    materialization_id = quality.report.materialization_id
    materialization_path = (
        objects.root / "sha256" / materialization_id[7:9] / materialization_id[9:]
    )
    materialization_path.unlink()

    with client:
        response = client.get("/api/market/daily-collection-quality")

    assert response.status_code == 200, response.text
    row = response.json()[0]
    assert row["job_id"] == job_id
    assert row["job_status"] == "succeeded"
    assert row["quality_read_status"] == "available"
    assert row["quality_attribution_status"] == "unreadable"
    assert row["quality"]["status"] == "blocked"
    assert row["quality"]["provider"] is None
    assert row["quality"]["diagnostics"]


def test_collection_quality_http_omits_other_jobs_and_pending_quality(
    tmp_path: Path,
) -> None:
    client, store = _collection_api(tmp_path)
    queued = store.enqueue(
        DAILY_MARKET_COLLECTION_JOB, _collection_payload(), now=CHECKED
    )
    another_payload = DailyMarketCollectionJobRequest(
        trade_date=DAY,
        instrument=ETF,
        source_policy_id=_collection_payload()["source_policy_id"],
        calendar_evidence_refs=("calendar:2026:sse:fixture",),
    ).to_payload()
    another = store.enqueue(DAILY_MARKET_COLLECTION_JOB, another_payload, now=CHECKED)
    store.enqueue("market_daily_verified", _collection_payload(), now=CHECKED)

    with client:
        response = client.get("/api/market/daily-collection-quality?limit=20")
        limited = client.get("/api/market/daily-collection-quality?limit=1")
        invalid = client.get("/api/market/daily-collection-quality?limit=0")

    assert response.status_code == 200, response.text
    assert {row["job_id"] for row in response.json()} == {queued.job_id, another.job_id}
    assert limited.status_code == 200, limited.text
    assert len(limited.json()) == 1
    row = next(row for row in response.json() if row["job_id"] == queued.job_id)
    assert row["job_id"] == queued.job_id
    assert row["job_status"] == "queued"
    assert row["result_ref"] is None
    assert row["quality_read_status"] == "not_recorded"
    assert row["quality_attribution_status"] == "not_checked"
    assert row["quality"] is None
    assert invalid.status_code == 422
    assert (
        store.enqueue(DAILY_MARKET_COLLECTION_JOB, _collection_payload(), now=CHECKED)
        == queued
    )


def test_automatic_collection_persists_single_source_quality_without_dataset(
    tmp_path, monkeypatch
):
    calls = []
    service = _collection_service(tmp_path, monkeypatch, _registry(call_log=calls))

    result_ref = service.run(_collection_payload(), checked_at=CHECKED)

    root = tmp_path / "research"
    store = ContentAddressedObjectStore(root / "objects")
    quality = read_market_quality_evidence(
        store, store.resolve_ref(result_ref.removeprefix("quality:"))
    )
    assert calls == ["baostock"]
    assert quality.report.status is MarketQualityStatus.PASS
    assert not DatasetCatalog(root).path.exists()
    assert not MarketServingStore(root).path.exists()


def test_automatic_collection_defaults_quality_time_after_provider_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed_at: datetime | None = None

    class CurrentCompletionProvider(FakeDailyProvider):
        def fetch_daily_bars(self, request):
            nonlocal completed_at
            batch = super().fetch_daily_bars(request)
            completed_at = datetime.now(timezone.utc)
            return replace(
                batch,
                started_at=completed_at - timedelta(milliseconds=1),
                completed_at=completed_at,
            )

    registry = ProviderRegistry(
        (
            ProviderRegistration(
                name="baostock",
                upstream_group="baostock",
                daily_bar_factory=lambda: CurrentCompletionProvider(
                    BAOSTOCK_DAILY_BAR_DESCRIPTOR
                ),
            ),
        )
    )
    service = _collection_service(tmp_path, monkeypatch, registry)

    result_ref = service.run(_collection_payload())

    objects = ContentAddressedObjectStore(tmp_path / "research" / "objects")
    quality = read_market_quality_evidence(
        objects, objects.resolve_ref(result_ref.removeprefix("quality:"))
    )
    assert completed_at is not None
    assert quality.report.status is MarketQualityStatus.PASS
    assert quality.report.checked_at >= completed_at


def test_collection_falls_back_only_when_source_unavailable(tmp_path, monkeypatch):
    calls = []
    service = _collection_service(
        tmp_path,
        monkeypatch,
        _registry(baostock_unavailable=True, call_log=calls),
    )

    assert service.run(_collection_payload(), checked_at=CHECKED).startswith(
        "quality:sha256:"
    )
    assert calls == ["baostock", "akshare_tencent"]


def test_blocked_collection_quality_stays_visible_without_source_switch(
    tmp_path, monkeypatch
):
    calls = []

    class WrongInstrumentProvider(FakeDailyProvider):
        def _row(self, instrument):
            return replace(
                super()._row(instrument),
                instrument=InstrumentKey("000001", InstrumentType.STOCK),
            )

    registry = ProviderRegistry(
        (
            ProviderRegistration(
                name="baostock",
                upstream_group="baostock",
                daily_bar_factory=lambda: WrongInstrumentProvider(
                    BAOSTOCK_DAILY_BAR_DESCRIPTOR, call_log=calls
                ),
            ),
            ProviderRegistration(
                name="akshare_tencent",
                upstream_group="tencent",
                daily_bar_factory=lambda: FakeDailyProvider(
                    AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR, call_log=calls
                ),
            ),
        )
    )
    service = _collection_service(tmp_path, monkeypatch, registry)

    result_ref = service.run(_collection_payload(), checked_at=CHECKED)

    root = tmp_path / "research"
    store = ContentAddressedObjectStore(root / "objects")
    quality = read_market_quality_evidence(
        store, store.resolve_ref(result_ref.removeprefix("quality:"))
    )
    assert quality.report.status is MarketQualityStatus.BLOCKED
    assert calls == ["baostock"]
    assert not DatasetCatalog(root).path.exists()


def test_collection_fences_quality_publication_after_lease_loss(tmp_path, monkeypatch):
    service = _collection_service(tmp_path, monkeypatch, _registry())
    monkeypatch.setattr(
        "server.services.daily_market_collection.publish_market_quality_evidence",
        lambda *args: pytest.fail("quality evidence published after lease loss"),
    )

    def lost_lease():
        raise ValueError("job_lease_lost")

    with pytest.raises(ValueError, match="job_lease_lost"):
        service.run(
            _collection_payload(),
            checked_at=CHECKED,
            before_publish=lost_lease,
        )

    assert not DatasetCatalog(tmp_path / "research").path.exists()
    assert not MarketServingStore(tmp_path / "research").path.exists()


def test_verified_daily_market_request_is_canonical_and_secret_free() -> None:
    request = VerifiedDailyMarketJobRequest.from_payload(
        {
            "schema_version": VERIFIED_DAILY_MARKET_JOB_SCHEMA_VERSION,
            "trade_date": DAY.isoformat(),
            "instruments": [
                {"symbol": "600000", "instrument_type": "stock"},
                {"symbol": "510300", "instrument_type": "etf"},
            ],
            "source_policy_id": "karkinos.market.source.free_cn_research.v1",
            "calendar_evidence_refs": ["calendar-ref"],
            "observation_round": "post_close.v1",
        }
    )
    assert request.instruments == (ETF, STOCK)
    assert request.to_payload()["instruments"] == [
        {"symbol": "510300", "instrument_type": "etf"},
        {"symbol": "600000", "instrument_type": "stock"},
    ]
    assert "token" not in str(request.to_payload()).lower()


def test_verified_daily_market_request_rejects_unsupported_instrument_type() -> None:
    payload = _payload()
    payload["instruments"] = [{"symbol": "Au9999", "instrument_type": "gold"}]
    with pytest.raises(
        VerifiedDailyMarketDataRequestError,
        match="verified_daily_market_instrument_type_unsupported",
    ):
        VerifiedDailyMarketJobRequest.from_payload(payload)


def test_matched_market_job_publishes_v2_catalog_and_serving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, monkeypatch)
    publication = service.run(_payload(), checked_at=CHECKED)

    root = tmp_path / "research"
    store = ContentAddressedObjectStore(root / "objects")
    replayed = read_daily_bar_dataset(store, publication.dataset_ref)
    summary = dataset_summary(root, publication.dataset_ref)
    catalog_entry = DatasetCatalog(root).get(publication.dataset_id)
    serving = MarketServingStore(root).read_daily_bars(
        provider="baostock",
        start_date=DAY,
        end_date=DAY,
        instruments=(ETF, STOCK),
    )

    assert publication.primary_provider == "baostock"
    assert publication.comparison_provider == "akshare_tencent"
    assert publication.verification_id.startswith("sha256:")
    assert publication.result_ref == f"dataset:{publication.dataset_id}"
    assert replayed.snapshot.verification_bound is True
    assert (
        replayed.snapshot.partitions[0].verification_id == publication.verification_id
    )
    assert catalog_entry.ref == publication.dataset_ref
    assert summary["cross_source_verified"] is True
    assert summary["point_in_time_verified"] is False
    assert [bar.instrument for bar in serving] == [ETF, STOCK]


def test_matched_market_publication_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, monkeypatch)
    first = service.run(_payload(), checked_at=CHECKED)
    second = service.run(_payload(), checked_at=CHECKED)
    assert second == first
    entries = DatasetCatalog(tmp_path / "research").list_daily_bar_datasets()
    assert tuple(item.ref for item in entries) == (first.dataset_ref,)


def test_verified_dataset_backtest_binding_uses_selected_provider_not_tdx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = _service(tmp_path, monkeypatch).run(_payload(), checked_at=CHECKED)
    request = SimpleNamespace(
        dataset_id=publication.dataset_id,
        start_date=DAY.isoformat(),
        end_date=DAY.isoformat(),
        assets=[],
    )

    _, handlers, binding = load_dataset_backtest_inputs(tmp_path / "research", request)

    assert binding["source_names"] == ["baostock"]
    assert binding["cross_source_verified"] is True
    assert binding["point_in_time_verified"] is False
    assert {handler._df.attrs["provider_name"] for handler in handlers.values()} == {
        "baostock"
    }
    snapshot = build_backtest_dataset_snapshot(
        start_date=DAY.isoformat(),
        end_date=DAY.isoformat(),
        configured_source="baostock",
        data_handlers=handlers,
        store=None,
        source_names=binding["source_names"],
        research_dataset_binding=binding,
    )
    replay = verify_backtest_dataset_snapshot_replay(snapshot, store_root=tmp_path)
    assert snapshot["cross_source_verified"] is True
    assert snapshot["point_in_time_verified"] is False
    assert replay["verified_symbol_count"] == len(handlers)
    assert replay["status"] == "pass"
    assert replay["blockers"] == []
    false_claim = build_backtest_dataset_snapshot(
        start_date=DAY.isoformat(),
        end_date=DAY.isoformat(),
        configured_source="baostock",
        data_handlers=handlers,
        store=None,
        source_names=binding["source_names"],
        research_dataset_binding={**binding, "cross_source_verified": False},
    )
    false_replay = verify_backtest_dataset_snapshot_replay(
        false_claim, store_root=tmp_path
    )
    assert (
        "dataset_replay_immutable_dataset_binding_mismatch" in false_replay["blockers"]
    )


def test_unavailable_preferred_source_fails_over_to_next_independent_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_log: list[str] = []
    service = _service(
        tmp_path,
        monkeypatch,
        baostock_unavailable=True,
        include_eastmoney=True,
        call_log=call_log,
    )

    publication = service.run(_payload(), checked_at=CHECKED)

    assert publication.primary_provider == "akshare_tencent"
    assert publication.comparison_provider == "akshare"
    assert publication.source_resolution.outcome == "matched"
    assert publication.source_resolution.attempted_pairs == (
        ("baostock", "akshare_tencent"),
        ("akshare_tencent", "akshare"),
    )
    assert publication.source_resolution.unavailable_providers == ("baostock",)
    assert publication.source_resolution.selected_pair == (
        "akshare_tencent",
        "akshare",
    )
    assert call_log == ["baostock", "akshare_tencent", "akshare"]


def test_valid_cross_source_conflict_never_fails_over_to_hide_disagreement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_log: list[str] = []
    service = _service(
        tmp_path,
        monkeypatch,
        comparison_close_offset=Decimal("0.01"),
        include_eastmoney=True,
        call_log=call_log,
    )

    with pytest.raises(
        VerifiedDailyMarketDataNotPublishable,
        match="verified_daily_market_cross_source_conflict",
    ) as caught:
        service.run(_payload(), checked_at=CHECKED)

    resolution = caught.value.source_resolution
    assert resolution is not None
    assert resolution.outcome == "conflict"
    assert resolution.attempted_pairs == (("baostock", "akshare_tencent"),)
    assert resolution.unavailable_providers == ()
    assert resolution.selected_pair == ("baostock", "akshare_tencent")
    assert call_log == ["baostock", "akshare_tencent"]


def test_conflict_preserves_objects_but_does_not_publish_projections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(
        tmp_path,
        monkeypatch,
        comparison_close_offset=Decimal("0.01"),
    )

    with pytest.raises(
        VerifiedDailyMarketDataNotPublishable,
        match="verified_daily_market_cross_source_conflict",
    ):
        service.run(_payload(), checked_at=CHECKED)

    root = tmp_path / "research"
    assert any((root / "objects").rglob("*"))
    assert not DatasetCatalog(root).path.exists()
    assert not MarketServingStore(root).path.exists()


def test_publication_guard_fences_catalog_and_serving_visibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, monkeypatch)
    calls = 0

    def reject_lost_lease() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("job_lease_lost")

    with pytest.raises(ValueError, match="job_lease_lost"):
        service.run(
            _payload(),
            checked_at=CHECKED,
            before_publish=reject_lost_lease,
        )

    root = tmp_path / "research"
    assert calls == 1
    assert any((root / "objects").rglob("*"))
    assert not DatasetCatalog(root).path.exists()
    assert not MarketServingStore(root).path.exists()
