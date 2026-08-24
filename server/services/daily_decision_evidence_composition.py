"""Composition root for daily decision evidence automation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from server.services.automation_control import AutomationControlService
from server.services.daily_decision_evidence_contracts import (
    QuoteRefresher,
    StatePlanReader,
    StateRiskRunner,
)
from server.services.daily_decision_evidence_values import object_dict, object_list


def build_daily_decision_evidence_automation_service(
    state: Any,
    *,
    plan_reader: StatePlanReader,
    risk_runner: StateRiskRunner,
    quote_refresher: QuoteRefresher,
    service_type: Callable[..., Any],
) -> Any:
    """Bind explicit application adapters to the background evidence service."""
    from server.services.daily_candidate_quote_freeze import (
        DailyCandidateQuoteFreezeService,
    )
    from server.services.promoted_strategy_universe_scan import (
        PromotedStrategyUniverseScanService,
    )

    automation_controls = AutomationControlService(
        db=state.db,
        trading_controls=state.trading_controls,
    )
    runtime_config = getattr(state, "config", None)
    scanner = PromotedStrategyUniverseScanService(
        db=state.db,
        config=runtime_config,
        safety_gate_reader=automation_controls.get_status,
    )
    quote_freezer = DailyCandidateQuoteFreezeService(
        db=state.db,
        state=state,
        quote_refresher=quote_refresher,
    )
    scan_cache: dict[tuple[object, ...], dict[str, Any]] = {}

    async def read_plan() -> tuple[dict[str, Any], dict[str, Any]]:
        decision, trading_plan = await plan_reader(state)
        decision_date = str(decision.get("decision_date") or "")
        plan_date = str(trading_plan.get("plan_date") or "")
        if decision_date and decision_date == plan_date:
            portfolio = object_dict(
                object_dict(decision.get("summary")).get("portfolio")
            )
            cache_key = promoted_scan_cache_key(decision_date, portfolio)
            cached = scan_cache.get(cache_key)
            if cached is None:
                prepared = await asyncio.to_thread(
                    scanner.run_once,
                    decision_date=decision_date,
                    portfolio_summary=portfolio,
                    persist_actions=False,
                )
                quote_freeze = await quote_freezer.run_once(prepared)
                decision, trading_plan = await plan_reader(state)
                final_portfolio = object_dict(
                    object_dict(decision.get("summary")).get("portfolio")
                )
                quote_blockers = [
                    f"daily_candidate_quote_freeze:{item}"
                    for item in quote_freeze.get("blockers") or []
                ]
                final_scan = await asyncio.to_thread(
                    scanner.run_once,
                    decision_date=decision_date,
                    portfolio_summary=final_portfolio,
                    expected_signal_selection_fingerprint=prepared.get(
                        "signal_selection_fingerprint"
                    ),
                    additional_blockers=quote_blockers,
                )
                decision, trading_plan = await plan_reader(state)
                cached = {
                    "scan": final_scan,
                    "quote_freeze": quote_freeze,
                }
                if final_scan.get("status") in {
                    "completed",
                    "completed_no_signal",
                }:
                    final_portfolio = object_dict(
                        object_dict(decision.get("summary")).get("portfolio")
                    )
                    scan_cache[
                        promoted_scan_cache_key(decision_date, final_portfolio)
                    ] = cached
            decision = bind_promoted_strategy_scan(
                decision,
                cached["scan"],
                quote_freeze=cached["quote_freeze"],
            )
        return decision, trading_plan

    async def run_risk() -> dict[str, Any]:
        return await risk_runner(state)

    return service_type(
        db=state.db,
        trading_controls=state.trading_controls,
        notifier=state.notifier,
        plan_reader=read_plan,
        risk_runner=run_risk,
    )


def bind_promoted_strategy_scan(
    decision_payload: dict[str, Any],
    scan: dict[str, Any],
    *,
    quote_freeze: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach one persisted scanner projection to the in-memory decision read."""

    decision = dict(decision_payload)
    summary = object_dict(decision.get("summary"))
    status = str(scan.get("status") or "blocked")
    blockers = [str(item) for item in scan.get("blockers") or [] if str(item)]
    summary["promoted_strategy_universe_scan"] = {
        "schema_version": scan.get("schema_version"),
        "run_id": scan.get("run_id"),
        "status": status,
        "decision_date": scan.get("decision_date"),
        "market_date": scan.get("market_date"),
        "input_fingerprint": scan.get("input_fingerprint"),
        "output_fingerprint": scan.get("output_fingerprint"),
        "active_strategy_count": len(scan.get("strategy_bindings") or []),
        "selected_signal_count": int(scan.get("selected_signal_count") or 0),
        "normal_no_signal": scan.get("normal_no_signal") is True,
        "blockers": blockers,
        "provider_contact_performed": False,
        "creates_oms_order": False,
        "submits_broker_order": False,
        "changes_capital_authority": False,
    }
    if quote_freeze is not None:
        summary["daily_candidate_quote_freeze"] = {
            "schema_version": quote_freeze.get("schema_version"),
            "run_id": quote_freeze.get("run_id"),
            "status": quote_freeze.get("status"),
            "decision_date": quote_freeze.get("decision_date"),
            "symbols": list(quote_freeze.get("symbols") or []),
            "blockers": list(quote_freeze.get("blockers") or []),
            "provider_contact_performed": quote_freeze.get("provider_contact_performed")
            is True,
            "creates_oms_order": False,
            "submits_broker_order": False,
            "changes_capital_authority": False,
        }
    decision["summary"] = summary
    if not object_list(decision.get("candidates")):
        if status == "completed_no_signal":
            decision["no_action_reasons"] = [
                "full_market_scan_completed_without_strategy_signal"
            ]
        elif blockers:
            decision["no_action_reasons"] = [
                f"promoted_strategy_universe_scan:{item}" for item in blockers
            ]
    return decision


def promoted_scan_cache_key(
    decision_date: str,
    portfolio: dict[str, Any],
) -> tuple[object, ...]:
    return (
        decision_date,
        portfolio.get("valuation_snapshot_id"),
        portfolio.get("ledger_cutoff_id"),
        portfolio.get("ledger_fingerprint"),
        portfolio.get("quote_set_fingerprint"),
        portfolio.get("total_equity"),
    )
