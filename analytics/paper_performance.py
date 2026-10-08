"""Derived diagnostics from an isolated simulation book's recorded accounting.

Equity owns net return. Fees and slipped execution prices are already present
in that equity and position P/L; diagnostic costs are never deducted again.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, localcontext
from typing import Any, Mapping

from domain.portfolio_accounting import total_trade_fee

PAPER_HEALTH_POLICY_ID = "karkinos.research.modeled_paper_health.v1"
_ZERO = Decimal(0)


def _number(value):
    try:
        result = Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError):
        raise ValueError("paper_performance_number_invalid") from None
    if not result.is_finite():
        raise ValueError("paper_performance_nonfinite")
    return result


def _text(value):
    return format(value, ".12f").rstrip("0").rstrip(".") or "0"


def paper_book_performance(book: Mapping[str, Any]) -> dict[str, Any]:
    """Project one immutable book version, including the initial-cash baseline."""
    with localcontext() as context:
        context.prec = 40
        initial = _number(book["initial_cash"])
        rows = [step["projection"] for step in book["steps"]]
        equity, peak, drawdown = initial, initial, _ZERO
        benchmark_available = bool(book["policy"].get("benchmark"))
        series = [
            {
                "session": None,
                "equity": _text(initial),
                "net_return": "0",
                "benchmark_equity": _text(initial) if benchmark_available else None,
                "benchmark_net_return": "0" if benchmark_available else None,
                "modeled_net_excess_return": "0" if benchmark_available else None,
            }
        ]
        benchmark_equity = initial
        previous = initial
        for row in rows:
            equity = _number(row["equity"])
            peak = max(peak, equity)
            drawdown = max(drawdown, (peak - equity) / peak)
            benchmark = row.get("benchmark")
            if benchmark is None:
                benchmark_available = False
            else:
                benchmark_equity = _number(benchmark["equity"])
            series.append(
                {
                    "session": row["session"],
                    "equity": _text(equity),
                    "cash": row["cash"],
                    "net_return": _text(equity / initial - 1),
                    "session_return": _text(equity / previous - 1)
                    if previous > 0
                    else None,
                    "benchmark_equity": _text(benchmark_equity)
                    if benchmark_available
                    else None,
                    "benchmark_net_return": _text(benchmark_equity / initial - 1)
                    if benchmark_available
                    else None,
                    "modeled_net_excess_return": _text(
                        (equity - benchmark_equity) / initial
                    )
                    if benchmark_available
                    else None,
                }
            )
            previous = equity
        state = book["state"]
        fills = book["fills"]
        accepted = {attempt["publication_id"] for attempt in book["attempts"]}
        first_target_session = min(
            (attempt["session"] for attempt in book["attempts"]), default=None
        )
        evaluated_sessions = sum(
            first_target_session is not None and row["session"] >= first_target_session
            for row in rows
        )
        synchronized_benchmark = (book["policy"].get("benchmark") or {}).get(
            "activation"
        ) == "first_real_published_target_accepted_after_book_start"
        benchmark_started = (
            not synchronized_benchmark or first_target_session is not None
        )
        fees = sum(
            (
                total_trade_fee(
                    commission=_number(fill["commission"]),
                    fee_breakdown=fill.get("fee_breakdown"),
                )
                for fill in fills
            ),
            _ZERO,
        )
        slippage = sum((_number(fill["slippage"]) for fill in fills), _ZERO)
        turnover = (
            sum(
                (
                    _number(fill["fill_price"]) * _number(fill["fill_quantity"])
                    for fill in fills
                ),
                _ZERO,
            )
            / initial
        )
        contributions = []
        for symbol, position in sorted(state["positions"].items()):
            trade_pnl = _number(position["realized_pnl"]) + _number(
                position["unrealized_pnl"]
            )
            income = sum(
                (
                    _number(action["gross_amount"])
                    for action in (
                        rows[-1].get("corporate_actions", []) if rows else []
                    )
                    if action["symbol"] == symbol
                ),
                _ZERO,
            )
            contributions.append(
                {
                    "symbol": symbol,
                    "market_value": position["market_value"],
                    "realized_pnl": position["realized_pnl"],
                    "unrealized_pnl": position["unrealized_pnl"],
                    "distribution_income": _text(income),
                    "net_pnl": _text(trade_pnl + income),
                    "return_contribution": _text((trade_pnl + income) / initial),
                    "equity_weight": _text(_number(position["market_value"]) / equity)
                    if equity > 0
                    else None,
                }
            )
        explained = sum((_number(item["net_pnl"]) for item in contributions), _ZERO)
        # Gross income may belong to a fully sold position retained by accounting;
        # expose a reconciliation remainder rather than inventing attribution.
        return {
            "schema_version": "karkinos.paper_performance.v1",
            "book_id": book["id"],
            "input_version": book["version"],
            "status": "measured" if rows else "waiting",
            "outcome_fingerprint": hashlib.sha256(
                json.dumps(
                    {
                        "book_id": book["id"],
                        "version": book["version"],
                        "source": book.get("source"),
                        "code_binding": book.get("code_binding"),
                        "policy": book["policy"],
                        "initial_cash": book["initial_cash"],
                        "evaluation_start": book["evaluation_start"],
                        "steps": book["steps"],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest(),
            "evaluation_start": book["evaluation_start"],
            "through_session": book["last_settled_session"],
            "settled_sessions": len(rows),
            "accepted_publication_count": len(accepted),
            "sessions_since_first_accepted_target": evaluated_sessions,
            "waiting_sessions_before_first_target": len(rows) - evaluated_sessions,
            "benchmark_start_session": first_target_session
            if synchronized_benchmark
            else book["evaluation_start"]
            if benchmark_available
            else None,
            "health_comparison_basis": "book_cash_baseline_with_synchronized_first_accepted_target"
            if synchronized_benchmark
            else "legacy_or_unspecified_benchmark",
            "initial_cash": _text(initial),
            "equity": _text(equity),
            "net_pnl": _text(equity - initial),
            "net_return": _text(equity / initial - 1),
            "max_drawdown": _text(drawdown),
            "benchmark": book["policy"].get("benchmark"),
            "benchmark_status": "measured"
            if benchmark_available and benchmark_started and rows
            else "waiting"
            if benchmark_available
            else "unavailable",
            "benchmark_net_return": _text(benchmark_equity / initial - 1)
            if benchmark_available
            else None,
            "modeled_net_excess_return": _text((equity - benchmark_equity) / initial)
            if benchmark_available
            else None,
            "fees_paid": _text(fees),
            "slippage_cost": _text(slippage),
            "costs_already_in_equity": True,
            "turnover_notional_over_initial_cash": _text(turnover),
            "cash": state["cash"],
            "cash_weight": _text(_number(state["cash"]) / equity)
            if equity > 0
            else None,
            "cash_return_contribution": "0",
            "cash_interest_modeled": False,
            "dividend_receivable": state["dividend_receivable"],
            "dividend_income": state["dividend_income"],
            "position_contributions": contributions,
            "pnl_reconciliation_residual": _text(equity - initial - explained),
            "target_attempts": book["attempts"],
            "equity_series": series,
            "return_basis": book["policy"].get(
                "corporate_action_mode", "reported_distributions_gross"
            ),
            "includes_fees": True,
            "includes_slippage": True,
            "corporate_action_coverage_complete": False,
            "model_assumptions_only": True,
            "account_authority": False,
            "limitations": book["policy"]["limitations"],
        }


def validate_paper_health_policy(value):
    if not isinstance(value, Mapping) or set(value) != {
        "mode",
        "minimum_settled_sessions",
        "maximum_drawdown",
        "minimum_net_excess_return",
    }:
        raise ValueError("paper_health_policy_invalid")
    minimum = value["minimum_settled_sessions"]
    drawdown = _number(value["maximum_drawdown"])
    excess = _number(value["minimum_net_excess_return"])
    if (
        value["mode"] not in ("report_only", "pause_on_breach")
        or type(minimum) is not int
        or not 1 <= minimum <= 2000
        or not 0 <= drawdown <= 1
        or not -1 <= excess <= 1
    ):
        raise ValueError("paper_health_policy_invalid")
    return {
        "mode": value["mode"],
        "minimum_settled_sessions": minimum,
        "maximum_drawdown": _text(drawdown),
        "minimum_net_excess_return": _text(excess),
    }


def evaluate_paper_health(performance, policy):
    result = {
        "policy_id": PAPER_HEALTH_POLICY_ID,
        "status": "not_configured",
        "action": "none",
        "input_version": performance["input_version"],
        "through_session": performance["through_session"],
        "model_assumptions_only": True,
        "account_authority": False,
        "qualification_authority": False,
        "breaches": [],
        "comparison_basis": performance.get("health_comparison_basis"),
        "benchmark_start_session": performance.get("benchmark_start_session"),
        "waiting_sessions_before_first_target": performance.get(
            "waiting_sessions_before_first_target"
        ),
    }
    if policy is None:
        return result
    policy = validate_paper_health_policy(policy)
    result["policy"] = policy
    if performance["status"] != "measured":
        result["status"] = "unavailable"
    elif (
        performance.get("sessions_since_first_accepted_target", 0)
        < policy["minimum_settled_sessions"]
    ):
        result["status"] = "insufficient_evidence"
    elif performance["benchmark_status"] != "measured":
        result["status"] = "unavailable"
    else:
        if _number(performance["max_drawdown"]) > _number(policy["maximum_drawdown"]):
            result["breaches"].append("maximum_drawdown")
        if _number(performance["modeled_net_excess_return"]) < _number(
            policy["minimum_net_excess_return"]
        ):
            result["breaches"].append("minimum_net_excess_return")
        result["status"] = "threshold_breached" if result["breaches"] else "within_rule"
        result["action"] = (
            "pause_paper_target_acceptance"
            if result["breaches"] and policy["mode"] == "pause_on_breach"
            else "continue_observation"
            if not result["breaches"]
            else "review"
        )
    return result
