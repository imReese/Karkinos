"""Read-only freshness validation for persisted promoted-strategy scans."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from server.ai_runtime.contracts import content_fingerprint
from server.services.market_universe_automation import verified_trading_dates
from server.services.market_universe_truth import (
    MarketUniversePolicy,
    require_complete_market_universe_snapshot,
)
from server.services.promoted_strategy_universe_scan_support import (
    aggregate_ranked_signals,
    automation_safety_blockers,
    evaluate_promoted_strategy_market,
    history_start,
    prior_verified_trading_date,
    promoted_scan_evaluation_policy_fingerprint,
)


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

    start_date = history_start(config, market_date)
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
        receipts = [
            dict(item)
            for item in data_store.list_market_daily_ingestion_receipts(
                start_date=start_date,
                end_date=market_date,
                provider_name=str(getattr(config, "data_source", "") or ""),
            )
        ]
        members = [
            str(item.get("symbol") or "")
            for item in verified_snapshot["members"]
            if isinstance(item, Mapping)
        ]
        frames = data_store.load_market_bar_windows(
            symbols=members,
            start_date=start_date,
            end_date=market_date,
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
    current_portfolio_binding = {
        "valuation_snapshot_id": portfolio["valuation_snapshot_id"] or None,
        "valuation_status": portfolio["valuation_status"],
        "held_symbol_fingerprint": "sha256:" + content_fingerprint(held_symbols),
        "held_stock_count": len(held_symbols),
        "capital_constraint_fingerprint": "sha256:"
        + content_fingerprint(
            {
                "valuation_snapshot_id": portfolio["valuation_snapshot_id"],
                "valuation_status": portfolio["valuation_status"],
                "total_equity": portfolio["total_equity"],
            }
        ),
    }
    if dict(scan.get("portfolio_binding") or {}) != current_portfolio_binding:
        blockers.append("promoted_strategy_scan_current_portfolio_changed")

    if market_replay_ready and not strategy_blockers and promoted:
        truths, raw_signals, truth_blockers = evaluate_promoted_strategy_market(
            promoted=promoted,
            market_date=market_date,
            snapshot=snapshot,
            frames=frames,
            receipts=receipts,
            trading_dates=trading_dates,
            start_date=start_date,
            total_equity=portfolio["total_equity"],
            held_stock_symbols=held_symbols,
            policy=policy,
        )
        blockers.extend(
            f"promoted_strategy_scan_current_truth:{item}" for item in truth_blockers
        )
        if not truth_blockers:
            if any(
                truths.get(strategy_id, {}).get("evidence_fingerprint")
                != stored_by_id.get(strategy_id, {}).get("universe_truth_fingerprint")
                for strategy_id in current_by_id
            ):
                blockers.append("promoted_strategy_scan_current_universe_truth_changed")
            selected_signals, signal_conflict_blockers = aggregate_ranked_signals(
                raw_signals,
                allocation_slots=policy.allocation_slots,
            )
            blockers.extend(signal_conflict_blockers)
            current_signal_fingerprint = "sha256:" + content_fingerprint(
                {
                    "decision_date": decision_date,
                    "market_date": market_date,
                    "signals": selected_signals,
                }
            )
            if scan.get("signal_selection_fingerprint") != current_signal_fingerprint:
                blockers.append(
                    "promoted_strategy_scan_current_signal_selection_changed"
                )
    return list(dict.fromkeys(blockers))


__all__ = ["current_scan_input_blockers"]
