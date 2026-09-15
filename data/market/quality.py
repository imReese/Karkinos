"""Market Data 质量评估与发布门禁。

Quality 不拥有市场事实，也不会修改 MarketRevision。

关系：

    MarketRevision
          +
    Materialization
          ↓
      QualityPolicy
          ↓
      QualityReport

同一个 Revision 可以根据不同用途采用不同策略：

    research_strict_v1
        → 数据不完整时阻断

    serving_relaxed_v1
        → 数据不完整时允许降级展示

质量检查只回答“这份数据是否适合某种用途”，不会修复数据、
选择 Provider，也不会改变任何 canonical market fact。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from core.types import InstrumentKey
from data.market.model import DailyBarObservation
from data.market.revision import (
    MarketRevision,
    MarketRevisionError,
    MarketRevisionMaterialization,
    validate_daily_bar_materialization,
)
from data.market.schema import (
    DAILY_BAR_SCHEMA,
    daily_bars_from_table,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
    ObjectStoreError,
)
from data.storage.parquet import (
    ParquetStorageError,
    read_parquet,
)

logger = logging.getLogger(__name__)


class MarketQualityStatus(str, Enum):
    """一次质量评估的汇总状态。"""

    PASS = "pass"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class MarketQualitySeverity(str, Enum):
    """单条质量诊断的严重程度。"""

    WARNING = "warning"
    BLOCKING = "blocking"


class MarketQualityDiagnosticKind(str, Enum):
    """稳定的 Market Data 质量诊断类型。"""

    MATERIALIZATION_INTEGRITY_FAILURE = "materialization_integrity_failure"

    EXPECTED_UNIVERSE_MISSING = "expected_universe_missing"

    MISSING_INSTRUMENT = "missing_instrument"

    UNEXPECTED_INSTRUMENT = "unexpected_instrument"

    DUPLICATE_INSTRUMENT_SESSION = "duplicate_instrument_session"

    PROVIDER_DIFFERENCE = "provider_difference"


@dataclass(frozen=True, slots=True)
class MarketQualityDiagnostic:
    """一条确定性的质量诊断。

    details 使用排序后的 tuple，而不是可变 dict，
    方便后续生成稳定 evidence identity。
    """

    kind: MarketQualityDiagnosticKind
    severity: MarketQualitySeverity

    instrument: InstrumentKey | None = None

    details: tuple[
        tuple[str, str],
        ...,
    ] = ()


@dataclass(frozen=True, slots=True)
class DailyBarQualityPolicy:
    """日线 MarketRevision 的质量策略。"""

    policy_id: str

    require_expected_universe: bool

    missing_instrument_severity: MarketQualitySeverity

    unexpected_instrument_severity: MarketQualitySeverity

    def __post_init__(self) -> None:
        normalized = str(self.policy_id).strip()

        if not normalized:
            raise ValueError("market_quality_policy_id_missing")

        object.__setattr__(
            self,
            "policy_id",
            normalized,
        )


RESEARCH_STRICT_DAILY = DailyBarQualityPolicy(
    policy_id=("karkinos.market_quality.daily.research_strict.v1"),
    require_expected_universe=True,
    missing_instrument_severity=(MarketQualitySeverity.BLOCKING),
    unexpected_instrument_severity=(MarketQualitySeverity.BLOCKING),
)


SERVING_RELAXED_DAILY = DailyBarQualityPolicy(
    policy_id=("karkinos.market_quality.daily.serving_relaxed.v1"),
    require_expected_universe=False,
    missing_instrument_severity=(MarketQualitySeverity.WARNING),
    unexpected_instrument_severity=(MarketQualitySeverity.WARNING),
)


@dataclass(frozen=True, slots=True)
class MarketDataQualityReport:
    """一份绑定 Revision Materialization 的质量评估结果."""

    revision_id: str
    materialization_id: str
    policy_id: str

    status: MarketQualityStatus

    checked_at: datetime

    observed_instrument_count: int
    expected_instrument_count: int | None

    diagnostics: tuple[
        MarketQualityDiagnostic,
        ...,
    ]

    @property
    def blocking_count(self) -> int:
        return sum(
            diagnostic.severity is MarketQualitySeverity.BLOCKING
            for diagnostic in self.diagnostics
        )

    @property
    def warning_count(self) -> int:
        return sum(
            diagnostic.severity is MarketQualitySeverity.WARNING
            for diagnostic in self.diagnostics
        )

    @property
    def blocks_publication(self) -> bool:
        """是否禁止进入要求该策略的数据发布路径。"""
        return self.status is MarketQualityStatus.BLOCKED


def evaluate_daily_bar_revision(
    store: ContentAddressedObjectStore,
    *,
    revision: MarketRevision,
    materialization: MarketRevisionMaterialization,
    policy: DailyBarQualityPolicy,
    expected_instruments: Sequence[InstrumentKey] | None = None,
    checked_at: datetime | None = None,
    additional_diagnostics: Iterable[MarketQualityDiagnostic] = (),
) -> MarketDataQualityReport:
    """验证并评估一份已固化的日线 MarketRevision。

    先验证完整 lineage：

        Revision
            ↓
        Materialization
            ↓
        Capture
            ↓
        Parquet Object

    只有物化数据本身完整后，才进行 coverage 等用途质量判断。

    完整性损坏不会抛给 Quality Gate 的调用者，而是转换为
    BLOCKED QualityReport。编程错误仍然正常抛出。
    """
    checked_at = _checked_at(checked_at)

    try:
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

    except (
        MarketRevisionError,
        ParquetStorageError,
        ObjectStoreError,
        ValueError,
    ) as exc:
        report = MarketDataQualityReport(
            revision_id=revision.ref.revision_id,
            materialization_id=(materialization.materialization_id),
            policy_id=policy.policy_id,
            status=MarketQualityStatus.BLOCKED,
            checked_at=checked_at,
            observed_instrument_count=0,
            expected_instrument_count=(
                None
                if expected_instruments is None
                else len(_expected_instrument_set(expected_instruments))
            ),
            diagnostics=(
                MarketQualityDiagnostic(
                    kind=(
                        MarketQualityDiagnosticKind.MATERIALIZATION_INTEGRITY_FAILURE
                    ),
                    severity=(MarketQualitySeverity.BLOCKING),
                    details=_details(
                        error_type=type(exc).__name__,
                    ),
                ),
            ),
        )

        _log_quality_report(report)

        return report

    report = evaluate_daily_bar_quality(
        bars,
        revision_id=revision.ref.revision_id,
        materialization_id=(materialization.materialization_id),
        policy=policy,
        expected_instruments=expected_instruments,
        checked_at=checked_at,
        additional_diagnostics=(additional_diagnostics),
    )

    _log_quality_report(report)

    return report


def evaluate_daily_bar_quality(
    bars: Sequence[DailyBarObservation],
    *,
    revision_id: str,
    materialization_id: str,
    policy: DailyBarQualityPolicy,
    expected_instruments: Sequence[InstrumentKey] | None = None,
    checked_at: datetime | None = None,
    additional_diagnostics: Iterable[MarketQualityDiagnostic] = (),
) -> MarketDataQualityReport:
    """对已验证的 canonical 日线记录执行用途质量检查。

    本函数不访问磁盘，便于独立测试质量规则。
    """
    checked_at = _checked_at(checked_at)

    diagnostics: list[MarketQualityDiagnostic] = []

    observed: set[InstrumentKey] = set()

    seen: set[
        tuple[
            object,
            str,
            str,
        ]
    ] = set()

    for bar in bars:
        if not isinstance(
            bar,
            DailyBarObservation,
        ):
            raise TypeError("market_quality_daily_bar_invalid")

        key = (
            bar.session_date,
            bar.instrument.instrument_type.value,
            bar.instrument.symbol,
        )

        if key in seen:
            diagnostics.append(
                MarketQualityDiagnostic(
                    kind=(MarketQualityDiagnosticKind.DUPLICATE_INSTRUMENT_SESSION),
                    severity=(MarketQualitySeverity.BLOCKING),
                    instrument=bar.instrument,
                    details=_details(
                        session_date=(bar.session_date.isoformat()),
                    ),
                )
            )

        seen.add(key)
        observed.add(bar.instrument)

    expected: set[InstrumentKey] | None = None

    if expected_instruments is not None:
        expected = _expected_instrument_set(expected_instruments)

    elif policy.require_expected_universe:
        diagnostics.append(
            MarketQualityDiagnostic(
                kind=(MarketQualityDiagnosticKind.EXPECTED_UNIVERSE_MISSING),
                severity=(MarketQualitySeverity.BLOCKING),
            )
        )

    if expected is not None:
        missing = sorted(
            expected - observed,
            key=_instrument_sort_key,
        )

        unexpected = sorted(
            observed - expected,
            key=_instrument_sort_key,
        )

        for instrument in missing:
            diagnostics.append(
                MarketQualityDiagnostic(
                    kind=(MarketQualityDiagnosticKind.MISSING_INSTRUMENT),
                    severity=(policy.missing_instrument_severity),
                    instrument=instrument,
                )
            )

        for instrument in unexpected:
            diagnostics.append(
                MarketQualityDiagnostic(
                    kind=(MarketQualityDiagnosticKind.UNEXPECTED_INSTRUMENT),
                    severity=(policy.unexpected_instrument_severity),
                    instrument=instrument,
                )
            )

    for diagnostic in additional_diagnostics:
        if not isinstance(
            diagnostic,
            MarketQualityDiagnostic,
        ):
            raise TypeError("market_quality_additional_diagnostic_invalid")

        diagnostics.append(diagnostic)

    diagnostics = sorted(
        diagnostics,
        key=_diagnostic_sort_key,
    )

    return MarketDataQualityReport(
        revision_id=_require_non_empty_text(
            revision_id,
            field="revision_id",
        ),
        materialization_id=(
            _require_non_empty_text(
                materialization_id,
                field="materialization_id",
            )
        ),
        policy_id=policy.policy_id,
        status=_quality_status(diagnostics),
        checked_at=checked_at,
        observed_instrument_count=len(observed),
        expected_instrument_count=(None if expected is None else len(expected)),
        diagnostics=tuple(diagnostics),
    )


def provider_difference_diagnostic(
    *,
    instrument: InstrumentKey,
    field: str,
    primary_value: str,
    comparison_value: str,
    primary_provider: str,
    comparison_provider: str,
    severity: MarketQualitySeverity,
) -> MarketQualityDiagnostic:
    """创建跨 Provider 差异诊断。

    reconciliation.py 后续只负责发现差异，
    通过这个稳定类型把结果接入 Quality Gate。
    """
    if not isinstance(
        instrument,
        InstrumentKey,
    ):
        raise TypeError("market_quality_provider_difference_instrument_invalid")

    return MarketQualityDiagnostic(
        kind=(MarketQualityDiagnosticKind.PROVIDER_DIFFERENCE),
        severity=severity,
        instrument=instrument,
        details=_details(
            field=field,
            primary_value=primary_value,
            comparison_value=(comparison_value),
            primary_provider=(primary_provider),
            comparison_provider=(comparison_provider),
        ),
    )


def _quality_status(
    diagnostics: Sequence[MarketQualityDiagnostic],
) -> MarketQualityStatus:
    if any(
        diagnostic.severity is MarketQualitySeverity.BLOCKING
        for diagnostic in diagnostics
    ):
        return MarketQualityStatus.BLOCKED

    if diagnostics:
        return MarketQualityStatus.DEGRADED

    return MarketQualityStatus.PASS


def _expected_instrument_set(
    instruments: Sequence[InstrumentKey],
) -> set[InstrumentKey]:
    result: set[InstrumentKey] = set()

    for instrument in instruments:
        if not isinstance(
            instrument,
            InstrumentKey,
        ):
            raise TypeError("market_quality_expected_instrument_invalid")

        if instrument in result:
            raise ValueError("market_quality_expected_instrument_duplicate")

        result.add(instrument)

    return result


def _instrument_sort_key(
    instrument: InstrumentKey,
) -> tuple[str, str]:
    return (
        instrument.instrument_type.value,
        instrument.symbol,
    )


def _diagnostic_sort_key(
    diagnostic: MarketQualityDiagnostic,
) -> tuple[
    str,
    str,
    str,
    str,
    tuple[tuple[str, str], ...],
]:
    instrument_type = ""
    symbol = ""

    if diagnostic.instrument is not None:
        instrument_type = diagnostic.instrument.instrument_type.value
        symbol = diagnostic.instrument.symbol

    return (
        diagnostic.severity.value,
        diagnostic.kind.value,
        instrument_type,
        symbol,
        diagnostic.details,
    )


def _details(
    **values: object,
) -> tuple[
    tuple[str, str],
    ...,
]:
    """生成稳定且不可变的诊断附加信息。"""
    return tuple(
        sorted(
            (
                key,
                str(value),
            )
            for key, value in values.items()
            if value is not None
        )
    )


def _checked_at(
    value: datetime | None,
) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)

    if not isinstance(
        value,
        datetime,
    ):
        raise TypeError("market_quality_checked_at_must_be_datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("market_quality_checked_at_must_be_timezone_aware")

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
        raise TypeError(f"market_quality_{field}_must_be_text")

    normalized = value.strip()

    if not normalized:
        raise ValueError(f"market_quality_{field}_missing")

    return normalized


def _log_quality_report(
    report: MarketDataQualityReport,
) -> None:
    """每个 Revision 只记录一条质量摘要，避免逐行日志。"""
    level = (
        logging.INFO if report.status is MarketQualityStatus.PASS else logging.WARNING
    )

    logger.log(
        level,
        "Market Data 质量检查完成 "
        "revision_id=%s materialization_id=%s "
        "policy=%s status=%s observed=%d expected=%s "
        "blocking=%d warnings=%d",
        report.revision_id,
        report.materialization_id,
        report.policy_id,
        report.status.value,
        report.observed_instrument_count,
        report.expected_instrument_count,
        report.blocking_count,
        report.warning_count,
    )
