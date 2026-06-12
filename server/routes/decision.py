"""Decision cockpit routes — /api/decision/*"""

from __future__ import annotations

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
        candidates = [
            _decision_candidate(action, journal_by_signal, db) for action in actions
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
            "summary": {
                "candidate_count": len(candidates),
                "risk_blocked_count": sum(
                    1
                    for candidate in candidates
                    if candidate["risk_gate_status"] == "blocked"
                ),
                "ready_for_manual_confirmation_count": sum(
                    1
                    for candidate in candidates
                    if candidate["manual_confirmation_status"]
                    == "ready_for_manual_confirmation"
                ),
            },
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
        candidates = [
            _decision_candidate(action, journal_by_signal, db)
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
                "candidate_count": len(candidates),
                "excluded_daily_count": len(daily_actions),
                "risk_blocked_count": sum(
                    1
                    for candidate in candidates
                    if candidate["risk_gate_status"] == "blocked"
                ),
                "ready_for_manual_confirmation_count": sum(
                    1
                    for candidate in candidates
                    if candidate["manual_confirmation_status"]
                    == "ready_for_manual_confirmation"
                ),
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


def _decision_candidate(
    action: dict[str, Any],
    journal_by_signal: dict[int, dict[str, Any]],
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
            "after_cost_oos_validation": {
                "status": "not_attached",
                "reason": "strategy validation evidence is surfaced by /api/backtest/strategy-validation",
            },
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
