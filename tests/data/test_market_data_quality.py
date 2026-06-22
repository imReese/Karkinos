"""Market data quality diagnostic tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from core.types import AssetClass, BarFrequency, Symbol
from data.market_data import (
    MarketDataDiagnosticKind,
    MarketDataEventKind,
    MarketDataQualityStatus,
    MarketDataRecord,
    MarketDataRecordMetadata,
    MarketDataStatus,
    build_market_data_quality_report,
)


def test_quality_report_detects_missing_non_trading_and_stale_records() -> None:
    report = build_market_data_quality_report(
        [
            _record(
                symbol="600519",
                session="2026-06-18",
                status=MarketDataStatus.CONFIRMED,
            ),
            _record(
                symbol="600519",
                session="2026-06-20",
                status=MarketDataStatus.CONFIRMED,
            ),
            _record(
                symbol="600519",
                session="2026-06-18",
                status=MarketDataStatus.STALE,
                freshness={"age_seconds": 7200},
            ),
        ],
        expected_trading_sessions=("2026-06-18", "2026-06-19"),
        non_trading_sessions=("2026-06-20",),
        stale_after_seconds=1800,
        symbols=(Symbol("600519"),),
        checked_at=datetime(2026, 6, 20, 15, 30, tzinfo=UTC),
    )

    assert report.status == MarketDataQualityStatus.BLOCKED
    assert _diagnostic_kinds(report) == {
        MarketDataDiagnosticKind.MISSING_TRADING_DATE,
        MarketDataDiagnosticKind.NON_TRADING_DAY_OBSERVATION,
        MarketDataDiagnosticKind.STALE_QUOTE,
    }
    assert report.to_payload()["status_label_zh"] == "阻断"
    assert {
        diagnostic.details["trading_session"]
        for diagnostic in report.diagnostics
        if diagnostic.kind is MarketDataDiagnosticKind.MISSING_TRADING_DATE
    } == {"2026-06-19"}


def test_quality_report_detects_fund_nav_adjustment_and_provider_differences() -> None:
    report = build_market_data_quality_report(
        [
            _record(
                symbol="600519",
                session="2026-06-18",
                source="provider_a",
                adjustment_mode="qfq",
                close=Decimal("10.00"),
            ),
            _record(
                symbol="600519",
                session="2026-06-18",
                source="provider_b",
                adjustment_mode=None,
                close=Decimal("10.30"),
            ),
            _record(
                symbol="012345",
                asset_class=AssetClass.FUND,
                session="2026-06-18",
                status=MarketDataStatus.CONFIRMED_NAV_MISSING,
                close=Decimal("1.2345"),
            ),
        ],
        expected_trading_sessions=("2026-06-18",),
        provider_difference_tolerance=Decimal("0.05"),
        symbols=(Symbol("600519"), Symbol("012345")),
        checked_at=datetime(2026, 6, 20, 15, 30, tzinfo=UTC),
    )

    assert report.status == MarketDataQualityStatus.BLOCKED
    assert _diagnostic_kinds(report) == {
        MarketDataDiagnosticKind.ADJUSTMENT_GAP,
        MarketDataDiagnosticKind.PROVIDER_DIFFERENCE,
        MarketDataDiagnosticKind.DELAYED_FUND_NAV,
    }
    payload = report.to_payload()
    assert payload["diagnostics"][0]["kind"] in {
        "adjustment_gap",
        "provider_difference",
        "delayed_fund_nav",
    }
    assert all("message_zh" in item for item in payload["diagnostics"])


def _diagnostic_kinds(report):
    return {diagnostic.kind for diagnostic in report.diagnostics}


def _record(
    *,
    symbol: str,
    session: str,
    asset_class: AssetClass = AssetClass.STOCK,
    status: MarketDataStatus = MarketDataStatus.CONFIRMED,
    source: str = "fixture_provider",
    adjustment_mode: str | None = "qfq",
    close: Decimal = Decimal("10.00"),
    freshness: dict | None = None,
) -> MarketDataRecord:
    observed_at = datetime.fromisoformat(f"{session}T15:00:00+00:00")
    return MarketDataRecord(
        kind=MarketDataEventKind.DAILY_BAR,
        symbol=Symbol(symbol),
        asset_class=asset_class,
        frequency=BarFrequency.DAILY,
        timestamp=observed_at,
        values={"close": close},
        metadata=MarketDataRecordMetadata(
            source=source,
            source_symbol=f"{symbol}.TEST",
            status=status,
            observed_at=observed_at,
            trading_session=session,
            adjustment_mode=adjustment_mode,
            freshness=freshness or {"age_seconds": 0},
        ),
    )
