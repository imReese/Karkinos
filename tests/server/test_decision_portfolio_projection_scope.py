from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.config import ServerConfig
from server.contracts.portfolio_cash_flows import CashFlowWrite
from server.db import AppDatabase
from server.dependencies import AppState, AppStateContextMiddleware
from server.services.decision_action_application import (
    batch_pre_trade_risk_evidence_gate,
)
from server.services.decision_candidate_market_evidence import (
    bind_candidate_market_evidence,
    candidate_market_evidence,
)
from server.services.decision_gate_evidence import data_freshness_evidence
from server.services.decision_portfolio_projection import (
    decision_portfolio_context,
    decision_symbols,
    market_data_summary,
    portfolio_state_summary,
)
from server.services.decision_workflow_projection import data_refresh_workflow_task


def _position(quantity: float, market_value: float):
    return SimpleNamespace(
        quantity=quantity,
        market_value=market_value,
        valuation_available=True,
    )


def _persisted_decision_state(tmp_path, *, with_quote=True) -> AppState:
    db = AppDatabase(tmp_path / "decision.db")
    db.init_sync()
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-10-16T09:00:00+08:00",
        amount=1000,
        asset_class="cash",
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-10-16T10:00:00+08:00",
        symbol="600001",
        direction="buy",
        quantity=100,
        price=1,
        asset_class="stock",
    )
    if with_quote:
        db.save_quote_snapshot_sync(
            symbol="600001",
            asset_class="stock",
            price=1,
            volume=1000,
            timestamp="2026-10-16T15:00:00+08:00",
            quote_source="deterministic_fixture",
            quote_status="confirmed",
        )
    db.publish_current_valuation_snapshot_sync(
        now=datetime.fromisoformat("2026-10-16T16:00:00+08:00")
    )
    state = AppState()
    state.db = db
    state.config = ServerConfig()
    return state


@pytest.mark.parametrize("through_http", [False, True])
def test_decision_context_keeps_published_ledger_when_a_deposit_commits(
    tmp_path, monkeypatch, through_http
) -> None:
    from server.projections import portfolio_application
    from server.routes import decision as decision_routes

    state = _persisted_decision_state(tmp_path)
    db = state.require_database()
    read_valuation = portfolio_application.current_valuation_snapshot
    captured_snapshot = None
    read_ledger = db.get_all_ledger_entries_sync
    ledger_reads = 0

    def counted_ledger():
        nonlocal ledger_reads
        ledger_reads += 1
        return read_ledger()

    def publish_concurrent_deposit(*args, **kwargs):
        nonlocal captured_snapshot
        captured_snapshot = read_valuation(*args, **kwargs)
        db.record_cash_flow_sync(
            CashFlowWrite(
                command_id="concurrent-deposit",
                operator_id="synthetic",
                timestamp="2026-10-16T15:30:00+08:00",
                amount=1000,
                flow_type="deposit",
            )
        )
        return captured_snapshot

    monkeypatch.setattr(db, "get_all_ledger_entries_sync", counted_ledger)
    monkeypatch.setattr(
        portfolio_application,
        "current_valuation_snapshot",
        publish_concurrent_deposit,
    )
    if through_http:
        app = FastAPI()
        app.add_middleware(AppStateContextMiddleware, app_state=state)
        app.include_router(decision_routes.create_router())
        with TestClient(app) as client:
            response = client.get("/api/decision/today")
        assert response.status_code == 200, response.text
        summary = response.json()["summary"]["portfolio"]
        context = {
            "authority": "persisted_valuation_snapshot",
            "valuation_snapshot": captured_snapshot,
        }
    else:
        context = decision_portfolio_context(state)
        summary = portfolio_state_summary(state, portfolio_context=context)
        assert float(context["portfolio"].cash) == 900
        assert ledger_reads == 1

    assert captured_snapshot is not None
    assert summary["cash"] == 900
    assert summary["valuation_snapshot_id"] == captured_snapshot["snapshot_id"]
    assert summary["ledger_cutoff_id"] == captured_snapshot["ledger_cutoff_id"] == 2
    assert max(row["id"] for row in read_ledger()) == 3

    context = bind_candidate_market_evidence(
        context, candidate_market_evidence(db, [], state=state)
    )
    gate = batch_pre_trade_risk_evidence_gate(
        db,
        portfolio_context=context,
        tasks=[],
        data_freshness_resolver=data_freshness_evidence,
    )
    assert gate["ready"] is False
    assert {item["code"] for item in gate["blockers"]} >= {
        "valuation_publication_snapshot_drift",
        "valuation_publication_ledger_cutoff_drift",
    }
    assert len(read_ledger()) == 3
    monkeypatch.setattr(
        portfolio_application, "current_valuation_snapshot", read_valuation
    )
    current = portfolio_state_summary(
        state, portfolio_context=decision_portfolio_context(state)
    )
    assert current["cash"] == 1900
    assert current["ledger_cutoff_id"] == 3


def test_decision_context_requires_a_published_snapshot(tmp_path) -> None:
    db = AppDatabase(tmp_path / "unpublished.db")
    db.init_sync()
    state = AppState()
    state.db = db
    state.config = ServerConfig()

    with pytest.raises(HTTPException) as error:
        decision_portfolio_context(state)

    assert error.value.status_code == 503


def test_decision_context_requires_the_published_ledger(tmp_path, monkeypatch) -> None:
    state = _persisted_decision_state(tmp_path)

    def unavailable():
        raise RuntimeError("synthetic ledger unavailable")

    monkeypatch.setattr(
        state.require_database(), "get_all_ledger_entries_sync", unavailable
    )

    with pytest.raises(HTTPException) as error:
        decision_portfolio_context(state)

    assert error.value.status_code == 503


def test_decision_context_missing_quote_still_blocks_valuation_and_risk(
    tmp_path,
) -> None:
    state = _persisted_decision_state(tmp_path, with_quote=False)
    db = state.require_database()
    context = decision_portfolio_context(state)
    summary = portfolio_state_summary(state, portfolio_context=context)
    tasks = [{"id": 1, "symbol": "600001", "asset_class": "stock"}]
    context = bind_candidate_market_evidence(
        context, candidate_market_evidence(db, tasks, state=state)
    )
    gate = batch_pre_trade_risk_evidence_gate(
        db,
        portfolio_context=context,
        tasks=tasks,
        data_freshness_resolver=data_freshness_evidence,
    )

    assert summary["status"] == "blocked"
    assert summary["total_equity"] is None
    assert context["quotes"]["600001"]["quote_status"] == "missing"
    assert context["quotes"]["600001"].get("price") is None
    assert context["candidate_quotes"] == {}
    assert gate["ready"] is False
    assert "candidate_market_data_not_complete" in {
        item["code"] for item in gate["blockers"]
    }


def test_portfolio_state_summary_excludes_closed_zero_quantity_positions():
    portfolio = SimpleNamespace(
        cash=500.0,
        valuation_status="complete",
        positions={
            "600001": _position(100.0, 1000.0),
            "600002": _position(0.0, 0.0),
        },
    )
    context = {
        "portfolio": portfolio,
        "instruments": {
            "600001": SimpleNamespace(instrument_type=SimpleNamespace(value="stock")),
            "600002": SimpleNamespace(instrument_type=SimpleNamespace(value="stock")),
        },
        "valuation_snapshot": None,
        "authority": "legacy_runtime_fallback",
    }

    summary = portfolio_state_summary(
        SimpleNamespace(),
        portfolio_context=context,
    )

    assert summary["position_count"] == 1
    assert summary["symbols"] == ["600001"]
    assert summary["instrument_types"] == {"600001": "stock"}
    assert summary["total_market_value"] == 1000.0
    assert summary["total_equity"] == 1500.0


def test_decision_symbols_include_only_current_holdings_and_current_actions():
    state = SimpleNamespace(
        scheduler=SimpleNamespace(
            watchlist=[
                ("WATCH_ONLY", "stock"),
                ("600001", "stock"),
            ]
        ),
        config=SimpleNamespace(
            assets=[
                {"symbol": "CONFIG_ONLY", "asset_class": "stock"},
            ]
        ),
    )
    context = {
        "portfolio": SimpleNamespace(
            positions={
                "600001": _position(100.0, 1000.0),
                "600002": _position(0.0, 0.0),
            }
        ),
    }

    symbols = decision_symbols(
        state,
        [{"symbol": "ACTION_ONLY"}],
        portfolio_context=context,
    )

    assert symbols == ["ACTION_ONLY", "600001"]


@pytest.mark.parametrize("candidate_map_present", [False, True])
def test_market_summary_does_not_fill_missing_candidates_with_account_quotes(
    candidate_map_present,
) -> None:
    context = {
        "authority": "persisted_valuation_snapshot",
        "portfolio": SimpleNamespace(
            positions={
                "600001": _position(100.0, 1000.0),
                "600002": _position(100.0, 2000.0),
            }
        ),
        "quotes": {
            "600001": {"price": 10.0, "quote_status": "confirmed"},
            "600002": {"price": 20.0, "quote_status": "confirmed"},
        },
    }
    if candidate_map_present:
        context["candidate_quotes"] = {}

    summary = market_data_summary(
        SimpleNamespace(),
        [{"symbol": "600001", "asset_class": "stock"}],
        portfolio_context=context,
    )

    assert summary["source_health"] == "partial"
    assert summary["quote_count"] == 1
    assert summary["trusted_quote_count"] == 1
    assert summary["missing_symbols"] == ["600001"]
    assert data_refresh_workflow_task(summary)["status"] == "blocked"


@pytest.mark.parametrize(
    ("quote_timestamp", "expected_health"),
    [
        ("2026-07-02T09:30:00+08:00", "confirmed"),
        ("2026-07-01T15:00:00+08:00", "stale"),
    ],
)
def test_market_summary_uses_bound_candidate_freshness(
    tmp_path, quote_timestamp, expected_health
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_latest_quote_sync(
        symbol="600001",
        asset_type="stock",
        price=20.0,
        quote_timestamp=quote_timestamp,
        quote_source="deterministic_fixture",
        quote_status="confirmed",
    )
    actions = [{"id": 1, "symbol": "600001", "asset_class": "stock"}]
    evidence = candidate_market_evidence(
        db,
        actions,
        now=datetime(2026, 7, 2, 9, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    context = bind_candidate_market_evidence(
        {
            "authority": "persisted_valuation_snapshot",
            "portfolio": SimpleNamespace(positions={}),
            "quotes": {
                "600001": {
                    "symbol": "600001",
                    "instrument_type": "stock",
                    "price": 10.0,
                    "quote_status": "confirmed",
                    "quote_timestamp": "2026-07-02T09:31:00+08:00",
                }
            },
        },
        evidence,
    )

    summary = market_data_summary(
        SimpleNamespace(db=db), actions, portfolio_context=context
    )

    assert context["candidate_quotes"]["600001"]["quote_status"] == expected_health
    assert summary["source_health"] == expected_health
    assert summary["quote_count"] == 1
    assert summary["trusted_quote_count"] == (
        1 if expected_health == "confirmed" else 0
    )
    assert summary["stale_quote_count"] == (1 if expected_health == "stale" else 0)
    assert summary["latest_quote_timestamp"] == quote_timestamp
    assert data_refresh_workflow_task(summary)["status"] == (
        "pass" if expected_health == "confirmed" else "blocked"
    )


@pytest.mark.parametrize(
    "authority", ["persisted_valuation_snapshot", "legacy_runtime_fallback"]
)
def test_market_summary_keeps_account_quotes_for_holdings_without_candidates(
    authority,
) -> None:
    context = {
        "authority": authority,
        "portfolio": SimpleNamespace(
            positions={
                "600001": _position(100.0, 1000.0),
                "600002": _position(0.0, 0.0),
            }
        ),
        "quotes": {"600001": {"price": 10.0, "quote_status": "confirmed"}},
        "candidate_quotes": {},
    }

    summary = market_data_summary(SimpleNamespace(), [], portfolio_context=context)

    assert summary["source_health"] == "confirmed"
    assert summary["quote_count"] == 1
    assert summary["trusted_quote_count"] == 1
    assert summary["missing_symbols"] == []
    assert data_refresh_workflow_task(summary)["status"] == "pass"


def test_legacy_market_summary_keeps_account_quote_fallback_for_actions() -> None:
    summary = market_data_summary(
        SimpleNamespace(),
        [{"symbol": "600001", "asset_class": "stock"}],
        portfolio_context={
            "authority": "legacy_runtime_fallback",
            "portfolio": SimpleNamespace(positions={}),
            "quotes": {"600001": {"price": 10.0, "quote_status": "confirmed"}},
            "candidate_quotes": {},
        },
    )

    assert summary["source_health"] == "confirmed"
    assert summary["quote_count"] == 1
    assert summary["missing_symbols"] == []
