"""Fail-closed Account Truth, strategy, market, and paper/shadow evidence."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from server.services.decision_contracts import (
    ACCOUNT_STRATEGY_CONTROL_KEY,
    STRATEGY_ATTRIBUTION_READY_STATUSES,
    action_trade_date,
    int_or_none,
    json_object,
    parse_action_timestamp,
)


def account_truth_gate_evidence(state: Any) -> dict[str, Any]:
    from server.account_truth_gate import build_latest_account_truth_promotion_evidence

    promotion = json_object(build_latest_account_truth_promotion_evidence(state))
    if not promotion:
        return {
            "status": "missing",
            "gate_status": "blocked",
            "score": None,
            "has_evidence": False,
            "data_freshness_status": "missing",
            "unresolved_mismatch_count": None,
            "blocking_reasons": ["account_truth_score_unavailable"],
            "required_actions": ["preview_import_and_reconcile_broker_evidence"],
            "limitations": [
                "Decision platform requires Account Truth evidence before live-like manual confirmation."
            ],
        }

    blockers = [
        str(item)
        for item in [
            *(promotion.get("blockers") or []),
            *(promotion.get("score_blocking_reasons") or []),
        ]
        if str(item)
    ]
    blockers = list(dict.fromkeys(blockers))
    required_actions = [
        str(item) for item in promotion.get("score_required_actions") or [] if str(item)
    ]
    gate_status = str(promotion.get("gate_status") or "blocked").lower()
    if promotion.get("status") != "clear" or blockers:
        gate_status = "blocked"
    import_run_id = str(promotion.get("import_run_id") or "")
    return {
        "schema_version": promotion.get("schema_version"),
        "status": "available" if import_run_id else "missing",
        "promotion_status": promotion.get("status"),
        "gate_status": gate_status,
        "score": int_or_none(promotion.get("score")),
        "has_evidence": bool(import_run_id),
        "data_freshness_status": promotion.get("data_freshness_status"),
        "unresolved_mismatch_count": int_or_none(
            promotion.get("unresolved_mismatch_count")
        ),
        "reconciliation_status": promotion.get("reconciliation_status"),
        "blocking_reasons": blockers,
        "required_actions": required_actions or blockers,
        "limitations": list(
            dict.fromkeys(
                [
                    *[
                        str(item)
                        for item in promotion.get("score_limitations") or []
                        if str(item)
                    ],
                    "Account Truth is resolved from the current sanitized promotion evidence; stale, source-incomplete, drifted, or unreconciled evidence is blocked.",
                ]
            )
        ),
        "import_run_id": import_run_id or None,
        "source_type": promotion.get("source_type"),
        "source_name": None,
        "source_fingerprint": promotion.get("source_fingerprint"),
        "captured_at": promotion.get("captured_at"),
        "created_at": promotion.get("captured_at"),
        "current_age_seconds": promotion.get("current_age_seconds"),
        "max_age_seconds": promotion.get("max_age_seconds"),
        "ledger_coverage": promotion.get("ledger_coverage"),
        "citic_source_follow_up": promotion.get("citic_source_follow_up"),
        "does_not_mutate_production_ledger": True,
        "does_not_issue_execution_authority": True,
        "broker_submission_enabled": False,
    }


def strategy_attribution_gate_evidence(
    state: Any,
    db: Any,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    reader = getattr(db, "get_runtime_control_sync", None)
    payload = reader(ACCOUNT_STRATEGY_CONTROL_KEY) if callable(reader) else None
    if not isinstance(payload, dict):
        return {
            "status": "not_configured",
            "gate_status": "pass",
            "strategy_id": None,
            "assignment_status": "not_configured",
            "attribution_status": "not_configured",
            "contribution_status": "not_configured",
            "has_evidence": True,
            "required_actions": [],
            "blocking_reasons": [],
            "limitations": [
                "No account strategy assignment is configured for this decision lane."
            ],
        }

    from server.services.account_strategy_assignment import (
        account_strategy_assignment_from_payload,
    )
    from server.services.account_strategy_projections import (
        build_attribution_summary,
        build_contribution_report,
    )

    fallback_config = getattr(
        state,
        "config",
        SimpleNamespace(strategy=first_action_strategy_id(actions)),
    )
    assignment = account_strategy_assignment_from_payload(
        payload,
        fallback_config=fallback_config,
    )
    if assignment.status in {"disabled", "inactive", "retired"}:
        return {
            "status": "disabled",
            "gate_status": "pass",
            "strategy_id": assignment.strategy_id,
            "assignment_status": assignment.status,
            "attribution_status": "not_required",
            "contribution_status": "not_required",
            "has_evidence": True,
            "required_actions": [],
            "blocking_reasons": [],
            "limitations": list(assignment.limitations),
        }

    attribution = build_attribution_summary(db, assignment)
    contribution = build_contribution_report(db, assignment)
    contribution_status = contribution.contribution_status
    is_ready = (
        contribution_status in STRATEGY_ATTRIBUTION_READY_STATUSES
        and contribution.evidence_binding_status == "bound"
        and bool(contribution.valuation_snapshot_id)
        and contribution.ledger_cutoff_id > 0
        and bool(contribution.contribution_fingerprint)
    )
    attributed_signal_refs = {
        ref for ref in attribution.evidence_refs if ref.startswith("signal:")
    }
    assigned_candidate_actions = [
        action
        for action in actions
        if str(action.get("strategy_id") or assignment.strategy_id)
        == assignment.strategy_id
    ]
    candidate_lineage_missing = any(
        not action.get("source_signal_id")
        or f"signal:{action['source_signal_id']}" not in attributed_signal_refs
        for action in assigned_candidate_actions
    )
    is_not_applicable = (
        contribution_status == "no_linked_fills"
        and contribution.linked_fill_count == 0
        and contribution.unattributed_fill_count == 0
        and not candidate_lineage_missing
    )
    has_linked_evidence = any(
        [
            attribution.signal_count,
            attribution.order_count,
            attribution.fill_count,
            contribution.linked_fill_count,
        ]
    )
    if is_ready or is_not_applicable:
        gate_status = "pass"
    elif contribution.evidence_binding_status == "blocked":
        gate_status = "blocked"
    elif has_linked_evidence:
        gate_status = "degraded"
    else:
        gate_status = "blocked"
    if is_ready or is_not_applicable:
        required_actions = []
    elif candidate_lineage_missing:
        required_actions = ["link_strategy_signals_orders_fills_and_contribution"]
    else:
        required_actions = [contribution.next_manual_action]
    return {
        "status": "available",
        "gate_status": gate_status,
        "strategy_id": assignment.strategy_id,
        "assignment_status": assignment.status,
        "attribution_status": attribution.attribution_status,
        "contribution_status": contribution_status,
        "has_evidence": is_ready or is_not_applicable,
        "signal_count": attribution.signal_count,
        "order_count": attribution.order_count,
        "fill_count": attribution.fill_count,
        "linked_fill_count": contribution.linked_fill_count,
        "ledger_posted_fill_count": contribution.ledger_posted_fill_count,
        "unposted_linked_fill_count": contribution.unposted_linked_fill_count,
        "unattributed_fill_count": contribution.unattributed_fill_count,
        "evidence_binding_status": contribution.evidence_binding_status,
        "valuation_snapshot_id": contribution.valuation_snapshot_id,
        "ledger_cutoff_id": contribution.ledger_cutoff_id,
        "contribution_fingerprint": contribution.contribution_fingerprint,
        "net_contribution": contribution.net_contribution,
        "required_actions": required_actions,
        "blocking_reasons": (
            []
            if is_ready or is_not_applicable
            else (
                ["strategy_attribution_not_ready"]
                if candidate_lineage_missing
                else list(contribution.blockers) or ["strategy_attribution_not_ready"]
            )
        ),
        "limitations": [
            *list(attribution.limitations),
            *list(contribution.limitations),
        ],
    }


def first_action_strategy_id(actions: list[dict[str, Any]]) -> str:
    for action in actions:
        strategy_id = action.get("strategy_id")
        if strategy_id:
            return str(strategy_id)
    return "dual_ma"


def data_freshness_evidence(
    action: dict[str, Any],
    db: Any,
    *,
    quotes: dict[str, dict[str, Any]],
    allow_direct_quote_fallback: bool,
) -> dict[str, Any]:
    symbol = str(action.get("symbol") or "")
    quote = quotes.get(symbol)
    if quote is None and allow_direct_quote_fallback:
        reader = getattr(db, "get_latest_quote_sync", None)
        if not callable(reader):
            return {"status": "unknown", "reason": "latest_quote_reader_unavailable"}
        asset_type = action.get("asset_class")
        quote = reader(symbol, asset_type=asset_type)
        if quote is None:
            quote = reader(symbol)
    if quote is None:
        return {"status": "missing", "reason": "missing_latest_quote"}
    quote_timestamp = parse_action_timestamp(
        quote.get("quote_timestamp") or quote.get("timestamp")
    )
    return {
        "status": quote.get("quote_status") or "live",
        "quote_timestamp": (
            quote_timestamp.isoformat() if quote_timestamp is not None else None
        ),
        "quote_source": quote.get("quote_source"),
        "price": quote.get("price"),
        "stale_reason": quote.get("stale_reason"),
    }


def paper_shadow_evidence(
    action: dict[str, Any],
    manual_confirmation_status: str,
    *,
    db: Any,
) -> dict[str, Any]:
    status = str(action.get("paper_shadow_status") or "review_required")
    has_evidence = status in {"attached", "pass", "reviewed", "shadow_recorded"}
    run_id = None
    input_fingerprint = None
    divergence_status = None
    order_divergence_status = None
    review_status = None
    order_id = action.get("paper_shadow_order_id")
    order_intent: dict[str, Any] = {}
    simulated_order: dict[str, Any] = {}
    if not has_evidence:
        reader = getattr(db, "latest_paper_shadow_run_sync", None)
        plan_date = action_trade_date(action)
        latest_run = (
            reader(plan_date=plan_date)
            if callable(reader) and plan_date is not None
            else None
        )
        payload = json_object(
            latest_run.get("payload_json") if isinstance(latest_run, dict) else None
        )
        action_ref = f"action:{action.get('id')}"
        matching_order = next(
            (
                order
                for order in payload.get("orders") or []
                if isinstance(order, dict)
                and json_object(order.get("order_intent")).get("action_ref")
                == action_ref
            ),
            None,
        )
        if isinstance(latest_run, dict) and isinstance(matching_order, dict):
            run_id = latest_run.get("run_id")
            input_fingerprint = latest_run.get("input_fingerprint")
            divergence_status = latest_run.get("divergence_status")
            review_status = latest_run.get("review_status")
            order_id = matching_order.get("order_id")
            order_divergence_status = matching_order.get("divergence_status")
            order_intent = json_object(matching_order.get("order_intent"))
            simulated_order = {
                key: matching_order.get(key)
                for key in (
                    "order_id",
                    "symbol",
                    "status",
                    "divergence_status",
                    "quantity",
                    "price",
                    "filled_quantity",
                    "remaining_quantity",
                )
            }
            has_evidence = True
            if (
                str(divergence_status or "") == "within_expectations"
                and str(order_divergence_status or "") == "within_expectations"
            ):
                status = "pass"
            else:
                status = "review_required"
    if has_evidence and status != "review_required":
        required_actions: list[str] = []
        blocking_reasons: list[str] = []
    elif has_evidence:
        required_actions = ["review_paper_shadow_divergence"]
        blocking_reasons = ["paper_shadow_divergence_requires_review"]
    else:
        required_actions = ["review_paper_shadow_evidence"]
        blocking_reasons = ["paper_shadow_evidence_required_before_manual_confirmation"]
    return {
        "status": status,
        "has_evidence": has_evidence,
        "execution_mode": (
            "paper_shadow" if run_id is not None else action.get("execution_mode")
        ),
        "run_id": run_id,
        "input_fingerprint": input_fingerprint,
        "order_id": order_id,
        "divergence_status": divergence_status,
        "order_divergence_status": order_divergence_status,
        "review_status": review_status,
        "order_intent": order_intent,
        "simulated_order": simulated_order,
        "required_actions": required_actions,
        "blocking_reasons": blocking_reasons,
        "manual_confirmation_status": manual_confirmation_status,
    }


def paper_shadow_allows_manual_ticket(evidence: dict[str, Any]) -> bool:
    """Require one exact persisted, drift-clear simulation before ticketing."""

    return (
        evidence.get("status") == "pass"
        and evidence.get("has_evidence") is True
        and bool(evidence.get("run_id"))
        and bool(evidence.get("input_fingerprint"))
        and bool(evidence.get("order_id"))
        and evidence.get("divergence_status") == "within_expectations"
        and evidence.get("order_divergence_status") == "within_expectations"
    )
