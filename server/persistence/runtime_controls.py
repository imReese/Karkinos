"""SQLite repository for persisted runtime control key/value state."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from server.contracts.automatic_trading import (
    AUTOMATIC_TRADING_CONTROL_KEY,
    AUTOMATIC_TRADING_DISABLE_ACKNOWLEDGEMENT,
    AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT,
    automatic_trading_disable_identity,
    automatic_trading_transition_error,
    resolve_persisted_automatic_trading_control,
)
from server.persistence.event_log import insert_event_sync

_AUTOMATIC_TRADING_EVENT_SOURCE = "trading_controls"
_AUTOMATIC_TRADING_EVENT_ENTITY_TYPE = "automatic_trading_control"


class RuntimeControlRepository:
    """Own runtime-control persistence without interpreting control authority."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    def set_value(self, key: str, value: dict[str, Any]) -> None:
        if key == AUTOMATIC_TRADING_CONTROL_KEY:
            raise ValueError(
                "automatic trading control requires the dedicated audited CAS"
            )
        with sqlite3.connect(self._database_path) as conn:
            conn.execute(
                """
                INSERT INTO runtime_controls (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (
                    key,
                    json.dumps(value, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

    def get_value(self, key: str) -> dict[str, Any] | None:
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT value_json FROM runtime_controls WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            return json.loads(row["value_json"])

    def compare_and_set_automatic_trading(
        self,
        *,
        expected_revision: int,
        value: dict[str, Any],
        acknowledgement: str,
    ) -> dict[str, Any]:
        """Atomically replace the automatic-trading control and append its audit."""

        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise ValueError("expected_revision must be a non-negative integer")
        if not isinstance(value, dict):
            raise ValueError("automatic trading control value must be an object")
        configured_enabled = value.get("configured_enabled")
        if not isinstance(configured_enabled, bool):
            raise ValueError("automatic trading configured_enabled must be a boolean")
        expected_acknowledgement = (
            AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT
            if configured_enabled
            else AUTOMATIC_TRADING_DISABLE_ACKNOWLEDGEMENT
        )
        if acknowledgement != expected_acknowledgement:
            raise ValueError(
                "acknowledgement does not match the requested automatic trading action"
            )
        proposed_epoch_ms = value.get("effective_at_epoch_ms")
        if (
            not isinstance(proposed_epoch_ms, int)
            or isinstance(proposed_epoch_ms, bool)
            or proposed_epoch_ms < 0
        ):
            raise ValueError(
                "automatic trading control effective_at_epoch_ms is invalid"
            )

        with sqlite3.connect(self._database_path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT value_json FROM runtime_controls WHERE key = ? LIMIT 1",
                (AUTOMATIC_TRADING_CONTROL_KEY,),
            ).fetchone()
            if row is None:
                current = None
                current_state = resolve_persisted_automatic_trading_control(
                    None,
                    now_epoch_ms=proposed_epoch_ms,
                )
            else:
                current = _decode_present_control_value(row["value_json"])
                current_effective_epoch_ms = (
                    current.get("effective_at_epoch_ms")
                    if isinstance(current, dict)
                    else None
                )
                structural_state = resolve_persisted_automatic_trading_control(
                    current,
                    now_epoch_ms=(
                        current_effective_epoch_ms
                        if isinstance(current_effective_epoch_ms, int)
                        and not isinstance(current_effective_epoch_ms, bool)
                        and current_effective_epoch_ms >= 0
                        else proposed_epoch_ms
                    ),
                )
                if structural_state.get("status") == "unavailable":
                    conn.rollback()
                    raise RuntimeError(
                        "automatic trading control persisted state is unavailable"
                    )
                if proposed_epoch_ms < int(current_effective_epoch_ms):
                    conn.rollback()
                    raise ValueError(
                        "automatic trading control action timestamp cannot move backwards"
                    )
                current_state = resolve_persisted_automatic_trading_control(
                    current,
                    now_epoch_ms=proposed_epoch_ms,
                )
            current_revision = int(current_state.get("revision") or 0)
            if current_revision != expected_revision:
                conn.rollback()
                return {
                    "updated": False,
                    "current_revision": current_revision,
                    "value": current,
                    "event_id": 0,
                }

            transition_error = automatic_trading_transition_error(
                current_status=str(current_state.get("status") or "unavailable"),
                requested_enabled=configured_enabled,
            )
            if transition_error:
                conn.rollback()
                raise ValueError(transition_error)

            next_revision = expected_revision + 1
            if value.get("revision") != next_revision:
                conn.rollback()
                raise ValueError(
                    "automatic trading control revision must advance by exactly one"
                )
            proposed_state = resolve_persisted_automatic_trading_control(
                value,
                now_epoch_ms=proposed_epoch_ms,
            )
            expected_status = "enabled" if configured_enabled else "disabled"
            if (
                proposed_state.get("status") != expected_status
                or proposed_state.get("evidence_available") is not True
            ):
                conn.rollback()
                raise ValueError("automatic trading control value is invalid")
            expected_lineage = _expected_last_disabled_lineage(
                current,
                configured_enabled=configured_enabled,
                revision=next_revision,
                effective_at=str(value["effective_at"]),
                effective_at_epoch_ms=int(value["effective_at_epoch_ms"]),
            )
            if any(
                value.get(field) != expected
                for field, expected in expected_lineage.items()
            ):
                conn.rollback()
                raise ValueError(
                    "automatic trading control last-disabled lineage is invalid"
                )

            updated_at = str(value["updated_at"])
            control_fingerprint = str(value["control_fingerprint"])

            conn.execute(
                """
                INSERT INTO runtime_controls (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (
                    AUTOMATIC_TRADING_CONTROL_KEY,
                    json.dumps(
                        value,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    updated_at,
                ),
            )
            event_type = (
                "automatic_trading.control_enabled"
                if configured_enabled
                else "automatic_trading.control_disabled"
            )
            event = insert_event_sync(
                conn,
                event_type=event_type,
                timestamp=updated_at,
                entity_type=_AUTOMATIC_TRADING_EVENT_ENTITY_TYPE,
                entity_id=control_fingerprint,
                source=_AUTOMATIC_TRADING_EVENT_SOURCE,
                source_ref=f"revision:{next_revision}",
                payload={
                    **value,
                    "action": "enable" if configured_enabled else "disable",
                    "expected_revision": expected_revision,
                    "previous_control_fingerprint": str(
                        (current or {}).get("control_fingerprint") or ""
                    ),
                    "acknowledgement": acknowledgement,
                    "grants_capital_authority": False,
                    "automatic_broker_submission_implemented": False,
                },
            )
            conn.commit()
            return {
                "updated": True,
                "current_revision": next_revision,
                "value": dict(value),
                "event_id": int(event.lastrowid or 0),
            }


def _decode_present_control_value(value: Any) -> Any:
    if not isinstance(value, str):
        raise RuntimeError("automatic trading control persisted state is unavailable")
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "automatic trading control persisted state is unavailable"
        ) from exc


def _expected_last_disabled_lineage(
    current: Any,
    *,
    configured_enabled: bool,
    revision: int,
    effective_at: str,
    effective_at_epoch_ms: int,
) -> dict[str, Any]:
    if not configured_enabled:
        return {
            "last_disabled_at": effective_at,
            "last_disabled_at_epoch_ms": effective_at_epoch_ms,
            "last_disabled_revision": revision,
            "last_disabled_control_identity": automatic_trading_disable_identity(
                revision=revision,
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
