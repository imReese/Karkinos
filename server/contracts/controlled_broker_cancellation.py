"""Stable contracts and canonical values for controlled broker cancellation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

CONTROLLED_BROKER_CANCELLATION_SCHEMA_VERSION = (
    "karkinos.controlled_broker_cancellation.v1"
)
CONTROLLED_BROKER_CANCELLATION_STATUS_SCHEMA_VERSION = (
    "karkinos.controlled_broker_cancellation_status.v1"
)
CONTROLLED_BROKER_CANCELLATION_ACKNOWLEDGEMENT = (
    "request_one_exact_broker_cancellation_once"
)
CONTROLLED_BROKER_CANCELLATION_RECOVERY_SCHEMA_VERSION = (
    "karkinos.controlled_broker_cancellation_recovery.v1"
)
CONTROLLED_BROKER_CANCELLATION_RECOVERY_ACKNOWLEDGEMENT = (
    "query_exact_broker_cancellation_outcome_once_without_recancel"
)
CONTROLLED_BROKER_CANCELLATION_MINIMUM_QUERY_WAIT_SECONDS = 30
CONTROLLED_BROKER_CANCELLATION_GATEWAY_HEALTH_MAX_AGE_SECONDS = 60

FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CANCELLABLE_LIFECYCLE_STATUSES = frozenset({"submitted", "open", "partially_filled"})
REQUIRED_RELEASE_ASSERTIONS = (
    "broker_agreement_reviewed",
    "connector_tested",
    "program_trading_reporting_reviewed",
    "risk_controls_reviewed",
)
CANCEL_RESULT_STATUSES = frozenset(
    {
        "accepted",
        "requested",
        "cancel_pending",
        "cancelled",
        "partial_cancelled",
        "reused",
        "rejected",
        "blocked",
        "not_found",
        "gateway_cancel_exception",
        "gateway_unavailable_after_prepare",
    }
)
QUERY_RESULT_STATUSES = frozenset(
    {
        "accepted",
        "submitted",
        "open",
        "partially_filled",
        "filled",
        "cancelled",
        "partial_cancelled",
        "rejected",
        "not_found",
        "gateway_query_exception",
        "gateway_unavailable_after_claim",
        "rejected_before_gateway_query",
    }
)


class ControlledBrokerCancellationRejected(ValueError):
    """Raised after a cancellation or recovery attempt fails closed."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


def cancellation_fingerprint(value: Any) -> str:
    """Return the canonical deterministic hash for cancellation evidence."""

    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def cancellation_json_dump(value: Any) -> str:
    """Serialize one canonical cancellation record."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def cancellation_json_object(value: Any) -> dict[str, Any]:
    """Decode a persisted JSON object, failing closed to an empty mapping."""

    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def cancellation_mapping(value: Any) -> dict[str, Any]:
    """Copy a mapping-shaped value without accepting arbitrary objects."""

    return dict(value) if isinstance(value, dict) else {}


def cancellation_decimal(value: Any) -> Decimal:
    """Parse a finite decimal, failing closed to zero for invalid evidence."""

    try:
        parsed = Decimal(str(value if value not in {None, ""} else "0"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
    return parsed if parsed.is_finite() else Decimal("0")


def cancellation_decimal_string(value: Any) -> str:
    """Return the canonical plain-string decimal representation."""

    parsed = cancellation_decimal(value)
    text = format(parsed, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def parse_cancellation_timestamp(value: Any) -> datetime | None:
    """Normalize an ISO timestamp to aware UTC."""

    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def cancellation_aware_utc(value: datetime) -> datetime:
    """Normalize a clock value to aware UTC."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
