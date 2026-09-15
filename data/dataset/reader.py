"""不可变 PIT Dataset 的离线读取与重放。

Reader 从一个已经发布的 DatasetRef 出发，沿着 manifest 中固化的
lineage 读取 Market Data：

    DatasetRef
        ↓
    Dataset Manifest
        ↓
    DailyBarDatasetSnapshot
        ↓
    MarketRevision
        ↓
    MarketRevisionMaterialization
        ↓
    Capture / Parquet
        ↓
    canonical DailyBarObservation

Reader 不重新执行 Resolver，也不会访问 Provider。

这意味着同一个 DatasetRef 在未来任何时间重放时，都必须继续读取
当初已经绑定的 Revision / Materialization，而不能偷偷切换到后来修订
的数据版本。
"""

from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa

from core.types import InstrumentKey
from data.dataset.manifest import (
    DatasetManifestError,
    read_daily_bar_dataset_manifest,
)
from data.dataset.model import (
    DailyBarDatasetPartition,
    DailyBarDatasetSnapshot,
    DatasetRef,
)
from data.market.model import (
    DailyBarObservation,
)
from data.market.revision import (
    MARKET_DATA_KIND_DAILY_BARS,
    MarketRevision,
    MarketRevisionError,
    MarketRevisionMaterialization,
    MarketRevisionRef,
    read_market_revision,
    read_market_revision_materialization,
    validate_daily_bar_materialization,
)
from data.market.schema import (
    DAILY_BAR_SCHEMA,
    daily_bars_from_table,
    daily_bars_to_table,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
    ObjectStoreError,
)
from data.storage.parquet import (
    ParquetStorageError,
    read_parquet,
)


class DatasetReaderError(RuntimeError):
    """Dataset Reader 基础异常。"""


class DatasetReaderIntegrityError(DatasetReaderError):
    """Dataset lineage 或底层数据无法通过完整性验证。"""


@dataclass(frozen=True, slots=True)
class DailyBarDatasetReadResult:
    """一次 DatasetRef 离线重放的结果。

    snapshot 是 Dataset 的不可变 PIT 定义。

    bars 是严格按照：

        partition_date
        → instrument_type
        → symbol

    排列后的 canonical Market Data。
    """

    ref: DatasetRef

    snapshot: DailyBarDatasetSnapshot

    bars: tuple[
        DailyBarObservation,
        ...,
    ]

    @property
    def row_count(self) -> int:
        return len(self.bars)

    @property
    def table(self) -> pa.Table:
        """转换为 canonical Arrow Table。"""
        return daily_bars_to_table(self.bars)


def read_daily_bar_dataset(
    store: ContentAddressedObjectStore,
    ref: DatasetRef,
) -> DailyBarDatasetReadResult:
    """完全离线重放一个已经发布的日线 Dataset。

    读取过程不会：

    - 联系 Provider；
    - 重新执行 PIT Resolver；
    - 查询所谓 latest Revision；
    - 修改 Dataset Manifest。

    Manifest 中绑定的 lineage 是唯一数据来源。
    """
    if not isinstance(
        store,
        ContentAddressedObjectStore,
    ):
        raise TypeError("dataset_reader_store_invalid")

    if not isinstance(
        ref,
        DatasetRef,
    ):
        raise TypeError("dataset_reader_ref_invalid")

    try:
        snapshot = read_daily_bar_dataset_manifest(
            store,
            ref,
        )
    except DatasetManifestError as exc:
        raise DatasetReaderIntegrityError("dataset_reader_manifest_invalid") from exc

    bars: list[DailyBarObservation] = []

    for partition in snapshot.partitions:
        partition_bars = _read_partition(
            store,
            snapshot=snapshot,
            partition=partition,
        )

        bars.extend(partition_bars)

    result = DailyBarDatasetReadResult(
        ref=ref,
        snapshot=snapshot,
        bars=tuple(bars),
    )

    _validate_dataset_result(result)

    return result


def read_daily_bar_dataset_table(
    store: ContentAddressedObjectStore,
    ref: DatasetRef,
) -> pa.Table:
    """读取 Dataset 并直接返回 canonical Arrow Table。"""
    return read_daily_bar_dataset(
        store,
        ref,
    ).table


def _read_partition(
    store: ContentAddressedObjectStore,
    *,
    snapshot: DailyBarDatasetSnapshot,
    partition: DailyBarDatasetPartition,
) -> tuple[
    DailyBarObservation,
    ...,
]:
    """读取并验证 Dataset 中绑定的一个 Market Data partition。"""
    try:
        revision_manifest_ref = store.resolve_ref(partition.revision_id)

        revision_ref = MarketRevisionRef(manifest_ref=(revision_manifest_ref))

        revision = read_market_revision(
            store,
            revision_ref,
        )

        materialization_manifest_ref = store.resolve_ref(partition.materialization_id)

        materialization = read_market_revision_materialization(
            store,
            materialization_manifest_ref,
        )

        _validate_partition_lineage(
            snapshot=snapshot,
            partition=partition,
            revision=revision,
            materialization=materialization,
        )

        # 这里使用 MarketRevision 自己的 canonical validation，
        # Dataset Reader 不复制 Revision domain 的完整性规则。
        validate_daily_bar_materialization(
            store,
            revision=revision,
            materialization=materialization,
        )

        table = read_parquet(
            store,
            materialization.artifact,
            expected_schema=DAILY_BAR_SCHEMA,
        )

    except (
        ObjectStoreError,
        MarketRevisionError,
        ParquetStorageError,
    ) as exc:
        raise DatasetReaderIntegrityError(
            "dataset_reader_partition_unreadable:"
            f"{partition.partition_date.isoformat()}"
        ) from exc

    try:
        all_bars = daily_bars_from_table(table)
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise DatasetReaderIntegrityError(
            "dataset_reader_partition_schema_invalid:"
            f"{partition.partition_date.isoformat()}"
        ) from exc

    return _select_partition_bars(
        snapshot=snapshot,
        partition=partition,
        bars=all_bars,
    )


def _validate_partition_lineage(
    *,
    snapshot: DailyBarDatasetSnapshot,
    partition: DailyBarDatasetPartition,
    revision: MarketRevision,
    materialization: MarketRevisionMaterialization,
) -> None:
    """验证 Dataset Manifest 与 Market lineage 一致。"""
    if revision.ref.revision_id != partition.revision_id:
        raise DatasetReaderIntegrityError("dataset_reader_revision_id_mismatch")

    if materialization.materialization_id != partition.materialization_id:
        raise DatasetReaderIntegrityError("dataset_reader_materialization_id_mismatch")

    if materialization.revision_ref != revision.ref:
        raise DatasetReaderIntegrityError(
            "dataset_reader_materialization_revision_mismatch"
        )

    if revision.kind != MARKET_DATA_KIND_DAILY_BARS:
        raise DatasetReaderIntegrityError("dataset_reader_revision_kind_invalid")

    if revision.partition_date != partition.partition_date:
        raise DatasetReaderIntegrityError("dataset_reader_partition_date_mismatch")

    if revision.provider != partition.provider:
        raise DatasetReaderIntegrityError("dataset_reader_provider_mismatch")

    if revision.market_schema_version != snapshot.market_schema_version:
        raise DatasetReaderIntegrityError("dataset_reader_market_schema_mismatch")


def _select_partition_bars(
    *,
    snapshot: DailyBarDatasetSnapshot,
    partition: DailyBarDatasetPartition,
    bars: tuple[
        DailyBarObservation,
        ...,
    ],
) -> tuple[
    DailyBarObservation,
    ...,
]:
    """从 MarketRevision 中取出 Dataset universe 真正需要的记录。

    Revision 可以是全市场，而 Dataset 可以只绑定其中一个较小 universe。

    Reader 必须精确重放 snapshot.instruments，不能因为 Revision 中多了
    其他股票而把额外记录带入 Research。
    """
    requested = set(snapshot.instruments)

    selected: dict[
        InstrumentKey,
        DailyBarObservation,
    ] = {}

    for bar in bars:
        if bar.session_date != partition.partition_date:
            raise DatasetReaderIntegrityError("dataset_reader_bar_partition_mismatch")

        if bar.instrument not in requested:
            continue

        if bar.instrument in selected:
            raise DatasetReaderIntegrityError("dataset_reader_duplicate_instrument")

        # Reader 再次检查 PIT boundary。
        #
        # 正常情况下 Resolver 已经保证这一点，但 Dataset Manifest 是长期
        # replay contract，因此读取边界不能只依赖“当初 Resolver 应该没错”。
        if bar.available_at > snapshot.cutoff:
            raise DatasetReaderIntegrityError("dataset_reader_bar_after_cutoff")

        selected[bar.instrument] = bar

    if set(selected) != requested:
        raise DatasetReaderIntegrityError("dataset_reader_universe_incomplete")

    # snapshot.instruments 已经在 model.py 中 canonicalize。
    # 按这个顺序读取可以保证不同机器上的 replay 顺序完全一致。
    return tuple(selected[instrument] for instrument in snapshot.instruments)


def _validate_dataset_result(
    result: DailyBarDatasetReadResult,
) -> None:
    """对完整 replay 结果做最后的结构检查。"""
    expected_rows = result.snapshot.partition_count * result.snapshot.instrument_count

    if result.row_count != expected_rows:
        raise DatasetReaderIntegrityError("dataset_reader_row_count_mismatch")

    expected_dates = tuple(
        partition.partition_date for partition in result.snapshot.partitions
    )

    actual_dates = tuple(sorted({bar.session_date for bar in result.bars}))

    if actual_dates != expected_dates:
        raise DatasetReaderIntegrityError("dataset_reader_partition_coverage_mismatch")
