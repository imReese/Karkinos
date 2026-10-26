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
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from types import MappingProxyType

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
                "karkinos.tencent_sina.direct_reported_amount_compatibility.v1": (
                    Decimal(0),
                    Decimal(0),
                    Decimal(0),
                ),
                "karkinos.tencent_tushare.reported_amount_resolution.v1": (
                    Decimal(0),
                    Decimal(0),
                    Decimal("99.99"),
                ),
                "karkinos.tencent_tushare.reported_volume_amount_resolution.v2": (
                    Decimal(0),
                    Decimal(0),
                    Decimal("99.99"),
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

BSE_AUCTION_RELATION_KIND = "karkinos.bse.sina.auction_reported_components.v1"


@dataclass(frozen=True, slots=True)
class BseAuctionRelation:
    """Explicit reported-basis relation, never a residual or provider bar.

    Empty component refs compare equal-volume native bars at Sina's actual
    encoded amount quantum. They make no statement about absent block trades.
    Nonempty refs must bind all fixed-date pages and actual old/new code HTML.
    """

    block_page_capture_ids: tuple[str, ...] = ()
    mapping_capture_id: str | None = None

    def __post_init__(self) -> None:
        ids = self.block_page_capture_ids
        if not isinstance(ids, tuple) or not 0 <= len(ids) <= 10:
            raise ValueError("bse_auction_component_refs_invalid")
        if len(set(ids)) != len(ids) or any(
            not isinstance(item, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", item) is None
            for item in ids
        ):
            raise ValueError("bse_auction_component_refs_invalid")
        if bool(ids) != (self.mapping_capture_id is not None) or (
            self.mapping_capture_id is not None
            and re.fullmatch(r"sha256:[0-9a-f]{64}", self.mapping_capture_id) is None
        ):
            raise ValueError("bse_auction_mapping_ref_invalid")


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


# Agreement within one Tencent reported 100-CNY unit, not exact traded amount
# or a bound on true-value error. Only reviewed SSE/SZSE stock captures qualify:
# both raw responses must reproduce every compared field, Tencent must retain
# its reviewed amount marker/grid, and TuShare must reproduce reported cents.
# Prices, volume, event time and suspension stay exact; zero amounts stay exact.
TENCENT_TUSHARE_REPORTED_AMOUNT_RECONCILIATION_V1 = DailyBarReconciliationPolicy(
    amount_tolerance=Decimal("99.99"),
    source_precision_policy="karkinos.tencent_tushare.reported_amount_resolution.v1",
)

# Explicit per-row reported compatibility, not a provider-wide rounding law or
# a bound on true volume. Exact volume remains accepted, including actual
# non-100-share values. A differing positive integer Tencent volume must equal
# one HALF_UP projection of TuShare's positive integer shares to 100 shares.
# Every compared field still replays both native sources; the finer original
# bars and their deltas remain evidence. Numeric volume tolerance stays zero.
TENCENT_TUSHARE_REPORTED_VOLUME_AMOUNT_RECONCILIATION_V2 = DailyBarReconciliationPolicy(
    amount_tolerance=Decimal("99.99"),
    source_precision_policy=(
        "karkinos.tencent_tushare.reported_volume_amount_resolution.v2"
    ),
)


# Exact native OHLCV plus one direct Sina->Tencent reported amount projection.
# This is an explicit per-row compatibility criterion, not a global source law.
# Numeric tolerances remain zero; raw original values are never rewritten.
TENCENT_SINA_REPORTED_AMOUNT_RECONCILIATION_V1 = DailyBarReconciliationPolicy(
    source_precision_policy="karkinos.tencent_sina.direct_reported_amount_compatibility.v1",
)


BSE_TENCENT_REPORTED_RELATION_KIND = (
    "karkinos.bse.official_primary.tencent_reported_value_compatibility.v1"
)
BSE_TENCENT_AMOUNT_COMPARISON = "Tencent_amount_equals_official_HALF_UP_100CNY"


@dataclass(frozen=True, slots=True)
class BseTencentReportedRelation:
    """Per-row compatibility; primary is the unchanged finer official bar.

    This explicitly admits reported-value compatibility, not raw six-field
    equality or a provider-wide precision/error guarantee. Amounts are copied
    audit values and are checked against both native bars on every replay.
    """

    block_page_capture_ids: tuple[str, ...]
    mapping_capture_id: str
    official_amount: Decimal
    tencent_amount: Decimal

    def __post_init__(self) -> None:
        from data.providers.bse_sina_history import number

        BseAuctionRelation(self.block_page_capture_ids, self.mapping_capture_id)
        if not self.block_page_capture_ids:
            raise ValueError("bse_tencent_complete_component_pages_required")
        for value in (self.official_amount, self.tencent_amount):
            if not isinstance(value, Decimal) or number(value, "amount") <= 0:
                raise ValueError("bse_tencent_actual_positive_amount_required")


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
    component_relation: BseAuctionRelation | BseTencentReportedRelation | None = None,
    component_checked_at: datetime | None = None,
) -> MarketReconciliationReport:
    """完整验证两份 lineage 并返回稳定的跨 Provider 对账报告。"""
    report, _, _ = reconcile_daily_bar_revisions_with_bars(
        store,
        primary_revision=primary_revision,
        primary_materialization=primary_materialization,
        comparison_revision=comparison_revision,
        comparison_materialization=comparison_materialization,
        policy=policy,
        component_relation=component_relation,
        component_checked_at=component_checked_at,
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
    component_relation: BseAuctionRelation | BseTencentReportedRelation | None = None,
    component_checked_at: datetime | None = None,
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
    if component_relation is not None:
        return (
            (
                _reconcile_bse_tencent_reported
                if isinstance(component_relation, BseTencentReportedRelation)
                else _reconcile_bse_auction
            )(
                store,
                primary_revision=primary_revision,
                primary_materialization=primary_materialization,
                comparison_revision=comparison_revision,
                comparison_materialization=comparison_materialization,
                primary_bars=primary_bars,
                comparison_bars=comparison_bars,
                policy=policy,
                relation=component_relation,
                checked_at=component_checked_at,
            ),
            primary_bars,
            comparison_bars,
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

    elif (
        policy.source_precision_policy
        == "karkinos.tencent_sina.direct_reported_amount_compatibility.v1"
    ):
        if {primary_revision.provider, comparison_revision.provider} != {
            "akshare_tencent",
            "sina_native_public_probe",
        }:
            raise ValueError("market_reconciliation_source_precision_pair_invalid")
        for revision, materialization, bars in (
            (primary_revision, primary_materialization, primary_bars),
            (comparison_revision, comparison_materialization, comparison_bars),
        ):
            if revision.provider == "akshare_tencent":
                _validate_tencent_tushare_reported_amount(store, materialization, bars)
            else:
                _validate_sina_reported_amount(store, materialization, bars)

    elif policy.source_precision_policy in {
        "karkinos.tencent_tushare.reported_amount_resolution.v1",
        "karkinos.tencent_tushare.reported_volume_amount_resolution.v2",
    }:
        if {primary_revision.provider, comparison_revision.provider} != {
            "akshare_tencent",
            "tushare",
        }:
            raise ValueError("market_reconciliation_source_precision_pair_invalid")
        for materialization, bars in (
            (primary_materialization, primary_bars),
            (comparison_materialization, comparison_bars),
        ):
            _validate_tencent_tushare_reported_amount(store, materialization, bars)

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


def _reconcile_bse_auction(
    store,
    *,
    primary_revision,
    primary_materialization,
    comparison_revision,
    comparison_materialization,
    primary_bars,
    comparison_bars,
    policy,
    relation,
    checked_at,
):
    """Replay both original bars and published components, without rewriting."""
    from data.providers.bse_sina_history import (
        canonical_rows,
        exact_bse_arithmetic,
        read_block_components,
        read_official,
        read_sina_rows,
        require_capture_before,
    )

    if (
        not isinstance(relation, BseAuctionRelation)
        or policy != STRICT_DAILY_RECONCILIATION
        or primary_revision.provider != "sina_native_public_probe"
        or comparison_revision.provider != "bse_official_kline_probe"
        or len(primary_bars) != 1
        or len(comparison_bars) != 1
    ):
        raise ValueError("bse_auction_native_pair_required")
    sina, official = primary_bars[0], comparison_bars[0]
    identity_fields = ("instrument", "session_date", "event_time", "suspended")
    if any(getattr(sina, k) != getattr(official, k) for k in identity_fields):
        raise ValueError("bse_auction_exact_identity_required")
    if sina.suspended or any(
        getattr(sina, k) != getattr(official, k)
        for k in ("open", "high", "low", "close")
    ):
        raise ValueError("bse_auction_exact_auction_prices_required")
    day, key = sina.session_date, sina.instrument
    official_cap, native_official, _, _ = read_official(
        store, comparison_materialization.capture_ref.object_id, key, session_date=day
    )
    sina_cap, sina_rows, precision, _ = read_sina_rows(
        store, primary_materialization.capture_ref.object_id, key, session_date=day
    )
    require_capture_before(official_cap, checked_at)
    require_capture_before(sina_cap, checked_at)
    if day not in sina_rows or day not in native_official:
        raise ValueError("bse_auction_original_native_row_missing")
    native_sina, _ = canonical_rows(sina_cap, key, {day: sina_rows[day]})
    if native_sina.get(day) != sina or native_official[day] != official:
        raise ValueError("bse_auction_original_materialization_mismatch")
    quantity = notional = Decimal(0)
    if relation.block_page_capture_ids:
        quantity, notional = read_block_components(
            store,
            relation.block_page_capture_ids,
            relation.mapping_capture_id,
            key,
            day,
            checked_at,
        )
    quantum = precision[day]["amount_quantum_CNY"]
    with exact_bse_arithmetic():
        if official.volume - sina.volume != quantity:
            raise ValueError("bse_auction_exact_quantity_relation_required")
        residual = official.amount - notional
        if (
            residual < 0
            or sina.amount <= 0
            or sina.volume <= 0
            or precision[day]["amount_phase_CNY"] != 0
        ):
            raise ValueError("bse_auction_actual_reported_quantization_required")
        # This is the sole intentionally rounded operation. Division and the
        # final multiplication remain exact under the local Inexact trap.
        reported = (residual / quantum).to_integral_value(
            rounding=ROUND_HALF_UP
        ) * quantum
        if reported != sina.amount:
            raise ValueError("bse_auction_actual_reported_quantization_required")
    return MarketReconciliationReport(
        primary_revision_id=primary_revision.ref.revision_id,
        comparison_revision_id=comparison_revision.ref.revision_id,
        primary_provider=primary_revision.provider,
        comparison_provider=comparison_revision.provider,
        matched_instrument_count=1,
        primary_instrument_count=1,
        comparison_instrument_count=1,
        differences=(),
    )


def _reconcile_bse_tencent_reported(
    store,
    *,
    primary_revision,
    primary_materialization,
    comparison_revision,
    comparison_materialization,
    primary_bars,
    comparison_bars,
    policy,
    relation,
    checked_at,
):
    """Exact native OHLCV plus one explicit reported-value projection.

    Only this tagged relation admits the amount representation comparison.
    No bar is synthesized, adjusted, or replaced, and no default tolerance is
    changed. Published complete no-component pages retain the auction basis.
    """
    from data.providers.bse_sina_history import (
        canonical_rows,
        exact_bse_arithmetic,
        read_official,
        read_tencent_rows,
        require_capture_before,
        require_no_reported_block_components,
    )

    if (
        type(relation) is not BseTencentReportedRelation
        or policy != STRICT_DAILY_RECONCILIATION
        or primary_revision.provider != "bse_official_kline_probe"
        or comparison_revision.provider != "tencent_native_public_probe"
        or len(primary_bars) != 1
        or len(comparison_bars) != 1
    ):
        raise ValueError("bse_tencent_official_primary_native_pair_required")
    official, tencent = primary_bars[0], comparison_bars[0]
    if (
        any(
            getattr(official, field) != getattr(tencent, field)
            for field in (
                "instrument",
                "session_date",
                "event_time",
                "suspended",
                "open",
                "high",
                "low",
                "close",
                "volume",
            )
        )
        or official.suspended
        or official.volume <= 0
    ):
        raise ValueError("bse_tencent_exact_identity_prices_volume_required")
    key, day = official.instrument, official.session_date
    official_cap, native_official, _, _ = read_official(
        store, primary_materialization.capture_ref.object_id, key, session_date=day
    )
    tencent_cap, native_rows = read_tencent_rows(
        store,
        comparison_materialization.capture_ref.object_id,
        key,
        relation.mapping_capture_id,
        session_date=day,
    )
    require_capture_before(official_cap, checked_at)
    require_capture_before(tencent_cap, checked_at)
    native_tencent, _ = canonical_rows(tencent_cap, key, native_rows)
    if native_official.get(day) != official or native_tencent.get(day) != tencent:
        raise ValueError("bse_tencent_original_materialization_mismatch")
    if (
        official.amount != relation.official_amount
        or tencent.amount != relation.tencent_amount
    ):
        raise ValueError("bse_tencent_actual_amount_metadata_mismatch")
    with exact_bse_arithmetic():
        # Fixed representational grid, never caller-controlled or a true error
        # bound. This is the sole intentionally rounded operation; there is no
        # preliminary 1-CNY rounding, tolerance, or fallback.
        reported = (official.amount / Decimal(100)).to_integral_value(
            rounding=ROUND_HALF_UP
        ) * Decimal(100)
        if reported != tencent.amount:
            raise ValueError("bse_tencent_direct_reported_value_projection_required")
        if (
            not official.low * official.volume
            <= official.amount
            <= official.high * official.volume
        ):
            raise ValueError("bse_tencent_official_auction_notional_sanity_required")
    require_no_reported_block_components(
        store,
        relation.block_page_capture_ids,
        relation.mapping_capture_id,
        key,
        day,
        checked_at,
    )
    return MarketReconciliationReport(
        primary_revision_id=primary_revision.ref.revision_id,
        comparison_revision_id=comparison_revision.ref.revision_id,
        primary_provider=primary_revision.provider,
        comparison_provider=comparison_revision.provider,
        matched_instrument_count=1,
        primary_instrument_count=1,
        comparison_instrument_count=1,
        differences=(),
    )


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

    elif (
        policy.source_precision_policy
        == "karkinos.tencent_sina.direct_reported_amount_compatibility.v1"
    ):
        from data.providers.bse_sina_history import _sina_a_share_symbol

        if {primary_provider, comparison_provider} != {
            "akshare_tencent",
            "sina_native_public_probe",
        }:
            raise ValueError("market_reconciliation_source_precision_pair_invalid")
        for provider, rows in (
            (primary_provider, primary),
            (comparison_provider, comparison),
        ):
            for bar in rows.values():
                _sina_a_share_symbol(bar.instrument)
                if (
                    bar.amount <= 0
                    or bar.volume <= 0
                    or bar.suspended
                    or bar.amount
                    % (100 if provider == "akshare_tencent" else Decimal("0.01"))
                ):
                    raise ValueError(
                        "market_reconciliation_source_precision_evidence_invalid"
                    )

    elif policy.source_precision_policy in {
        "karkinos.tencent_tushare.reported_amount_resolution.v1",
        "karkinos.tencent_tushare.reported_volume_amount_resolution.v2",
    }:
        if {primary_provider, comparison_provider} != {"akshare_tencent", "tushare"}:
            raise ValueError("market_reconciliation_source_precision_pair_invalid")
        for provider, rows in (
            (primary_provider, primary),
            (comparison_provider, comparison),
        ):
            if any(
                key.instrument_type is not InstrumentType.STOCK
                or _bse_instrument(key)
                or bar.amount
                % (100 if provider == "akshare_tencent" else Decimal("0.01"))
                for key, bar in rows.items()
            ):
                raise ValueError(
                    "market_reconciliation_source_precision_evidence_invalid"
                )
        if policy.source_precision_policy == (
            "karkinos.tencent_tushare.reported_volume_amount_resolution.v2"
        ):
            from data.providers.tushare import (
                TushareDailyBarRequestError,
                _request_target,
            )

            try:
                if any(
                    not _request_target(key)[1].endswith((".SH", ".SZ"))
                    for key in primary.keys() | comparison.keys()
                ):
                    raise TushareDailyBarRequestError("unreviewed_stock_venue")
            except TushareDailyBarRequestError as exc:
                raise ValueError(
                    "market_reconciliation_source_precision_evidence_invalid"
                ) from exc

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
                reported_amount_compatible=(
                    policy.source_precision_policy
                    == "karkinos.tencent_sina.direct_reported_amount_compatibility.v1"
                    and _tencent_sina_reported_amount_compatible(
                        primary[instrument].amount
                        if primary_provider == "sina_native_public_probe"
                        else comparison[instrument].amount,
                        primary[instrument].amount
                        if primary_provider == "akshare_tencent"
                        else comparison[instrument].amount,
                    )
                ),
                reported_volume_compatible=(
                    policy.source_precision_policy
                    == "karkinos.tencent_tushare.reported_volume_amount_resolution.v2"
                    and _tencent_tushare_reported_volume_compatible(
                        primary[instrument].volume
                        if primary_provider == "tushare"
                        else comparison[instrument].volume,
                        comparison[instrument].volume
                        if primary_provider == "tushare"
                        else primary[instrument].volume,
                    )
                ),
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


_TENCENT_TUSHARE_NATIVE_INDEXES: ContextVar[dict | None] = ContextVar(
    "tencent_tushare_native_input_indexes", default=None
)


@contextmanager
def tencent_tushare_native_read_scope(*, join_existing=False):
    """Reuse immutable raw indexes within one read, never financial decisions.

    Capture and raw bytes are reopened and hash-verified on every lookup. Only
    complete successful selected-symbol scans enter the call-local index.
    """
    if join_existing and _TENCENT_TUSHARE_NATIVE_INDEXES.get() is not None:
        yield
        return
    indexes = {}
    token = _TENCENT_TUSHARE_NATIVE_INDEXES.set(indexes)
    try:
        yield
    finally:
        indexes.clear()
        _TENCENT_TUSHARE_NATIVE_INDEXES.reset(token)


def _tencent_tushare_native_inputs(payload, capture, start, end):
    """Freeze one raw response; preserve Tu global and Tencent skipped-call rules."""
    is_tencent = capture.provider == "akshare_tencent"
    inputs = {}
    for call in payload["calls"]:
        if is_tencent:
            symbol = str(call["symbol"])[2:]
            # Unselected Tencent calls have no metadata/frame semantics here.
            inputs.setdefault(symbol, []).append(json.dumps(call))
            continue
        if call["endpoint"] != "daily":
            raise ValueError
        if capture.payload_format == "tushare.pro.market_daily.dataframe.v2" and (
            start != end or call["request"] != {"trade_date": start.strftime("%Y%m%d")}
        ):
            raise ValueError
        columns = call["frame"]["columns"]
        if len(columns) != len(set(columns)):
            raise ValueError
        columns_json = json.dumps(columns)
        identity_json = json.dumps(
            {"ts_code": call["ts_code"]} if "ts_code" in call else {}
        )
        for values in call["frame"]["data"]:
            raw = dict(zip(columns, values, strict=True))
            symbol = str(raw["ts_code"]).split(".")[0]
            inputs.setdefault(symbol, []).append(
                (columns_json, json.dumps(values), identity_json)
            )
    return MappingProxyType({symbol: tuple(rows) for symbol, rows in inputs.items()})


def _tencent_tushare_native_index(inputs, capture, instrument, start, end):
    from data.providers import tencent, tushare

    is_tencent = capture.provider == "akshare_tencent"
    symbol = instrument.symbol
    indexed = {}
    for source in inputs.get(symbol, ()):
        if is_tencent:
            call = json.loads(source)
            source_symbol = tencent._provider_symbol(instrument)
            if (
                call["symbol"] != source_symbol
                or call["request"]
                != {
                    "symbol": source_symbol,
                    "start_date": start.strftime("%Y%m%d"),
                    "end_date": end.strftime("%Y%m%d"),
                    "adjust": "",
                }
                or call["amount_normalization"] != tencent._AMOUNT_FLOAT_NORMALIZATION
                or call["volume_scale_to_shares"]
                != str(
                    tencent._sdk_volume_scale(
                        instrument, "1.18.97", adapter_version=capture.adapter_version
                    )
                )
                or (
                    capture.adapter_version
                    in {
                        "karkinos.akshare_tencent.daily_bar.v4",
                        "karkinos.akshare_tencent.daily_bar.v5",
                    }
                    and call["volume_normalization"]
                    != (
                        tencent._VOLUME_FLOAT_NORMALIZATION
                        if tencent._sdk_multiplies_volume(source_symbol)
                        else None
                    )
                )
            ):
                raise ValueError
            columns = call["frame"]["columns"]
            if len(columns) != len(set(columns)):
                raise ValueError
            columns_json = json.dumps(columns)
            rows = (
                (columns_json, json.dumps(values), None)
                for values in call["frame"]["data"]
            )
        else:
            rows = (source,)
        for columns_json, values_json, identity_json in rows:
            raw = dict(
                zip(json.loads(columns_json), json.loads(values_json), strict=True)
            )
            if is_tencent:
                session = tencent._trade_date(raw["date"])
            else:
                expected_code = tushare._request_target(instrument)[1]
                if raw["ts_code"] != expected_code or (
                    capture.payload_format == "tushare.pro.daily_bar.dataframe.v1"
                    and json.loads(identity_json)["ts_code"] != expected_code
                ):
                    raise ValueError
                session = tushare._trade_date(raw["trade_date"])
            indexed.setdefault((symbol, session), []).append(
                (columns_json, values_json)
            )
    return MappingProxyType({key: tuple(rows) for key, rows in indexed.items()})


def _validate_tencent_tushare_reported_amount(store, materialization, bars):
    """Replay selected cells from immutable SDK responses; never infer raw truth."""
    from data.providers import tencent, tushare

    indexes = _TENCENT_TUSHARE_NATIVE_INDEXES.get()
    succeeded = False
    try:
        capture = read_provider_capture(store, materialization.capture_ref)
        raw_payload = read_provider_raw_payload(store, capture)
        cache_key = (
            str(store.root.resolve()),
            capture.capture_id,
            capture.raw_object_ref.object_id,
        )
        cached = indexes.get(cache_key) if indexes is not None else None
        payload = json.loads(raw_payload) if cached is None else cached[0]
        request = json.loads(capture.request_json)
        start = date.fromisoformat(request["start_date"])
        end = date.fromisoformat(request["end_date"])
        requested = {
            (item["symbol"], item["instrument_type"]) for item in request["instruments"]
        }
        wanted = {(bar.instrument.symbol, bar.session_date): bar for bar in bars}
        if (
            not wanted
            or len(wanted) != len(bars)
            or capture.operation != "daily_bars"
            or request["kind"] != "daily_bars"
            or request["frequency"] != "1d"
            or payload["schema"] != capture.payload_format
            or any(
                bar.instrument.instrument_type is not InstrumentType.STOCK
                or _bse_instrument(bar.instrument)
                or (bar.instrument.symbol, "stock") not in requested
                or not start <= bar.session_date <= end
                for bar in bars
            )
        ):
            raise ValueError
        is_tencent = capture.provider == "akshare_tencent"
        if is_tencent:
            formats = {
                "karkinos.akshare_tencent.daily_bar.v3": "akshare.tencent.stock_zh_a_hist_tx.dataframe.v3",
                "karkinos.akshare_tencent.daily_bar.v4": "akshare.tencent.stock_zh_a_hist_tx.dataframe.v4",
                "karkinos.akshare_tencent.daily_bar.v5": "akshare.tencent.stock_zh_a_hist_tx.dataframe.v5",
            }
            if (
                formats.get(capture.adapter_version) != capture.payload_format
                or payload["sdk_version"] != "1.18.97"
            ):
                raise ValueError
        elif (
            capture.provider != "tushare"
            or capture.adapter_version != "karkinos.tushare.daily_bar.v2"
            or capture.payload_format
            not in {
                "tushare.pro.daily_bar.dataframe.v1",
                "tushare.pro.market_daily.dataframe.v2",
            }
        ):
            raise ValueError
        instruments = {bar.instrument.symbol: bar.instrument for bar in bars}
        inputs = (
            _tencent_tushare_native_inputs(payload, capture, start, end)
            if cached is None
            else cached[1]
        )
        prior_indexes = {} if cached is None else cached[2]
        new_indexes = {}
        for symbol, instrument in instruments.items():
            if symbol not in prior_indexes:
                new_indexes[symbol] = _tencent_tushare_native_index(
                    inputs, capture, instrument, start, end
                )
        native_indexes = MappingProxyType(prior_indexes | new_indexes)
        actual = {}
        for key, bar in wanted.items():
            rows = native_indexes[key[0]].get(key, ())
            if len(rows) != 1:
                raise ValueError
            columns, values = (json.loads(value) for value in rows[0])
            instrument = instruments[key[0]]
            session = key[1]
            records = (dict(zip(columns, values, strict=True)),)
            if is_tencent:
                row = tencent._rows_from_records(
                    records,
                    columns=columns,
                    instrument=instrument,
                    expected_session=session,
                    volume_scale=tencent._sdk_volume_scale(
                        instrument, "1.18.97", adapter_version=capture.adapter_version
                    ),
                    sdk_version="1.18.97",
                    adapter_version=capture.adapter_version,
                )[0]
                if row.amount % 100:
                    raise ValueError
            else:
                row = tushare._rows_from_records(
                    records,
                    columns=columns,
                    instrument=instrument,
                    expected_session=session,
                    endpoint="daily",
                )[0]
                if row.amount % Decimal("0.01"):
                    raise ValueError
            bar = wanted[key]
            if (
                any(
                    getattr(row, field + "_value") != getattr(bar, field)
                    for field in ("open", "high", "low", "close")
                )
                or row.volume != bar.volume
                or row.amount != bar.amount
                or row.event_time != bar.event_time
                or row.suspended != bar.suspended
                or bar.available_at != capture.completed_at
                or bar.captured_at != capture.completed_at
            ):
                raise ValueError
            actual[key] = row
        if actual.keys() != wanted.keys():
            raise ValueError
        if indexes is not None and cached is None:
            header = {"schema": payload["schema"]}
            if is_tencent:
                header["sdk_version"] = payload["sdk_version"]
            indexes[cache_key] = (MappingProxyType(header), inputs, native_indexes)
        elif indexes is not None:
            indexes[cache_key] = (cached[0], inputs, native_indexes)
        succeeded = True
    except (
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        ArithmeticError,
        tencent.AkshareTencentDailyBarResponseError,
        tushare.TushareDailyBarResponseError,
    ) as exc:
        raise ValueError(
            "market_reconciliation_source_precision_evidence_invalid"
        ) from exc

    finally:
        if not succeeded and indexes is not None:
            prefix = (str(store.root.resolve()), materialization.capture_ref.object_id)
            for key in tuple(indexes):
                if key[:2] == prefix:
                    del indexes[key]


def _validate_sina_reported_amount(store, materialization, bars):
    """Replay each selected ordinary Sina cell from its original K2 capture."""
    from data.providers.bse_sina_history import canonical_rows, read_sina_a_share_rows

    if not bars or len({(bar.instrument, bar.session_date) for bar in bars}) != len(
        bars
    ):
        raise ValueError("market_reconciliation_sina_native_evidence_invalid")
    for bar in bars:
        cap, raw, precision, _ = read_sina_a_share_rows(
            store,
            materialization.capture_ref.object_id,
            bar.instrument,
            session_date=bar.session_date,
        )
        native, _ = canonical_rows(cap, bar.instrument, raw)
        if (
            native.get(bar.session_date) != bar
            or precision.get(bar.session_date, {}).get("amount_phase_CNY") != 0
            or bar.amount % Decimal("0.01")
        ):
            raise ValueError("market_reconciliation_sina_native_evidence_invalid")


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


def _tencent_sina_reported_amount_compatible(
    sina_amount: Decimal, tencent_amount: Decimal
) -> bool:
    """One exact rational HALF_UP to 100 CNY, without intermediate rounding."""
    for value in (sina_amount, tencent_amount):
        if (
            not isinstance(value, Decimal)
            or not value.is_finite()
            or value <= 0
            or len(value.as_tuple().digits) > 80
            or not isinstance(value.as_tuple().exponent, int)
            or value.as_tuple().exponent < -80
            or value.adjusted() > 79
        ):
            return False
    numerator, denominator = sina_amount.as_integer_ratio()
    tc_numerator, tc_denominator = tencent_amount.as_integer_ratio()
    if 100 % denominator or tc_denominator != 1 or tc_numerator % 100:
        return False
    units, remainder = divmod(numerator, denominator * 100)
    return (units + (2 * remainder >= denominator * 100)) * 100 == tc_numerator


def _tencent_tushare_reported_volume_compatible(
    tushare_volume: Decimal, tencent_volume: Decimal
) -> bool:
    """One exact integer HALF_UP projection, after accepting exact equality.

    Integer divmod avoids ambient Decimal precision and intermediate rounding.
    Differing values outside the bounded 80-digit integer domain fail closed;
    this implementation bound is not a financial error allowance.
    """
    if any(
        not isinstance(value, Decimal) or not value.is_finite()
        for value in (tushare_volume, tencent_volume)
    ):
        return False
    if tushare_volume == tencent_volume:
        return True
    for value in (tushare_volume, tencent_volume):
        parts = value.as_tuple()
        if (
            value <= 0
            or len(parts.digits) > 80
            or not isinstance(parts.exponent, int)
            or parts.exponent < -80
            or value.adjusted() > 79
            or value != value.to_integral_value()
        ):
            return False
    tu, tx = int(tushare_volume), int(tencent_volume)
    if tx % 100:
        return False
    units, remainder = divmod(tu, 100)
    return (units + (remainder >= 50)) * 100 == tx


def _compare_daily_bar(
    primary: DailyBarObservation,
    comparison: DailyBarObservation,
    *,
    policy: DailyBarReconciliationPolicy,
    reported_volume_compatible: bool = False,
    reported_amount_compatible: bool = False,
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

    if difference is not None and not reported_volume_compatible:
        differences.append(difference)

    difference = _compare_decimal_field(
        primary,
        comparison,
        field="amount",
        tolerance=Decimal(0)
        if policy.source_precision_policy
        in {
            "karkinos.tencent_tushare.reported_amount_resolution.v1",
            "karkinos.tencent_tushare.reported_volume_amount_resolution.v2",
        }
        and (primary.amount == 0 or comparison.amount == 0)
        else policy.amount_tolerance,
    )

    if difference is not None and not reported_amount_compatible:
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
