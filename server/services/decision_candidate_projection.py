"""Decision candidate construction from already-resolved evidence."""

from __future__ import annotations

import inspect
from typing import Any, Callable

from server.services.asset_metadata import resolve_asset_metadata
from server.services.decision_contracts import (
    BLOCKING_DATA_STATUSES,
    READY_MANUAL_CONFIRMATION_STATUS,
    TRUSTED_DATA_STATUSES,
    account_truth_manual_confirmation_status,
    action_trade_date,
    append_unique_text,
    data_quality_manual_confirmation_status,
    float_or_none,
    json_object,
    normalize_decision_action,
)


async def validation_by_strategy_id(db: Any) -> dict[str, dict[str, Any]]:
    reader = getattr(db, "get_backtest_results", None)
    if not callable(reader):
        return {}
    rows = reader()
    if inspect.isawaitable(rows):
        rows = await rows
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        strategy_id = backtest_strategy_id(row)
        if not strategy_id or strategy_id in indexed:
            continue
        indexed[str(strategy_id)] = backtest_validation_row(row)
    return indexed


def decision_candidate(
    action: dict[str, Any],
    journal_by_signal: dict[int, dict[str, Any]],
    validation_by_strategy: dict[str, dict[str, Any]],
    db: Any,
    account_truth: dict[str, Any],
    strategy_attribution: dict[str, Any],
    *,
    state: Any,
    quotes: dict[str, dict[str, Any]],
    allow_direct_quote_fallback: bool,
    data_freshness_resolver: Callable[..., dict[str, Any]],
    strategy_order_gate_resolver: Callable[..., tuple[dict[str, Any], list[str]]],
    paper_shadow_resolver: Callable[..., dict[str, Any]],
    paper_shadow_ticket_gate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    signal_id = action.get("source_signal_id")
    journal = journal_by_signal.get(int(signal_id)) if signal_id is not None else None
    journal_signal = (journal or {}).get("signal") or {}
    symbol = str(action.get("symbol") or journal_signal.get("symbol") or "")
    metadata = resolve_asset_metadata(
        state,
        symbol,
        asset_class=str(action.get("asset_class") or "") or None,
        quote=quotes.get(symbol),
        fallback_name=(
            action.get("display_name")
            or action.get("name")
            or journal_signal.get("display_name")
            or journal_signal.get("name")
        ),
    )
    account_truth_gate_status = str(account_truth.get("gate_status") or "blocked")
    data_freshness = data_freshness_resolver(
        action,
        db,
        quotes=quotes,
        allow_direct_quote_fallback=allow_direct_quote_fallback,
    )
    manual_confirmation_status = (
        action.get("manual_confirmation_status", "awaiting_risk_gate")
        if account_truth_gate_status == "pass"
        else account_truth_manual_confirmation_status(account_truth_gate_status)
    )
    strategy_attribution_gate_status = str(
        strategy_attribution.get("gate_status") or "pass"
    )
    data_manual_confirmation_status = data_quality_manual_confirmation_status(
        data_freshness
    )
    if (
        account_truth_gate_status == "pass"
        and data_manual_confirmation_status is not None
        and manual_confirmation_status == READY_MANUAL_CONFIRMATION_STATUS
    ):
        manual_confirmation_status = data_manual_confirmation_status
    if (
        account_truth_gate_status == "pass"
        and strategy_attribution_gate_status != "pass"
        and manual_confirmation_status == READY_MANUAL_CONFIRMATION_STATUS
    ):
        manual_confirmation_status = "strategy_attribution_review_required"
    strategy_order_generation, _ = strategy_order_gate_resolver(
        db,
        str(action.get("strategy_id") or ""),
        as_of_date=action_trade_date(action),
    )
    if (
        strategy_order_generation.get("status") != "pass"
        and manual_confirmation_status == READY_MANUAL_CONFIRMATION_STATUS
    ):
        manual_confirmation_status = "strategy_advancement_review_required"
    risk_gate = risk_gate_evidence(action)
    validation = after_cost_oos_validation_evidence(action, validation_by_strategy)
    paper_shadow = paper_shadow_resolver(
        action,
        manual_confirmation_status,
        db=db,
    )
    if (
        strategy_order_generation.get("status") == "pass"
        and manual_confirmation_status == READY_MANUAL_CONFIRMATION_STATUS
        and not paper_shadow_ticket_gate(paper_shadow)
    ):
        manual_confirmation_status = "paper_shadow_review_required"
        paper_shadow["manual_confirmation_status"] = manual_confirmation_status
    manual_confirmation = manual_confirmation_evidence(
        action,
        manual_confirmation_status=manual_confirmation_status,
    )
    strategy_evidence = {
        "strategy_id": action.get("strategy_id"),
        "order_generation_gate": strategy_order_generation,
    }
    return {
        "action_id": action.get("id"),
        "action": normalize_decision_action(action),
        "symbol": symbol,
        "display_name": metadata.display_name,
        "asset_class": action.get("asset_class"),
        "title": action.get("title"),
        "detail": action.get("detail"),
        "urgency": action.get("urgency"),
        "raw_target_weight": action.get(
            "raw_target_weight",
            action.get("target_weight"),
        ),
        "target_weight": action.get("target_weight"),
        "price": action.get("price"),
        "allocation_quantity": action.get("allocation_quantity"),
        "allocation_status": action.get("allocation_status"),
        "allocation_evidence": dict(action.get("allocation_evidence") or {}),
        "risk_gate_status": action.get("risk_gate_status", "not_checked"),
        "manual_confirmation_required": bool(
            action.get("manual_confirmation_required", True)
        ),
        "manual_confirmation_status": manual_confirmation_status,
        "evidence": {
            "strategy": strategy_evidence,
            "portfolio_allocation": dict(action.get("allocation_evidence") or {}),
            "signal": signal_evidence(
                action,
                journal,
                display_name=metadata.display_name,
            ),
            "risk_gate": risk_gate,
            "after_cost_oos_validation": validation,
            "data_freshness": data_freshness,
            "account_truth": account_truth,
            "strategy_attribution": strategy_attribution,
            "certainty": certainty_evidence(
                data_freshness=data_freshness,
                account_truth=account_truth,
                risk_gate=risk_gate,
                strategy_order_generation=strategy_order_generation,
                paper_shadow=paper_shadow,
                paper_shadow_ticket_gate=paper_shadow_ticket_gate,
            ),
            "paper_shadow": paper_shadow,
            "cost_impact": cost_impact_evidence(validation),
            "uncertainty": uncertainty_evidence(
                risk_gate=risk_gate,
                validation=validation,
                data_freshness=data_freshness,
                account_truth=account_truth,
                strategy_attribution=strategy_attribution,
                strategy_order_generation=strategy_order_generation,
                paper_shadow=paper_shadow,
            ),
            "manual_confirmation": manual_confirmation,
            "journal": journal_evidence(journal),
        },
    }


def signal_evidence(
    action: dict[str, Any],
    journal: dict[str, Any] | None,
    *,
    display_name: str,
) -> dict[str, Any]:
    signal = (journal or {}).get("signal") or {}
    return {
        "id": signal.get("id", action.get("source_signal_id")),
        "timestamp": signal.get("timestamp", action.get("timestamp")),
        "strategy_id": signal.get("strategy_id", action.get("strategy_id")),
        "symbol": signal.get("symbol", action.get("symbol")),
        "display_name": (
            signal.get("display_name") or signal.get("name") or display_name
        ),
        "target_weight": signal.get("target_weight", action.get("target_weight")),
    }


def risk_gate_evidence(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": action.get("risk_gate_status", "not_checked"),
        "decision_id": action.get("risk_decision_id"),
        "passed": action.get("risk_gate_passed"),
        "severity": action.get("risk_gate_severity"),
        "reasons": list(action.get("risk_gate_reasons") or []),
    }


def after_cost_oos_validation_evidence(
    action: dict[str, Any],
    validation_by_strategy: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    strategy_id = action.get("strategy_id")
    if not strategy_id:
        return {"status": "not_attached", "reason": "missing_strategy_id"}
    validation = validation_by_strategy.get(str(strategy_id))
    if validation is None:
        return {
            "status": "not_attached",
            "strategy_id": strategy_id,
            "reason": "no_matching_backtest_validation_evidence",
        }
    after_cost = dict(validation.get("after_cost") or {})
    oos_validation = dict(validation.get("oos_validation") or {})
    has_after_cost = bool(after_cost)
    has_oos = bool(oos_validation)
    missing = []
    if not has_after_cost:
        missing.append("after_cost_report")
    if not has_oos:
        missing.append("out_of_sample_validation")
    return {
        "status": "attached" if not missing else "incomplete",
        "strategy_id": strategy_id,
        "backtest_result_id": validation.get("backtest_result_id"),
        "backtest_created_at": validation.get("backtest_created_at"),
        "has_after_cost_report": has_after_cost,
        "has_out_of_sample_validation": has_oos,
        "missing_requirements": missing,
        "after_cost": after_cost,
        "oos_validation": oos_validation,
        "cost_summary": dict(validation.get("cost_summary") or {}),
        "limitations": list(validation.get("limitations") or []),
    }


def certainty_evidence(
    *,
    data_freshness: dict[str, Any],
    account_truth: dict[str, Any],
    risk_gate: dict[str, Any],
    strategy_order_generation: dict[str, Any],
    paper_shadow: dict[str, Any],
    paper_shadow_ticket_gate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    status = "pass"
    required_actions: list[str] = []
    uncertain_reasons: list[str] = []

    risk_status = str(risk_gate.get("status") or "not_checked")
    if risk_status != "passed":
        status = "blocked"
        append_unique_text(required_actions, "review_risk_blockers")
        for reason in risk_gate.get("reasons") or []:
            append_unique_text(uncertain_reasons, reason)

    account_truth_status = str(account_truth.get("gate_status") or "blocked")
    if account_truth_status != "pass":
        status = "blocked" if account_truth_status == "blocked" else "degraded"
        for action in account_truth.get("required_actions") or []:
            append_unique_text(required_actions, action)
        for reason in account_truth.get("blocking_reasons") or []:
            append_unique_text(uncertain_reasons, reason)

    data_status = str(data_freshness.get("status") or "unknown")
    if data_status in BLOCKING_DATA_STATUSES:
        status = "blocked"
        append_unique_text(required_actions, "refresh_market_data")
    elif data_status not in TRUSTED_DATA_STATUSES:
        if status != "blocked":
            status = "degraded"
        append_unique_text(required_actions, "refresh_or_confirm_market_data")
    if data_status not in TRUSTED_DATA_STATUSES:
        append_unique_text(uncertain_reasons, data_freshness.get("reason"))
        append_unique_text(uncertain_reasons, data_freshness.get("stale_reason"))
        append_unique_text(uncertain_reasons, data_status)

    strategy_order_generation_passed = strategy_order_generation.get("status") == "pass"
    if not strategy_order_generation_passed:
        status = "blocked"
        append_unique_text(required_actions, "review_strategy_advancement_evidence")
        for reason in strategy_order_generation.get("blockers") or []:
            append_unique_text(uncertain_reasons, reason)
    elif not paper_shadow_ticket_gate(paper_shadow):
        status = "blocked"
        append_unique_text(required_actions, "run_or_review_current_paper_shadow")
        for reason in paper_shadow.get("blocking_reasons") or []:
            append_unique_text(uncertain_reasons, reason)

    posture = (
        "manual_confirmation_allowed"
        if status == "pass"
        else "blocked" if status == "blocked" else "review_required"
    )
    return {
        "status": status,
        "posture": posture,
        "required_actions": required_actions,
        "uncertain_reasons": uncertain_reasons,
    }


def manual_confirmation_evidence(
    action: dict[str, Any],
    *,
    manual_confirmation_status: str,
) -> dict[str, Any]:
    return {
        "required": bool(action.get("manual_confirmation_required", True)),
        "status": manual_confirmation_status,
        "reason": action.get("manual_confirmation_reason"),
    }


def cost_impact_evidence(validation: dict[str, Any]) -> dict[str, Any]:
    cost_summary = dict(validation.get("cost_summary") or {})
    total_commission = float_or_none(
        cost_summary.get("total_commission", cost_summary.get("commission"))
    )
    total_slippage = float_or_none(
        cost_summary.get("total_slippage", cost_summary.get("slippage"))
    )
    has_costs = (
        bool(cost_summary) or total_commission is not None or total_slippage is not None
    )
    return {
        "status": "estimated_from_research_costs" if has_costs else "missing",
        "source": "after_cost_oos_validation",
        "total_commission": total_commission,
        "total_slippage": total_slippage,
        "cost_summary": cost_summary,
    }


def uncertainty_evidence(
    *,
    risk_gate: dict[str, Any],
    validation: dict[str, Any],
    data_freshness: dict[str, Any],
    account_truth: dict[str, Any],
    strategy_attribution: dict[str, Any],
    strategy_order_generation: dict[str, Any],
    paper_shadow: dict[str, Any],
) -> dict[str, Any]:
    factors: list[str] = []
    for limitation in validation.get("limitations") or []:
        append_unique_text(factors, limitation)
    for missing in validation.get("missing_requirements") or []:
        append_unique_text(factors, missing)
    for reason in risk_gate.get("reasons") or []:
        append_unique_text(factors, reason)
    for key in ("reason", "stale_reason"):
        append_unique_text(factors, data_freshness.get(key))
    for reason in strategy_order_generation.get("blockers") or []:
        append_unique_text(factors, reason)
    uncertainty_payloads = [account_truth, strategy_attribution]
    if strategy_order_generation.get("status") == "pass":
        uncertainty_payloads.append(paper_shadow)
    for payload in uncertainty_payloads:
        for reason in payload.get("blocking_reasons") or []:
            append_unique_text(factors, reason)
        for action in payload.get("required_actions") or []:
            append_unique_text(factors, action)
    return {
        "status": "review_required" if factors else "pass",
        "factors": factors,
    }


def journal_evidence(journal: dict[str, Any] | None) -> dict[str, Any]:
    latest_event = (journal or {}).get("latest_event") or {}
    return {
        "has_journal_entry": journal is not None,
        "latest_event_type": latest_event.get("event_type"),
        "latest_event_source": latest_event.get("source"),
        "latest_event_ref": latest_event.get("source_ref"),
    }


def backtest_strategy_id(row: dict[str, Any]) -> str | None:
    config = json_object(row.get("config_json"))
    strategy_id = config.get("strategy")
    return str(strategy_id) if strategy_id else None


def backtest_validation_row(row: dict[str, Any]) -> dict[str, Any]:
    metrics = json_object(row.get("metrics_json"))
    after_cost = json_object(metrics.get("evidence_bundle"))
    oos_validation = json_object(metrics.get("oos_validation"))
    return {
        "backtest_result_id": row.get("id"),
        "backtest_created_at": row.get("created_at"),
        "after_cost": after_cost,
        "oos_validation": oos_validation,
        "cost_summary": json_object(row.get("cost_summary_json")),
        "limitations": validation_limitations(after_cost, oos_validation),
    }


def validation_limitations(
    after_cost: dict[str, Any],
    oos_validation: dict[str, Any],
) -> list[str]:
    limitations: list[str] = []
    for payload in (after_cost, oos_validation):
        for limitation in payload.get("limitations") or []:
            if limitation not in limitations:
                limitations.append(str(limitation))
    if not limitations:
        limitations.append(
            "Backtest and OOS evidence are historical research artifacts, not a profitability claim."
        )
    return limitations
