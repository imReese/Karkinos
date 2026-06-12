"""Decision cockpit routes — /api/decision/*"""

from __future__ import annotations

import inspect
import json
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/decision", tags=["decision"])

    @r.get("/today")
    async def get_today_decision() -> dict[str, Any]:
        from server.app import get_app_state

        state = get_app_state()
        db = state.db
        actions = _read_action_tasks(db)
        journal_by_signal = _journal_by_signal_id(db)
        validation_by_strategy = await _validation_by_strategy_id(db)
        candidates = [
            _decision_candidate(action, journal_by_signal, validation_by_strategy, db)
            for action in actions
        ]
        no_action_reasons = [] if candidates else ["no_pending_action_tasks"]
        return {
            "lane": "daily",
            "decision_date": date.today().isoformat(),
            "generated_at": datetime.now().isoformat(),
            "decision": _overall_decision(candidates),
            "requires_manual_confirmation": any(
                candidate["manual_confirmation_required"] for candidate in candidates
            ),
            "summary": _decision_summary(
                state,
                actions=actions,
                candidates=candidates,
                journal_by_signal=journal_by_signal,
            ),
            "candidates": candidates,
            "no_action_reasons": no_action_reasons,
            "limitations": [
                "Decision cockpit output is research and portfolio tooling, not investment advice.",
                "Live-like execution remains manual-confirmation only by default.",
            ],
        }

    @r.get("/intraday")
    async def get_intraday_decision() -> dict[str, Any]:
        from server.app import get_app_state

        state = get_app_state()
        db = state.db
        actions = _read_action_tasks(db)
        intraday_actions = [action for action in actions if _is_intraday_action(action)]
        daily_actions = [
            action for action in actions if not _is_intraday_action(action)
        ]
        journal_by_signal = _journal_by_signal_id(db)
        validation_by_strategy = await _validation_by_strategy_id(db)
        candidates = [
            _decision_candidate(action, journal_by_signal, validation_by_strategy, db)
            for action in intraday_actions
        ]
        no_action_reasons = (
            [] if candidates else ["no_intraday_stock_or_etf_action_tasks"]
        )
        return {
            "lane": "intraday",
            "decision_date": date.today().isoformat(),
            "generated_at": datetime.now().isoformat(),
            "cadence": "polling_or_minute_level",
            "decision": _overall_decision(candidates),
            "requires_manual_confirmation": any(
                candidate["manual_confirmation_required"] for candidate in candidates
            ),
            "summary": {
                **_decision_summary(
                    state,
                    actions=actions,
                    candidates=candidates,
                    journal_by_signal=journal_by_signal,
                ),
                "excluded_daily_count": len(daily_actions),
            },
            "candidates": candidates,
            "excluded_daily_symbols": [
                str(action.get("symbol")) for action in daily_actions
            ],
            "no_action_reasons": no_action_reasons,
            "limitations": [
                "Intraday decisions are polling/minute-level cockpit candidates, not high-frequency trading instructions.",
                "Decision cockpit output is research and portfolio tooling, not investment advice.",
                "Live-like execution remains manual-confirmation only by default.",
            ],
        }

    return r


def _read_action_tasks(db: Any) -> list[dict[str, Any]]:
    reader = getattr(db, "get_action_tasks_sync", None)
    if not callable(reader):
        return []
    return list(reader(statuses=["pending", "deferred"], limit=50, offset=0))


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
) -> dict[str, Any]:
    risk_blocked_count = sum(
        1 for candidate in candidates if candidate["risk_gate_status"] == "blocked"
    )
    return {
        "candidate_count": len(candidates),
        "risk_blocked_count": risk_blocked_count,
        "ready_for_manual_confirmation_count": sum(
            1
            for candidate in candidates
            if candidate["manual_confirmation_status"]
            == "ready_for_manual_confirmation"
        ),
        "portfolio": _portfolio_state_summary(state),
        "market_data": _market_data_summary(state, actions),
        "action_tasks": _action_task_summary(actions),
        "audit": _audit_summary(actions, candidates, journal_by_signal),
    }


def _portfolio_state_summary(state: Any) -> dict[str, Any]:
    scheduler = getattr(state, "scheduler", None)
    portfolio = getattr(scheduler, "portfolio", None) if scheduler else None
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
    return {
        "status": "available",
        "cash": cash,
        "position_count": len(symbols),
        "symbols": symbols,
        "total_market_value": total_market_value,
        "total_equity": total_equity,
    }


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
) -> dict[str, Any]:
    symbols = _decision_symbols(state, actions)
    quotes = _collect_decision_quotes(state)
    relevant_quotes = {symbol: quotes[symbol] for symbol in symbols if symbol in quotes}
    statuses = [
        str(quote.get("quote_status") or quote.get("provider_status") or "live")
        for quote in relevant_quotes.values()
    ]
    live_count = sum(1 for status in statuses if status == "live")
    stale_count = sum(1 for status in statuses if status != "live")
    missing_symbols = [symbol for symbol in symbols if symbol not in quotes]
    latest_timestamp = _latest_quote_timestamp(relevant_quotes.values())
    if not symbols:
        source_health = "unknown"
    elif missing_symbols and not relevant_quotes:
        source_health = "missing"
    elif missing_symbols or stale_count:
        source_health = "partial" if live_count else "stale"
    else:
        source_health = "live"
    return {
        "source_health": source_health,
        "quote_count": len(relevant_quotes),
        "live_quote_count": live_count,
        "stale_quote_count": stale_count,
        "missing_symbols": missing_symbols,
        "latest_quote_timestamp": latest_timestamp,
        "has_persistent_cache": _has_persistent_quote_cache(state),
    }


def _decision_symbols(state: Any, actions: list[dict[str, Any]]) -> list[str]:
    symbols: list[str] = []
    for action in actions:
        _append_unique_symbol(symbols, action.get("symbol"))
    scheduler = getattr(state, "scheduler", None)
    for item in getattr(scheduler, "watchlist", []) or []:
        symbol = item[0] if isinstance(item, (list, tuple)) and item else item
        _append_unique_symbol(symbols, symbol)
    portfolio = getattr(scheduler, "portfolio", None) if scheduler else None
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
    scheduler = getattr(state, "scheduler", None)
    for symbol, quote in (getattr(scheduler, "latest_quotes", {}) or {}).items():
        if isinstance(quote, dict):
            quotes[str(symbol)] = _normalize_quote(symbol, quote)
    db = getattr(state, "db", None)
    if db is None:
        return quotes
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
) -> dict[str, Any]:
    signal_id = action.get("source_signal_id")
    journal = journal_by_signal.get(int(signal_id)) if signal_id is not None else None
    return {
        "action_id": action.get("id"),
        "action": _normalize_decision_action(action),
        "symbol": action.get("symbol"),
        "asset_class": action.get("asset_class"),
        "title": action.get("title"),
        "detail": action.get("detail"),
        "urgency": action.get("urgency"),
        "target_weight": action.get("target_weight"),
        "price": action.get("price"),
        "risk_gate_status": action.get("risk_gate_status", "not_checked"),
        "manual_confirmation_required": bool(
            action.get("manual_confirmation_required", True)
        ),
        "manual_confirmation_status": action.get(
            "manual_confirmation_status", "awaiting_risk_gate"
        ),
        "evidence": {
            "strategy": {"strategy_id": action.get("strategy_id")},
            "signal": _signal_evidence(action, journal),
            "risk_gate": _risk_gate_evidence(action),
            "after_cost_oos_validation": _after_cost_oos_validation_evidence(
                action, validation_by_strategy
            ),
            "data_freshness": _data_freshness_evidence(action, db),
            "manual_confirmation": _manual_confirmation_evidence(action),
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
    if any(candidate["risk_gate_status"] != "passed" for candidate in candidates):
        return "review_required"
    actions = {candidate["action"] for candidate in candidates}
    if len(actions) == 1:
        return next(iter(actions))
    if actions <= {"buy", "sell", "rebalance"}:
        return "rebalance"
    return "review_required"


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


def _data_freshness_evidence(action: dict[str, Any], db: Any) -> dict[str, Any]:
    reader = getattr(db, "get_latest_quote_sync", None)
    if not callable(reader):
        return {"status": "unknown", "reason": "latest_quote_reader_unavailable"}
    symbol = str(action.get("symbol") or "")
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


def _manual_confirmation_evidence(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "required": bool(action.get("manual_confirmation_required", True)),
        "status": action.get("manual_confirmation_status", "awaiting_risk_gate"),
        "reason": action.get("manual_confirmation_reason"),
    }


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
