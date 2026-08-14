"""Runtime trading controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Any

KILL_SWITCH_EVIDENCE_SCHEMA_VERSION = "karkinos.kill_switch_evidence.v1"


@dataclass(frozen=True)
class TradingControlSnapshot:
    kill_switch_enabled: bool
    reason: str = ""
    updated_at: str = ""


def resolve_kill_switch_evidence(trading_controls: Any) -> dict[str, Any]:
    """Resolve one explicit fail-closed snapshot for downstream authority gates."""

    try:
        getter = getattr(trading_controls, "snapshot", None)
        if not callable(getter):
            return _unavailable_kill_switch_evidence("kill_switch_status_unavailable")
        snapshot = getter()
        enabled = getattr(snapshot, "kill_switch_enabled", None)
        updated_at = str(getattr(snapshot, "updated_at", "") or "").strip()
        reason = str(getattr(snapshot, "reason", "") or "").strip()
    except Exception:
        return _unavailable_kill_switch_evidence("kill_switch_snapshot_failed")

    if not isinstance(enabled, bool) or not updated_at:
        return _unavailable_kill_switch_evidence("kill_switch_snapshot_invalid")
    return {
        "schema_version": KILL_SWITCH_EVIDENCE_SCHEMA_VERSION,
        "status": "blocked" if enabled else "pass",
        "enabled": enabled,
        "reason": reason,
        "updated_at": updated_at,
        "evidence_ref": (
            "trading_controls:kill_switch_enabled"
            if enabled
            else "trading_controls:kill_switch_clear"
        ),
        "blockers": ["kill_switch_enabled"] if enabled else [],
        "evidence_available": True,
        "manual_ticket_allowed": not enabled,
        "fail_closed": True,
    }


def _unavailable_kill_switch_evidence(blocker: str) -> dict[str, Any]:
    return {
        "schema_version": KILL_SWITCH_EVIDENCE_SCHEMA_VERSION,
        "status": "unavailable",
        "enabled": None,
        "reason": "",
        "updated_at": None,
        "evidence_ref": "",
        "blockers": [blocker],
        "evidence_available": False,
        "manual_ticket_allowed": False,
        "fail_closed": True,
    }


class TradingControlState:
    """Thread-safe mutable trading control state."""

    def __init__(self, db=None) -> None:
        self._lock = RLock()
        self._db = db
        self._kill_switch_enabled = False
        self._reason = ""
        self._updated_at = datetime.now().isoformat()
        self._restore()

    def snapshot(self) -> TradingControlSnapshot:
        with self._lock:
            return TradingControlSnapshot(
                kill_switch_enabled=self._kill_switch_enabled,
                reason=self._reason,
                updated_at=self._updated_at,
            )

    def set_kill_switch(
        self, enabled: bool, reason: str = ""
    ) -> TradingControlSnapshot:
        with self._lock:
            self._kill_switch_enabled = enabled
            self._reason = reason
            self._updated_at = datetime.now().isoformat()
            snapshot = TradingControlSnapshot(
                kill_switch_enabled=self._kill_switch_enabled,
                reason=self._reason,
                updated_at=self._updated_at,
            )

        self._persist(snapshot)
        return snapshot

    def _restore(self) -> None:
        if self._db is None or not hasattr(self._db, "get_runtime_control_sync"):
            return
        value = self._db.get_runtime_control_sync("kill_switch")
        if not value:
            return
        with self._lock:
            self._kill_switch_enabled = bool(value.get("enabled", False))
            self._reason = str(value.get("reason") or "")
            self._updated_at = str(value.get("updated_at") or self._updated_at)

    def _persist(self, snapshot: TradingControlSnapshot) -> None:
        if self._db is None or not hasattr(self._db, "set_runtime_control_sync"):
            return
        value: dict[str, Any] = {
            "enabled": snapshot.kill_switch_enabled,
            "reason": snapshot.reason,
            "updated_at": snapshot.updated_at,
        }
        self._db.set_runtime_control_sync("kill_switch", value)
