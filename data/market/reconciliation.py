"""Market Data 跨 Provider 对账。

本模块比较两份已经规范化、不可变的 MarketRevision。

职责：

    Revision A
        +
    Revision B
        ↓
    ReconciliationReport
        ↓
    Differences

本模块只回答“哪里不同”，不决定这些差异是否应该阻断 Research。

差异的严重程度属于 Quality Policy，而不是 reconciliation。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from core.types import InstrumentKey
from data.market.model import DailyBarObservation
from data.market.quality import (
    MarketQualityDiagnostic,
    MarketQualitySeverity,
    provider_difference_diagnostic,
)
from data.market.revision import (
    MARKET_DATA_KIND_DAILY_BARS,
    MarketRevision,
    MarketRevisionMaterialization,
    validate_daily_bar_materialization,
)
from data.market.schema import (
    DAILY_BAR_SCHEMA,
    daily_bars_from_table,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
)
from data.storage.parquet import (
    read_parquet,
)

logger = logging.getLogger(__name__)


class ReconciliationDifferenceKind(str, Enum):
    """稳定的跨 Provider 差异类型。"""

    MISSING_PRIMARY = "missing_primary"
    MISSING_COMPARISON = "missing_comparison"
    VALUE_DIFFERENCE = "value_difference"
    EVENT_TIME_DIFFERENCE = "event_time_difference"
    SUSPENSION_DIFFERENCE = "suspension_difference"


@dataclass(frozen=True, slots=True)
class DailyBarReconciliationPolicy:
    """日线字段比较容差。

    canonical Provider Adapter 已经负责单位转换，因此默认采用严格比较。

    如果某个外部数据源存在公开且稳定的舍入规则，可以由调用方显式提供
    容差，而不是在 reconciliation 内部偷偷放宽。
    """

    price_tolerance: Decimal = Decimal("0")
    volume_tolerance: Decimal = Decimal("0")
    amount_tolerance: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        for field in (
            "price_tolerance",
            "volume_tolerance",
            "amount_tolerance",
        ):
            value = getattr(self, field)

            if not isinstance(value, Decimal):
                raise TypeError(f"market_reconciliation_{field}_must_be_decimal")

            if not value.is_finite() or value < 0:
                raise ValueError(f"market_reconciliation_{field}_invalid")


STRICT_DAILY_RECONCILIATION = DailyBarReconciliationPolicy()

# Tencent's reviewed daily endpoint exposes volume in lots for most SSE/SZSE
# instruments and amount in 0.01 万元 increments. AKShare normalizes those to
# shares and CNY, which means the resulting values carry at most 100-share /
# 100-CNY source precision. Keep price exact and tolerate only sub-unit-grid
# rounding when reconciling against BaoStock's finer-grained values.
BAOSTOCK_TENCENT_DAILY_RECONCILIATION_V1 = DailyBarReconciliationPolicy(
    price_tolerance=Decimal("0"),
    volume_tolerance=Decimal("99"),
    amount_tolerance=Decimal("99.99"),
)


@dataclass(frozen=True, slots=True)
class MarketReconciliationDifference:
    """一项确定性的跨 Provider 差异。"""

    kind: ReconciliationDifferenceKind
    instrument: InstrumentKey

    field: str | None = None

    primary_value: str | None = None
    comparison_value: str | None = None

    absolute_difference: Decimal | None = None


@dataclass(frozen=True, slots=True)
class MarketReconciliationReport:
    """两份 MarketRevision 的对账结果。"""

    primary_revision_id: str
    comparison_revision_id: str

    primary_provider: str
    comparison_provider: str

    matched_instrument_count: int

    primary_instrument_count: int
    comparison_instrument_count: int

    differences: tuple[MarketReconciliationDifference, ...]

    @property
    def matched(self) -> bool:
        """两份 Revision 是否完全一致。"""
        return not self.differences

    @property
    def difference_count(self) -> int:
        return len(self.differences)

    def to_quality_diagnostics(
        self,
        *,
        severity: MarketQualitySeverity,
    ) -> tuple[MarketQualityDiagnostic, ...]:
        """把对账差异转换为 Quality Gate 可消费的诊断。

        严重程度由调用方显式指定，本模块不自行决定。
        """
        return tuple(
            _difference_to_quality_diagnostic(
                difference,
                report=self,
                severity=severity,
            )
            for difference in self.differences
        )


def reconcile_daily_bar_revisions(
    store: ContentAddressedObjectStore,
    *,
    primary_revision: MarketRevision,
    primary_materialization: MarketRevisionMaterialization,
    comparison_revision: MarketRevision,
    comparison_materialization: MarketRevisionMaterialization,
    policy: DailyBarReconciliationPolicy = (STRICT_DAILY_RECONCILIATION),
) -> MarketReconciliationReport:
    """比较两个 Provider 对同一个日线分区的 canonical 市场事实。

    两边在比较前都会完整验证：

        Revision
        → Materialization
        → Capture
        → Parquet

    无法验证的物化结果不能参与 reconciliation，直接 fail closed。
    """
    _validate_revision_pair(
        primary_revision,
        comparison_revision,
    )

    validate_daily_bar_materialization(
        store,
        revision=primary_revision,
        materialization=primary_materialization,
    )

    validate_daily_bar_materialization(
        store,
        revision=comparison_revision,
        materialization=comparison_materialization,
    )

    primary_bars = _read_daily_bars(
        store,
        primary_materialization,
    )
    comparison_bars = _read_daily_bars(
        store,
        comparison_materialization,
    )

    report = reconcile_daily_bars(
        primary_bars,
        comparison_bars,
        primary_revision_id=(primary_revision.ref.revision_id),
        comparison_revision_id=(comparison_revision.ref.revision_id),
        primary_provider=primary_revision.provider,
        comparison_provider=comparison_revision.provider,
        policy=policy,
    )

    logger.info(
        "Market Data 跨 Provider 对账完成 "
        "primary=%s comparison=%s partition=%s "
        "matched=%s differences=%d",
        primary_revision.provider,
        comparison_revision.provider,
        primary_revision.partition_date.isoformat(),
        report.matched,
        report.difference_count,
    )

    return report


def reconcile_daily_bars(
    primary_bars: tuple[
        DailyBarObservation,
        ...,
    ],
    comparison_bars: tuple[
        DailyBarObservation,
        ...,
    ],
    *,
    primary_revision_id: str,
    comparison_revision_id: str,
    primary_provider: str,
    comparison_provider: str,
    policy: DailyBarReconciliationPolicy = (STRICT_DAILY_RECONCILIATION),
) -> MarketReconciliationReport:
    """纯函数形式比较两组 canonical 日线记录。"""
    primary = _index_bars(primary_bars)
    comparison = _index_bars(comparison_bars)

    primary_keys = set(primary)
    comparison_keys = set(comparison)

    differences: list[MarketReconciliationDifference] = []

    for instrument in sorted(
        primary_keys - comparison_keys,
        key=_instrument_sort_key,
    ):
        differences.append(
            MarketReconciliationDifference(
                kind=(ReconciliationDifferenceKind.MISSING_COMPARISON),
                instrument=instrument,
            )
        )

    for instrument in sorted(
        comparison_keys - primary_keys,
        key=_instrument_sort_key,
    ):
        differences.append(
            MarketReconciliationDifference(
                kind=(ReconciliationDifferenceKind.MISSING_PRIMARY),
                instrument=instrument,
            )
        )

    shared = sorted(
        primary_keys & comparison_keys,
        key=_instrument_sort_key,
    )

    for instrument in shared:
        differences.extend(
            _compare_daily_bar(
                primary[instrument],
                comparison[instrument],
                policy=policy,
            )
        )

    differences = sorted(
        differences,
        key=_difference_sort_key,
    )

    return MarketReconciliationReport(
        primary_revision_id=(
            _require_text(
                primary_revision_id,
                field="primary_revision_id",
            )
        ),
        comparison_revision_id=(
            _require_text(
                comparison_revision_id,
                field="comparison_revision_id",
            )
        ),
        primary_provider=_require_text(
            primary_provider,
            field="primary_provider",
        ),
        comparison_provider=_require_text(
            comparison_provider,
            field="comparison_provider",
        ),
        matched_instrument_count=sum(
            1
            for instrument in shared
            if not any(
                difference.instrument == instrument for difference in differences
            )
        ),
        primary_instrument_count=len(primary),
        comparison_instrument_count=len(comparison),
        differences=tuple(differences),
    )


def _validate_revision_pair(
    primary: MarketRevision,
    comparison: MarketRevision,
) -> None:
    if (
        primary.kind != MARKET_DATA_KIND_DAILY_BARS
        or comparison.kind != MARKET_DATA_KIND_DAILY_BARS
    ):
        raise ValueError("market_reconciliation_kind_unsupported")

    if primary.partition_date != comparison.partition_date:
        raise ValueError("market_reconciliation_partition_mismatch")

    if primary.market_schema_version != comparison.market_schema_version:
        raise ValueError("market_reconciliation_schema_mismatch")

    if primary.provider == comparison.provider:
        raise ValueError("market_reconciliation_same_provider")


def _read_daily_bars(
    store: ContentAddressedObjectStore,
    materialization: MarketRevisionMaterialization,
) -> tuple[DailyBarObservation, ...]:
    table = read_parquet(
        store,
        materialization.artifact,
        expected_schema=DAILY_BAR_SCHEMA,
    )

    return daily_bars_from_table(table)


def _index_bars(
    bars: tuple[
        DailyBarObservation,
        ...,
    ],
) -> dict[
    InstrumentKey,
    DailyBarObservation,
]:
    result: dict[
        InstrumentKey,
        DailyBarObservation,
    ] = {}

    for bar in bars:
        if not isinstance(
            bar,
            DailyBarObservation,
        ):
            raise TypeError("market_reconciliation_daily_bar_invalid")

        if bar.instrument in result:
            raise ValueError("market_reconciliation_duplicate_instrument")

        result[bar.instrument] = bar

    return result


def _compare_daily_bar(
    primary: DailyBarObservation,
    comparison: DailyBarObservation,
    *,
    policy: DailyBarReconciliationPolicy,
) -> list[MarketReconciliationDifference]:
    if primary.instrument != comparison.instrument:
        raise ValueError("market_reconciliation_instrument_mismatch")

    if primary.session_date != comparison.session_date:
        raise ValueError("market_reconciliation_session_mismatch")

    differences: list[MarketReconciliationDifference] = []

    if primary.event_time != comparison.event_time:
        differences.append(
            MarketReconciliationDifference(
                kind=(ReconciliationDifferenceKind.EVENT_TIME_DIFFERENCE),
                instrument=primary.instrument,
                field="event_time",
                primary_value=(primary.event_time.isoformat()),
                comparison_value=(comparison.event_time.isoformat()),
            )
        )

    if primary.suspended != comparison.suspended:
        differences.append(
            MarketReconciliationDifference(
                kind=(ReconciliationDifferenceKind.SUSPENSION_DIFFERENCE),
                instrument=primary.instrument,
                field="suspended",
                primary_value=str(primary.suspended).lower(),
                comparison_value=str(comparison.suspended).lower(),
            )
        )

    price_fields = (
        "open",
        "high",
        "low",
        "close",
    )

    for field in price_fields:
        difference = _compare_decimal_field(
            primary,
            comparison,
            field=field,
            tolerance=(policy.price_tolerance),
        )

        if difference is not None:
            differences.append(difference)

    difference = _compare_decimal_field(
        primary,
        comparison,
        field="volume",
        tolerance=policy.volume_tolerance,
    )

    if difference is not None:
        differences.append(difference)

    difference = _compare_decimal_field(
        primary,
        comparison,
        field="amount",
        tolerance=policy.amount_tolerance,
    )

    if difference is not None:
        differences.append(difference)

    return differences


def _compare_decimal_field(
    primary: DailyBarObservation,
    comparison: DailyBarObservation,
    *,
    field: str,
    tolerance: Decimal,
) -> MarketReconciliationDifference | None:
    primary_value = getattr(
        primary,
        field,
    )

    comparison_value = getattr(
        comparison,
        field,
    )

    difference = abs(primary_value - comparison_value)

    if difference <= tolerance:
        return None

    return MarketReconciliationDifference(
        kind=(ReconciliationDifferenceKind.VALUE_DIFFERENCE),
        instrument=primary.instrument,
        field=field,
        primary_value=format(
            primary_value,
            "f",
        ),
        comparison_value=format(
            comparison_value,
            "f",
        ),
        absolute_difference=difference,
    )


def _difference_to_quality_diagnostic(
    difference: MarketReconciliationDifference,
    *,
    report: MarketReconciliationReport,
    severity: MarketQualitySeverity,
) -> MarketQualityDiagnostic:
    field = difference.field or difference.kind.value

    return provider_difference_diagnostic(
        instrument=difference.instrument,
        field=field,
        primary_value=(difference.primary_value or difference.kind.value),
        comparison_value=(difference.comparison_value or difference.kind.value),
        primary_provider=(report.primary_provider),
        comparison_provider=(report.comparison_provider),
        severity=severity,
    )


def _instrument_sort_key(
    instrument: InstrumentKey,
) -> tuple[str, str]:
    return (
        instrument.instrument_type.value,
        instrument.symbol,
    )


def _difference_sort_key(
    difference: MarketReconciliationDifference,
) -> tuple[str, str, str, str]:
    return (
        difference.instrument.instrument_type.value,
        difference.instrument.symbol,
        difference.kind.value,
        difference.field or "",
    )


def _require_text(
    value: str,
    *,
    field: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError(f"market_reconciliation_{field}_must_be_text")

    normalized = value.strip()

    if not normalized:
        raise ValueError(f"market_reconciliation_{field}_missing")

    return normalized
