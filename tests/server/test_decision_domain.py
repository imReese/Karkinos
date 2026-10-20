"""Executable verification for server.services.decision domain package."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from server.services.decision.quality import build_decision_quality_target


def test_cold_quality_import_isolates_application_and_preserves_account_plan() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            """
import sys
import server.services.decision.quality

unexpected = {
    "server.services.decision.plan",
    "server.services.decision.decision_application",
    "server.services.decision.decision_projection",
    "server.services.decision.decision_action_application",
    "server.services.strategy_promotion_pipeline",
    "server.ai_runtime.strategy_research",
}.intersection(sys.modules)
assert not unexpected, sorted(unexpected)

from server.services.account import account_paper_shadow

plan = account_paper_shadow.decision_plan.build_daily_trading_plan(
    decision_payload={"decision_date": "2026-09-01"},
    config=None,
)
assert plan["plan_date"] == "2026-09-01"
assert plan["conclusion_status"] == "account_truth_blocked"
assert plan["order_intents"] == []
assert plan["broker_bridge_status"] == "disabled"
""",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_decision_quality_target() -> None:
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
