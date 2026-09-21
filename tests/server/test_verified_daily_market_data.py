from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import DatasetCatalog
from data.dataset.reader import read_daily_bar_dataset
from data.market.contracts import (
    DailyBarRequest,
    MarketDataProviderDescriptor,
    ProviderDailyBarBatch,
    ProviderDailyBarRow,
)
from data.market.serving import MarketServingStore
from data.provider_registry import ProviderRegistration, ProviderRegistry
from data.providers.akshare_tencent_daily import (
    AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR,
)
from data.providers.baostock_daily import BAOSTOCK_DAILY_BAR_DESCRIPTOR
from data.storage.objects import ContentAddressedObjectStore
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
    ) -> None:
        self._descriptor = descriptor
        self._close_offset = close_offset
        self.calls: list[DailyBarRequest] = []

    @property
    def descriptor(self) -> MarketDataProviderDescriptor:
        return self._descriptor

    def fetch_daily_bars(self, request: DailyBarRequest) -> ProviderDailyBarBatch:
        self.calls.append(request)
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
) -> ProviderRegistry:
    return ProviderRegistry(
        (
            ProviderRegistration(
                name="baostock",
                upstream_group="baostock",
                daily_bar_factory=lambda: FakeDailyProvider(
                    BAOSTOCK_DAILY_BAR_DESCRIPTOR
                ),
            ),
            ProviderRegistration(
                name="akshare_tencent",
                upstream_group="tencent",
                daily_bar_factory=lambda: FakeDailyProvider(
                    AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR,
                    close_offset=comparison_close_offset,
                ),
            ),
        )
    )


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
) -> VerifiedDailyMarketDataService:
    registry = _registry(comparison_close_offset=comparison_close_offset)
    monkeypatch.setattr(
        "server.services.verified_daily_market_data.provider_registry_for_config",
        lambda config, include_tdx=False: registry,
    )
    return VerifiedDailyMarketDataService(
        tmp_path / "research",
        SimpleNamespace(tushare_token=""),
    )


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
