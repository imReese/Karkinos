from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from server.contracts.quote_ingestion import QuoteIngestionCommand
from server.db import AppDatabase
from server.projections.valuation_snapshot import load_persisted_quote_rows
from server.services.valuation_snapshot import (
    VALUATION_POLICY_VERSION,
    build_current_valuation_snapshot,
)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _valuation_now(
    hour: int = 16,
    minute: int = 0,
) -> datetime:
    return datetime(2026, 7, 10, hour, minute, tzinfo=_SHANGHAI_TZ)


def _holding_row(
    symbol: str,
    *,
    asset_class: str = "stock",
    entry_id: int = 1,
    timestamp: str = "2026-07-10T09:30:00+08:00",
) -> dict[str, object]:
    return {
        "id": entry_id,
        "entry_type": "trade_buy",
        "timestamp": timestamp,
        "symbol": symbol,
        "direction": "buy",
        "quantity": 1.0,
        "price": 1.0,
        "commission": 0.0,
        "asset_class": asset_class,
        "source": "manual",
    }


def _record_holding(
    db: AppDatabase,
    symbol: str,
    *,
    asset_class: str = "stock",
    timestamp: str = "2026-07-10T09:30:00+08:00",
) -> None:
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp=timestamp,
        symbol=symbol,
        direction="buy",
        quantity=1.0,
        price=1.0,
        asset_class=asset_class,
    )


def _record_latest_stock_holding(
    db: AppDatabase,
    *,
    timestamp: str = "2026-07-10T09:30:00+08:00",
) -> None:
    rows = db.list_latest_quotes_sync()
    symbols = {
        str(row["symbol"])
        for row in rows
        if str(
            row.get("instrument_type")
            or row.get("asset_type")
            or row.get("asset_class")
        )
        .strip()
        .lower()
        == "stock"
    }
    assert len(symbols) == 1
    _record_holding(db, next(iter(symbols)), timestamp=timestamp)


def test_valuation_snapshot_is_content_addressed_and_replayable(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
        quote_source="tushare_realtime_quote",
        provider_name="tushare",
        quote_status="live",
        provider_status="live",
        captured_reason="scheduler_poll",
    )
    _record_latest_stock_holding(db)

    publication_before = db.get_runtime_control_sync("valuation_snapshot_publication")
    first = build_current_valuation_snapshot(db, now=_valuation_now())
    assert db.get_valuation_snapshot_sync(first["snapshot_id"]) is None
    assert db.get_runtime_control_sync("valuation_snapshot_publication") == (
        publication_before
    )
    second = build_current_valuation_snapshot(
        db,
        persist=True,
        now=_valuation_now(),
    )
    stored = db.get_valuation_snapshot_sync(first["snapshot_id"])
    publication = db.get_runtime_control_sync("valuation_snapshot_publication")

    assert first == second
    assert first["snapshot_id"].startswith("valuation-")
    assert first["status"] == "degraded"
    assert first["valuation_lanes"] == [
        {
            "asset_class": "stock",
            "status": "degraded",
            "quote_count": 1,
            "complete_quote_count": 0,
            "review_required_quote_count": 1,
            "blocker_statuses": ["valuation_baseline_missing"],
        },
        {
            "asset_class": "fund",
            "status": "not_applicable",
            "quote_count": 0,
            "complete_quote_count": 0,
            "review_required_quote_count": 0,
            "blocker_statuses": [],
        },
    ]
    assert first["metadata"] == {
        "quote_count": 1,
        "current_position_count": 1,
        "valuation_scope_policy": "current_nonzero_positions.v1",
        "valuation_freshness_policy": "expected_session_and_live_ttl.v1",
        "valuation_expected_date": "2026-07-10",
        "current_position_scope_fingerprint": (
            "a2060e1120202f61d14a27774b5a0f0e0dfc9efbb198be0a14cbd686a0fafd77"
        ),
        "ledger_entry_count": 1,
        "persisted_facts_only": True,
        "runtime_cache_used": False,
        "provider_fetch_used": False,
        "ingestion_run_ids": [],
    }
    assert stored is not None
    assert publication is not None
    assert publication["status"] == "ready"
    assert publication["snapshot_id"] == first["snapshot_id"]
    assert json.loads(stored["quotes_json"])[0]["symbol"] == "603659"


def test_persisted_valuation_snapshots_are_database_immutable(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="600001",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )
    _record_holding(db, "600001")
    snapshot = db.publish_current_valuation_snapshot_sync(now=_valuation_now())

    with sqlite3.connect(db.path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE valuation_snapshots SET status = 'blocked' "
                "WHERE snapshot_id = ?",
                (snapshot["snapshot_id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "DELETE FROM valuation_snapshots WHERE snapshot_id = ?",
                (snapshot["snapshot_id"],),
            )


def test_qualification_rejects_tampered_persisted_valuation_content(tmp_path):
    from server.contracts.ai_shadow_research_qualification import (
        ShadowResearchQualificationRejected,
    )
    from server.services.ai_shadow_research_qualification_support import (
        require_complete_valuation,
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_daily_close_snapshot_sync(
        symbol="600001",
        asset_class="stock",
        trade_date="2026-07-09",
        close_price=25.46,
        source="test_close",
    )
    db.save_quote_snapshot_sync(
        symbol="600001",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
        quote_status="confirmed",
    )
    _record_holding(db, "600001")
    snapshot = db.publish_current_valuation_snapshot_sync(now=_valuation_now())
    assert snapshot["status"] == "complete"

    with sqlite3.connect(db.path) as conn:
        conn.execute("DROP TRIGGER valuation_snapshots_update_guard")
        quotes = json.loads(
            conn.execute(
                "SELECT quotes_json FROM valuation_snapshots " "WHERE snapshot_id = ?",
                (snapshot["snapshot_id"],),
            ).fetchone()[0]
        )
        quotes[0]["price"] = 999.0
        conn.execute(
            "UPDATE valuation_snapshots SET quotes_json = ? " "WHERE snapshot_id = ?",
            (json.dumps(quotes), snapshot["snapshot_id"]),
        )
        conn.commit()

    with pytest.raises(
        ShadowResearchQualificationRejected,
        match="qualification_valuation_snapshot_not_persisted",
    ):
        require_complete_valuation(snapshot, db)


def test_valuation_snapshot_publish_preserves_explicit_policy(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )

    projected = build_current_valuation_snapshot(
        db,
        valuation_policy="custom-policy.v1",
    )
    published = build_current_valuation_snapshot(
        db,
        valuation_policy="custom-policy.v1",
        persist=True,
    )
    stored = db.get_valuation_snapshot_sync(published["snapshot_id"])

    assert projected == published
    assert published["valuation_policy"] == "custom-policy.v1"
    assert stored is not None
    assert stored["valuation_policy"] == "custom-policy.v1"


def test_default_valuation_policy_preserves_no_argument_publisher_compatibility():
    class LegacyPublisher:
        def publish_current_valuation_snapshot_sync(self):
            return {"status": "complete", "valuation_policy": VALUATION_POLICY_VERSION}

    published = build_current_valuation_snapshot(LegacyPublisher(), persist=True)

    assert published["valuation_policy"] == VALUATION_POLICY_VERSION


def test_valuation_snapshot_changes_when_persisted_quote_changes(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )
    _record_latest_stock_holding(db)
    first = build_current_valuation_snapshot(db, persist=True)

    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.7,
        volume=1200.0,
        timestamp="2026-07-10T14:58:03+08:00",
    )
    second = build_current_valuation_snapshot(db, persist=True)

    assert second["snapshot_id"] != first["snapshot_id"]
    assert second["quote_set_fingerprint"] != first["quote_set_fingerprint"]


def test_valuation_snapshot_freezes_previous_close_evidence(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_daily_close_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        trade_date="2026-07-09",
        close_price=25.46,
        source="test_close",
    )
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )
    _record_latest_stock_holding(db)

    first = build_current_valuation_snapshot(db, persist=True)
    stored_first = db.get_valuation_snapshot_sync(first["snapshot_id"])
    assert first["quotes"][0]["previous_close"] == 25.46
    assert first["quotes"][0]["previous_close_date"] == "2026-07-09"
    assert first["quotes"][0]["valuation_baseline_status"] == "complete"

    db.save_daily_close_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        trade_date="2026-07-09",
        close_price=25.40,
        source="corrected_close",
    )
    second = build_current_valuation_snapshot(db, persist=True)

    assert second["snapshot_id"] != first["snapshot_id"]
    assert second["quote_set_fingerprint"] != first["quote_set_fingerprint"]
    assert json.loads(stored_first["quotes_json"])[0]["previous_close"] == 25.46
    assert second["quotes"][0]["previous_close"] == 25.40


def test_valuation_trade_date_comes_from_quotes_not_later_ledger_event(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )
    _record_latest_stock_holding(
        db,
        timestamp="2026-07-10T09:30:00+08:00",
    )
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-07-12T10:00:00+08:00",
        amount=1000.0,
    )

    snapshot = build_current_valuation_snapshot(db, persist=True)

    assert snapshot["as_of"] == "2026-07-12T10:00:00+08:00"
    assert snapshot["trade_date"] == "2026-07-10"


def test_valuation_snapshot_freezes_confirmed_same_day_close():
    class FakeDb:
        close = 24.58

        def list_latest_quotes_sync(self):
            return [
                {
                    "id": 1,
                    "symbol": "603659",
                    "asset_type": "stock",
                    "price": 24.6,
                    "quote_timestamp": "2026-07-10T14:57:03+08:00",
                }
            ]

        def list_quote_snapshots_sync(self):
            return []

        def get_ledger_entries_sync(self, limit=500, offset=0):
            quote_symbol = str(self.list_latest_quotes_sync()[0]["symbol"])
            return [_holding_row(quote_symbol)][offset : offset + limit]

        def get_market_bar_on_date_sync(self, symbol, trade_date, *, instrument_type):
            assert symbol == "603659"
            assert trade_date == "2026-07-10"
            assert instrument_type == "stock"
            return {"close": self.close, "source": "market_bars"}

        def get_latest_market_bar_before_date_sync(
            self, symbol, trade_date, *, instrument_type
        ):
            assert instrument_type == "stock"
            return {"close": 25.46, "trade_date": "2026-07-09"}

    db = FakeDb()
    first = build_current_valuation_snapshot(
        db,
        persist=False,
        now=_valuation_now(),
    )
    db.close = 24.57
    second = build_current_valuation_snapshot(
        db,
        persist=False,
        now=_valuation_now(),
    )

    assert first["quotes"][0]["observed_price"] == 24.6
    assert first["quotes"][0]["price"] == 24.58
    assert first["quotes"][0]["observed_timestamp"] == ("2026-07-10T14:57:03+08:00")
    assert first["quotes"][0]["quote_timestamp"] == ("2026-07-10T15:00:00+08:00")
    assert first["quotes"][0]["quote_source"] == "market_bar_close"
    assert first["quotes"][0]["quote_status"] == "confirmed"
    assert first["quotes"][0]["valuation_price_source"] == "market_bar_close"
    assert first["as_of"] == "2026-07-10T15:00:00+08:00"
    assert first["snapshot_id"] != second["snapshot_id"]


def test_valuation_snapshot_does_not_treat_intraday_bar_as_confirmed_close():
    class FakeDb:
        def list_latest_quotes_sync(self):
            return [
                {
                    "id": 1,
                    "symbol": "600001",
                    "asset_type": "stock",
                    "price": 24.6,
                    "quote_timestamp": "2026-07-10T14:57:03+08:00",
                    "quote_source": "tushare_realtime_quote",
                }
            ]

        def get_ledger_entries_sync(self, limit=500, offset=0):
            return [_holding_row("600001")][offset : offset + limit]

        def get_market_bar_on_date_sync(self, symbol, trade_date, *, instrument_type):
            assert instrument_type == "stock"
            raise AssertionError("an intraday bar is not a confirmed closing price")

        def get_latest_market_bar_before_date_sync(
            self, symbol, trade_date, *, instrument_type
        ):
            assert instrument_type == "stock"
            return {"close": 25.46, "trade_date": "2026-07-09"}

    snapshot = build_current_valuation_snapshot(
        FakeDb(),
        persist=False,
        now=_valuation_now(hour=14, minute=58),
    )
    quote = snapshot["quotes"][0]

    assert snapshot["status"] == "complete"
    assert quote["price"] == 24.6
    assert quote["quote_timestamp"] == "2026-07-10T14:57:03+08:00"
    assert quote["quote_source"] == "tushare_realtime_quote"
    assert quote["previous_close"] == 25.46
    assert quote["previous_close_date"] == "2026-07-09"


def test_valuation_snapshot_rejects_same_day_quote_after_valuation_clock():
    class FakeDb:
        def list_latest_quotes_sync(self):
            return [
                {
                    "id": 1,
                    "symbol": "600001",
                    "asset_type": "stock",
                    "price": 24.6,
                    "quote_timestamp": "2026-07-10T14:10:00+08:00",
                    "quote_source": "tushare_realtime_quote",
                }
            ]

        def get_ledger_entries_sync(self, limit=500, offset=0):
            return [_holding_row("600001")][offset : offset + limit]

        def get_latest_market_bar_before_date_sync(
            self, symbol, trade_date, *, instrument_type
        ):
            assert instrument_type == "stock"
            return {"close": 25.46, "trade_date": "2026-07-09"}

    snapshot = build_current_valuation_snapshot(
        FakeDb(),
        persist=False,
        now=_valuation_now(hour=14, minute=0),
    )
    quote = snapshot["quotes"][0]

    assert snapshot["status"] == "degraded"
    assert quote["quote_status"] == "stale"
    assert quote["stale_reason"] == "quote_timestamp_after_valuation_clock"


def test_valuation_loader_prefers_bounded_quote_selection_candidates() -> None:
    class CandidateDb:
        def list_quote_selection_candidates_sync(self):
            return [{"symbol": "603659", "price": 24.6}]

        def list_latest_quotes_sync(self):
            raise AssertionError("materialized quotes must not be loaded separately")

        def list_quote_snapshots_sync(self):
            raise AssertionError("the append-only quote history must not be scanned")

    assert load_persisted_quote_rows(CandidateDb()) == [
        {"symbol": "603659", "price": 24.6}
    ]


def test_valuation_snapshot_keeps_unconfirmed_fund_estimate_non_authoritative(
    tmp_path,
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_latest_quote_sync(
        symbol="019999",
        asset_type="fund",
        price=2.2527,
        quote_timestamp="2026-07-10T14:57:03+08:00",
        quote_source="eastmoney_fund_estimate",
        provider_name="akshare",
        quote_status="live",
    )
    _record_holding(db, "019999", asset_class="fund")

    snapshot = build_current_valuation_snapshot(db, persist=False)
    quote = snapshot["quotes"][0]

    assert snapshot["status"] == "degraded"
    assert quote["price"] == 2.2527
    assert quote["quote_status"] == "confirmed_nav_missing"
    assert quote["observed_quote_status"] == "live"
    assert quote["stale_reason"] == "confirmed_fund_nav_missing_estimate_only"
    assert quote["valuation_evidence_status"] == "unconfirmed_estimate"
    assert snapshot["metadata"]["provider_fetch_used"] is False


def test_valuation_snapshot_separates_stock_and_fund_lanes_under_one_identity():
    class MixedAssetDb:
        def list_latest_quotes_sync(self):
            return [
                {
                    "symbol": "600001",
                    "asset_type": "stock",
                    "price": 24.6,
                    "quote_timestamp": "2026-07-10T14:57:03+08:00",
                    "quote_status": "live",
                    "quote_source": "tushare_realtime_quote",
                },
                {
                    "symbol": "019999",
                    "asset_type": "fund",
                    "price": 2.2527,
                    "quote_timestamp": "2026-07-10T14:58:03+08:00",
                    "quote_status": "live",
                    "quote_source": "sina_fund_estimate",
                },
            ]

        def get_ledger_entries_sync(self, limit=500, offset=0):
            rows = [
                _holding_row("600001", entry_id=1),
                _holding_row("019999", asset_class="fund", entry_id=2),
            ]
            return rows[offset : offset + limit]

        def get_latest_market_bar_before_date_sync(
            self, symbol, trade_date, *, instrument_type
        ):
            assert trade_date == "2026-07-10"
            assert instrument_type == (
                "stock" if symbol == "600001" else "open_end_fund"
            )
            return {
                "close": 24.0 if symbol == "600001" else 2.2,
                "trade_date": "2026-07-09",
            }

    snapshot = build_current_valuation_snapshot(
        MixedAssetDb(),
        persist=False,
        now=_valuation_now(),
    )

    assert snapshot["status"] == "degraded"
    assert snapshot["snapshot_id"].startswith("valuation-")
    assert snapshot["valuation_lanes"] == [
        {
            "asset_class": "stock",
            "status": "complete",
            "quote_count": 1,
            "complete_quote_count": 1,
            "review_required_quote_count": 0,
            "blocker_statuses": [],
        },
        {
            "asset_class": "fund",
            "status": "degraded",
            "quote_count": 1,
            "complete_quote_count": 0,
            "review_required_quote_count": 1,
            "blocker_statuses": ["confirmed_nav_missing"],
        },
    ]


def test_unheld_fund_estimate_does_not_degrade_stock_account_valuation(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_daily_close_snapshot_sync(
        symbol="600001",
        asset_class="stock",
        trade_date="2026-07-09",
        close_price=24.0,
        source="test_close",
    )
    db.save_quote_snapshot_sync(
        symbol="600001",
        asset_class="stock",
        price=24.6,
        volume=1000,
        timestamp="2026-07-10T14:57:03+08:00",
        quote_status="confirmed",
    )
    db.save_quote_snapshot_sync(
        symbol="019999",
        asset_class="fund",
        price=2.2527,
        volume=None,
        timestamp="2026-07-10T14:58:03+08:00",
        quote_source="sina_fund_estimate",
        quote_status="live",
    )
    _record_holding(db, "600001")

    snapshot = build_current_valuation_snapshot(
        db,
        persist=False,
        now=_valuation_now(),
    )

    assert snapshot["status"] == "complete"
    assert [quote["symbol"] for quote in snapshot["quotes"]] == ["600001"]
    assert snapshot["metadata"]["current_position_count"] == 1
    assert snapshot["valuation_lanes"][0]["status"] == "complete"
    assert snapshot["valuation_lanes"][1]["status"] == "not_applicable"


def test_closed_fund_quote_is_excluded_from_current_valuation_scope(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_latest_quote_sync(
        symbol="019999",
        asset_type="fund",
        price=2.2527,
        quote_timestamp="2026-07-10T14:58:03+08:00",
        quote_source="sina_fund_estimate",
        quote_status="live",
    )
    _record_holding(db, "019999", asset_class="fund")
    db.insert_ledger_entry_sync(
        entry_type="trade_sell",
        timestamp="2026-07-10T10:30:00+08:00",
        symbol="019999",
        direction="sell",
        quantity=1.0,
        price=1.0,
        asset_class="fund",
    )

    snapshot = build_current_valuation_snapshot(db, persist=False)

    assert snapshot["status"] == "complete"
    assert snapshot["quotes"] == []
    assert snapshot["metadata"]["current_position_count"] == 0
    assert all(
        lane["status"] == "not_applicable" for lane in snapshot["valuation_lanes"]
    )


def test_open_holding_without_quote_is_explicitly_missing(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _record_holding(db, "019999", asset_class="fund")

    snapshot = build_current_valuation_snapshot(db, persist=False)

    assert snapshot["status"] == "missing"
    assert snapshot["quotes"] == [
        {
            "symbol": "019999",
            "asset_type": "fund",
            "quote_status": "missing",
            "stale_reason": "holding_quote_missing",
            "valuation_baseline_status": "missing",
            "valuation_evidence_status": "missing",
        }
    ]
    assert snapshot["valuation_lanes"][1]["blocker_statuses"] == [
        "missing",
        "valuation_baseline_missing",
    ]


def test_valuation_snapshot_preserves_explicit_etf_lane():
    class OtherAssetDb:
        def list_latest_quotes_sync(self):
            return [
                {
                    "symbol": "510300",
                    "asset_type": "etf",
                    "price": 4.1,
                    "quote_timestamp": "2026-07-10T14:57:03+08:00",
                    "quote_status": "confirmed",
                }
            ]

        def get_ledger_entries_sync(self, limit=500, offset=0):
            return [_holding_row("510300", asset_class="etf")][offset : offset + limit]

        def get_latest_market_bar_before_date_sync(
            self, symbol, trade_date, *, instrument_type
        ):
            assert instrument_type == "etf"
            return {"close": 4.0, "trade_date": "2026-07-09"}

    snapshot = build_current_valuation_snapshot(
        OtherAssetDb(),
        persist=False,
        now=_valuation_now(),
    )

    assert snapshot["status"] == "complete"
    assert [lane["asset_class"] for lane in snapshot["valuation_lanes"]] == [
        "stock",
        "fund",
        "etf",
    ]
    assert snapshot["valuation_lanes"][0]["status"] == "not_applicable"
    assert snapshot["valuation_lanes"][1]["status"] == "not_applicable"
    assert snapshot["valuation_lanes"][2]["status"] == "complete"


def test_valuation_snapshot_does_not_treat_legacy_fund_quote_as_etf():
    class LegacyFundQuoteDb:
        def list_latest_quotes_sync(self):
            return [
                {
                    "symbol": "510300",
                    "asset_type": "fund",
                    "price": 4.1,
                    "quote_timestamp": "2026-07-10T14:57:03+08:00",
                    "quote_status": "confirmed",
                }
            ]

        def get_ledger_entries_sync(self, limit=500, offset=0):
            return [_holding_row("510300", asset_class="etf")][offset : offset + limit]

    snapshot = build_current_valuation_snapshot(
        LegacyFundQuoteDb(),
        persist=False,
        now=_valuation_now(),
    )

    assert snapshot["status"] == "missing"
    assert snapshot["quotes"] == [
        {
            "symbol": "510300",
            "asset_type": "etf",
            "quote_status": "missing",
            "stale_reason": "holding_quote_missing",
            "valuation_baseline_status": "missing",
            "valuation_evidence_status": "missing",
        }
    ]
    assert snapshot["valuation_lanes"][2]["status"] == "missing"


def test_current_valuation_degrades_confirmed_quote_after_expected_session():
    class StaleQuoteDb:
        def list_latest_quotes_sync(self):
            return [
                {
                    "symbol": "600001",
                    "asset_type": "stock",
                    "price": 24.6,
                    "quote_timestamp": "2026-09-03T15:00:00+08:00",
                    "quote_status": "confirmed",
                }
            ]

        def get_ledger_entries_sync(self, limit=500, offset=0):
            return [
                _holding_row(
                    "600001",
                    timestamp="2026-09-03T09:30:00+08:00",
                )
            ][offset : offset + limit]

        def get_latest_market_bar_before_date_sync(
            self, symbol, trade_date, *, instrument_type
        ):
            assert instrument_type == "stock"
            return {"close": 24.0, "trade_date": "2026-09-02"}

    db = StaleQuoteDb()
    same_session = build_current_valuation_snapshot(
        db,
        now=datetime(2026, 9, 3, 16, 0, tzinfo=_SHANGHAI_TZ),
    )
    next_session = build_current_valuation_snapshot(
        db,
        now=datetime(2026, 9, 4, 10, 0, tzinfo=_SHANGHAI_TZ),
    )

    assert same_session["status"] == "complete"
    assert next_session["status"] == "degraded"
    assert next_session["snapshot_id"] != same_session["snapshot_id"]
    assert next_session["quotes"][0]["price"] == 24.6
    assert next_session["quotes"][0]["quote_status"] == "stale"
    assert (
        next_session["quotes"][0]["stale_reason"] == "quote_older_than_expected_session"
    )
    assert next_session["metadata"]["valuation_expected_date"] == "2026-09-04"
    assert next_session["valuation_lanes"][0]["blocker_statuses"] == ["stale"]


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 9, 5, 12, 0, tzinfo=_SHANGHAI_TZ),
        datetime(2026, 9, 7, 9, 0, tzinfo=_SHANGHAI_TZ),
    ],
)
def test_current_valuation_accepts_previous_session_before_next_open(now):
    class PreviousSessionDb:
        def list_latest_quotes_sync(self):
            return [
                {
                    "symbol": "600001",
                    "asset_type": "stock",
                    "price": 24.6,
                    "quote_timestamp": "2026-09-04T15:00:00+08:00",
                    "quote_status": "confirmed",
                }
            ]

        def get_ledger_entries_sync(self, limit=500, offset=0):
            return [
                _holding_row(
                    "600001",
                    timestamp="2026-09-04T09:30:00+08:00",
                )
            ][offset : offset + limit]

        def get_latest_market_bar_before_date_sync(
            self, symbol, trade_date, *, instrument_type
        ):
            assert instrument_type == "stock"
            return {"close": 24.0, "trade_date": "2026-09-03"}

    snapshot = build_current_valuation_snapshot(PreviousSessionDb(), now=now)

    assert snapshot["status"] == "complete"
    assert snapshot["metadata"]["valuation_expected_date"] == "2026-09-04"
    assert snapshot["quotes"][0]["quote_status"] == "confirmed"


def test_portfolio_snapshot_contract_preserves_valuation_lanes() -> None:
    from server.models import PortfolioSnapshot

    lane = {
        "asset_class": "stock",
        "status": "complete",
        "quote_count": 1,
        "complete_quote_count": 1,
        "review_required_quote_count": 0,
        "blocker_statuses": [],
    }

    snapshot = PortfolioSnapshot(
        cash=100.0,
        total_equity=100.0,
        positions=[],
        allocation=[],
        valuation_lanes=[lane],
    )

    assert snapshot.model_dump()["valuation_lanes"] == [lane]


def test_valuation_snapshot_keeps_sina_fund_estimate_non_authoritative(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_latest_quote_sync(
        symbol="019999",
        asset_type="fund",
        price=2.2527,
        quote_timestamp="2026-07-10T14:57:03+08:00",
        quote_source="sina_fund_estimate",
        provider_name="sina",
        quote_status="live",
    )
    _record_holding(db, "019999", asset_class="fund")

    snapshot = build_current_valuation_snapshot(db, persist=False)
    quote = snapshot["quotes"][0]

    assert snapshot["status"] == "degraded"
    assert quote["price"] == 2.2527
    assert quote["quote_status"] == "confirmed_nav_missing"
    assert quote["valuation_price_source"] == "sina_fund_estimate"
    assert quote["valuation_evidence_status"] == "unconfirmed_estimate"


def test_valuation_snapshot_does_not_override_confirmed_fund_nav_with_market_bar():
    class FakeDb:
        def list_latest_quotes_sync(self):
            return [
                {
                    "id": 1,
                    "symbol": "019999",
                    "asset_type": "fund",
                    "price": 2.2411,
                    "quote_timestamp": "2026-07-10T20:30:00+08:00",
                    "quote_source": "eastmoney_fund_page",
                    "provider_status": "live",
                    "quote_status": "confirmed",
                    "nav_date": "2026-07-10",
                }
            ]

        def list_quote_snapshots_sync(self):
            return []

        def get_ledger_entries_sync(self, limit=500, offset=0):
            return [_holding_row("019999", asset_class="fund")][offset : offset + limit]

        def get_market_bar_on_date_sync(self, symbol, trade_date, *, instrument_type):
            raise AssertionError("open-end funds must not consume market bars")

        def get_latest_market_bar_before_date_sync(
            self, symbol, trade_date, *, instrument_type
        ):
            assert instrument_type == "open_end_fund"
            return {"close": 2.22, "trade_date": "2026-07-09"}

    snapshot = build_current_valuation_snapshot(
        FakeDb(),
        persist=False,
        now=_valuation_now(hour=20, minute=31),
    )
    quote = snapshot["quotes"][0]

    assert snapshot["status"] == "complete"
    assert quote["price"] == 2.2411
    assert quote["quote_source"] == "eastmoney_fund_page"
    assert quote["quote_status"] == "confirmed"
    assert "stale_reason" not in quote
    assert "valuation_evidence_status" not in quote


def test_valuation_snapshot_does_not_promote_fund_estimate_from_market_bar():
    class FakeDb:
        def list_latest_quotes_sync(self):
            return [
                {
                    "id": 1,
                    "symbol": "019999",
                    "asset_type": "fund",
                    "price": 2.2527,
                    "quote_timestamp": "2026-07-10T14:57:03+08:00",
                    "quote_source": "eastmoney_fund_estimate",
                    "quote_status": "live",
                }
            ]

        def get_ledger_entries_sync(self, limit=500, offset=0):
            return [_holding_row("019999", asset_class="fund")][offset : offset + limit]

        def get_market_bar_on_date_sync(self, symbol, trade_date, *, instrument_type):
            raise AssertionError("open-end funds must not consume market bars")

        def get_latest_market_bar_before_date_sync(
            self, symbol, trade_date, *, instrument_type
        ):
            assert instrument_type == "open_end_fund"
            return {"close": 2.22, "trade_date": "2026-07-09"}

    snapshot = build_current_valuation_snapshot(FakeDb(), persist=False)
    quote = snapshot["quotes"][0]

    assert snapshot["status"] == "degraded"
    assert quote["price"] == 2.2527
    assert quote["quote_source"] == "eastmoney_fund_estimate"
    assert quote["quote_status"] == "confirmed_nav_missing"
    assert quote["valuation_evidence_status"] == "unconfirmed_estimate"


def test_valuation_snapshot_orders_mixed_timezone_timestamps_by_instant(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T15:00:00+08:00",
        fetch_run_id="run-earlier",
    )
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.7,
        volume=1200.0,
        timestamp="2026-07-10T08:00:00Z",
        fetch_run_id="run-later",
    )
    _record_latest_stock_holding(db)

    snapshot = build_current_valuation_snapshot(db, persist=True)

    assert snapshot["quotes"][0]["price"] == 24.7
    assert snapshot["as_of"] == "2026-07-10T16:00:00+08:00"
    assert snapshot["metadata"]["ingestion_run_ids"] == ["run-later"]


def test_cash_only_valuation_is_complete_without_persisted_quotes(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    snapshot = build_current_valuation_snapshot(db, persist=True)

    assert snapshot["status"] == "complete"
    assert snapshot["quotes"] == []
    assert snapshot["metadata"]["current_position_count"] == 0
    assert snapshot["metadata"]["runtime_cache_used"] is False


def test_legacy_valuation_publisher_name_uses_atomic_publication(tmp_path):
    from server.persistence.financial_facts_valuation_composition import (
        build_and_persist_current_valuation_snapshot,
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )

    snapshot = build_and_persist_current_valuation_snapshot(db)
    publication = db.get_runtime_control_sync("valuation_snapshot_publication")

    assert publication is not None
    assert publication["status"] == "ready"
    assert publication["snapshot_id"] == snapshot["snapshot_id"]


def test_valuation_snapshot_fails_closed_for_legacy_invalid_quote_timestamp(
    tmp_path,
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_latest_quote_sync(
        symbol="603659",
        asset_type="stock",
        price=24.6,
        previous_close=24.0,
        quote_timestamp="not-a-date",
    )
    _record_latest_stock_holding(db)

    snapshot = db.publish_current_valuation_snapshot_sync()

    assert snapshot["status"] == "missing"
    assert snapshot["as_of"] == "2026-07-10T09:30:00+08:00"
    assert snapshot["trade_date"] == "2026-07-10"
    assert snapshot["quotes"][0]["quote_status"] == "error"
    assert snapshot["quotes"][0]["stale_reason"] == "invalid_quote_timestamp"
    assert snapshot["quotes"][0]["valuation_evidence_status"] == "invalid_timestamp"


def test_valuation_snapshot_routes_separate_create_and_read(monkeypatch, tmp_path):
    from server.routes import portfolio as portfolio_routes

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )
    _record_latest_stock_holding(db)
    monkeypatch.setattr(
        "server.dependencies.get_app_state",
        lambda: SimpleNamespace(db=db),
    )
    router = portfolio_routes.create_router()
    create_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/portfolio/valuation-snapshots"
        and "POST" in route.methods
    )

    created = asyncio.run(create_route.endpoint())
    read_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/portfolio/valuation-snapshots/{snapshot_id}"
    )
    read = asyncio.run(read_route.endpoint(created["snapshot_id"]))

    assert read["snapshot_id"] == created["snapshot_id"]
    assert read["quotes"] == created["quotes"]
    assert read["valuation_lanes"] == created["valuation_lanes"]
    assert read["metadata"] == created["metadata"]


def test_existing_persisted_snapshot_rebuilds_lanes_without_identity_migration(
    tmp_path,
):
    from server.services.valuation_snapshot import valuation_snapshot_from_row

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="600001",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )
    _record_holding(db, "600001")

    first = db.publish_current_valuation_snapshot_sync()
    repeated = db.publish_current_valuation_snapshot_sync()
    stored = db.get_valuation_snapshot_sync(first["snapshot_id"])

    assert repeated["snapshot_id"] == first["snapshot_id"]
    assert stored is not None
    assert "valuation_lanes" not in json.loads(stored["metadata_json"])
    assert (
        valuation_snapshot_from_row(stored)["valuation_lanes"]
        == first["valuation_lanes"]
    )


def test_successful_quote_run_publishes_replayable_snapshot(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    run_id = "run-publish-snapshot"
    db.create_quote_fetch_run(
        run_id=run_id,
        started_at="2026-07-10T14:56:00+08:00",
        trigger="test",
        provider="test",
        asset_type="stock",
        symbol_count=1,
        status="running",
    )
    _record_holding(db, "600001")
    db.persist_quote_ingestion_sync(
        QuoteIngestionCommand(
            symbol="600001",
            asset_type="stock",
            price=24.6,
            volume=1000.0,
            quote_timestamp="2026-07-10T14:57:03+08:00",
            fetch_run_id=run_id,
        )
    )

    finished = db.finish_quote_fetch_run(
        run_id=run_id,
        finished_at="2026-07-10T14:58:00+08:00",
        status="success",
        success_count=1,
        metadata={"trigger": "test"},
    )

    metadata = json.loads(finished["metadata_json"])
    snapshot_id = metadata["valuation_snapshot_id"]
    stored = db.get_valuation_snapshot_sync(snapshot_id)
    publication = db.get_runtime_control_sync("valuation_snapshot_publication")
    assert finished["status"] == "success"
    assert stored is not None
    assert publication["status"] == "ready"
    assert publication["snapshot_id"] == snapshot_id
    assert json.loads(stored["quotes_json"])[0]["fetch_run_id"] == run_id


def test_quote_run_fails_closed_when_success_has_no_staged_evidence(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    run_id = "run-publication-failure"
    db.create_quote_fetch_run(
        run_id=run_id,
        started_at="2026-07-10T14:56:00+08:00",
        trigger="test",
        provider="test",
        asset_type="stock",
        symbol_count=1,
        status="running",
    )
    finished = db.finish_quote_fetch_run(
        run_id=run_id,
        finished_at="2026-07-10T14:58:00+08:00",
        status="success",
        success_count=1,
        metadata={"trigger": "test"},
    )

    assert finished["status"] == "failed"
    assert "valuation snapshot publication failed" in finished["error_message"]
    assert (
        json.loads(finished["metadata_json"])["valuation_snapshot_publication"]
        == "failed"
    )


def test_ledger_commit_publishes_new_replayable_snapshot(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )

    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-07-10T09:00:00+08:00",
        amount=10000.0,
        asset_class="cash",
    )

    current = build_current_valuation_snapshot(db, persist=False)
    stored = db.get_valuation_snapshot_sync(current["snapshot_id"])
    assert stored is not None
    assert stored["ledger_cutoff_id"] == 1


def test_financial_read_fails_closed_when_facts_are_newer_than_publication(tmp_path):
    from server.routes.portfolio import _current_valuation_snapshot

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )
    _record_latest_stock_holding(db)
    published = db.publish_current_valuation_snapshot_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.7,
        volume=1200.0,
        timestamp="2026-07-10T14:58:03+08:00",
    )

    with pytest.raises(HTTPException) as exc_info:
        _current_valuation_snapshot(SimpleNamespace(db=db))

    assert exc_info.value.status_code == 503
    assert db.get_valuation_snapshot_sync(published["snapshot_id"]) is not None


def test_market_context_index_does_not_invalidate_account_valuation(tmp_path):
    from server.routes.portfolio import _current_valuation_snapshot

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )
    _record_latest_stock_holding(db)
    published = db.publish_current_valuation_snapshot_sync()

    db.upsert_latest_quote_sync(
        symbol="000001",
        asset_type="index",
        price=3524.3,
        volume=0.0,
        quote_timestamp="2026-07-10T14:58:03+08:00",
        quote_source="fixture",
        provider_name="fixture",
        provider_status="live",
        quote_status="live",
        captured_at="2026-07-10T14:58:03+08:00",
        captured_reason="scheduler_market_index_sync",
    )

    current = _current_valuation_snapshot(SimpleNamespace(db=db))

    assert current["snapshot_id"] == published["snapshot_id"]
    assert current["valuation_policy"] == "karkinos.persisted_valuation.v5"
    assert [quote["symbol"] for quote in current["quotes"]] == ["603659"]


@pytest.mark.parametrize("publication", [None, {"status": "failed"}])
def test_financial_read_fails_closed_without_ready_publication(tmp_path, publication):
    from server.routes.portfolio import _current_valuation_snapshot

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="603659",
        asset_class="stock",
        price=24.6,
        volume=1000.0,
        timestamp="2026-07-10T14:57:03+08:00",
    )
    if publication is not None:
        db.set_runtime_control_sync("valuation_snapshot_publication", publication)

    with pytest.raises(HTTPException) as exc_info:
        _current_valuation_snapshot(SimpleNamespace(db=db))

    assert exc_info.value.status_code == 503
