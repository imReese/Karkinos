"""Persisted prior-execution closure gate for production daily candidates."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from server.services.execution_reconciliation import (
    build_current_plan_paper_actual_comparison,
)

DAILY_CANDIDATE_EXECUTION_CLOSURE_SCHEMA_VERSION = (
    "karkinos.daily_candidate_execution_closure.v1"
)
MAX_EXECUTION_CLOSURE_ORDERS = 500

_NO_FILL_TERMINAL_ITEM_STATUSES = {
    "cancelled",
    "controlled_submission_rejected",
}
_NO_FILL_TERMINAL_STATUSES = {"cancelled", "expired", "rejected"}


def build_daily_candidate_execution_closure(db: Any) -> dict[str, Any]:
    """Require every prior non-simulation OMS order to be currently closed."""

    blockers: list[str] = []
    order_reader = getattr(db, "list_oms_orders_sync", None)
    item_reader = getattr(
        db, "get_latest_execution_reconciliation_item_for_order_sync", None
    )
    if not callable(order_reader):
        return _missing_closure("execution_order_source_unavailable")
    if not callable(item_reader):
        return _missing_closure("execution_reconciliation_source_unavailable")

    rows = [
        dict(item)
        for item in order_reader(limit=MAX_EXECUTION_CLOSURE_ORDERS + 1) or []
        if isinstance(item, dict)
    ]
    scan_truncated = len(rows) > MAX_EXECUTION_CLOSURE_ORDERS
    if scan_truncated:
        blockers.append("execution_order_scan_truncated")
    production_orders = [
        order
        for order in rows[:MAX_EXECUTION_CLOSURE_ORDERS]
        if _execution_mode(order) != "paper_shadow"
    ]
    order_results: list[dict[str, Any]] = []
    for order in production_orders:
        order_id = str(order.get("order_id") or "")
        order_ref = _order_ref(order_id)
        order_blockers: list[str] = []
        if not order_id:
            order_blockers.append("execution_order_identity_missing")
            item = None
        else:
            item = item_reader(order_id)
        if not isinstance(item, dict):
            order_blockers.append("execution_reconciliation_item_missing")
            item = {}
        if str(item.get("order_id") or "") != order_id:
            order_blockers.append("execution_reconciliation_order_mismatch")
        if str(item.get("suggested_action") or "") != "no_action":
            order_blockers.append("execution_reconciliation_not_clear")

        item_payload = _object(item.get("payload_json"))
        comparison = _object(item_payload.get("plan_paper_actual_comparison"))
        actual = _object(comparison.get("actual"))
        comparison_fingerprint = str(comparison.get("evidence_fingerprint") or "")
        if actual:
            if comparison.get("status") != "pass":
                order_blockers.append("plan_paper_actual_comparison_not_pass")
            if not _is_sha256(comparison_fingerprint):
                order_blockers.append("plan_paper_actual_fingerprint_invalid")
            current = build_current_plan_paper_actual_comparison(db, order)
            if current.get("status") != "pass":
                order_blockers.append("plan_paper_actual_current_source_not_pass")
            if comparison_fingerprint != str(current.get("evidence_fingerprint") or ""):
                order_blockers.append("plan_paper_actual_current_source_changed")
        elif not _is_no_fill_terminal(order, item, item_payload):
            order_blockers.append("plan_paper_actual_comparison_missing")

        order_blockers = list(dict.fromkeys(order_blockers))
        blockers.extend(f"{blocker}:{order_ref}" for blocker in order_blockers)
        order_results.append(
            {
                "order_ref": order_ref,
                "oms_status": str(order.get("status") or "unknown"),
                "reconciliation_item_status": str(item.get("item_status") or "missing"),
                "plan_paper_actual_status": str(
                    comparison.get("status") or "not_available"
                ),
                "plan_paper_actual_fingerprint": comparison_fingerprint or None,
                "status": "pass" if not order_blockers else "blocked",
                "blockers": order_blockers,
            }
        )

    blockers = list(dict.fromkeys(blockers))
    core = {
        "schema_version": DAILY_CANDIDATE_EXECUTION_CLOSURE_SCHEMA_VERSION,
        "status": (
            "blocked"
            if blockers
            else "not_required" if not production_orders else "pass"
        ),
        "production_order_count": len(production_orders),
        "clear_order_count": sum(
            1 for item in order_results if item.get("status") == "pass"
        ),
        "scan_truncated": scan_truncated,
        "orders": order_results,
        "blockers": blockers,
        "persisted_evidence_only": True,
        "provider_contact_performed": False,
        "manual_review_required": bool(blockers),
        "authorizes_execution": False,
        "does_not_submit_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_change_capital_authority": True,
    }
    return {**core, "evidence_fingerprint": _fingerprint(core)}


def _is_no_fill_terminal(
    order: dict[str, Any],
    item: dict[str, Any],
    item_payload: dict[str, Any],
) -> bool:
    item_status = str(item.get("item_status") or "")
    if item_status in _NO_FILL_TERMINAL_ITEM_STATUSES:
        return True
    summary = _object(item_payload.get("controlled_submission_evidence_summary"))
    terminal_status = str(summary.get("terminal_status") or "")
    try:
        filled_quantity = float(summary.get("filled_quantity") or 0)
    except (TypeError, ValueError):
        return False
    return bool(
        item_status == "controlled_submission_reconciliation_cleared"
        and terminal_status in _NO_FILL_TERMINAL_STATUSES
        and filled_quantity == 0
        and str(order.get("status") or "")
        in {*_NO_FILL_TERMINAL_STATUSES, "reconciled"}
    )


def _execution_mode(order: dict[str, Any]) -> str:
    return str(_object(order.get("payload_json")).get("execution_mode") or "").lower()


def _order_ref(order_id: str) -> str:
    return hashlib.sha256(str(order_id or "missing").encode("utf-8")).hexdigest()[:16]


def _missing_closure(blocker: str) -> dict[str, Any]:
    core = {
        "schema_version": DAILY_CANDIDATE_EXECUTION_CLOSURE_SCHEMA_VERSION,
        "status": "blocked",
        "production_order_count": 0,
        "clear_order_count": 0,
        "scan_truncated": False,
        "orders": [],
        "blockers": [blocker],
        "persisted_evidence_only": True,
        "provider_contact_performed": False,
        "manual_review_required": True,
        "authorizes_execution": False,
        "does_not_submit_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_change_capital_authority": True,
    }
    return {**core, "evidence_fingerprint": _fingerprint(core)}


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _is_sha256(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    )


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
