"""Dataset Catalog 测试。"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import (
    DatasetCatalog,
    DatasetCatalogIntegrityError,
    DatasetCatalogNotFoundError,
)
from data.dataset.manifest import (
    publish_daily_bar_dataset_manifest,
)
from data.dataset.model import (
    DATASET_KIND_DAILY_BARS,
    DailyBarDatasetPartition,
    DailyBarDatasetSnapshot,
)
from data.dataset.reader import (
    read_daily_bar_dataset,
)
from data.market.capture import (
    capture_provider_payload,
)
from data.market.normalize import (
    normalize_daily_bar,
)
from data.market.revision import (
    publish_daily_bar_revision,
)
from data.market.schema import (
    DAILY_BAR_SCHEMA_VERSION,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
)


def _instrument(
    symbol: str = "600000",
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


def _snapshot(
    *,
    start_date: date = date(2026, 9, 15),
    end_date: date = date(2026, 9, 15),
    cutoff: datetime = datetime(
        2026,
        9,
        15,
        8,
        0,
        tzinfo=timezone.utc,
    ),
    resolver_policy_id: str = ("karkinos.dataset.pit.strict.v1"),
    instruments: (
        tuple[
            InstrumentKey,
            ...,
        ]
        | None
    ) = None,
    partitions: (
        tuple[
            DailyBarDatasetPartition,
            ...,
        ]
        | None
    ) = None,
) -> DailyBarDatasetSnapshot:
    if instruments is None:
        instruments = (_instrument(),)

    if partitions is None:
        partitions = (
            DailyBarDatasetPartition(
                partition_date=start_date,
                provider="tdx",
                revision_id=_content_id("a"),
                materialization_id=_content_id("b"),
            ),
        )

    return DailyBarDatasetSnapshot(
        start_date=start_date,
        end_date=end_date,
        cutoff=cutoff,
        instruments=instruments,
        resolver_policy_id=resolver_policy_id,
        market_schema_version=(DAILY_BAR_SCHEMA_VERSION),
        partitions=partitions,
    )


def _publish(
    store: ContentAddressedObjectStore,
    **snapshot_kwargs,
):
    snapshot = _snapshot(**snapshot_kwargs)

    ref = publish_daily_bar_dataset_manifest(
        store,
        snapshot,
    )

    return ref, snapshot


def _registered_at(
    hour: int,
) -> datetime:
    return datetime(
        2026,
        9,
        16,
        hour,
        0,
        tzinfo=timezone.utc,
    )


def test_register_indexes_published_dataset(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    ref, snapshot = _publish(store)

    registered_at = _registered_at(1)

    entry = catalog.register(
        store,
        ref,
        registered_at=registered_at,
    )

    assert entry.ref == ref

    assert entry.kind == DATASET_KIND_DAILY_BARS

    assert entry.start_date == snapshot.start_date

    assert entry.end_date == snapshot.end_date

    assert entry.cutoff == snapshot.cutoff

    assert entry.resolver_policy_id == snapshot.resolver_policy_id

    assert entry.market_schema_version == snapshot.market_schema_version

    assert entry.instrument_count == snapshot.instrument_count

    assert entry.partition_count == snapshot.partition_count

    assert entry.registered_at == registered_at

    assert catalog.path.is_file()


def test_register_is_idempotent_and_preserves_first_registered_at(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    ref, _ = _publish(store)

    first_registered_at = _registered_at(1)

    later_registered_at = _registered_at(5)

    first = catalog.register(
        store,
        ref,
        registered_at=first_registered_at,
    )

    second = catalog.register(
        store,
        ref,
        registered_at=later_registered_at,
    )

    assert second == first

    assert second.registered_at == first_registered_at


def test_registered_at_is_normalized_to_utc(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    ref, _ = _publish(store)

    shanghai = timezone(timedelta(hours=8))

    entry = catalog.register(
        store,
        ref,
        registered_at=datetime(
            2026,
            9,
            16,
            9,
            30,
            tzinfo=shanghai,
        ),
    )

    assert entry.registered_at == datetime(
        2026,
        9,
        16,
        1,
        30,
        tzinfo=timezone.utc,
    )


def test_register_rejects_naive_registered_at(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    ref, _ = _publish(store)

    with pytest.raises(
        ValueError,
        match=("dataset_catalog_registered_at" "_must_be_timezone_aware"),
    ):
        catalog.register(
            store,
            ref,
            registered_at=datetime(
                2026,
                9,
                16,
                1,
                0,
            ),
        )


def test_get_returns_registered_dataset(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    ref, _ = _publish(store)

    expected = catalog.register(
        store,
        ref,
        registered_at=_registered_at(1),
    )

    actual = catalog.get(ref.dataset_id)

    assert actual == expected


def test_contains_reports_registration_state(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    ref, _ = _publish(store)

    assert catalog.contains(ref.dataset_id) is False

    catalog.register(
        store,
        ref,
        registered_at=_registered_at(1),
    )

    assert catalog.contains(ref.dataset_id) is True


def test_get_fails_when_catalog_does_not_exist(
    tmp_path,
) -> None:
    catalog = DatasetCatalog(tmp_path / "catalog-root")

    dataset_id = _content_id("a")

    with pytest.raises(
        DatasetCatalogNotFoundError,
        match="dataset_catalog_missing",
    ):
        catalog.get(dataset_id)


def test_get_fails_for_unregistered_dataset(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    registered_ref, _ = _publish(store)

    catalog.register(
        store,
        registered_ref,
        registered_at=_registered_at(1),
    )

    missing_id = _content_id("f")

    with pytest.raises(
        DatasetCatalogNotFoundError,
        match="dataset_catalog_not_found",
    ):
        catalog.get(missing_id)


def test_list_returns_registered_daily_datasets(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    first_ref, _ = _publish(
        store,
        cutoff=datetime(
            2026,
            9,
            15,
            8,
            0,
            tzinfo=timezone.utc,
        ),
    )

    second_ref, _ = _publish(
        store,
        cutoff=datetime(
            2026,
            9,
            15,
            9,
            0,
            tzinfo=timezone.utc,
        ),
    )

    catalog.register(
        store,
        first_ref,
        registered_at=_registered_at(1),
    )

    catalog.register(
        store,
        second_ref,
        registered_at=_registered_at(2),
    )

    entries = catalog.list_daily_bar_datasets()

    assert len(entries) == 2

    assert {entry.ref for entry in entries} == {
        first_ref,
        second_ref,
    }


def test_list_orders_by_cutoff_descending(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    early_ref, _ = _publish(
        store,
        cutoff=datetime(
            2026,
            9,
            15,
            8,
            0,
            tzinfo=timezone.utc,
        ),
    )

    late_ref, _ = _publish(
        store,
        cutoff=datetime(
            2026,
            9,
            15,
            10,
            0,
            tzinfo=timezone.utc,
        ),
    )

    catalog.register(
        store,
        early_ref,
        registered_at=_registered_at(1),
    )

    catalog.register(
        store,
        late_ref,
        registered_at=_registered_at(2),
    )

    entries = catalog.list_daily_bar_datasets()

    assert [entry.ref for entry in entries] == [
        late_ref,
        early_ref,
    ]


def test_list_has_stable_dataset_id_tiebreak(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    cutoff = datetime(
        2026,
        9,
        15,
        8,
        0,
        tzinfo=timezone.utc,
    )

    first_ref, _ = _publish(
        store,
        cutoff=cutoff,
        resolver_policy_id=("karkinos.dataset.policy.a.v1"),
    )

    second_ref, _ = _publish(
        store,
        cutoff=cutoff,
        resolver_policy_id=("karkinos.dataset.policy.b.v1"),
    )

    catalog.register(
        store,
        second_ref,
        registered_at=_registered_at(2),
    )

    catalog.register(
        store,
        first_ref,
        registered_at=_registered_at(1),
    )

    entries = catalog.list_daily_bar_datasets()

    expected = sorted(
        [
            first_ref,
            second_ref,
        ],
        key=lambda ref: ref.dataset_id,
    )

    assert [entry.ref for entry in entries] == expected


def test_list_filters_by_date_range(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    first_ref, _ = _publish(
        store,
        start_date=date(
            2026,
            9,
            1,
        ),
        end_date=date(
            2026,
            9,
            3,
        ),
        partitions=(),
    )

    second_ref, _ = _publish(
        store,
        start_date=date(
            2026,
            9,
            2,
        ),
        end_date=date(
            2026,
            9,
            4,
        ),
        partitions=(),
    )

    third_ref, _ = _publish(
        store,
        start_date=date(
            2026,
            9,
            4,
        ),
        end_date=date(
            2026,
            9,
            6,
        ),
        partitions=(),
    )

    for index, ref in enumerate(
        (
            first_ref,
            second_ref,
            third_ref,
        ),
        start=1,
    ):
        catalog.register(
            store,
            ref,
            registered_at=(_registered_at(index)),
        )

    entries = catalog.list_daily_bar_datasets(
        start_date=date(
            2026,
            9,
            2,
        ),
        end_date=date(
            2026,
            9,
            5,
        ),
    )

    # start_date >= 9/2 且 end_date <= 9/5。
    assert [entry.ref for entry in entries] == [
        second_ref,
    ]


def test_list_filters_by_cutoff(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    cutoffs = (
        datetime(
            2026,
            9,
            15,
            7,
            0,
            tzinfo=timezone.utc,
        ),
        datetime(
            2026,
            9,
            15,
            8,
            0,
            tzinfo=timezone.utc,
        ),
        datetime(
            2026,
            9,
            15,
            9,
            0,
            tzinfo=timezone.utc,
        ),
    )

    refs = []

    for index, cutoff in enumerate(
        cutoffs,
        start=1,
    ):
        ref, _ = _publish(
            store,
            cutoff=cutoff,
        )

        refs.append(ref)

        catalog.register(
            store,
            ref,
            registered_at=(_registered_at(index)),
        )

    entries = catalog.list_daily_bar_datasets(
        cutoff_lte=datetime(
            2026,
            9,
            15,
            8,
            0,
            tzinfo=timezone.utc,
        )
    )

    assert {entry.ref for entry in entries} == {
        refs[0],
        refs[1],
    }


def test_list_filters_by_resolver_policy(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    strict_ref, _ = _publish(
        store,
        resolver_policy_id=("karkinos.dataset.pit.strict.v1"),
    )

    relaxed_ref, _ = _publish(
        store,
        resolver_policy_id=("karkinos.dataset.pit.relaxed.v1"),
    )

    catalog.register(
        store,
        strict_ref,
        registered_at=_registered_at(1),
    )

    catalog.register(
        store,
        relaxed_ref,
        registered_at=_registered_at(2),
    )

    entries = catalog.list_daily_bar_datasets(
        resolver_policy_id=("karkinos.dataset.pit.strict.v1")
    )

    assert [entry.ref for entry in entries] == [
        strict_ref,
    ]


def test_list_limit_is_applied_after_sorting(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    for hour in (
        7,
        8,
        9,
    ):
        ref, _ = _publish(
            store,
            cutoff=datetime(
                2026,
                9,
                15,
                hour,
                0,
                tzinfo=timezone.utc,
            ),
        )

        catalog.register(
            store,
            ref,
            registered_at=(_registered_at(hour)),
        )

    entries = catalog.list_daily_bar_datasets(limit=2)

    assert len(entries) == 2

    assert entries[0].cutoff > entries[1].cutoff


@pytest.mark.parametrize(
    "limit",
    [
        0,
        -1,
    ],
)
def test_list_rejects_invalid_limit(
    tmp_path,
    limit,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    ref, _ = _publish(store)

    catalog.register(
        store,
        ref,
        registered_at=_registered_at(1),
    )

    with pytest.raises(
        ValueError,
        match="dataset_catalog_limit_invalid",
    ):
        catalog.list_daily_bar_datasets(limit=limit)


def test_list_rejects_boolean_limit(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    ref, _ = _publish(store)

    catalog.register(
        store,
        ref,
        registered_at=_registered_at(1),
    )

    with pytest.raises(
        TypeError,
        match="dataset_catalog_limit_must_be_int",
    ):
        catalog.list_daily_bar_datasets(limit=True)


def test_catalog_rejects_unsupported_schema_version(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    ref, _ = _publish(store)

    catalog.register(
        store,
        ref,
        registered_at=_registered_at(1),
    )

    with sqlite3.connect(catalog.path) as connection:
        connection.execute("""
            UPDATE catalog_metadata
            SET value = '999'
            WHERE key = 'schema_version'
            """)
        connection.commit()

    with pytest.raises(
        DatasetCatalogIntegrityError,
        match=("dataset_catalog_schema_unsupported"),
    ):
        catalog.get(ref.dataset_id)


def test_catalog_rejects_missing_schema_metadata(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    ref, _ = _publish(store)

    catalog.register(
        store,
        ref,
        registered_at=_registered_at(1),
    )

    with sqlite3.connect(catalog.path) as connection:
        connection.execute("""
            DELETE FROM catalog_metadata
            WHERE key = 'schema_version'
            """)
        connection.commit()

    with pytest.raises(
        DatasetCatalogIntegrityError,
        match="dataset_catalog_schema_missing",
    ):
        catalog.get(ref.dataset_id)


def test_catalog_rejects_structurally_corrupted_entry(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    ref, _ = _publish(store)

    catalog.register(
        store,
        ref,
        registered_at=_registered_at(1),
    )

    with sqlite3.connect(catalog.path) as connection:
        connection.execute(
            """
            UPDATE dataset_catalog
            SET instrument_count = -1
            WHERE dataset_id = ?
            """,
            (ref.dataset_id,),
        )
        connection.commit()

    with pytest.raises(
        DatasetCatalogIntegrityError,
        match="dataset_catalog_entry_invalid",
    ):
        catalog.get(ref.dataset_id)


def test_reregister_detects_forged_catalog_metadata(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    ref, snapshot = _publish(store)

    catalog.register(
        store,
        ref,
        registered_at=_registered_at(1),
    )

    # 伪造一个结构合法但与 Manifest 不一致的派生 metadata。
    with sqlite3.connect(catalog.path) as connection:
        connection.execute(
            """
            UPDATE dataset_catalog
            SET instrument_count = ?
            WHERE dataset_id = ?
            """,
            (
                snapshot.instrument_count + 10,
                ref.dataset_id,
            ),
        )
        connection.commit()

    # 再次从 immutable Manifest 登记时必须发现冲突，
    # 不能让 Catalog metadata 覆盖 Dataset truth。
    with pytest.raises(
        DatasetCatalogIntegrityError,
        match="dataset_catalog_entry_conflict",
    ):
        catalog.register(
            store,
            ref,
            registered_at=_registered_at(2),
        )


def test_register_requires_store_instance(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    ref, _ = _publish(store)

    with pytest.raises(
        TypeError,
        match="dataset_catalog_store_invalid",
    ):
        catalog.register(
            "not-a-store",
            ref,
            registered_at=_registered_at(1),
        )


def test_register_requires_dataset_ref(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    with pytest.raises(
        TypeError,
        match="dataset_catalog_ref_invalid",
    ):
        catalog.register(
            store,
            "not-a-dataset-ref",
            registered_at=_registered_at(1),
        )


@pytest.mark.parametrize(
    "dataset_id",
    [
        "not-a-content-id",
        "sha256:abc",
        f"sha256:{'A' * 64}",
        f"sha256:{'g' * 64}",
    ],
)
def test_get_rejects_invalid_dataset_id(
    tmp_path,
    dataset_id,
) -> None:
    catalog = DatasetCatalog(tmp_path / "catalog-root")

    with pytest.raises(
        ValueError,
        match="dataset_catalog_dataset_id_invalid",
    ):
        catalog.get(dataset_id)


def test_contains_returns_false_before_catalog_exists(
    tmp_path,
) -> None:
    catalog = DatasetCatalog(tmp_path / "catalog-root")

    assert catalog.contains(_content_id("a")) is False


def _publish_replayable_dataset(
    store: ContentAddressedObjectStore,
):
    session_date = date(
        2026,
        9,
        15,
    )

    event_time = datetime(
        2026,
        9,
        15,
        7,
        0,
        tzinfo=timezone.utc,
    )

    available_at = datetime(
        2026,
        9,
        15,
        7,
        1,
        tzinfo=timezone.utc,
    )

    captured_at = datetime(
        2026,
        9,
        15,
        7,
        3,
        tzinfo=timezone.utc,
    )

    instrument = _instrument("600000")

    bar = normalize_daily_bar(
        instrument=instrument,
        session_date=session_date,
        event_time=event_time,
        available_at=available_at,
        captured_at=captured_at,
        open_value="10.31",
        high_value="10.52",
        low_value="10.20",
        close_value="10.48",
        volume="123456",
        amount="1283912.42",
        suspended=False,
    )

    capture = capture_provider_payload(
        store,
        provider="tdx",
        operation="daily_bars",
        request={
            "kind": "daily_bars",
            "frequency": "1d",
            "start_date": (session_date.isoformat()),
            "end_date": (session_date.isoformat()),
            "instruments": [
                {
                    "symbol": (instrument.symbol),
                    "instrument_type": (instrument.instrument_type.value),
                },
            ],
        },
        raw_payload=b"tdx-replayable-response",
        payload_format="tdx.daily_bars.v1",
        adapter_version="karkinos.tdx.v1",
        started_at=(captured_at - timedelta(milliseconds=500)),
        completed_at=captured_at,
        record_count=1,
    )

    revision, materialization = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=(bar,),
        normalizer_version=("karkinos.market.normalize.v1"),
    )

    snapshot = DailyBarDatasetSnapshot(
        start_date=session_date,
        end_date=session_date,
        cutoff=datetime(
            2026,
            9,
            15,
            8,
            0,
            tzinfo=timezone.utc,
        ),
        instruments=(instrument,),
        resolver_policy_id=("karkinos.dataset.pit.strict.v1"),
        market_schema_version=(DAILY_BAR_SCHEMA_VERSION),
        partitions=(
            DailyBarDatasetPartition(
                partition_date=session_date,
                provider="tdx",
                revision_id=(revision.ref.revision_id),
                materialization_id=(materialization.materialization_id),
            ),
        ),
    )

    ref = publish_daily_bar_dataset_manifest(
        store,
        snapshot,
    )

    return ref


def test_dataset_remains_replayable_after_catalog_is_deleted(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    ref = _publish_replayable_dataset(store)

    catalog.register(
        store,
        ref,
        registered_at=_registered_at(1),
    )

    assert catalog.contains(ref.dataset_id) is True

    # Catalog 只是索引。删除它不能影响 Dataset truth。
    catalog.path.unlink()

    assert catalog.contains(ref.dataset_id) is False

    result = read_daily_bar_dataset(
        store,
        ref,
    )

    assert result.ref == ref
    assert result.row_count == 1

    assert result.bars[0].instrument.symbol == "600000"

    assert result.bars[0].close == Decimal("10.48000000")


def test_catalog_can_be_rebuilt_from_dataset_ref(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    catalog = DatasetCatalog(tmp_path / "catalog-root")

    ref, snapshot = _publish(store)

    first = catalog.register(
        store,
        ref,
        registered_at=_registered_at(1),
    )

    catalog.path.unlink()

    rebuilt = catalog.register(
        store,
        ref,
        registered_at=_registered_at(5),
    )

    assert rebuilt.ref == first.ref
    assert rebuilt.kind == first.kind

    assert rebuilt.start_date == snapshot.start_date

    assert rebuilt.end_date == snapshot.end_date

    assert rebuilt.cutoff == snapshot.cutoff

    # registered_at 是 Catalog 本地 operational metadata，
    # Catalog 重建后允许重新产生。
    assert rebuilt.registered_at == _registered_at(5)
