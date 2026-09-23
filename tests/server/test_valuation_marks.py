"""Observation recency never replaces the Financial Book's published NAV mark."""

import json
import sqlite3
from datetime import datetime

import pytest

from server.config import ServerConfig
from server.contracts.quote_ingestion import QuoteIngestionCommand
from server.db import AppDatabase
from server.dependencies import AppState
from server.projections.account_state import (
    build_overview_account_state_response as build_account_state_response,
)
from server.projections.valuation_snapshot import (
    build_current_valuation_snapshot,
    select_authoritative_valuation_marks,
    valuation_snapshot_from_row,
)
from tests.server.test_market_pricing_semantics import SHANGHAI, _calendar

MONDAY = datetime(2026, 9, 14, 10, 30, tzinfo=SHANGHAI)


def _book(tmp_path):
    db = AppDatabase(tmp_path / "book.db")
    db.init_sync()
    db.upsert_market_calendar_snapshot_sync(
        {**_calendar(), "provider": "fixture", "status": "available", "limitations": []}
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
        entry_type="cash_deposit",
        timestamp="2026-09-10T09:00:00+08:00",
        amount=1000.0,
        asset_class="cash",
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-09-10T10:00:00+08:00",
        symbol="019999",
        direction="buy",
        quantity=100.0,
        price=1.5,
        asset_class="fund",
    )
    return db


def _nav(**overrides):
    return {
        "symbol": "019999",
        "asset_type": "fund",
        "price": 1.8,
        "quote_timestamp": "2026-09-11T18:00:00+08:00",
        "quote_source": "eastmoney_fund_page",
        "quote_status": "confirmed",
        "nav_date": "2026-09-11",
        **overrides,
    }


def _estimate():
    return _nav(
        price=1.8115,
        quote_timestamp="2026-09-14T10:29:00+08:00",
        quote_source="sina_fund_estimate",
        quote_status="live",
        nav_date=None,
    )


def _save(db, row):
    row = dict(row)
    db.save_quote_snapshot_sync(
        asset_class=row.pop("asset_type"),
        timestamp=row.pop("quote_timestamp"),
        volume=None,
        **row,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("baseline", [True, False])
async def test_published_nav_survives_new_estimate_in_real_book(tmp_path, baseline):
    db = _book(tmp_path)
    if baseline:
        db.save_daily_close_snapshot_sync(
            symbol="019999",
            asset_class="fund",
            trade_date="2026-09-10",
            close_price=1.75,
            source="fixture",
        )
    _save(db, _nav())
    _save(db, _estimate())
    valuation = db.publish_current_valuation_snapshot_sync(now=MONDAY)
    state = AppState()
    state.db, state.config = db, ServerConfig()

    account = await build_account_state_response(state, now=MONDAY)

    position = account.snapshot.positions[0]
    assert valuation["status"] == "complete"
    assert position.latest_price == 1.8
    assert position.market_value == 180.0
    assert position.unrealized_pnl == pytest.approx(30.0)
    assert position.pricing_kind == "published_nav"
    assert position.pricing_as_of == "2026-09-11"
    assert position.quote_status == "stale"
    assert position.stale_reason == "quote_older_than_expected_session"
    assert position.latest_observation.price == 1.8115
    assert position.latest_observation.pricing_kind == "estimated_nav"
    assert position.latest_observation.pricing_authority == "non_authoritative"
    assert account.summary.total_equity == 1030.0
    assert account.summary.cumulative_pnl == pytest.approx(30.0)
    assert account.overview.valuation_usability == "usable"
    assert account.overview.user_attention == []
    assert account.overview.decision_readiness != "ready"
    if baseline:
        assert account.summary.today_pnl == pytest.approx(5.0)
        assert account.summary.latest_session_date == "2026-09-11"
    if baseline:
        assert position.today_change == pytest.approx(5.0)
        assert position.performance_session_date == "2026-09-11"
    else:
        assert position.today_change is None
    stored = valuation_snapshot_from_row(
        db.get_valuation_snapshot_sync(valuation["snapshot_id"])
    )
    assert stored["quotes"] == valuation["quotes"]
    assert db.get_latest_quote_sync("019999", "fund")["price"] == 1.8115


@pytest.mark.parametrize("writer", ["snapshot", "ingestion"])
def test_late_published_nav_changes_revision_without_regressing_observation(
    tmp_path, writer
):
    db = _book(tmp_path)
    _save(db, _estimate())
    before = db.publish_current_valuation_snapshot_sync(now=MONDAY)
    with sqlite3.connect(db.path) as conn:
        revision_before = conn.execute(
            "SELECT revision FROM quote_current_materialization_state"
        ).fetchone()[0]
    if writer == "ingestion":
        db.persist_quote_ingestion_sync(QuoteIngestionCommand(**_nav()))
    else:
        _save(db, _nav())
    after = db.publish_current_valuation_snapshot_sync(now=MONDAY)
    with sqlite3.connect(db.path) as conn:
        revision_after = conn.execute(
            "SELECT revision FROM quote_current_materialization_state"
        ).fetchone()[0]
    assert before["status"] == "degraded"
    assert after["status"] == "complete"
    assert revision_after > revision_before
    assert after["snapshot_id"] != before["snapshot_id"]
    assert after["quotes"][0]["price"] == 1.8
    assert after["quotes"][0]["latest_observation"]["price"] == 1.8115
    assert db.get_latest_quote_sync("019999", "fund")["price"] == 1.8115
    assert (
        json.loads(db.get_valuation_snapshot_sync(before["snapshot_id"])["quotes_json"])
        == before["quotes"]
    )


def test_nav_selection_uses_economic_date_before_observation_time(tmp_path):
    db = _book(tmp_path)
    _save(db, _nav())
    _save(
        db,
        _nav(
            price=1.79,
            nav_date="2026-09-10",
            quote_timestamp="2026-09-14T10:00:00+08:00",
        ),
    )
    valuation = build_current_valuation_snapshot(db, now=MONDAY)
    mark = valuation["quotes"][0]
    assert valuation["status"] == "complete"
    assert mark["price"] == 1.8
    assert mark["nav_date"] == "2026-09-11"
    assert mark["latest_observation"]["price"] == 1.79


def test_conflicting_published_nav_is_not_hidden_by_newer_estimate(tmp_path):
    db = _book(tmp_path)
    _save(db, _nav())
    _save(db, _estimate())
    _save(db, _nav(price=1.9, quote_timestamp="2026-09-11T19:00:00+08:00"))
    with pytest.raises(ValueError, match="published NAV facts conflict"):
        build_current_valuation_snapshot(db, now=MONDAY)


@pytest.mark.asyncio
async def test_after_close_book_uses_previous_session_nav_but_decision_stays_stale(
    tmp_path,
):
    db = _book(tmp_path)
    _save(
        db,
        _nav(
            nav_date="2026-09-17",
            quote_timestamp="2026-09-17T20:00:00+08:00",
        ),
    )
    now = datetime(2026, 9, 18, 19, 30, tzinfo=SHANGHAI)

    valuation = db.publish_current_valuation_snapshot_sync(now=now)
    assert valuation["valuation_policy"] == "karkinos.persisted_valuation.v8"
    assert valuation["status"] == "complete"
    assert valuation["quotes"][0]["quote_status"] == "confirmed"

    state = AppState()
    state.db, state.config = db, ServerConfig()
    account = await build_account_state_response(state, now=now)

    position = account.snapshot.positions[0]
    assert position.valuation_available is True
    assert position.market_value == pytest.approx(180.0)
    assert position.quote_status == "stale"
    assert position.stale_reason == "quote_older_than_expected_session"
    assert account.summary.total_equity == pytest.approx(1030.0)
    assert account.summary.cumulative_pnl == pytest.approx(30.0)
    assert account.overview.valuation_usability == "usable"
    assert account.overview.decision_readiness != "ready"


def test_estimate_only_and_overdue_nav_are_distinct_unusable_evidence(tmp_path):
    db = _book(tmp_path)
    _save(db, _estimate())
    only_estimate = build_current_valuation_snapshot(db, now=MONDAY)
    assert only_estimate["quotes"][0]["quote_status"] == "confirmed_nav_missing"
    _save(db, _nav(nav_date="2026-09-10", quote_timestamp="2026-09-10T18:00:00+08:00"))
    overdue = build_current_valuation_snapshot(db, now=MONDAY)
    assert overdue["quotes"][0]["price"] == 1.8
    assert overdue["quotes"][0]["quote_status"] == "stale"
    assert overdue["quotes"][0]["stale_reason"] == "quote_older_than_expected_session"
    assert overdue["quotes"][0]["latest_observation"]["price"] == 1.8115


@pytest.mark.asyncio
async def test_overdue_published_nav_has_display_value_without_restoring_valuation(
    tmp_path,
):
    db = _book(tmp_path)
    _save(db, _nav(nav_date="2026-09-21", quote_timestamp="2026-09-21T18:00:00+08:00"))
    _save(
        db,
        _nav(
            price=1.9,
            nav_date=None,
            quote_timestamp="2026-09-22T14:55:00+08:00",
            quote_source="sina_fund_estimate",
            quote_status="live",
        ),
    )
    now = datetime(2026, 9, 23, 19, 30, tzinfo=SHANGHAI)
    db.publish_current_valuation_snapshot_sync(now=now)
    state = AppState()
    state.db, state.config = db, ServerConfig()

    account = await build_account_state_response(state, now=now)

    assert account.summary.total_equity is None
    assert account.summary.indicative_total_equity == pytest.approx(1030.0)
    assert account.summary.indicative_fund_nav_date == "2026-09-21"
    assert account.summary.cumulative_pnl is None
    assert account.snapshot.positions[0].market_value is None
    assert account.overview.valuation_usability == "degraded"
    assert account.overview.decision_readiness == "blocked"


@pytest.mark.asyncio
async def test_estimated_nav_never_produces_indicative_total(tmp_path):
    db = _book(tmp_path)
    _save(db, _estimate())
    db.publish_current_valuation_snapshot_sync(now=MONDAY)
    state = AppState()
    state.db, state.config = db, ServerConfig()

    account = await build_account_state_response(state, now=MONDAY)

    assert account.summary.total_equity is None
    assert account.summary.indicative_total_equity is None


@pytest.mark.asyncio
async def test_missing_stock_price_blocks_fund_reference_total(tmp_path):
    db = _book(tmp_path)
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-09-22T10:00:00+08:00",
        symbol="600001",
        direction="buy",
        quantity=1.0,
        price=10.0,
        asset_class="stock",
    )
    _save(db, _nav(nav_date="2026-09-21", quote_timestamp="2026-09-21T18:00:00+08:00"))
    now = datetime(2026, 9, 23, 19, 30, tzinfo=SHANGHAI)
    db.publish_current_valuation_snapshot_sync(now=now)
    state = AppState()
    state.db, state.config = db, ServerConfig()

    account = await build_account_state_response(state, now=now)

    assert account.summary.total_equity is None
    assert account.summary.indicative_total_equity is None


def test_conflicting_same_instant_published_mark_stays_fail_closed():
    with pytest.raises(ValueError, match="quote authority facts conflict"):
        select_authoritative_valuation_marks(
            [
                _nav(),
                _nav(price=1.9),
                _estimate(),
            ]
        )


def test_published_nav_selection_uses_index_without_history_sort(tmp_path):
    from server.persistence.quote_current_materialization import (
        published_nav_rows_on_connection,
    )

    db = _book(tmp_path)
    _save(db, _nav())
    _save(db, _estimate())
    with sqlite3.connect(db.path) as conn:
        queries = []
        conn.set_trace_callback(queries.append)
        rows = published_nav_rows_on_connection(conn, "019999")
        conn.set_trace_callback(None)
        assert rows[0]["price"] == 1.8
        plans = [list(conn.execute("EXPLAIN QUERY PLAN " + query)) for query in queries]
    newest_plan = " ".join(str(row[-1]) for row in plans[0])
    assert "USING INDEX idx_quote_snapshots_published_nav_date" in newest_plan
    assert "USE TEMP B-TREE" not in newest_plan
    peer_plan = " ".join(str(row[-1]) for row in plans[1])
    assert "idx_quote_snapshots_published_nav_date" in peer_plan
    assert "idx_quote_snapshots_typed_identity_instant" in peer_plan
    assert "SCAN quote_snapshots" not in peer_plan


def test_startup_reconciliation_advances_late_authoritative_nav_revision(tmp_path):
    from server.persistence.financial_fact_event_payloads import (
        quote_instant_storage_key,
    )
    from server.persistence.quote_current_materialization import (
        reconcile_quote_current_materialization_on_connection,
    )

    db = _book(tmp_path)
    _save(db, _estimate())
    with sqlite3.connect(db.path) as conn:
        before = conn.execute(
            "SELECT revision FROM quote_current_materialization_state"
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO quote_snapshots (
                symbol, asset_class, instrument_type, identity_provenance, price,
                timestamp, quote_instant_utc, created_at, quote_status, quote_source, nav_date
            ) VALUES ('019999', 'open_end_fund', 'open_end_fund', 'explicit_canonical', 1.8,
                ?, ?, ?, 'confirmed', 'eastmoney_fund_page', '2026-09-11')""",
            (
                _nav()["quote_timestamp"],
                quote_instant_storage_key(_nav()["quote_timestamp"]),
                MONDAY.isoformat(),
            ),
        )
        result = reconcile_quote_current_materialization_on_connection(
            conn, updated_at=MONDAY.isoformat()
        )
        assert result.revision > before
    snapshot = build_current_valuation_snapshot(db, now=MONDAY)
    assert snapshot["quotes"][0]["price"] == 1.8
    assert snapshot["quotes"][0]["latest_observation"]["price"] == 1.8115


def test_legacy_v6_baseline_classification_preserves_snapshot_identity(tmp_path):
    from server.contracts.content_identity import content_fingerprint
    from server.projections.valuation_snapshot import (
        _valuation_snapshot_identity_payload,
    )
    from server.valuation_snapshot_contract import validate_valuation_snapshot

    db = _book(tmp_path)
    _save(db, _nav())
    current = build_current_valuation_snapshot(db, now=MONDAY)
    assert current["status"] == "complete"
    legacy = {
        **current,
        "valuation_policy": "karkinos.persisted_valuation.v6",
        "status": "degraded",
        "metadata": {
            **current["metadata"],
            "valuation_freshness_policy": "expected_session_and_live_ttl.v1",
        },
    }
    legacy["snapshot_id"] = "valuation-" + content_fingerprint(
        _valuation_snapshot_identity_payload(legacy)
    )
    validate_valuation_snapshot(legacy)
    validate_valuation_snapshot(current)
    assert current["snapshot_id"] != legacy["snapshot_id"]


@pytest.mark.parametrize(
    "hour,minute,status",
    [
        (9, 0, "pre_open"),
        (10, 0, "open"),
        (12, 0, "midday_break"),
        (16, 0, "after_close"),
    ],
)
def test_verified_market_session_has_explicit_current_day_phase(
    tmp_path, hour, minute, status
):
    from server.services.market_calendar_dates import project_market_session

    session = project_market_session(
        _book(tmp_path), MONDAY.replace(hour=hour, minute=minute)
    )
    assert session["status"] == status
    assert session["market_date"] == "2026-09-14"


@pytest.mark.asyncio
async def test_previous_estimate_does_not_become_canonical_session_baseline(tmp_path):
    db = _book(tmp_path)
    _save(
        db,
        _nav(
            price=1.7,
            quote_source="sina_fund_estimate",
            quote_status="live",
            nav_date=None,
            quote_timestamp="2026-09-10T14:00:00+08:00",
        ),
    )
    _save(db, _nav())
    valuation = db.publish_current_valuation_snapshot_sync(now=MONDAY)
    state = AppState()
    state.db, state.config = db, ServerConfig()
    account = await build_account_state_response(state, now=MONDAY)
    assert valuation["status"] == "complete"
    assert account.summary.total_equity == 1030.0
    assert account.summary.today_pnl is None
    assert account.snapshot.positions[0].today_change is None


def test_unheld_published_nav_conflict_does_not_block_current_book(tmp_path):
    db = _book(tmp_path)
    _save(db, _nav())
    _save(db, _nav(symbol="018888"))
    _save(
        db,
        _nav(symbol="018888", price=1.9, quote_timestamp="2026-09-11T19:00:00+08:00"),
    )
    snapshot = build_current_valuation_snapshot(db, now=MONDAY)
    assert snapshot["status"] == "complete"
    assert [row["symbol"] for row in snapshot["quotes"]] == ["019999"]
