"""Market Data 质量评估测试。"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.capture import capture_provider_payload
from data.market.normalize import normalize_daily_bar
from data.market.quality import (
    RESEARCH_STRICT_DAILY,
    SERVING_RELAXED_DAILY,
    MarketDataQualityReport,
    MarketQualityDiagnostic,
    MarketQualityDiagnosticKind,
    MarketQualitySeverity,
    MarketQualityStatus,
    evaluate_daily_bar_quality,
    evaluate_daily_bar_revision,
    provider_difference_diagnostic,
)
from data.market.revision import (
    publish_daily_bar_revision,
)
from data.storage.objects import ContentAddressedObjectStore

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
    captured_at: datetime = _CAPTURED_AT,
):
    if symbol == "600000":
        open_value = "10.31"
        high_value = "10.52"
        low_value = "10.20"
        close_value = "10.48"
    else:
        open_value = "12.10"
        high_value = "12.50"
        low_value = "12.00"
        close_value = "12.34"

    return normalize_daily_bar(
        instrument=_instrument(
            symbol,
            instrument_type,
        ),
        session_date=_SESSION_DATE,
        event_time=_EVENT_TIME,
        available_at=_AVAILABLE_AT,
        captured_at=captured_at,
        open_value=open_value,
        high_value=high_value,
        low_value=low_value,
        close_value=close_value,
        volume="123456",
        amount="1283912.42",
        suspended=False,
    )


def _bars():
    return (
        _bar("000001"),
        _bar("600000"),
    )


def _expected():
    return (
        _instrument("000001"),
        _instrument("600000"),
    )


def _capture(
    store: ContentAddressedObjectStore,
):
    return capture_provider_payload(
        store,
        provider="tdx",
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
        raw_payload=b"provider-response",
        payload_format="tdx.daily_bars.v1",
        adapter_version="karkinos.tdx.v1",
        started_at=(_CAPTURED_AT - timedelta(milliseconds=500)),
        completed_at=_CAPTURED_AT,
        record_count=2,
    )


def _revision_and_materialization(
    store: ContentAddressedObjectStore,
):
    capture = _capture(store)

    return publish_daily_bar_revision(
        store,
        capture=capture,
        bars=_bars(),
        normalizer_version="karkinos.market.normalize.v1",
    )


def _object_path(
    store: ContentAddressedObjectStore,
    object_id: str,
) -> Path:
    digest = object_id.removeprefix("sha256:")

    return store.root / "sha256" / digest[:2] / digest[2:]


def test_complete_expected_universe_passes_strict_policy() -> None:
    report = evaluate_daily_bar_quality(
        _bars(),
        revision_id="revision-1",
        materialization_id="materialization-1",
        policy=RESEARCH_STRICT_DAILY,
        expected_instruments=_expected(),
        checked_at=_CAPTURED_AT,
    )

    assert report.status is MarketQualityStatus.PASS
    assert report.blocks_publication is False
    assert report.diagnostics == ()
    assert report.observed_instrument_count == 2
    assert report.expected_instrument_count == 2
    assert report.blocking_count == 0
    assert report.warning_count == 0


def test_strict_policy_blocks_without_expected_universe() -> None:
    report = evaluate_daily_bar_quality(
        _bars(),
        revision_id="revision-1",
        materialization_id="materialization-1",
        policy=RESEARCH_STRICT_DAILY,
        expected_instruments=None,
        checked_at=_CAPTURED_AT,
    )

    assert report.status is MarketQualityStatus.BLOCKED
    assert report.blocks_publication is True

    assert len(report.diagnostics) == 1
    assert (
        report.diagnostics[0].kind
        is MarketQualityDiagnosticKind.EXPECTED_UNIVERSE_MISSING
    )
    assert report.diagnostics[0].severity is MarketQualitySeverity.BLOCKING


def test_relaxed_policy_allows_missing_expected_universe() -> None:
    report = evaluate_daily_bar_quality(
        _bars(),
        revision_id="revision-1",
        materialization_id="materialization-1",
        policy=SERVING_RELAXED_DAILY,
        expected_instruments=None,
        checked_at=_CAPTURED_AT,
    )

    assert report.status is MarketQualityStatus.PASS
    assert report.expected_instrument_count is None
    assert report.blocks_publication is False


def test_missing_instrument_blocks_strict_policy() -> None:
    report = evaluate_daily_bar_quality(
        (_bar("600000"),),
        revision_id="revision-1",
        materialization_id="materialization-1",
        policy=RESEARCH_STRICT_DAILY,
        expected_instruments=_expected(),
        checked_at=_CAPTURED_AT,
    )

    assert report.status is MarketQualityStatus.BLOCKED

    diagnostic = report.diagnostics[0]

    assert diagnostic.kind is MarketQualityDiagnosticKind.MISSING_INSTRUMENT
    assert diagnostic.severity is MarketQualitySeverity.BLOCKING
    assert diagnostic.instrument == _instrument("000001")


def test_missing_instrument_degrades_relaxed_policy() -> None:
    report = evaluate_daily_bar_quality(
        (_bar("600000"),),
        revision_id="revision-1",
        materialization_id="materialization-1",
        policy=SERVING_RELAXED_DAILY,
        expected_instruments=_expected(),
        checked_at=_CAPTURED_AT,
    )

    assert report.status is MarketQualityStatus.DEGRADED
    assert report.blocks_publication is False
    assert report.warning_count == 1

    assert report.diagnostics[0].kind is MarketQualityDiagnosticKind.MISSING_INSTRUMENT


def test_unexpected_instrument_blocks_strict_policy() -> None:
    report = evaluate_daily_bar_quality(
        (
            *_bars(),
            _bar("601398"),
        ),
        revision_id="revision-1",
        materialization_id="materialization-1",
        policy=RESEARCH_STRICT_DAILY,
        expected_instruments=_expected(),
        checked_at=_CAPTURED_AT,
    )

    assert report.status is MarketQualityStatus.BLOCKED

    unexpected = [
        diagnostic
        for diagnostic in report.diagnostics
        if (diagnostic.kind is MarketQualityDiagnosticKind.UNEXPECTED_INSTRUMENT)
    ]

    assert len(unexpected) == 1
    assert unexpected[0].instrument == _instrument("601398")


def test_unexpected_instrument_degrades_relaxed_policy() -> None:
    report = evaluate_daily_bar_quality(
        (
            *_bars(),
            _bar("601398"),
        ),
        revision_id="revision-1",
        materialization_id="materialization-1",
        policy=SERVING_RELAXED_DAILY,
        expected_instruments=_expected(),
        checked_at=_CAPTURED_AT,
    )

    assert report.status is MarketQualityStatus.DEGRADED
    assert report.warning_count == 1


def test_same_symbol_with_different_instrument_type_is_distinct() -> None:
    stock = _bar(
        "510300",
        instrument_type=InstrumentType.STOCK,
    )

    etf = _bar(
        "510300",
        instrument_type=InstrumentType.ETF,
    )

    report = evaluate_daily_bar_quality(
        (
            stock,
            etf,
        ),
        revision_id="revision-1",
        materialization_id="materialization-1",
        policy=RESEARCH_STRICT_DAILY,
        expected_instruments=(
            _instrument(
                "510300",
                InstrumentType.STOCK,
            ),
            _instrument(
                "510300",
                InstrumentType.ETF,
            ),
        ),
        checked_at=_CAPTURED_AT,
    )

    assert report.status is MarketQualityStatus.PASS
    assert report.observed_instrument_count == 2


def test_duplicate_instrument_session_is_blocking() -> None:
    bar = _bar("600000")

    report = evaluate_daily_bar_quality(
        (
            bar,
            bar,
        ),
        revision_id="revision-1",
        materialization_id="materialization-1",
        policy=SERVING_RELAXED_DAILY,
        expected_instruments=(_instrument("600000"),),
        checked_at=_CAPTURED_AT,
    )

    assert report.status is MarketQualityStatus.BLOCKED

    assert any(
        diagnostic.kind is MarketQualityDiagnosticKind.DUPLICATE_INSTRUMENT_SESSION
        and diagnostic.severity is MarketQualitySeverity.BLOCKING
        for diagnostic in report.diagnostics
    )


def test_provider_difference_warning_degrades_report() -> None:
    diagnostic = provider_difference_diagnostic(
        instrument=_instrument("600000"),
        field="close",
        primary_value="10.48",
        comparison_value="10.49",
        primary_provider="tdx",
        comparison_provider="tushare",
        severity=MarketQualitySeverity.WARNING,
    )

    report = evaluate_daily_bar_quality(
        _bars(),
        revision_id="revision-1",
        materialization_id="materialization-1",
        policy=RESEARCH_STRICT_DAILY,
        expected_instruments=_expected(),
        checked_at=_CAPTURED_AT,
        additional_diagnostics=(diagnostic,),
    )

    assert report.status is MarketQualityStatus.DEGRADED
    assert report.warning_count == 1

    assert report.diagnostics[0].kind is MarketQualityDiagnosticKind.PROVIDER_DIFFERENCE


def test_blocking_diagnostic_has_priority_over_warning() -> None:
    warning = provider_difference_diagnostic(
        instrument=_instrument("600000"),
        field="close",
        primary_value="10.48",
        comparison_value="10.49",
        primary_provider="tdx",
        comparison_provider="tushare",
        severity=MarketQualitySeverity.WARNING,
    )

    report = evaluate_daily_bar_quality(
        (_bar("600000"),),
        revision_id="revision-1",
        materialization_id="materialization-1",
        policy=RESEARCH_STRICT_DAILY,
        expected_instruments=_expected(),
        checked_at=_CAPTURED_AT,
        additional_diagnostics=(warning,),
    )

    assert report.status is MarketQualityStatus.BLOCKED
    assert report.blocking_count == 1
    assert report.warning_count == 1


def test_diagnostic_order_is_deterministic() -> None:
    first = provider_difference_diagnostic(
        instrument=_instrument("600000"),
        field="close",
        primary_value="10.48",
        comparison_value="10.49",
        primary_provider="tdx",
        comparison_provider="tushare",
        severity=MarketQualitySeverity.WARNING,
    )

    second = provider_difference_diagnostic(
        instrument=_instrument("000001"),
        field="close",
        primary_value="12.34",
        comparison_value="12.35",
        primary_provider="tdx",
        comparison_provider="tushare",
        severity=MarketQualitySeverity.WARNING,
    )

    forward = evaluate_daily_bar_quality(
        _bars(),
        revision_id="revision-1",
        materialization_id="materialization-1",
        policy=RESEARCH_STRICT_DAILY,
        expected_instruments=_expected(),
        checked_at=_CAPTURED_AT,
        additional_diagnostics=(
            first,
            second,
        ),
    )

    reverse = evaluate_daily_bar_quality(
        _bars(),
        revision_id="revision-1",
        materialization_id="materialization-1",
        policy=RESEARCH_STRICT_DAILY,
        expected_instruments=_expected(),
        checked_at=_CAPTURED_AT,
        additional_diagnostics=(
            second,
            first,
        ),
    )

    assert forward.diagnostics == reverse.diagnostics


def test_checked_at_is_normalized_to_utc() -> None:
    shanghai = timezone(timedelta(hours=8))

    checked_at = datetime(
        2026,
        9,
        15,
        18,
        30,
        tzinfo=shanghai,
    )

    report = evaluate_daily_bar_quality(
        _bars(),
        revision_id="revision-1",
        materialization_id="materialization-1",
        policy=RESEARCH_STRICT_DAILY,
        expected_instruments=_expected(),
        checked_at=checked_at,
    )

    assert report.checked_at == datetime(
        2026,
        9,
        15,
        10,
        30,
        tzinfo=timezone.utc,
    )


def test_checked_at_must_be_timezone_aware() -> None:
    with pytest.raises(
        ValueError,
        match="market_quality_checked_at_must_be_timezone_aware",
    ):
        evaluate_daily_bar_quality(
            _bars(),
            revision_id="revision-1",
            materialization_id="materialization-1",
            policy=RESEARCH_STRICT_DAILY,
            expected_instruments=_expected(),
            checked_at=datetime(
                2026,
                9,
                15,
                10,
                30,
            ),
        )


def test_duplicate_expected_instrument_is_rejected() -> None:
    instrument = _instrument("600000")

    with pytest.raises(
        ValueError,
        match=("market_quality_expected_instrument_duplicate"),
    ):
        evaluate_daily_bar_quality(
            _bars(),
            revision_id="revision-1",
            materialization_id="materialization-1",
            policy=RESEARCH_STRICT_DAILY,
            expected_instruments=(
                instrument,
                instrument,
            ),
            checked_at=_CAPTURED_AT,
        )


def test_report_is_bound_to_revision_and_materialization(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    revision, materialization = _revision_and_materialization(store)

    report = evaluate_daily_bar_revision(
        store,
        revision=revision,
        materialization=materialization,
        policy=RESEARCH_STRICT_DAILY,
        expected_instruments=_expected(),
        checked_at=_CAPTURED_AT,
    )

    assert report.status is MarketQualityStatus.PASS

    assert report.revision_id == revision.ref.revision_id

    assert report.materialization_id == materialization.materialization_id


def test_corrupted_materialization_becomes_blocked_report(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    revision, materialization = _revision_and_materialization(store)

    path = _object_path(
        store,
        materialization.artifact.object_ref.object_id,
    )

    # 主动绕过只读权限，模拟磁盘损坏。
    os.chmod(
        path,
        0o644,
    )
    path.write_bytes(b"corrupted parquet bytes")

    report = evaluate_daily_bar_revision(
        store,
        revision=revision,
        materialization=materialization,
        policy=RESEARCH_STRICT_DAILY,
        expected_instruments=_expected(),
        checked_at=_CAPTURED_AT,
    )

    # Quality Gate 不应让损坏数据继续进入发布路径。
    assert report.status is MarketQualityStatus.BLOCKED
    assert report.blocks_publication is True
    assert report.blocking_count == 1

    assert report.diagnostics[0].kind is (
        MarketQualityDiagnosticKind.MATERIALIZATION_INTEGRITY_FAILURE
    )

    assert report.diagnostics[0].severity is MarketQualitySeverity.BLOCKING


def test_additional_diagnostic_must_use_canonical_type() -> None:
    with pytest.raises(
        TypeError,
        match=("market_quality_additional_diagnostic_invalid"),
    ):
        evaluate_daily_bar_quality(
            _bars(),
            revision_id="revision-1",
            materialization_id="materialization-1",
            policy=RESEARCH_STRICT_DAILY,
            expected_instruments=_expected(),
            checked_at=_CAPTURED_AT,
            additional_diagnostics=("warning",),
        )
