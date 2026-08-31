"""Controlled Sessions database compatibility capability."""

from __future__ import annotations

from typing import Any

from server.persistence.facades.base import DatabaseRepositoryAccess


class ControlledSessionDatabaseFacade(DatabaseRepositoryAccess):
    """Delegate the legacy API to cohesive repositories."""

    # ---------- Controlled Session Budget Reservations ----------

    def reserve_controlled_session_budget_sync(
        self, *, reservation: dict[str, Any]
    ) -> dict[str, Any]:
        """Atomically reserve bounded capital without issuing execution authority."""
        return self._controlled_session.reserve_controlled_session_budget_sync(
            reservation=reservation
        )

    def list_controlled_session_budget_reservations_sync(
        self, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List immutable reservation records newest first."""
        return (
            self._controlled_session.list_controlled_session_budget_reservations_sync(
                limit=limit
            )
        )

    def get_controlled_session_budget_reservation_sync(
        self, reservation_id: str
    ) -> dict[str, Any] | None:
        """Read one reservation by its deterministic id."""
        return self._controlled_session.get_controlled_session_budget_reservation_sync(
            reservation_id
        )

    # ---------- Controlled Session Runtime Authority ----------

    def issue_controlled_session_sync(
        self, *, session: dict[str, Any]
    ) -> dict[str, Any]:
        """Issue one persisted bounded session for one exact reservation."""
        return self._controlled_session.issue_controlled_session_sync(session=session)

    def replace_paused_controlled_session_sync(
        self, *, replacement: dict[str, Any]
    ) -> dict[str, Any]:
        """Atomically retire one paused session and issue one bounded replacement."""
        return self._controlled_session.replace_paused_controlled_session_sync(
            replacement=replacement
        )

    def revoke_controlled_session_sync(
        self, *, revocation: dict[str, Any]
    ) -> dict[str, Any]:
        """Persist an operator-signed one-way session revocation."""
        return self._controlled_session.revoke_controlled_session_sync(
            revocation=revocation
        )

    def get_controlled_session_runtime_session_sync(
        self, session_id: str
    ) -> dict[str, Any] | None:
        """Read one runtime session including private hash fields for verification."""
        return self._controlled_session.get_controlled_session_runtime_session_sync(
            session_id
        )

    def list_controlled_session_runtime_sessions_sync(
        self, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List runtime sessions without interpreting current authority."""
        return self._controlled_session.list_controlled_session_runtime_sessions_sync(
            limit=limit
        )

    def find_enabled_paused_controlled_session_sync(
        self,
        *,
        authorization_id: str,
        account_alias: str,
        strategy_id: str,
        now_epoch_ms: int,
    ) -> dict[str, Any] | None:
        """Find active paused authority that requires signed replacement review."""
        return self._controlled_session.find_enabled_paused_controlled_session_sync(
            authorization_id=authorization_id,
            account_alias=account_alias,
            strategy_id=strategy_id,
            now_epoch_ms=now_epoch_ms,
        )

    def list_controlled_session_replacements_sync(
        self, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List immutable signed replacement evidence newest first."""
        return self._controlled_session.list_controlled_session_replacements_sync(
            limit=limit
        )

    def get_controlled_session_replacement_for_predecessor_sync(
        self, predecessor_session_id: str
    ) -> dict[str, Any] | None:
        """Read immutable replacement evidence for one retired predecessor."""
        return self._controlled_session.get_controlled_session_replacement_for_predecessor_sync(
            predecessor_session_id
        )

    def list_controlled_session_revocations_sync(
        self, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List immutable signed revocation evidence newest first."""
        return self._controlled_session.list_controlled_session_revocations_sync(
            limit=limit
        )

    # ---------- Controlled Session Live Gate Snapshots ----------

    def record_controlled_session_gate_snapshot_sync(
        self, *, snapshot: dict[str, Any]
    ) -> dict[str, Any]:
        """Persist one sanitized runtime-gate observation idempotently."""
        return self._controlled_session.record_controlled_session_gate_snapshot_sync(
            snapshot=snapshot
        )

    def latest_controlled_session_gate_snapshot_sync(
        self, session_id: str
    ) -> dict[str, Any] | None:
        """Read the newest persisted gate snapshot for one session."""
        return self._controlled_session.latest_controlled_session_gate_snapshot_sync(
            session_id
        )

    def list_controlled_session_gate_snapshots_sync(
        self, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List sanitized runtime-gate snapshots newest first."""
        return self._controlled_session.list_controlled_session_gate_snapshots_sync(
            limit=limit
        )

    def list_controlled_session_gate_snapshots_for_session_sync(
        self, *, session_id: str, since_epoch_ms: int = 0, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List one session's persisted gate snapshots oldest first."""
        return self._controlled_session.list_controlled_session_gate_snapshots_for_session_sync(
            session_id=session_id, since_epoch_ms=since_epoch_ms, limit=limit
        )

    def get_controlled_session_runtime_metrics_sync(
        self, *, session_id: str, window_start_epoch_ms: int, observed_at_epoch_ms: int
    ) -> dict[str, Any]:
        """Read admission counters and the exact reserved order capacity."""
        return self._controlled_session.get_controlled_session_runtime_metrics_sync(
            session_id=session_id,
            window_start_epoch_ms=window_start_epoch_ms,
            observed_at_epoch_ms=observed_at_epoch_ms,
        )

    # ---------- Controlled Session Runtime Rate Admissions ----------

    def admit_controlled_session_order_sync(
        self, *, admission: dict[str, Any]
    ) -> dict[str, Any]:
        """Atomically admit one order under fresh gates and a shared rate window."""
        return self._controlled_session.admit_controlled_session_order_sync(
            admission=admission
        )

    def list_controlled_session_rate_admissions_sync(
        self, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List immutable runtime rate-admission evidence newest first."""
        return self._controlled_session.list_controlled_session_rate_admissions_sync(
            limit=limit
        )

    # ---------- Controlled Session Automatic Pause ----------

    def pause_controlled_session_sync(self, *, pause: dict[str, Any]) -> dict[str, Any]:
        """Persist the first automatic pause; no automatic resume path exists."""
        return self._controlled_session.pause_controlled_session_sync(pause=pause)

    def get_controlled_session_runtime_state_sync(
        self, session_id: str
    ) -> dict[str, Any] | None:
        """Read the durable pause state for one session."""
        return self._controlled_session.get_controlled_session_runtime_state_sync(
            session_id
        )

    def get_controlled_session_pause_event_sync(
        self, pause_event_id: str
    ) -> dict[str, Any] | None:
        """Read one immutable automatic-pause event by fingerprint."""
        return self._controlled_session.get_controlled_session_pause_event_sync(
            pause_event_id
        )

    def list_controlled_session_pause_events_sync(
        self, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List immutable automatic-pause evidence newest first."""
        return self._controlled_session.list_controlled_session_pause_events_sync(
            limit=limit
        )
