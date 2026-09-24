"""Receipt-bound, read-only observations for frozen candidate reports."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
from fastapi.routing import APIRoute

from analytics.dataset_snapshot import build_backtest_dataset_snapshot
from core.types import AssetClass, Symbol
from data.handler import DataHandler
from data.market_daily_store import verify_market_daily_receipt_on_connection
from data.research_market_data import (
    load_research_market_frames,
    research_market_binding,
)
from data.store import DataStore
from server.contracts.content_identity import content_fingerprint
from server.routes import decision as decision_routes
from server.services import daily_decision_report
from server.services.daily_candidate_outcomes import (
    evaluate_daily_candidate_outcomes,
)


class _DB:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get_market_calendar_snapshot_sync(
        self, *, exchange: str, year: int
    ) -> dict[str, Any]:
        assert exchange == "SSE"
        day = date(year, 1, 1)
        days = []
        while day.year == year:
            days.append({"date": day.isoformat(), "is_trading_day": day.weekday() < 5})
            day += timedelta(days=1)
        return {
            "exchange": exchange,
            "year": year,
            "days_json": json.dumps(days),
            "trading_day_count": sum(item["is_trading_day"] for item in days),
            "closed_day_count": sum(not item["is_trading_day"] for item in days),
            "source_fingerprint": "a" * 64,
            "verification_source_fingerprint": "a" * 64,
            "official_source_fingerprint": "b" * 64,
            "official_source_url": "https://example.test/calendar",
            "official_verified_at": f"{year}-01-01T00:00:00+08:00",
            "official_verified_by": "fixture",
            "official_verification_status": "verified",
        }


def _bar(day: str, *, open_price: float, close: float) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "600869",
                "timestamp": datetime.fromisoformat(day + "T15:00:00"),
                "open": open_price,
                "high": max(open_price, close),
                "low": min(open_price, close),
                "close": close,
                "volume": 1000,
                "amount": 10000,
            }
        ]
    )


def _formal_report(anchor_receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_date": "2026-09-23",
        "candidates": [
            {
                "kind": "formal_signal",
                "decision_date": "2026-09-23",
                "frozen_market_date": "2026-09-22",
                "symbol": "600869",
                "direction": "buy",
                "scan_run_id": "scan:one",
                "source_ref": "scan:one:signal:41",
                "frozen_price": 9.5,
                "report_authoritative": True,
            }
        ],
        "blocked_signals": [],
        "research_previews": [],
        "scans": [
            {
                "run_id": "scan:one",
                "status": "completed",
                "integrity_valid": True,
                "market_date": "2026-09-22",
                "receipt_fingerprints": [anchor_receipt["receipt_fingerprint"]],
            }
        ],
    }


def _store(tmp_path: Path) -> tuple[_DB, DataStore, dict[str, Any]]:
    app_path = tmp_path / "app.db"
    sqlite3.connect(app_path).close()
    store = DataStore(tmp_path)
    anchor = store.ingest_market_daily_batch(
        trade_date="2026-09-22",
        provider_name="tushare",
        bars=_bar("2026-09-22", open_price=9, close=9.5),
    )
    return _DB(app_path), store, anchor


def test_formal_candidate_uses_next_session_open_and_same_source_receipts(
    tmp_path: Path,
) -> None:
    db, store, anchor = _store(tmp_path)
    entry = store.ingest_market_daily_batch(
        trade_date="2026-09-24",
        provider_name="tushare",
        bars=_bar("2026-09-24", open_price=10, close=11),
    )

    result = evaluate_daily_candidate_outcomes(
        db, _formal_report(anchor), as_of=date(2026, 9, 24)
    )

    candidate = result["items"][0]
    first = candidate["horizons"]["T+1"]
    assert candidate["anchor"]["receipt_fingerprint"] == anchor["receipt_fingerprint"]
    assert first["status"] == "observed"
    assert first["price_move_pct"] == 10
    assert first["entry_receipt_fingerprint"] == entry["receipt_fingerprint"]
    assert first["horizon_receipt_fingerprint"] == entry["receipt_fingerprint"]
    assert first["available_at_verified"] is False
    assert candidate["horizons"]["T+5"]["status"] == "pending"
    assert result["formal_authoritative_directional_hits"]["T+1"] == {
        "observed_count": 1,
        "directional_hit_count": 1,
        "directional_hit_rate": 1.0,
    }
    assert result["provider_contacted"] is False
    assert result["authorizes_execution"] is False

    before_next_session = evaluate_daily_candidate_outcomes(
        db, _formal_report(anchor), as_of=date(2026, 9, 23)
    )["items"][0]["horizons"]["T+1"]
    assert before_next_session == {
        "status": "pending",
        "reason_code": "horizon_session_not_reached",
        "session_date": "2026-09-24",
    }


def test_other_provider_or_revised_anchor_cannot_fill_observation(
    tmp_path: Path,
) -> None:
    db, store, anchor = _store(tmp_path)
    store.ingest_market_daily_batch(
        trade_date="2026-09-24",
        provider_name="other",
        bars=_bar("2026-09-24", open_price=10, close=11),
    )
    report = _formal_report(anchor)
    first = evaluate_daily_candidate_outcomes(db, report, as_of=date(2026, 9, 24))[
        "items"
    ][0]["horizons"]["T+1"]
    assert first == {"status": "unavailable", "reason_code": "horizon_receipt_missing"}

    with sqlite3.connect(tmp_path / "meta.db") as conn:
        conn.execute(
            "UPDATE market_bars_v2 SET close=99 "
            "WHERE symbol='600869' AND substr(timestamp,1,10)='2026-09-22'"
        )
    candidate = evaluate_daily_candidate_outcomes(db, report, as_of=date(2026, 9, 24))[
        "items"
    ][0]
    assert candidate["anchor_status"] == "unavailable"
    assert candidate["reason_code"] == "daily_receipt_unverified"


def test_verified_legacy_receipt_without_price_basis_is_not_used_as_anchor(
    tmp_path: Path,
) -> None:
    db, _, anchor = _store(tmp_path)
    legacy = dict(anchor)
    legacy["schema_version"] = "karkinos.market_daily_ingestion_receipt.v2"
    legacy.pop("units", None)
    legacy.pop("price_basis", None)
    legacy.pop("receipt_fingerprint")
    legacy["receipt_fingerprint"] = "sha256:" + content_fingerprint(legacy)
    with sqlite3.connect(tmp_path / "meta.db") as conn:
        conn.execute(
            "UPDATE market_daily_ingestion_receipts SET receipt_json=? "
            "WHERE trade_date='2026-09-22' AND provider_name='tushare'",
            (json.dumps(legacy),),
        )
        assert verify_market_daily_receipt_on_connection(conn, legacy)

    candidate = evaluate_daily_candidate_outcomes(
        db, _formal_report(legacy), as_of=date(2026, 9, 24)
    )["items"][0]

    assert candidate["anchor_status"] == "unavailable"
    assert candidate["reason_code"] == "historical_price_basis_unverified"


def test_blocked_signal_can_be_observed_without_affecting_formal_hit_rate(
    tmp_path: Path,
) -> None:
    db, store, anchor = _store(tmp_path)
    store.ingest_market_daily_batch(
        trade_date="2026-09-24",
        provider_name="tushare",
        bars=_bar("2026-09-24", open_price=10, close=11),
    )
    report = _formal_report(anchor)
    report["blocked_signals"] = [
        {
            "kind": "account_blocked_signal",
            "decision_date": "2026-09-23",
            "frozen_market_date": "2026-09-22",
            "symbol": "600869",
            "scan_run_id": "scan:one",
            "source_ref": "scan:one:raw_signal:0",
            "frozen_price": 9.5,
            "source_bound": True,
            "report_authoritative": False,
        }
    ]

    result = evaluate_daily_candidate_outcomes(db, report, as_of=date(2026, 9, 24))

    assert result["items"][1]["horizons"]["T+1"]["status"] == "observed"
    assert result["formal_authoritative_directional_hits"]["T+1"]["observed_count"] == 1


def test_research_preview_without_source_bound_snapshot_stays_unavailable(
    tmp_path: Path,
) -> None:
    db, _, _ = _store(tmp_path)
    operation = {
        "kind": "research_preview",
        "market_date": "2026-09-22",
        "signal_date": "2026-09-22",
        "symbol": "600869",
        "operation": "buy_candidate",
        "source_ref": "selection:one:operation:0",
        "selection_id": "selection:one",
        "run_id": "research:one",
        "dataset_snapshot_id": "sha256:" + "a" * 64,
        "formula_fingerprint": "sha256:" + "b" * 64,
    }
    source_preview = {
        "operations": [
            {
                "symbol": "600869",
                "operation": "buy_candidate",
                "signal_date": "2026-09-22",
            }
        ]
    }
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            "CREATE TABLE backtest_results (id INTEGER PRIMARY KEY, metrics_json TEXT)"
        )
        conn.execute(
            "CREATE TABLE ai_shadow_research_candidates "
            "(run_id TEXT, candidate_id TEXT, candidate_result_id INTEGER, "
            "comparison_json TEXT)"
        )
        conn.execute(
            "INSERT INTO backtest_results VALUES (?, ?)",
            (
                7,
                json.dumps(
                    {
                        "dataset_snapshot": {
                            "snapshot_id": operation["dataset_snapshot_id"]
                        },
                        "normalized_research_operation_preview": source_preview,
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO ai_shadow_research_candidates VALUES (?, ?, ?, ?)",
            (
                "research:one",
                "candidate:one",
                7,
                json.dumps({"normalized_research_operation_preview": source_preview}),
            ),
        )
    report = {
        "report_date": "2026-09-22",
        "candidates": [],
        "blocked_signals": [],
        "scans": [],
        "research_previews": [
            {
                "run_id": "research:one",
                "selection_id": "selection:one",
                "status": "no_selection",
                "research_winner_candidate_id": "candidate:one",
                "dataset_snapshot_id": operation["dataset_snapshot_id"],
                "formula_fingerprint": operation["formula_fingerprint"],
                "operations": [operation],
            }
        ],
    }

    result = evaluate_daily_candidate_outcomes(db, report, as_of=date(2026, 9, 24))

    assert result["items"][0]["reason_code"] == "research_snapshot_source_unbound"


def test_source_bound_research_snapshot_can_observe_price_move(
    tmp_path: Path,
) -> None:
    db, store, anchor = _store(tmp_path)
    prior = store.ingest_market_daily_batch(
        trade_date="2026-09-21",
        provider_name="tushare",
        bars=_bar("2026-09-21", open_price=9, close=9),
    )
    entry = store.ingest_market_daily_batch(
        trade_date="2026-09-23",
        provider_name="tushare",
        bars=_bar("2026-09-23", open_price=10, close=11),
    )
    binding = research_market_binding([prior, anchor])
    frames = load_research_market_frames(
        tmp_path,
        binding=binding,
        symbols=["600869"],
        start_date="2026-09-21",
        end_date="2026-09-22",
    )
    snapshot = build_backtest_dataset_snapshot(
        start_date="2026-09-21",
        end_date="2026-09-22",
        configured_source=None,
        data_handlers={
            Symbol("600869"): DataHandler(
                frames["600869"],
                Symbol("600869"),
                asset_class=AssetClass.STOCK,
            )
        },
        store=store,
        source_names=[],
        market_data_binding=binding,
    )
    operation = {
        "kind": "research_preview",
        "market_date": "2026-09-22",
        "signal_date": "2026-09-22",
        "symbol": "600869",
        "operation": "buy_candidate",
        "source_ref": "selection:one:operation:0",
        "selection_id": "selection:one",
        "run_id": "research:one",
        "dataset_snapshot_id": snapshot["snapshot_id"],
        "formula_fingerprint": "sha256:" + "b" * 64,
    }
    source_preview = {
        "operations": [
            {
                "symbol": "600869",
                "operation": "buy_candidate",
                "signal_date": "2026-09-22",
            }
        ]
    }
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            "CREATE TABLE backtest_results (id INTEGER PRIMARY KEY, metrics_json TEXT)"
        )
        conn.execute(
            "CREATE TABLE ai_shadow_research_candidates "
            "(run_id TEXT, candidate_id TEXT, candidate_result_id INTEGER, "
            "comparison_json TEXT)"
        )
        conn.execute(
            "INSERT INTO backtest_results VALUES (?, ?)",
            (
                7,
                json.dumps(
                    {
                        "dataset_snapshot": snapshot,
                        "normalized_research_operation_preview": source_preview,
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO ai_shadow_research_candidates VALUES (?, ?, ?, ?)",
            (
                "research:one",
                "candidate:one",
                7,
                json.dumps({"normalized_research_operation_preview": source_preview}),
            ),
        )
    report = {
        "report_date": "2026-09-22",
        "candidates": [],
        "blocked_signals": [],
        "scans": [],
        "research_previews": [
            {
                "run_id": "research:one",
                "selection_id": "selection:one",
                "status": "no_selection",
                "research_winner_candidate_id": "candidate:one",
                "dataset_snapshot_id": snapshot["snapshot_id"],
                "formula_fingerprint": operation["formula_fingerprint"],
                "operations": [operation],
            }
        ],
    }

    result = evaluate_daily_candidate_outcomes(db, report, as_of=date(2026, 9, 24))

    candidate = result["items"][0]
    assert candidate["anchor"]["dataset_snapshot_id"] == snapshot["snapshot_id"]
    assert candidate["horizons"]["T+1"]["price_move_pct"] == 10
    assert (
        candidate["horizons"]["T+1"]["entry_receipt_fingerprint"]
        == entry["receipt_fingerprint"]
    )


def test_daily_report_detail_route_attaches_outcomes(
    tmp_path: Path, monkeypatch
) -> None:
    db, store, anchor = _store(tmp_path)
    store.ingest_market_daily_batch(
        trade_date="2026-09-24",
        provider_name="tushare",
        bars=_bar("2026-09-24", open_price=10, close=11),
    )
    monkeypatch.setattr(
        "server.dependencies.get_app_state", lambda: SimpleNamespace(db=db)
    )
    monkeypatch.setattr(
        daily_decision_report,
        "get_daily_decision_report",
        lambda _db, _date: _formal_report(anchor),
    )
    endpoint = next(
        route.endpoint
        for route in decision_routes.create_router().routes
        if isinstance(route, APIRoute)
        and route.path == "/api/decision/daily-reports/{report_date}"
    )

    result = asyncio.run(endpoint("2026-09-23"))

    assert result["report_date"] == "2026-09-23"
    assert (
        result["candidate_outcomes"]["schema_version"]
        == "karkinos.decision.candidate_outcomes.v1"
    )
    assert result["candidate_outcomes"]["items"][0]["source_ref"] == (
        "scan:one:signal:41"
    )
