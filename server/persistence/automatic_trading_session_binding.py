"""Transaction-local binding between bounded sessions and the runtime gate."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from server.contracts.automatic_trading import (
    AUTOMATIC_TRADING_CONTROL_KEY,
    AUTOMATIC_TRADING_SESSION_BINDING_KEY,
    AUTOMATIC_TRADING_SESSION_BINDING_SCHEMA_VERSION,
    resolve_persisted_automatic_trading_control,
)

_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "revision",
        "control_fingerprint",
        "last_disabled_at_epoch_ms",
        "last_disabled_revision",
        "last_disabled_control_identity",
        "observed_at_epoch_ms",
    }
)
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


class AutomaticTradingSessionBindingUnavailable(ValueError):
    """Raised when a bounded session cannot bind an enabled canonical gate."""


def read_automatic_trading_control_in_transaction(
    conn: sqlite3.Connection,
    *,
    now_epoch_ms: int,
) -> tuple[Any, dict[str, Any]]:
    """Read and resolve the gate using the caller's open SQLite transaction."""

    row = conn.execute(
        """
            SELECT value_json FROM runtime_controls
            WHERE key = ?
            LIMIT 1
            """,
        (AUTOMATIC_TRADING_CONTROL_KEY,),
    ).fetchone()
    value: Any = None
    if row is not None:
        try:
            value = json.loads(row["value_json"])
        except (json.JSONDecodeError, TypeError):
            value = {"invalid_persisted_control": True}
    return value, resolve_persisted_automatic_trading_control(
        value,
        now_epoch_ms=now_epoch_ms,
    )


def bind_session_payload_to_automatic_trading_control(
    conn: sqlite3.Connection,
    *,
    payload: dict[str, Any],
    observed_at_epoch_ms: int,
) -> dict[str, Any]:
    """Bind one session issuance to the gate observed under the same write lock."""

    _, evidence = read_automatic_trading_control_in_transaction(
        conn,
        now_epoch_ms=observed_at_epoch_ms,
    )
    if (
        evidence.get("status") != "enabled"
        or evidence.get("enabled") is not True
        or evidence.get("evidence_available") is not True
    ):
        raise AutomaticTradingSessionBindingUnavailable(
            "automatic trading control is not enabled for session issuance"
        )
    binding = {
        "schema_version": AUTOMATIC_TRADING_SESSION_BINDING_SCHEMA_VERSION,
        "status": str(evidence.get("status") or "unavailable"),
        "revision": evidence.get("revision"),
        "control_fingerprint": str(evidence.get("control_fingerprint") or ""),
        "last_disabled_at_epoch_ms": evidence.get("last_disabled_at_epoch_ms"),
        "last_disabled_revision": evidence.get("last_disabled_revision"),
        "last_disabled_control_identity": evidence.get(
            "last_disabled_control_identity"
        ),
        "observed_at_epoch_ms": observed_at_epoch_ms,
    }
    return {**payload, AUTOMATIC_TRADING_SESSION_BINDING_KEY: binding}


def automatic_trading_binding_from_session_payload(value: Any) -> dict[str, Any] | None:
    """Return one structurally valid issuance binding or ``None``."""

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(value, dict):
        return None
    binding = value.get(AUTOMATIC_TRADING_SESSION_BINDING_KEY)
    if not isinstance(binding, dict) or set(binding) != _BINDING_FIELDS:
        return None
    revision = binding.get("revision")
    fingerprint = binding.get("control_fingerprint")
    observed_at_epoch_ms = binding.get("observed_at_epoch_ms")
    last_disabled_fields = (
        binding.get("last_disabled_at_epoch_ms"),
        binding.get("last_disabled_revision"),
        binding.get("last_disabled_control_identity"),
    )
    last_disabled_lineage_valid = all(
        item is None for item in last_disabled_fields
    ) or (
        all(item is not None for item in last_disabled_fields)
        and isinstance(last_disabled_fields[0], int)
        and not isinstance(last_disabled_fields[0], bool)
        and last_disabled_fields[0] >= 0
        and isinstance(last_disabled_fields[1], int)
        and not isinstance(last_disabled_fields[1], bool)
        and last_disabled_fields[1] >= 1
        and isinstance(last_disabled_fields[2], str)
        and _FINGERPRINT_RE.fullmatch(last_disabled_fields[2]) is not None
    )
    if (
        not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
        or not isinstance(fingerprint, str)
        or _FINGERPRINT_RE.fullmatch(fingerprint) is None
        or not isinstance(observed_at_epoch_ms, int)
        or isinstance(observed_at_epoch_ms, bool)
        or observed_at_epoch_ms < 0
        or binding.get("schema_version")
        != AUTOMATIC_TRADING_SESSION_BINDING_SCHEMA_VERSION
        or binding.get("status") != "enabled"
        or not last_disabled_lineage_valid
    ):
        return None
    return dict(binding)


def automatic_trading_session_reuse_blockers(
    conn: sqlite3.Connection,
    *,
    session_payload: Any,
    observed_at_epoch_ms: int,
) -> list[str]:
    """Validate an idempotently reused session against the current gate."""

    _, evidence = read_automatic_trading_control_in_transaction(
        conn,
        now_epoch_ms=observed_at_epoch_ms,
    )
    if (
        evidence.get("status") != "enabled"
        or evidence.get("enabled") is not True
        or evidence.get("evidence_available") is not True
    ):
        return ["runtime_session_automatic_trading_not_enabled"]

    binding = automatic_trading_binding_from_session_payload(session_payload)
    if binding is None or any(
        binding[field] != evidence.get(field)
        for field in (
            "revision",
            "control_fingerprint",
            "last_disabled_at_epoch_ms",
            "last_disabled_revision",
            "last_disabled_control_identity",
        )
    ):
        return ["runtime_session_automatic_trading_binding_mismatch"]
    return []
