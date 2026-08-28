"""Canonical contract for the persisted automatic-trading runtime gate."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

AUTOMATIC_TRADING_CONTROL_KEY = "automatic_trading"
AUTOMATIC_TRADING_CONTROL_SCHEMA_VERSION = "karkinos.automatic_trading_control.v1"
AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT = (
    "enable_bounded_automatic_trading_gate_without_capital_authority"
)
AUTOMATIC_TRADING_DISABLE_ACKNOWLEDGEMENT = "disable_automatic_trading_gate_immediately"
AUTOMATIC_TRADING_SESSION_BINDING_KEY = "automatic_trading_control_binding"
AUTOMATIC_TRADING_SESSION_BINDING_SCHEMA_VERSION = (
    "karkinos.automatic_trading_session_binding.v1"
)
AUTOMATIC_TRADING_CONTROL_FIELDS = frozenset(
    {
        "schema_version",
        "configured_enabled",
        "revision",
        "control_fingerprint",
        "reason",
        "operator_id",
        "effective_at",
        "effective_at_epoch_ms",
        "expires_at",
        "expires_at_epoch_ms",
        "last_disabled_at",
        "last_disabled_at_epoch_ms",
        "last_disabled_revision",
        "last_disabled_control_identity",
        "updated_at",
    }
)

_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_MINIMUM_TTL_MS = 60_000
_MAXIMUM_TTL_MS = 43_200_000


def automatic_trading_control_fingerprint(value: dict[str, Any]) -> str:
    """Return the identity of the fields that define one control revision."""

    payload = {
        field: value.get(field)
        for field in (
            "schema_version",
            "configured_enabled",
            "revision",
            "reason",
            "operator_id",
            "effective_at",
            "effective_at_epoch_ms",
            "expires_at",
            "expires_at_epoch_ms",
            "last_disabled_at",
            "last_disabled_at_epoch_ms",
            "last_disabled_revision",
            "last_disabled_control_identity",
            "updated_at",
        )
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def automatic_trading_disable_identity(*, revision: int, epoch_ms: int) -> str:
    """Return the stable identity of one gate-closing transition."""

    return hashlib.sha256(
        json.dumps(
            {
                "control_key": AUTOMATIC_TRADING_CONTROL_KEY,
                "disabled_at_epoch_ms": epoch_ms,
                "disabled_revision": revision,
                "schema_version": AUTOMATIC_TRADING_CONTROL_SCHEMA_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def automatic_trading_evidence(
    *,
    status: str,
    blocker: str,
    configured_enabled: bool = False,
    revision: int = 0,
    control_fingerprint: str = "",
) -> dict[str, Any]:
    """Build a non-authorizing fail-closed automatic-trading projection."""

    return {
        "schema_version": AUTOMATIC_TRADING_CONTROL_SCHEMA_VERSION,
        "configured_enabled": configured_enabled,
        "enabled": False,
        "status": status,
        "revision": revision,
        "control_fingerprint": control_fingerprint,
        "reason": "",
        "operator_id": "",
        "effective_at": None,
        "effective_at_epoch_ms": None,
        "expires_at": None,
        "expires_at_epoch_ms": None,
        "last_disabled_at": None,
        "last_disabled_at_epoch_ms": None,
        "last_disabled_revision": None,
        "last_disabled_control_identity": None,
        "updated_at": None,
        "blockers": [blocker],
        "evidence_available": False,
        "fail_closed": True,
        "required_acknowledgement": (
            AUTOMATIC_TRADING_DISABLE_ACKNOWLEDGEMENT
            if configured_enabled
            else AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT
        ),
        "grants_capital_authority": False,
        "automatic_broker_submission_implemented": False,
    }


def resolve_persisted_automatic_trading_control(
    value: Any,
    now_epoch_ms: int,
    expected_revision: int | None = None,
    expected_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Resolve one persisted control into canonical fail-closed evidence."""

    if (
        isinstance(now_epoch_ms, bool)
        or not isinstance(now_epoch_ms, int)
        or now_epoch_ms < 0
    ):
        return automatic_trading_evidence(
            status="unavailable",
            blocker="automatic_trading_clock_invalid",
        )
    if value is None:
        return automatic_trading_evidence(
            status="disabled",
            blocker="automatic_trading_control_missing",
        )
    if not isinstance(value, dict):
        return automatic_trading_evidence(
            status="unavailable",
            blocker="automatic_trading_control_invalid",
        )

    configured_enabled = value.get("configured_enabled")
    revision = value.get("revision")
    control_fingerprint = value.get("control_fingerprint")
    reason = value.get("reason")
    operator_id = value.get("operator_id")
    effective_at = value.get("effective_at")
    effective_at_epoch_ms = value.get("effective_at_epoch_ms")
    expires_at = value.get("expires_at")
    expires_at_epoch_ms = value.get("expires_at_epoch_ms")
    updated_at = value.get("updated_at")

    structurally_valid = (
        set(value) == AUTOMATIC_TRADING_CONTROL_FIELDS
        and value.get("schema_version") == AUTOMATIC_TRADING_CONTROL_SCHEMA_VERSION
        and isinstance(configured_enabled, bool)
        and isinstance(revision, int)
        and not isinstance(revision, bool)
        and revision >= 1
        and isinstance(control_fingerprint, str)
        and _FINGERPRINT_RE.fullmatch(control_fingerprint) is not None
        and isinstance(reason, str)
        and bool(reason.strip())
        and isinstance(operator_id, str)
        and bool(operator_id.strip())
        and isinstance(effective_at_epoch_ms, int)
        and not isinstance(effective_at_epoch_ms, bool)
        and effective_at_epoch_ms >= 0
        and timestamp_matches_epoch(effective_at, effective_at_epoch_ms)
        and timestamp_matches_epoch(updated_at, effective_at_epoch_ms)
        and _last_disabled_lineage_is_valid(
            value,
            configured_enabled=configured_enabled,
            revision=revision,
            effective_at_epoch_ms=effective_at_epoch_ms,
        )
    )
    if configured_enabled is True:
        structurally_valid = (
            structurally_valid
            and isinstance(expires_at_epoch_ms, int)
            and not isinstance(expires_at_epoch_ms, bool)
            and _MINIMUM_TTL_MS
            <= expires_at_epoch_ms - effective_at_epoch_ms
            <= _MAXIMUM_TTL_MS
            and timestamp_matches_epoch(expires_at, expires_at_epoch_ms)
        )
    elif configured_enabled is False:
        structurally_valid = (
            structurally_valid and expires_at is None and expires_at_epoch_ms is None
        )

    if structurally_valid:
        structurally_valid = (
            automatic_trading_control_fingerprint(value) == control_fingerprint
        )
    if not structurally_valid:
        return automatic_trading_evidence(
            status="unavailable",
            blocker="automatic_trading_control_invalid",
            configured_enabled=(
                configured_enabled if isinstance(configured_enabled, bool) else False
            ),
            revision=(
                revision
                if isinstance(revision, int)
                and not isinstance(revision, bool)
                and revision >= 0
                else 0
            ),
            control_fingerprint=(
                control_fingerprint if isinstance(control_fingerprint, str) else ""
            ),
        )

    evidence = {
        **value,
        "enabled": configured_enabled is True,
        "status": "enabled" if configured_enabled else "disabled",
        "blockers": ([] if configured_enabled else ["automatic_trading_disabled"]),
        "evidence_available": True,
        "fail_closed": True,
        "grants_capital_authority": False,
        "automatic_broker_submission_implemented": False,
    }
    if configured_enabled and now_epoch_ms < effective_at_epoch_ms:
        evidence.update(
            enabled=False,
            status="unavailable",
            blockers=["automatic_trading_control_not_yet_effective"],
        )
    elif configured_enabled and now_epoch_ms >= expires_at_epoch_ms:
        evidence.update(
            enabled=False,
            status="expired",
            blockers=["automatic_trading_control_expired"],
        )

    identity_blockers: list[str] = []
    if expected_revision is not None and revision != expected_revision:
        identity_blockers.append("automatic_trading_control_revision_mismatch")
    if expected_fingerprint is not None and control_fingerprint != expected_fingerprint:
        identity_blockers.append("automatic_trading_control_fingerprint_mismatch")
    if identity_blockers:
        evidence["enabled"] = False
        evidence["status"] = "unavailable"
        evidence["blockers"] = list(
            dict.fromkeys([*evidence["blockers"], *identity_blockers])
        )
    evidence["required_acknowledgement"] = (
        AUTOMATIC_TRADING_DISABLE_ACKNOWLEDGEMENT
        if configured_enabled is True
        else AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT
    )
    return evidence


def automatic_trading_transition_error(
    *, current_status: str, requested_enabled: bool
) -> str | None:
    """Return the canonical state-machine error for one requested transition."""

    if requested_enabled:
        if current_status != "disabled":
            return "automatic trading gate can only be enabled from disabled state"
        return None
    if current_status not in {"enabled", "expired"}:
        return (
            "automatic trading gate can only be disabled from enabled or expired state"
        )
    return None


def timestamp_epoch_ms(value: Any) -> int | None:
    """Parse one aware ISO timestamp into integer epoch milliseconds."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def timestamp_matches_epoch(value: Any, epoch_ms: int) -> bool:
    """Return whether an aware ISO timestamp denotes the exact epoch ms."""

    parsed_epoch_ms = timestamp_epoch_ms(value)
    return parsed_epoch_ms is not None and parsed_epoch_ms == epoch_ms


def _last_disabled_lineage_is_valid(
    value: dict[str, Any],
    *,
    configured_enabled: Any,
    revision: Any,
    effective_at_epoch_ms: Any,
) -> bool:
    fields = (
        value.get("last_disabled_at"),
        value.get("last_disabled_at_epoch_ms"),
        value.get("last_disabled_revision"),
        value.get("last_disabled_control_identity"),
    )
    if all(item is None for item in fields):
        return configured_enabled is True and revision == 1
    if any(item is None for item in fields):
        return False

    last_disabled_at, last_disabled_at_epoch_ms, last_disabled_revision, identity = (
        fields
    )
    if (
        not isinstance(last_disabled_at_epoch_ms, int)
        or isinstance(last_disabled_at_epoch_ms, bool)
        or last_disabled_at_epoch_ms < 0
        or not isinstance(last_disabled_revision, int)
        or isinstance(last_disabled_revision, bool)
        or last_disabled_revision < 1
        or not isinstance(identity, str)
        or _FINGERPRINT_RE.fullmatch(identity) is None
        or not timestamp_matches_epoch(last_disabled_at, last_disabled_at_epoch_ms)
        or last_disabled_at_epoch_ms > effective_at_epoch_ms
        or identity
        != automatic_trading_disable_identity(
            revision=last_disabled_revision,
            epoch_ms=last_disabled_at_epoch_ms,
        )
    ):
        return False
    if configured_enabled is False:
        return (
            last_disabled_revision == revision
            and last_disabled_at_epoch_ms == effective_at_epoch_ms
        )
    return configured_enabled is True and last_disabled_revision < revision
