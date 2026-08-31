"""Runtime trading controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable

from server.contracts.automatic_trading import (
    AUTOMATIC_TRADING_CONTROL_KEY,
    AUTOMATIC_TRADING_CONTROL_SCHEMA_VERSION,
    AUTOMATIC_TRADING_DISABLE_ACKNOWLEDGEMENT,
    AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT,
)
from server.contracts.automatic_trading import (
    automatic_trading_control_fingerprint as _automatic_trading_fingerprint,
)
from server.contracts.automatic_trading import automatic_trading_disable_identity
from server.contracts.automatic_trading import (
    automatic_trading_evidence as _automatic_trading_evidence,
)
from server.contracts.automatic_trading import (
    automatic_trading_transition_error,
    resolve_persisted_automatic_trading_control,
)

KILL_SWITCH_EVIDENCE_SCHEMA_VERSION = "karkinos.kill_switch_evidence.v1"
_AUTOMATIC_TRADING_CONTROL_KEY = AUTOMATIC_TRADING_CONTROL_KEY


@dataclass(frozen=True)
class TradingControlSnapshot:
    kill_switch_enabled: bool
    reason: str = ""
    updated_at: str = ""


class AutomaticTradingControlRevisionConflict(ValueError):
    """Raised when an automatic-trading update loses its revision CAS."""

    def __init__(
        self,
        *,
        expected_revision: int,
        current_revision: int,
        current_state: dict[str, Any],
    ) -> None:
        super().__init__(
            "automatic trading control revision conflict: "
            f"expected {expected_revision}, current {current_revision}"
        )
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        self.current_state = current_state


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


def resolve_automatic_trading_evidence(
    trading_controls: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read the canonical runtime control without granting any other authority."""

    try:
        getter = getattr(trading_controls, "automatic_trading_snapshot", None)
        if not callable(getter):
            return _automatic_trading_evidence(
                status="unavailable",
                blocker="automatic_trading_status_unavailable",
            )
        snapshot = getter(now=now)
    except Exception:
        return _automatic_trading_evidence(
            status="unavailable",
            blocker="automatic_trading_snapshot_failed",
        )
    if not isinstance(snapshot, dict):
        return _automatic_trading_evidence(
            status="unavailable",
            blocker="automatic_trading_snapshot_invalid",
        )
    if (
        not isinstance(snapshot.get("enabled"), bool)
        or not isinstance(snapshot.get("configured_enabled"), bool)
        or snapshot.get("status")
        not in {"enabled", "disabled", "expired", "unavailable"}
        or not isinstance(snapshot.get("blockers"), list)
        or not isinstance(snapshot.get("revision"), int)
        or not isinstance(snapshot.get("control_fingerprint"), str)
        or (
            snapshot.get("enabled") is True
            and (
                snapshot.get("status") != "enabled"
                or snapshot.get("configured_enabled") is not True
                or bool(snapshot.get("blockers"))
            )
        )
        or (
            snapshot.get("status") != "enabled" and snapshot.get("enabled") is not False
        )
    ):
        return _automatic_trading_evidence(
            status="unavailable",
            blocker="automatic_trading_snapshot_invalid",
        )
    return dict(snapshot)


class TradingControlState:
    """Thread-safe mutable trading control state."""

    def __init__(
        self,
        db=None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._lock = RLock()
        self._db = db
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._kill_switch_enabled = False
        self._reason = ""
        self._updated_at = datetime.now().isoformat()
        self._automatic_trading_control: Any = None
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

    def automatic_trading_snapshot(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Return the current effective automatic-trading gate."""

        persisted = self._read_automatic_trading_control()
        if persisted is not _NO_PERSISTED_REFRESH:
            with self._lock:
                self._automatic_trading_control = persisted
        with self._lock:
            value = self._automatic_trading_control
            if isinstance(value, dict):
                value = dict(value)
        resolved_now = _aware_utc(now or self._clock())
        return resolve_persisted_automatic_trading_control(
            value,
            now_epoch_ms=_epoch_ms(resolved_now),
        )

    def set_automatic_trading(
        self,
        *,
        enabled: bool,
        reason: str,
        operator_id: str,
        expected_revision: int,
        ttl_seconds: int | None = None,
        acknowledgement: str,
    ) -> dict[str, Any]:
        """CAS-update the runtime gate; enabling remains expiring and non-authorizing."""

        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason is required")
        if len(reason) > 500:
            raise ValueError("reason must contain at most 500 characters")
        if not isinstance(operator_id, str) or not operator_id.strip():
            raise ValueError("operator_id is required")
        if len(operator_id) > 128:
            raise ValueError("operator_id must contain at most 128 characters")
        normalized_reason = reason.strip()
        normalized_operator_id = operator_id.strip()
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise ValueError("expected_revision must be a non-negative integer")
        expected_acknowledgement = (
            AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT
            if enabled
            else AUTOMATIC_TRADING_DISABLE_ACKNOWLEDGEMENT
        )
        if acknowledgement != expected_acknowledgement:
            raise ValueError(
                "acknowledgement does not match the requested automatic trading action"
            )
        if enabled and (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, int)
            or not 60 <= ttl_seconds <= 43_200
        ):
            raise ValueError("ttl_seconds must be between 60 and 43200 when enabling")

        now_epoch_ms = _epoch_ms(_aware_utc(self._clock()))
        effective_at = _datetime_from_epoch_ms(now_epoch_ms).isoformat()
        if self._db is None:
            with self._lock:
                current_value = self._automatic_trading_control
                if isinstance(current_value, dict):
                    current_value = dict(current_value)
        else:
            current_value = self._read_automatic_trading_control()
            if current_value is _NO_PERSISTED_REFRESH:
                with self._lock:
                    current_value = self._automatic_trading_control
                    if isinstance(current_value, dict):
                        current_value = dict(current_value)
        next_revision = expected_revision + 1
        expires_at_epoch_ms = (
            now_epoch_ms + int(ttl_seconds) * 1000 if enabled else None
        )
        value: dict[str, Any] = {
            "schema_version": AUTOMATIC_TRADING_CONTROL_SCHEMA_VERSION,
            "configured_enabled": enabled,
            "revision": next_revision,
            "control_fingerprint": "",
            "reason": normalized_reason,
            "operator_id": normalized_operator_id,
            "effective_at": effective_at,
            "effective_at_epoch_ms": now_epoch_ms,
            "expires_at": (
                _datetime_from_epoch_ms(expires_at_epoch_ms).isoformat()
                if expires_at_epoch_ms is not None
                else None
            ),
            "expires_at_epoch_ms": expires_at_epoch_ms,
            **_next_last_disabled_lineage(
                current_value,
                enabled=enabled,
                next_revision=next_revision,
                effective_at=effective_at,
                effective_at_epoch_ms=now_epoch_ms,
            ),
            "updated_at": effective_at,
        }
        value["control_fingerprint"] = _automatic_trading_fingerprint(value)

        if self._db is None:
            with self._lock:
                current_revision = _persisted_control_revision(
                    self._automatic_trading_control
                )
                if current_revision != expected_revision:
                    current_state = resolve_persisted_automatic_trading_control(
                        self._automatic_trading_control,
                        now_epoch_ms=now_epoch_ms,
                    )
                    raise AutomaticTradingControlRevisionConflict(
                        expected_revision=expected_revision,
                        current_revision=current_revision,
                        current_state=current_state,
                    )
                current_state = resolve_persisted_automatic_trading_control(
                    self._automatic_trading_control,
                    now_epoch_ms=now_epoch_ms,
                )
                if current_state.get("status") == "unavailable":
                    raise RuntimeError(
                        "automatic trading control persisted state is unavailable"
                    )
                transition_error = automatic_trading_transition_error(
                    current_status=str(current_state.get("status") or "unavailable"),
                    requested_enabled=enabled,
                )
                if transition_error:
                    raise ValueError(transition_error)
                self._automatic_trading_control = dict(value)
        else:
            writer = getattr(
                self._db,
                "compare_and_set_automatic_trading_control_sync",
                None,
            )
            if not callable(writer):
                raise RuntimeError(
                    "automatic trading persistence capability is unavailable"
                )
            result = writer(
                expected_revision=expected_revision,
                value=value,
                acknowledgement=acknowledgement,
            )
            if result.get("updated") is not True:
                current_value = result.get("value")
                with self._lock:
                    self._automatic_trading_control = current_value
                current_revision = int(result.get("current_revision") or 0)
                raise AutomaticTradingControlRevisionConflict(
                    expected_revision=expected_revision,
                    current_revision=current_revision,
                    current_state=resolve_persisted_automatic_trading_control(
                        current_value,
                        now_epoch_ms=now_epoch_ms,
                    ),
                )
            with self._lock:
                self._automatic_trading_control = dict(value)

        return resolve_persisted_automatic_trading_control(
            value,
            now_epoch_ms=now_epoch_ms,
        )

    def _restore(self) -> None:
        if self._db is None or not hasattr(self._db, "get_runtime_control_sync"):
            return
        kill_switch = self._db.get_runtime_control_sync("kill_switch")
        automatic_trading = self._read_automatic_trading_control()
        with self._lock:
            if kill_switch:
                self._kill_switch_enabled = bool(kill_switch.get("enabled", False))
                self._reason = str(kill_switch.get("reason") or "")
                self._updated_at = str(
                    kill_switch.get("updated_at") or self._updated_at
                )
            if automatic_trading is not _NO_PERSISTED_REFRESH:
                self._automatic_trading_control = automatic_trading

    def _persist(self, snapshot: TradingControlSnapshot) -> None:
        if self._db is None or not hasattr(self._db, "set_runtime_control_sync"):
            return
        value: dict[str, Any] = {
            "enabled": snapshot.kill_switch_enabled,
            "reason": snapshot.reason,
            "updated_at": snapshot.updated_at,
        }
        self._db.set_runtime_control_sync("kill_switch", value)

    def _read_automatic_trading_control(self) -> Any:
        if self._db is None or not hasattr(self._db, "get_runtime_control_sync"):
            return _NO_PERSISTED_REFRESH
        try:
            return self._db.get_runtime_control_sync(_AUTOMATIC_TRADING_CONTROL_KEY)
        except Exception:
            return {"invalid_persisted_control": True}


_NO_PERSISTED_REFRESH = object()


def _next_last_disabled_lineage(
    current: Any,
    *,
    enabled: bool,
    next_revision: int,
    effective_at: str,
    effective_at_epoch_ms: int,
) -> dict[str, Any]:
    if not enabled:
        return {
            "last_disabled_at": effective_at,
            "last_disabled_at_epoch_ms": effective_at_epoch_ms,
            "last_disabled_revision": next_revision,
            "last_disabled_control_identity": automatic_trading_disable_identity(
                revision=next_revision,
                epoch_ms=effective_at_epoch_ms,
            ),
        }
    source = current if isinstance(current, dict) else {}
    return {
        field: source.get(field)
        for field in (
            "last_disabled_at",
            "last_disabled_at_epoch_ms",
            "last_disabled_revision",
            "last_disabled_control_identity",
        )
    }


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _epoch_ms(value: datetime) -> int:
    return int(_aware_utc(value).timestamp() * 1000)


def _datetime_from_epoch_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _persisted_control_revision(value: Any) -> int:
    if not isinstance(value, dict):
        return 0
    revision = value.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        return 0
    return revision
