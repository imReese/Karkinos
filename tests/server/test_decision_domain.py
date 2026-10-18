"""Executable verification for server.services.decision domain package."""

from __future__ import annotations

import server.services.decision_application as legacy_decision_app
import server.services.decision_projection as legacy_decision_projection
from server.services import decision
from server.services.decision import (
    build_decision_quality_target,
    daily_candidate_generation_status,
    decision_portfolio_context,
    intraday_decision_payload,
    run_batch_pre_trade_risk_for_state,
    suppress_unverified_daily_scan_candidates,
    today_decision_payload,
)


def test_decision_domain_exports_canonical_symbols() -> None:
    assert today_decision_payload is legacy_decision_app.today_decision_payload
    assert intraday_decision_payload is legacy_decision_app.intraday_decision_payload
    assert decision_portfolio_context is legacy_decision_app.decision_portfolio_context
    assert (
        run_batch_pre_trade_risk_for_state
        is legacy_decision_app.run_batch_pre_trade_risk_for_state
    )
    assert (
        suppress_unverified_daily_scan_candidates
        is legacy_decision_projection.suppress_unverified_daily_scan_candidates
    )
    assert (
        daily_candidate_generation_status
        is legacy_decision_projection.daily_candidate_generation_status
    )


def test_decision_quality_target_via_domain() -> None:
    payload = {
        "decision_date": "2026-09-01",
        "market_data": {
            "calendar_status": "confirmed",
            "market_status": "live",
            "market_summary": "normal",
        },
        "pre_trade_risk": {"status": "passed"},
        "portfolio": {"cash": 100000.0, "total_equity": 100000.0},
        "actions": [],
    }
    target = build_decision_quality_target(payload)
    assert target.decision_date == "2026-09-01"
    assert len(target.dimensions) >= 1
    names = {dim.name for dim in target.dimensions}
    assert "data_complete" in names
