"""Fail-closed response builders for controlled-session persistence."""

from __future__ import annotations

from typing import Any


def controlled_session_budget_rejection(
    reservation: dict[str, Any],
    blockers: list[str],
    *,
    before: dict[str, int] | None = None,
    after: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "reservation": {},
        "reservation_id": str(reservation.get("reservation_id") or ""),
        "attestation_id": str(reservation.get("attestation_id") or ""),
        "aggregate_before": before or {},
        "aggregate_after": after or {},
    }


def controlled_session_rate_admission_rejection(
    admission: dict[str, Any],
    blockers: list[str],
    *,
    admitted_before: int = 0,
    admitted_after: int = 0,
    effective_rate: int = 0,
    pause_event_id: str = "",
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "admission": {},
        "admission_id": str(admission.get("admission_id") or ""),
        "session_id": str(admission.get("session_id") or ""),
        "order_id": str(admission.get("order_id") or ""),
        "admitted_before": admitted_before,
        "admitted_after": admitted_after,
        "effective_rate": effective_rate,
        "pause_event_id": pause_event_id,
    }


def controlled_session_pause_rejection(
    pause: dict[str, Any], blockers: list[str]
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "state": {},
        "event": {},
        "pause_event_id": str(pause.get("pause_event_id") or ""),
        "session_id": str(pause.get("session_id") or ""),
    }


def controlled_session_authority_rejection(
    payload: dict[str, Any], blockers: list[str]
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "session": {},
        "revocation": {},
        "session_id": str(payload.get("session_id") or ""),
        "session_fingerprint": str(payload.get("session_fingerprint") or ""),
    }


def controlled_session_gate_snapshot_rejection(
    snapshot: dict[str, Any], blockers: list[str]
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "snapshot": {},
        "snapshot_id": str(snapshot.get("snapshot_id") or ""),
        "session_id": str(snapshot.get("session_id") or ""),
    }


__all__ = [
    "controlled_session_authority_rejection",
    "controlled_session_budget_rejection",
    "controlled_session_gate_snapshot_rejection",
    "controlled_session_pause_rejection",
    "controlled_session_rate_admission_rejection",
]
