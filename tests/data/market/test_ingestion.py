"""Market Data ingestion 主流程测试。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import (
    DailyBarRequest,
    ProviderDailyBarBatch,
    ProviderDailyBarRow,
)
from data.market.ingestion import (
    DailyBarIngestionNoData,
    ingest_daily_bars,
)
from data.market.quality import (
    RESEARCH_STRICT_DAILY,
    MarketQualityStatus,
)
from data.market.schema import (
    DAILY_BAR_SCHEMA,
    daily_bars_from_table,
)
from data.storage.objects import ContentAddressedObjectStore
from data.storage.parquet import read_parquet

_SESSION_DATE = date(2026, 9, 15)

_EVENT_TIME = datetime(
    2026,
    9,
    15,
    7,
    0,
    tzinfo=timezone.utc,
)

_AVAILABLE_AT = datetime(
    2026,
    9,
    15,
    7,
    1,
    tzinfo=timezone.utc,
)

_STARTED_AT = datetime(
    2026,
    9,
    15,
    7,
    2,
    tzinfo=timezone.utc,
)

_COMPLETED_AT = datetime(
    2026,
    9,
    15,
    7,
    3,
    tzinfo=timezone.utc,
)


def _instrument(
    symbol: str,
    instrument_type: InstrumentType = InstrumentType.STOCK,
) -> InstrumentKey:
    return InstrumentKey(
        symbol=symbol,
        instrument_type=instrument_type,
    )


def _request() -> DailyBarRequest:
    return DailyBarRequest(
        instruments=(
            _instrument("000001"),
            _instrument("600000"),
        ),
        start_date=_SESSION_DATE,
        end_date=_SESSION_DATE,
    )


def _row(
    symbol: str,
    *,
    close_value: str | float = "10.48",
    available_at: datetime | None = _AVAILABLE_AT,
) -> ProviderDailyBarRow:
    if symbol == "000001":
        return ProviderDailyBarRow(
            instrument=_instrument(symbol),
            session_date=_SESSION_DATE,
            event_time=_EVENT_TIME,
            available_at=available_at,
            open_value="12.10",
            high_value="12.50",
            low_value="12.00",
            close_value="12.34",
            volume="100000",
            amount="1234000",
            suspended=False,
        )

    return ProviderDailyBarRow(
        instrument=_instrument(symbol),
        session_date=_SESSION_DATE,
        event_time=_EVENT_TIME,
        available_at=available_at,
        open_value="10.31",
        high_value="10.52",
        low_value="10.20",
        close_value=close_value,
        volume="123456",
        amount="1283912.42",
        suspended=False,
    )


def _batch(
    *,
    rows: tuple[ProviderDailyBarRow, ...] | None = None,
    raw_payload: bytes = b"provider-response",
) -> ProviderDailyBarBatch:
    return ProviderDailyBarBatch(
        provider="tdx",
        adapter_version="karkinos.tdx.v1",
        payload_format="tdx.daily_bars.v1",
        started_at=_STARTED_AT,
        completed_at=_COMPLETED_AT,
        raw_payload=raw_payload,
        rows=(
            rows
            if rows is not None
            else (
                _row("000001"),
                _row("600000"),
            )
        ),
    )


class FakeDailyBarProvider:
    """测试用 Provider，只返回预先构造好的 Batch。"""

    def __init__(
        self,
        batch: ProviderDailyBarBatch,
    ) -> None:
        self.batch = batch
        self.requests: list[DailyBarRequest] = []

    def fetch_daily_bars(
        self,
        request: DailyBarRequest,
    ) -> ProviderDailyBarBatch:
        self.requests.append(request)
        return self.batch


class FailingDailyBarProvider:
    """测试 Provider 调用失败时 ingestion 的行为。"""

    def fetch_daily_bars(
        self,
        request: DailyBarRequest,
    ) -> ProviderDailyBarBatch:
        raise RuntimeError("provider unavailable")


def _read_materialized_bars(
    store: ContentAddressedObjectStore,
    result,
):
    table = read_parquet(
        store,
        result.materialization.artifact,
        expected_schema=DAILY_BAR_SCHEMA,
    )

    return daily_bars_from_table(table)


def _object_file_count(
    store: ContentAddressedObjectStore,
) -> int:
    sha_root = store.root / "sha256"

    if not sha_root.exists():
        return 0

    return sum(1 for path in sha_root.rglob("*") if path.is_file())


def test_ingestion_runs_complete_market_data_pipeline(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    provider = FakeDailyBarProvider(_batch())

    result = ingest_daily_bars(
        provider,
        store,
        request=_request(),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version=("karkinos.market.normalize.daily_bar.v1"),
        checked_at=_COMPLETED_AT,
    )

    assert provider.requests == [_request()]

    assert result.capture.provider == "tdx"
    assert result.capture.record_count == 2

    assert result.revision.provider == "tdx"
    assert result.revision.partition_date == _SESSION_DATE
    assert result.revision.row_count == 2

    assert result.materialization.revision_ref == result.revision.ref
    assert result.materialization.capture_ref == result.capture.capture_ref

    assert result.quality.status is MarketQualityStatus.PASS
    assert result.quality.revision_id == result.revision.ref.revision_id
    assert (
        result.quality.materialization_id == result.materialization.materialization_id
    )

    assert result.eligible_for_dataset_publication is True


def test_ingestion_persists_replayable_canonical_bars(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    result = ingest_daily_bars(
        FakeDailyBarProvider(_batch()),
        store,
        request=_request(),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version=("karkinos.market.normalize.daily_bar.v1"),
        checked_at=_COMPLETED_AT,
    )

    bars = _read_materialized_bars(
        store,
        result,
    )

    assert [bar.instrument.symbol for bar in bars] == [
        "000001",
        "600000",
    ]

    assert (
        bars[0].close == _row("000001").close_value
        or str(bars[0].close) == "12.34000000"
    )

    assert str(bars[1].close) == "10.48000000"


def test_missing_provider_availability_falls_back_to_capture_completion(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    batch = _batch(
        rows=(
            _row(
                "000001",
                available_at=None,
            ),
            _row(
                "600000",
                available_at=None,
            ),
        )
    )

    result = ingest_daily_bars(
        FakeDailyBarProvider(batch),
        store,
        request=_request(),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version=("karkinos.market.normalize.daily_bar.v1"),
        checked_at=_COMPLETED_AT,
    )

    bars = _read_materialized_bars(
        store,
        result,
    )

    assert bars

    assert all(bar.available_at == batch.completed_at for bar in bars)

    assert all(bar.captured_at == batch.completed_at for bar in bars)


def test_provider_row_order_does_not_change_revision_identity(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    forward = ingest_daily_bars(
        FakeDailyBarProvider(
            _batch(
                rows=(
                    _row("000001"),
                    _row("600000"),
                ),
                raw_payload=b"forward-response",
            )
        ),
        store,
        request=_request(),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version=("karkinos.market.normalize.daily_bar.v1"),
        checked_at=_COMPLETED_AT,
    )

    reverse = ingest_daily_bars(
        FakeDailyBarProvider(
            _batch(
                rows=(
                    _row("600000"),
                    _row("000001"),
                ),
                raw_payload=b"reverse-response",
            )
        ),
        store,
        request=_request(),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version=("karkinos.market.normalize.daily_bar.v1"),
        checked_at=_COMPLETED_AT,
    )

    # 原始响应不同，因此 Capture 不同。
    assert forward.capture.capture_id != reverse.capture.capture_id

    # Provider 返回顺序不属于 canonical Market Data 语义。
    assert forward.revision.ref == reverse.revision.ref

    assert forward.revision.content_fingerprint == reverse.revision.content_fingerprint


def test_missing_instrument_preserves_revision_but_blocks_dataset(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    result = ingest_daily_bars(
        FakeDailyBarProvider(
            _batch(
                rows=(_row("600000"),),
            )
        ),
        store,
        request=_request(),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version=("karkinos.market.normalize.daily_bar.v1"),
        checked_at=_COMPLETED_AT,
    )

    # Provider 返回的数据仍然是一版真实存在的市场数据。
    assert result.revision.row_count == 1

    # 但它不满足正式研究要求。
    assert result.quality.status is MarketQualityStatus.BLOCKED
    assert result.eligible_for_dataset_publication is False

    # Capture / Revision / Materialization 全部仍然可验证。
    assert store.verify(result.capture.capture_ref)
    assert store.verify(result.revision.ref.manifest_ref)
    assert store.verify(result.materialization.manifest_ref)


def test_empty_provider_result_preserves_capture_but_creates_no_revision(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    provider = FakeDailyBarProvider(
        _batch(
            rows=(),
            raw_payload=b"empty-provider-response",
        )
    )

    with pytest.raises(
        DailyBarIngestionNoData,
    ) as caught:
        ingest_daily_bars(
            provider,
            store,
            request=_request(),
            quality_policy=RESEARCH_STRICT_DAILY,
            normalizer_version=("karkinos.market.normalize.daily_bar.v1"),
            checked_at=_COMPLETED_AT,
        )

    capture = caught.value.capture

    assert capture.record_count == 0

    assert store.verify(capture.capture_ref)
    assert store.verify(capture.raw_object_ref)

    # 空结果只会生成 Raw Object + Capture Manifest，
    # 不会制造一个没有市场事实的 MarketRevision。
    assert _object_file_count(store) == 2


def test_provider_failure_creates_no_capture(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    with pytest.raises(
        RuntimeError,
        match="provider unavailable",
    ):
        ingest_daily_bars(
            FailingDailyBarProvider(),
            store,
            request=_request(),
            quality_policy=RESEARCH_STRICT_DAILY,
            normalizer_version=("karkinos.market.normalize.daily_bar.v1"),
            checked_at=_COMPLETED_AT,
        )

    # Provider 在返回 Batch 前就失败，没有任何可固化的响应证据。
    assert _object_file_count(store) == 0


def test_provider_correction_creates_new_revision(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    original = ingest_daily_bars(
        FakeDailyBarProvider(
            _batch(
                rows=(
                    _row("000001"),
                    _row(
                        "600000",
                        close_value="10.48",
                    ),
                ),
                raw_payload=b"provider-revision-1",
            )
        ),
        store,
        request=_request(),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version=("karkinos.market.normalize.daily_bar.v1"),
        checked_at=_COMPLETED_AT,
    )

    corrected = ingest_daily_bars(
        FakeDailyBarProvider(
            _batch(
                rows=(
                    _row("000001"),
                    _row(
                        "600000",
                        close_value="10.49",
                    ),
                ),
                raw_payload=b"provider-revision-2",
            )
        ),
        store,
        request=_request(),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version=("karkinos.market.normalize.daily_bar.v1"),
        checked_at=_COMPLETED_AT,
    )

    assert (
        original.revision.content_fingerprint != corrected.revision.content_fingerprint
    )

    assert original.revision.ref != corrected.revision.ref

    # 两版历史都必须继续存在，不能覆盖旧 Revision。
    assert store.verify(original.revision.ref.manifest_ref)
    assert store.verify(corrected.revision.ref.manifest_ref)


def test_same_provider_facts_are_idempotent(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    provider = FakeDailyBarProvider(_batch())

    first = ingest_daily_bars(
        provider,
        store,
        request=_request(),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version=("karkinos.market.normalize.daily_bar.v1"),
        checked_at=_COMPLETED_AT,
    )

    second = ingest_daily_bars(
        provider,
        store,
        request=_request(),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version=("karkinos.market.normalize.daily_bar.v1"),
        checked_at=_COMPLETED_AT,
    )

    assert first.capture == second.capture
    assert first.revision == second.revision
    assert first.materialization == second.materialization


def test_provider_supplied_availability_is_preserved(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    provider_available_at = _AVAILABLE_AT - timedelta(seconds=37)

    batch = _batch(
        rows=(
            _row(
                "000001",
                available_at=provider_available_at,
            ),
            _row(
                "600000",
                available_at=provider_available_at,
            ),
        )
    )

    result = ingest_daily_bars(
        FakeDailyBarProvider(batch),
        store,
        request=_request(),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version=("karkinos.market.normalize.daily_bar.v1"),
        checked_at=_COMPLETED_AT,
    )

    bars = _read_materialized_bars(
        store,
        result,
    )

    assert all(bar.available_at == provider_available_at for bar in bars)

    assert all(bar.captured_at == batch.completed_at for bar in bars)
