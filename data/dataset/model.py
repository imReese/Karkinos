"""Point-in-time Dataset 的核心值对象。

Dataset 是 Research 与 Market Data 之间的不可变证据边界。

Market Data 回答：

    Provider 曾经提供过哪些版本的市场事实？

Dataset 回答：

    对于某个明确的 cutoff、universe 和解析策略，
    这次研究实际选择了哪些 MarketRevision Materialization？

关系：

    MarketRevision
          +
    Materialization
          ↓
    PIT Resolver
          ↓
    DailyBarDatasetSnapshot
          ↓
    DatasetRef

本模块只定义不可变值对象和基础结构约束。

它不负责：

- 查询 MarketRevision；
- 判断 available_at 是否早于 cutoff；
- 选择 Provider；
- 验证交易日历；
- 写 manifest；
- 写 Parquet；
- 执行 Research。

这些职责分别属于 resolver.py、manifest.py、reader.py 等模块。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from core.types import InstrumentKey
from data.storage.objects import ObjectRef

DATASET_KIND_DAILY_BARS = "daily_bars"

_SHA256_OBJECT_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class DatasetRef:
    """一个已发布、不可变的 Dataset manifest 引用。

    Dataset identity 是 manifest 的内容地址，而不是某个 Parquet 文件地址。

    同一个底层 MarketRevision 即使物理序列化方式改变，
    只要 Dataset manifest 语义不变，Dataset 的逻辑定义仍然由 manifest
    决定。
    """

    manifest_ref: ObjectRef

    def __post_init__(self) -> None:
        if not isinstance(
            self.manifest_ref,
            ObjectRef,
        ):
            raise TypeError("dataset_ref_manifest_must_be_object_ref")

    @property
    def dataset_id(self) -> str:
        return self.manifest_ref.object_id


@dataclass(frozen=True, slots=True)
class DailyBarDatasetPartition:
    """Dataset 对一个交易日所选择的 Market Data 版本。

    revision_id 标识 canonical 市场事实版本。

    materialization_id 进一步绑定 Capture / availability provenance，
    因此 Dataset PIT lineage 不能只记录 revision_id。

    同一 Revision 可能存在：

        Revision R1
        ├── Materialization M1：9 月 15 日获取
        └── Materialization M2：9 月 20 日再次获取

    对 PIT Research 来说，M1 与 M2 的信息可用时间并不等价。
    """

    partition_date: date

    provider: str

    revision_id: str
    materialization_id: str
    verification_id: str | None = None
    # Empty retains the original fixed-basket contract. New shards declare
    # exactly which instruments they supply, without combining their captures.
    instruments: tuple[InstrumentKey, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(
            self.partition_date,
            datetime,
        ) or not isinstance(
            self.partition_date,
            date,
        ):
            raise TypeError("dataset_partition_date_must_be_date")

        provider = _require_non_empty_text(
            self.provider,
            field="partition_provider",
        )

        revision_id = _require_content_id(
            self.revision_id,
            field="revision_id",
        )

        materialization_id = _require_content_id(
            self.materialization_id,
            field="materialization_id",
        )
        verification_id = (
            None
            if self.verification_id is None
            else _require_content_id(
                self.verification_id,
                field="verification_id",
            )
        )

        object.__setattr__(
            self,
            "provider",
            provider,
        )

        object.__setattr__(
            self,
            "revision_id",
            revision_id,
        )

        object.__setattr__(
            self,
            "materialization_id",
            materialization_id,
        )
        object.__setattr__(
            self,
            "verification_id",
            verification_id,
        )
        if self.instruments:
            object.__setattr__(
                self, "instruments", _canonical_instruments(self.instruments)
            )


@dataclass(frozen=True, slots=True)
class DailyBarDatasetMembership:
    """A session's explicit Dataset selection, separate from source facts.

    Missing source references or decision time keep this exploratory. Merely
    constructing a selection does not establish point-in-time market membership.
    """

    partition_date: date
    instruments: tuple[InstrumentKey, ...]
    available_at: datetime
    source_observation_ids: tuple[str, ...] = ()
    decision_at: datetime | None = None
    maintenance_instruments: tuple[InstrumentKey, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "partition_date",
            _require_date(self.partition_date, field="membership_date"),
        )
        object.__setattr__(
            self, "instruments", _canonical_instruments(self.instruments)
        )
        if self.maintenance_instruments:
            maintenance = _canonical_instruments(self.maintenance_instruments)
            if set(maintenance).intersection(self.instruments):
                raise ValueError("dataset_membership_maintenance_overlap")
            object.__setattr__(self, "maintenance_instruments", maintenance)
        object.__setattr__(
            self,
            "available_at",
            _utc_instant(self.available_at, field="membership_available_at"),
        )
        refs = tuple(
            _require_content_id(item, field="membership_observation_id")
            for item in self.source_observation_ids
        )
        if len(refs) != len(set(refs)):
            raise ValueError("dataset_membership_observation_duplicate")
        object.__setattr__(self, "source_observation_ids", tuple(sorted(refs)))
        if self.decision_at is not None:
            decision = _utc_instant(self.decision_at, field="membership_decision_at")
            if self.available_at > decision:
                raise ValueError("dataset_membership_unavailable_at_decision")
            object.__setattr__(self, "decision_at", decision)


@dataclass(frozen=True, slots=True)
class DailyBarDatasetSnapshot:
    """一份已经完成 PIT 解析的日线 Dataset 定义。

    snapshot 本身仍然只是值对象。

    manifest.py 后续会把它序列化成稳定 JSON，并由 ObjectStore 发布，
    最终得到 DatasetRef。
    """

    start_date: date
    end_date: date

    cutoff: datetime

    instruments: tuple[
        InstrumentKey,
        ...,
    ]

    resolver_policy_id: str

    market_schema_version: str

    partitions: tuple[
        DailyBarDatasetPartition,
        ...,
    ]
    # Observations only: no adjusted prices or modeled corporate-action returns.
    corporate_action_observation_ids: tuple[str, ...] = ()
    session_memberships: tuple[DailyBarDatasetMembership, ...] = ()
    universe_policy_id: str | None = None

    def __post_init__(self) -> None:
        start_date = _require_date(
            self.start_date,
            field="start_date",
        )

        end_date = _require_date(
            self.end_date,
            field="end_date",
        )

        if start_date > end_date:
            raise ValueError("dataset_date_range_invalid")

        cutoff = _utc_instant(
            self.cutoff,
            field="cutoff",
        )

        resolver_policy_id = _require_non_empty_text(
            self.resolver_policy_id,
            field="resolver_policy_id",
        )

        market_schema_version = _require_non_empty_text(
            self.market_schema_version,
            field="market_schema_version",
        )

        instruments = _canonical_instruments(self.instruments)

        partitions = _canonical_partitions(
            self.partitions,
            start_date=start_date,
            end_date=end_date,
            sharded=bool(self.session_memberships),
        )
        memberships = tuple(
            sorted(self.session_memberships, key=lambda item: item.partition_date)
        )
        if memberships:
            if not self.universe_policy_id or not self.universe_policy_id.strip():
                raise ValueError("dataset_membership_policy_required")
            if len({item.partition_date for item in memberships}) != len(memberships):
                raise ValueError("dataset_membership_date_duplicate")
            if {item.partition_date for item in memberships} != {
                item.partition_date for item in partitions
            }:
                raise ValueError("dataset_membership_date_coverage_mismatch")
            if set(instruments) != {
                instrument
                for item in memberships
                for instrument in (*item.instruments, *item.maintenance_instruments)
            }:
                raise ValueError("dataset_membership_universe_mismatch")
            for membership in memberships:
                if membership.available_at > cutoff or (
                    membership.decision_at is not None
                    and membership.decision_at > cutoff
                ):
                    raise ValueError("dataset_membership_after_cutoff")
                supplied: set[InstrumentKey] = set()
                for part in partitions:
                    if part.partition_date != membership.partition_date:
                        continue
                    if not part.instruments:
                        raise ValueError("dataset_shard_instruments_required")
                    if supplied.intersection(part.instruments):
                        raise ValueError("dataset_shard_instrument_duplicate")
                    supplied.update(part.instruments)
                if supplied != set(
                    (*membership.instruments, *membership.maintenance_instruments)
                ):
                    raise ValueError("dataset_shard_membership_incomplete")
        elif (
            any(part.instruments for part in partitions)
            or self.universe_policy_id is not None
        ):
            raise ValueError("dataset_session_memberships_required")
        object.__setattr__(self, "session_memberships", memberships)
        verification_states = {
            partition.verification_id is not None for partition in partitions
        }
        if len(verification_states) > 1:
            raise ValueError("dataset_partition_verification_mixed")
        observation_ids = tuple(
            _require_content_id(item, field="corporate_action_observation_id")
            for item in self.corporate_action_observation_ids
        )
        if len(set(observation_ids)) != len(observation_ids):
            raise ValueError("dataset_corporate_action_observation_duplicate")
        object.__setattr__(
            self, "corporate_action_observation_ids", tuple(sorted(observation_ids))
        )

        object.__setattr__(
            self,
            "start_date",
            start_date,
        )

        object.__setattr__(
            self,
            "end_date",
            end_date,
        )

        object.__setattr__(
            self,
            "cutoff",
            cutoff,
        )

        object.__setattr__(
            self,
            "instruments",
            instruments,
        )

        object.__setattr__(
            self,
            "resolver_policy_id",
            resolver_policy_id,
        )

        object.__setattr__(
            self,
            "market_schema_version",
            market_schema_version,
        )

        object.__setattr__(
            self,
            "partitions",
            partitions,
        )

    @property
    def kind(self) -> str:
        return DATASET_KIND_DAILY_BARS

    @property
    def partition_count(self) -> int:
        return len(self.partitions)

    @property
    def instrument_count(self) -> int:
        return len(self.instruments)

    @property
    def verification_bound(self) -> bool:
        return bool(self.partitions) and all(
            partition.verification_id is not None for partition in self.partitions
        )

    @property
    def membership_evidence_bound(self) -> bool:
        """A binding, not a substitute for Reader verification or qualification."""
        return bool(self.session_memberships) and all(
            item.source_observation_ids and item.decision_at is not None
            for item in self.session_memberships
        )

    def instruments_for_session(self, day: date) -> tuple[InstrumentKey, ...]:
        if not self.session_memberships:
            return self.instruments
        for membership in self.session_memberships:
            if membership.partition_date == day:
                return membership.instruments
        raise ValueError("dataset_session_membership_missing")


def _canonical_instruments(
    instruments: tuple[
        InstrumentKey,
        ...,
    ],
) -> tuple[
    InstrumentKey,
    ...,
]:
    """验证 universe，并生成稳定顺序。"""
    normalized: list[InstrumentKey] = []

    seen: set[InstrumentKey] = set()

    for instrument in instruments:
        if not isinstance(
            instrument,
            InstrumentKey,
        ):
            raise TypeError("dataset_instrument_must_be_instrument_key")

        if instrument in seen:
            raise ValueError("dataset_instrument_duplicate")

        seen.add(instrument)
        normalized.append(instrument)

    if not normalized:
        raise ValueError("dataset_instruments_empty")

    normalized.sort(key=_instrument_sort_key)

    return tuple(normalized)


def _canonical_partitions(
    partitions: tuple[
        DailyBarDatasetPartition,
        ...,
    ],
    *,
    start_date: date,
    end_date: date,
    sharded: bool = False,
) -> tuple[
    DailyBarDatasetPartition,
    ...,
]:
    """验证并规范 Dataset partition 顺序。

    这里不要求日期连续。

    是否为交易日、是否存在缺失交易日属于 Dataset Resolver / Calendar
    的职责，model.py 不应自行猜测交易日历。
    """
    normalized: list[DailyBarDatasetPartition] = []

    seen_dates: set[date] = set()

    for partition in partitions:
        if not isinstance(
            partition,
            DailyBarDatasetPartition,
        ):
            raise TypeError("dataset_partition_invalid")

        if not (start_date <= partition.partition_date <= end_date):
            raise ValueError("dataset_partition_outside_range")

        if partition.partition_date in seen_dates and not sharded:
            raise ValueError("dataset_partition_date_duplicate")

        seen_dates.add(partition.partition_date)

        normalized.append(partition)

    normalized.sort(
        key=lambda item: (
            item.partition_date,
            tuple(_instrument_sort_key(key) for key in item.instruments),
            item.provider,
            item.revision_id,
            item.materialization_id,
        )
    )

    return tuple(normalized)


def _instrument_sort_key(
    instrument: InstrumentKey,
) -> tuple[str, str]:
    return (
        instrument.instrument_type.value,
        instrument.symbol,
    )


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
        raise TypeError(f"dataset_{field}_must_be_date")

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
        raise TypeError(f"dataset_{field}_must_be_datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"dataset_{field}_must_be_timezone_aware")

    return value.astimezone(timezone.utc)


def _require_content_id(
    value: str,
    *,
    field: str,
) -> str:
    value = _require_non_empty_text(
        value,
        field=field,
    )

    if _SHA256_OBJECT_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"dataset_{field}_invalid")

    return value


def _require_non_empty_text(
    value: str,
    *,
    field: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError(f"dataset_{field}_must_be_text")

    normalized = value.strip()

    if not normalized:
        raise ValueError(f"dataset_{field}_missing")

    return normalized
