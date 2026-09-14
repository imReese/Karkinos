from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from server.projections.quote_status import (
    current_quote_valuation_evidence,
    quote_is_stale,
    quote_pricing_semantics,
    quote_status,
    quote_valuation_status,
)
from server.projections.valuation_snapshot import build_current_valuation_snapshot
from server.services.market_calendar_dates import project_market_session

SHANGHAI = ZoneInfo("Asia/Shanghai")
SATURDAY = datetime(2026, 9, 12, 17, 46, tzinfo=SHANGHAI)


def _calendar(*, holidays=()):
    current = date(2026, 1, 1)
    days = []
    while current.year == 2026:
        days.append(
            {
                "date": current.isoformat(),
                "is_trading_day": current.weekday() < 5
                and current.isoformat() not in holidays,
            }
        )
        current += timedelta(days=1)
    trading = sum(day["is_trading_day"] for day in days)
    return {
        "exchange": "SSE",
        "year": 2026,
        "days": days,
        "trading_day_count": trading,
        "closed_day_count": len(days) - trading,
        "official_verification_status": "verified",
        "source_fingerprint": "a" * 64,
        "verification_source_fingerprint": "a" * 64,
        "official_source_fingerprint": "b" * 64,
        "official_source_url": "https://example.test/calendar",
        "official_verified_at": "2026-01-01T00:00:00+08:00",
        "official_verified_by": "fixture",
    }


class CalendarDb:
    def __init__(self, *, calendar=None, quote=None):
        self.calendar = calendar or _calendar()
        self.quote = quote or _quote()

    def get_market_calendar_snapshot_sync(self, *, exchange, year):
        return self.calendar if year == 2026 else None

    def list_latest_quotes_sync(self):
        return [self.quote]

    def get_ledger_entries_sync(self, limit=500, offset=0):
        rows = [
            {
                "id": 1,
                "entry_type": "trade_buy",
                "timestamp": "2026-09-10T10:00:00+08:00",
                "symbol": "600001",
                "direction": "buy",
                "quantity": 1.0,
                "price": 10.0,
                "asset_class": "stock",
            }
        ]
        return rows[offset : offset + limit]


def _quote(day="2026-09-11", **overrides):
    return {
        "symbol": "600001",
        "asset_type": "stock",
        "instrument_type": "stock",
        "price": 11.0,
        "previous_close": 10.0,
        "quote_timestamp": f"{day}T15:00:00+08:00",
        "quote_status": "confirmed",
        "quote_source": "market_bar_close",
        **overrides,
    }


@pytest.mark.parametrize(
    "day, expected", [("2026-09-11", "complete"), ("2026-09-10", "degraded")]
)
def test_verified_weekend_valuation_requires_latest_completed_session(day, expected):
    db = CalendarDb(quote=_quote(day))
    session = project_market_session(db, SATURDAY)
    assert session["status"] == "non_trading_day"
    assert session["latest_completed_trade_date"] == "2026-09-11"
    assert session["next_trading_date"] == "2026-09-14"
    valuation = build_current_valuation_snapshot(db, now=SATURDAY)
    assert valuation["status"] == expected
    assert bool(valuation["metadata"]["valuation_calendar_evidence_refs"])


def test_verified_holiday_uses_calendar_instead_of_weekday_age():
    db = CalendarDb(
        calendar=_calendar(holidays={"2026-09-11"}), quote=_quote("2026-09-10")
    )
    friday = datetime(2026, 9, 11, 10, 30, tzinfo=SHANGHAI)
    assert project_market_session(db, friday)["status"] == "non_trading_day"
    assert not quote_is_stale(db.quote, now=friday, db=db)
    assert build_current_valuation_snapshot(db, now=friday)["status"] == "complete"


def test_expired_intraday_cache_remains_blocked_for_decisions():
    now = datetime(2026, 9, 11, 10, 30, tzinfo=SHANGHAI)
    quote = _quote(
        quote_timestamp="2026-09-11T10:20:00+08:00",
        quote_status="cache",
        quote_source="provider",
    )
    db = CalendarDb(quote=quote)
    assert quote_status(SimpleNamespace(db=db), quote, now=now) == "stale"
    assert build_current_valuation_snapshot(db, now=now)["status"] == "degraded"


@pytest.mark.parametrize(
    "status", ["missing", "error", "conflicting", "unknown", "unrecognized"]
)
def test_invalid_quote_status_is_never_authoritative_valuation(status):
    quote = _quote(quote_status=status)
    assert quote_valuation_status(quote) == "missing"
    assert (
        current_quote_valuation_evidence(quote, now=SATURDAY)["quote_status"] == status
    )


def test_calendar_verification_conflict_does_not_fall_back_to_weekday():
    calendar = _calendar()
    calendar["verification_source_fingerprint"] = "c" * 64
    db = CalendarDb(calendar=calendar)
    assert project_market_session(db, SATURDAY)["calendar_verified"] is False
    assert quote_is_stale(db.quote, now=SATURDAY, db=db)
    assert build_current_valuation_snapshot(db, now=SATURDAY)["status"] == "degraded"


def test_confirmed_fund_nav_has_its_own_date_and_no_live_valuation_ttl():
    now = datetime(2026, 9, 11, 10, 30, tzinfo=SHANGHAI)
    quote = _quote(
        "2026-09-10",
        asset_type="fund",
        instrument_type="open_end_fund",
        quote_source="eastmoney_fund_page",
        nav_date="2026-09-10",
    )
    session = project_market_session(CalendarDb(), now)
    assert quote_pricing_semantics(quote) == {
        "pricing_kind": "published_nav",
        "pricing_as_of": "2026-09-10",
        "pricing_authority": "authoritative",
    }
    assert not quote_is_stale(
        quote, now=now, market_session=session, for_valuation=True
    )
    assert quote_is_stale(quote, now=now, market_session=session)
    assert quote_is_stale(quote, now=SATURDAY, db=CalendarDb(), for_valuation=True)


def test_fund_estimate_and_missing_confirmed_nav_remain_non_authoritative():
    estimate = _quote(
        asset_type="fund",
        instrument_type="open_end_fund",
        quote_source="sina_fund_estimate",
        quote_status="live",
    )
    assert quote_pricing_semantics(estimate)["pricing_kind"] == "estimated_nav"
    assert quote_pricing_semantics(estimate)["pricing_authority"] == "non_authoritative"
    assert quote_valuation_status(estimate) == "degraded"
    pending = {
        **estimate,
        "quote_source": "provider",
        "quote_status": "confirmed_nav_missing",
    }
    assert quote_pricing_semantics(pending)["pricing_kind"] == "nav_pending"
    assert quote_pricing_semantics(pending)["pricing_authority"] == "missing"


def test_cache_provenance_does_not_change_price_semantics_or_expire_weekend_close():
    quote = _quote(captured_reason="persistent_cache", using_persistent_cache=True)
    session = project_market_session(CalendarDb(), SATURDAY)
    projected = current_quote_valuation_evidence(
        quote, now=SATURDAY, market_session=session
    )
    assert quote_pricing_semantics(projected)["pricing_kind"] == "session_close"
    assert quote_valuation_status(projected) == "complete"
    assert projected == quote
    monday = datetime(2026, 9, 14, 10, 30, tzinfo=SHANGHAI)
    stale = current_quote_valuation_evidence(
        quote, now=monday, market_session=project_market_session(CalendarDb(), monday)
    )
    assert quote_valuation_status(stale) == "degraded"
    assert quote["quote_status"] == "confirmed"


def test_etf_uses_exchange_price_and_intraday_observation_is_not_invented_close():
    quote = _quote(instrument_type="etf", asset_type="etf")
    assert quote_pricing_semantics(quote)["pricing_kind"] == "session_close"
    intraday = {
        **quote,
        "quote_timestamp": "2026-09-11T14:00:00+08:00",
        "quote_source": "exchange",
    }
    assert (
        quote_pricing_semantics(
            intraday, market_session=project_market_session(CalendarDb(), SATURDAY)
        )["pricing_kind"]
        == "realtime_quote"
    )


def test_readiness_retains_valid_nav_after_later_refresh_failure(tmp_path):
    from server.db import AppDatabase
    from server.projections.system_readiness import build_system_readiness

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    calendar = _calendar()
    db.upsert_market_calendar_snapshot_sync(
        {**calendar, "provider": "fixture", "status": "available", "limitations": []}
    )
    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2026,
        source_fingerprint="a" * 64,
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="b" * 64,
        verified_by="fixture",
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-09-10T10:00:00+08:00",
        symbol="019999",
        direction="buy",
        quantity=100.0,
        price=1.0,
        asset_class="fund",
    )
    db.save_quote_snapshot_sync(
        symbol="019999",
        asset_class="fund",
        price=1.1,
        volume=None,
        timestamp="2026-09-11T15:00:00+08:00",
        quote_source="eastmoney_fund_page",
        quote_status="confirmed",
        nav_date="2026-09-11",
    )
    db.save_daily_close_snapshot_sync(
        symbol="019999",
        asset_class="fund",
        trade_date="2026-09-10",
        close_price=1.0,
        source="fixture",
    )
    valuation = db.publish_current_valuation_snapshot_sync(now=SATURDAY)
    assert valuation["status"] == "complete"
    db.create_quote_fetch_run(
        run_id="failed-later-refresh",
        started_at="2026-09-12T17:45:00+08:00",
        trigger="manual",
        provider="fixture",
        asset_type="fund",
        status="failed",
        symbol_count=1,
        metadata={"requested_symbols": ["019999"]},
    )
    saturday = build_system_readiness(db.path, now=SATURDAY)
    assert saturday["subsystems"]["valuation_read"]["status"] == "ready"
    assert saturday["subsystems"]["market_data"]["latest_attempt"]["status"] == "failed"
    assert saturday["subsystems"]["market_data"]["status"] == "degraded"
    monday = build_system_readiness(
        db.path, now=datetime(2026, 9, 14, 10, 30, tzinfo=SHANGHAI)
    )
    assert monday["subsystems"]["valuation_read"]["status"] == "ready"
    assert monday["subsystems"]["decision"]["status"] == "blocked"
    monday_close = build_system_readiness(
        db.path, now=datetime(2026, 9, 14, 18, 30, tzinfo=SHANGHAI)
    )
    assert monday_close["subsystems"]["valuation_read"]["status"] == "degraded"
    assert monday_close["valuation_snapshot_id"] == saturday["valuation_snapshot_id"]


def test_fund_without_confirmed_nav_identity_and_manual_mark_fail_closed():
    fund = _quote(
        asset_type="fund",
        instrument_type="open_end_fund",
        quote_status="live",
        quote_source="unknown_provider",
    )
    assert quote_pricing_semantics(fund)["pricing_authority"] == "missing"
    assert quote_valuation_status(fund) == "degraded"
    dated_fund = {**fund, "nav_date": "2026-09-11"}
    assert quote_pricing_semantics(dated_fund)["pricing_authority"] == "missing"
    assert quote_valuation_status(dated_fund) == "degraded"
    manual = _quote(quote_source="manual_mark")
    assert quote_pricing_semantics(manual)["pricing_authority"] == "non_authoritative"
    assert quote_valuation_status(manual) == "degraded"
    manual_fund = {
        **fund,
        "quote_source": "manual_mark",
        "nav_date": "2026-09-11",
        "quote_status": "confirmed",
    }
    assert quote_pricing_semantics(manual_fund)["pricing_kind"] == "manual_mark"
    assert quote_valuation_status(manual_fund) == "degraded"


def test_readiness_reassesses_authority_without_invalidating_legacy_identity(tmp_path):
    import sqlite3

    from server.contracts.content_identity import content_fingerprint
    from server.db import AppDatabase
    from server.persistence.financial_facts_valuation import (
        insert_valuation_snapshot_on_connection,
    )
    from server.projections.system_readiness import build_system_readiness
    from server.projections.valuation_snapshot import (
        _valuation_snapshot_identity_payload,
    )

    legacy = build_current_valuation_snapshot(
        CalendarDb(quote=_quote(quote_source="manual_mark")), now=SATURDAY
    )
    assert legacy["status"] == "degraded"
    legacy["valuation_policy"] = "karkinos.persisted_valuation.v5"
    legacy["status"] = "complete"
    legacy["snapshot_id"] = "valuation-" + content_fingerprint(
        _valuation_snapshot_identity_payload(legacy)
    )
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    with sqlite3.connect(db.path) as conn:
        conn.row_factory = sqlite3.Row
        insert_valuation_snapshot_on_connection(
            conn, legacy, created_at=SATURDAY.isoformat()
        )
    db.set_runtime_control_sync(
        "valuation_snapshot_publication",
        {"status": "ready", "snapshot_id": legacy["snapshot_id"]},
    )

    readiness = build_system_readiness(db.path, now=SATURDAY)

    assert readiness["valuation_snapshot_id"] == legacy["snapshot_id"]
    assert readiness["subsystems"]["valuation_read"]["status"] == "degraded"
    assert readiness["subsystems"]["valuation_read"]["blockers"] == [
        "valuation_incomplete"
    ]
    assert db.get_valuation_snapshot_sync(legacy["snapshot_id"])["status"] == "complete"
