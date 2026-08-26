"""Fail-closed response builders for controlled-execution persistence."""

from __future__ import annotations

from typing import Any


def controlled_broker_submit_rejection(
    intent: dict[str, Any], blockers: list[str]
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "external_call_permitted": False,
        "submit_intent_id": str(intent.get("submit_intent_id") or ""),
        "order_id": str(intent.get("order_id") or ""),
        "intent": {},
    }


def controlled_submission_clearance_rejection(
    clearance: dict[str, Any], blockers: list[str]
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "clearance_id": str(clearance.get("clearance_id") or ""),
        "submit_intent_id": str(clearance.get("submit_intent_id") or ""),
        "order_id": str(clearance.get("order_id") or ""),
        "clearance": {},
        "production_ledger_mutated": False,
    }


def controlled_submission_ledger_posting_rejection(
    requested: dict[str, Any], blockers: list[str]
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "posting_id": str(requested.get("posting_id") or ""),
        "clearance_id": str(requested.get("clearance_id") or ""),
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "production_ledger_mutated": False,
    }


def controlled_submission_ledger_correction_rejection(
    requested: dict[str, Any], blockers: list[str]
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "correction_id": str(requested.get("correction_id") or ""),
        "posting_id": str(requested.get("posting_id") or ""),
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "production_ledger_mutated": False,
    }


__all__ = [
    "controlled_broker_submit_rejection",
    "controlled_submission_clearance_rejection",
    "controlled_submission_ledger_correction_rejection",
    "controlled_submission_ledger_posting_rejection",
]
