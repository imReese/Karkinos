"""PIT Dataset 核心值对象测试。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.model import (
    DATASET_KIND_DAILY_BARS,
    DailyBarDatasetPartition,
    DailyBarDatasetSnapshot,
    DatasetRef,
)
from data.storage.objects import ObjectRef

_START_DATE = date(2026, 9, 14)
_END_DATE = date(2026, 9, 16)

_CUTOFF = datetime(
    2026,
    9,
    17,
    1,
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


def _content_id(
    digit: str,
) -> str:
    return f"sha256:{digit * 64}"


def _object_ref(
    digit: str = "a",
) -> ObjectRef:
    return ObjectRef(
        object_id=_content_id(digit),
        size_bytes=123,
    )


def _partition(
    partition_date: date,
    *,
    provider: str = "tdx",
    revision_digit: str = "a",
    materialization_digit: str = "b",
) -> DailyBarDatasetPartition:
    return DailyBarDatasetPartition(
        partition_date=partition_date,
        provider=provider,
        revision_id=_content_id(revision_digit),
        materialization_id=_content_id(materialization_digit),
    )


def _snapshot(
    *,
    instruments=None,
    partitions=None,
    cutoff: datetime = _CUTOFF,
) -> DailyBarDatasetSnapshot:
    return DailyBarDatasetSnapshot(
        start_date=_START_DATE,
        end_date=_END_DATE,
        cutoff=cutoff,
        instruments=(
            instruments
            if instruments is not None
            else (
                _instrument("000001"),
                _instrument("600000"),
            )
        ),
        resolver_policy_id=("karkinos.dataset.pit.strict.v1"),
        market_schema_version=("karkinos.market.daily_bar.v1"),
        partitions=(
            partitions
            if partitions is not None
            else (
                _partition(
                    date(2026, 9, 14),
                    revision_digit="a",
                    materialization_digit="b",
                ),
                _partition(
                    date(2026, 9, 15),
                    revision_digit="c",
                    materialization_digit="d",
                ),
            )
        ),
    )


def test_dataset_ref_exposes_manifest_identity() -> None:
    manifest_ref = _object_ref("a")

    ref = DatasetRef(manifest_ref=manifest_ref)

    assert ref.manifest_ref == manifest_ref
    assert ref.dataset_id == manifest_ref.object_id


def test_dataset_ref_requires_object_ref() -> None:
    with pytest.raises(
        TypeError,
        match=("dataset_ref_manifest_must_be_object_ref"),
    ):
        DatasetRef(
            manifest_ref="sha256:not-an-object-ref",
        )


def test_partition_preserves_revision_and_materialization_identity() -> None:
    partition = _partition(
        date(2026, 9, 15),
    )

    assert partition.partition_date == date(2026, 9, 15)
    assert partition.provider == "tdx"
    assert partition.revision_id == _content_id("a")
    assert partition.materialization_id == _content_id("b")


def test_partition_normalizes_provider_text() -> None:
    partition = DailyBarDatasetPartition(
        partition_date=date(2026, 9, 15),
        provider="  tdx  ",
        revision_id=_content_id("a"),
        materialization_id=_content_id("b"),
    )

    assert partition.provider == "tdx"


def test_partition_date_must_be_exact_date() -> None:
    with pytest.raises(
        TypeError,
        match="dataset_partition_date_must_be_date",
    ):
        DailyBarDatasetPartition(
            partition_date=datetime(
                2026,
                9,
                15,
                tzinfo=timezone.utc,
            ),
            provider="tdx",
            revision_id=_content_id("a"),
            materialization_id=_content_id("b"),
        )


def test_partition_provider_must_not_be_empty() -> None:
    with pytest.raises(
        ValueError,
        match="dataset_partition_provider_missing",
    ):
        DailyBarDatasetPartition(
            partition_date=date(2026, 9, 15),
            provider="   ",
            revision_id=_content_id("a"),
            materialization_id=_content_id("b"),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        (
            "revision_id",
            "revision-1",
        ),
        (
            "materialization_id",
            "materialization-1",
        ),
        (
            "revision_id",
            "sha256:abc",
        ),
        (
            "materialization_id",
            f"sha256:{'G' * 64}",
        ),
    ],
)
def test_partition_requires_content_addressed_ids(
    field,
    value,
) -> None:
    kwargs = {
        "partition_date": date(2026, 9, 15),
        "provider": "tdx",
        "revision_id": _content_id("a"),
        "materialization_id": _content_id("b"),
    }

    kwargs[field] = value

    with pytest.raises(
        ValueError,
        match=f"dataset_{field}_invalid",
    ):
        DailyBarDatasetPartition(**kwargs)


def test_snapshot_exposes_basic_identity_fields() -> None:
    snapshot = _snapshot()

    assert snapshot.kind == DATASET_KIND_DAILY_BARS
    assert snapshot.start_date == _START_DATE
    assert snapshot.end_date == _END_DATE
    assert snapshot.cutoff == _CUTOFF

    assert snapshot.instrument_count == 2
    assert snapshot.partition_count == 2


def test_snapshot_normalizes_cutoff_to_utc() -> None:
    shanghai = timezone(timedelta(hours=8))

    snapshot = _snapshot(
        cutoff=datetime(
            2026,
            9,
            17,
            9,
            30,
            tzinfo=shanghai,
        )
    )

    assert snapshot.cutoff == datetime(
        2026,
        9,
        17,
        1,
        30,
        tzinfo=timezone.utc,
    )


def test_snapshot_rejects_naive_cutoff() -> None:
    with pytest.raises(
        ValueError,
        match=("dataset_cutoff_must_be_timezone_aware"),
    ):
        _snapshot(
            cutoff=datetime(
                2026,
                9,
                17,
                1,
                0,
            )
        )


def test_snapshot_rejects_invalid_date_range() -> None:
    with pytest.raises(
        ValueError,
        match="dataset_date_range_invalid",
    ):
        DailyBarDatasetSnapshot(
            start_date=date(2026, 9, 16),
            end_date=date(2026, 9, 15),
            cutoff=_CUTOFF,
            instruments=(_instrument("600000"),),
            resolver_policy_id="pit.strict.v1",
            market_schema_version="market.v1",
            partitions=(),
        )


@pytest.mark.parametrize(
    "field",
    [
        "start_date",
        "end_date",
    ],
)
def test_snapshot_dates_must_be_exact_dates(
    field,
) -> None:
    kwargs = {
        "start_date": _START_DATE,
        "end_date": _END_DATE,
        "cutoff": _CUTOFF,
        "instruments": (_instrument("600000"),),
        "resolver_policy_id": "pit.strict.v1",
        "market_schema_version": "market.v1",
        "partitions": (),
    }

    kwargs[field] = datetime(
        2026,
        9,
        15,
        tzinfo=timezone.utc,
    )

    with pytest.raises(
        TypeError,
        match=(f"dataset_{field}_must_be_date"),
    ):
        DailyBarDatasetSnapshot(**kwargs)


def test_snapshot_canonicalizes_instrument_order() -> None:
    snapshot = _snapshot(
        instruments=(
            _instrument("600000"),
            _instrument("510300", InstrumentType.ETF),
            _instrument("000001"),
        )
    )

    assert snapshot.instruments == (
        _instrument(
            "510300",
            InstrumentType.ETF,
        ),
        _instrument("000001"),
        _instrument("600000"),
    )


def test_same_symbol_with_different_instrument_type_is_distinct() -> None:
    snapshot = _snapshot(
        instruments=(
            _instrument(
                "510300",
                InstrumentType.STOCK,
            ),
            _instrument(
                "510300",
                InstrumentType.ETF,
            ),
        )
    )

    assert snapshot.instrument_count == 2


def test_snapshot_rejects_duplicate_instrument() -> None:
    instrument = _instrument("600000")

    with pytest.raises(
        ValueError,
        match="dataset_instrument_duplicate",
    ):
        _snapshot(
            instruments=(
                instrument,
                instrument,
            )
        )


def test_snapshot_rejects_empty_instrument_universe() -> None:
    with pytest.raises(
        ValueError,
        match="dataset_instruments_empty",
    ):
        _snapshot(
            instruments=(),
        )


def test_snapshot_rejects_non_instrument_key() -> None:
    with pytest.raises(
        TypeError,
        match=("dataset_instrument_must_be_instrument_key"),
    ):
        _snapshot(instruments=("600000",))


def test_snapshot_canonicalizes_partition_order() -> None:
    snapshot = _snapshot(
        partitions=(
            _partition(
                date(2026, 9, 16),
                revision_digit="e",
                materialization_digit="f",
            ),
            _partition(
                date(2026, 9, 14),
                revision_digit="a",
                materialization_digit="b",
            ),
            _partition(
                date(2026, 9, 15),
                revision_digit="c",
                materialization_digit="d",
            ),
        )
    )

    assert [item.partition_date for item in snapshot.partitions] == [
        date(2026, 9, 14),
        date(2026, 9, 15),
        date(2026, 9, 16),
    ]


def test_snapshot_rejects_duplicate_partition_date() -> None:
    with pytest.raises(
        ValueError,
        match="dataset_partition_date_duplicate",
    ):
        _snapshot(
            partitions=(
                _partition(
                    date(2026, 9, 15),
                    revision_digit="a",
                    materialization_digit="b",
                ),
                _partition(
                    date(2026, 9, 15),
                    revision_digit="c",
                    materialization_digit="d",
                ),
            )
        )


@pytest.mark.parametrize(
    "partition_date",
    [
        date(2026, 9, 13),
        date(2026, 9, 17),
    ],
)
def test_snapshot_rejects_partition_outside_range(
    partition_date,
) -> None:
    with pytest.raises(
        ValueError,
        match="dataset_partition_outside_range",
    ):
        _snapshot(
            partitions=(
                _partition(
                    partition_date,
                ),
            )
        )


def test_snapshot_allows_empty_partitions() -> None:
    snapshot = _snapshot(
        partitions=(),
    )

    assert snapshot.partitions == ()
    assert snapshot.partition_count == 0


def test_snapshot_does_not_require_calendar_continuity() -> None:
    snapshot = _snapshot(
        partitions=(
            _partition(
                date(2026, 9, 14),
                revision_digit="a",
                materialization_digit="b",
            ),
            _partition(
                date(2026, 9, 16),
                revision_digit="c",
                materialization_digit="d",
            ),
        )
    )

    # model.py 只表达结构，不猜测 9 月 15 日是否应当存在。
    assert snapshot.partition_count == 2


def test_snapshot_rejects_invalid_partition_type() -> None:
    with pytest.raises(
        TypeError,
        match="dataset_partition_invalid",
    ):
        _snapshot(partitions=("2026-09-15",))


def test_resolver_policy_id_is_normalized() -> None:
    snapshot = DailyBarDatasetSnapshot(
        start_date=_START_DATE,
        end_date=_END_DATE,
        cutoff=_CUTOFF,
        instruments=(_instrument("600000"),),
        resolver_policy_id=("  karkinos.dataset.pit.strict.v1  "),
        market_schema_version=("karkinos.market.daily_bar.v1"),
        partitions=(),
    )

    assert snapshot.resolver_policy_id == "karkinos.dataset.pit.strict.v1"


def test_snapshot_rejects_empty_resolver_policy_id() -> None:
    with pytest.raises(
        ValueError,
        match=("dataset_resolver_policy_id_missing"),
    ):
        DailyBarDatasetSnapshot(
            start_date=_START_DATE,
            end_date=_END_DATE,
            cutoff=_CUTOFF,
            instruments=(_instrument("600000"),),
            resolver_policy_id="   ",
            market_schema_version=("karkinos.market.daily_bar.v1"),
            partitions=(),
        )


def test_snapshot_rejects_empty_market_schema_version() -> None:
    with pytest.raises(
        ValueError,
        match=("dataset_market_schema_version_missing"),
    ):
        DailyBarDatasetSnapshot(
            start_date=_START_DATE,
            end_date=_END_DATE,
            cutoff=_CUTOFF,
            instruments=(_instrument("600000"),),
            resolver_policy_id=("karkinos.dataset.pit.strict.v1"),
            market_schema_version="   ",
            partitions=(),
        )


def test_same_revision_with_different_materialization_is_distinct_selection() -> None:
    revision_id = _content_id("a")

    early = DailyBarDatasetPartition(
        partition_date=date(2026, 9, 15),
        provider="tdx",
        revision_id=revision_id,
        materialization_id=_content_id("b"),
    )

    late = DailyBarDatasetPartition(
        partition_date=date(2026, 9, 15),
        provider="tdx",
        revision_id=revision_id,
        materialization_id=_content_id("c"),
    )

    assert early.revision_id == late.revision_id
    assert early.materialization_id != late.materialization_id
    assert early != late


def test_different_cutoffs_are_distinct_snapshots_even_with_same_selection() -> None:
    first = _snapshot(
        cutoff=datetime(
            2026,
            9,
            17,
            1,
            0,
            tzinfo=timezone.utc,
        )
    )

    second = _snapshot(
        cutoff=datetime(
            2026,
            9,
            18,
            1,
            0,
            tzinfo=timezone.utc,
        )
    )

    assert first.instruments == second.instruments
    assert first.partitions == second.partitions

    # cutoff 是 PIT statement 的一部分。
    assert first != second
