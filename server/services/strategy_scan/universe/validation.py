"""Read-only freshness validation for persisted promoted-strategy scans."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from core.types import InstrumentType
from server.ai_runtime.contracts import content_fingerprint
from server.services.account.valuation import (
    is_asset_class_valuation_healthy,
    portfolio_stock_valuation_from_snapshot,
    valuation_snapshot_from_row,
)
from server.services.market.market_universe_automation import verified_trading_dates
from server.services.market.market_universe_truth import (
    MarketUniversePolicy,
    require_complete_market_universe_snapshot,
)
from server.services.strategy_scan.universe.evaluation import (
    account_eligible_signals,
    active_action_blockers,
    aggregate_ranked_signals,
    automation_safety_blockers,
    board_buy_blocker,
    buy_candidates_cash_requirement,
    cash_buffer_ratio,
    evaluate_promoted_strategy_market,
    market_evaluation_cache_key,
    portfolio_scan_binding,
    prior_verified_trading_date,
    promoted_history_start,
    promoted_scan_evaluation_policy_fingerprint,
    resolve_daily_bar_receipt_provider,
    resolve_daily_bar_receipts,
)
from server.services.strategy_scan.universe.formula_inputs import (
    load_exact_formula_market_inputs,
)


def _nonnegative_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
    except Exception:
        return None
    return number if number.is_finite() and number >= 0 else None


def _verify_bound_valuation(
    *,
    db: Any,
    bound_val_id: str | None,
    bound_ledger: str | None,
    bound_cutoff: int | None,
    blockers: list[str],
) -> dict[str, Any] | None:
    if not bound_val_id:
        if bound_ledger is not None:
            blockers.append("promoted_strategy_scan_current_portfolio_changed")
        return None
    if not hasattr(db, "get_valuation_snapshot_sync"):
        if bound_ledger is not None:
            blockers.append("promoted_strategy_scan_current_portfolio_changed")
        return None
    raw_snap = db.get_valuation_snapshot_sync(bound_val_id)
    if (
        raw_snap is None
        or not isinstance(raw_snap, Mapping)
        or "snapshot_id" not in raw_snap
    ):
        if bound_ledger is not None:
            blockers.append("promoted_strategy_scan_current_portfolio_changed")
        return None
    bound_snap = valuation_snapshot_from_row(dict(raw_snap))
    if not is_asset_class_valuation_healthy(bound_snap, "stock"):
        blockers.append("promoted_strategy_scan_current_portfolio_changed")
    if bound_ledger is not None and (
        bound_snap.get("ledger_fingerprint") != bound_ledger
        or int(bound_snap.get("ledger_cutoff_id") or 0) != int(bound_cutoff or 0)
    ):
        blockers.append("promoted_strategy_scan_current_portfolio_changed")
    return bound_snap


def _validate_current_portfolio_binding(
    *,
    portfolio: Mapping[str, Any],
    bound_binding: Mapping[str, Any],
    current_portfolio_binding: Mapping[str, Any],
    held_symbols: list[str],
    reserve_ratio: Any,
    bound_val_id: str | None,
    bound_ledger: str | None,
    blockers: list[str],
) -> None:
    has_valuation_metadata = any(
        key in portfolio
        for key in (
            "valuation_status",
            "status",
            "valuation_lanes",
            "valuation_snapshot_id",
            "fact_authority",
        )
    )
    if (
        has_valuation_metadata or bound_val_id is not None or bound_ledger is not None
    ) and not is_asset_class_valuation_healthy(portfolio, "stock"):
        blockers.append("promoted_strategy_scan_current_portfolio_changed")
        return
    if bound_ledger is not None and portfolio.get("ledger_fingerprint") is not None:
        current_held_symbol_fingerprint = "sha256:" + content_fingerprint(held_symbols)
        if (
            portfolio.get("ledger_fingerprint") != bound_ledger
            or int(portfolio.get("ledger_cutoff_id") or 0)
            != int(bound_binding.get("ledger_cutoff_id") or 0)
            or bound_binding.get("held_symbol_fingerprint")
            != current_held_symbol_fingerprint
            or bound_binding.get("available_cash") != portfolio.get("cash")
            or str(bound_binding.get("cash_buffer_ratio") or "") != str(reserve_ratio)
        ):
            blockers.append("promoted_strategy_scan_current_portfolio_changed")
        return
    if bound_binding != current_portfolio_binding:
        blockers.append("promoted_strategy_scan_current_portfolio_changed")


def _build_frozen_replay_portfolio(
    *,
    db: Any,
    config: Any = None,
    portfolio: Mapping[str, Any],
    bound_binding: Mapping[str, Any],
    bound_snap: Mapping[str, Any] | None,
    bound_val_id: str | None,
    blockers: list[str],
) -> tuple[dict[str, Any], float]:
    frozen_portfolio: dict[str, Any] | None = None
    evaluation_equity: float | None = None
    if (
        bound_val_id
        and bound_snap is not None
        and bound_binding.get("ledger_fingerprint") is not None
    ):
        try:
            replayed = portfolio_stock_valuation_from_snapshot(
                db,
                bound_snap,
                config=config,
            )
            evaluation_equity = float(replayed["evaluation_equity"])
            frozen_position_values = {
                symbol: float(value)
                for symbol, value in replayed["stock_position_market_values"].items()
            }
            frozen_portfolio = {
                **portfolio,
                "valuation_snapshot_id": bound_val_id,
                "valuation_status": bound_snap.get("status", "complete"),
                "valuation_lanes": list(
                    bound_snap.get("valuation_lanes")
                    or portfolio.get("valuation_lanes")
                    or []
                ),
                "fact_authority": "persisted_valuation_snapshot",
                "total_equity": evaluation_equity,
                "stock_equity": float(replayed["stock_equity"]),
                "cash": float(replayed["cash"]),
                "stock_position_market_values": frozen_position_values,
                "stock_symbols": list(replayed["stock_symbols"]),
            }
        except Exception:
            frozen_portfolio = None
            evaluation_equity = None
            blockers.append("promoted_strategy_scan_current_portfolio_changed")
    if frozen_portfolio is None or evaluation_equity is None:
        bound_equity = bound_binding.get("bound_equity")
        evaluation_equity = (
            float(bound_equity)
            if isinstance(bound_equity, (int, float)) and bound_equity > 0
            else (
                float(portfolio["total_equity"])
                if isinstance(portfolio.get("total_equity"), (int, float))
                and portfolio["total_equity"] > 0
                else 100_000.0
            )
        )
        frozen_portfolio = {
            **portfolio,
            "total_equity": evaluation_equity,
            "stock_symbols": portfolio_stock_symbols(portfolio, []),
        }
    return frozen_portfolio, evaluation_equity


def portfolio_stock_symbols(
    portfolio_summary: Mapping[str, Any],
    blockers: list[str],
) -> list[str]:
    """Keep only holdings with persisted stock identity for scan evaluation."""
    symbols = sorted(
        {
            str(symbol)
            for symbol in portfolio_summary.get("symbols") or []
            if str(symbol)
        }
    )
    instrument_types = portfolio_summary.get("instrument_types")
    if not isinstance(instrument_types, Mapping):
        if symbols:
            blockers.append("portfolio_instrument_type_evidence_missing")
        return []
    stocks: list[str] = []
    for symbol in symbols:
        try:
            instrument_type = InstrumentType.from_persisted(
                instrument_types.get(symbol)
            )
        except ValueError:
            blockers.append(f"portfolio_instrument_type_unresolved:{symbol}")
            continue
        if instrument_type is InstrumentType.STOCK:
            stocks.append(symbol)
    return stocks


def current_scan_input_blockers(
    *,
    db: Any,
    config: Any,
    data_store: Any,
    policy: MarketUniversePolicy,
    scan: Mapping[str, Any],
    portfolio_summary: Mapping[str, Any],
    portfolio_reader: Callable[[Mapping[str, Any]], tuple[dict[str, Any], list[str]]],
    promoted_reader: Callable[[str], tuple[list[dict[str, Any]], list[str]]],
    safety_reader: Callable[[], dict[str, Any]],
    current_time: datetime | None = None,
    evaluation_cache: dict[tuple[Any, ...], Any] | None = None,
) -> list[str]:
    """Reopen every mutable input before a persisted scan is consumed."""

    decision_date = str(scan.get("decision_date") or "")
    market_date = str(scan.get("market_date") or "")
    blockers: list[str] = []
    if not decision_date or not market_date:
        return ["promoted_strategy_scan_current_identity_missing"]

    try:
        current_market_date = prior_verified_trading_date(db, decision_date)
    except Exception:
        current_market_date = None
        blockers.append("promoted_strategy_scan_current_calendar_replay_failed")
    if current_market_date != market_date:
        blockers.append("promoted_strategy_scan_market_date_changed")

    try:
        portfolio, portfolio_blockers = portfolio_reader(portfolio_summary)
    except Exception:
        portfolio = {
            "valuation_snapshot_id": "",
            "valuation_status": "missing",
            "total_equity": 0.0,
            "symbols": [],
            "stock_symbols": [],
        }
        portfolio_blockers = ["portfolio_current_evidence_unavailable"]
    if portfolio_blockers:
        blockers.append("promoted_strategy_scan_current_portfolio_blocked")

    try:
        promoted, strategy_blockers = promoted_reader(decision_date)
    except Exception:
        promoted = []
        strategy_blockers = ["promoted_strategy_current_evidence_unavailable"]
    if strategy_blockers:
        blockers.append("promoted_strategy_scan_current_strategy_gate_blocked")
    stored_bindings = [
        dict(item)
        for item in scan.get("strategy_bindings") or []
        if isinstance(item, Mapping)
    ]
    stored_by_id = {
        str(item.get("strategy_id") or ""): item for item in stored_bindings
    }
    current_by_id = {str(item.get("strategy_id") or ""): item for item in promoted}
    if len(stored_by_id) != len(stored_bindings) or set(stored_by_id) != set(
        current_by_id
    ):
        blockers.append("promoted_strategy_scan_active_strategy_set_changed")
    else:
        for strategy_id, current in current_by_id.items():
            stored = stored_by_id[strategy_id]
            if any(
                stored.get(key) != current.get(key)
                for key in (
                    "strategy_artifact_fingerprint",
                    "order_generation_gate_fingerprint",
                    "qualification_fingerprint",
                )
            ):
                blockers.append(
                    "promoted_strategy_scan_current_strategy_binding_changed"
                )
                break

    try:
        safety_gate = safety_reader()
    except Exception:
        safety_gate = {"status": "unavailable"}
    if automation_safety_blockers(safety_gate):
        blockers.append("promoted_strategy_scan_current_safety_gate_blocked")
    current_safety_fingerprint = "sha256:" + content_fingerprint(safety_gate)
    if scan.get("safety_gate_fingerprint") != current_safety_fingerprint:
        blockers.append("promoted_strategy_scan_safety_gate_changed")

    current_policy_fingerprint = promoted_scan_evaluation_policy_fingerprint(policy)
    if scan.get("evaluation_policy_fingerprint") != current_policy_fingerprint:
        blockers.append("promoted_strategy_scan_evaluation_policy_changed")

    start_date = promoted_history_start(promoted, config, market_date)
    snapshot: dict[str, Any] = {}
    receipts: list[dict[str, Any]] = []
    frames: dict[str, Any] = {}
    trading_dates: list[str] = []
    market_replay_ready = True
    try:
        snapshot = dict(
            data_store.get_market_universe_snapshot(trade_date=market_date) or {}
        )
        verified_snapshot = require_complete_market_universe_snapshot(
            snapshot,
            policy=policy,
            expected_trade_date=market_date,
        )
        trading_dates = verified_trading_dates(
            db,
            start_date=start_date,
            end_date=market_date,
        )
        if not trading_dates or trading_dates[-1] != market_date:
            raise ValueError("verified_market_history_window_incomplete")
        receipts = resolve_daily_bar_receipts(
            data_store=data_store,
            start_date=start_date,
            end_date=market_date,
            config=config,
            snapshot=snapshot,
        )
        members = [
            str(item.get("symbol") or "")
            for item in verified_snapshot["members"]
            if isinstance(item, Mapping)
        ]
        frames = data_store.load_market_bar_windows(
            symbols=members,
            start_date=start_date,
            end_date=market_date,
            receipts=receipts,
        )
    except Exception:
        market_replay_ready = False
        blockers.append("promoted_strategy_scan_current_market_replay_failed")
    if snapshot.get("snapshot_id") != scan.get("market_universe_snapshot_id"):
        blockers.append("promoted_strategy_scan_market_universe_changed")
    receipt_fingerprints = [item.get("receipt_fingerprint") for item in receipts]
    if receipt_fingerprints != list(scan.get("receipt_fingerprints") or []):
        blockers.append("promoted_strategy_scan_market_receipts_changed")

    held_symbols = list(portfolio["stock_symbols"])
    reserve_ratio = cash_buffer_ratio(config)
    current_portfolio_binding = portfolio_scan_binding(
        portfolio,
        held_symbols=held_symbols,
        reserve_ratio=reserve_ratio,
    )
    bound_binding = dict(scan.get("portfolio_binding") or {})
    bound_ledger = bound_binding.get("ledger_fingerprint")
    bound_val_id = bound_binding.get("valuation_snapshot_id")

    bound_snap = _verify_bound_valuation(
        db=db,
        bound_val_id=bound_val_id,
        bound_ledger=bound_ledger,
        bound_cutoff=bound_binding.get("ledger_cutoff_id"),
        blockers=blockers,
    )
    _validate_current_portfolio_binding(
        portfolio=portfolio,
        bound_binding=bound_binding,
        current_portfolio_binding=current_portfolio_binding,
        held_symbols=held_symbols,
        reserve_ratio=reserve_ratio,
        bound_val_id=bound_val_id,
        bound_ledger=bound_ledger,
        blockers=blockers,
    )

    if market_replay_ready and not strategy_blockers and promoted:
        frozen_portfolio, evaluation_equity = _build_frozen_replay_portfolio(
            db=db,
            config=config,
            portfolio=portfolio,
            bound_binding=bound_binding,
            bound_snap=bound_snap,
            bound_val_id=bound_val_id,
            blockers=blockers,
        )
        exact_frames, cross_sections, bindings, exact_blockers = (
            load_exact_formula_market_inputs(
                db,
                promoted,
                market_date=market_date,
                decision_at=current_time or datetime.now(timezone.utc),
                saved_bindings={
                    key: value["formula_dataset_binding"]
                    for key, value in stored_by_id.items()
                    if "formula_dataset_binding" in value
                },
            )
        )
        blockers.extend(exact_blockers)
        decision_at = (
            next(iter(cross_sections.values())).as_of if cross_sections else None
        )
        cache_key = market_evaluation_cache_key(
            market_date=market_date,
            snapshot_id=str(snapshot.get("snapshot_id") or ""),
            receipt_fingerprints=[item.get("receipt_fingerprint") for item in receipts],
            trading_dates=trading_dates,
            start_date=start_date,
            total_equity=evaluation_equity,
            held_symbols=held_symbols,
            policy_fingerprint=promoted_scan_evaluation_policy_fingerprint(policy),
            promoted_strategies=promoted,
            formula_bindings=bindings,
        )
        if evaluation_cache is not None and cache_key in evaluation_cache:
            cached_truths, cached_signals, cached_blockers, _ = evaluation_cache[
                cache_key
            ]
            truths = copy.deepcopy(cached_truths)
            raw_signals = copy.deepcopy(cached_signals)
            truth_blockers = list(cached_blockers)
        else:
            truths, raw_signals, truth_blockers = evaluate_promoted_strategy_market(
                promoted=promoted,
                market_date=market_date,
                snapshot=snapshot,
                frames=frames,
                receipts=receipts,
                trading_dates=trading_dates,
                start_date=start_date,
                total_equity=evaluation_equity,
                held_stock_symbols=held_symbols,
                policy=policy,
                decision_at=decision_at,
                cross_sections=cross_sections,
                formula_frames=exact_frames,
            )
            if evaluation_cache is not None:
                evaluation_cache[cache_key] = (
                    copy.deepcopy(truths),
                    copy.deepcopy(raw_signals),
                    list(truth_blockers),
                    copy.deepcopy(bindings),
                )
        relevant_truth_blockers = active_action_blockers(
            truth_blockers, scan.get("selected_signals") or []
        )
        blockers.extend(
            f"promoted_strategy_scan_current_truth:{item}"
            for item in relevant_truth_blockers
        )
        if not relevant_truth_blockers:
            if any(
                truths.get(strategy_id, {}).get("evidence_fingerprint")
                != stored_by_id.get(strategy_id, {}).get("universe_truth_fingerprint")
                for strategy_id in current_by_id
            ):
                blockers.append("promoted_strategy_scan_current_universe_truth_changed")
            account_signals, account_blocked_buys = account_eligible_signals(
                raw_signals,
                config=config,
                decision_date=decision_date,
                portfolio=frozen_portfolio,
                policy=policy,
                cash_buffer_ratio=reserve_ratio,
                db=db,
            )
            selected_signals, signal_conflict_blockers = aggregate_ranked_signals(
                account_signals,
                allocation_slots=policy.allocation_slots,
            )
            blockers.extend(signal_conflict_blockers)
            current_signal_fingerprint = "sha256:" + content_fingerprint(
                {
                    "decision_date": decision_date,
                    "market_date": market_date,
                    "raw_signals": raw_signals,
                    "account_blocked_buys": account_blocked_buys,
                    "signals": selected_signals,
                }
            )
            if scan.get("signal_selection_fingerprint") != current_signal_fingerprint:
                blockers.append(
                    "promoted_strategy_scan_current_signal_selection_changed"
                )

            current_permissions = portfolio.get("board_buy_permissions")
            current_permissions_dict = (
                dict(current_permissions)
                if isinstance(current_permissions, Mapping)
                else {}
            )
            live_cash = _nonnegative_decimal(portfolio.get("cash"))
            live_equity = _nonnegative_decimal(
                portfolio.get("total_equity") or portfolio.get("stock_equity")
            )
            live_reserve = (
                live_equity * reserve_ratio if live_equity is not None else Decimal(0)
            )
            live_available = (
                max(Decimal(0), live_cash - live_reserve)
                if live_cash is not None
                else Decimal(0)
            )
            live_quotes_by_symbol: dict[str, Decimal] = {}
            if bound_ledger is not None and hasattr(db, "get_latest_quotes_sync"):
                for q in db.get_latest_quotes_sync():
                    sym = str(q.get("symbol") or "")
                    q_price = _nonnegative_decimal(q.get("price"))
                    if sym and q_price is not None and q_price > 0:
                        live_quotes_by_symbol[sym] = q_price
            buy_rows: list[Mapping[str, Any]] = []
            for row in selected_signals:
                if row.get("direction") == "buy":
                    blocker = board_buy_blocker(
                        row["symbol"], current_permissions_dict, decision_date
                    )
                    if blocker:
                        blockers.append(
                            "promoted_strategy_scan_current_board_permission_changed:"
                            + blocker
                        )
                    buy_rows.append(row)
                elif row.get("direction") == "sell":
                    if str(row["symbol"]) not in held_symbols:
                        blockers.append("promoted_strategy_scan_holding_changed")
            min_required_buy_cash = buy_candidates_cash_requirement(
                buy_rows,
                config=config,
                policy=policy,
                live_quotes_by_symbol=live_quotes_by_symbol,
            )
            if min_required_buy_cash > live_available:
                blockers.append("promoted_strategy_scan_current_cash_insufficient")
    return list(dict.fromkeys(blockers))


__all__ = ["current_scan_input_blockers"]
