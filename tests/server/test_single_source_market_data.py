"""Explicit single-source publication is labelled and never claims agreement."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import DatasetCatalog
from data.dataset.reader import read_daily_bar_dataset
from data.market.serving import MarketServingStore
from data.storage.objects import ContentAddressedObjectStore
from server.services.market.verified_daily_market_data import (
    VERIFIED_DAILY_MARKET_RANGE_JOB_SCHEMA_VERSION,
    VerifiedDailyMarketDataNotPublishable,
    VerifiedDailyMarketDataUnavailable,
    VerifiedDailyMarketJobRequest,
)
from server.services.research.research_observation_inputs import (
    ResearchObservationInputError,
    require_research_dataset_agreement,
)
from tests.server.test_verified_daily_market_data import (
    CHECKED,
    DAY,
    STOCK,
    _service,
)

SINGLE_SOURCE_POLICY = "karkinos.market.source.free_cn_research_single_source.v1"
STOCK_ONLY = InstrumentKey("600000", InstrumentType.STOCK)


def _payload() -> dict:
    return VerifiedDailyMarketJobRequest(
        trade_date=DAY,
        instruments=(STOCK,),
        source_policy_id=SINGLE_SOURCE_POLICY,
        calendar_evidence_refs=("calendar:2026:sse:fixture",),
    ).to_payload()


def test_single_source_policy_publishes_labelled_dataset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, monkeypatch, baostock_unavailable=True)

    publication = service.run(_payload(), checked_at=CHECKED)

    assert publication.source_class == "single_source"
    assert publication.verification_id is None
    assert publication.primary_provider == "akshare_tencent"
    assert publication.comparison_provider is None
    assert publication.source_resolution.outcome == "single_source"
    assert publication.source_resolution.selected_provider == "akshare_tencent"
    assert (
        publication.source_resolution.to_payload()["selected_provider"]
        == "akshare_tencent"
    )

    root = tmp_path / "research"
    assert DatasetCatalog(root).path.exists()
    assert MarketServingStore(root).path.exists()
    entry = DatasetCatalog(root).get(publication.dataset_id)
    replayed = read_daily_bar_dataset(
        ContentAddressedObjectStore(root / "objects"), entry.ref
    )
    assert replayed.snapshot.source_class == "single_source"
    assert replayed.snapshot.verification_required is False
    assert replayed.snapshot.verification_bound is False
    assert replayed.snapshot.partitions[0].verification_id is None


def test_single_source_dataset_is_refused_by_research_agreement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, monkeypatch, baostock_unavailable=True)
    publication = service.run(_payload(), checked_at=CHECKED)
    root = tmp_path / "research"
    objects = ContentAddressedObjectStore(root / "objects")
    snapshot = read_daily_bar_dataset(
        objects, DatasetCatalog(root).get(publication.dataset_id).ref
    ).snapshot

    with pytest.raises(
        ResearchObservationInputError, match="observation_dataset_unverified"
    ):
        require_research_dataset_agreement(objects, snapshot)


def test_single_source_policy_still_blocks_live_conflict(
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
    assert not DatasetCatalog(root).path.exists()
    assert not MarketServingStore(root).path.exists()


def test_single_source_range_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, monkeypatch, baostock_unavailable=True)
    payload = VerifiedDailyMarketJobRequest(
        trade_date=DAY,
        instruments=(STOCK_ONLY,),
        source_policy_id=SINGLE_SOURCE_POLICY,
        calendar_evidence_refs=("calendar:2026:sse:fixture",),
        range_start_date=DAY,
        range_end_date=DAY,
        session_memberships=((DAY, (STOCK_ONLY,), ("calendar:2026:sse:fixture",)),),
    ).to_payload()
    assert payload["schema_version"] == VERIFIED_DAILY_MARKET_RANGE_JOB_SCHEMA_VERSION

    with pytest.raises(
        VerifiedDailyMarketDataUnavailable,
        match="verified_daily_market_single_source_range_unsupported",
    ):
        service.run(payload, checked_at=CHECKED)


def test_single_source_policy_is_opt_in_only() -> None:
    from data.source_policy import (
        FREE_CN_RESEARCH_SINGLE_SOURCE_V1,
        FREE_CN_RESEARCH_V1,
        MarketDataUseCase,
    )

    assert (
        FREE_CN_RESEARCH_V1.route(MarketDataUseCase.DAILY_BARS).single_source_allowed
        is False
    )
    assert (
        FREE_CN_RESEARCH_SINGLE_SOURCE_V1.route(
            MarketDataUseCase.DAILY_BARS
        ).single_source_allowed
        is True
    )
    assert FREE_CN_RESEARCH_V1.policy_id != FREE_CN_RESEARCH_SINGLE_SOURCE_V1.policy_id
