from __future__ import annotations

from server.db import AppDatabase
from server.services.automation_control import (
    DEFAULT_AUTOMATION_POLICY_ID,
    AutomationControlService,
)
from server.services.trading_controls import TradingControlState


def test_default_policy_keeps_live_broker_submission_disabled(tmp_path) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    service = AutomationControlService(db=db, trading_controls=None)

    policy = service.get_default_policy()

    assert policy["policy_id"] == DEFAULT_AUTOMATION_POLICY_ID
    assert policy["broker_submission_enabled"] is False
    assert policy["default_execution_mode"] == "manual_confirmation"
    assert policy["manual_confirmation_required"] is True
    assert "paper_shadow" in policy["allowed_execution_modes"]
    assert "live" not in policy["allowed_execution_modes"]


def test_update_default_policy_rejects_live_submission_enablement(tmp_path) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    service = AutomationControlService(db=db, trading_controls=None)

    try:
        service.update_default_policy(
            {
                "broker_submission_enabled": True,
                "allowed_execution_modes": ["paper_shadow", "live"],
            },
            updated_by="test",
        )
    except ValueError as exc:
        assert "broker submission is disabled by default" in str(exc)
    else:
        raise AssertionError("expected live broker submission to be rejected")


def test_status_reports_manual_default_and_kill_switch(tmp_path) -> None:
    db = AppDatabase(tmp_path / "automation.db")
    db.init_sync()
    trading_controls = TradingControlState(db=db)
    trading_controls.set_kill_switch(True, "operator pause")
    service = AutomationControlService(db=db, trading_controls=trading_controls)

    status = service.get_status()

    assert status["broker_submission_enabled"] is False
    assert status["default_execution_mode"] == "manual_confirmation"
    assert status["kill_switch_enabled"] is True
    assert status["automation_ready"] is False
    assert status["next_action"] == "resolve_kill_switch"
