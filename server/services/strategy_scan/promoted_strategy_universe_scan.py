"""Deterministic full-market scan for human-promoted paper/shadow strategies."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any

import pandas as pd

from data.dataset.reader import daily_bar_dataset_read_scope
from data.store import DataStore
from server.ai_runtime.contracts import content_fingerprint
from server.bootstrap import resolve_data_dir
from server.contracts.recommendation_publication import publication_source_blocker
from server.services.account.valuation_snapshot import is_asset_class_valuation_healthy
from server.services.ai_shadow.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactRejected,
    DailyStrategyArtifactStore,
)
from server.services.market.market_universe_automation import verified_trading_dates
from server.services.market.market_universe_truth import MarketUniversePolicy
from server.services.strategy_promotion_pipeline import (
    AI_SHADOW_STRATEGY_PREFIX,
    resolve_strategy_order_generation_gate,
)
from server.services.strategy_scan.promoted_strategy_universe_scan_persistence import (
    persist_recommendation_tasks,
)
from server.services.strategy_scan.promoted_strategy_universe_scan_support import (
    SIGNAL_SELECTION_POLICY,
    account_eligible_signals,
    active_action_blockers,
    aggregate_ranked_signals,
    automation_safety_blockers,
    board_buy_blocker,
    cash_buffer_ratio,
    decision_window_blockers,
    evaluate_promoted_strategy_market,
    history_start,
    json_object,
    policy_entry_signals,
    portfolio_scan_binding,
    positive_float,
    prior_verified_trading_date,
    promoted_history_start,
    promoted_scan_evaluation_policy_fingerprint,
    resolve_daily_bar_receipt_provider,
    resolve_daily_bar_receipts,
    truth_projection,
)
from server.services.strategy_scan.promoted_strategy_universe_scan_validation import (
    current_scan_input_blockers,
    portfolio_stock_symbols,
)

PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION = (
    "karkinos.promoted_strategy_universe_scan.v1"
)
PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE = "promoted_strategy_universe_scan"
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
        with daily_bar_dataset_read_scope(join_existing=True):
            return self._run_once(
                decision_date=decision_date,
                portfolio_summary=portfolio_summary,
                persist_actions=persist_actions,
                expected_signal_selection_fingerprint=expected_signal_selection_fingerprint,
                additional_blockers=additional_blockers,
            )

    def _run_once(
        self,
        *,
        decision_date: str,
        portfolio_summary: Mapping[str, Any],
        persist_actions: bool,
        expected_signal_selection_fingerprint: str | None,
        additional_blockers: list[str] | None,
    ) -> dict[str, Any]:
        started_at = self._clock()
        safety_gate = self._read_safety_gate()
        blockers = decision_window_blockers(
            db=self._db,
            decision_date=decision_date,
            now=started_at,
        )
        blockers.extend(automation_safety_blockers(safety_gate))
        blockers.extend(str(item) for item in additional_blockers or [] if str(item))
        promoted, strategy_blockers = self._resolve_promoted_strategies(decision_date)
        blockers.extend(strategy_blockers)
        market_date = prior_verified_trading_date(self._db, decision_date)
        if market_date is None:
            blockers.append("prior_verified_market_date_unavailable")
        portfolio, portfolio_blockers = self._portfolio_context(portfolio_summary)
        blockers.extend(portfolio_blockers)
        market, market_blockers = self._load_market_evidence(
            market_date=market_date,
            promoted=promoted,
            portfolio_stock_symbols=portfolio["stock_symbols"],
        )
        blockers.extend(market_blockers)
        fatal_evaluation_blockers = [
            item
            for item in blockers
            if item
            in {
                "strategy_scan_decision_date_invalid",
                "strategy_scan_decision_date_not_verified_trading_day",
                "prior_verified_market_date_unavailable",
                "full_market_universe_snapshot_missing",
                "verified_market_history_window_incomplete",
                "full_market_daily_receipt_replay_failed",
                "promoted_strategy_not_configured",
                "promoted_daily_candidate_strategy_missing",
                "portfolio_instrument_type_evidence_missing",
            }
            or item.startswith("strategy_gate_rejected:")
            or item.startswith("portfolio_instrument_type_unresolved:")
        ]
        if not promoted or market_date is None or fatal_evaluation_blockers:
            truths, raw_signals, truth_blockers = {}, [], []
        else:
            total_equity = portfolio["total_equity"]
            evaluation_equity = (
                total_equity
                if isinstance(total_equity, (int, float)) and total_equity > 0
                else 100_000.0
            )
            truths, raw_signals, truth_blockers = self._evaluate_promoted_strategies(
                promoted=promoted,
                market_date=market_date,
                market=market,
                total_equity=evaluation_equity,
            )
        blockers.extend(truth_blockers)
        return self._complete_run(
            decision_date=decision_date,
            started_at=started_at,
            safety_gate=safety_gate,
            promoted=promoted,
            market_date=market_date,
            portfolio=portfolio,
            market=market,
            truth_by_strategy=truths,
            raw_signals=raw_signals,
            blockers=blockers,
            persist_actions=persist_actions,
            expected_signal_selection_fingerprint=(
                expected_signal_selection_fingerprint
            ),
        )

    def current_input_blockers(
        self,
        *,
        scan: Mapping[str, Any],
        portfolio_summary: Mapping[str, Any],
    ) -> list[str]:
        """Reopen every mutable input before a persisted scan is consumed."""
        with daily_bar_dataset_read_scope(join_existing=True):
            return current_scan_input_blockers(
                db=self._db,
                config=self._config,
                data_store=self._data_store,
                policy=self._policy,
                scan=scan,
                portfolio_summary=portfolio_summary,
                portfolio_reader=self._portfolio_context,
                promoted_reader=self._resolve_promoted_strategies,
                safety_reader=self._read_safety_gate,
            )

    def _portfolio_context(
        self,
        portfolio_summary: Mapping[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        blockers: list[str] = []
        stock_equity = positive_float(portfolio_summary.get("stock_equity"))
        total_equity = positive_float(portfolio_summary.get("total_equity"))
        if total_equity is None:
            if stock_equity is not None:
                total_equity = stock_equity
            else:
                blockers.append("portfolio_total_equity_invalid")
                total_equity = 0.0
        valuation_status = (
            str(portfolio_summary.get("valuation_status") or "missing").strip().lower()
        )
        if not is_asset_class_valuation_healthy(portfolio_summary, "stock"):
            blockers.append("valuation_snapshot_not_complete")
        valuation_snapshot_id = str(
            portfolio_summary.get("valuation_snapshot_id") or ""
        )
        if not valuation_snapshot_id:
            blockers.append("valuation_snapshot_identity_missing")
        return {
            "total_equity": total_equity,
            "stock_equity": stock_equity,
            "stock_position_market_values": portfolio_summary.get(
                "stock_position_market_values"
            ),
            "cash": _nonnegative_cash(portfolio_summary.get("cash")),
            "fact_authority": portfolio_summary.get("fact_authority"),
            "board_buy_permissions": portfolio_summary.get("board_buy_permissions"),
            "valuation_status": valuation_status,
            "valuation_snapshot_id": valuation_snapshot_id,
            "valuation_lanes": list(portfolio_summary.get("valuation_lanes") or []),
            "symbols": sorted(
                {
                    str(symbol)
                    for symbol in portfolio_summary.get("symbols") or []
                    if str(symbol)
                }
            ),
            "stock_symbols": portfolio_stock_symbols(portfolio_summary, blockers),
        }, blockers

    def _load_market_evidence(
        self,
        *,
        market_date: str | None,
        promoted: list[dict[str, Any]],
        portfolio_stock_symbols: list[str],
    ) -> tuple[dict[str, Any], list[str]]:
        evidence: dict[str, Any] = {
            "snapshot": {},
            "receipts": [],
            "frames": {},
            "trading_dates": [],
            "history_start": None,
            "held_symbols": [],
        }
        blockers: list[str] = []
        if market_date is None or not promoted:
            return evidence, blockers
        snapshot = dict(
            self._data_store.get_market_universe_snapshot(trade_date=market_date) or {}
        )
        if not snapshot:
            blockers.append("full_market_universe_snapshot_missing")
        start_date = promoted_history_start(promoted, self._config, market_date)
        try:
            trading_dates = verified_trading_dates(
                self._db,
                start_date=start_date,
                end_date=market_date,
            )
        except ValueError as exc:
            trading_dates = []
            blockers.append(str(exc))
        if not trading_dates:
            blockers.append("verified_market_history_window_incomplete")
        receipts: list[dict[str, Any]] = []
        try:
            receipts = resolve_daily_bar_receipts(
                data_store=self._data_store,
                start_date=start_date,
                end_date=market_date,
                config=self._config,
                snapshot=snapshot,
            )
        except (OSError, ValueError):
            blockers.append("full_market_daily_receipt_replay_failed")
        held_symbols: list[str] = []
        frames: dict[str, pd.DataFrame] = {}
        if snapshot:
            members = [
                str(member.get("symbol") or "")
                for member in snapshot.get("members") or []
                if isinstance(member, Mapping)
            ]
            held_symbols = sorted(set(portfolio_stock_symbols))
            frames = self._data_store.load_market_bar_windows(
                symbols=sorted(set(members) | set(held_symbols)),
                start_date=start_date,
                end_date=market_date,
            )
        return {
            "snapshot": snapshot,
            "receipts": receipts,
            "frames": frames,
            "trading_dates": trading_dates,
            "history_start": start_date,
            "held_symbols": held_symbols,
        }, blockers

    def _evaluate_promoted_strategies(
        self,
        *,
        promoted: list[dict[str, Any]],
        market_date: str | None,
        market: Mapping[str, Any],
        total_equity: float,
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[str]]:
        start_date = market.get("history_start")
        if market_date is None or not isinstance(start_date, str):
            return {}, [], []
        return evaluate_promoted_strategy_market(
            promoted=promoted,
            market_date=market_date,
            snapshot=market["snapshot"],
            frames=market["frames"],
            receipts=market["receipts"],
            trading_dates=market["trading_dates"],
            start_date=start_date,
            total_equity=total_equity,
            held_stock_symbols=market["held_symbols"],
            policy=self._policy,
        )

    def _complete_run(
        self,
        *,
        decision_date: str,
        started_at: datetime,
        safety_gate: Mapping[str, Any],
        promoted: list[dict[str, Any]],
        market_date: str | None,
        portfolio: Mapping[str, Any],
        market: Mapping[str, Any],
        truth_by_strategy: Mapping[str, dict[str, Any]],
        raw_signals: list[dict[str, Any]],
        blockers: list[str],
        persist_actions: bool,
        expected_signal_selection_fingerprint: str | None,
    ) -> dict[str, Any]:
        blockers = list(dict.fromkeys(blockers))
        reserve_ratio = cash_buffer_ratio(self._config)
        account_signals, account_blocked_buys = account_eligible_signals(
            raw_signals,
            config=self._config,
            decision_date=decision_date,
            portfolio=portfolio,
            policy=self._policy,
            cash_buffer_ratio=reserve_ratio,
            db=self._db,
        )
        selected_signals, signal_conflict_blockers = aggregate_ranked_signals(
            account_signals,
            allocation_slots=self._policy.allocation_slots,
        )
        blockers.extend(signal_conflict_blockers)
        signal_selection_fingerprint = "sha256:" + content_fingerprint(
            {
                "decision_date": decision_date,
                "market_date": market_date,
                "raw_signals": raw_signals,
                "account_blocked_buys": account_blocked_buys,
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
            "market_universe_snapshot_id": market["snapshot"].get("snapshot_id"),
            "receipt_fingerprints": [
                item.get("receipt_fingerprint") for item in market["receipts"]
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
                    "qualification_fingerprint": item.get("qualification_fingerprint"),
                    "universe_truth_fingerprint": truth_by_strategy.get(
                        str(item["strategy_id"]), {}
                    ).get("evidence_fingerprint"),
                }
                for item in promoted
            ],
            "portfolio_binding": portfolio_scan_binding(
                portfolio,
                held_symbols=market["held_symbols"],
                reserve_ratio=reserve_ratio,
            ),
            "evaluation_policy_fingerprint": (
                promoted_scan_evaluation_policy_fingerprint(self._policy)
            ),
            "signal_selection_policy": SIGNAL_SELECTION_POLICY,
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
                payload = json_object(existing.get("payload_json"))
                active_blockers = active_action_blockers(
                    blockers, payload.get("selected_signals") or []
                )
                if active_blockers:
                    payload = {
                        **payload,
                        "status": "blocked",
                        "blockers": active_blockers,
                        "action_tasks": [],
                        "normal_no_signal": False,
                        "finished_at": self._clock().isoformat(),
                    }
                    payload.pop("output_fingerprint", None)
                    payload["output_fingerprint"] = "sha256:" + content_fingerprint(
                        payload
                    )
                return {**payload, "run_id": run_id, "reused": True}

        action_blockers = active_action_blockers(blockers, selected_signals)
        action_tasks: list[dict[str, Any]] = []
        if persist_actions:
            status = (
                "blocked"
                if action_blockers
                else ("completed" if selected_signals else "completed_no_signal")
            )
        else:
            status = (
                "blocked"
                if action_blockers
                else ("prepared" if selected_signals else "prepared_no_signal")
            )
        if persist_actions and not action_blockers and selected_signals:

            def current_authority_validator():
                from server.services.account.account_board_permissions import (
                    resolve_board_buy_permissions,
                )
                from server.services.account.valuation_snapshot import (
                    build_current_valuation_snapshot,
                )

                current, changed = self._resolve_promoted_strategies(decision_date)
                changed.extend(
                    decision_window_blockers(
                        db=self._db, decision_date=decision_date, now=self._clock()
                    )
                )
                current_safety = self._read_safety_gate()
                changed.extend(automation_safety_blockers(current_safety))
                for item in current:
                    row = self._db.get_strategy_promotion_state_sync(
                        item["strategy_id"]
                    )
                    blocker = publication_source_blocker(self._db, row or {})
                    if blocker:
                        changed.append(blocker)
                permissions = resolve_board_buy_permissions(self._config, decision_date)
                buys = [row for row in selected_signals if row["direction"] == "buy"]
                _, board_blockers = policy_entry_signals(
                    buys,
                    portfolio={**portfolio, "board_buy_permissions": permissions},
                    decision_date=decision_date,
                    db=self._db,
                )
                changed.extend(
                    "current_board_permission_changed:" + row["reason"]
                    for row in board_blockers
                )
                for row in buys:
                    if not row.get("portfolio_policy_id"):
                        blocker = board_buy_blocker(
                            row["symbol"], permissions, decision_date
                        )
                        if blocker:
                            changed.append(
                                "current_board_permission_changed:" + blocker
                            )
                try:
                    valuation = build_current_valuation_snapshot(
                        self._db, persist=False, now=self._clock()
                    )
                    if (
                        not is_asset_class_valuation_healthy(valuation, "stock")
                        or valuation.get("snapshot_id")
                        != portfolio["valuation_snapshot_id"]
                    ):
                        changed.append("current_portfolio_valuation_changed")
                    if (
                        prior_verified_trading_date(self._db, decision_date)
                        != market_date
                    ):
                        changed.append("current_market_session_changed")
                    snapshot = dict(
                        self._data_store.get_market_universe_snapshot(
                            trade_date=market_date
                        )
                        or {}
                    )
                    if snapshot != market["snapshot"]:
                        changed.append("current_market_universe_changed")
                    receipts = resolve_daily_bar_receipts(
                        data_store=self._data_store,
                        start_date=market["history_start"],
                        end_date=market_date,
                        config=self._config,
                        snapshot=snapshot,
                    )
                    if receipts != market["receipts"]:
                        changed.append("current_market_receipts_changed")
                    if (
                        verified_trading_dates(
                            self._db,
                            start_date=market["history_start"],
                            end_date=market_date,
                        )
                        != market["trading_dates"]
                    ):
                        changed.append("current_market_calendar_changed")
                except (
                    AttributeError,
                    KeyError,
                    LookupError,
                    OSError,
                    TypeError,
                    ValueError,
                ):
                    changed.append("current_account_or_market_evidence_unavailable")
                if changed or current != promoted or current_safety != safety_gate:
                    raise ValueError(
                        "promoted_strategy_scan_authority_changed_before_persist"
                        + (":" + ",".join(changed) if changed else "")
                    )

            try:
                action_tasks = persist_recommendation_tasks(
                    db=self._db,
                    decision_date=decision_date,
                    signals=selected_signals,
                    current_authority_validator=current_authority_validator,
                )
            except ValueError as exc:
                if not str(exc).startswith(
                    "promoted_strategy_scan_authority_changed_before_persist"
                ):
                    raise
                action_blockers.append(str(exc))
                status = "blocked"
        payload_core = {
            **input_core,
            "status": status,
            "input_fingerprint": input_fingerprint,
            "blockers": action_blockers,
            "raw_signal_count": len(raw_signals),
            "raw_signals": raw_signals,
            "account_blocked_buys": account_blocked_buys,
            "selected_signal_count": len(selected_signals),
            "selected_signals": selected_signals,
            "action_tasks": action_tasks,
            "full_market_truths": [
                truth_projection(strategy_id, truth)
                for strategy_id, truth in sorted(truth_by_strategy.items())
            ],
            "normal_no_signal": status == "completed_no_signal" and not raw_signals,
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
                    "source_ref": market["snapshot"].get("snapshot_id"),
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
        from server.contracts.recommendation_publication import (
            publication_source_blocker,
        )

        for row in active:
            if publication_source_blocker(self._db, row) is not None:
                continue
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
            qualification_binding = dict(promotion.get("qualification_binding") or {})
            qualification_fingerprint = str(
                qualification_binding.get("evidence_fingerprint") or ""
            )
            if (
                artifact.get("qualification_overlay_required") is True
                and not qualification_fingerprint
            ):
                blockers.append(
                    f"promoted_strategy_gate:{strategy_id}:"
                    "qualification_binding_missing"
                )
                continue
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
            policy_history = None
            if promotion.get("decision_source") == "policy":
                from server.persistence.strategy_research import (
                    StrategyResearchAuditStore,
                )

                try:
                    final = StrategyResearchAuditStore(self._db.path).get_sealed_test(
                        promotion["publication_decision"]["final_evaluation_id"]
                    )
                    policy_history = date.fromisoformat(
                        final["evidence"]["sealed_dataset_snapshot"]["date_range"][
                            "start"
                        ]
                    ).isoformat()
                    if policy_history >= decision_date:
                        raise ValueError("frozen_history_not_before_decision")
                except (KeyError, LookupError, TypeError, ValueError):
                    blockers.append(
                        f"promoted_strategy_snapshot:{strategy_id}:frozen_history_unavailable"
                    )
                    continue
            resolved.append(
                {
                    "strategy_id": strategy_id,
                    "strategy": dict(loaded.get("strategy") or {}),
                    "portfolio_policy_id": (
                        "karkinos.research.session_portfolio.liquidity_slots.v1"
                        if promotion.get("decision_source") == "policy"
                        else None
                    ),
                    "strategy_artifact_fingerprint": loaded.get(
                        "strategy_artifact_fingerprint"
                    ),
                    "order_generation_gate_fingerprint": "sha256:"
                    + content_fingerprint(gate),
                    "qualification_fingerprint": (qualification_fingerprint or None),
                    "history_start": policy_history
                    or history_start(
                        self._config,
                        prior_verified_trading_date(self._db, decision_date)
                        or decision_date,
                    ),
                }
            )
        if not resolved and not blockers:
            blockers.append("promoted_daily_candidate_strategy_missing")
        return resolved, blockers

    def _load_strategy(self, *, candidate_id: str, run_id: str) -> dict[str, Any]:
        database_path = Path(self._db.path)
        store = DailyStrategyArtifactStore(
            database_path,
            database_path.parent / "strategy-research-backups",
        )
        try:
            return store.load_verified_winner_strategy(
                candidate_id=candidate_id,
                run_id=run_id,
            )
        except DailyStrategyArtifactRejected as winner_error:
            try:
                return store.require_verified_research_candidate(
                    candidate_id=candidate_id,
                    run_id=run_id,
                )
            except DailyStrategyArtifactRejected:
                raise winner_error


def _nonnegative_cash(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        cash = float(value)
    except (TypeError, ValueError):
        return None
    return cash if isfinite(cash) and cash >= 0 else None
