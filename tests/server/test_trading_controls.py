"""Trading control state tests."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from server.contracts.automatic_trading import (
    AUTOMATIC_TRADING_CONTROL_SCHEMA_VERSION,
    automatic_trading_control_fingerprint,
)
from server.db import AppDatabase
from server.persistence.runtime_controls import RuntimeControlRepository
from server.services.trading_controls import (
    AUTOMATIC_TRADING_DISABLE_ACKNOWLEDGEMENT,
    AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT,
    AutomaticTradingControlRevisionConflict,
    TradingControlState,
    resolve_automatic_trading_evidence,
    resolve_kill_switch_evidence,
    resolve_persisted_automatic_trading_control,
)


def _automatic_control_value(
    *,
    ttl_seconds: int = 300,
) -> dict:
    effective_at = datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc)
    expires_at = effective_at + timedelta(seconds=ttl_seconds)
    value = {
        "schema_version": AUTOMATIC_TRADING_CONTROL_SCHEMA_VERSION,
        "configured_enabled": True,
        "revision": 1,
        "control_fingerprint": "",
        "reason": "direct repository contract test",
        "operator_id": "operator-test",
        "effective_at": effective_at.isoformat(),
        "effective_at_epoch_ms": int(effective_at.timestamp() * 1000),
        "expires_at": expires_at.isoformat(),
        "expires_at_epoch_ms": int(expires_at.timestamp() * 1000),
        "last_disabled_at": None,
        "last_disabled_at_epoch_ms": None,
        "last_disabled_revision": None,
        "last_disabled_control_identity": None,
        "updated_at": effective_at.isoformat(),
    }
    value["control_fingerprint"] = automatic_trading_control_fingerprint(value)
    return value


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


def test_automatic_trading_evidence_defaults_missing_and_malformed_closed() -> None:
    missing = resolve_persisted_automatic_trading_control(
        None,
        now_epoch_ms=1_000,
    )
    malformed = resolve_persisted_automatic_trading_control(
        {"configured_enabled": True},
        now_epoch_ms=1_000,
    )
    unavailable = resolve_automatic_trading_evidence(None)

    assert missing["status"] == "disabled"
    assert missing["enabled"] is False
    assert missing["configured_enabled"] is False
    assert missing["blockers"] == ["automatic_trading_control_missing"]
    assert malformed["status"] == "unavailable"
    assert malformed["enabled"] is False
    assert malformed["blockers"] == ["automatic_trading_control_invalid"]
    assert unavailable["enabled"] is False
    assert unavailable["blockers"] == ["automatic_trading_status_unavailable"]
    assert all(
        item["grants_capital_authority"] is False
        and item["automatic_broker_submission_implemented"] is False
        for item in (missing, malformed, unavailable)
    )


def test_automatic_trading_runtime_toggle_expires_without_restart() -> None:
    now = [datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc)]
    controls = TradingControlState(clock=lambda: now[0])

    enabled = controls.set_automatic_trading(
        enabled=True,
        reason="bounded operator window",
        operator_id="operator-1",
        expected_revision=0,
        ttl_seconds=60,
        acknowledgement=AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT,
    )
    assert enabled["status"] == "enabled"
    assert enabled["enabled"] is True
    assert enabled["revision"] == 1

    now[0] += timedelta(seconds=60)
    expired = controls.automatic_trading_snapshot()
    assert expired["status"] == "expired"
    assert expired["configured_enabled"] is True
    assert expired["enabled"] is False
    assert expired["blockers"] == ["automatic_trading_control_expired"]

    disabled = controls.set_automatic_trading(
        enabled=False,
        reason="operator ended window",
        operator_id="operator-1",
        expected_revision=1,
        acknowledgement=AUTOMATIC_TRADING_DISABLE_ACKNOWLEDGEMENT,
    )
    assert disabled["status"] == "disabled"
    assert disabled["revision"] == 2
    assert disabled["expires_at"] is None


def test_automatic_trading_restore_cas_and_audit_are_persisted(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    now = datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc)
    first = TradingControlState(db=db, clock=lambda: now)
    stale = TradingControlState(db=db, clock=lambda: now)

    enabled = first.set_automatic_trading(
        enabled=True,
        reason="operator-supervised window",
        operator_id="operator-7",
        expected_revision=0,
        ttl_seconds=300,
        acknowledgement=AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT,
    )
    restored = TradingControlState(db=db, clock=lambda: now)
    assert restored.automatic_trading_snapshot() == enabled

    with pytest.raises(AutomaticTradingControlRevisionConflict) as conflict:
        stale.set_automatic_trading(
            enabled=True,
            reason="stale update",
            operator_id="operator-8",
            expected_revision=0,
            ttl_seconds=300,
            acknowledgement=AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT,
        )
    assert conflict.value.current_revision == 1

    disabled = first.set_automatic_trading(
        enabled=False,
        reason="operator stop",
        operator_id="operator-7",
        expected_revision=1,
        acknowledgement=AUTOMATIC_TRADING_DISABLE_ACKNOWLEDGEMENT,
    )
    assert disabled["revision"] == 2
    with sqlite3.connect(db.path) as conn:
        raw = conn.execute(
            "SELECT value_json FROM runtime_controls WHERE key = 'automatic_trading'"
        ).fetchone()[0]
        events = conn.execute("""
            SELECT event_type, payload_json FROM event_log
            WHERE source = 'trading_controls'
            ORDER BY id
            """).fetchall()
    assert json.loads(raw)["configured_enabled"] is False
    assert [row[0] for row in events] == [
        "automatic_trading.control_enabled",
        "automatic_trading.control_disabled",
    ]
    assert json.loads(events[0][1])["grants_capital_authority"] is False
    assert json.loads(events[1][1])["action"] == "disable"


def test_automatic_trading_audit_failure_rolls_back_control(
    monkeypatch,
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    controls = TradingControlState(
        db=db,
        clock=lambda: datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc),
    )

    def fail_event(*args, **kwargs):
        raise RuntimeError("event audit unavailable")

    monkeypatch.setattr(
        "server.persistence.runtime_controls.insert_event_sync",
        fail_event,
    )
    with pytest.raises(RuntimeError, match="event audit unavailable"):
        controls.set_automatic_trading(
            enabled=True,
            reason="must roll back",
            operator_id="operator-9",
            expected_revision=0,
            ttl_seconds=60,
            acknowledgement=AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT,
        )

    with sqlite3.connect(db.path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM runtime_controls WHERE key = 'automatic_trading'"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM event_log WHERE source = 'trading_controls'"
            ).fetchone()[0]
            == 0
        )


def test_automatic_trading_reserved_key_rejects_both_generic_write_layers(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    repository = RuntimeControlRepository(db.path)

    with pytest.raises(ValueError, match="dedicated audited CAS"):
        repository.set_value("automatic_trading", {"configured_enabled": True})
    with pytest.raises(ValueError, match="dedicated audited CAS"):
        db.set_runtime_control_sync(
            "automatic_trading",
            {"configured_enabled": True},
        )

    with sqlite3.connect(db.path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM runtime_controls WHERE key = 'automatic_trading'"
            ).fetchone()[0]
            == 0
        )


def test_automatic_trading_repository_rejects_wrong_action_acknowledgement(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    repository = RuntimeControlRepository(db.path)

    with pytest.raises(ValueError, match="acknowledgement does not match"):
        repository.compare_and_set_automatic_trading(
            expected_revision=0,
            value=_automatic_control_value(),
            acknowledgement=AUTOMATIC_TRADING_DISABLE_ACKNOWLEDGEMENT,
        )

    with sqlite3.connect(db.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runtime_controls").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM event_log WHERE source = 'trading_controls'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("mutation", ["fingerprint", "ttl"])
def test_automatic_trading_repository_rejects_invalid_proposed_control(
    tmp_path,
    mutation: str,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    repository = RuntimeControlRepository(db.path)
    value = _automatic_control_value(ttl_seconds=43_201 if mutation == "ttl" else 300)
    if mutation == "fingerprint":
        value["control_fingerprint"] = "f" * 64

    with pytest.raises(ValueError, match="control value is invalid"):
        repository.compare_and_set_automatic_trading(
            expected_revision=0,
            value=value,
            acknowledgement=AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT,
        )

    with sqlite3.connect(db.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runtime_controls").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM event_log WHERE source = 'trading_controls'"
            ).fetchone()[0]
            == 0
        )


def test_automatic_trading_backend_state_machine_rejects_rolling_renewal_and_noop() -> (
    None
):
    controls = TradingControlState(
        clock=lambda: datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc)
    )
    controls.set_automatic_trading(
        enabled=True,
        reason="first bounded window",
        operator_id="operator-test",
        expected_revision=0,
        ttl_seconds=300,
        acknowledgement=AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT,
    )

    with pytest.raises(ValueError, match="only be enabled from disabled"):
        controls.set_automatic_trading(
            enabled=True,
            reason="rolling renewal is forbidden",
            operator_id="operator-test",
            expected_revision=1,
            ttl_seconds=300,
            acknowledgement=AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT,
        )

    controls.set_automatic_trading(
        enabled=False,
        reason="operator close",
        operator_id="operator-test",
        expected_revision=1,
        acknowledgement=AUTOMATIC_TRADING_DISABLE_ACKNOWLEDGEMENT,
    )
    with pytest.raises(ValueError, match="only be disabled from enabled or expired"):
        controls.set_automatic_trading(
            enabled=False,
            reason="duplicate close",
            operator_id="operator-test",
            expected_revision=2,
            acknowledgement=AUTOMATIC_TRADING_DISABLE_ACKNOWLEDGEMENT,
        )
