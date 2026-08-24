"""Decision action selection and fail-closed risk application orchestration."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

from fastapi import HTTPException

from core.types import Symbol
from data.market_data import is_fund_estimate_quote_source
from server.services.decision_contracts import (
    TRUSTED_DATA_STATUSES,
    action_sort_key,
    action_trade_date,
    int_or_none,
)


async def run_batch_pre_trade_risk(
    state: Any,
    *,
    portfolio_context_resolver: Callable[[Any], dict[str, Any]],
    read_action_tasks_resolver: Callable[..., list[dict[str, Any]]],
    action_filter_date_resolver: Callable[[dict[str, Any]], str | None],
    evidence_gate_resolver: Callable[..., dict[str, Any]],
    blocked_response_resolver: Callable[..., dict[str, Any]],
    allocate_actions_resolver: Callable[..., list[dict[str, Any]]],
) -> dict[str, Any]:
    """Run the canonical persisted-evidence batch risk gate for one app state."""

    from server.services.live_context import LiveContextProvider
    from server.services.pre_trade_batch import run_pre_trade_risk_batch

    if state.db is None:
        raise HTTPException(status_code=503, detail="database is unavailable")
    if state.trading_controls is None:
        raise HTTPException(
            status_code=503,
            detail="trading controls are unavailable",
        )
    portfolio_context = portfolio_context_resolver(state)
    tasks = read_action_tasks_resolver(
        state.db,
        decision_date=action_filter_date_resolver(portfolio_context),
    )
    evidence_gate = evidence_gate_resolver(
        state.db,
        portfolio_context=portfolio_context,
        tasks=tasks,
    )
    if not evidence_gate["ready"]:
        return blocked_response_resolver(
            tasks=tasks,
            evidence_gate=evidence_gate,
        )
    portfolio = portfolio_context.get("portfolio")
    positions = getattr(portfolio, "positions", {}) if portfolio is not None else {}
    risk_portfolio = SimpleNamespace(
        cash=getattr(portfolio, "cash", 0),
        positions={
            Symbol(str(symbol)): position
            for symbol, position in dict(positions or {}).items()
        },
        instruments={},
    )
    context_provider = LiveContextProvider(
        portfolio_getter=lambda: risk_portfolio,
        controls=state.trading_controls,
    )
    result = run_pre_trade_risk_batch(
        db=state.db,
        context_provider=context_provider,
        config=getattr(state, "config", None),
        tasks=allocate_actions_resolver(
            state,
            portfolio_context,
            tasks,
        ),
        evidence_binding=evidence_gate["evidence_binding"],
    )
    return {
        **result,
        **evidence_gate["evidence_binding"],
        "blockers": [],
        "persisted_facts_only": True,
    }


def read_action_tasks(
    db: Any,
    *,
    decision_date: str | None = None,
) -> list[dict[str, Any]]:
    reader = getattr(db, "get_action_tasks_sync", None)
    if not callable(reader):
        return []
    rows = list(reader(statuses=["pending", "deferred"], limit=500, offset=0))
    row_dates = [
        trade_date
        for row in rows
        for trade_date in [action_trade_date(row)]
        if trade_date is not None
    ]
    effective_date = decision_date or (max(row_dates) if row_dates else None)
    filtered = [
        row
        for row in rows
        if effective_date is None or action_trade_date(row) in {None, effective_date}
    ]
    ordered = sorted(filtered, key=action_sort_key, reverse=True)
    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in ordered:
        identity = (
            str(row.get("symbol") or ""),
            str(row.get("strategy_id") or ""),
            str(row.get("asset_class") or ""),
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduplicated.append(row)
    return deduplicated


def trading_plan_positions(
    state: Any,
    *,
    portfolio_context: dict[str, Any] | None = None,
    portfolio_context_resolver: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    context = portfolio_context or portfolio_context_resolver(state)
    portfolio = context.get("portfolio")
    positions = getattr(portfolio, "positions", {}) if portfolio else {}
    return dict(positions) if isinstance(positions, dict) else {}


def allocate_decision_actions(
    state: Any,
    portfolio_context: dict[str, Any],
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    portfolio = portfolio_context.get("portfolio")
    if portfolio is None:
        return actions
    from server.services.portfolio_allocation import allocate_action_tasks

    return allocate_action_tasks(
        actions,
        portfolio=portfolio,
        quotes=dict(portfolio_context.get("quotes") or {}),
        config=getattr(state, "config", None),
    )


def batch_pre_trade_risk_evidence_gate(
    db: Any,
    *,
    portfolio_context: dict[str, Any],
    tasks: list[dict[str, Any]],
    data_freshness_resolver: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Require one complete persisted valuation identity before risk writes."""

    snapshot = portfolio_context.get("valuation_snapshot")
    authority = str(portfolio_context.get("authority") or "unknown")
    snapshot_payload = snapshot if isinstance(snapshot, dict) else {}
    valuation_status = str(snapshot_payload.get("status") or "missing").lower()
    snapshot_id = str(snapshot_payload.get("snapshot_id") or "") or None
    ledger_cutoff_id = int_or_none(snapshot_payload.get("ledger_cutoff_id")) or 0
    evidence_binding = {
        "valuation_snapshot_id": snapshot_id,
        "ledger_cutoff_id": ledger_cutoff_id,
        "valuation_status": valuation_status,
        "fact_authority": authority,
    }
    blockers: list[dict[str, Any]] = []

    if authority != "persisted_valuation_snapshot":
        blockers.append(
            {
                "code": "persisted_valuation_snapshot_required",
                "status": authority,
            }
        )
    if not snapshot_id:
        blockers.append({"code": "valuation_snapshot_identity_missing"})
    if valuation_status != "complete":
        blockers.append(
            {
                "code": "valuation_snapshot_not_complete",
                "status": valuation_status,
            }
        )
    if ledger_cutoff_id <= 0:
        blockers.append({"code": "ledger_cutoff_missing"})

    quotes = dict(portfolio_context.get("quotes") or {})
    for task in tasks:
        freshness = data_freshness_resolver(
            task,
            db,
            quotes=quotes,
            allow_direct_quote_fallback=False,
        )
        quote_source = str(freshness.get("quote_source") or "").lower()
        status = str(freshness.get("status") or "unknown").lower()
        if is_fund_estimate_quote_source(quote_source):
            status = "confirmed_nav_missing"
        if status in TRUSTED_DATA_STATUSES:
            continue
        blockers.append(
            {
                "code": "candidate_market_data_not_complete",
                "symbol": str(task.get("symbol") or ""),
                "status": status,
                "quote_source": freshness.get("quote_source"),
                "stale_reason": freshness.get("stale_reason"),
            }
        )

    return {
        "ready": not blockers,
        "evidence_binding": evidence_binding,
        "blockers": blockers,
    }


def blocked_batch_pre_trade_risk_response(
    *,
    tasks: list[dict[str, Any]],
    evidence_gate: dict[str, Any],
) -> dict[str, Any]:
    """Return an explainable, zero-write batch result for incomplete evidence."""

    binding = dict(evidence_gate.get("evidence_binding") or {})
    blockers = list(evidence_gate.get("blockers") or [])
    blocker_codes = list(
        dict.fromkeys(
            str(blocker.get("code") or "valuation_evidence_not_ready")
            for blocker in blockers
        )
    )
    return {
        "schema_version": "karkinos.pre_trade_risk_batch.v1",
        "status": "blocked_by_data_quality",
        "processed_count": 0,
        "passed_count": 0,
        "blocked_count": 0,
        "skipped_count": len(tasks),
        "candidate_count": len(tasks),
        "does_not_create_order": True,
        "does_not_submit_broker_order": True,
        "does_not_write_ledger": True,
        "risk_decision_writes_performed": False,
        "database_writes_performed": False,
        "default_execution_mode": "manual_confirmation",
        "persisted_facts_only": True,
        **binding,
        "evidence_binding": binding,
        "blockers": blockers,
        "results": [
            {
                "action_id": task.get("id"),
                "symbol": task.get("symbol"),
                "status": "skipped",
                "passed": None,
                "decision_id": None,
                "reasons": blocker_codes,
            }
            for task in tasks
        ],
    }
