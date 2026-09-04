"""Deterministic full-market scan for human-promoted paper/shadow strategies."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from core.types import InstrumentType
from data.store import DataStore
from server.ai_runtime.contracts import content_fingerprint
from server.bootstrap import resolve_data_dir
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactRejected,
    DailyStrategyArtifactStore,
)
from server.services.market_universe_automation import verified_trading_dates
from server.services.market_universe_truth import MarketUniversePolicy
from server.services.promoted_strategy_universe_scan_persistence import (
    persist_recommendation_tasks,
)
from server.services.promoted_strategy_universe_scan_support import (
    SIGNAL_SELECTION_POLICY,
    aggregate_ranked_signals,
    automation_safety_blockers,
    decision_window_blockers,
    evaluate_promoted_strategy_market,
    history_start,
    json_object,
    positive_float,
    prior_verified_trading_date,
    promoted_scan_evaluation_policy_fingerprint,
    truth_projection,
)
from server.services.promoted_strategy_universe_scan_validation import (
    current_scan_input_blockers,
)
from server.services.strategy_promotion_pipeline import (
    AI_SHADOW_STRATEGY_PREFIX,
    resolve_strategy_order_generation_gate,
)

PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION = (
    "karkinos.promoted_strategy_universe_scan.v1"
)
PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE = "promoted_strategy_universe_scan"
StrategyGateResolver = Callable[..., tuple[dict[str, Any], list[str]]]
StrategyLoader = Callable[..., dict[str, Any]]
SafetyGateReader = Callable[[], Mapping[str, Any]]


def _portfolio_stock_symbols(
    portfolio_summary: Mapping[str, Any],
    blockers: list[str],
) -> list[str]:
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
        if blockers:
            truths, raw_signals, truth_blockers = {}, [], []
        else:
            truths, raw_signals, truth_blockers = self._evaluate_promoted_strategies(
                promoted=promoted,
                market_date=market_date,
                market=market,
                total_equity=portfolio["total_equity"],
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
        total_equity = positive_float(portfolio_summary.get("total_equity"))
        if total_equity is None:
            blockers.append("portfolio_total_equity_invalid")
            total_equity = 0.0
        valuation_status = (
            str(portfolio_summary.get("valuation_status") or "missing").strip().lower()
        )
        if valuation_status != "complete":
            blockers.append("valuation_snapshot_not_complete")
        valuation_snapshot_id = str(
            portfolio_summary.get("valuation_snapshot_id") or ""
        )
        if not valuation_snapshot_id:
            blockers.append("valuation_snapshot_identity_missing")
        return {
            "total_equity": total_equity,
            "valuation_status": valuation_status,
            "valuation_snapshot_id": valuation_snapshot_id,
            "symbols": sorted(
                {
                    str(symbol)
                    for symbol in portfolio_summary.get("symbols") or []
                    if str(symbol)
                }
            ),
            "stock_symbols": _portfolio_stock_symbols(portfolio_summary, blockers),
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
        start_date = history_start(self._config, market_date)
        trading_dates = verified_trading_dates(
            self._db,
            start_date=start_date,
            end_date=market_date,
        )
        if not trading_dates:
            blockers.append("verified_market_history_window_incomplete")
        receipts: list[dict[str, Any]] = []
        try:
            receipts = [
                dict(item)
                for item in self._data_store.list_market_daily_ingestion_receipts(
                    start_date=start_date,
                    end_date=market_date,
                    provider_name=str(getattr(self._config, "data_source", "") or ""),
                )
            ]
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
                symbols=members,
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
        selected_signals, signal_conflict_blockers = aggregate_ranked_signals(
            raw_signals,
            allocation_slots=self._policy.allocation_slots,
        )
        blockers.extend(signal_conflict_blockers)
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
            "portfolio_binding": {
                "valuation_snapshot_id": portfolio["valuation_snapshot_id"] or None,
                "valuation_status": portfolio["valuation_status"],
                "held_symbol_fingerprint": "sha256:"
                + content_fingerprint(market["held_symbols"]),
                "held_stock_count": len(market["held_symbols"]),
                "capital_constraint_fingerprint": "sha256:"
                + content_fingerprint(
                    {
                        "valuation_snapshot_id": portfolio["valuation_snapshot_id"],
                        "valuation_status": portfolio["valuation_status"],
                        "total_equity": portfolio["total_equity"],
                    }
                ),
            },
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
            action_tasks = persist_recommendation_tasks(
                db=self._db,
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
                truth_projection(strategy_id, truth)
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
            resolved.append(
                {
                    "strategy_id": strategy_id,
                    "strategy": dict(loaded.get("strategy") or {}),
                    "strategy_artifact_fingerprint": loaded.get(
                        "strategy_artifact_fingerprint"
                    ),
                    "order_generation_gate_fingerprint": "sha256:"
                    + content_fingerprint(gate),
                    "qualification_fingerprint": (qualification_fingerprint or None),
                }
            )
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
