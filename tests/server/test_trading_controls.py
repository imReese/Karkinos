"""Trading control state tests."""

from __future__ import annotations

from server.db import AppDatabase
from server.services.trading_controls import (
    TradingControlState,
    resolve_kill_switch_evidence,
)


def test_trading_control_state_persists_kill_switch(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    controls = TradingControlState(db=db)
    updated = controls.set_kill_switch(True, "risk event")

    assert updated.kill_switch_enabled is True
    assert updated.reason == "risk event"

    restored = TradingControlState(db=db)
    snapshot = restored.snapshot()
    assert snapshot.kill_switch_enabled is True
    assert snapshot.reason == "risk event"


def test_kill_switch_evidence_resolver_fails_closed_for_missing_failed_or_invalid_state() -> (
    None
):
    class FailingControls:
        def snapshot(self):
            raise RuntimeError("fixture failure")

    class InvalidControls:
        def snapshot(self):
            return object()

    missing = resolve_kill_switch_evidence(None)
    failed = resolve_kill_switch_evidence(FailingControls())
    invalid = resolve_kill_switch_evidence(InvalidControls())

    assert missing["status"] == "unavailable"
    assert missing["enabled"] is None
    assert missing["manual_ticket_allowed"] is False
    assert missing["blockers"] == ["kill_switch_status_unavailable"]
    assert failed["blockers"] == ["kill_switch_snapshot_failed"]
    assert invalid["blockers"] == ["kill_switch_snapshot_invalid"]
    assert all(item["fail_closed"] is True for item in (missing, failed, invalid))


def test_kill_switch_evidence_resolver_distinguishes_clear_and_enabled_state(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    controls = TradingControlState(db=db)

    clear = resolve_kill_switch_evidence(controls)
    controls.set_kill_switch(True, "operator pause")
    blocked = resolve_kill_switch_evidence(controls)

    assert clear["status"] == "pass"
    assert clear["enabled"] is False
    assert clear["manual_ticket_allowed"] is True
    assert clear["evidence_ref"] == "trading_controls:kill_switch_clear"
    assert blocked["status"] == "blocked"
    assert blocked["enabled"] is True
    assert blocked["reason"] == "operator pause"
    assert blocked["blockers"] == ["kill_switch_enabled"]
