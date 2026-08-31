"""Controlled session persistence capability: controlled_session_issuance_uow."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.contracts.automatic_trading import timestamp_epoch_ms
from server.persistence.automatic_trading_session_binding import (
    AutomaticTradingSessionBindingUnavailable,
    automatic_trading_session_reuse_blockers,
    bind_session_payload_to_automatic_trading_control,
)
from server.persistence.controlled_session_access import (
    ControlledSessionRepositoryAccess,
)
from server.persistence.controlled_session_rejections import (
    controlled_session_authority_rejection,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)


class ControlledSessionIssuanceUnitOfWorkMixin(ControlledSessionRepositoryAccess):
    """Cohesive SQLite capability mixed into the aggregate repository."""

    def issue_controlled_session_sync(
        self,
        *,
        session: dict[str, Any],
    ) -> dict[str, Any]:
        """Issue one persisted bounded session for one exact reservation."""
        requested = dict(session)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                        SELECT * FROM controlled_session_runtime_sessions
                        WHERE session_id = ? OR reservation_id = ?
                        ORDER BY id ASC
                        LIMIT 1
                        """,
                    (requested["session_id"], requested["reservation_id"]),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["session_id"] == requested["session_id"]
                        and existing["session_fingerprint"]
                        == requested["session_fingerprint"]
                        and existing["issuance_fingerprint"]
                        == requested["issuance_fingerprint"]
                        and existing["reservation_id"] == requested["reservation_id"]
                    ):
                        created_at_epoch_ms = timestamp_epoch_ms(
                            requested.get("created_at")
                        )
                        if created_at_epoch_ms is None:
                            conn.rollback()
                            return controlled_session_authority_rejection(
                                requested,
                                ["runtime_session_created_at_invalid"],
                            )
                        reuse_blockers = automatic_trading_session_reuse_blockers(
                            conn,
                            session_payload=existing["payload_json"],
                            observed_at_epoch_ms=created_at_epoch_ms,
                        )
                        if reuse_blockers:
                            conn.rollback()
                            return controlled_session_authority_rejection(
                                requested,
                                reuse_blockers,
                            )
                        conn.commit()
                        return {
                            "status": str(existing["status"]),
                            "blockers": [],
                            "reused": True,
                            "session": dict(existing),
                        }
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_reservation_or_identity_conflict"],
                    )

                reservation = conn.execute(
                    """
                        SELECT * FROM controlled_session_budget_reservations
                        WHERE reservation_id = ?
                        LIMIT 1
                        """,
                    (requested["reservation_id"],),
                ).fetchone()
                if reservation is None:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_reservation_not_found"],
                    )
                reservation_blockers: list[str] = []
                for field in (
                    "attestation_id",
                    "envelope_fingerprint",
                    "authorization_id",
                    "account_alias",
                    "strategy_id",
                    "requested_start_at",
                    "requested_expires_at",
                ):
                    if str(reservation[field] or "") != str(requested[field] or ""):
                        reservation_blockers.append(
                            f"runtime_session_reservation_{field}_mismatch"
                        )
                if str(reservation["status"] or "") != "reserved":
                    reservation_blockers.append(
                        "runtime_session_reservation_not_reserved"
                    )
                if reservation_blockers:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        reservation_blockers,
                    )
                created_at_epoch_ms = timestamp_epoch_ms(requested.get("created_at"))
                if created_at_epoch_ms is None:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_created_at_invalid"],
                    )
                try:
                    session_payload = bind_session_payload_to_automatic_trading_control(
                        conn,
                        payload=dict(requested["payload"]),
                        observed_at_epoch_ms=created_at_epoch_ms,
                    )
                except AutomaticTradingSessionBindingUnavailable:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_automatic_trading_not_enabled"],
                    )

                conn.execute(
                    """
                        INSERT INTO controlled_session_runtime_sessions (
                            session_id, session_fingerprint, issuance_fingerprint,
                            reservation_id, attestation_id, envelope_fingerprint,
                            authorization_id, account_alias, strategy_id,
                            operator_id, operator_approval_id, order_ids_json,
                            effective_at_epoch_ms, expires_at_epoch_ms,
                            effective_at, expires_at, max_order_rate_per_minute,
                            token_salt, token_hash, status, payload_json, created_at,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                    (
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["issuance_fingerprint"],
                        requested["reservation_id"],
                        requested["attestation_id"],
                        requested["envelope_fingerprint"],
                        requested["authorization_id"],
                        requested["account_alias"],
                        requested["strategy_id"],
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        _serialize_event_payload_json(requested["order_ids"]),
                        int(requested["effective_at_epoch_ms"]),
                        int(requested["expires_at_epoch_ms"]),
                        requested["requested_start_at"],
                        requested["requested_expires_at"],
                        int(requested["max_order_rate_per_minute"]),
                        requested["token_salt"],
                        requested["token_hash"],
                        "enabled",
                        _serialize_event_payload_json(session_payload),
                        requested["created_at"],
                        requested["created_at"],
                    ),
                )
                saved = conn.execute(
                    """
                        SELECT * FROM controlled_session_runtime_sessions
                        WHERE session_id = ?
                        LIMIT 1
                        """,
                    (requested["session_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "enabled",
                    "blockers": [],
                    "reused": False,
                    "session": dict(saved) if saved is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()
                return controlled_session_authority_rejection(
                    requested,
                    ["runtime_session_issuance_transaction_unavailable"],
                )
