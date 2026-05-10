"""Runtime trading controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class TradingControlSnapshot:
    kill_switch_enabled: bool
    reason: str = ""
    updated_at: str = ""


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
