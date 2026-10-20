"""Cash valuation advances by verified sessions without inventing ledger events."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from server.contracts.ai_shadow_research_qualification import (
    ShadowResearchQualificationRejected,
)
from server.db import AppDatabase
from server.persistence.market_calendar import MarketCalendarRepository
from server.projections.valuation_snapshot import valuation_snapshot_from_row
from server.services.account.valuation_snapshot import build_current_valuation_snapshot
from server.services.ai_shadow.ai_shadow_research_qualification_support import (
    require_current_valuation_trade_date,
)
from server.services.market.calendar import latest_verified_closed_trading_date
from tests.server.test_market_pricing_semantics import _calendar

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _verify_calendar(db):
    db._market_calendar = MarketCalendarRepository(
        db.path, now=lambda tz=None: datetime(2026, 1, 1, tzinfo=SHANGHAI)
    )
    db.upsert_market_calendar_snapshot_sync(
        {**_calendar(), "provider": "fixture", "status": "available", "limitations": []}
    )
    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2026,
        source_fingerprint="a" * 64,
        verification_status="verified",
        official_source_url="https://example.test/synthetic-calendar",
        official_source_fingerprint="b" * 64,
        verified_by="fixture",
    )


def _book(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-06-08T18:00:00+08:00",
        amount=20000,
        asset_class="cash",
    )
    return db


def _require_current(db, snapshot, now):
    require_current_valuation_trade_date(
        snapshot,
        source_market_date="2026-06-08",
        latest_closed_market_date_reader=latest_verified_closed_trading_date,
        db=db,
        clock=lambda: now,
    )


def test_old_cash_ledger_has_stable_current_session_value_and_legacy_replay(tmp_path):
    db = _book(tmp_path)
    now = datetime(2026, 8, 31, 18, tzinfo=SHANGHAI)
    legacy = build_current_valuation_snapshot(db, persist=True, now=now)
    assert legacy["trade_date"] == "2026-06-08"
    assert "cash_valuation_basis" not in legacy["metadata"]
    ledger = db.get_all_ledger_entries_sync()
    _verify_calendar(db)
    first = build_current_valuation_snapshot(db, persist=True, now=now)
    later = build_current_valuation_snapshot(db, persist=True, now=now.replace(hour=21))
    assert first == later
    assert first["status"] == "complete" and first["quotes"] == []
    assert first["trade_date"] == "2026-08-31"
    assert first["as_of"] == "2026-08-31T00:00:00+08:00"
    assert first["metadata"]["cash_valuation_basis"] == "verified_expected_session.v1"
    assert first["ledger_cutoff_id"] == legacy["ledger_cutoff_id"]
    assert first["ledger_fingerprint"] == legacy["ledger_fingerprint"]
    _require_current(db, first, now)
    next_day = now.replace(month=9, day=1)
    following = build_current_valuation_snapshot(db, persist=True, now=next_day)
    assert following["trade_date"] == "2026-09-01"
    assert following["snapshot_id"] != first["snapshot_id"]
    assert following["ledger_fingerprint"] == first["ledger_fingerprint"]
    _require_current(db, following, next_day)
    with pytest.raises(ShadowResearchQualificationRejected, match="snapshot_stale"):
        _require_current(db, first, next_day)
    for snapshot in (legacy, first, following):
        restored = valuation_snapshot_from_row(
            db.get_valuation_snapshot_sync(snapshot["snapshot_id"])
        )
        assert restored["snapshot_id"] == snapshot["snapshot_id"]
        assert restored["trade_date"] == snapshot["trade_date"]
    assert db.get_all_ledger_entries_sync() == ledger


def test_weekend_cashflow_keeps_fact_time_but_uses_last_verified_session(tmp_path):
    db = _book(tmp_path)
    _verify_calendar(db)
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-09-05T12:00:00+08:00",
        amount=1000,
        asset_class="cash",
    )
    now = datetime(2026, 9, 5, 18, tzinfo=SHANGHAI)
    snapshot = build_current_valuation_snapshot(db, persist=True, now=now)
    assert snapshot["as_of"] == "2026-09-05T12:00:00+08:00"
    assert snapshot["trade_date"] == "2026-09-04"
    assert snapshot["metadata"]["valuation_expected_date"] == "2026-09-04"
    _require_current(db, snapshot, now)


@pytest.mark.parametrize(
    ("asset_class", "has_old_quote"),
    [("stock", False), ("stock", True), ("fund", False)],
)
def test_nonzero_holdings_still_require_current_market_evidence(
    tmp_path, asset_class, has_old_quote
):
    db = _book(tmp_path)
    _verify_calendar(db)
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-06-08T18:01:00+08:00",
        symbol="600000",
        direction="buy",
        quantity=100,
        price=10,
        asset_class=asset_class,
    )
    if has_old_quote:
        db.upsert_latest_quote_sync(
            symbol="600000",
            asset_type="stock",
            price=10,
            previous_close=10,
            quote_timestamp="2026-08-28T15:00:00+08:00",
            quote_status="confirmed",
        )
    now = datetime(2026, 8, 31, 18, tzinfo=SHANGHAI)
    snapshot = build_current_valuation_snapshot(db, persist=True, now=now)
    assert snapshot["status"] in {"missing", "degraded"}
    assert snapshot["trade_date"] < "2026-08-31"
    assert "cash_valuation_basis" not in snapshot["metadata"]
    with pytest.raises(ShadowResearchQualificationRejected, match="snapshot_stale"):
        _require_current(db, snapshot, now)


@pytest.mark.parametrize(
    ("entry_type", "message"),
    [
        ("trade_buy", "quantity must be a finite decimal"),
        ("unknown_fund_subscription", "Unsupported"),
    ],
)
def test_unresolved_ledger_cannot_be_reclassified_as_current_cash(
    tmp_path, entry_type, message
):
    db = _book(tmp_path)
    _verify_calendar(db)
    rows = [
        *db.get_all_ledger_entries_sync(),
        {
            "id": 2,
            "entry_type": entry_type,
            "timestamp": "2026-08-31T12:00:00+08:00",
            "symbol": "019999",
            "direction": "buy",
            "amount": "1000",
            "quantity": None,
            "price": "1",
            "commission": "0",
            "asset_class": "fund",
        },
    ]
    from server.projections.valuation_snapshot import build_current_valuation_snapshot

    with pytest.raises(ValueError, match=message):
        build_current_valuation_snapshot(
            db,
            candidate_ledger_rows=rows,
            now=datetime(2026, 8, 31, 18, tzinfo=SHANGHAI),
        )
