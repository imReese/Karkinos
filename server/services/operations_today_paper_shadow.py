"""Paper/shadow review projection for Operations Today."""

from __future__ import annotations

from typing import Any

from server.services.operations_today_values import dedupe as _dedupe
from server.services.operations_today_values import dict_value as _dict
from server.services.operations_today_values import int_value as _int
from server.services.operations_today_values import (
    is_daily_shadow_order as _is_daily_shadow_order,
)
from server.services.operations_today_values import json_list as _json_list
from server.services.operations_today_values import (
    latest_timestamp as _latest_timestamp,
)
from server.services.operations_today_values import list_of_dicts as _list_of_dicts
from server.services.operations_today_values import list_value as _list
from server.services.operations_today_values import (
    paper_shadow_default_next_step as _paper_shadow_default_next_step,
)
from server.services.operations_today_values import (
    paper_shadow_status_can_accept_manual_handoff as _paper_shadow_status_can_accept_manual_handoff,
)
from server.services.operations_today_values import payload as _payload
from server.services.operations_today_values import payload_status as _payload_status


def _paper_shadow_summary(
    *,
    plan_date: str,
    trading_plan: dict[str, Any],
    order_facts: list[dict[str, Any]],
    fill_facts: list[dict[str, Any]],
) -> dict[str, Any]:
    order_intent_count = _int(trading_plan.get("order_intent_count"))
    run_id = f"shadow:{plan_date}"
    orders = [
        order
        for order in order_facts
        if _is_daily_shadow_order(order, run_id=run_id, plan_date=plan_date)
    ]
    order_ids = {
        str(order.get("order_id")) for order in orders if order.get("order_id")
    }
    fills = [fill for fill in fill_facts if str(fill.get("order_id")) in order_ids]
    divergence_statuses = [
        status
        for order in orders
        if (status := _payload_status(order, "divergence_status")) is not None
    ]
    reviewed_count = len(divergence_statuses)
    if order_intent_count == 0:
        status = "not_required"
        next_step = "none"
    elif not orders:
        status = "not_run"
        next_step = "run_paper_shadow_daily"
    elif reviewed_count < len(orders):
        status = "review_required"
        next_step = "review_shadow_divergence"
    elif all(item == "within_expectations" for item in divergence_statuses):
        status = "within_expectations"
        next_step = "review_manual_confirmation"
    else:
        status = "diverged"
        next_step = "resolve_shadow_divergence"
    return {
        "status": status,
        "effective_status": status,
        "run_id": run_id if orders or order_intent_count > 0 else None,
        "order_intent_count": order_intent_count,
        "simulated_order_count": len(orders),
        "simulated_fill_count": len(fills),
        "divergence_reviewed_count": reviewed_count,
        "divergence_status": status,
        "next_manual_review_step": next_step,
        "last_run_at": _latest_timestamp(orders + fills),
        "orders": [
            {
                "order_id": order.get("order_id"),
                "symbol": order.get("symbol"),
                "status": order.get("status"),
                "divergence_status": _payload_status(order, "divergence_status"),
            }
            for order in orders[:5]
        ],
        "review_queue": [],
        "manual_handoff": _paper_shadow_manual_handoff(
            status=status,
            effective_status=status,
            review_status=None,
            reviewed_at=None,
            reviewer=None,
            next_manual_review_step=next_step,
            review_queue=[],
        ),
    }


def _paper_shadow_run_summary(
    run: dict[str, Any],
    *,
    fallback_order_intent_count: int,
) -> dict[str, Any]:
    payload = _payload(run)
    review = _dict(payload.get("review"))
    orders = _list_of_dicts(payload.get("orders"))
    fills = _list_of_dicts(payload.get("fills"))
    status = str(run.get("status") or "not_run")
    divergence_status = str(run.get("divergence_status") or status)
    review_status = str(
        run.get("review_status") or review.get("review_status") or ""
    ).strip()
    effective_status = _paper_shadow_effective_status(
        status=status,
        review_status=review_status,
    )
    review_queue = _list_of_dicts(payload.get("review_queue"))
    reviewed_count = len(
        [order for order in orders if str(order.get("divergence_status") or "").strip()]
    )
    review_queue = review_queue or _fallback_paper_shadow_review_queue(
        run_id=run.get("run_id"),
        status=status,
        orders=orders,
        divergence_summary=_dict(payload.get("divergence_summary")),
    )
    next_manual_review_step = _paper_shadow_default_next_step(
        status=status,
        value=run.get("next_manual_review_step"),
        review_status=review_status,
    )
    return {
        "status": status,
        "effective_status": effective_status,
        "run_id": run.get("run_id"),
        "input_fingerprint": run.get("input_fingerprint"),
        "input_snapshot": _dict(payload.get("input_snapshot")),
        "evidence_refs": _list(payload.get("evidence_refs")),
        "order_intent_count": _int(
            run.get("order_intent_count"),
            fallback_order_intent_count,
        ),
        "simulated_order_count": _int(
            run.get("simulated_order_count"),
            len(orders),
        ),
        "simulated_fill_count": _int(run.get("simulated_fill_count"), len(fills)),
        "divergence_reviewed_count": reviewed_count,
        "divergence_status": divergence_status,
        "review_status": review_status,
        "reviewed_at": run.get("reviewed_at") or review.get("reviewed_at"),
        "reviewer": run.get("reviewer") or review.get("reviewer"),
        "next_manual_review_step": next_manual_review_step,
        "last_run_at": run.get("updated_at") or run.get("created_at"),
        "limitations": _json_list(run.get("limitations_json")),
        "orders": orders[:5],
        "review_queue": review_queue,
        "divergence_summary": _dict(payload.get("divergence_summary")),
        "manual_handoff": _paper_shadow_manual_handoff(
            status=status,
            effective_status=effective_status,
            review_status=review_status or None,
            reviewed_at=run.get("reviewed_at") or review.get("reviewed_at"),
            reviewer=run.get("reviewer") or review.get("reviewer"),
            next_manual_review_step=next_manual_review_step,
            review_queue=review_queue,
        ),
    }


def _paper_shadow_manual_handoff(
    *,
    status: str,
    effective_status: str,
    review_status: str | None,
    reviewed_at: Any,
    reviewer: Any,
    next_manual_review_step: str,
    review_queue: list[dict[str, Any]],
) -> dict[str, Any]:
    run_status = str(status or "").strip().lower()
    effective = str(effective_status or run_status).strip().lower()
    review = str(review_status or "").strip() or None
    required_actions = _paper_shadow_handoff_required_actions(
        next_manual_review_step=next_manual_review_step,
        review_queue=review_queue,
    )
    ready = False
    handoff_status = "blocked_by_paper_shadow_review"
    blockers: list[str] = []

    if effective == "accepted_for_manual_confirmation":
        ready = True
        handoff_status = "ready_after_accepted_review"
        required_actions = ["review_manual_confirmation"]
    elif run_status == "within_expectations":
        ready = True
        handoff_status = "ready_after_clean_simulation"
        required_actions = ["review_manual_confirmation"]
    elif run_status == "not_required":
        handoff_status = "not_required"
        required_actions = ["none"]
    elif run_status == "not_run":
        handoff_status = "paper_shadow_required"
        blockers = ["paper_shadow_run_not_run"]
    elif run_status == "running":
        handoff_status = "waiting_for_paper_shadow_run"
        blockers = ["paper_shadow_run_running"]
    elif run_status == "failed":
        handoff_status = "blocked_by_failed_run"
        blockers = ["failed_paper_shadow_run"]
    elif review == "needs_rerun":
        handoff_status = "blocked_by_review_requested_rerun"
        blockers = ["paper_shadow_review_requested_rerun"]
    elif run_status in {"diverged", "review_required"}:
        handoff_status = "blocked_by_unresolved_divergence"
        blockers = ["unresolved_paper_shadow_divergence"]

    return {
        "ready": ready,
        "status": handoff_status,
        "blockers": blockers,
        "required_actions": required_actions,
        "review_queue_count": len(review_queue),
        "highest_severity": _paper_shadow_highest_review_severity(review_queue),
        "review_status": review,
        "reviewed_at": reviewed_at,
        "reviewer": reviewer,
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }


def _paper_shadow_handoff_required_actions(
    *,
    next_manual_review_step: str,
    review_queue: list[dict[str, Any]],
) -> list[str]:
    actions = [
        str(item.get("required_action") or "").strip()
        for item in review_queue
        if str(item.get("required_action") or "").strip()
    ]
    next_step = str(next_manual_review_step or "").strip()
    if next_step:
        actions.append(next_step)
    return _dedupe(actions) or ["none"]


def _paper_shadow_highest_review_severity(
    review_queue: list[dict[str, Any]],
) -> str | None:
    rank = {"danger": 3, "warning": 2, "info": 1}
    highest: str | None = None
    highest_rank = 0
    for item in review_queue:
        severity = str(item.get("severity") or "").strip().lower()
        severity_rank = rank.get(severity, 0)
        if severity_rank > highest_rank:
            highest = severity
            highest_rank = severity_rank
    return highest


def _fallback_paper_shadow_review_queue(
    *,
    run_id: Any,
    status: str,
    orders: list[dict[str, Any]],
    divergence_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    run_status = str(status or "").strip().lower()
    if run_status in {"not_run", "not_required", "within_expectations"}:
        return []
    queue: list[dict[str, Any]] = []
    for order in orders:
        item = _fallback_paper_shadow_review_item(
            run_id=run_id,
            run_status=run_status,
            order=order,
        )
        if item:
            queue.append(item)
    queue.extend(
        _fallback_missing_simulation_review_items(
            run_id=run_id,
            divergence_summary=divergence_summary,
        )
    )
    return queue


def _fallback_paper_shadow_review_item(
    *,
    run_id: Any,
    run_status: str,
    order: dict[str, Any],
) -> dict[str, Any] | None:
    order_status = str(order.get("status") or "").strip().lower()
    divergence_status = str(order.get("divergence_status") or "").strip().lower()
    if order_status == "filled" and divergence_status == "within_expectations":
        return None

    intent_ref = str(
        _dict(order.get("order_intent")).get("action_ref")
        or order.get("order_intent_ref")
        or ""
    ).strip()
    order_id = str(order.get("order_id") or "").strip()
    required_action, severity, reason = _fallback_paper_shadow_review_action(
        run_status=run_status,
        order_status=order_status,
        divergence_status=divergence_status,
        intent_ref=intent_ref,
        order_id=order_id,
    )
    item = {
        "review_id": f"{run_id}:{_fallback_review_suffix(intent_ref or order_id)}",
        "order_intent_ref": intent_ref,
        "order_id": order_id or None,
        "symbol": order.get("symbol"),
        "status": order_status or "review_required",
        "divergence_status": divergence_status or "review_required",
        "severity": severity,
        "required_action": required_action,
        "reason": reason,
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }
    transition_evidence = _fallback_paper_shadow_oms_evidence(
        order=order,
        order_id=order_id,
    )
    if transition_evidence:
        item.update(transition_evidence)
        item["evidence_refs"] = _dedupe(
            [intent_ref]
            + ([f"paper_order:{order_id}"] if order_id else [])
            + _list(transition_evidence.get("oms_transition_refs"))
        )
    for key in ("filled_quantity", "remaining_quantity"):
        if order.get(key) is not None:
            item[key] = order.get(key)
    return item


def _fallback_paper_shadow_oms_evidence(
    *,
    order: dict[str, Any],
    order_id: str,
) -> dict[str, Any]:
    transitions = [
        _fallback_paper_shadow_oms_transition(item)
        for item in _list_of_dicts(order.get("oms_transitions"))
    ]
    transitions = [item for item in transitions if item.get("to_status")]
    if not transitions:
        return {}

    transition_refs = [
        f"oms_transition:{order_id}:{item['sequence']}:{item['to_status']}"
        for item in transitions
        if order_id and item.get("sequence") is not None and item.get("to_status")
    ]
    evidence: dict[str, Any] = {
        "oms_status_path": [str(item["to_status"]) for item in transitions],
        "oms_transition_refs": transition_refs,
        "oms_transitions": transitions,
    }
    terminal = _fallback_terminal_oms_transition(
        transitions=transitions,
        status=str(order.get("status") or ""),
    )
    if terminal:
        terminal_status = str(terminal.get("to_status") or "")
        evidence["terminal_status"] = terminal_status
        evidence["terminal_reason"] = str(terminal.get("reason") or "")
        if order_id and terminal.get("sequence") is not None and terminal_status:
            evidence["terminal_oms_transition_ref"] = (
                f"oms_transition:{order_id}:{terminal['sequence']}:{terminal_status}"
            )
    return evidence


def _fallback_paper_shadow_oms_transition(
    transition: dict[str, Any],
) -> dict[str, Any]:
    return {
        "sequence": transition.get("sequence"),
        "from_status": transition.get("from_status"),
        "to_status": transition.get("to_status"),
        "source": transition.get("source"),
        "reason": transition.get("reason") or "",
        "filled_quantity": transition.get("filled_quantity"),
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }


def _fallback_terminal_oms_transition(
    *,
    transitions: list[dict[str, Any]],
    status: str,
) -> dict[str, Any] | None:
    terminal_statuses = {"rejected", "cancelled", "expired", "failed"}
    expected_status = str(status or "").strip().lower()
    if expected_status not in terminal_statuses:
        return None
    return next(
        (
            item
            for item in reversed(transitions)
            if str(item.get("to_status") or "").strip().lower() == expected_status
        ),
        None,
    )


def _fallback_paper_shadow_review_action(
    *,
    run_status: str,
    order_status: str,
    divergence_status: str,
    intent_ref: str,
    order_id: str,
) -> tuple[str, str, str]:
    if (
        run_status == "failed"
        or order_status == "failed"
        or divergence_status == "failed"
    ):
        ref = intent_ref or order_id or "paper/shadow order"
        return (
            "inspect_failed_run",
            "danger",
            f"Paper/shadow simulation failed for {ref}; inspect the failed run before manual confirmation.",
        )
    if run_status == "diverged" or divergence_status == "diverged":
        status = order_status or "unknown"
        return (
            "resolve_shadow_divergence",
            "warning",
            f"Paper/shadow order {status} requires divergence review before manual confirmation.",
        )
    return (
        "review_shadow_divergence",
        "warning",
        "Paper/shadow order requires review before manual confirmation.",
    )


def _fallback_review_suffix(value: str) -> str:
    text = str(value or "").strip()
    if ":" in text:
        return text.split(":", 1)[1]
    return text or "unknown"


def _fallback_missing_simulation_review_items(
    *,
    run_id: Any,
    divergence_summary: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    execution = _dict(_dict(divergence_summary).get("execution_comparison"))
    missing_refs = _list(execution.get("missing_order_intent_refs"))
    return [
        {
            "review_id": f"{run_id}:{_fallback_review_suffix(intent_ref)}",
            "order_intent_ref": intent_ref,
            "order_id": None,
            "symbol": None,
            "status": "missing_simulation",
            "divergence_status": "review_required",
            "severity": "warning",
            "required_action": "review_shadow_divergence",
            "reason": (
                f"Paper/shadow simulation is missing for {intent_ref}; "
                "review the order intent before manual confirmation."
            ),
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        }
        for intent_ref in missing_refs
    ]


def _paper_shadow_effective_status(
    *,
    status: str,
    review_status: str,
) -> str:
    if (
        review_status == "accepted_for_manual_confirmation"
        and _paper_shadow_status_can_accept_manual_handoff(status)
    ):
        return "accepted_for_manual_confirmation"
    return status


paper_shadow_summary = _paper_shadow_summary
paper_shadow_run_summary = _paper_shadow_run_summary
paper_shadow_manual_handoff = _paper_shadow_manual_handoff
paper_shadow_handoff_required_actions = _paper_shadow_handoff_required_actions
paper_shadow_highest_review_severity = _paper_shadow_highest_review_severity
fallback_paper_shadow_review_queue = _fallback_paper_shadow_review_queue
fallback_paper_shadow_review_item = _fallback_paper_shadow_review_item
fallback_paper_shadow_oms_evidence = _fallback_paper_shadow_oms_evidence
fallback_paper_shadow_oms_transition = _fallback_paper_shadow_oms_transition
fallback_terminal_oms_transition = _fallback_terminal_oms_transition
fallback_paper_shadow_review_action = _fallback_paper_shadow_review_action
fallback_review_suffix = _fallback_review_suffix
fallback_missing_simulation_review_items = _fallback_missing_simulation_review_items
paper_shadow_effective_status = _paper_shadow_effective_status
