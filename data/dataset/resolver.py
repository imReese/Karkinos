"""Point-in-Time Dataset 解析器。

Resolver 负责把已经存在的 Market Data 历史版本解析成一份确定的
Dataset Snapshot：

    MarketRevision / Materialization candidates
                    ↓
              Quality Gate
                    ↓
              PIT eligibility
          available_at <= cutoff
                    ↓
            Provider priority
                    ↓
         deterministic selection
                    ↓
        DailyBarDatasetSnapshot

Resolver 不负责：

- 请求外部 Provider；
- 创建 MarketRevision；
- 修改历史数据；
- 推断交易日历；
- 发布 Dataset Manifest；
- 维护 latest/current Dataset。

调用方必须显式提供 expected_partition_dates。Resolver 不猜测某一天
是不是交易日。

正式 Research 可以因此做到：

    DatasetRef
        → Snapshot
        → Materialization
        → Revision
        → Capture
        → Raw Object

并且解析阶段完全基于已经落盘的数据执行。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

from core.types import InstrumentKey
from data.dataset.model import (
    DailyBarDatasetPartition,
    DailyBarDatasetSnapshot,
)
from data.market.model import (
    DailyBarObservation,
)
from data.market.quality import (
    MarketDataQualityReport,
    MarketQualityStatus,
)
from data.market.revision import (
    MARKET_DATA_KIND_DAILY_BARS,
    MarketRevision,
    MarketRevisionMaterialization,
    validate_daily_bar_materialization,
)
from data.market.schema import (
    DAILY_BAR_SCHEMA,
    DAILY_BAR_SCHEMA_VERSION,
    daily_bars_from_table,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
)
from data.storage.parquet import (
    read_parquet,
)

logger = logging.getLogger(__name__)


class DatasetResolverError(RuntimeError):
    """Dataset Resolver 基础异常。"""


class DatasetResolverIntegrityError(DatasetResolverError):
    """候选数据的 lineage 或结构不可信。"""


class DatasetPartitionUnresolvedError(DatasetResolverError):
    """某个预期分区没有可用的 PIT 候选版本。"""

    def __init__(
        self,
        partition_date: date,
    ) -> None:
        self.partition_date = partition_date

        super().__init__(f"dataset_partition_unresolved:{partition_date.isoformat()}")


class DatasetPartitionAmbiguousError(DatasetResolverError):
    """多个 MarketRevision 在 PIT 语义上无法确定先后。"""

    def __init__(
        self,
        partition_date: date,
        provider: str,
    ) -> None:
        self.partition_date = partition_date
        self.provider = provider

        super().__init__(
            "dataset_partition_revision_ambiguous:"
            f"{partition_date.isoformat()}:"
            f"{provider}"
        )


@dataclass(frozen=True, slots=True)
class DailyBarDatasetResolverPolicy:
    """日线 PIT Dataset 的确定性选择策略。

    provider_priority 从高到低排列。

    required_quality_policy_id 指定候选必须使用哪一个 Quality Policy
    完成评估，避免拿 serving_relaxed 的结果冒充正式研究质量门禁。

    allow_degraded_quality=False 时只允许 PASS。
    """

    policy_id: str

    provider_priority: tuple[str, ...]

    required_quality_policy_id: str

    allow_degraded_quality: bool = False

    def __post_init__(self) -> None:
        policy_id = _require_non_empty_text(
            self.policy_id,
            field="policy_id",
        )

        quality_policy_id = _require_non_empty_text(
            self.required_quality_policy_id,
            field=("required_quality_policy_id"),
        )

        providers: list[str] = []
        seen: set[str] = set()

        for provider in self.provider_priority:
            normalized = _require_non_empty_text(
                provider,
                field="provider",
            )

            if normalized in seen:
                raise ValueError("dataset_resolver_provider_duplicate")

            seen.add(normalized)
            providers.append(normalized)

        if not providers:
            raise ValueError("dataset_resolver_provider_priority_empty")

        if not isinstance(
            self.allow_degraded_quality,
            bool,
        ):
            raise TypeError("dataset_resolver_allow_degraded_quality_must_be_bool")

        object.__setattr__(
            self,
            "policy_id",
            policy_id,
        )
        object.__setattr__(
            self,
            "provider_priority",
            tuple(providers),
        )
        object.__setattr__(
            self,
            "required_quality_policy_id",
            quality_policy_id,
        )


@dataclass(frozen=True, slots=True)
class DailyBarResolutionCandidate:
    """一个可以参与 Dataset PIT 解析的 Market Data 候选。

    quality 必须明确绑定同一个 revision/materialization。
    Resolver 不会自行猜测 Quality Report 属于哪份数据。
    """

    revision: MarketRevision
    materialization: MarketRevisionMaterialization
    quality: MarketDataQualityReport

    def __post_init__(self) -> None:
        if not isinstance(
            self.revision,
            MarketRevision,
        ):
            raise TypeError("dataset_resolver_revision_invalid")

        if not isinstance(
            self.materialization,
            MarketRevisionMaterialization,
        ):
            raise TypeError("dataset_resolver_materialization_invalid")

        if not isinstance(
            self.quality,
            MarketDataQualityReport,
        ):
            raise TypeError("dataset_resolver_quality_invalid")


@dataclass(frozen=True, slots=True)
class _EligibleCandidate:
    """完成完整验证后的内部候选。"""

    candidate: DailyBarResolutionCandidate

    availability_frontier: datetime

    captured_at: datetime


def resolve_daily_bar_dataset(
    store: ContentAddressedObjectStore,
    *,
    candidates: tuple[
        DailyBarResolutionCandidate,
        ...,
    ],
    start_date: date,
    end_date: date,
    cutoff: datetime,
    instruments: tuple[
        InstrumentKey,
        ...,
    ],
    expected_partition_dates: tuple[
        date,
        ...,
    ],
    policy: DailyBarDatasetResolverPolicy,
) -> DailyBarDatasetSnapshot:
    """解析一份不可变的日线 PIT Dataset Snapshot。

    对每个 expected partition：

    1. 验证候选 Revision / Materialization lineage；
    2. 验证候选 Quality Report；
    3. 检查请求 universe 是否完整存在；
    4. 要求所有实际使用记录 available_at <= cutoff；
    5. 根据 Provider 优先级选择 Provider；
    6. 在该 Provider 内选择最新可用 Revision；
    7. 如果同一时点存在多个不同 Revision，则 fail closed。

    Resolver 不会因为候选不满足 PIT 条件而修改或删除 MarketRevision。
    """
    start_date = _require_date(
        start_date,
        field="start_date",
    )

    end_date = _require_date(
        end_date,
        field="end_date",
    )

    if start_date > end_date:
        raise ValueError("dataset_resolver_date_range_invalid")

    cutoff = _utc_instant(
        cutoff,
        field="cutoff",
    )

    instruments = _canonical_instruments(instruments)

    expected_dates = _canonical_expected_dates(
        expected_partition_dates,
        start_date=start_date,
        end_date=end_date,
    )

    candidate_groups: dict[
        date,
        list[DailyBarResolutionCandidate],
    ] = {partition_date: [] for partition_date in expected_dates}

    for candidate in candidates:
        if not isinstance(
            candidate,
            DailyBarResolutionCandidate,
        ):
            raise TypeError("dataset_resolver_candidate_invalid")

        partition_date = candidate.revision.partition_date

        if partition_date not in candidate_groups:
            raise ValueError("dataset_resolver_candidate_partition_unexpected")

        candidate_groups[partition_date].append(candidate)

    selected_partitions: list[DailyBarDatasetPartition] = []

    for partition_date in expected_dates:
        selected = _resolve_partition(
            store,
            partition_date=partition_date,
            candidates=tuple(candidate_groups[partition_date]),
            instruments=instruments,
            cutoff=cutoff,
            policy=policy,
        )

        selected_partitions.append(
            DailyBarDatasetPartition(
                partition_date=(partition_date),
                provider=(selected.candidate.revision.provider),
                revision_id=(selected.candidate.revision.ref.revision_id),
                materialization_id=(
                    selected.candidate.materialization.materialization_id
                ),
            )
        )

    snapshot = DailyBarDatasetSnapshot(
        start_date=start_date,
        end_date=end_date,
        cutoff=cutoff,
        instruments=instruments,
        resolver_policy_id=policy.policy_id,
        market_schema_version=(DAILY_BAR_SCHEMA_VERSION),
        partitions=tuple(selected_partitions),
    )

    providers = sorted({partition.provider for partition in snapshot.partitions})

    logger.info(
        "PIT Dataset 解析完成 "
        "start=%s end=%s cutoff=%s "
        "instruments=%d partitions=%d "
        "providers=%s policy=%s",
        start_date.isoformat(),
        end_date.isoformat(),
        cutoff.isoformat(),
        snapshot.instrument_count,
        snapshot.partition_count,
        ",".join(providers),
        policy.policy_id,
    )

    return snapshot


def _resolve_partition(
    store: ContentAddressedObjectStore,
    *,
    partition_date: date,
    candidates: tuple[
        DailyBarResolutionCandidate,
        ...,
    ],
    instruments: tuple[
        InstrumentKey,
        ...,
    ],
    cutoff: datetime,
    policy: DailyBarDatasetResolverPolicy,
) -> _EligibleCandidate:
    """为一个预期交易日选择唯一 PIT 候选。"""
    eligible: list[_EligibleCandidate] = []

    allowed_providers = set(policy.provider_priority)

    for candidate in candidates:
        if candidate.revision.provider not in allowed_providers:
            continue

        evaluated = _evaluate_candidate(
            store,
            candidate=candidate,
            partition_date=partition_date,
            instruments=instruments,
            cutoff=cutoff,
            policy=policy,
        )

        if evaluated is not None:
            eligible.append(evaluated)

    if not eligible:
        raise DatasetPartitionUnresolvedError(partition_date)

    by_provider: dict[
        str,
        list[_EligibleCandidate],
    ] = {}

    for candidate in eligible:
        by_provider.setdefault(
            candidate.candidate.revision.provider,
            [],
        ).append(candidate)

    for provider in policy.provider_priority:
        provider_candidates = by_provider.get(provider)

        if not provider_candidates:
            continue

        return _select_provider_candidate(
            partition_date=partition_date,
            provider=provider,
            candidates=tuple(provider_candidates),
        )

    # 正常情况下不可能到这里；保留 fail-closed 防御。
    raise DatasetPartitionUnresolvedError(partition_date)


def _evaluate_candidate(
    store: ContentAddressedObjectStore,
    *,
    candidate: DailyBarResolutionCandidate,
    partition_date: date,
    instruments: tuple[
        InstrumentKey,
        ...,
    ],
    cutoff: datetime,
    policy: DailyBarDatasetResolverPolicy,
) -> _EligibleCandidate | None:
    """验证并判断一个候选是否 PIT eligible。"""
    revision = candidate.revision
    materialization = candidate.materialization
    quality = candidate.quality

    if revision.kind != MARKET_DATA_KIND_DAILY_BARS:
        raise DatasetResolverIntegrityError("dataset_resolver_revision_kind_invalid")

    if revision.market_schema_version != DAILY_BAR_SCHEMA_VERSION:
        raise DatasetResolverIntegrityError("dataset_resolver_market_schema_mismatch")

    if revision.partition_date != partition_date:
        raise DatasetResolverIntegrityError("dataset_resolver_partition_mismatch")

    if materialization.revision_ref != revision.ref:
        raise DatasetResolverIntegrityError(
            "dataset_resolver_materialization_revision_mismatch"
        )

    if quality.revision_id != revision.ref.revision_id:
        raise DatasetResolverIntegrityError(
            "dataset_resolver_quality_revision_mismatch"
        )

    if quality.materialization_id != materialization.materialization_id:
        raise DatasetResolverIntegrityError(
            "dataset_resolver_quality_materialization_mismatch"
        )

    if quality.policy_id != policy.required_quality_policy_id:
        return None

    if quality.status is MarketQualityStatus.BLOCKED:
        return None

    if (
        quality.status is MarketQualityStatus.DEGRADED
        and not policy.allow_degraded_quality
    ):
        return None

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

    bars = daily_bars_from_table(table)

    requested = set(instruments)

    indexed: dict[
        InstrumentKey,
        DailyBarObservation,
    ] = {}

    for bar in bars:
        if bar.instrument in requested:
            indexed[bar.instrument] = bar

    # Dataset 当前引用的是整个 Revision，但 Reader 后续会按照
    # snapshot.instruments 过滤，因此 Revision 可以包含更大的 universe。
    #
    # 这里必须确保所有实际请求的 instrument 都存在。
    if set(indexed) != requested:
        return None

    requested_bars = tuple(indexed[instrument] for instrument in instruments)

    # PIT 核心约束：
    #
    # 只有在 cutoff 前已经 available 的事实才能进入 Dataset。
    #
    # captured_at 不作为 source-availability cutoff，因为当 Provider 能提供
    # 更准确的历史 availability evidence 时，Karkinos 允许在之后完成抓取；
    # 如果 Provider 没有 availability evidence，ingestion 已经保守地把
    # available_at fallback 到 captured_at。
    if any(bar.available_at > cutoff for bar in requested_bars):
        return None

    availability_frontier = max(bar.available_at for bar in requested_bars)

    captured_at_values = {bar.captured_at for bar in requested_bars}

    if len(captured_at_values) != 1:
        # publish_daily_bar_revision 本来已经保证这一点，
        # 这里作为 Dataset 边界再次 fail closed。
        raise DatasetResolverIntegrityError(
            "dataset_resolver_capture_time_inconsistent"
        )

    captured_at = next(iter(captured_at_values))

    return _EligibleCandidate(
        candidate=candidate,
        availability_frontier=(availability_frontier),
        captured_at=captured_at,
    )


def _select_provider_candidate(
    *,
    partition_date: date,
    provider: str,
    candidates: tuple[
        _EligibleCandidate,
        ...,
    ],
) -> _EligibleCandidate:
    """在同一个 Provider 内选择最新的 PIT Revision。

    先选择 availability frontier 最新的候选。

    如果相同 frontier 上存在不同 Revision，则没有可靠证据判断谁覆盖谁，
    因此 fail closed，而不是依赖 hash 或调用顺序偷偷选一个。

    如果只是同一个 Revision 的多个 Materialization，则选择最早 capture
    的 materialization，再用 materialization_id 做最终稳定 tie-break。
    """
    latest_frontier = max(candidate.availability_frontier for candidate in candidates)

    latest = tuple(
        candidate
        for candidate in candidates
        if (candidate.availability_frontier == latest_frontier)
    )

    revision_ids = {
        candidate.candidate.revision.ref.revision_id for candidate in latest
    }

    if len(revision_ids) > 1:
        raise DatasetPartitionAmbiguousError(
            partition_date,
            provider,
        )

    return min(
        latest,
        key=lambda candidate: (
            candidate.captured_at,
            candidate.candidate.materialization.materialization_id,
        ),
    )


def _canonical_expected_dates(
    values: tuple[
        date,
        ...,
    ],
    *,
    start_date: date,
    end_date: date,
) -> tuple[
    date,
    ...,
]:
    """验证调用方显式提供的预期 partition 日期。"""
    result: list[date] = []

    seen: set[date] = set()

    for value in values:
        partition_date = _require_date(
            value,
            field="expected_partition_date",
        )

        if not (start_date <= partition_date <= end_date):
            raise ValueError("dataset_resolver_expected_partition_outside_range")

        if partition_date in seen:
            raise ValueError("dataset_resolver_expected_partition_duplicate")

        seen.add(partition_date)
        result.append(partition_date)

    result.sort()

    return tuple(result)


def _canonical_instruments(
    values: tuple[
        InstrumentKey,
        ...,
    ],
) -> tuple[
    InstrumentKey,
    ...,
]:
    result: list[InstrumentKey] = []

    seen: set[InstrumentKey] = set()

    for value in values:
        if not isinstance(
            value,
            InstrumentKey,
        ):
            raise TypeError("dataset_resolver_instrument_invalid")

        if value in seen:
            raise ValueError("dataset_resolver_instrument_duplicate")

        seen.add(value)
        result.append(value)

    if not result:
        raise ValueError("dataset_resolver_instruments_empty")

    result.sort(
        key=lambda instrument: (
            instrument.instrument_type.value,
            instrument.symbol,
        )
    )

    return tuple(result)


def _require_date(
    value: date,
    *,
    field: str,
) -> date:
    if isinstance(
        value,
        datetime,
    ) or not isinstance(
        value,
        date,
    ):
        raise TypeError(f"dataset_resolver_{field}_must_be_date")

    return value


def _utc_instant(
    value: datetime,
    *,
    field: str,
) -> datetime:
    if not isinstance(
        value,
        datetime,
    ):
        raise TypeError(f"dataset_resolver_{field}_must_be_datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"dataset_resolver_{field}_must_be_timezone_aware")

    return value.astimezone(timezone.utc)


def _require_non_empty_text(
    value: str,
    *,
    field: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError(f"dataset_resolver_{field}_must_be_text")

    normalized = value.strip()

    if not normalized:
        raise ValueError(f"dataset_resolver_{field}_missing")

    return normalized
