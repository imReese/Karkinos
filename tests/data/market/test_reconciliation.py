"""Market Data 跨 Provider 对账测试。"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.capture import capture_provider_payload
from data.market.normalize import normalize_daily_bar
from data.market.quality import (
    MarketQualityDiagnosticKind,
    MarketQualitySeverity,
)
from data.market.reconciliation import (
    BAOSTOCK_TENCENT_DAILY_RECONCILIATION_V1,
    DailyBarReconciliationPolicy,
    ReconciliationDifferenceKind,
    reconcile_daily_bar_revisions,
    reconcile_daily_bars,
)
from data.market.revision import (
    publish_daily_bar_revision,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
)
from data.storage.parquet import (
    ParquetIntegrityError,
)

_SESSION_DATE = date(2026, 9, 15)

_EVENT_TIME = datetime(
    2026,
    9,
    15,
    7,
    0,
    tzinfo=timezone.utc,
)

_AVAILABLE_AT = datetime(
    2026,
    9,
    15,
    7,
    1,
    tzinfo=timezone.utc,
)

_CAPTURED_AT = datetime(
    2026,
    9,
    15,
    7,
    3,
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


def _bar(
    symbol: str,
    *,
    instrument_type: InstrumentType = InstrumentType.STOCK,
    event_time: datetime = _EVENT_TIME,
    close: str = "10.48",
    volume: str = "123456",
    amount: str = "1283912.42",
    suspended: bool = False,
    captured_at: datetime = _CAPTURED_AT,
):
    if symbol == "000001":
        open_value = "12.10"
        high_value = "12.50"
        low_value = "12.00"

        if close == "10.48":
            close = "12.34"
    else:
        open_value = "10.31"
        high_value = "10.52"
        low_value = "10.20"

    return normalize_daily_bar(
        instrument=_instrument(
            symbol,
            instrument_type,
        ),
        session_date=_SESSION_DATE,
        event_time=event_time,
        available_at=_AVAILABLE_AT,
        captured_at=captured_at,
        open_value=open_value,
        high_value=high_value,
        low_value=low_value,
        close_value=close,
        volume=volume,
        amount=amount,
        suspended=suspended,
    )


def _bars():
    return (
        _bar("000001"),
        _bar("600000"),
    )


def _capture(
    store: ContentAddressedObjectStore,
    *,
    provider: str,
    raw_payload: bytes,
    completed_at: datetime = _CAPTURED_AT,
):
    return capture_provider_payload(
        store,
        provider=provider,
        operation="daily_bars",
        request={
            "kind": "daily_bars",
            "frequency": "1d",
            "start_date": "2026-09-15",
            "end_date": "2026-09-15",
            "instruments": [
                {
                    "symbol": "000001",
                    "instrument_type": "stock",
                },
                {
                    "symbol": "600000",
                    "instrument_type": "stock",
                },
            ],
        },
        raw_payload=raw_payload,
        payload_format=f"{provider}.daily_bars.v1",
        adapter_version=f"karkinos.{provider}.v1",
        started_at=(completed_at - timedelta(milliseconds=500)),
        completed_at=completed_at,
        record_count=2,
    )


def _revision(
    store: ContentAddressedObjectStore,
    *,
    provider: str,
    bars,
    raw_payload: bytes,
):
    capture = _capture(
        store,
        provider=provider,
        raw_payload=raw_payload,
    )

    return publish_daily_bar_revision(
        store,
        capture=capture,
        bars=bars,
        normalizer_version="karkinos.market.normalize.v1",
    )


def _object_path(
    store: ContentAddressedObjectStore,
    object_id: str,
) -> Path:
    digest = object_id.removeprefix("sha256:")

    return store.root / "sha256" / digest[:2] / digest[2:]


def test_identical_daily_bars_match() -> None:
    report = reconcile_daily_bars(
        _bars(),
        _bars(),
        primary_revision_id="revision-tdx",
        comparison_revision_id="revision-tushare",
        primary_provider="tdx",
        comparison_provider="tushare",
    )

    assert report.matched is True
    assert report.difference_count == 0
    assert report.differences == ()

    assert report.primary_instrument_count == 2
    assert report.comparison_instrument_count == 2
    assert report.matched_instrument_count == 2


def test_price_difference_is_reported() -> None:
    primary = (
        _bar(
            "600000",
            close="10.48",
        ),
    )

    comparison = (
        _bar(
            "600000",
            close="10.49",
        ),
    )

    report = reconcile_daily_bars(
        primary,
        comparison,
        primary_revision_id="revision-tdx",
        comparison_revision_id="revision-tushare",
        primary_provider="tdx",
        comparison_provider="tushare",
    )

    assert report.matched is False
    assert report.difference_count == 1
    assert report.matched_instrument_count == 0

    difference = report.differences[0]

    assert difference.kind is ReconciliationDifferenceKind.VALUE_DIFFERENCE
    assert difference.instrument == _instrument("600000")
    assert difference.field == "close"
    assert difference.primary_value == "10.48"
    assert difference.comparison_value == "10.49"
    assert difference.absolute_difference == Decimal("0.01")


def test_explicit_tolerance_can_suppress_small_difference() -> None:
    policy = DailyBarReconciliationPolicy(
        price_tolerance=Decimal("0.01"),
        volume_tolerance=Decimal("0"),
        amount_tolerance=Decimal("0"),
    )

    report = reconcile_daily_bars(
        (
            _bar(
                "600000",
                close="10.48",
            ),
        ),
        (
            _bar(
                "600000",
                close="10.49",
            ),
        ),
        primary_revision_id="revision-tdx",
        comparison_revision_id="revision-tushare",
        primary_provider="tdx",
        comparison_provider="tushare",
        policy=policy,
    )

    assert report.matched is True
    assert report.differences == ()


def test_difference_above_tolerance_is_reported() -> None:
    policy = DailyBarReconciliationPolicy(
        price_tolerance=Decimal("0.01"),
    )

    report = reconcile_daily_bars(
        (
            _bar(
                "600000",
                close="10.48",
            ),
        ),
        (
            _bar(
                "600000",
                close="10.50",
            ),
        ),
        primary_revision_id="revision-tdx",
        comparison_revision_id="revision-tushare",
        primary_provider="tdx",
        comparison_provider="tushare",
        policy=policy,
    )

    assert report.difference_count == 1
    assert report.differences[0].absolute_difference == Decimal("0.02")


def test_missing_comparison_instrument_is_reported() -> None:
    report = reconcile_daily_bars(
        (
            _bar("000001"),
            _bar("600000"),
        ),
        (_bar("600000"),),
        primary_revision_id="revision-tdx",
        comparison_revision_id="revision-tushare",
        primary_provider="tdx",
        comparison_provider="tushare",
    )

    assert report.difference_count == 1

    difference = report.differences[0]

    assert difference.kind is ReconciliationDifferenceKind.MISSING_COMPARISON
    assert difference.instrument == _instrument("000001")


def test_missing_primary_instrument_is_reported() -> None:
    report = reconcile_daily_bars(
        (_bar("600000"),),
        (
            _bar("000001"),
            _bar("600000"),
        ),
        primary_revision_id="revision-tdx",
        comparison_revision_id="revision-tushare",
        primary_provider="tdx",
        comparison_provider="tushare",
    )

    assert report.difference_count == 1

    assert report.differences[0].kind is ReconciliationDifferenceKind.MISSING_PRIMARY
    assert report.differences[0].instrument == _instrument("000001")


def test_event_time_difference_is_reported() -> None:
    comparison_event_time = _EVENT_TIME + timedelta(seconds=1)

    report = reconcile_daily_bars(
        (_bar("600000"),),
        (
            _bar(
                "600000",
                event_time=comparison_event_time,
            ),
        ),
        primary_revision_id="revision-tdx",
        comparison_revision_id="revision-tushare",
        primary_provider="tdx",
        comparison_provider="tushare",
    )

    assert report.difference_count == 1

    difference = report.differences[0]

    assert difference.kind is ReconciliationDifferenceKind.EVENT_TIME_DIFFERENCE
    assert difference.field == "event_time"


def test_suspension_difference_is_reported() -> None:
    primary = _bar(
        "600000",
        volume="0",
        amount="0",
        suspended=True,
    )

    comparison = _bar(
        "600000",
        volume="0",
        amount="0",
        suspended=False,
    )

    report = reconcile_daily_bars(
        (primary,),
        (comparison,),
        primary_revision_id="revision-tdx",
        comparison_revision_id="revision-tushare",
        primary_provider="tdx",
        comparison_provider="tushare",
    )

    assert report.difference_count == 1

    assert (
        report.differences[0].kind is ReconciliationDifferenceKind.SUSPENSION_DIFFERENCE
    )


def test_volume_tolerance_is_independent_from_price_tolerance() -> None:
    policy = DailyBarReconciliationPolicy(
        price_tolerance=Decimal("0"),
        volume_tolerance=Decimal("1"),
        amount_tolerance=Decimal("0"),
    )

    report = reconcile_daily_bars(
        (
            _bar(
                "600000",
                volume="100",
            ),
        ),
        (
            _bar(
                "600000",
                volume="101",
            ),
        ),
        primary_revision_id="revision-tdx",
        comparison_revision_id="revision-tushare",
        primary_provider="tdx",
        comparison_provider="tushare",
        policy=policy,
    )

    assert report.matched is True


def test_amount_difference_uses_amount_tolerance() -> None:
    policy = DailyBarReconciliationPolicy(
        amount_tolerance=Decimal("0.10"),
    )

    report = reconcile_daily_bars(
        (
            _bar(
                "600000",
                amount="1000.00",
            ),
        ),
        (
            _bar(
                "600000",
                amount="1000.11",
            ),
        ),
        primary_revision_id="revision-tdx",
        comparison_revision_id="revision-tushare",
        primary_provider="tdx",
        comparison_provider="tushare",
        policy=policy,
    )

    assert report.difference_count == 1
    assert report.differences[0].field == "amount"


def test_same_symbol_different_instrument_type_is_distinct() -> None:
    stock = _bar(
        "510300",
        instrument_type=InstrumentType.STOCK,
    )

    etf = _bar(
        "510300",
        instrument_type=InstrumentType.ETF,
    )

    report = reconcile_daily_bars(
        (stock,),
        (etf,),
        primary_revision_id="revision-tdx",
        comparison_revision_id="revision-tushare",
        primary_provider="tdx",
        comparison_provider="tushare",
    )

    assert report.difference_count == 2

    assert {difference.kind for difference in report.differences} == {
        ReconciliationDifferenceKind.MISSING_PRIMARY,
        ReconciliationDifferenceKind.MISSING_COMPARISON,
    }


def test_difference_order_is_deterministic() -> None:
    primary = (
        _bar(
            "600000",
            close="10.48",
        ),
        _bar(
            "000001",
            close="12.34",
        ),
    )

    comparison = (
        _bar(
            "000001",
            close="12.35",
        ),
        _bar(
            "600000",
            close="10.49",
        ),
    )

    forward = reconcile_daily_bars(
        primary,
        comparison,
        primary_revision_id="revision-tdx",
        comparison_revision_id="revision-tushare",
        primary_provider="tdx",
        comparison_provider="tushare",
    )

    reverse = reconcile_daily_bars(
        tuple(reversed(primary)),
        tuple(reversed(comparison)),
        primary_revision_id="revision-tdx",
        comparison_revision_id="revision-tushare",
        primary_provider="tdx",
        comparison_provider="tushare",
    )

    assert forward.differences == reverse.differences


def test_duplicate_instrument_is_rejected() -> None:
    bar = _bar("600000")

    with pytest.raises(
        ValueError,
        match="market_reconciliation_duplicate_instrument",
    ):
        reconcile_daily_bars(
            (
                bar,
                bar,
            ),
            (bar,),
            primary_revision_id="revision-tdx",
            comparison_revision_id="revision-tushare",
            primary_provider="tdx",
            comparison_provider="tushare",
        )


def test_report_can_be_converted_to_warning_quality_diagnostics() -> None:
    report = reconcile_daily_bars(
        (
            _bar(
                "600000",
                close="10.48",
            ),
        ),
        (
            _bar(
                "600000",
                close="10.49",
            ),
        ),
        primary_revision_id="revision-tdx",
        comparison_revision_id="revision-tushare",
        primary_provider="tdx",
        comparison_provider="tushare",
    )

    diagnostics = report.to_quality_diagnostics(
        severity=MarketQualitySeverity.WARNING,
    )

    assert len(diagnostics) == 1

    diagnostic = diagnostics[0]

    assert diagnostic.kind is MarketQualityDiagnosticKind.PROVIDER_DIFFERENCE
    assert diagnostic.severity is MarketQualitySeverity.WARNING
    assert diagnostic.instrument == _instrument("600000")


def test_same_difference_can_be_blocking_for_research() -> None:
    report = reconcile_daily_bars(
        (
            _bar(
                "600000",
                close="10.48",
            ),
        ),
        (
            _bar(
                "600000",
                close="10.49",
            ),
        ),
        primary_revision_id="revision-tdx",
        comparison_revision_id="revision-tushare",
        primary_provider="tdx",
        comparison_provider="tushare",
    )

    diagnostics = report.to_quality_diagnostics(
        severity=MarketQualitySeverity.BLOCKING,
    )

    assert diagnostics[0].severity is MarketQualitySeverity.BLOCKING


def test_revision_level_reconciliation_matches_identical_facts(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    primary_revision, primary_materialization = _revision(
        store,
        provider="tdx",
        bars=_bars(),
        raw_payload=b"tdx-response",
    )

    comparison_revision, comparison_materialization = _revision(
        store,
        provider="tushare",
        bars=_bars(),
        raw_payload=b"tushare-response",
    )

    report = reconcile_daily_bar_revisions(
        store,
        primary_revision=primary_revision,
        primary_materialization=primary_materialization,
        comparison_revision=comparison_revision,
        comparison_materialization=comparison_materialization,
    )

    assert report.matched is True
    assert report.difference_count == 0

    # Provider 不同，因此 Revision identity 不同；
    # 但 canonical 市场事实可以完全一致。
    assert primary_revision.ref != comparison_revision.ref
    assert (
        primary_revision.content_fingerprint == comparison_revision.content_fingerprint
    )


def test_revision_level_reconciliation_detects_provider_difference(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    primary_revision, primary_materialization = _revision(
        store,
        provider="tdx",
        bars=(
            _bar("000001"),
            _bar(
                "600000",
                close="10.48",
            ),
        ),
        raw_payload=b"tdx-response",
    )

    comparison_revision, comparison_materialization = _revision(
        store,
        provider="tushare",
        bars=(
            _bar("000001"),
            _bar(
                "600000",
                close="10.49",
            ),
        ),
        raw_payload=b"tushare-response",
    )

    report = reconcile_daily_bar_revisions(
        store,
        primary_revision=primary_revision,
        primary_materialization=primary_materialization,
        comparison_revision=comparison_revision,
        comparison_materialization=comparison_materialization,
    )

    assert report.matched is False
    assert report.difference_count == 1

    difference = report.differences[0]

    assert difference.field == "close"
    assert difference.instrument == _instrument("600000")


def test_revision_reconciliation_rejects_same_provider(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    first_revision, first_materialization = _revision(
        store,
        provider="tdx",
        bars=_bars(),
        raw_payload=b"tdx-response-1",
    )

    second_revision, second_materialization = _revision(
        store,
        provider="tdx",
        bars=_bars(),
        raw_payload=b"tdx-response-2",
    )

    with pytest.raises(
        ValueError,
        match="market_reconciliation_same_provider",
    ):
        reconcile_daily_bar_revisions(
            store,
            primary_revision=first_revision,
            primary_materialization=first_materialization,
            comparison_revision=second_revision,
            comparison_materialization=second_materialization,
        )


def test_revision_reconciliation_rejects_different_partition(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    primary_revision, primary_materialization = _revision(
        store,
        provider="tdx",
        bars=_bars(),
        raw_payload=b"tdx-response",
    )

    next_day = date(2026, 9, 16)
    next_event = datetime(
        2026,
        9,
        16,
        7,
        0,
        tzinfo=timezone.utc,
    )
    next_available = datetime(
        2026,
        9,
        16,
        7,
        1,
        tzinfo=timezone.utc,
    )
    next_captured = datetime(
        2026,
        9,
        16,
        7,
        3,
        tzinfo=timezone.utc,
    )

    next_capture = _capture(
        store,
        provider="tushare",
        raw_payload=b"tushare-next-day",
        completed_at=next_captured,
    )

    next_bar = normalize_daily_bar(
        instrument=_instrument("600000"),
        session_date=next_day,
        event_time=next_event,
        available_at=next_available,
        captured_at=next_captured,
        open_value="10.31",
        high_value="10.52",
        low_value="10.20",
        close_value="10.48",
        volume="123456",
        amount="1283912.42",
        suspended=False,
    )

    comparison_revision, comparison_materialization = publish_daily_bar_revision(
        store,
        capture=next_capture,
        bars=(next_bar,),
        normalizer_version="karkinos.market.normalize.v1",
    )

    with pytest.raises(
        ValueError,
        match="market_reconciliation_partition_mismatch",
    ):
        reconcile_daily_bar_revisions(
            store,
            primary_revision=primary_revision,
            primary_materialization=primary_materialization,
            comparison_revision=comparison_revision,
            comparison_materialization=comparison_materialization,
        )


def test_corrupted_materialization_cannot_be_reconciled(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    primary_revision, primary_materialization = _revision(
        store,
        provider="tdx",
        bars=_bars(),
        raw_payload=b"tdx-response",
    )

    comparison_revision, comparison_materialization = _revision(
        store,
        provider="tushare",
        bars=_bars(),
        raw_payload=b"tushare-response",
    )

    path = _object_path(
        store,
        comparison_materialization.artifact.object_ref.object_id,
    )

    # 主动绕过只读权限，模拟物理对象损坏。
    os.chmod(
        path,
        0o644,
    )
    path.write_bytes(b"corrupted parquet")

    with pytest.raises(
        ParquetIntegrityError,
        match="parquet_object_integrity_failed",
    ):
        reconcile_daily_bar_revisions(
            store,
            primary_revision=primary_revision,
            primary_materialization=primary_materialization,
            comparison_revision=comparison_revision,
            comparison_materialization=comparison_materialization,
        )


def test_baostock_tencent_policy_only_tolerates_reviewed_source_precision() -> None:
    within = reconcile_daily_bars(
        (
            _bar(
                "600000",
                volume="45671103",
                amount="414887057.39",
            ),
        ),
        (
            _bar(
                "600000",
                volume="45671100",
                amount="414887100",
            ),
        ),
        primary_revision_id="revision-baostock",
        comparison_revision_id="revision-tencent",
        primary_provider="baostock",
        comparison_provider="akshare_tencent",
        policy=BAOSTOCK_TENCENT_DAILY_RECONCILIATION_V1,
    )
    assert within.matched is True

    volume_outside = reconcile_daily_bars(
        (_bar("600000", volume="45671103", amount="414887057.39"),),
        (_bar("600000", volume="45671203", amount="414887057.39"),),
        primary_revision_id="revision-baostock",
        comparison_revision_id="revision-tencent",
        primary_provider="baostock",
        comparison_provider="akshare_tencent",
        policy=BAOSTOCK_TENCENT_DAILY_RECONCILIATION_V1,
    )
    assert volume_outside.matched is False
    assert volume_outside.differences[0].field == "volume"

    amount_outside = reconcile_daily_bars(
        (_bar("600000", volume="45671103", amount="414887057.39"),),
        (_bar("600000", volume="45671103", amount="414887157.39"),),
        primary_revision_id="revision-baostock",
        comparison_revision_id="revision-tencent",
        primary_provider="baostock",
        comparison_provider="akshare_tencent",
        policy=BAOSTOCK_TENCENT_DAILY_RECONCILIATION_V1,
    )
    assert amount_outside.matched is False
    assert amount_outside.differences[0].field == "amount"
