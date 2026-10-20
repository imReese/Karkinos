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

from data.research_market_data import (
    resolve_daily_bar_receipts as resolve_daily_bar_receipts,
)
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
    "karkinos.promoted_strategy_universe_scan_evaluation_policy.v5"
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


def active_action_blockers(
    blockers: Sequence[str],
    selected_signals: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Filter blockers to those that actively block the selected actions."""
    if not selected_signals:
        return list(dict.fromkeys(str(item) for item in blockers if str(item)))

    has_buys = any(s.get("direction") == "buy" for s in selected_signals)
    held_symbols = {
        str(s.get("symbol") or "")
        for s in selected_signals
        if s.get("direction") == "sell"
    }

    relevant: list[str] = []
    for blocker in blockers:
        blocker_str = str(blocker)
        if not blocker_str:
            continue
        # Buy-only blockers do not block an all-sell (exit) action set
        if not has_buys:
            if (
                ":full_market_evidence_incomplete" in blocker_str
                or ":full_market_eligible_stock_pool_too_small" in blocker_str
                or ":market_universe_eligible_members_missing" in blocker_str
                or ":full_market_trading_date_evidence_incomplete" in blocker_str
                or ":full_market_daily_receipt_coverage_incomplete" in blocker_str
                or ":full_market_daily_receipt_invalid" in blocker_str
                or blocker_str.startswith("daily_candidate_quote_freeze:")
                or "current_board_permission_changed" in blocker_str
                or blocker_str == "unsupported_trade_unit"
                or blocker_str == "insufficient_cash_for_one_lot"
            ):
                continue
        # Per-holding exit blockers only block the affected symbol
        if (
            ":holding_outside_active_stock_universe:" in blocker_str
            or ":holding_exit_evidence_incomplete:" in blocker_str
        ):
            if not any(
                f":{sym}:" in blocker_str or blocker_str.endswith(f":{sym}")
                for sym in held_symbols
            ):
                continue
        relevant.append(blocker_str)
    return list(dict.fromkeys(relevant))


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
    db: Any = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Keep research signals intact while choosing only affordable account buys."""
    signals, profile_blocked = policy_entry_signals(
        signals, portfolio=portfolio, decision_date=decision_date, db=db
    )
    if any(signal.get("portfolio_policy_id") for signal in signals):
        policy_buys = [
            row
            for row in signals
            if row.get("direction") == "buy" and row.get("portfolio_policy_id")
        ]
        legacy_buys = [
            row
            for row in signals
            if row.get("direction") == "buy" and not row.get("portfolio_policy_id")
        ]
        if policy_buys and legacy_buys:
            selected, blocked = _mixed_account_signals(
                signals,
                config=config,
                decision_date=decision_date,
                portfolio=portfolio,
                policy=policy,
                cash_buffer_ratio=cash_buffer_ratio,
                db=db,
            )
            return selected, [*profile_blocked, *blocked]
        if policy_buys:
            selected, blocked, _ = _portfolio_account_signals(
                signals,
                portfolio=portfolio,
                cash_buffer_ratio=cash_buffer_ratio,
                decision_date=decision_date,
                db=db,
            )
            return selected, [*profile_blocked, *blocked]
    selected, blocked = _legacy_account_signals(
        signals,
        config=config,
        decision_date=decision_date,
        portfolio=portfolio,
        policy=policy,
        cash_buffer_ratio=cash_buffer_ratio,
    )
    return selected, [*profile_blocked, *blocked]


def policy_entry_signals(signals, *, portfolio, decision_date, db):
    """Apply the frozen entry universe before ranking, preserving exit maintenance."""
    from domain.instrument import entry_board_symbols
    from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
    from server.contracts.recommendation_publication import validate_entry_board_policy
    from server.services.account_board_permissions import entry_board_policy_blocker

    selected, blocked, profiles = [], [], {}
    for row in signals:
        if row.get("direction") != "buy" or not row.get("portfolio_policy_id"):
            selected.append(row)
            continue
        identity = str(row["strategy_id"])
        if identity not in profiles:
            try:
                if row["portfolio_policy_id"] != FORMULA_PORTFOLIO_POLICY_ID:
                    raise ValueError("portfolio_policy_conflict")
                state = db.get_strategy_promotion_state_sync(identity)
                payload = json_object(state.get("payload_json"))
                profile = validate_entry_board_policy(
                    payload["readiness"]["deployment_validation"].get(
                        "entry_board_policy"
                    )
                )
                permissions = portfolio.get("board_buy_permissions")
                blocker = entry_board_policy_blocker(
                    profile, permissions, decision_date=decision_date
                )
                profiles[identity] = profile, blocker
            except (
                AttributeError,
                KeyError,
                LookupError,
                TypeError,
                ValueError,
            ) as exc:
                profiles[identity] = None, str(exc)
        profile, blocker = profiles[identity]
        if not blocker and str(row["symbol"]) not in entry_board_symbols(
            profile["allowed_boards"], [str(row["symbol"])]
        ):
            blocker = "frozen_entry_board_policy"
        if blocker:
            blocked.append(
                {
                    "strategy_id": identity,
                    "symbol": str(row["symbol"]),
                    "reason": blocker,
                }
            )
        else:
            selected.append(row)
    return selected, blocked


def _legacy_account_signals(
    signals, *, config, decision_date, portfolio, policy, cash_buffer_ratio
):
    """Preserve the existing human-source permission and minimum-lot checks."""
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
    equity = _nonnegative_decimal(
        portfolio.get("total_equity") or portfolio.get("stock_equity")
    )
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


def _mixed_account_signals(
    signals, *, config, decision_date, portfolio, policy, cash_buffer_ratio, db
):
    """Rank once and reserve one account budget across independent sources."""
    from domain.instrument import make_research_stock
    from domain.research_targets import allocate_formula_targets

    exits = [row for row in signals if row.get("direction") == "sell"]
    exit_symbols = {str(row["symbol"]) for row in exits}
    cash = _nonnegative_decimal(portfolio.get("cash"))
    equity = _nonnegative_decimal(portfolio.get("total_equity"))
    values = portfolio.get("stock_position_market_values")
    reason = None
    if (
        portfolio.get("fact_authority") != "persisted_valuation_snapshot"
        or cash is None
        or equity is None
        or equity <= 0
    ):
        reason = "cash_evidence_missing"
    if not isinstance(values, Mapping) or any(
        symbol not in values for symbol in portfolio.get("stock_symbols", [])
    ):
        reason = "position_value_evidence_missing"
    position_values = {}
    if isinstance(values, Mapping):
        for symbol, value in values.items():
            parsed = _nonnegative_decimal(value)
            if parsed is None:
                reason = "position_value_evidence_missing"
                break
            if parsed:
                position_values[str(symbol)] = parsed
    available = (
        max(Decimal(0), cash - equity * cash_buffer_ratio)
        if cash is not None and equity is not None
        else Decimal(0)
    )
    selected, blocked, seen = [], [], set()
    for row in sorted(
        (row for row in signals if row.get("direction") == "buy"),
        key=lambda row: (
            -float(row["ranking_liquidity"]),
            str(row["symbol"]),
            str(row["strategy_id"]),
        ),
    ):
        symbol = str(row["symbol"])
        if symbol in seen:
            continue
        seen.add(symbol)
        blocker = reason or (
            "account_exit_signal_conflict" if symbol in exit_symbols else None
        )
        if blocker:
            blocked.append(
                {
                    "strategy_id": str(row["strategy_id"]),
                    "symbol": symbol,
                    "reason": blocker,
                }
            )
            continue
        current_portfolio = {
            **portfolio,
            "cash": available,
            "stock_position_market_values": position_values,
            "stock_symbols": list(position_values),
        }
        if row.get("portfolio_policy_id"):
            accepted, rejected, allocation = _portfolio_account_signals(
                [row],
                portfolio=current_portfolio,
                cash_buffer_ratio=Decimal(0),
                decision_date=decision_date,
                db=db,
            )
            selected.extend(accepted)
            blocked.extend(rejected)
        else:
            accepted, rejected = _legacy_account_signals(
                [row],
                config=config,
                decision_date=decision_date,
                portfolio=current_portfolio,
                policy=policy,
                cash_buffer_ratio=Decimal(0),
            )
            blocked.extend(rejected)
            if not accepted:
                continue
            price = _nonnegative_decimal(row.get("frozen_close"))
            weight = _nonnegative_decimal(row.get("target_weight"))
            if (
                price is None
                or price <= 0
                or weight is None
                or weight <= 0
                or weight > 1
            ):
                blocked.append(
                    {
                        "strategy_id": str(row["strategy_id"]),
                        "symbol": symbol,
                        "reason": "frozen_price_or_target_invalid",
                    }
                )
                continue

            def cost(_symbol, quote_price, quantity):
                fee = resolve_manual_trade_fee_breakdown(
                    config,
                    asset_class="stock",
                    direction="buy",
                    quantity=float(quantity),
                    price=float(quote_price),
                    symbol=symbol,
                )
                gross = quote_price * quantity
                configured_fee = (
                    _nonnegative_decimal(fee.total_fee) if fee is not None else None
                )
                return gross + max(
                    gross * policy.fee_buffer_rate, configured_fee or Decimal(0)
                )

            allocation = allocate_formula_targets(
                entries=[symbol],
                exits=sorted(exit_symbols),
                position_values=position_values,
                prices={symbol: price},
                liquidity={symbol: Decimal(str(row["ranking_liquidity"]))},
                lot_sizes={symbol: make_research_stock(symbol, symbol).lot_size},
                cash=available,
                equity=equity,
                buy_cost=cost,
                max_positions=policy.allocation_slots,
                max_symbol_weight=weight,
                cash_buffer_ratio=Decimal(0),
            )
            if symbol in allocation["selected_entries"]:
                selected.append(
                    {
                        **row,
                        "target_weight": float(allocation["target_weights"][symbol]),
                    }
                )
            else:
                blocked.append(
                    {
                        "strategy_id": str(row["strategy_id"]),
                        "symbol": symbol,
                        "reason": allocation["rejected_entries"].get(
                            symbol, "already_held"
                        ),
                    }
                )
        if allocation is not None and symbol in allocation["entry_quantities"]:
            # A policy-selected but account-blocked top name keeps its slot;
            # replacing it with another name would change the validated ranking.
            position_values[symbol] = allocation["entry_quantities"][symbol] * Decimal(
                str(row["frozen_close"])
            )
            available -= allocation["purchase_costs"][symbol]
    return [*exits, *selected], blocked


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
        "stock_position_market_values": portfolio.get("stock_position_market_values"),
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


def promoted_history_start(promoted, config, market_date):
    """Load each frozen policy's full initialization; legacy retains runtime scope."""
    return (
        min(
            str(item["history_start"])
            if item.get("portfolio_policy_id") or item.get("history_start")
            else history_start(config, market_date)
            for item in promoted
        )
        if promoted
        else history_start(config, market_date)
    )


def resolve_daily_bar_receipt_provider(
    *,
    data_store: Any,
    start_date: str,
    end_date: str,
    config: Any = None,
    snapshot: Mapping[str, Any] | None = None,
    preferred_provider: str | None = None,
) -> str:
    """Resolve the authoritative daily bar receipt provider for replay."""
    preferred = str(preferred_provider or "").strip()
    available_providers: list[str] = []
    if hasattr(data_store, "list_market_daily_ingestion_receipt_providers"):
        try:
            available_providers = (
                data_store.list_market_daily_ingestion_receipt_providers(
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        except Exception:
            available_providers = []

    if preferred:
        return preferred

    snapshot_provider = str(
        (snapshot.get("provider_name") if isinstance(snapshot, Mapping) else "") or ""
    ).strip()
    if (
        snapshot_provider
        and available_providers
        and snapshot_provider in available_providers
    ):
        return snapshot_provider

    config_candidates: list[str] = []
    if config is not None:
        try:
            from data.source_policy import MarketDataUseCase
            from data.source_routing import configured_data_provider_names

            config_candidates.extend(
                configured_data_provider_names(config, MarketDataUseCase.DAILY_BARS)
            )
        except Exception:
            pass
        data_source = str(getattr(config, "data_source", "") or "").strip()
        if data_source and data_source not in config_candidates:
            config_candidates.append(data_source)

    for candidate in config_candidates:
        if candidate in available_providers:
            return candidate

    if len(available_providers) == 1:
        return available_providers[0]
    if available_providers:
        return available_providers[0]

    if config_candidates:
        return config_candidates[0]
    if snapshot_provider:
        return snapshot_provider
    return str(getattr(config, "data_source", "") or "").strip()


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
    unavailable_policy_history: list[str] = []
    target_weight = 1.0 / policy.allocation_slots
    held = set(held_stock_symbols)
    for promoted_strategy in promoted:
        strategy_id = str(promoted_strategy["strategy_id"])
        strategy = dict(promoted_strategy["strategy"])
        formula_ast = strategy.get("formula_ast")
        selected_universe = tuple(
            str(symbol) for symbol in strategy.get("selected_universe") or []
        )
        strategy_start = str(promoted_strategy.get("history_start") or start_date)
        strategy_frames = (
            {
                symbol: frame.loc[
                    pd.to_datetime(frame["timestamp"]).dt.date
                    >= date.fromisoformat(strategy_start)
                ].copy()
                for symbol, frame in frames.items()
            }
            if promoted_strategy.get("history_start")
            else frames
        )
        strategy_dates = [day for day in trading_dates if day >= strategy_start]
        strategy_receipts = [
            row
            for row in receipts
            if str(row.get("trade_date") or "") >= strategy_start
        ]
        if promoted_strategy.get("portfolio_policy_id") and set(strategy_dates) - {
            str(row.get("trade_date") or "") for row in strategy_receipts
        }:
            blocker = f"strategy_frozen_history_unavailable:{strategy_id}"
            truths[strategy_id] = {
                "status": "blocked",
                "blockers": [blocker],
                "minimum_history_rows": policy.minimum_history_rows,
            }
            unavailable_policy_history.append(blocker)
            continue
        try:
            validate_formula_ast(formula_ast, universe_size=len(selected_universe))
            truth = build_full_market_universe_truth(
                snapshot=snapshot,
                frames=strategy_frames,
                receipts=strategy_receipts,
                required_trading_dates=strategy_dates,
                start_date=strategy_start,
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
        has_truth_blockers = truth.get("status") != "complete"
        if has_truth_blockers:
            blockers.extend(
                f"strategy_full_market_truth:{strategy_id}:{item}"
                for item in truth.get("blockers") or []
            )
            # Fail-closed for new buy candidates only; held positions may still exit
            eligible_symbols: list[str] = []
        else:
            eligible_symbols = list(truth.get("eligible_symbols") or [])
        evaluated_signals = evaluate_strategy_signals(
            strategy_id=strategy_id,
            formula_ast=formula_ast,
            universe_size=len(selected_universe),
            target_weight=target_weight,
            frames=strategy_frames,
            eligible_symbols=eligible_symbols,
            maintenance_symbols=list(truth.get("maintenance_symbols") or []),
            held_symbols=held,
            market_date=market_date,
        )
        if promoted_strategy.get("portfolio_policy_id"):
            for signal in evaluated_signals:
                signal["portfolio_policy_id"] = promoted_strategy["portfolio_policy_id"]
        raw_signals.extend(evaluated_signals)
    if not raw_signals:
        # An unobservable policy cannot be reported as an ordinary no-signal day.
        blockers.extend(unavailable_policy_history)
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


def _portfolio_account_signals(
    signals, *, portfolio, cash_buffer_ratio, decision_date, db
):
    """The same complete-capital kernel, adapted to current account facts."""
    from domain.instrument import make_research_stock
    from domain.research_targets import (
        FORMULA_PORTFOLIO_POLICY_ID,
        allocate_formula_targets,
    )
    from server.persistence.strategy_research import StrategyResearchAuditStore
    from server.services.reviewed_fee_schedule import (
        resolve_frozen_deployment_fee_schedule,
    )

    exits = [row for row in signals if row["direction"] == "sell"]
    buys, blocked = {}, []
    values = portfolio.get("stock_position_market_values")
    equity = _nonnegative_decimal(portfolio.get("total_equity"))
    cash = _nonnegative_decimal(portfolio.get("cash"))
    reason = None
    if not isinstance(values, Mapping) or any(
        s not in values for s in portfolio.get("stock_symbols", [])
    ):
        reason = "position_value_evidence_missing"
    if (
        portfolio.get("fact_authority") != "persisted_valuation_snapshot"
        or equity is None
        or equity <= 0
        or cash is None
    ):
        reason = "cash_evidence_missing"
    calculators, capitals, validated_limits = {}, [], []
    for row in sorted(
        signals,
        key=lambda item: (
            -float(item.get("ranking_liquidity", 0)),
            str(item["symbol"]),
            str(item["strategy_id"]),
        ),
    ):
        if row["direction"] != "buy":
            continue
        symbol = row["symbol"]
        blocker = reason
        if row.get("portfolio_policy_id") != FORMULA_PORTFOLIO_POLICY_ID:
            blocker = blocker or "portfolio_policy_conflict"
        if blocker is None:
            try:
                identity = row["strategy_id"]
                if identity not in calculators:
                    state = db.get_strategy_promotion_state_sync(identity)
                    payload = json_object(state.get("payload_json"))
                    validation = payload["readiness"]["deployment_validation"]
                    final = StrategyResearchAuditStore(db._path).get_sealed_test(
                        validation["final_evaluation_id"]
                    )
                    binding = final["evidence"]["reservation"]
                    resolution = resolve_frozen_deployment_fee_schedule(
                        db, binding["fee_schedule"], tuple(r["symbol"] for r in signals)
                    )
                    if not (
                        date.fromisoformat(resolution.review.effective_start_date)
                        <= date.fromisoformat(decision_date)
                        <= date.fromisoformat(resolution.review.effective_end_date)
                    ):
                        blocker = "reviewed_fee_schedule_action_date_not_covered"
                    else:
                        calculators[identity] = resolution.commission_calc
                        capitals.append(Decimal(str(validation["initial_cash"])))
                        validated_limits.append(
                            binding["publication_grant"]["risk_limits"]
                        )
                if blocker is None:
                    buys.setdefault(symbol, row)
            except (ValueError, KeyError, TypeError, LookupError, AttributeError):
                blocker = "validated_account_execution_binding_unavailable"
        if blocker:
            blocked.append(
                {
                    "strategy_id": str(row["strategy_id"]),
                    "symbol": str(symbol),
                    "reason": blocker,
                }
            )
    if not buys:
        return exits, blocked, None
    scoped_equity = min(equity, *capitals)
    held_values = [
        Decimal(str(value)) for value in values.values() if Decimal(str(value)) > 0
    ]
    for limits in validated_limits:
        if (
            len(held_values) > limits["max_positions"]
            or sum(held_values, Decimal(0)) / scoped_equity
            > Decimal(str(limits["max_gross_weight"]))
            or max(held_values, default=Decimal(0)) / scoped_equity
            > Decimal(str(limits["max_symbol_weight"]))
        ):
            blocked.extend(
                {
                    "strategy_id": str(row["strategy_id"]),
                    "symbol": symbol,
                    "reason": "current_portfolio_exceeds_publication_risk_bounds",
                }
                for symbol, row in buys.items()
            )
            return exits, blocked, None
    prices = {symbol: Decimal(str(row["frozen_close"])) for symbol, row in buys.items()}
    instruments = {symbol: make_research_stock(symbol, symbol) for symbol in buys}

    from server.services.backtest_costs import quote_formula_purchase

    def cost(symbol, price, quantity):
        return quote_formula_purchase(
            calculators[buys[symbol]["strategy_id"]],
            instruments[symbol],
            symbol,
            price,
            quantity,
        )

    try:
        decision = allocate_formula_targets(
            entries=list(buys),
            exits=[row["symbol"] for row in exits],
            position_values={s: Decimal(str(value)) for s, value in values.items()},
            prices=prices,
            liquidity={
                s: Decimal(str(row["ranking_liquidity"])) for s, row in buys.items()
            },
            lot_sizes={s: item.lot_size for s, item in instruments.items()},
            cash=cash,
            equity=scoped_equity,
            buy_cost=cost,
            cash_buffer_ratio=cash_buffer_ratio,
        )
    except ValueError as exc:
        blocked.extend(
            {
                "strategy_id": str(row["strategy_id"]),
                "symbol": symbol,
                "reason": "validated_cost_or_portfolio_constraint:" + str(exc),
            }
            for symbol, row in buys.items()
        )
        return exits, blocked, None
    selected = []
    for symbol in decision["selected_entries"]:
        selected.append(
            {
                **buys[symbol],
                "target_weight": float(
                    decision["target_weights"][symbol] * scoped_equity / equity
                ),
            }
        )
    blocked.extend(
        {"strategy_id": str(buys[s]["strategy_id"]), "symbol": s, "reason": why}
        for s, why in decision["rejected_entries"].items()
    )
    return [*exits, *selected], blocked, decision
