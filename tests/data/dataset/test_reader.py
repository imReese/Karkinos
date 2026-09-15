"""不可变 PIT Dataset 离线读取与重放测试。"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.manifest import (
    publish_daily_bar_dataset_manifest,
)
from data.dataset.model import (
    DailyBarDatasetPartition,
    DailyBarDatasetSnapshot,
    DatasetRef,
)
from data.dataset.reader import (
    DatasetReaderIntegrityError,
    read_daily_bar_dataset,
    read_daily_bar_dataset_table,
)
from data.market.capture import capture_provider_payload
from data.market.normalize import normalize_daily_bar
from data.market.revision import (
    publish_daily_bar_revision,
)
from data.market.schema import (
    DAILY_BAR_SCHEMA_VERSION,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
)

_SESSION_DATE = date(
    2026,
    9,
    15,
)

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

_CAPTURED_AT = datetime(
    2026,
    9,
    15,
    7,
    3,
    tzinfo=timezone.utc,
)

_CUTOFF = datetime(
    2026,
    9,
    15,
    8,
    0,
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


def _universe() -> tuple[
    InstrumentKey,
    ...,
]:
    return (
        _instrument("000001"),
        _instrument("600000"),
    )


def _bar(
    symbol: str,
    *,
    session_date: date = _SESSION_DATE,
    available_at: datetime = _AVAILABLE_AT,
    captured_at: datetime = _CAPTURED_AT,
    close: str | None = None,
):
    event_time = datetime(
        session_date.year,
        session_date.month,
        session_date.day,
        7,
        0,
        tzinfo=timezone.utc,
    )

    if symbol == "000001":
        open_value = "12.10"
        high_value = "12.50"
        low_value = "12.00"
        close_value = close if close is not None else "12.34"
        volume = "100000"
        amount = "1234000"

    elif symbol == "601398":
        open_value = "6.18"
        high_value = "6.25"
        low_value = "6.10"
        close_value = close if close is not None else "6.20"
        volume = "234567"
        amount = "1454321.54"

    else:
        open_value = "10.31"
        high_value = "10.52"
        low_value = "10.20"
        close_value = close if close is not None else "10.48"
        volume = "123456"
        amount = "1283912.42"

    return normalize_daily_bar(
        instrument=_instrument(symbol),
        session_date=session_date,
        event_time=event_time,
        available_at=available_at,
        captured_at=captured_at,
        open_value=open_value,
        high_value=high_value,
        low_value=low_value,
        close_value=close_value,
        volume=volume,
        amount=amount,
        suspended=False,
    )


def _bars(
    *,
    session_date: date = _SESSION_DATE,
    available_at: datetime = _AVAILABLE_AT,
    captured_at: datetime = _CAPTURED_AT,
    close_600000: str = "10.48",
    include_000001: bool = True,
    extra_instrument: bool = False,
):
    result = []

    if include_000001:
        result.append(
            _bar(
                "000001",
                session_date=session_date,
                available_at=available_at,
                captured_at=captured_at,
            )
        )

    result.append(
        _bar(
            "600000",
            session_date=session_date,
            available_at=available_at,
            captured_at=captured_at,
            close=close_600000,
        )
    )

    if extra_instrument:
        result.append(
            _bar(
                "601398",
                session_date=session_date,
                available_at=available_at,
                captured_at=captured_at,
            )
        )

    return tuple(result)


def _capture(
    store: ContentAddressedObjectStore,
    *,
    provider: str,
    session_date: date,
    captured_at: datetime,
    record_count: int,
    raw_payload: bytes,
):
    return capture_provider_payload(
        store,
        provider=provider,
        operation="daily_bars",
        request={
            "kind": "daily_bars",
            "frequency": "1d",
            "start_date": (session_date.isoformat()),
            "end_date": (session_date.isoformat()),
            "instruments": [
                {
                    "symbol": "000001",
                    "instrument_type": "stock",
                },
                {
                    "symbol": "600000",
                    "instrument_type": "stock",
                },
            ],
        },
        raw_payload=raw_payload,
        payload_format=(f"{provider}.daily_bars.v1"),
        adapter_version=(f"karkinos.{provider}.v1"),
        started_at=(captured_at - timedelta(milliseconds=500)),
        completed_at=captured_at,
        record_count=record_count,
    )


def _revision(
    store: ContentAddressedObjectStore,
    *,
    provider: str = "tdx",
    session_date: date = _SESSION_DATE,
    available_at: datetime = _AVAILABLE_AT,
    captured_at: datetime = _CAPTURED_AT,
    close_600000: str = "10.48",
    include_000001: bool = True,
    extra_instrument: bool = False,
    raw_payload: bytes = b"provider-response",
):
    bars = _bars(
        session_date=session_date,
        available_at=available_at,
        captured_at=captured_at,
        close_600000=close_600000,
        include_000001=include_000001,
        extra_instrument=extra_instrument,
    )

    capture = _capture(
        store,
        provider=provider,
        session_date=session_date,
        captured_at=captured_at,
        record_count=len(bars),
        raw_payload=raw_payload,
    )

    return publish_daily_bar_revision(
        store,
        capture=capture,
        bars=bars,
        normalizer_version=("karkinos.market.normalize.v1"),
    )


def _publish_dataset(
    store: ContentAddressedObjectStore,
    *,
    revision,
    materialization,
    instruments: (
        tuple[
            InstrumentKey,
            ...,
        ]
        | None
    ) = None,
    cutoff: datetime = _CUTOFF,
    provider: str | None = None,
    revision_id: str | None = None,
    materialization_id: str | None = None,
    partition_date: date | None = None,
) -> DatasetRef:
    selected_date = (
        partition_date if partition_date is not None else revision.partition_date
    )

    snapshot = DailyBarDatasetSnapshot(
        start_date=selected_date,
        end_date=selected_date,
        cutoff=cutoff,
        instruments=(instruments if instruments is not None else _universe()),
        resolver_policy_id=("karkinos.dataset.pit.strict.v1"),
        market_schema_version=(DAILY_BAR_SCHEMA_VERSION),
        partitions=(
            DailyBarDatasetPartition(
                partition_date=(selected_date),
                provider=(provider if provider is not None else revision.provider),
                revision_id=(
                    revision_id if revision_id is not None else revision.ref.revision_id
                ),
                materialization_id=(
                    materialization_id
                    if materialization_id is not None
                    else materialization.materialization_id
                ),
            ),
        ),
    )

    return publish_daily_bar_dataset_manifest(
        store,
        snapshot,
    )


def _object_path(
    store: ContentAddressedObjectStore,
    ref,
):
    return store.root / "sha256" / ref.digest[:2] / ref.digest[2:]


def test_dataset_ref_replays_canonical_market_data(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    revision, materialization = _revision(store)

    dataset_ref = _publish_dataset(
        store,
        revision=revision,
        materialization=materialization,
    )

    result = read_daily_bar_dataset(
        store,
        dataset_ref,
    )

    assert result.ref == dataset_ref
    assert result.row_count == 2

    assert [bar.instrument.symbol for bar in result.bars] == [
        "000001",
        "600000",
    ]

    assert result.bars[0].close == Decimal("12.34000000")

    assert result.bars[1].close == Decimal("10.48000000")


def test_dataset_table_replay_is_canonical(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    revision, materialization = _revision(store)

    dataset_ref = _publish_dataset(
        store,
        revision=revision,
        materialization=materialization,
    )

    table = read_daily_bar_dataset_table(
        store,
        dataset_ref,
    )

    assert table.num_rows == 2
    assert table.schema.metadata == result_metadata(
        read_daily_bar_dataset(
            store,
            dataset_ref,
        ).table
    )


def result_metadata(
    table,
):
    return table.schema.metadata


def test_new_market_revision_does_not_change_old_dataset(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    old_revision, old_materialization = _revision(
        store,
        close_600000="10.48",
        raw_payload=b"tdx-r1",
    )

    dataset_ref = _publish_dataset(
        store,
        revision=old_revision,
        materialization=old_materialization,
    )

    # Dataset 发布之后 Provider 又修订了历史行情。
    new_revision, _ = _revision(
        store,
        available_at=datetime(
            2026,
            9,
            15,
            9,
            0,
            tzinfo=timezone.utc,
        ),
        captured_at=datetime(
            2026,
            9,
            15,
            9,
            3,
            tzinfo=timezone.utc,
        ),
        close_600000="10.49",
        raw_payload=b"tdx-r2",
    )

    assert new_revision.ref != old_revision.ref

    replayed = read_daily_bar_dataset(
        store,
        dataset_ref,
    )

    selected = {bar.instrument.symbol: bar for bar in replayed.bars}

    # Reader 不能偷偷切换到后来出现的 10.49。
    assert selected["600000"].close == Decimal("10.48000000")


def test_reader_filters_revision_to_dataset_universe(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    revision, materialization = _revision(
        store,
        extra_instrument=True,
    )

    dataset_ref = _publish_dataset(
        store,
        revision=revision,
        materialization=materialization,
        instruments=_universe(),
    )

    result = read_daily_bar_dataset(
        store,
        dataset_ref,
    )

    assert result.row_count == 2

    assert {bar.instrument.symbol for bar in result.bars} == {
        "000001",
        "600000",
    }

    assert all(bar.instrument.symbol != "601398" for bar in result.bars)


def test_reader_rejects_incomplete_dataset_universe(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    revision, materialization = _revision(
        store,
        include_000001=False,
    )

    dataset_ref = _publish_dataset(
        store,
        revision=revision,
        materialization=materialization,
        instruments=_universe(),
    )

    with pytest.raises(
        DatasetReaderIntegrityError,
        match=("dataset_reader_universe_incomplete"),
    ):
        read_daily_bar_dataset(
            store,
            dataset_ref,
        )


def test_reader_rejects_bar_available_after_dataset_cutoff(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    available_at = datetime(
        2026,
        9,
        15,
        9,
        0,
        tzinfo=timezone.utc,
    )

    captured_at = datetime(
        2026,
        9,
        15,
        9,
        3,
        tzinfo=timezone.utc,
    )

    revision, materialization = _revision(
        store,
        available_at=available_at,
        captured_at=captured_at,
    )

    # Manifest 自己只是 immutable selection contract，
    # 因此可以构造这种语义错误的 Dataset。
    # Reader 必须在 replay 边界再次 fail closed。
    dataset_ref = _publish_dataset(
        store,
        revision=revision,
        materialization=materialization,
        cutoff=_CUTOFF,
    )

    with pytest.raises(
        DatasetReaderIntegrityError,
        match="dataset_reader_bar_after_cutoff",
    ):
        read_daily_bar_dataset(
            store,
            dataset_ref,
        )


def test_reader_rejects_missing_revision_object(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    revision, materialization = _revision(store)

    missing_revision_id = "sha256:" + "f" * 64

    dataset_ref = _publish_dataset(
        store,
        revision=revision,
        materialization=materialization,
        revision_id=missing_revision_id,
    )

    with pytest.raises(
        DatasetReaderIntegrityError,
        match=("dataset_reader_partition_unreadable"),
    ):
        read_daily_bar_dataset(
            store,
            dataset_ref,
        )


def test_reader_rejects_missing_materialization_object(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    revision, materialization = _revision(store)

    missing_materialization_id = "sha256:" + "e" * 64

    dataset_ref = _publish_dataset(
        store,
        revision=revision,
        materialization=materialization,
        materialization_id=(missing_materialization_id),
    )

    with pytest.raises(
        DatasetReaderIntegrityError,
        match=("dataset_reader_partition_unreadable"),
    ):
        read_daily_bar_dataset(
            store,
            dataset_ref,
        )


def test_reader_rejects_cross_bound_materialization(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    first_revision, first_materialization = _revision(
        store,
        close_600000="10.48",
        raw_payload=b"revision-one",
    )

    second_revision, second_materialization = _revision(
        store,
        close_600000="10.49",
        raw_payload=b"revision-two",
    )

    assert first_revision.ref != second_revision.ref

    dataset_ref = _publish_dataset(
        store,
        revision=first_revision,
        materialization=first_materialization,
        materialization_id=(second_materialization.materialization_id),
    )

    with pytest.raises(
        DatasetReaderIntegrityError,
        match=("dataset_reader_materialization_revision_mismatch"),
    ):
        read_daily_bar_dataset(
            store,
            dataset_ref,
        )


def test_reader_rejects_provider_mismatch(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    revision, materialization = _revision(
        store,
        provider="tdx",
    )

    dataset_ref = _publish_dataset(
        store,
        revision=revision,
        materialization=materialization,
        provider="tushare",
    )

    with pytest.raises(
        DatasetReaderIntegrityError,
        match="dataset_reader_provider_mismatch",
    ):
        read_daily_bar_dataset(
            store,
            dataset_ref,
        )


def test_reader_rejects_corrupted_parquet(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    revision, materialization = _revision(store)

    dataset_ref = _publish_dataset(
        store,
        revision=revision,
        materialization=materialization,
    )

    path = _object_path(
        store,
        materialization.artifact.object_ref,
    )

    # 主动绕过 immutable 文件权限，模拟磁盘损坏。
    os.chmod(
        path,
        0o644,
    )

    path.write_bytes(b"corrupted parquet")

    with pytest.raises(
        DatasetReaderIntegrityError,
        match=("dataset_reader_partition_unreadable"),
    ):
        read_daily_bar_dataset(
            store,
            dataset_ref,
        )


def test_reader_rejects_corrupted_dataset_manifest(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    revision, materialization = _revision(store)

    dataset_ref = _publish_dataset(
        store,
        revision=revision,
        materialization=materialization,
    )

    path = _object_path(
        store,
        dataset_ref.manifest_ref,
    )

    os.chmod(
        path,
        0o644,
    )

    path.write_bytes(b"corrupted manifest")

    with pytest.raises(
        DatasetReaderIntegrityError,
        match="dataset_reader_manifest_invalid",
    ):
        read_daily_bar_dataset(
            store,
            dataset_ref,
        )


def test_same_dataset_ref_replays_identically(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    revision, materialization = _revision(store)

    dataset_ref = _publish_dataset(
        store,
        revision=revision,
        materialization=materialization,
    )

    first = read_daily_bar_dataset(
        store,
        dataset_ref,
    )

    second = read_daily_bar_dataset(
        store,
        dataset_ref,
    )

    assert first == second

    assert first.table.equals(second.table)


def test_reader_preserves_canonical_instrument_order(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    revision, materialization = _revision(store)

    dataset_ref = _publish_dataset(
        store,
        revision=revision,
        materialization=materialization,
        instruments=(
            _instrument("600000"),
            _instrument("000001"),
        ),
    )

    result = read_daily_bar_dataset(
        store,
        dataset_ref,
    )

    # Dataset model 已经 canonicalize universe。
    assert [bar.instrument.symbol for bar in result.bars] == [
        "000001",
        "600000",
    ]


def test_reader_rejects_invalid_ref_type(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    with pytest.raises(
        TypeError,
        match="dataset_reader_ref_invalid",
    ):
        read_daily_bar_dataset(
            store,
            "not-a-dataset-ref",
        )
