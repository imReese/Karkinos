"""Decision platform routes — /api/decision/*"""

from __future__ import annotations

import inspect
import json
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from core.types import Symbol

_ACCOUNT_STRATEGY_CONTROL_KEY = "account_strategy_assignment"
_STRATEGY_ATTRIBUTION_READY_STATUSES = {"evidence_bound_from_posted_fills"}
_READY_MANUAL_CONFIRMATION_STATUS = "ready_for_manual_confirmation"
_TRUSTED_DATA_STATUSES = {"complete", "confirmed", "fresh", "live", "pass"}
_REVIEW_DATA_STATUSES = {
    "cache",
    "cache_only",
    "confirmed_nav_missing",
    "estimated",
    "partial",
    "stale",
    "unknown",
}
_BLOCKING_DATA_STATUSES = {"blocked", "error", "missing", "unavailable"}
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/decision", tags=["decision"])

    @r.get("/today")
    async def get_today_decision() -> dict[str, Any]:
        from server.app import get_app_state

        state = get_app_state()
        return await _today_decision_payload(state)

    @r.get("/trading-plan")
    async def get_daily_trading_plan() -> dict[str, Any]:
        from server.app import get_app_state
        from server.services.daily_trading_plan import build_daily_trading_plan

        state = get_app_state()
        portfolio_context = _decision_portfolio_context(state)
        decision_payload = await _today_decision_payload(
            state,
            portfolio_context=portfolio_context,
        )
        return build_daily_trading_plan(
            decision_payload=decision_payload,
            config=getattr(state, "config", None),
            positions=_trading_plan_positions(
                state,
                portfolio_context=portfolio_context,
            ),
        )

    @r.post("/pre-trade-risk/batch")
    async def run_batch_pre_trade_risk() -> dict[str, Any]:
        from server.app import get_app_state
        from server.services.live_context import LiveContextProvider
        from server.services.pre_trade_batch import run_pre_trade_risk_batch

        state = get_app_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="database is unavailable")
        if state.trading_controls is None:
            raise HTTPException(
                status_code=503,
                detail="trading controls are unavailable",
            )
        portfolio_context = _decision_portfolio_context(state)
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
        return run_pre_trade_risk_batch(
            db=state.db,
            context_provider=context_provider,
            config=getattr(state, "config", None),
            tasks=_allocate_decision_actions(
                state,
                portfolio_context,
                _read_action_tasks(
                    state.db,
                    decision_date=_action_filter_date(portfolio_context),
                ),
            ),
        )

    @r.get("/intraday")
    async def get_intraday_decision() -> dict[str, Any]:
        from server.app import get_app_state

        state = get_app_state()
        db = state.db
        portfolio_context = _decision_portfolio_context(state)
        actions = _allocate_decision_actions(
            state,
            portfolio_context,
            _read_action_tasks(
                db,
                decision_date=_action_filter_date(portfolio_context),
            ),
        )
        decision_date = _response_decision_date(portfolio_context, actions)
        intraday_actions = [action for action in actions if _is_intraday_action(action)]
        daily_actions = [
            action for action in actions if not _is_intraday_action(action)
        ]
        journal_by_signal = _journal_by_signal_id(db)
        validation_by_strategy = await _validation_by_strategy_id(db)
        account_truth = _account_truth_gate_evidence(state)
        strategy_attribution = _strategy_attribution_gate_evidence(
            state,
            db,
            actions,
        )
        candidates = [
            _decision_candidate(
                action,
                journal_by_signal,
                validation_by_strategy,
                db,
                account_truth,
                strategy_attribution,
                quotes=dict(portfolio_context.get("quotes") or {}),
                allow_direct_quote_fallback=(
                    portfolio_context.get("authority") != "persisted_valuation_snapshot"
                ),
            )
            for action in intraday_actions
        ]
        no_action_reasons = (
            [] if candidates else ["no_intraday_stock_or_etf_action_tasks"]
        )
        return {
            "lane": "intraday",
            "decision_date": decision_date,
            "generated_at": datetime.now().isoformat(),
            "cadence": "polling_or_minute_level",
            "decision": _overall_decision(candidates),
            "requires_manual_confirmation": _has_ready_manual_confirmation(candidates),
            "summary": {
                **_decision_summary(
                    state,
                    actions=actions,
                    candidates=candidates,
                    journal_by_signal=journal_by_signal,
                    account_truth=account_truth,
                    strategy_attribution=strategy_attribution,
                    portfolio_context=portfolio_context,
                ),
                "excluded_daily_count": len(daily_actions),
            },
            "candidates": candidates,
            "excluded_daily_symbols": [
                str(action.get("symbol")) for action in daily_actions
            ],
            "no_action_reasons": no_action_reasons,
            "limitations": [
                "Intraday decisions are polling/minute-level platform candidates, not high-frequency trading instructions.",
                "Decision platform output is research and portfolio evidence, not investment advice.",
                "Live-like execution remains manual-confirmation only by default.",
            ],
        }

    return r


async def _today_decision_payload(
    state: Any,
    *,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = state.db
    resolved_portfolio_context = portfolio_context or _decision_portfolio_context(state)
    actions = _allocate_decision_actions(
        state,
        resolved_portfolio_context,
        _read_action_tasks(
            db,
            decision_date=_action_filter_date(resolved_portfolio_context),
        ),
    )
    decision_date = _response_decision_date(resolved_portfolio_context, actions)
    journal_by_signal = _journal_by_signal_id(db)
    validation_by_strategy = await _validation_by_strategy_id(db)
    account_truth = _account_truth_gate_evidence(state)
    strategy_attribution = _strategy_attribution_gate_evidence(
        state,
        db,
        actions,
    )
    candidates = [
        _decision_candidate(
            action,
            journal_by_signal,
            validation_by_strategy,
            db,
            account_truth,
            strategy_attribution,
            quotes=dict(resolved_portfolio_context.get("quotes") or {}),
            allow_direct_quote_fallback=(
                resolved_portfolio_context.get("authority")
                != "persisted_valuation_snapshot"
            ),
        )
        for action in actions
    ]
    no_action_reasons = [] if candidates else ["no_pending_action_tasks"]
    return {
        "lane": "daily",
        "decision_date": decision_date,
        "generated_at": datetime.now().isoformat(),
        "decision": _overall_decision(candidates),
        "requires_manual_confirmation": _has_ready_manual_confirmation(candidates),
        "summary": _decision_summary(
            state,
            actions=actions,
            candidates=candidates,
            journal_by_signal=journal_by_signal,
            account_truth=account_truth,
            strategy_attribution=strategy_attribution,
            portfolio_context=resolved_portfolio_context,
        ),
        "candidates": candidates,
        "no_action_reasons": no_action_reasons,
        "limitations": [
            "Decision platform output is research and portfolio evidence, not investment advice.",
            "Live-like execution remains manual-confirmation only by default.",
        ],
    }


def _read_action_tasks(
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
        for trade_date in [_action_trade_date(row)]
        if trade_date is not None
    ]
    effective_date = decision_date or (max(row_dates) if row_dates else None)
    filtered = [
        row
        for row in rows
        if effective_date is None or _action_trade_date(row) in {None, effective_date}
    ]
    ordered = sorted(filtered, key=_action_sort_key, reverse=True)
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


def _action_sort_key(action: dict[str, Any]) -> tuple[float, int]:
    timestamp = _parse_action_timestamp(action.get("timestamp"))
    try:
        action_id = int(action.get("id") or 0)
    except (TypeError, ValueError):
        action_id = 0
    return (
        timestamp.timestamp() if timestamp is not None else float("-inf"),
        action_id,
    )


def _trading_plan_positions(
    state: Any,
    *,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = portfolio_context or _decision_portfolio_context(state)
    portfolio = context.get("portfolio")
    positions = getattr(portfolio, "positions", {}) if portfolio else {}
    return dict(positions) if isinstance(positions, dict) else {}


def _allocate_decision_actions(
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


def _decision_portfolio_context(state: Any) -> dict[str, Any]:
    """Resolve Decision facts from the same persisted snapshot as Portfolio."""

    db = getattr(state, "db", None)
    persistent_facts_available = db is not None and any(
        callable(getattr(db, name, None))
        for name in (
            "list_latest_quotes_sync",
            "get_latest_quotes_sync",
            "list_quote_snapshots_sync",
            "get_ledger_entries_sync",
        )
    )
    if persistent_facts_available:
        from server.routes.portfolio import (
            _current_valuation_snapshot,
            _quotes_from_valuation_snapshot,
            _resolve_projection_sources,
        )
        from server.services.valuation_snapshot import build_current_valuation_snapshot

        snapshot = (
            _current_valuation_snapshot(state)
            if callable(getattr(db, "save_valuation_snapshot_sync", None))
            else build_current_valuation_snapshot(db, persist=False)
        )
        quotes = _quotes_from_valuation_snapshot(snapshot)
        scheduler = getattr(state, "scheduler", None)
        projection_scheduler = (
            SimpleNamespace(
                portfolio=getattr(scheduler, "portfolio", None),
                instruments=getattr(scheduler, "instruments", {}),
            )
            if scheduler is not None
            else None
        )
        projection_state = SimpleNamespace(
            db=db,
            scheduler=projection_scheduler,
            config=getattr(
                state,
                "config",
                SimpleNamespace(initial_cash=0, assets=[]),
            ),
        )
        portfolio, instruments = _resolve_projection_sources(
            projection_state,
            latest_quotes=quotes,
        )
        return {
            "portfolio": portfolio,
            "instruments": instruments,
            "quotes": quotes,
            "valuation_snapshot": snapshot,
            "authority": "persisted_valuation_snapshot",
        }

    scheduler = getattr(state, "scheduler", None)
    portfolio = getattr(scheduler, "portfolio", None) if scheduler else None
    return {
        "portfolio": portfolio,
        "instruments": getattr(scheduler, "instruments", {}) if scheduler else {},
        "quotes": _collect_decision_quotes(state),
        "valuation_snapshot": None,
        "authority": "legacy_runtime_fallback",
    }


def _decision_date_from_context(context: dict[str, Any]) -> str:
    snapshot = context.get("valuation_snapshot")
    if isinstance(snapshot, dict) and snapshot.get("trade_date"):
        return str(snapshot["trade_date"])
    timestamps = [
        _parse_action_timestamp(quote.get("quote_timestamp") or quote.get("timestamp"))
        for quote in (context.get("quotes") or {}).values()
        if isinstance(quote, dict)
    ]
    parsed = [timestamp for timestamp in timestamps if timestamp is not None]
    return max(parsed).date().isoformat() if parsed else date.today().isoformat()


def _action_filter_date(context: dict[str, Any]) -> str | None:
    if context.get("authority") != "persisted_valuation_snapshot":
        return None
    snapshot = context.get("valuation_snapshot")
    if isinstance(snapshot, dict) and snapshot.get("status") == "missing":
        return None
    return _decision_date_from_context(context)


def _response_decision_date(
    context: dict[str, Any],
    actions: list[dict[str, Any]],
) -> str:
    snapshot = context.get("valuation_snapshot")
    if (
        context.get("authority") == "persisted_valuation_snapshot"
        and isinstance(snapshot, dict)
        and snapshot.get("status") != "missing"
    ):
        return _decision_date_from_context(context)
    action_dates = [
        trade_date
        for action in actions
        for trade_date in [_action_trade_date(action)]
        if trade_date is not None
    ]
    return max(action_dates) if action_dates else _decision_date_from_context(context)


def _action_trade_date(action: dict[str, Any]) -> str | None:
    parsed = _parse_action_timestamp(action.get("timestamp"))
    return parsed.date().isoformat() if parsed is not None else None


def _parse_action_timestamp(value: Any) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=_SHANGHAI_TZ)
    return parsed.astimezone(_SHANGHAI_TZ)


def _journal_by_signal_id(db: Any) -> dict[int, dict[str, Any]]:
    reader = getattr(db, "list_signal_journal_sync", None)
    if not callable(reader):
        return {}
    rows = reader(limit=50, offset=0)
    indexed: dict[int, dict[str, Any]] = {}
    for row in rows:
        signal = row.get("signal") or {}
        signal_id = signal.get("id")
        if signal_id is None:
            continue
        indexed[int(signal_id)] = row
    return indexed


def _decision_summary(
    state: Any,
    *,
    actions: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    journal_by_signal: dict[int, dict[str, Any]],
    account_truth: dict[str, Any],
    strategy_attribution: dict[str, Any],
    portfolio_context: dict[str, Any],
) -> dict[str, Any]:
    risk_blocked_count = sum(
        1 for candidate in candidates if candidate["risk_gate_status"] == "blocked"
    )
    ready_for_manual_confirmation_count = sum(
        1
        for candidate in candidates
        if candidate["manual_confirmation_status"] == "ready_for_manual_confirmation"
    )
    market_data = _market_data_summary(
        state,
        actions,
        portfolio_context=portfolio_context,
    )
    action_tasks = _action_task_summary(actions)
    audit = _audit_summary(actions, candidates, journal_by_signal)
    return {
        "candidate_count": len(candidates),
        "risk_blocked_count": risk_blocked_count,
        "ready_for_manual_confirmation_count": ready_for_manual_confirmation_count,
        "portfolio": _portfolio_state_summary(
            state,
            portfolio_context=portfolio_context,
        ),
        "market_data": market_data,
        "account_truth": account_truth,
        "strategy_attribution": strategy_attribution,
        "action_tasks": action_tasks,
        "audit": audit,
        "workflow_tasks": _workflow_tasks(
            market_data=market_data,
            account_truth=account_truth,
            strategy_attribution=strategy_attribution,
            action_tasks=action_tasks,
            audit=audit,
            candidate_count=len(candidates),
            ready_for_manual_confirmation_count=ready_for_manual_confirmation_count,
        ),
    }


def _portfolio_state_summary(
    state: Any,
    *,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = portfolio_context or _decision_portfolio_context(state)
    portfolio = context.get("portfolio")
    if portfolio is None:
        return {
            "status": "missing",
            "cash": 0.0,
            "position_count": 0,
            "symbols": [],
            "total_market_value": 0.0,
            "total_equity": 0.0,
        }
    positions = getattr(portfolio, "positions", {}) or {}
    position_items = positions.items() if isinstance(positions, dict) else []
    symbols: list[str] = []
    total_market_value = 0.0
    for symbol, position in position_items:
        symbols.append(str(symbol))
        total_market_value += _position_market_value(position)
    cash = _float_or_zero(getattr(portfolio, "cash", 0.0))
    total_equity = _portfolio_total_equity(portfolio, cash, total_market_value)
    result = {
        "status": "available",
        "cash": cash,
        "position_count": len(symbols),
        "symbols": symbols,
        "total_market_value": total_market_value,
        "total_equity": total_equity,
    }
    snapshot = context.get("valuation_snapshot")
    if isinstance(snapshot, dict):
        from server.services.valuation_snapshot import valuation_identity_fields

        result.update(valuation_identity_fields(snapshot))
    result["fact_authority"] = context.get("authority")
    return result


def _portfolio_total_equity(
    portfolio: Any,
    cash: float,
    total_market_value: float,
) -> float:
    total_equity = getattr(portfolio, "total_equity", None)
    if callable(total_equity):
        try:
            return _float_or_zero(total_equity())
        except TypeError:
            pass
    if total_equity is not None and not callable(total_equity):
        return _float_or_zero(total_equity)
    return cash + total_market_value


def _position_market_value(position: Any) -> float:
    market_value = getattr(position, "market_value", None)
    if callable(market_value):
        try:
            return _float_or_zero(market_value())
        except TypeError:
            return 0.0
    if market_value is not None:
        return _float_or_zero(market_value)
    quantity = _float_or_zero(
        getattr(position, "quantity", getattr(position, "shares", 0.0))
    )
    price = _float_or_zero(
        getattr(
            position,
            "current_price",
            getattr(position, "last_price", getattr(position, "price", 0.0)),
        )
    )
    return quantity * price


def _float_or_zero(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _market_data_summary(
    state: Any,
    actions: list[dict[str, Any]],
    *,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = portfolio_context or _decision_portfolio_context(state)
    symbols = _decision_symbols(state, actions, portfolio_context=context)
    quotes = dict(context.get("quotes") or {})
    relevant_quotes = {symbol: quotes[symbol] for symbol in symbols if symbol in quotes}
    statuses = [
        str(quote.get("quote_status") or quote.get("provider_status") or "live")
        for quote in relevant_quotes.values()
    ]
    live_count = sum(1 for status in statuses if status == "live")
    confirmed_count = sum(1 for status in statuses if status == "confirmed")
    trusted_count = sum(1 for status in statuses if status in _TRUSTED_DATA_STATUSES)
    stale_count = sum(1 for status in statuses if status not in _TRUSTED_DATA_STATUSES)
    missing_symbols = [symbol for symbol in symbols if symbol not in quotes]
    latest_timestamp = _latest_quote_timestamp(relevant_quotes.values())
    if not symbols:
        source_health = "unknown"
    elif missing_symbols and not relevant_quotes:
        source_health = "missing"
    elif missing_symbols or stale_count:
        source_health = "partial" if trusted_count else "stale"
    else:
        source_health = "live" if live_count == len(statuses) else "confirmed"
    return {
        "source_health": source_health,
        "quote_count": len(relevant_quotes),
        "live_quote_count": live_count,
        "confirmed_quote_count": confirmed_count,
        "trusted_quote_count": trusted_count,
        "stale_quote_count": stale_count,
        "missing_symbols": missing_symbols,
        "latest_quote_timestamp": latest_timestamp,
        "has_persistent_cache": _has_persistent_quote_cache(state),
    }


def _decision_symbols(
    state: Any,
    actions: list[dict[str, Any]],
    *,
    portfolio_context: dict[str, Any] | None = None,
) -> list[str]:
    symbols: list[str] = []
    for action in actions:
        _append_unique_symbol(symbols, action.get("symbol"))
    scheduler = getattr(state, "scheduler", None)
    for item in getattr(scheduler, "watchlist", []) or []:
        symbol = item[0] if isinstance(item, (list, tuple)) and item else item
        _append_unique_symbol(symbols, symbol)
    context = portfolio_context or _decision_portfolio_context(state)
    portfolio = context.get("portfolio")
    positions = getattr(portfolio, "positions", {}) if portfolio else {}
    if isinstance(positions, dict):
        for symbol in positions:
            _append_unique_symbol(symbols, symbol)
    config = getattr(state, "config", None)
    for asset in getattr(config, "assets", []) or []:
        if isinstance(asset, dict):
            _append_unique_symbol(symbols, asset.get("symbol"))
    return symbols


def _append_unique_symbol(symbols: list[str], symbol: Any) -> None:
    if symbol is None:
        return
    value = str(symbol)
    if value and value not in symbols:
        symbols.append(value)


def _collect_decision_quotes(state: Any) -> dict[str, dict[str, Any]]:
    quotes: dict[str, dict[str, Any]] = {}
    db = getattr(state, "db", None)
    persistent_reader_available = db is not None and any(
        callable(getattr(db, name, None))
        for name in ("list_latest_quotes_sync", "get_latest_quotes_sync")
    )
    for reader_name in ("list_latest_quotes_sync", "get_latest_quotes_sync"):
        reader = getattr(db, reader_name, None)
        if not callable(reader):
            continue
        for row in reader() or []:
            if not isinstance(row, dict):
                continue
            symbol = row.get("symbol")
            if symbol is None:
                continue
            quotes[str(symbol)] = _normalize_quote(symbol, row)
    if persistent_reader_available:
        return quotes
    scheduler = getattr(state, "scheduler", None)
    for symbol, quote in (getattr(scheduler, "latest_quotes", {}) or {}).items():
        if isinstance(quote, dict):
            quotes[str(symbol)] = _normalize_quote(symbol, quote)
    return quotes


def _normalize_quote(symbol: Any, quote: dict[str, Any]) -> dict[str, Any]:
    return {
        **quote,
        "symbol": str(quote.get("symbol") or symbol),
        "asset_class": quote.get("asset_class") or quote.get("asset_type"),
        "quote_status": quote.get("quote_status") or quote.get("provider_status"),
        "quote_timestamp": quote.get("quote_timestamp") or quote.get("timestamp"),
    }


def _latest_quote_timestamp(quotes: Any) -> str | None:
    timestamps = [
        str(timestamp)
        for quote in quotes
        for timestamp in [quote.get("quote_timestamp") or quote.get("timestamp")]
        if timestamp
    ]
    return max(timestamps) if timestamps else None


def _has_persistent_quote_cache(state: Any) -> bool:
    db = getattr(state, "db", None)
    if db is None:
        return False
    for reader_name in ("list_latest_quotes_sync", "get_latest_quotes_sync"):
        reader = getattr(db, reader_name, None)
        if not callable(reader):
            continue
        rows = reader() or []
        if rows:
            return True
    return False


def _action_task_summary(actions: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = [str(action.get("status") or "unknown") for action in actions]
    return {
        "total_count": len(actions),
        "pending_count": statuses.count("pending"),
        "deferred_count": statuses.count("deferred"),
        "symbols": [
            str(action.get("symbol")) for action in actions if action.get("symbol")
        ],
    }


def _audit_summary(
    actions: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    journal_by_signal: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "signal_count": len(
            {
                action.get("source_signal_id")
                for action in actions
                if action.get("source_signal_id") is not None
            }
        ),
        "journal_entry_count": len(journal_by_signal),
        "risk_checked_count": sum(
            1
            for action in actions
            if action.get("risk_gate_status") in {"passed", "blocked"}
            or action.get("risk_gate_passed") is not None
        ),
        "risk_blocked_count": sum(
            1 for candidate in candidates if candidate["risk_gate_status"] == "blocked"
        ),
    }


def _workflow_tasks(
    *,
    market_data: dict[str, Any],
    account_truth: dict[str, Any],
    strategy_attribution: dict[str, Any],
    action_tasks: dict[str, Any],
    audit: dict[str, Any],
    candidate_count: int,
    ready_for_manual_confirmation_count: int,
) -> list[dict[str, Any]]:
    return [
        _data_refresh_workflow_task(market_data),
        _account_truth_workflow_task(account_truth),
        _risk_review_workflow_task(action_tasks, audit),
        _strategy_evidence_workflow_task(strategy_attribution, candidate_count),
        _paper_shadow_workflow_task(candidate_count),
        _manual_confirmation_workflow_task(
            account_truth=account_truth,
            strategy_attribution=strategy_attribution,
            audit=audit,
            candidate_count=candidate_count,
            ready_for_manual_confirmation_count=ready_for_manual_confirmation_count,
        ),
    ]


def _data_refresh_workflow_task(market_data: dict[str, Any]) -> dict[str, Any]:
    source_health = str(market_data.get("source_health") or "unknown")
    if source_health in _TRUSTED_DATA_STATUSES:
        status = "pass"
        required_actions: list[str] = []
        blocking_reasons: list[str] = []
        description = "Market data is trusted for the decision universe."
    elif source_health == "missing":
        status = "blocked"
        required_actions = ["refresh_market_data"]
        blocking_reasons = ["market_data_missing"]
        description = "Decision data is missing for the selected universe."
    else:
        status = "degraded"
        required_actions = ["refresh_or_confirm_market_data"]
        blocking_reasons = ["market_data_not_fully_live"]
        description = (
            "Some decision quotes are stale, cached, or only partially available."
        )
    return _workflow_task(
        task_id="data_refresh",
        priority=10,
        status=status,
        title="Data refresh",
        description=description,
        required_actions=required_actions,
        blocking_reasons=blocking_reasons,
        evidence={
            "source_health": source_health,
            "quote_count": market_data.get("quote_count"),
            "missing_symbols": list(market_data.get("missing_symbols") or []),
            "latest_quote_timestamp": market_data.get("latest_quote_timestamp"),
        },
    )


def _account_truth_workflow_task(account_truth: dict[str, Any]) -> dict[str, Any]:
    gate_status = str(account_truth.get("gate_status") or "blocked")
    if gate_status == "pass":
        status = "pass"
    elif gate_status == "degraded":
        status = "degraded"
    else:
        status = "blocked"
    return _workflow_task(
        task_id="account_truth",
        priority=20,
        status=status,
        title="Account truth",
        description="Broker evidence and local account facts are checked before action review.",
        required_actions=list(account_truth.get("required_actions") or []),
        blocking_reasons=list(account_truth.get("blocking_reasons") or []),
        evidence={
            "gate_status": gate_status,
            "score": account_truth.get("score"),
            "has_evidence": bool(account_truth.get("has_evidence")),
            "unresolved_mismatch_count": account_truth.get("unresolved_mismatch_count"),
        },
    )


def _risk_review_workflow_task(
    action_tasks: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    total_count = int(action_tasks.get("total_count") or 0)
    risk_checked_count = int(audit.get("risk_checked_count") or 0)
    risk_blocked_count = int(audit.get("risk_blocked_count") or 0)
    if risk_blocked_count:
        status = "blocked"
        required_actions = ["review_risk_blockers"]
        blocking_reasons = ["risk_gate_blocked"]
        description = "At least one candidate is blocked by the pre-trade risk gate."
    elif total_count and risk_checked_count < total_count:
        status = "review_required"
        required_actions = ["run_pre_trade_risk_gate"]
        blocking_reasons = ["risk_gate_not_checked"]
        description = "Some candidate actions still need risk-gate evidence."
    else:
        status = "pass"
        required_actions = []
        blocking_reasons = []
        description = "Risk-gate evidence is present for the current candidates."
    return _workflow_task(
        task_id="risk_review",
        priority=30,
        status=status,
        title="Risk review",
        description=description,
        required_actions=required_actions,
        blocking_reasons=blocking_reasons,
        evidence={
            "total_action_count": total_count,
            "risk_checked_count": risk_checked_count,
            "risk_blocked_count": risk_blocked_count,
        },
    )


def _strategy_evidence_workflow_task(
    strategy_attribution: dict[str, Any],
    candidate_count: int,
) -> dict[str, Any]:
    gate_status = str(strategy_attribution.get("gate_status") or "pass")
    if gate_status == "pass":
        status = "pass"
    elif gate_status == "degraded":
        status = "degraded"
    else:
        status = "blocked"
    return _workflow_task(
        task_id="strategy_evidence",
        priority=40,
        status=status,
        title="Strategy evidence",
        description="Strategy candidates are reviewed only after data and account facts.",
        required_actions=list(strategy_attribution.get("required_actions") or []),
        blocking_reasons=list(strategy_attribution.get("blocking_reasons") or []),
        evidence={
            "candidate_count": candidate_count,
            "gate_status": gate_status,
            "strategy_id": strategy_attribution.get("strategy_id"),
            "has_evidence": bool(strategy_attribution.get("has_evidence")),
        },
    )


def _paper_shadow_workflow_task(candidate_count: int) -> dict[str, Any]:
    if candidate_count:
        status = "review_required"
        required_actions = ["review_paper_shadow_evidence"]
        description = (
            "Candidate actions should be compared against paper/shadow evidence."
        )
    else:
        status = "pass"
        required_actions = []
        description = "No candidate actions require paper/shadow review."
    return _workflow_task(
        task_id="paper_shadow_review",
        priority=50,
        status=status,
        title="Paper/shadow review",
        description=description,
        required_actions=required_actions,
        blocking_reasons=[],
        evidence={"candidate_count": candidate_count},
    )


def _manual_confirmation_workflow_task(
    *,
    account_truth: dict[str, Any],
    strategy_attribution: dict[str, Any],
    audit: dict[str, Any],
    candidate_count: int,
    ready_for_manual_confirmation_count: int,
) -> dict[str, Any]:
    account_truth_status = str(account_truth.get("gate_status") or "blocked")
    strategy_status = str(strategy_attribution.get("gate_status") or "pass")
    risk_blocked_count = int(audit.get("risk_blocked_count") or 0)
    if not candidate_count:
        status = "pass"
        required_actions: list[str] = []
        blocking_reasons: list[str] = []
        description = "No candidate actions require manual confirmation."
    elif (
        account_truth_status == "pass"
        and strategy_status == "pass"
        and risk_blocked_count == 0
        and ready_for_manual_confirmation_count
    ):
        status = "review_required"
        required_actions = ["manual_confirm_candidate_actions"]
        blocking_reasons = []
        description = "Candidate actions are ready for explicit human review."
    else:
        status = "blocked"
        required_actions = ["resolve_upstream_workflow_blockers"]
        blocking_reasons = ["upstream_workflow_blockers"]
        description = (
            "Manual confirmation is blocked until upstream evidence is resolved."
        )
    return _workflow_task(
        task_id="manual_confirmation",
        priority=60,
        status=status,
        title="Manual confirmation",
        description=description,
        required_actions=required_actions,
        blocking_reasons=blocking_reasons,
        evidence={
            "candidate_count": candidate_count,
            "ready_for_manual_confirmation_count": (
                ready_for_manual_confirmation_count
            ),
            "account_truth_gate_status": account_truth_status,
            "strategy_attribution_gate_status": strategy_status,
            "risk_blocked_count": risk_blocked_count,
        },
    )


def _workflow_task(
    *,
    task_id: str,
    priority: int,
    status: str,
    title: str,
    description: str,
    required_actions: list[str],
    blocking_reasons: list[str],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": task_id,
        "priority": priority,
        "status": status,
        "title": title,
        "description": description,
        "required_actions": required_actions,
        "blocking_reasons": blocking_reasons,
        "evidence": evidence,
    }


async def _validation_by_strategy_id(db: Any) -> dict[str, dict[str, Any]]:
    reader = getattr(db, "get_backtest_results", None)
    if not callable(reader):
        return {}
    rows = reader()
    if inspect.isawaitable(rows):
        rows = await rows
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        strategy_id = _backtest_strategy_id(row)
        if not strategy_id or strategy_id in indexed:
            continue
        indexed[str(strategy_id)] = _backtest_validation_row(row)
    return indexed


def _decision_candidate(
    action: dict[str, Any],
    journal_by_signal: dict[int, dict[str, Any]],
    validation_by_strategy: dict[str, dict[str, Any]],
    db: Any,
    account_truth: dict[str, Any],
    strategy_attribution: dict[str, Any],
    *,
    quotes: dict[str, dict[str, Any]],
    allow_direct_quote_fallback: bool,
) -> dict[str, Any]:
    signal_id = action.get("source_signal_id")
    journal = journal_by_signal.get(int(signal_id)) if signal_id is not None else None
    account_truth_gate_status = str(account_truth.get("gate_status") or "blocked")
    data_freshness = _data_freshness_evidence(
        action,
        db,
        quotes=quotes,
        allow_direct_quote_fallback=allow_direct_quote_fallback,
    )
    manual_confirmation_status = (
        action.get("manual_confirmation_status", "awaiting_risk_gate")
        if account_truth_gate_status == "pass"
        else _account_truth_manual_confirmation_status(account_truth_gate_status)
    )
    strategy_attribution_gate_status = str(
        strategy_attribution.get("gate_status") or "pass"
    )
    data_manual_confirmation_status = _data_quality_manual_confirmation_status(
        data_freshness
    )
    if (
        account_truth_gate_status == "pass"
        and data_manual_confirmation_status is not None
        and manual_confirmation_status == _READY_MANUAL_CONFIRMATION_STATUS
    ):
        manual_confirmation_status = data_manual_confirmation_status
    if (
        account_truth_gate_status == "pass"
        and strategy_attribution_gate_status != "pass"
        and manual_confirmation_status == _READY_MANUAL_CONFIRMATION_STATUS
    ):
        manual_confirmation_status = "strategy_attribution_review_required"
    risk_gate = _risk_gate_evidence(action)
    validation = _after_cost_oos_validation_evidence(action, validation_by_strategy)
    manual_confirmation = _manual_confirmation_evidence(
        action,
        manual_confirmation_status=manual_confirmation_status,
    )
    paper_shadow = _paper_shadow_evidence(
        action,
        manual_confirmation_status,
        db=db,
    )
    return {
        "action_id": action.get("id"),
        "action": _normalize_decision_action(action),
        "symbol": action.get("symbol"),
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
            "strategy": {"strategy_id": action.get("strategy_id")},
            "portfolio_allocation": dict(action.get("allocation_evidence") or {}),
            "signal": _signal_evidence(action, journal),
            "risk_gate": risk_gate,
            "after_cost_oos_validation": validation,
            "data_freshness": data_freshness,
            "account_truth": account_truth,
            "strategy_attribution": strategy_attribution,
            "certainty": _certainty_evidence(
                data_freshness=data_freshness,
                account_truth=account_truth,
                risk_gate=risk_gate,
            ),
            "paper_shadow": paper_shadow,
            "cost_impact": _cost_impact_evidence(validation),
            "uncertainty": _uncertainty_evidence(
                risk_gate=risk_gate,
                validation=validation,
                data_freshness=data_freshness,
                account_truth=account_truth,
                strategy_attribution=strategy_attribution,
                paper_shadow=paper_shadow,
            ),
            "manual_confirmation": manual_confirmation,
            "journal": _journal_evidence(journal),
        },
    }


def _normalize_decision_action(action: dict[str, Any]) -> str:
    direction = str(action.get("direction") or "").lower()
    if direction in {"buy", "sell", "hold", "rebalance"}:
        return direction
    return "review_required"


def _is_intraday_action(action: dict[str, Any]) -> bool:
    asset_class = str(action.get("asset_class") or "").lower()
    symbol = str(action.get("symbol") or "")
    if asset_class == "stock":
        return True
    if asset_class in {"fund", "etf"}:
        return _looks_exchange_traded_fund_symbol(symbol)
    return False


def _looks_exchange_traded_fund_symbol(symbol: str) -> bool:
    return symbol.startswith(
        (
            "159",
            "510",
            "511",
            "512",
            "513",
            "515",
            "516",
            "517",
            "518",
            "560",
            "561",
            "562",
            "563",
            "588",
        )
    )


def _overall_decision(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "no_action"
    if any(
        candidate["evidence"].get("certainty", {}).get("status") != "pass"
        for candidate in candidates
    ):
        return "review_required"
    if any(candidate["risk_gate_status"] != "passed" for candidate in candidates):
        return "review_required"
    if any(
        candidate["evidence"]["account_truth"]["gate_status"] != "pass"
        for candidate in candidates
    ):
        return "review_required"
    if any(
        candidate["evidence"]["strategy_attribution"]["gate_status"] != "pass"
        for candidate in candidates
    ):
        return "review_required"
    actions = {candidate["action"] for candidate in candidates}
    if len(actions) == 1:
        return next(iter(actions))
    if actions <= {"buy", "sell", "rebalance"}:
        return "rebalance"
    return "review_required"


def _has_ready_manual_confirmation(candidates: list[dict[str, Any]]) -> bool:
    return any(
        candidate.get("manual_confirmation_required")
        and candidate.get("manual_confirmation_status")
        == _READY_MANUAL_CONFIRMATION_STATUS
        for candidate in candidates
    )


def _account_truth_gate_evidence(state: Any) -> dict[str, Any]:
    db = getattr(state, "db", None)
    from server.account_truth_gate import build_latest_account_truth_score_payload

    score_payload = _json_object(build_latest_account_truth_score_payload(state))
    if not score_payload:
        score_payload = _latest_account_truth_score(db)
    if not score_payload:
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

    gate_status = str(
        score_payload.get("gate_status") or score_payload.get("status") or "blocked"
    ).lower()
    return {
        "status": "available",
        "gate_status": gate_status,
        "score": _int_or_none(score_payload.get("score")),
        "has_evidence": True,
        "data_freshness_status": score_payload.get("data_freshness_status"),
        "unresolved_mismatch_count": _int_or_none(
            score_payload.get("unresolved_mismatch_count")
        ),
        "blocking_reasons": list(score_payload.get("blocking_reasons") or []),
        "required_actions": list(score_payload.get("required_actions") or []),
        "limitations": list(score_payload.get("limitations") or []),
        "import_run_id": score_payload.get("import_run_id"),
        "source_type": score_payload.get("source_type"),
        "source_name": score_payload.get("source_name"),
        "created_at": score_payload.get("created_at"),
        "ledger_coverage": score_payload.get("ledger_coverage"),
    }


def _latest_account_truth_score(db: Any) -> dict[str, Any]:
    reader = getattr(db, "get_account_truth_score_sync", None)
    if callable(reader):
        return _json_object(reader())

    list_reader = getattr(db, "list_account_truth_scores_sync", None)
    if callable(list_reader):
        rows = list_reader(limit=1)
        if rows:
            return _json_object(rows[0])
    return {}


def _strategy_attribution_gate_evidence(
    state: Any,
    db: Any,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    reader = getattr(db, "get_runtime_control_sync", None)
    payload = reader(_ACCOUNT_STRATEGY_CONTROL_KEY) if callable(reader) else None
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

    from server.routes.account_strategy import (
        _assignment_from_payload,
        _build_attribution_summary,
        _build_contribution_report,
    )

    fallback_config = getattr(
        state,
        "config",
        SimpleNamespace(strategy=_first_action_strategy_id(actions)),
    )
    assignment = _assignment_from_payload(payload, fallback_config=fallback_config)
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

    attribution = _build_attribution_summary(db, assignment)
    contribution = _build_contribution_report(db, assignment)
    contribution_status = contribution.contribution_status
    is_ready = (
        contribution_status in _STRATEGY_ATTRIBUTION_READY_STATUSES
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


def _first_action_strategy_id(actions: list[dict[str, Any]]) -> str:
    for action in actions:
        strategy_id = action.get("strategy_id")
        if strategy_id:
            return str(strategy_id)
    return "dual_ma"


def _account_truth_manual_confirmation_status(gate_status: str) -> str:
    if gate_status == "degraded":
        return "account_truth_review_required"
    return "blocked_by_account_truth"


def _signal_evidence(
    action: dict[str, Any],
    journal: dict[str, Any] | None,
) -> dict[str, Any]:
    signal = (journal or {}).get("signal") or {}
    return {
        "id": signal.get("id", action.get("source_signal_id")),
        "timestamp": signal.get("timestamp", action.get("timestamp")),
        "strategy_id": signal.get("strategy_id", action.get("strategy_id")),
        "symbol": signal.get("symbol", action.get("symbol")),
        "target_weight": signal.get("target_weight", action.get("target_weight")),
    }


def _risk_gate_evidence(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": action.get("risk_gate_status", "not_checked"),
        "decision_id": action.get("risk_decision_id"),
        "passed": action.get("risk_gate_passed"),
        "severity": action.get("risk_gate_severity"),
        "reasons": list(action.get("risk_gate_reasons") or []),
    }


def _after_cost_oos_validation_evidence(
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


def _data_freshness_evidence(
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
    return {
        "status": quote.get("quote_status") or "live",
        "quote_timestamp": quote.get("quote_timestamp"),
        "quote_source": quote.get("quote_source"),
        "price": quote.get("price"),
        "stale_reason": quote.get("stale_reason"),
    }


def _data_quality_manual_confirmation_status(
    data_freshness: dict[str, Any],
) -> str | None:
    status = str(data_freshness.get("status") or "unknown")
    if status in _TRUSTED_DATA_STATUSES:
        return None
    if status in _BLOCKING_DATA_STATUSES:
        return "blocked_by_data_quality"
    return "data_review_required"


def _certainty_evidence(
    *,
    data_freshness: dict[str, Any],
    account_truth: dict[str, Any],
    risk_gate: dict[str, Any],
) -> dict[str, Any]:
    status = "pass"
    required_actions: list[str] = []
    uncertain_reasons: list[str] = []

    risk_status = str(risk_gate.get("status") or "not_checked")
    if risk_status != "passed":
        status = "blocked"
        _append_unique_text(required_actions, "review_risk_blockers")
        for reason in risk_gate.get("reasons") or []:
            _append_unique_text(uncertain_reasons, reason)

    account_truth_status = str(account_truth.get("gate_status") or "blocked")
    if account_truth_status != "pass":
        status = "blocked" if account_truth_status == "blocked" else "degraded"
        for action in account_truth.get("required_actions") or []:
            _append_unique_text(required_actions, action)
        for reason in account_truth.get("blocking_reasons") or []:
            _append_unique_text(uncertain_reasons, reason)

    data_status = str(data_freshness.get("status") or "unknown")
    if data_status in _BLOCKING_DATA_STATUSES:
        status = "blocked"
        _append_unique_text(required_actions, "refresh_market_data")
    elif data_status not in _TRUSTED_DATA_STATUSES:
        if status != "blocked":
            status = "degraded"
        _append_unique_text(required_actions, "refresh_or_confirm_market_data")
    if data_status not in _TRUSTED_DATA_STATUSES:
        _append_unique_text(uncertain_reasons, data_freshness.get("reason"))
        _append_unique_text(uncertain_reasons, data_freshness.get("stale_reason"))
        _append_unique_text(uncertain_reasons, data_status)

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


def _manual_confirmation_evidence(
    action: dict[str, Any],
    *,
    manual_confirmation_status: str,
) -> dict[str, Any]:
    return {
        "required": bool(action.get("manual_confirmation_required", True)),
        "status": manual_confirmation_status,
        "reason": action.get("manual_confirmation_reason"),
    }


def _paper_shadow_evidence(
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
    review_status = None
    order_id = action.get("paper_shadow_order_id")
    if not has_evidence:
        reader = getattr(db, "latest_paper_shadow_run_sync", None)
        plan_date = _action_trade_date(action)
        latest_run = (
            reader(plan_date=plan_date)
            if callable(reader) and plan_date is not None
            else None
        )
        payload = _json_object(
            latest_run.get("payload_json") if isinstance(latest_run, dict) else None
        )
        action_ref = f"action:{action.get('id')}"
        matching_order = next(
            (
                order
                for order in payload.get("orders") or []
                if isinstance(order, dict)
                and _json_object(order.get("order_intent")).get("action_ref")
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
            has_evidence = True
            if str(divergence_status or "") == "within_expectations":
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
        "review_status": review_status,
        "required_actions": required_actions,
        "blocking_reasons": blocking_reasons,
        "manual_confirmation_status": manual_confirmation_status,
    }


def _cost_impact_evidence(validation: dict[str, Any]) -> dict[str, Any]:
    cost_summary = dict(validation.get("cost_summary") or {})
    total_commission = _float_or_none(
        cost_summary.get("total_commission", cost_summary.get("commission"))
    )
    total_slippage = _float_or_none(
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


def _uncertainty_evidence(
    *,
    risk_gate: dict[str, Any],
    validation: dict[str, Any],
    data_freshness: dict[str, Any],
    account_truth: dict[str, Any],
    strategy_attribution: dict[str, Any],
    paper_shadow: dict[str, Any],
) -> dict[str, Any]:
    factors: list[str] = []
    for limitation in validation.get("limitations") or []:
        _append_unique_text(factors, limitation)
    for missing in validation.get("missing_requirements") or []:
        _append_unique_text(factors, missing)
    for reason in risk_gate.get("reasons") or []:
        _append_unique_text(factors, reason)
    for key in ("reason", "stale_reason"):
        _append_unique_text(factors, data_freshness.get(key))
    for payload in (account_truth, strategy_attribution, paper_shadow):
        for reason in payload.get("blocking_reasons") or []:
            _append_unique_text(factors, reason)
        for action in payload.get("required_actions") or []:
            _append_unique_text(factors, action)
    return {
        "status": "review_required" if factors else "pass",
        "factors": factors,
    }


def _append_unique_text(values: list[str], value: Any) -> None:
    if value is None:
        return
    text = str(value)
    if text and text not in values:
        values.append(text)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _journal_evidence(journal: dict[str, Any] | None) -> dict[str, Any]:
    latest_event = (journal or {}).get("latest_event") or {}
    return {
        "has_journal_entry": journal is not None,
        "latest_event_type": latest_event.get("event_type"),
        "latest_event_source": latest_event.get("source"),
        "latest_event_ref": latest_event.get("source_ref"),
    }


def _backtest_strategy_id(row: dict[str, Any]) -> str | None:
    config = _json_object(row.get("config_json"))
    strategy_id = config.get("strategy")
    return str(strategy_id) if strategy_id else None


def _backtest_validation_row(row: dict[str, Any]) -> dict[str, Any]:
    metrics = _json_object(row.get("metrics_json"))
    after_cost = _json_object(metrics.get("evidence_bundle"))
    oos_validation = _json_object(metrics.get("oos_validation"))
    return {
        "backtest_result_id": row.get("id"),
        "backtest_created_at": row.get("created_at"),
        "after_cost": after_cost,
        "oos_validation": oos_validation,
        "cost_summary": _json_object(row.get("cost_summary_json")),
        "limitations": _validation_limitations(after_cost, oos_validation),
    }


def _validation_limitations(
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


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _int_or_none(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
