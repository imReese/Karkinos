"""Trading control state tests."""

from __future__ import annotations

from server.db import AppDatabase
from server.services.trading_controls import TradingControlState


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
