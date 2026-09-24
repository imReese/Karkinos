"""Resolve locally reviewed broker board access for candidate eligibility."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from server.contracts.content_identity import content_fingerprint

BOARD_NAMES = ("chinext", "star", "beijing")
BOARD_PERMISSION_REVIEW_DAYS = 30
BOARD_PERMISSION_SOURCE = "self_reported_broker_account"
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def resolve_board_buy_permissions(config: Any, decision_date: str) -> dict[str, Any]:
    """A dated self-report may qualify a candidate; it never grants trade authority."""
    unknown = {board: "unknown" for board in BOARD_NAMES}
    result: dict[str, Any] = {
        "status": "unavailable",
        "resolved_for_date": decision_date,
        "evidence_fingerprint": None,
        "boards": unknown,
        "source": None,
        "reviewed_at": None,
        "expires_on": None,
    }
    raw = getattr(config, "account_board_permissions", None)
    if is_dataclass(raw):
        payload = asdict(raw)
    elif isinstance(raw, dict):
        payload = dict(raw)
    else:
        return result
    if (
        payload.get("source") != BOARD_PERMISSION_SOURCE
        or not str(payload.get("reviewed_by") or "").strip()
        or not isinstance(payload.get("boards"), dict)
    ):
        return result
    boards = payload["boards"]
    if set(boards) - set(BOARD_NAMES) or any(
        status not in {"enabled", "disabled", "unknown"} for status in boards.values()
    ):
        return result
    try:
        decision_day = date.fromisoformat(decision_date)
        reviewed = datetime.fromisoformat(str(payload.get("reviewed_at") or ""))
    except ValueError:
        return result
    if reviewed.tzinfo is None or reviewed.utcoffset() is None:
        return result
    reviewed_day = reviewed.astimezone(_SHANGHAI).date()
    expires_on = reviewed_day + timedelta(days=BOARD_PERMISSION_REVIEW_DAYS)
    if not reviewed_day <= decision_day <= expires_on:
        return result
    identity = {
        "reviewed_at": reviewed.isoformat(),
        "reviewed_by": str(payload["reviewed_by"]).strip(),
        "source": BOARD_PERMISSION_SOURCE,
        "boards": {board: boards.get(board, "unknown") for board in BOARD_NAMES},
    }
    return {
        "status": "current",
        "resolved_for_date": decision_date,
        "evidence_fingerprint": "sha256:" + content_fingerprint(identity),
        "boards": identity["boards"],
        "source": BOARD_PERMISSION_SOURCE,
        "reviewed_at": identity["reviewed_at"],
        "expires_on": expires_on.isoformat(),
    }
