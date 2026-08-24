"""Pure gateway-result classification for controlled broker submission."""

from __future__ import annotations

import re
from typing import Any

from server.contracts.controlled_broker_submission import GATEWAY_RESULT_STATUSES
from server.services.controlled_broker_submission_values import (
    FINGERPRINT_PATTERN as _FINGERPRINT_PATTERN,
)
from server.services.controlled_broker_submission_values import (
    ID_PATTERN as _ID_PATTERN,
)


def classify_gateway_result(
    raw: dict[str, Any],
    *,
    client_order_id: str,
    order_fingerprint: str,
    allow_definitive_not_found: bool,
) -> str:
    status = str(raw.get("status") or "").lower()
    if str(raw.get("client_order_id") or "") != client_order_id:
        return "submission_unknown"
    raw_order_fingerprint = str(raw.get("order_fingerprint") or "")
    if raw_order_fingerprint and raw_order_fingerprint != order_fingerprint:
        return "submission_unknown"
    if (
        status in {"accepted", "submitted", "open", "partially_filled", "filled"}
        and raw.get("submitted") is True
        and _ID_PATTERN.fullmatch(str(raw.get("broker_order_id") or ""))
    ):
        return "submitted"
    if (
        status == "rejected"
        and raw.get("submitted") is False
        and raw.get("definitive") is True
        and not str(raw.get("broker_order_id") or "")
    ):
        return "rejected"
    if (
        allow_definitive_not_found
        and status == "not_found"
        and raw.get("submitted") is False
        and raw.get("definitive") is True
        and not str(raw.get("broker_order_id") or "")
    ):
        return "rejected"
    return "submission_unknown"


def sanitize_gateway_result(raw: dict[str, Any]) -> dict[str, Any]:
    status = str(raw.get("status") or "").lower()
    client_order_id = str(raw.get("client_order_id") or "")
    order_fingerprint = str(raw.get("order_fingerprint") or "")
    broker_order_id = str(raw.get("broker_order_id") or "")
    error_type = str(raw.get("error_type") or "")
    return {
        "status": status if status in GATEWAY_RESULT_STATUSES else "unknown",
        "client_order_id": (
            client_order_id if _ID_PATTERN.fullmatch(client_order_id) else ""
        ),
        "order_fingerprint": (
            order_fingerprint
            if _FINGERPRINT_PATTERN.fullmatch(order_fingerprint)
            else ""
        ),
        "broker_order_id": (
            broker_order_id if _ID_PATTERN.fullmatch(broker_order_id) else ""
        ),
        "submitted": (
            raw.get("submitted") if raw.get("submitted") in {True, False} else None
        ),
        "definitive": raw.get("definitive") is True,
        "error_type": (
            error_type
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", error_type)
            else ""
        ),
    }
