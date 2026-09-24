"""Deterministic projections and fail-closed checks for promoted-strategy scans."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.formula_dsl import (
    FORMULA_AST_CONTRACT,
    evaluate_formula,
    validate_formula_ast,
)
from server.services.manual_trade_fees import resolve_manual_trade_fee_breakdown
from server.services.market_universe_automation import verified_trading_dates
from server.services.market_universe_truth import (
    FULL_MARKET_UNIVERSE_TRUTH_SCHEMA_VERSION,
    MarketUniversePolicy,
    build_full_market_universe_truth,
    normalize_a_share_members,
)

SHANGHAI_TIME_ZONE = ZoneInfo("Asia/Shanghai")
DECISION_WINDOW_START = time(9, 35)
DECISION_WINDOW_END = time(9, 45)
PROMOTED_STRATEGY_SCAN_EVALUATION_POLICY_VERSION = (
    "karkinos.promoted_strategy_universe_scan_evaluation_policy.v4"
)
SIGNAL_SELECTION_POLICY = (
    "exits_first_fail_closed_on_multi_strategy_sell_symbol_conflict_"
    "then_account_eligible_20d_median_amount_desc_then_symbol_asc"
)
_RESTRICTED_BOARDS = frozenset({"chinext", "star", "beijing"})
_DEFAULT_CASH_BUFFER_RATIO = Decimal("0.03")


def promoted_scan_evaluation_policy_fingerprint(
    policy: MarketUniversePolicy,
) -> str:
    """Bind every explicit policy contract used to interpret one frozen scan."""

    return "sha256:" + content_fingerprint(
        {
            "schema_version": PROMOTED_STRATEGY_SCAN_EVALUATION_POLICY_VERSION,
            "market_universe_policy": policy.to_dict(),
            "full_market_universe_truth_schema_version": (
                FULL_MARKET_UNIVERSE_TRUTH_SCHEMA_VERSION
            ),
            "formula_ast_contract": FORMULA_AST_CONTRACT,
            "signal_selection_policy": SIGNAL_SELECTION_POLICY,
        }
    )


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


def aggregate_ranked_signals(
    signals: list[dict[str, Any]],
    *,
    allocation_slots: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Rank signals and surface ambiguous account-level exits without choosing one."""

    exit_strategy_ids_by_symbol: dict[str, list[str]] = {}
    for signal in signals:
        if signal.get("direction") != "sell":
            continue
        exit_strategy_ids_by_symbol.setdefault(str(signal["symbol"]), []).append(
            str(signal["strategy_id"])
        )
    blockers = [
        "promoted_strategy_exit_signal_conflict:"
        f"{symbol}:{','.join(sorted(set(strategy_ids)))}"
        for symbol, strategy_ids in sorted(exit_strategy_ids_by_symbol.items())
        if len(strategy_ids) > 1
    ]
    return (
        select_ranked_signals(signals, allocation_slots=allocation_slots),
        blockers,
    )


def board_buy_blocker(
    symbol: str,
    permission_evidence: Any,
    decision_date: str,
) -> str | None:
    """Resolve a stock's current buy permission independently of UI projection."""
    identity = normalize_a_share_members([symbol])
    board = identity[0]["board"] if identity else "unknown"
    if board == "unknown":
        return "board_permission_unknown"
    if board not in _RESTRICTED_BOARDS:
        return None
    evidence = permission_evidence if isinstance(permission_evidence, Mapping) else {}
    current = (
        evidence.get("status") == "current"
        and evidence.get("resolved_for_date") == decision_date
        and _prefixed_sha256(evidence.get("evidence_fingerprint"))
        and isinstance(evidence.get("boards"), Mapping)
    )
    permission = evidence["boards"].get(board) if current else None
    if permission != "enabled":
        return (
            "board_permission_disabled"
            if permission == "disabled"
            else "board_permission_unknown"
        )
    if board == "star":
        # The downstream account allocator still rounds STAR orders to
        # 100 shares; STAR's minimum buy order is 200 shares.
        return "unsupported_trade_unit"
    return None


def account_eligible_signals(
    signals: list[dict[str, Any]],
    *,
    config: Any,
    decision_date: str,
    portfolio: Mapping[str, Any],
    policy: MarketUniversePolicy,
    cash_buffer_ratio: Decimal,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Keep research signals intact while choosing only affordable account buys."""
    exits = [signal for signal in signals if signal.get("direction") == "sell"]
    buys = sorted(
        (signal for signal in signals if signal.get("direction") == "buy"),
        key=lambda item: (
            -float(item["ranking_liquidity"]),
            str(item["symbol"]),
            str(item["strategy_id"]),
        ),
    )
    permission_evidence = portfolio.get("board_buy_permissions")
    cash = (
        _nonnegative_decimal(portfolio.get("cash"))
        if portfolio.get("fact_authority") == "persisted_valuation_snapshot"
        else None
    )
    equity = _nonnegative_decimal(portfolio.get("total_equity"))
    remaining = (
        max(cash - equity * cash_buffer_ratio, Decimal("0"))
        if cash is not None and equity is not None
        else None
    )
    selected_buys: list[dict[str, Any]] = []
    blocked: list[dict[str, str]] = []
    seen_symbols: set[str] = set()
    for signal in buys:
        symbol = str(signal["symbol"])
        identity = normalize_a_share_members([symbol])
        board = identity[0]["board"] if identity else "unknown"
        reason = board_buy_blocker(symbol, permission_evidence, decision_date)
        price = _nonnegative_decimal(signal.get("frozen_close"))
        if reason is None and (price is None or price == 0):
            reason = "frozen_price_invalid"
        if reason is None and remaining is None:
            reason = "cash_evidence_missing"
        if reason is None and remaining is not None and price is not None:
            gross = price * policy.lot_size
            fee = resolve_manual_trade_fee_breakdown(
                config,
                asset_class="stock",
                direction="buy",
                quantity=float(policy.lot_size),
                price=float(price),
                symbol=symbol,
            )
            configured_fee = (
                _nonnegative_decimal(fee.total_fee) if fee is not None else None
            )
            minimum_cost = gross + max(
                gross * policy.fee_buffer_rate,
                configured_fee or Decimal("0"),
            )
            if minimum_cost > remaining:
                reason = "insufficient_cash_for_one_lot"
        if reason is not None:
            blocked.append(
                {
                    "strategy_id": str(signal["strategy_id"]),
                    "symbol": symbol,
                    "board": board,
                    "reason": reason,
                }
            )
            continue
        if symbol in seen_symbols or len(selected_buys) >= policy.allocation_slots:
            continue
        seen_symbols.add(symbol)
        selected_buys.append(signal)
        if remaining is not None and price is not None:
            remaining -= (
                price * policy.lot_size * (Decimal("1") + policy.fee_buffer_rate)
            )
    return [*exits, *selected_buys], blocked


def cash_buffer_ratio(config: Any) -> Decimal:
    configured = getattr(config, "trading_plan_min_cash_buffer_ratio", None)
    if configured is None:
        configured = getattr(config, "min_cash_buffer_ratio", None)
    ratio = _nonnegative_decimal(configured)
    return ratio if ratio is not None and ratio <= 1 else _DEFAULT_CASH_BUFFER_RATIO


def portfolio_scan_binding(
    portfolio: Mapping[str, Any],
    *,
    held_symbols: Sequence[str],
    reserve_ratio: Decimal,
) -> dict[str, Any]:
    permissions = portfolio.get("board_buy_permissions")
    permissions = dict(permissions) if isinstance(permissions, Mapping) else {}
    capital = {
        "valuation_snapshot_id": portfolio["valuation_snapshot_id"],
        "valuation_status": portfolio["valuation_status"],
        "total_equity": portfolio["total_equity"],
        "cash": portfolio.get("cash"),
        "fact_authority": portfolio.get("fact_authority"),
        "cash_buffer_ratio": str(reserve_ratio),
        "board_buy_permissions": permissions,
    }
    return {
        "valuation_snapshot_id": portfolio["valuation_snapshot_id"] or None,
        "valuation_status": portfolio["valuation_status"],
        "held_symbol_fingerprint": "sha256:" + content_fingerprint(held_symbols),
        "held_stock_count": len(held_symbols),
        "available_cash": portfolio.get("cash"),
        "fact_authority": portfolio.get("fact_authority"),
        "cash_buffer_ratio": str(reserve_ratio),
        "board_buy_permissions_fingerprint": permissions.get("evidence_fingerprint"),
        "capital_constraint_fingerprint": "sha256:" + content_fingerprint(capital),
    }


def _nonnegative_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and number >= 0 else None


def _prefixed_sha256(value: Any) -> bool:
    text = str(value or "")
    return (
        len(text) == 71
        and text.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in text[7:])
    )


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
    try:
        dates = verified_trading_dates(
            db,
            start_date=decision_date,
            end_date=decision_date,
        )
    except ValueError:
        dates = []
    if dates != [decision_date]:
        blockers.append("strategy_scan_decision_date_not_verified_trading_day")
    return blockers


def prior_verified_trading_date(db: Any, decision_date: str) -> str | None:
    try:
        parsed = date.fromisoformat(decision_date)
        start = (parsed - timedelta(days=45)).isoformat()
        dates = verified_trading_dates(
            db,
            start_date=start,
            end_date=(parsed - timedelta(days=1)).isoformat(),
        )
    except ValueError:
        return None
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
            start = date.fromisoformat(configured)
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


def evaluate_promoted_strategy_market(
    *,
    promoted: Sequence[Mapping[str, Any]],
    market_date: str,
    snapshot: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    receipts: Sequence[Mapping[str, Any]],
    trading_dates: Sequence[str],
    start_date: str,
    total_equity: float,
    held_stock_symbols: Sequence[str],
    policy: MarketUniversePolicy,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Evaluate the one canonical market truth and signal path for every strategy."""

    truths: dict[str, dict[str, Any]] = {}
    raw_signals: list[dict[str, Any]] = []
    blockers: list[str] = []
    target_weight = 1.0 / policy.allocation_slots
    held = set(held_stock_symbols)
    for promoted_strategy in promoted:
        strategy_id = str(promoted_strategy["strategy_id"])
        strategy = dict(promoted_strategy["strategy"])
        formula_ast = strategy.get("formula_ast")
        selected_universe = tuple(
            str(symbol) for symbol in strategy.get("selected_universe") or []
        )
        try:
            validate_formula_ast(formula_ast, universe_size=len(selected_universe))
            truth = build_full_market_universe_truth(
                snapshot=snapshot,
                frames=frames,
                receipts=receipts,
                required_trading_dates=trading_dates,
                start_date=start_date,
                end_date=market_date,
                initial_cash=total_equity,
                target_weight=target_weight,
                held_symbols=held_stock_symbols,
                minimum_history_rows=max(
                    policy.minimum_history_rows,
                    formula_history_rows(formula_ast),
                ),
                policy=policy,
            )
        except Exception as exc:
            blockers.append(
                f"strategy_full_market_truth_failed:{strategy_id}:"
                f"{type(exc).__name__}:{exc}"
            )
            continue
        truths[strategy_id] = truth
        if truth.get("status") != "complete":
            blockers.extend(
                f"strategy_full_market_truth:{strategy_id}:{item}"
                for item in truth.get("blockers") or []
            )
            continue
        raw_signals.extend(
            evaluate_strategy_signals(
                strategy_id=strategy_id,
                formula_ast=formula_ast,
                universe_size=len(selected_universe),
                target_weight=target_weight,
                frames=frames,
                eligible_symbols=list(truth["eligible_symbols"]),
                maintenance_symbols=list(truth["maintenance_symbols"]),
                held_symbols=held,
                market_date=market_date,
            )
        )
    return truths, raw_signals, blockers


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
