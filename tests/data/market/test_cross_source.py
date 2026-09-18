from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.resolver import (
    DailyBarDatasetResolverPolicy,
    resolve_daily_bar_dataset,
)
from data.market.contracts import (
    DailyBarProvider,
    DailyBarRequest,
    MarketDataProviderDescriptor,
    ProviderDailyBarBatch,
    ProviderDailyBarRow,
)
from data.market.cross_source import (
    CrossSourceDailyBarConfigurationError,
    CrossSourceDailyBarIntegrityError,
    ingest_cross_source_daily_bars,
)
from data.market.quality import RESEARCH_STRICT_DAILY
from data.market.verification_evidence import MarketVerificationStatus
from data.providers.tdx import TDX_PROVIDER_DESCRIPTOR
from data.providers.tushare_daily import TUSHARE_DAILY_BAR_DESCRIPTOR
from data.storage.objects import ContentAddressedObjectStore

DAY = date(2026, 9, 15)
STARTED = datetime(2026, 9, 15, 7, 59, 59, tzinfo=timezone.utc)
COMPLETED = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)
CHECKED = datetime(2026, 9, 15, 8, 5, tzinfo=timezone.utc)
INSTRUMENT = InstrumentKey("600000", InstrumentType.STOCK)
REQUEST = DailyBarRequest((INSTRUMENT,), DAY, DAY)


class FakeProvider:
    def __init__(
        self,
        descriptor: MarketDataProviderDescriptor,
        *,
        close: str = "10.48",
        include_row: bool = True,
        row_instrument: InstrumentKey = INSTRUMENT,
        batch_provider: str | None = None,
        batch_adapter_version: str | None = None,
    ) -> None:
        self._descriptor = descriptor
        self._close = close
        self._include_row = include_row
        self._row_instrument = row_instrument
        self._batch_provider = batch_provider
        self._batch_adapter_version = batch_adapter_version
        self.calls = 0

    @property
    def descriptor(self) -> MarketDataProviderDescriptor:
        return self._descriptor

    def fetch_daily_bars(self, request: DailyBarRequest) -> ProviderDailyBarBatch:
        self.calls += 1
        rows = ()
        if self._include_row:
            rows = (
                ProviderDailyBarRow(
                    instrument=self._row_instrument,
                    session_date=DAY,
                    event_time=datetime(2026, 9, 15, 7, 0, tzinfo=timezone.utc),
                    available_at=None,
                    open_value=Decimal("10.31"),
                    high_value=Decimal("10.52"),
                    low_value=Decimal("10.20"),
                    close_value=Decimal(self._close),
                    volume=Decimal("123456"),
                    amount=Decimal("1283912.42"),
                    suspended=False,
                ),
            )
        return ProviderDailyBarBatch(
            provider=self._batch_provider or self._descriptor.provider,
            adapter_version=(
                self._batch_adapter_version or self._descriptor.adapter_version
            ),
            payload_format=f"{self._descriptor.provider}.fixture.v1",
            started_at=STARTED,
            completed_at=COMPLETED,
            raw_payload=json.dumps(
                {"provider": self._descriptor.provider, "close": self._close}
            ).encode(),
            rows=rows,
        )


def _run(
    tmp_path: Path,
    *,
    primary: FakeProvider | None = None,
    comparison: FakeProvider | None = None,
):
    store = ContentAddressedObjectStore(tmp_path / "objects")
    result = ingest_cross_source_daily_bars(
        primary or FakeProvider(TDX_PROVIDER_DESCRIPTOR),
        comparison or FakeProvider(TUSHARE_DAILY_BAR_DESCRIPTOR),
        store,
        request=REQUEST,
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version="karkinos.market.normalize.v1",
        checked_at=CHECKED,
    )
    return store, result


def test_cross_source_match_produces_verified_dataset_candidates(
    tmp_path: Path,
) -> None:
    store, result = _run(tmp_path)

    assert result.verification is not None
    assert result.verification.status is MarketVerificationStatus.MATCHED
    assert result.eligible_for_verified_dataset
    assert result.primary_quality.quality_id.startswith("sha256:")
    assert result.comparison_quality.quality_id.startswith("sha256:")

    candidates = result.resolution_candidates()
    assert len(candidates) == 2
    snapshot = resolve_daily_bar_dataset(
        store,
        candidates=candidates,
        start_date=DAY,
        end_date=DAY,
        cutoff=COMPLETED,
        instruments=(INSTRUMENT,),
        expected_partition_dates=(DAY,),
        policy=DailyBarDatasetResolverPolicy(
            policy_id="fixture.verified.v1",
            provider_priority=("tdx", "tushare"),
            required_quality_policy_id=RESEARCH_STRICT_DAILY.policy_id,
        ),
    )
    assert snapshot.verification_bound
    assert snapshot.partitions[0].verification_id == result.verification.verification_id


def test_cross_source_conflict_is_durable_but_not_dataset_eligible(
    tmp_path: Path,
) -> None:
    _, result = _run(
        tmp_path,
        comparison=FakeProvider(TUSHARE_DAILY_BAR_DESCRIPTOR, close="10.49"),
    )

    assert result.verification is not None
    assert result.verification.status is MarketVerificationStatus.CONFLICT
    assert not result.eligible_for_verified_dataset
    assert result.resolution_candidates() == ()


def test_cross_source_quality_failure_preserves_quality_evidence_without_verification(
    tmp_path: Path,
) -> None:
    _, result = _run(
        tmp_path,
        comparison=FakeProvider(
            TUSHARE_DAILY_BAR_DESCRIPTOR,
            row_instrument=InstrumentKey("000001", InstrumentType.STOCK),
        ),
    )

    assert result.verification is None
    assert result.verification_status == "quality_blocked"
    assert result.primary_quality.quality_id.startswith("sha256:")
    assert result.comparison_quality.quality_id.startswith("sha256:")
    assert result.resolution_candidates() == ()


def test_cross_source_rejects_same_upstream_before_provider_io(tmp_path: Path) -> None:
    primary = FakeProvider(TDX_PROVIDER_DESCRIPTOR)
    comparison = FakeProvider(
        replace(TUSHARE_DAILY_BAR_DESCRIPTOR, upstream_group="tdx")
    )
    store = ContentAddressedObjectStore(tmp_path / "objects")

    with pytest.raises(
        CrossSourceDailyBarConfigurationError,
        match="cross_source_daily_bar_upstream_groups_must_differ",
    ):
        ingest_cross_source_daily_bars(
            primary,
            comparison,
            store,
            request=REQUEST,
            quality_policy=RESEARCH_STRICT_DAILY,
            normalizer_version="karkinos.market.normalize.v1",
            checked_at=CHECKED,
        )

    assert primary.calls == 0
    assert comparison.calls == 0


def test_cross_source_rejects_unadjusted_capability_mismatch_before_io(
    tmp_path: Path,
) -> None:
    primary = FakeProvider(TDX_PROVIDER_DESCRIPTOR)
    comparison = FakeProvider(
        replace(
            TUSHARE_DAILY_BAR_DESCRIPTOR,
            daily_bar_capabilities=(
                replace(
                    TUSHARE_DAILY_BAR_DESCRIPTOR.daily_bar_capabilities[0],
                    price_basis="qfq",
                ),
            ),
        )
    )
    store = ContentAddressedObjectStore(tmp_path / "objects")

    with pytest.raises(
        CrossSourceDailyBarConfigurationError,
        match="cross_source_daily_bar_capability_unsupported",
    ):
        ingest_cross_source_daily_bars(
            primary,
            comparison,
            store,
            request=REQUEST,
            quality_policy=RESEARCH_STRICT_DAILY,
            normalizer_version="karkinos.market.normalize.v1",
            checked_at=CHECKED,
        )


def test_cross_source_rejects_provider_identity_drift(tmp_path: Path) -> None:
    provider = FakeProvider(
        TDX_PROVIDER_DESCRIPTOR,
        batch_provider="different-provider",
    )
    store = ContentAddressedObjectStore(tmp_path / "objects")

    with pytest.raises(
        CrossSourceDailyBarIntegrityError,
        match="cross_source_daily_bar_provider_identity_mismatch",
    ):
        ingest_cross_source_daily_bars(
            provider,
            FakeProvider(TUSHARE_DAILY_BAR_DESCRIPTOR),
            store,
            request=REQUEST,
            quality_policy=RESEARCH_STRICT_DAILY,
            normalizer_version="karkinos.market.normalize.v1",
            checked_at=CHECKED,
        )


def test_fake_provider_still_satisfies_daily_bar_protocol() -> None:
    assert isinstance(FakeProvider(TDX_PROVIDER_DESCRIPTOR), DailyBarProvider)
