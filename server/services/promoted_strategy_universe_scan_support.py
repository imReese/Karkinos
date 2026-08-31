"""Deterministic projections and fail-closed checks for promoted-strategy scans."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from server.ai_runtime.formula_dsl import evaluate_formula
from server.services.market_universe_automation import verified_trading_dates

SHANGHAI_TIME_ZONE = ZoneInfo("Asia/Shanghai")
DECISION_WINDOW_START = time(9, 35)
DECISION_WINDOW_END = time(9, 45)


def evaluate_strategy_signals(
    *,
    strategy_id: str,
    formula_ast: Mapping[str, Any],
    universe_size: int,
    target_weight: float,
    frames: Mapping[str, pd.DataFrame],
    eligible_symbols: list[str],
    maintenance_symbols: list[str],
    held_symbols: set[str],
    market_date: str,
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    candidates = sorted(set(eligible_symbols) | set(maintenance_symbols))
    for symbol in candidates:
        frame = frames.get(symbol)
        if frame is None or frame.empty:
            continue
        entry, exit_signal, _provider_sizing_ignored = evaluate_formula(
            formula_ast,
            frame,
            universe_size=universe_size,
        )
        latest = frame.sort_values("timestamp").iloc[-1]
        latest_date = pd.Timestamp(latest["timestamp"]).date().isoformat()
        if latest_date != market_date:
            raise ValueError(f"formula_market_date_missing:{symbol}")
        is_held = symbol in held_symbols
        exit_now = bool(exit_signal.iloc[-1])
        entry_now = bool(entry.iloc[-1])
        if is_held and exit_now:
            direction = "sell"
            signal_weight = 0.0
        elif not is_held and entry_now and not exit_now:
            direction = "buy"
            signal_weight = target_weight
        else:
            continue
        amount = pd.to_numeric(
            frame.get("amount", frame["close"] * frame["volume"]),
            errors="coerce",
        ).tail(20)
        liquidity = float(amount.median()) if not amount.empty else 0.0
        signals.append(
            {
                "strategy_id": strategy_id,
                "symbol": symbol,
                "direction": direction,
                "target_weight": float(signal_weight),
                "frozen_close": float(latest["close"]),
                "frozen_market_date": market_date,
                "ranking_liquidity": liquidity if math.isfinite(liquidity) else 0.0,
            }
        )
    return signals


def select_ranked_signals(
    signals: list[dict[str, Any]],
    *,
    allocation_slots: int,
) -> list[dict[str, Any]]:
    exits = sorted(
        (item for item in signals if item["direction"] == "sell"),
        key=lambda item: (str(item["symbol"]), str(item["strategy_id"])),
    )
    buys = sorted(
        (item for item in signals if item["direction"] == "buy"),
        key=lambda item: (
            -float(item["ranking_liquidity"]),
            str(item["symbol"]),
            str(item["strategy_id"]),
        ),
    )
    selected_buys: list[dict[str, Any]] = []
    seen_symbols: set[str] = set()
    for item in buys:
        symbol = str(item["symbol"])
        if symbol in seen_symbols:
            continue
        seen_symbols.add(symbol)
        selected_buys.append(item)
        if len(selected_buys) == allocation_slots:
            break
    return [*exits, *selected_buys]


def decision_window_blockers(
    *,
    db: Any,
    decision_date: str,
    now: datetime,
) -> list[str]:
    try:
        parsed = date.fromisoformat(decision_date)
    except ValueError:
        return ["strategy_scan_decision_date_invalid"]
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    shanghai = current.astimezone(SHANGHAI_TIME_ZONE)
    blockers: list[str] = []
    if shanghai.date() != parsed:
        blockers.append("strategy_scan_not_current_decision_date")
    if not (
        DECISION_WINDOW_START
        <= shanghai.time().replace(tzinfo=None)
        < DECISION_WINDOW_END
    ):
        blockers.append("strategy_scan_outside_reviewed_decision_window")
    dates = verified_trading_dates(
        db,
        start_date=decision_date,
        end_date=decision_date,
    )
    if dates != [decision_date]:
        blockers.append("strategy_scan_decision_date_not_verified_trading_day")
    return blockers


def prior_verified_trading_date(db: Any, decision_date: str) -> str | None:
    parsed = date.fromisoformat(decision_date)
    start = (parsed - timedelta(days=45)).isoformat()
    dates = verified_trading_dates(
        db,
        start_date=start,
        end_date=(parsed - timedelta(days=1)).isoformat(),
    )
    return dates[-1] if dates else None


def automation_safety_blockers(status: Mapping[str, Any]) -> list[str]:
    if status.get("status") == "unavailable":
        return ["strategy_scan_automation_safety_evidence_unavailable"]
    blockers: list[str] = []
    if status.get("kill_switch_enabled") is not False:
        blockers.append("strategy_scan_kill_switch_not_clear")
    if status.get("broker_submission_enabled") is not False:
        blockers.append("strategy_scan_broker_submission_must_remain_disabled")
    if status.get("manual_confirmation_required") is not True:
        blockers.append("strategy_scan_manual_confirmation_not_required")
    if str(status.get("default_execution_mode") or "") not in {
        "manual_confirmation",
        "paper_shadow",
        "dry_run",
    }:
        blockers.append("strategy_scan_execution_mode_not_safe")
    return blockers


def history_start(config: Any, market_date: str) -> str:
    end = date.fromisoformat(market_date)
    start = end - timedelta(days=540)
    configured = str(getattr(config, "start_date", "") or "").strip()
    if configured:
        try:
            start = min(start, date.fromisoformat(configured))
        except ValueError:
            pass
    return start.isoformat()


def formula_history_rows(formula_ast: Mapping[str, Any]) -> int:
    def expression_rows(expression: Any) -> int:
        if not isinstance(expression, Mapping):
            return 1
        op = str(expression.get("op") or "")
        if op in {"field", "constant"}:
            return 1
        if op in {"lag", "delta", "return"}:
            return expression_rows(expression.get("input")) + int(
                expression.get("period") or 0
            )
        if op in {"rolling_mean", "rolling_std", "zscore", "ema", "rsi"}:
            return expression_rows(expression.get("input")) + max(
                int(expression.get("window") or 1) - 1,
                0,
            )
        if op == "atr":
            return int(expression.get("window") or 1)
        if op in {
            "add",
            "subtract",
            "multiply",
            "divide",
            "gt",
            "gte",
            "lt",
            "lte",
            "equal",
            "and",
            "or",
            "cross",
        }:
            rows = max(
                expression_rows(expression.get("left")),
                expression_rows(expression.get("right")),
            )
            return rows + (1 if op == "cross" else 0)
        if op == "not":
            return expression_rows(expression.get("input"))
        return 1

    return max(
        expression_rows(formula_ast.get("entry")),
        expression_rows(formula_ast.get("exit")),
    )


def truth_projection(strategy_id: str, truth: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "strategy_id": strategy_id,
        "status": truth.get("status"),
        "trade_date": truth.get("trade_date"),
        "market_universe_snapshot_id": truth.get("market_universe_snapshot_id"),
        "active_stock_member_count": truth.get("active_stock_member_count"),
        "eligible_stock_count": truth.get("eligible_stock_count"),
        "maintenance_symbols": list(truth.get("maintenance_symbols") or []),
        "excluded_reason_counts": dict(truth.get("excluded_reason_counts") or {}),
        "minimum_history_rows": truth.get("minimum_history_rows"),
        "evidence_fingerprint": truth.get("evidence_fingerprint"),
        "blockers": list(truth.get("blockers") or []),
    }


def json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None
