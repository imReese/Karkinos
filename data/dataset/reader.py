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

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any

import pyarrow as pa

from core.types import InstrumentKey, InstrumentType
from data.dataset.manifest import (
    DatasetManifestError,
    read_daily_bar_dataset_manifest,
)
from data.dataset.model import (
    DailyBarDatasetMembership,
    DailyBarDatasetPartition,
    DailyBarDatasetSnapshot,
    DatasetRef,
)
from data.market.model import (
    DailyBarObservation,
)
from data.market.reconciliation import (
    BseTencentReportedRelation,
    reconcile_daily_bar_revisions_with_bars,
    tencent_tushare_native_read_scope,
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
    daily_bars_to_table,
)
from data.market.verification_evidence import (
    MarketVerificationEvidenceError,
    MarketVerificationStatus,
    read_market_verification_evidence,
    read_market_verification_evidence_with_component_bars,
)
from data.providers.bse_sina_history import bse_native_read_scope
from data.storage.objects import (
    ContentAddressedObjectStore,
    ObjectStoreError,
)
from data.storage.parquet import (
    ParquetStorageError,
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
    corporate_action_evidence: dict[str, Any] | None = None

    @property
    def row_count(self) -> int:
        return len(self.bars)

    @property
    def table(self) -> pa.Table:
        """转换为 canonical Arrow Table。"""
        return daily_bars_to_table(self.bars)


_CALL_VERIFIED_DATASETS: ContextVar[
    dict[tuple[str, DatasetRef], DailyBarDatasetReadResult] | None
] = ContextVar("call_verified_daily_bar_datasets", default=None)

_BarsBySession = dict[date, dict[InstrumentKey, DailyBarObservation]]
_CALL_PARENT_BAR_INDEXES: ContextVar[
    dict[
        tuple[str, DatasetRef],
        tuple[tuple[DailyBarObservation, ...], _BarsBySession],
    ]
    | None
] = ContextVar("call_verified_parent_bar_indexes", default=None)
_CALL_VERIFIED_MEMBERSHIPS: ContextVar[
    dict[
        tuple[str, int],
        tuple[DailyBarDatasetSnapshot, dict[date, tuple[InstrumentKey, ...]]],
    ]
    | None
] = ContextVar("call_verified_dataset_memberships", default=None)


@contextmanager
def daily_bar_dataset_read_scope(*, join_existing: bool = False) -> Iterator[None]:
    """Reuse immutable reads within one caller, never across cold requests."""
    if join_existing and _CALL_VERIFIED_DATASETS.get() is not None:
        yield
        return
    token = _CALL_VERIFIED_DATASETS.set({})
    index_token = _CALL_PARENT_BAR_INDEXES.set({})
    membership_token = _CALL_VERIFIED_MEMBERSHIPS.set({})
    try:
        yield
    finally:
        _CALL_VERIFIED_MEMBERSHIPS.reset(membership_token)
        _CALL_PARENT_BAR_INDEXES.reset(index_token)
        _CALL_VERIFIED_DATASETS.reset(token)


def read_daily_bar_dataset(
    store: ContentAddressedObjectStore,
    ref: DatasetRef,
) -> DailyBarDatasetReadResult:
    """Read verified bytes once per explicit call scope and isolate mutable CA."""
    if not isinstance(store, ContentAddressedObjectStore):
        raise TypeError("dataset_reader_store_invalid")
    if not isinstance(ref, DatasetRef):
        raise TypeError("dataset_reader_ref_invalid")
    verified = _CALL_VERIFIED_DATASETS.get()
    if verified is None:
        return _read_daily_bar_dataset(store, ref)
    key = (str(store.root.resolve()), ref)
    if key in verified:
        return replace(
            verified[key],
            corporate_action_evidence=deepcopy(verified[key].corporate_action_evidence),
        )
    result = _read_daily_bar_dataset(store, ref)
    verified[key] = replace(
        result, corporate_action_evidence=deepcopy(result.corporate_action_evidence)
    )
    return result


@bse_native_read_scope()
@tencent_tushare_native_read_scope()
def _read_daily_bar_dataset(
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
    # Repeated rows share immutable identities and instants within this read.
    # Keep this local: a later cold read must still verify its own source bytes.
    instruments = {key: key for key in snapshot.instruments}
    sessions: dict[date, date] = {}
    instants: dict[datetime, datetime] = {}
    _validate_membership_evidence(store, snapshot)
    memberships = {item.partition_date: item for item in snapshot.session_memberships}

    for partition in snapshot.partitions:
        partition_bars = _read_partition(
            store,
            snapshot=snapshot,
            partition=partition,
            membership=memberships.get(partition.partition_date),
        )

        bars.extend(
            replace(
                bar,
                instrument=instruments.setdefault(bar.instrument, bar.instrument),
                session_date=sessions.setdefault(bar.session_date, bar.session_date),
                event_time=instants.setdefault(bar.event_time, bar.event_time),
                available_at=instants.setdefault(bar.available_at, bar.available_at),
                captured_at=instants.setdefault(bar.captured_at, bar.captured_at),
            )
            for bar in partition_bars
        )

    bars.sort(
        key=lambda bar: (
            bar.session_date,
            bar.instrument.instrument_type.value,
            bar.instrument.symbol,
        )
    )

    result = DailyBarDatasetReadResult(
        ref=ref,
        snapshot=snapshot,
        bars=tuple(bars),
        corporate_action_evidence=read_dataset_corporate_action_evidence(
            store, snapshot
        ),
    )

    _validate_dataset_result(result)

    return result


def _parent_bars_by_session(
    store: ContentAddressedObjectStore,
    parent: DailyBarDatasetReadResult,
) -> _BarsBySession:
    """Index the actual verified parent once; never retain old prefix results."""
    indexes = _CALL_PARENT_BAR_INDEXES.get()
    key = (str(store.root.resolve()), parent.ref)
    if indexes is not None:
        previous = indexes.get(key)
        if previous is not None and previous[0] is parent.bars:
            return previous[1]
    grouped: _BarsBySession = {}
    for bar in parent.bars:
        grouped.setdefault(bar.session_date, {})[bar.instrument] = bar
    if indexes is not None:
        indexes[key] = (parent.bars, grouped)
    return grouped


def read_daily_bar_dataset_prefix(
    store: ContentAddressedObjectStore,
    ref: DatasetRef,
    *,
    verified_parent: DailyBarDatasetReadResult,
) -> DailyBarDatasetReadResult:
    """Reuse bars already fully verified by this caller's current read.

    The parent is a call-scoped read result, never a persisted trust token or a
    substitute for a new cold read. Reopen the old manifest, membership sources,
    verification times and original action captures under its own time bounds.
    A different lineage takes the ordinary complete reader path.
    """
    if not isinstance(store, ContentAddressedObjectStore):
        raise TypeError("dataset_reader_store_invalid")
    if not isinstance(ref, DatasetRef):
        raise TypeError("dataset_reader_ref_invalid")
    if not isinstance(verified_parent, DailyBarDatasetReadResult):
        raise TypeError("dataset_reader_verified_parent_invalid")
    try:
        snapshot = read_daily_bar_dataset_manifest(store, ref)
    except DatasetManifestError as exc:
        raise DatasetReaderIntegrityError("dataset_reader_manifest_invalid") from exc
    parent = verified_parent.snapshot
    if (
        snapshot.start_date != parent.start_date
        or snapshot.end_date > parent.end_date
        or snapshot.resolver_policy_id != parent.resolver_policy_id
        or snapshot.market_schema_version != parent.market_schema_version
        or snapshot.universe_policy_id != parent.universe_policy_id
        or not set(snapshot.instruments) <= set(parent.instruments)
        or snapshot.partitions != parent.partitions[: len(snapshot.partitions)]
        or snapshot.session_memberships
        != parent.session_memberships[: len(snapshot.session_memberships)]
    ):
        # A call may replay many independently frozen historical revisions.
        # Validate a different lineage cold without retaining each full history
        # in the operation's current-Dataset cache.
        return _read_daily_bar_dataset(store, ref)
    _validate_membership_evidence(store, snapshot)
    memberships = {item.partition_date: item for item in snapshot.session_memberships}
    grouped = _parent_bars_by_session(store, verified_parent)
    bars: list[DailyBarObservation] = []
    for partition in snapshot.partitions:
        if partition.verification_id is not None:
            try:
                verification = read_market_verification_evidence(
                    store, store.resolve_ref(partition.verification_id)
                )
            except (ObjectStoreError, MarketVerificationEvidenceError) as exc:
                raise DatasetReaderIntegrityError(
                    "dataset_reader_verification_unreadable"
                ) from exc
            if verification.checked_at > snapshot.cutoff:
                raise DatasetReaderIntegrityError(
                    "dataset_reader_verification_after_cutoff"
                )
            membership = memberships.get(partition.partition_date)
            if (
                membership is not None
                and membership.decision_at is not None
                and verification.checked_at > membership.decision_at
            ):
                raise DatasetReaderIntegrityError(
                    "dataset_reader_verification_after_decision"
                )
        available = grouped.get(partition.partition_date, {})
        bars.extend(
            _select_partition_bars(
                snapshot=snapshot,
                partition=partition,
                membership=memberships.get(partition.partition_date),
                bars=tuple(
                    available[key]
                    for key in (partition.instruments or snapshot.instruments)
                    if key in available
                ),
            )
        )
    result = DailyBarDatasetReadResult(
        ref=ref,
        snapshot=snapshot,
        bars=tuple(
            sorted(
                bars,
                key=lambda bar: (
                    bar.session_date,
                    bar.instrument.instrument_type.value,
                    bar.instrument.symbol,
                ),
            )
        ),
        corporate_action_evidence=read_dataset_corporate_action_evidence(
            store, snapshot
        ),
    )
    _validate_dataset_result(result)
    return result


def read_dataset_corporate_action_evidence(
    store: ContentAddressedObjectStore,
    snapshot: DailyBarDatasetSnapshot,
    *,
    include_capture_freshness: bool = False,
) -> dict[str, Any] | None:
    """Replay the bound observations; an empty provider report is not full coverage."""
    if not snapshot.corporate_action_observation_ids:
        return None
    from data.market.capture import ProviderCaptureError
    from data.market.corporate_actions import (
        CorporateActionObservationError,
        read_corporate_action_observation,
        summarize_corporate_action_observation,
    )

    # A prospective market-date window is a single actual batch composition,
    # distinct from the persisted per-stock full-history v1 observations.
    if len(snapshot.corporate_action_observation_ids) == 1:
        from data.market.corporate_actions import (
            WINDOW_SCHEMA,
            read_corporate_action_window,
        )

        identity = snapshot.corporate_action_observation_ids[0]
        try:
            raw = json.loads(store.read_bytes_by_id(identity))
            if raw.get("schema_version") == WINDOW_SCHEMA:
                evidence = read_corporate_action_window(
                    store, store.resolve_ref(identity)
                )
                actual = tuple(
                    InstrumentKey.from_values(**item)
                    for item in evidence.pop("instruments")
                )
                if actual != snapshot.instruments:
                    raise DatasetReaderIntegrityError(
                        "dataset_corporate_action_coverage_mismatch"
                    )
                if datetime.fromisoformat(evidence["available_at"]) > snapshot.cutoff:
                    raise DatasetReaderIntegrityError(
                        "dataset_corporate_action_after_cutoff"
                    )
                if (
                    date.fromisoformat(evidence["coverage_end_date"])
                    < snapshot.end_date
                ):
                    raise DatasetReaderIntegrityError(
                        "dataset_corporate_action_window_incomplete"
                    )
                if not include_capture_freshness:
                    evidence.pop("oldest_captured_at")
                return evidence
        except (
            CorporateActionObservationError,
            ProviderCaptureError,
            ObjectStoreError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            if isinstance(exc, DatasetReaderIntegrityError):
                raise
            raise DatasetReaderIntegrityError(
                "dataset_corporate_action_unreadable"
            ) from exc
    summaries, seen, oldest = [], set(), []
    try:
        for observation_id in snapshot.corporate_action_observation_ids:
            observation = read_corporate_action_observation(
                store, store.resolve_ref(observation_id)
            )
            instrument = InstrumentKey(
                observation["instrument"]["symbol"],
                InstrumentType(observation["instrument"]["instrument_type"]),
            )
            if instrument in seen or instrument not in snapshot.instruments:
                raise DatasetReaderIntegrityError(
                    "dataset_corporate_action_instrument_mismatch"
                )
            seen.add(instrument)
            oldest.append(
                observation.get("oldest_captured_at", observation["captured_at"])
            )
            if datetime.fromisoformat(observation["available_at"]) > snapshot.cutoff:
                raise DatasetReaderIntegrityError(
                    "dataset_corporate_action_after_cutoff"
                )
            summaries.append(
                summarize_corporate_action_observation(
                    observation,
                    start_date=snapshot.start_date,
                    end_date=snapshot.end_date,
                )
            )
    except (
        CorporateActionObservationError,
        ObjectStoreError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise DatasetReaderIntegrityError(
            "dataset_corporate_action_unreadable"
        ) from exc
    if seen != set(snapshot.instruments):
        raise DatasetReaderIntegrityError("dataset_corporate_action_coverage_mismatch")
    result = dict(summaries[0])
    result.update(
        observation_ids=list(snapshot.corporate_action_observation_ids),
        available_at=max(item["available_at"] for item in summaries),
        captured_at=max(item["captured_at"] for item in summaries),
        events=[event for item in summaries for event in item["events"]],
        limitations=sorted(
            {limit for item in summaries for limit in item["limitations"]}
        ),
    )
    if any(
        item.get("source_extent") == "selected_events"
        or item.get("coverage_status") == "selected_events"
        for item in summaries
    ):
        result.update(
            coverage_status="selected_events",
            source_extent="selected_events",
            availability_basis="all_parent_captures_completed",
        )
    for key in ("total_record_count", "matched_event_count", "undated_event_count"):
        result[key] = sum(item[key] for item in summaries)
    if include_capture_freshness:
        # Keep the default summary byte-for-byte compatible with frozen report
        # bindings; operational freshness is an optional derived projection.
        result["oldest_captured_at"] = min(
            oldest,
            key=datetime.fromisoformat,
        )
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
    membership: DailyBarDatasetMembership | None,
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

        all_bars = _validate_partition_lineage(
            store=store,
            snapshot=snapshot,
            partition=partition,
            membership=membership,
            revision=revision,
            materialization=materialization,
        )

        if all_bars is None:
            # A verified partition already validated both sources while replaying
            # reconciliation. Legacy partitions validate their selected lineage.
            all_bars = validate_daily_bar_materialization(
                store,
                revision=revision,
                materialization=materialization,
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

    return _select_partition_bars(
        snapshot=snapshot,
        partition=partition,
        membership=membership,
        bars=all_bars,
    )


def _validate_partition_lineage(
    *,
    store: ContentAddressedObjectStore,
    snapshot: DailyBarDatasetSnapshot,
    partition: DailyBarDatasetPartition,
    membership: DailyBarDatasetMembership | None,
    revision: MarketRevision,
    materialization: MarketRevisionMaterialization,
) -> tuple[DailyBarObservation, ...] | None:
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

    if partition.verification_id is not None:
        try:
            verification, component_bars = (
                read_market_verification_evidence_with_component_bars(
                    store,
                    store.resolve_ref(partition.verification_id),
                )
            )
        except (ObjectStoreError, MarketVerificationEvidenceError) as exc:
            raise DatasetReaderIntegrityError(
                "dataset_reader_verification_unreadable"
            ) from exc
        if verification.status is not MarketVerificationStatus.MATCHED:
            raise DatasetReaderIntegrityError("dataset_reader_verification_not_matched")
        if verification.checked_at > snapshot.cutoff:
            raise DatasetReaderIntegrityError(
                "dataset_reader_verification_after_cutoff"
            )
        if (
            membership is not None
            and membership.decision_at is not None
            and verification.checked_at > membership.decision_at
        ):
            raise DatasetReaderIntegrityError(
                "dataset_reader_verification_after_decision"
            )
        selected = (
            partition.provider,
            partition.revision_id,
            partition.materialization_id,
        )
        verified_sides = {
            (
                verification.report.primary_provider,
                verification.report.primary_revision_id,
                verification.primary_materialization_id,
            ),
            (
                verification.report.comparison_provider,
                verification.report.comparison_revision_id,
                verification.comparison_materialization_id,
            ),
        }
        if selected not in verified_sides:
            raise DatasetReaderIntegrityError(
                "dataset_reader_verification_lineage_mismatch"
            )
        if verification.component_relation is not None and selected != (
            verification.report.primary_provider,
            verification.report.primary_revision_id,
            verification.primary_materialization_id,
        ):
            raise DatasetReaderIntegrityError(
                "dataset_reader_tencent_relation_requires_official_bar"
                if type(verification.component_relation) is BseTencentReportedRelation
                else "dataset_reader_auction_requires_sina_bar"
            )
        if component_bars is not None:
            # The evidence owner already reproduced both materializations and
            # the complete component report during this read. The lineage and
            # temporal checks above still apply to these exact verified sides.
            primary_bars, comparison_bars = component_bars
            if selected == (
                verification.report.primary_provider,
                verification.report.primary_revision_id,
                verification.primary_materialization_id,
            ):
                return primary_bars
            return comparison_bars
        try:
            primary_revision = read_market_revision(
                store,
                MarketRevisionRef(
                    store.resolve_ref(verification.report.primary_revision_id)
                ),
            )
            primary_materialization = read_market_revision_materialization(
                store,
                store.resolve_ref(verification.primary_materialization_id),
            )
            comparison_revision = read_market_revision(
                store,
                MarketRevisionRef(
                    store.resolve_ref(verification.report.comparison_revision_id)
                ),
            )
            comparison_materialization = read_market_revision_materialization(
                store,
                store.resolve_ref(verification.comparison_materialization_id),
            )
            replayed_report, primary_bars, comparison_bars = (
                reconcile_daily_bar_revisions_with_bars(
                    store,
                    primary_revision=primary_revision,
                    primary_materialization=primary_materialization,
                    comparison_revision=comparison_revision,
                    comparison_materialization=comparison_materialization,
                    policy=verification.policy,
                    component_relation=verification.component_relation,
                    component_checked_at=verification.checked_at,
                )
            )
        except (
            ObjectStoreError,
            MarketRevisionError,
            ParquetStorageError,
            TypeError,
            ValueError,
        ) as exc:
            raise DatasetReaderIntegrityError(
                "dataset_reader_verification_materialization_unreadable"
            ) from exc
        if replayed_report != verification.report:
            raise DatasetReaderIntegrityError(
                "dataset_reader_verification_report_mismatch"
            )
        if selected == (
            verification.report.primary_provider,
            verification.report.primary_revision_id,
            verification.primary_materialization_id,
        ):
            return primary_bars
        return comparison_bars
    return None


def _select_partition_bars(
    *,
    snapshot: DailyBarDatasetSnapshot,
    partition: DailyBarDatasetPartition,
    membership: DailyBarDatasetMembership | None,
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
    requested = set(partition.instruments or snapshot.instruments)

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
        if (
            membership is not None
            and membership.decision_at is not None
            and max(bar.available_at, bar.captured_at) > membership.decision_at
        ):
            raise DatasetReaderIntegrityError("dataset_reader_bar_after_decision")

        selected[bar.instrument] = bar

    if set(selected) != requested:
        raise DatasetReaderIntegrityError("dataset_reader_universe_incomplete")

    # snapshot.instruments 已经在 model.py 中 canonicalize。
    # 按这个顺序读取可以保证不同机器上的 replay 顺序完全一致。
    return tuple(
        selected[instrument]
        for instrument in (partition.instruments or snapshot.instruments)
    )


def _validate_dataset_result(
    result: DailyBarDatasetReadResult,
) -> None:
    """对完整 replay 结果做最后的结构检查。"""
    expected_rows = (
        sum(
            len(item.instruments) + len(item.maintenance_instruments)
            for item in result.snapshot.session_memberships
        )
        if result.snapshot.session_memberships
        else result.snapshot.partition_count * result.snapshot.instrument_count
    )

    if result.row_count != expected_rows:
        raise DatasetReaderIntegrityError("dataset_reader_row_count_mismatch")

    expected_dates = tuple(
        sorted({partition.partition_date for partition in result.snapshot.partitions})
    )

    actual_dates = tuple(sorted({bar.session_date for bar in result.bars}))

    if actual_dates != expected_dates:
        raise DatasetReaderIntegrityError("dataset_reader_partition_coverage_mismatch")


def dataset_session_nontrading_instruments(
    store, snapshot: DailyBarDatasetSnapshot | None, *, session_date: date | None = None
) -> dict[date, tuple[InstrumentKey, ...]]:
    """Replay dated raw status proof; this does not replace the full bar reader."""
    if snapshot is None:
        return {}
    return _validate_membership_evidence(store, snapshot, session_date=session_date)


def _validate_membership_evidence(
    store, snapshot: DailyBarDatasetSnapshot, *, session_date: date | None = None
) -> dict[date, tuple[InstrumentKey, ...]]:
    """Verify actual source bytes/times, without inferring historical membership."""
    from data.market.capture import ProviderCaptureError
    from data.providers.baostock import (
        BaoStockDailyBarError,
        read_baostock_historical_status,
    )
    from data.providers.bse_official_activity import (
        read_bse_official_historical_activity,
    )
    from data.providers.sse_suspension import read_sse_structured_suspension_status
    from data.providers.szse_memo_suspension import (
        read_szse_security_identity_relation,
        read_szse_structured_suspension_status,
    )
    from data.providers.szse_suspension import (
        SZSE_SUSPENSION_V2_ADAPTER_VERSION,
        read_sse_suspension_status,
        read_szse_suspension_status,
        read_szse_suspension_status_v2,
    )
    from data.providers.tushare_status import read_tushare_historical_status

    verified = _CALL_VERIFIED_MEMBERSHIPS.get()
    cache_key = (
        (str(store.root.resolve()), id(snapshot))
        if verified is not None
        and type(snapshot) is DailyBarDatasetSnapshot
        and all(
            type(item) is DailyBarDatasetMembership
            and isinstance(item.maintenance_instruments, tuple)
            for item in snapshot.session_memberships
        )
        else None
    )
    if verified is not None and cache_key is not None and cache_key in verified:
        # Retaining the immutable snapshot prevents object-id reuse. Only a
        # completed full validation can populate this request-local projection.
        _, previous = verified[cache_key]
        return {
            day: keys
            for day, keys in previous.items()
            if session_date is None or day == session_date
        }

    nontrading = {}
    # A range capture and master may serve thousands of dates. Reopen their
    # bytes once in this validation call; a later cold read verifies them again.
    sources = {}
    headers: dict[str, tuple[Any, Any]] = {}

    def source_header(identity: str) -> tuple[Any, Any]:
        if identity not in headers:
            ref = store.resolve_ref(identity)
            headers[identity] = ref, json.loads(store.read_bytes(ref))
        return headers[identity]

    for membership in getattr(snapshot, "session_memberships", ()):
        if session_date is not None and membership.partition_date != session_date:
            continue
        if not membership.source_observation_ids:
            continue
        members: set[InstrumentKey] = set()
        session_nontrading: set[InstrumentKey] = set()
        historical_status: dict[InstrumentKey, str] = {}
        historical_requests = []
        availability = []
        try:
            for identity in membership.source_observation_ids:
                source_key = identity
                identity_refs = ()
                source_ref, source = source_header(identity)
                if (source.get("provider"), source.get("operation")) == (
                    "szse_memo",
                    "suspension_status_probe",
                ):
                    # Identity must be bound independently by every dated
                    # membership; a prior alias-cache hit cannot supply it.
                    identity_ids = []
                    for related in membership.source_observation_ids:
                        _, header = source_header(related)
                        if (header.get("provider"), header.get("operation")) == (
                            "szse_disclosure",
                            "security_identity_announcement",
                        ):
                            identity_ids.append(related)
                    identity_ids = tuple(sorted(identity_ids))
                    identity_refs = tuple(
                        source_header(item)[0] for item in identity_ids
                    )
                    source_key = identity, identity_ids
                if source_key not in sources:
                    if source.get("schema_version") == "karkinos.provider_capture.v1":
                        source_kind = (source.get("provider"), source.get("operation"))
                        status_kwargs = {}
                        if source_kind == (
                            "szse_disclosure",
                            "security_identity_announcement",
                        ):
                            sources[source_key] = (
                                "security_identity",
                                read_szse_security_identity_relation(store, source_ref),
                            )
                            # Identity provenance supplies no members/status.
                            availability.append(sources[source_key][1][0].completed_at)
                            continue
                        if source_kind == ("szse_memo", "suspension_status_probe"):
                            read_status = read_szse_structured_suspension_status
                            status_kwargs = {
                                "selected_instruments": snapshot.instruments,
                                "identity_capture_refs": identity_refs,
                            }
                        elif source_kind == ("baostock", "daily_bars"):
                            read_status = read_baostock_historical_status
                        elif source_kind == ("tushare", "suspend_d"):
                            read_status = read_tushare_historical_status
                        elif source_kind == (
                            "szse_disclosure",
                            "suspension_announcement",
                        ):
                            read_status = (
                                read_szse_suspension_status_v2
                                if source.get("adapter_version")
                                == SZSE_SUSPENSION_V2_ADAPTER_VERSION
                                else read_szse_suspension_status
                            )
                        elif source_kind == (
                            "sse_disclosure",
                            "suspension_announcement",
                        ):
                            read_status = read_sse_suspension_status
                        elif source_kind == (
                            "bse_official_kline_probe",
                            "public_kline_probe",
                        ):
                            read_status = read_bse_official_historical_activity
                        elif source_kind == (
                            "sse_suspension",
                            "suspension_status_probe",
                        ):
                            read_status = read_sse_structured_suspension_status
                            status_kwargs = {
                                "selected_instruments": snapshot.instruments
                            }
                        else:
                            raise ValueError("historical_status_source_unsupported")
                        sources[source_key] = (
                            "historical_status",
                            read_status(store, source_ref, **status_kwargs),
                        )
                    else:
                        sources[source_key] = (
                            "master",
                            _membership_master_evidence(store, source),
                        )
                kind, source = sources[source_key]
                if kind == "security_identity":
                    availability.append(source[0].completed_at)
                    continue
                if kind == "historical_status":
                    capture, request, statuses = source
                    if membership.decision_at is not None or not (
                        request.start_date
                        <= membership.partition_date
                        <= request.end_date
                    ):
                        raise ValueError("historical_status_not_exploratory_or_dated")
                    historical_requests.append(request)
                    for key, status in statuses.get(
                        membership.partition_date, {}
                    ).items():
                        if (
                            key in historical_status
                            and historical_status[key] != status
                        ):
                            if "0" in (historical_status[key], status):
                                raise ValueError("historical_status_sources_conflict")
                            # Explicit activity and a resumption/intraday record
                            # both contradict a full-day halt. The latter alone
                            # cannot establish a traded bar or active status.
                            if historical_status[key] == "1":
                                continue
                        historical_status[key] = status
                    availability.append(capture.completed_at)
                    continue
                source_members, available, dated_nontrading = source
                session_nontrading.update(
                    dated_nontrading.get(membership.partition_date, ())
                )
                availability.append(available)
                members.update(source_members)
            if historical_requests:
                if not members or any(
                    not set(request.instruments) <= members
                    for request in historical_requests
                ):
                    raise ValueError("historical_status_membership_source_missing")
                if any(
                    status != "0" and key in session_nontrading
                    for key, status in historical_status.items()
                ):
                    raise ValueError("historical_status_sources_conflict")
                session_nontrading.update(
                    key for key, status in historical_status.items() if status == "0"
                )
                if session_nontrading.intersection(
                    (*membership.instruments, *membership.maintenance_instruments)
                ):
                    raise ValueError("historical_status_traded_membership_conflict")
            if (
                max(availability) != membership.available_at
                or not set(membership.instruments) <= members
            ):
                raise ValueError("membership_source_mismatch")
            if session_nontrading:
                nontrading[membership.partition_date] = tuple(
                    sorted(
                        session_nontrading,
                        key=lambda key: (key.instrument_type.value, key.symbol),
                    )
                )
        except (
            ObjectStoreError,
            ProviderCaptureError,
            BaoStockDailyBarError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ) as exc:
            raise DatasetReaderIntegrityError(
                "dataset_membership_evidence_invalid"
            ) from exc
    if verified is not None and cache_key is not None and session_date is None:
        verified[cache_key] = (snapshot, dict(nontrading))
    return nontrading


def _membership_master_evidence(store, source):
    """Replay a master once, preserving its actual date and availability."""
    if (
        source["schema_version"]
        not in {
            "karkinos.market_universe_snapshot.v2",
            "karkinos.market_universe_snapshot.v3",
        }
        or source["membership_basis"] != "current_active_stock_master"
        or source["availability_basis"] != "capture_completed_at"
        or source["observation_basis"] != "adapter_response"
    ):
        raise ValueError("unsupported_membership_source")
    started = datetime.fromisoformat(source["capture_started_at"])
    completed = datetime.fromisoformat(source["capture_completed_at"])
    available = datetime.fromisoformat(source["available_at"])
    if (
        any(value.utcoffset() is None for value in (started, completed, available))
        or not started <= completed == available
    ):
        raise ValueError("invalid_membership_source_time")
    dated_nontrading = {}
    if "source_capture_ids" in source:
        from data.store import (
            require_stock_master_capture_evidence,
            stock_master_nontrading_instruments,
        )

        require_stock_master_capture_evidence(store, source)
        day = date.fromisoformat(source["trade_date"])
        dated_nontrading[day] = stock_master_nontrading_instruments(
            source, session_date=day
        )
    members = {
        InstrumentKey(str(row["symbol"]), InstrumentType.STOCK)
        for row in source["members"]
    }
    return members, available, dated_nontrading
