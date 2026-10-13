"""Verification tests for the consolidated server.services.market domain."""

from __future__ import annotations

import pytest

import server.services.market as market_domain
import server.services.market_calendar_automation as legacy_automation
import server.services.market_calendar_dates as legacy_dates
import server.services.market_calendar_evidence as legacy_evidence
import server.services.market_hours as legacy_hours
import server.services.market_indices as legacy_indices

pytestmark = pytest.mark.unit


def test_market_domain_exports_preserve_facade_identity() -> None:
    """Ensure facades re-export exact canonical domain symbols."""
    # Calendar & evidence
    assert (
        market_domain.validate_verified_market_calendar
        is legacy_evidence.validate_verified_market_calendar
    )
    assert (
        market_domain.MarketCalendarEvidenceValidation
        is legacy_evidence.MarketCalendarEvidenceValidation
    )
    assert market_domain.project_market_session is legacy_dates.project_market_session
    assert (
        market_domain.VerifiedClosedTradingDate
        is legacy_dates.VerifiedClosedTradingDate
    )
    assert (
        market_domain.resolve_latest_verified_closed_trading_date
        is legacy_dates.resolve_latest_verified_closed_trading_date
    )
    assert (
        market_domain.resolve_verified_closed_trading_dates
        is legacy_dates.resolve_verified_closed_trading_dates
    )
    assert (
        market_domain.resolve_verified_closed_trading_dates_in_range
        is legacy_dates.resolve_verified_closed_trading_dates_in_range
    )
    assert (
        market_domain.latest_verified_closed_trading_date
        is legacy_dates.latest_verified_closed_trading_date
    )
    assert (
        market_domain.POST_CLOSE_INGESTION_TIME
        is legacy_dates.POST_CLOSE_INGESTION_TIME
    )

    # Automation
    assert (
        market_domain.MarketCalendarAutomationService
        is legacy_automation.MarketCalendarAutomationService
    )
    assert (
        market_domain.market_calendar_automation_years
        is legacy_automation.market_calendar_automation_years
    )
    assert (
        market_domain.MARKET_CALENDAR_AUTOMATION_SCHEMA_VERSION
        == legacy_automation.MARKET_CALENDAR_AUTOMATION_SCHEMA_VERSION
    )

    # Hours & Indices
    assert market_domain.get_shanghai_now is legacy_hours.get_shanghai_now
    assert market_domain.is_cn_trading_session is legacy_hours.is_cn_trading_session
    assert (
        market_domain.default_market_index_assets
        is legacy_indices.default_market_index_assets
    )
    assert (
        market_domain.market_index_display_name
        is legacy_indices.market_index_display_name
    )


def test_market_calendar_validation_fails_closed_on_none() -> None:
    """Missing calendar row must fail closed with explicit blockers."""
    validation = market_domain.validate_verified_market_calendar(None)
    assert not validation.verified
    assert "market_calendar_missing" in validation.blockers
    assert validation.evidence_ref is None
