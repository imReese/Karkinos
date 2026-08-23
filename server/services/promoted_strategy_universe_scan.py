"""Deterministic full-market scan for human-promoted paper/shadow strategies."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from data.store import DataStore
from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.formula_dsl import (
    evaluate_formula,
    validate_formula_ast,
)
from server.bootstrap import resolve_data_dir
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactStore,
)
from server.services.market_universe_automation import verified_trading_dates
from server.services.market_universe_truth import (
    MarketUniversePolicy,
    build_full_market_universe_truth,
)
from server.services.recommendation_flow import build_recommendation_cycle
from server.services.strategy_promotion_pipeline import (
    AI_SHADOW_STRATEGY_PREFIX,
    resolve_strategy_order_generation_gate,
)

PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION = (
    "karkinos.promoted_strategy_universe_scan.v1"
)
PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE = "promoted_strategy_universe_scan"
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_DECISION_START = time(9, 35)
_DECISION_END = time(9, 45)
_WRITE_LOCK = threading.Lock()

StrategyGateResolver = Callable[..., tuple[dict[str, Any], list[str]]]
StrategyLoader = Callable[..., dict[str, Any]]
SafetyGateReader = Callable[[], Mapping[str, Any]]


class PromotedStrategyUniverseScanService:
    """Create recommendation tasks, never orders, from frozen promoted formulas."""

    def __init__(
        self,
        *,
        db: Any,
        config: Any,
        data_store: DataStore | None = None,
        policy: MarketUniversePolicy | None = None,
        strategy_gate_resolver: StrategyGateResolver | None = None,
        strategy_loader: StrategyLoader | None = None,
        safety_gate_reader: SafetyGateReader | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._config = config
        self._data_store = data_store or DataStore(resolve_data_dir())
        self._policy = policy or MarketUniversePolicy()
        self._strategy_gate_resolver = (
            strategy_gate_resolver or resolve_strategy_order_generation_gate
        )
        self._strategy_loader = strategy_loader or self._load_strategy
        self._safety_gate_reader = safety_gate_reader
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run_once(
        self,
        *,
        decision_date: str,
        portfolio_summary: Mapping[str, Any],
        persist_actions: bool = True,
        expected_signal_selection_fingerprint: str | None = None,
        additional_blockers: list[str] | None = None,
    ) -> dict[str, Any]:
        """Scan once for the exact decision date using only prior closed bars."""

        started_at = self._clock()
        safety_gate = self._read_safety_gate()
        blockers = _decision_window_blockers(
            db=self._db,
            decision_date=decision_date,
            now=started_at,
        )
        blockers.extend(_automation_safety_blockers(safety_gate))
        blockers.extend(str(item) for item in additional_blockers or [] if str(item))
        promoted, strategy_blockers = self._resolve_promoted_strategies(decision_date)
        blockers.extend(strategy_blockers)
        market_date = _prior_verified_trading_date(self._db, decision_date)
        if market_date is None:
            blockers.append("prior_verified_market_date_unavailable")

        total_equity = _positive_float(portfolio_summary.get("total_equity"))
        if total_equity is None:
            blockers.append("portfolio_total_equity_invalid")
            total_equity = 0.0
        portfolio_symbols = sorted(
            {
                str(symbol)
                for symbol in portfolio_summary.get("symbols") or []
                if str(symbol)
            }
        )
        held_symbols: list[str] = []
        valuation_snapshot_id = str(
            portfolio_summary.get("valuation_snapshot_id") or ""
        )
        if not valuation_snapshot_id:
            blockers.append("valuation_snapshot_identity_missing")

        provider_name = str(getattr(self._config, "data_source", "") or "")
        snapshot: dict[str, Any] = {}
        receipts: list[dict[str, Any]] = []
        frames: dict[str, pd.DataFrame] = {}
        trading_dates: list[str] = []
        history_start = None
        if market_date is not None and promoted:
            snapshot_value = self._data_store.get_market_universe_snapshot(
                trade_date=market_date
            )
            snapshot = dict(snapshot_value or {})
            if not snapshot:
                blockers.append("full_market_universe_snapshot_missing")
            history_start = _history_start(self._config, market_date)
            trading_dates = verified_trading_dates(
                self._db,
                start_date=history_start,
                end_date=market_date,
            )
            if not trading_dates:
                blockers.append("verified_market_history_window_incomplete")
            try:
                receipts = [
                    dict(item)
                    for item in self._data_store.list_market_daily_ingestion_receipts(
                        start_date=history_start,
                        end_date=market_date,
                        provider_name=provider_name,
                    )
                ]
            except (OSError, ValueError):
                blockers.append("full_market_daily_receipt_replay_failed")
            if snapshot:
                member_symbols = [
                    str(member.get("symbol") or "")
                    for member in snapshot.get("members") or []
                    if isinstance(member, Mapping)
                ]
                member_set = set(member_symbols)
                held_symbols = sorted(set(portfolio_symbols) & member_set)
                frames = self._data_store.load_market_bar_windows(
                    symbols=member_symbols,
                    start_date=history_start,
                    end_date=market_date,
                )

        truth_by_strategy: dict[str, dict[str, Any]] = {}
        raw_signals: list[dict[str, Any]] = []
        if not blockers and market_date is not None and history_start is not None:
            for promoted_strategy in promoted:
                strategy_id = str(promoted_strategy["strategy_id"])
                strategy = dict(promoted_strategy["strategy"])
                formula_ast = strategy.get("formula_ast")
                selected_universe = tuple(
                    str(symbol) for symbol in strategy.get("selected_universe") or []
                )
                try:
                    validate_formula_ast(
                        formula_ast,
                        universe_size=len(selected_universe),
                    )
                    target_weight = 1.0 / self._policy.allocation_slots
                    minimum_rows = max(
                        self._policy.minimum_history_rows,
                        _formula_history_rows(formula_ast),
                    )
                    truth = build_full_market_universe_truth(
                        snapshot=snapshot,
                        frames=frames,
                        receipts=receipts,
                        required_trading_dates=trading_dates,
                        start_date=history_start,
                        end_date=market_date,
                        initial_cash=total_equity,
                        target_weight=target_weight,
                        held_symbols=held_symbols,
                        minimum_history_rows=minimum_rows,
                        policy=self._policy,
                    )
                except Exception as exc:
                    blockers.append(
                        f"strategy_full_market_truth_failed:{strategy_id}:"
                        f"{type(exc).__name__}:{exc}"
                    )
                    continue
                truth_by_strategy[strategy_id] = truth
                if truth.get("status") != "complete":
                    blockers.extend(
                        f"strategy_full_market_truth:{strategy_id}:{item}"
                        for item in truth.get("blockers") or []
                    )
                    continue
                raw_signals.extend(
                    _evaluate_strategy_signals(
                        strategy_id=strategy_id,
                        formula_ast=formula_ast,
                        universe_size=len(selected_universe),
                        target_weight=target_weight,
                        frames=frames,
                        eligible_symbols=list(truth["eligible_symbols"]),
                        maintenance_symbols=list(truth["maintenance_symbols"]),
                        held_symbols=set(held_symbols),
                        market_date=market_date,
                    )
                )

        blockers = list(dict.fromkeys(blockers))
        selected_signals = _select_ranked_signals(
            raw_signals,
            allocation_slots=self._policy.allocation_slots,
        )
        signal_selection_fingerprint = "sha256:" + content_fingerprint(
            {
                "decision_date": decision_date,
                "market_date": market_date,
                "signals": selected_signals,
            }
        )
        if (
            expected_signal_selection_fingerprint is not None
            and signal_selection_fingerprint != expected_signal_selection_fingerprint
        ):
            blockers.append("signal_selection_changed_after_quote_freeze")
        blockers = list(dict.fromkeys(blockers))
        input_core = {
            "schema_version": PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION,
            "decision_date": decision_date,
            "market_date": market_date,
            "market_universe_snapshot_id": snapshot.get("snapshot_id"),
            "receipt_fingerprints": [
                item.get("receipt_fingerprint") for item in receipts
            ],
            "strategy_bindings": [
                {
                    "strategy_id": item["strategy_id"],
                    "strategy_artifact_fingerprint": item.get(
                        "strategy_artifact_fingerprint"
                    ),
                    "order_generation_gate_fingerprint": item.get(
                        "order_generation_gate_fingerprint"
                    ),
                    "universe_truth_fingerprint": truth_by_strategy.get(
                        str(item["strategy_id"]), {}
                    ).get("evidence_fingerprint"),
                }
                for item in promoted
            ],
            "portfolio_binding": {
                "valuation_snapshot_id": valuation_snapshot_id or None,
                "held_symbol_fingerprint": "sha256:"
                + content_fingerprint(held_symbols),
                "held_stock_count": len(held_symbols),
                "capital_constraint_fingerprint": "sha256:"
                + content_fingerprint(
                    {
                        "valuation_snapshot_id": valuation_snapshot_id,
                        "total_equity": total_equity,
                    }
                ),
            },
            "signal_selection_policy": (
                "exits_first_then_20d_median_amount_desc_then_symbol_asc"
            ),
            "signal_selection_fingerprint": signal_selection_fingerprint,
            "safety_gate_fingerprint": "sha256:" + content_fingerprint(safety_gate),
        }
        input_fingerprint = "sha256:" + content_fingerprint(input_core)
        run_id = (
            f"automation:promoted-strategy-universe-scan:{decision_date}:"
            f"{input_fingerprint.removeprefix('sha256:')[:16]}"
        )
        if persist_actions:
            existing = self._db.get_automation_run_sync(run_id)
            if existing and str(existing.get("status") or "") in {
                "completed",
                "completed_no_signal",
            }:
                payload = _json_object(existing.get("payload_json"))
                return {**payload, "run_id": run_id, "reused": True}

        action_tasks: list[dict[str, Any]] = []
        if persist_actions:
            status = (
                "blocked"
                if blockers
                else ("completed" if selected_signals else "completed_no_signal")
            )
        else:
            status = (
                "blocked"
                if blockers
                else ("prepared" if selected_signals else "prepared_no_signal")
            )
        if persist_actions and not blockers and selected_signals:
            with _WRITE_LOCK:
                action_tasks = self._persist_signals(
                    decision_date=decision_date,
                    signals=selected_signals,
                )
        payload_core = {
            **input_core,
            "status": status,
            "input_fingerprint": input_fingerprint,
            "blockers": blockers,
            "raw_signal_count": len(raw_signals),
            "selected_signal_count": len(selected_signals),
            "selected_signals": selected_signals,
            "action_tasks": action_tasks,
            "full_market_truths": [
                _truth_projection(strategy_id, truth)
                for strategy_id, truth in sorted(truth_by_strategy.items())
            ],
            "normal_no_signal": status == "completed_no_signal",
            "preview_only": not persist_actions,
            "manual_confirmation_required": True,
            "creates_oms_order": False,
            "submits_broker_order": False,
            "mutates_account_ledger": False,
            "changes_strategy_promotion": False,
            "changes_capital_authority": False,
            "finished_at": self._clock().isoformat(),
        }
        output_fingerprint = "sha256:" + content_fingerprint(payload_core)
        payload = {**payload_core, "output_fingerprint": output_fingerprint}
        if persist_actions:
            self._db.upsert_automation_run_sync(
                {
                    "run_id": run_id,
                    "run_type": PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE,
                    "run_date": decision_date,
                    "status": status,
                    "execution_mode": "paper_shadow_recommendation_only",
                    "started_at": started_at.isoformat(),
                    "finished_at": payload["finished_at"],
                    "source_ref": snapshot.get("snapshot_id"),
                    "payload": payload,
                }
            )
        return {**payload, "run_id": run_id, "reused": False}

    def _read_safety_gate(self) -> dict[str, Any]:
        if self._safety_gate_reader is None:
            return {"status": "unavailable"}
        try:
            value = self._safety_gate_reader()
        except Exception as exc:
            return {"status": "unavailable", "error_type": type(exc).__name__}
        if not isinstance(value, Mapping):
            return {"status": "unavailable"}
        return {
            "default_execution_mode": value.get("default_execution_mode"),
            "manual_confirmation_required": value.get("manual_confirmation_required"),
            "broker_submission_enabled": value.get("broker_submission_enabled"),
            "kill_switch_enabled": value.get("kill_switch_enabled"),
            "kill_switch_reason": value.get("kill_switch_reason"),
        }

    def _resolve_promoted_strategies(
        self,
        decision_date: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        reader = getattr(self._db, "list_strategy_promotion_states_sync", None)
        rows = reader() if callable(reader) else []
        active = sorted(
            (
                dict(row)
                for row in rows
                if str(row.get("strategy_id") or "").startswith(
                    AI_SHADOW_STRATEGY_PREFIX
                )
                and row.get("stage") == "paper_shadow"
            ),
            key=lambda row: str(row.get("strategy_id") or ""),
        )
        if not active:
            return [], ["promoted_daily_candidate_strategy_missing"]
        resolved: list[dict[str, Any]] = []
        blockers: list[str] = []
        for row in active:
            strategy_id = str(row["strategy_id"])
            gate, gate_blockers = self._strategy_gate_resolver(
                self._db,
                strategy_id,
                as_of_date=decision_date,
            )
            if gate_blockers or gate.get("status") != "pass":
                blockers.extend(
                    f"promoted_strategy_gate:{strategy_id}:{item}"
                    for item in gate_blockers or ["not_pass"]
                )
                continue
            promotion = dict(gate.get("promotion") or {})
            artifact = dict(promotion.get("daily_strategy_artifact_binding") or {})
            candidate_id = str(artifact.get("winner_candidate_id") or "")
            run_id = str(artifact.get("run_id") or "")
            try:
                loaded = self._strategy_loader(
                    candidate_id=candidate_id,
                    run_id=run_id,
                )
            except Exception as exc:
                blockers.append(
                    f"promoted_strategy_snapshot:{strategy_id}:"
                    f"{type(exc).__name__}:{exc}"
                )
                continue
            if (
                loaded.get("candidate_id") != candidate_id
                or loaded.get("run_id") != run_id
                or loaded.get("strategy_artifact_fingerprint")
                != dict(artifact.get("operating_constraints") or {}).get(
                    "strategy_artifact_fingerprint"
                )
            ):
                blockers.append(f"promoted_strategy_snapshot:{strategy_id}:drift")
                continue
            resolved.append(
                {
                    "strategy_id": strategy_id,
                    "strategy": dict(loaded.get("strategy") or {}),
                    "strategy_artifact_fingerprint": loaded.get(
                        "strategy_artifact_fingerprint"
                    ),
                    "order_generation_gate_fingerprint": "sha256:"
                    + content_fingerprint(gate),
                }
            )
        return resolved, blockers

    def _load_strategy(self, *, candidate_id: str, run_id: str) -> dict[str, Any]:
        database_path = Path(getattr(self._db, "_path"))
        store = DailyStrategyArtifactStore(
            database_path,
            database_path.parent / "strategy-research-backups",
        )
        return store.load_verified_winner_strategy(
            candidate_id=candidate_id,
            run_id=run_id,
        )

    def _persist_signals(
        self,
        *,
        decision_date: str,
        signals: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        base = datetime.combine(
            date.fromisoformat(decision_date),
            _DECISION_START,
            tzinfo=_SHANGHAI_TZ,
        )
        persisted: list[dict[str, Any]] = []
        for index, signal in enumerate(signals):
            timestamp = (
                base + timedelta(microseconds=len(signals) - index)
            ).isoformat()
            signal_id = _find_signal_id(
                self._db,
                timestamp=timestamp,
                strategy_id=str(signal["strategy_id"]),
                symbol=str(signal["symbol"]),
                direction=str(signal["direction"]),
            )
            if signal_id is None:
                signal_id = self._db.save_signal_sync(
                    timestamp=timestamp,
                    strategy_id=str(signal["strategy_id"]),
                    symbol=str(signal["symbol"]),
                    direction=str(signal["direction"]),
                    target_weight=float(signal["target_weight"]),
                    price=float(signal["frozen_close"]),
                    asset_class="stock",
                )
            cycle = build_recommendation_cycle(
                signals=[
                    {
                        "id": signal_id,
                        "timestamp": timestamp,
                        "strategy_id": signal["strategy_id"],
                        "symbol": signal["symbol"],
                        "direction": signal["direction"],
                        "target_weight": signal["target_weight"],
                        "price": signal["frozen_close"],
                        "asset_class": "stock",
                    }
                ],
                available_cash=0,
                existing_positions={},
            )
            task = cycle.tasks[0]
            self._db.upsert_action_task_sync(
                source_signal_id=task.source_signal_id,
                symbol=task.symbol,
                title=task.title,
                detail=task.detail,
                direction=task.direction,
                urgency="high" if task.direction == "sell" else "medium",
                target_weight=task.target_weight,
                price=task.price,
                strategy_id=task.strategy_id,
                timestamp=task.timestamp,
                asset_class=task.asset_class,
            )
            persisted.append(
                {
                    "source_signal_id": signal_id,
                    "symbol": task.symbol,
                    "direction": task.direction,
                    "timestamp": timestamp,
                }
            )
        return persisted


def _evaluate_strategy_signals(
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


def _select_ranked_signals(
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


def _decision_window_blockers(
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
    shanghai = current.astimezone(_SHANGHAI_TZ)
    blockers: list[str] = []
    if shanghai.date() != parsed:
        blockers.append("strategy_scan_not_current_decision_date")
    if not (_DECISION_START <= shanghai.time().replace(tzinfo=None) < _DECISION_END):
        blockers.append("strategy_scan_outside_reviewed_decision_window")
    dates = verified_trading_dates(
        db,
        start_date=decision_date,
        end_date=decision_date,
    )
    if dates != [decision_date]:
        blockers.append("strategy_scan_decision_date_not_verified_trading_day")
    return blockers


def _prior_verified_trading_date(db: Any, decision_date: str) -> str | None:
    parsed = date.fromisoformat(decision_date)
    start = (parsed - timedelta(days=45)).isoformat()
    dates = verified_trading_dates(
        db,
        start_date=start,
        end_date=(parsed - timedelta(days=1)).isoformat(),
    )
    return dates[-1] if dates else None


def _automation_safety_blockers(status: Mapping[str, Any]) -> list[str]:
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


def _history_start(config: Any, market_date: str) -> str:
    end = date.fromisoformat(market_date)
    start = end - timedelta(days=540)
    configured = str(getattr(config, "start_date", "") or "").strip()
    if configured:
        try:
            start = min(start, date.fromisoformat(configured))
        except ValueError:
            pass
    return start.isoformat()


def _formula_history_rows(formula_ast: Mapping[str, Any]) -> int:
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


def _find_signal_id(
    db: Any,
    *,
    timestamp: str,
    strategy_id: str,
    symbol: str,
    direction: str,
) -> int | None:
    path = getattr(db, "_path", None)
    if path is None:
        return None
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            """
            SELECT id FROM signals
            WHERE timestamp = ? AND strategy_id = ? AND symbol = ? AND direction = ?
            ORDER BY id LIMIT 1
            """,
            (timestamp, strategy_id, symbol, direction),
        ).fetchone()
    return int(row[0]) if row is not None else None


def _truth_projection(strategy_id: str, truth: Mapping[str, Any]) -> dict[str, Any]:
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


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None
