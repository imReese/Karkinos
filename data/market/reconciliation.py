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

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from core.types import InstrumentKey, InstrumentType
from data.market.capture import read_provider_capture, read_provider_raw_payload
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
from data.storage.objects import (
    ContentAddressedObjectStore,
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
    source_precision_policy: str | None = None

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
        if self.source_precision_policy is not None:
            amounts = {
                "karkinos.eastmoney.bse.whole_hand_resolution.v1": (
                    Decimal(0),
                    Decimal(99),
                    Decimal(0),
                ),
                "karkinos.baostock_tushare.amount_resolution.v1": (
                    Decimal(0),
                    Decimal(0),
                    Decimal("0.99"),
                ),
            }
            if amounts.get(self.source_precision_policy) != (
                self.price_tolerance,
                self.volume_tolerance,
                self.amount_tolerance,
            ):
                raise ValueError(
                    "market_reconciliation_source_precision_policy_invalid"
                )


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

# The reviewed Eastmoney response reports BSE volume as integer hands. The
# rounding direction is unknown: this accepts only a difference smaller than
# one reported 100-share unit, without claiming exact volume agreement. Prices,
# amount, event time and all other venues retain exact comparison. Replay also
# proves the actual v2 raw integer-hand response before using this allowance.
EASTMONEY_TUSHARE_BSE_RECONCILIATION_V1 = DailyBarReconciliationPolicy(
    volume_tolerance=Decimal("99"),
    source_precision_policy="karkinos.eastmoney.bse.whole_hand_resolution.v1",
)

# TuShare reports amount in thousand CNY, with three to five decimal places in
# the captured stock response. Preserve Bao's exact cents and allow only a
# sub-CNY representational difference. This does not claim a rounding direction
# or relax prices/volume; replay verifies the original raw unit conversion.
BAOSTOCK_TUSHARE_AMOUNT_RECONCILIATION_V1 = DailyBarReconciliationPolicy(
    amount_tolerance=Decimal("0.99"),
    source_precision_policy="karkinos.baostock_tushare.amount_resolution.v1",
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
    """完整验证两份 lineage 并返回稳定的跨 Provider 对账报告。"""
    report, _, _ = reconcile_daily_bar_revisions_with_bars(
        store,
        primary_revision=primary_revision,
        primary_materialization=primary_materialization,
        comparison_revision=comparison_revision,
        comparison_materialization=comparison_materialization,
        policy=policy,
    )
    return report


def reconcile_daily_bar_revisions_with_bars(
    store: ContentAddressedObjectStore,
    *,
    primary_revision: MarketRevision,
    primary_materialization: MarketRevisionMaterialization,
    comparison_revision: MarketRevision,
    comparison_materialization: MarketRevisionMaterialization,
    policy: DailyBarReconciliationPolicy = (STRICT_DAILY_RECONCILIATION),
) -> tuple[
    MarketReconciliationReport,
    tuple[DailyBarObservation, ...],
    tuple[DailyBarObservation, ...],
]:
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

    primary_bars = validate_daily_bar_materialization(
        store,
        revision=primary_revision,
        materialization=primary_materialization,
    )

    comparison_bars = validate_daily_bar_materialization(
        store,
        revision=comparison_revision,
        materialization=comparison_materialization,
    )
    if (
        policy.source_precision_policy
        == "karkinos.eastmoney.bse.whole_hand_resolution.v1"
    ):
        _validate_eastmoney_bse_precision(
            store,
            primary_materialization
            if primary_revision.provider == "akshare"
            else comparison_materialization,
            primary_bars if primary_revision.provider == "akshare" else comparison_bars,
            primary_provider=primary_revision.provider,
            comparison_provider=comparison_revision.provider,
            precision_policy=policy.source_precision_policy,
        )
    elif (
        policy.source_precision_policy
        == "karkinos.baostock_tushare.amount_resolution.v1"
    ):
        _validate_tushare_amount_precision(
            store,
            primary_materialization
            if primary_revision.provider == "tushare"
            else comparison_materialization,
            primary_bars if primary_revision.provider == "tushare" else comparison_bars,
            primary_provider=primary_revision.provider,
            comparison_provider=comparison_revision.provider,
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

    return report, primary_bars, comparison_bars


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
    if (
        policy.source_precision_policy
        == "karkinos.eastmoney.bse.whole_hand_resolution.v1"
    ):
        if {primary_provider, comparison_provider} != {"akshare", "tushare"}:
            raise ValueError("market_reconciliation_source_precision_pair_invalid")
        eastmoney = primary if primary_provider == "akshare" else comparison
        if any(
            _bse_instrument(key) and bar.volume % 100 for key, bar in eastmoney.items()
        ):
            raise ValueError("market_reconciliation_source_precision_volume_invalid")
    elif (
        policy.source_precision_policy
        == "karkinos.baostock_tushare.amount_resolution.v1"
        and {primary_provider, comparison_provider} != {"baostock", "tushare"}
    ):
        raise ValueError("market_reconciliation_source_precision_pair_invalid")

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


def _validate_tushare_amount_precision(
    store, materialization, bars, *, primary_provider, comparison_provider
):
    if {primary_provider, comparison_provider} != {"baostock", "tushare"}:
        raise ValueError("market_reconciliation_source_precision_pair_invalid")
    capture = read_provider_capture(store, materialization.capture_ref)
    try:
        payload = json.loads(read_provider_raw_payload(store, capture))
        versions = {
            "karkinos.tushare.daily_bar.v1": {"tushare.pro.daily_bar.dataframe.v1"},
            "karkinos.tushare.daily_bar.v2": {
                "tushare.pro.daily_bar.dataframe.v1",
                "tushare.pro.market_daily.dataframe.v2",
            },
        }
        if (
            capture.provider != "tushare"
            or capture.payload_format
            not in versions.get(capture.adapter_version, set())
            or payload["schema"] != capture.payload_format
        ):
            raise ValueError
        wanted = {
            (
                bar.instrument.symbol,
                bar.instrument.instrument_type,
                bar.session_date.strftime("%Y%m%d"),
            ): bar.amount
            for bar in bars
        }
        actual = {}
        for call in payload["calls"]:
            if call["endpoint"] not in {"daily", "fund_daily"}:
                raise ValueError
            kind = (
                InstrumentType.STOCK
                if call["endpoint"] == "daily"
                else InstrumentType.ETF
            )
            columns = call["frame"]["columns"]
            if len(columns) != len(set(columns)):
                raise ValueError
            for values in call["frame"]["data"]:
                raw = dict(zip(columns, values, strict=True))
                code = (
                    raw["ts_code"]
                    if capture.payload_format == "tushare.pro.market_daily.dataframe.v2"
                    else call["ts_code"]
                )
                key = (
                    str(code).split(".")[0],
                    kind,
                    str(raw["trade_date"]).replace("-", ""),
                )
                if key not in wanted:
                    continue
                amount = Decimal(str(raw["amount"]))
                if (
                    not amount.is_finite()
                    or amount < 0
                    or amount * 100000 % 1 != 0
                    or key in actual
                ):
                    raise ValueError
                actual[key] = amount * 1000
        if actual != wanted:
            raise ValueError
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise ValueError(
            "market_reconciliation_source_precision_evidence_invalid"
        ) from exc


def _bse_instrument(instrument: InstrumentKey) -> bool:
    return (
        instrument.instrument_type is InstrumentType.STOCK
        and instrument.symbol.startswith(("4", "8", "92"))
    )


def _validate_eastmoney_bse_precision(
    store,
    materialization,
    bars,
    *,
    primary_provider,
    comparison_provider,
    precision_policy,
):
    if {primary_provider, comparison_provider} != {"akshare", "tushare"}:
        raise ValueError("market_reconciliation_source_precision_pair_invalid")
    capture = read_provider_capture(store, materialization.capture_ref)
    try:
        payload = json.loads(read_provider_raw_payload(store, capture))
        if (
            capture.provider != "akshare"
            or capture.adapter_version != "karkinos.akshare.daily_bar.v2"
            or capture.payload_format != "akshare.eastmoney.daily_bar.dataframe.v2"
            or payload["schema"] != capture.payload_format
            or payload["sdk_version"] != "1.18.97"
        ):
            raise ValueError
        actual = {}
        for call in payload["calls"]:
            symbol = call["symbol"]
            if not symbol.startswith(("4", "8", "92")):
                continue
            if (
                call["endpoint"] != "stock_zh_a_hist"
                or call["request"]["adjust"] != ""
                or call["request"]["symbol"] != symbol
                or call["volume_precision"] != precision_policy
            ):
                raise ValueError
            columns = call["frame"]["columns"]
            if len(columns) != len(set(columns)):
                raise ValueError
            for values in call["frame"]["data"]:
                row = dict(zip(columns, values, strict=True))
                volume = Decimal(str(row["成交量"]))
                if not volume.is_finite() or volume < 0 or volume % 1:
                    raise ValueError
                key = (symbol, str(row["日期"])[:10])
                if key in actual:
                    raise ValueError
                actual[key] = volume * 100
        if any(
            _bse_instrument(bar.instrument)
            and actual.get((bar.instrument.symbol, bar.session_date.isoformat()))
            != bar.volume
            for bar in bars
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise ValueError(
            "market_reconciliation_source_precision_evidence_invalid"
        ) from exc


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
        tolerance=policy.volume_tolerance
        if policy.source_precision_policy is None or _bse_instrument(primary.instrument)
        else Decimal(0),
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
