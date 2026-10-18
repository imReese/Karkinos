from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from server.db import AppDatabase
from server.services.decision_candidate_market_evidence import (
    bind_candidate_market_evidence,
    candidate_market_evidence,
)
from server.services.decision_portfolio_projection import (
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
