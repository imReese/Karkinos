"""Canonical account-action recommendation beside research-only previews."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime, time, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable
from zoneinfo import ZoneInfo

from server.contracts.content_identity import content_fingerprint

if TYPE_CHECKING:
    from data.dataset.reader import DailyBarDatasetReadResult

ACCOUNT_ACTION_RECOMMENDATION_SCHEMA_VERSION = (
    "karkinos.decision.account_action_recommendation.v1"
)
PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION = (
    "karkinos.promoted_strategy_universe_scan.v1"
)
PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE = "promoted_strategy_universe_scan"

_SCAN_INPUT_KEYS = (
    "schema_version",
    "decision_date",
    "market_date",
    "market_universe_snapshot_id",
    "receipt_fingerprints",
    "strategy_bindings",
    "portfolio_binding",
    "evaluation_policy_fingerprint",
    "signal_selection_policy",
    "signal_selection_fingerprint",
    "safety_gate_fingerprint",
)


def build_research_simulation_action_preview(
    *,
    research_source: Mapping[str, Any] | None,
    decision_payload: Mapping[str, Any],
    account_fact_blockers: Sequence[str] | None = None,
    positions: Mapping[str, Any] | None = None,
    position_values: Mapping[str, Decimal] | None = None,
    target_board_buy_permissions: Mapping[str, Any] | None = None,
    market_session: Mapping[str, Any] | None = None,
    market_snapshot: Mapping[str, Any] | None = None,
    verified_dataset_read: DailyBarDatasetReadResult | None = None,
    receipts: Sequence[Mapping[str, Any]] = (),
    trading_dates: Sequence[str] = (),
    history_start: str | None = None,
    target_market_date: str | None = None,
    display_name_resolver: Callable[[str, str | None], str] | None = None,
) -> dict[str, Any]:
    """Model one explicit research source against an existing account snapshot.

    Prices come only from a strict, verification-bound Dataset read; real daily
    receipts separately supply the existing full-market truth's coverage lane.
    Account blockers must be the account-truth lane of
    ``build_daily_candidate_base_gate`` plus current valuation/position bindings,
    never promotion, forward qualification, or the aggregate strict-action gate.
    No blocker supplied here is discarded. Prices are verified daily closes,
    not current quotes; an unfilled hypothetical exit never finances an entry.
    """
    from data.dataset.reader import DailyBarDatasetReadResult
    from data.research_market_data import _verified_supplement_frames
    from domain.instrument import make_research_stock
    from domain.research_targets import allocate_formula_targets
    from server.ai_runtime.strategy_research_support import selection_from_session
    from server.contracts.content_identity import canonical_json
    from server.contracts.http.strategy_models import BacktestCostAssumptions
    from server.services.backtest.backtest_costs import (
        quote_formula_purchase,
        resolve_backtest_costs,
    )
    from server.services.decision.daily_trading_plan_constraints import position_float
    from server.services.market.market_universe_truth import (
        MarketUniversePolicy,
        build_full_market_universe_truth,
        market_deployment_scope,
    )
    from server.services.strategy_scan.universe.evaluation import (
        board_buy_blocker,
        evaluate_strategy_signals,
        formula_history_rows,
    )

    source = dict(research_source or {})
    source_core = {
        key: value for key, value in source.items() if key != "source_fingerprint"
    }
    summary = _mapping(decision_payload.get("summary"))
    portfolio = _mapping(summary.get("portfolio"))
    session = _mapping(market_session)
    as_of = str(session.get("latest_completed_trade_date") or "") or None
    expected_target = (
        session.get("market_date")
        if session.get("status") in {"pre_open", "open", "midday_break"}
        else session.get("next_trading_date")
    )
    core: dict[str, Any] = {
        "status": "blocked",
        "blockers": [],
        "actions": [],
        "blocked_candidates": [],
        "source": {
            key: source.get(key)
            for key in (
                "session_id",
                "draft_id",
                "backtest_run_id",
                "critique_id",
                "canonical_backtest_result_id",
                "formula_fingerprint",
                "source_fingerprint",
                "historical_validation_status",
                "research_evidence_bundle",
                "dataset_simulation_admission",
                "current_CAS_replayed",
            )
        },
        "valuation_snapshot_id": portfolio.get("valuation_snapshot_id"),
        "ledger_cutoff_id": portfolio.get("ledger_cutoff_id"),
        "account_truth_source_fingerprint": _mapping(summary.get("account_truth")).get(
            "source_fingerprint"
        ),
        "as_of_market_date": as_of,
        "target_market_date": target_market_date,
        "price_basis": "verified_daily_close",
        "uses_current_quotes": False,
        "cost_basis": "saved_research_assumptions",
        "account_fee_schedule_evaluated": False,
        "quantity_basis": "desired_target_before_fill_simulation",
        "execution_simulated": False,
        "research_only": True,
        "read_only": True,
        "manual_confirmation_required": True,
        "human_review_status": "not_recorded",
        "executable": False,
        "creates_action_task": False,
        "creates_order_intent": False,
        "creates_oms_order": False,
        "authorizes_account_publication": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "authority_effect": "none",
    }
    blockers = list(account_fact_blockers or ())
    if account_fact_blockers is None:
        blockers.append("research_account_facts_not_checked")
    if source.get("status") != "ready":
        blockers.extend(
            _strings(source.get("blockers")) or ["research_simulation_source_not_ready"]
        )
    elif source.get("source_fingerprint") != "sha256:" + content_fingerprint(
        source_core
    ):
        blockers.append("research_simulation_source_fingerprint_mismatch")
    blockers.extend(_portfolio_preview_blockers(summary=summary, current_blockers=()))
    if portfolio.get("fact_authority") != "persisted_valuation_snapshot":
        blockers.append("research_valuation_fact_authority_missing")
    if (
        not portfolio.get("valuation_snapshot_id")
        or _nonnegative_int(portfolio.get("ledger_cutoff_id")) is None
    ):
        blockers.append("research_valuation_ledger_binding_missing")
    if positions is None or position_values is None:
        blockers.append("research_position_evidence_missing")
    elif set(position_values) != {str(s) for s in portfolio.get("symbols") or []}:
        blockers.append("research_position_coverage_mismatch")
    if (
        session.get("calendar_verified") is not True
        or not session.get("calendar_evidence_refs")
        or not as_of
        or not target_market_date
        or target_market_date != expected_target
        or target_market_date <= as_of
        or not history_start
        or not trading_dates
        or trading_dates[-1] != as_of
        or not market_snapshot
        or not receipts
    ):
        blockers.append("research_latest_verified_daily_window_unavailable")
    if (
        not isinstance(verified_dataset_read, DailyBarDatasetReadResult)
        or not verified_dataset_read.snapshot.verification_bound
        or verified_dataset_read.snapshot.end_date.isoformat() != as_of
        or not history_start
        or verified_dataset_read.snapshot.start_date.isoformat() > history_start
    ):
        blockers.append("research_latest_cross_source_dataset_unavailable")
    elif set(trading_dates) - {
        partition.partition_date.isoformat()
        for partition in verified_dataset_read.snapshot.partitions
    }:
        blockers.append("research_cross_source_session_coverage_incomplete")
    if blockers:
        core["blockers"] = list(dict.fromkeys(blockers))
        return {**core, "evidence_fingerprint": "sha256:" + content_fingerprint(core)}
    try:
        selection = selection_from_session(
            {"request_json": canonical_json({"selection": source["selection"]})}
        )
        scope = selection.deployment_scope or {}
        policy = MarketUniversePolicy.from_dict(scope["universe_policy"])
        if market_deployment_scope(policy) != scope:
            raise ValueError("research_simulation_scope_mismatch")
        assert verified_dataset_read is not None
        frames = _verified_supplement_frames(
            verified_dataset_read,
            [key.symbol for key in verified_dataset_read.snapshot.instruments],
            str(history_start),
            str(as_of),
        )
        core["market_dataset_id"] = verified_dataset_read.ref.dataset_id
        cash = Decimal(str(portfolio["cash"]))
        equity = Decimal(str(portfolio["total_equity"]))
        if not cash.is_finite() or cash < 0 or not equity.is_finite() or equity <= 0:
            raise ValueError("research_account_cash_or_equity_invalid")
        values = dict(position_values or {})
        if any(
            not isinstance(v, Decimal) or not v.is_finite() or v < 0
            for v in values.values()
        ):
            raise ValueError("research_position_value_invalid")
        stock_symbols = [
            s
            for s in values
            if _mapping(portfolio.get("instrument_types")).get(s) == "stock"
        ]
        if set(stock_symbols) != set(
            _mapping(portfolio.get("stock_position_market_values"))
        ):
            raise ValueError("research_stock_position_identity_incomplete")
        if any(
            values[s] != Decimal(str(portfolio["stock_position_market_values"][s]))
            for s in stock_symbols
        ):
            raise ValueError("research_stock_position_valuation_mismatch")
        truth = build_full_market_universe_truth(
            snapshot=dict(market_snapshot or {}),
            frames=frames,
            receipts=receipts,
            required_trading_dates=trading_dates,
            start_date=str(history_start),
            end_date=str(as_of),
            initial_cash=float(equity),
            target_weight=float(policy.target_weight),
            held_symbols=stock_symbols,
            minimum_history_rows=max(
                policy.minimum_history_rows, formula_history_rows(source["formula_ast"])
            ),
            policy=policy,
        )
        core["market_truth"] = truth
        if truth["status"] != "complete":
            core["blockers"] = _strings(truth.get("blockers")) or [
                "research_market_truth_incomplete"
            ]
            return {
                **core,
                "evidence_fingerprint": "sha256:" + content_fingerprint(core),
            }
        signals = evaluate_strategy_signals(
            strategy_id="research:" + str(source["draft_id"]),
            formula_ast=source["formula_ast"],
            universe_size=len(selection.universe),
            target_weight=float(policy.target_weight),
            frames=frames,
            eligible_symbols=truth["eligible_symbols"],
            maintenance_symbols=truth["maintenance_symbols"],
            held_symbols=set(stock_symbols),
            market_date=str(as_of),
        )
        blocked_candidates = []
        usable = []
        for row in signals:
            reason = None
            if row["direction"] == "buy":
                reason = board_buy_blocker(
                    row["symbol"],
                    target_board_buy_permissions
                    if target_board_buy_permissions is not None
                    else portfolio.get("board_buy_permissions"),
                    str(target_market_date),
                )
            else:
                position = (positions or {}).get(row["symbol"])
                quantity = position_float(position, "quantity", "shares")
                sellable = position_float(
                    position,
                    "t1_available_quantity",
                    "sellable_quantity",
                    "available_quantity",
                )
                if (
                    not math.isfinite(quantity)
                    or not math.isfinite(sellable)
                    or quantity <= 0
                    or sellable != quantity
                ):
                    reason = "research_sellable_quantity_insufficient_or_missing"
            if reason:
                blocked_candidates.append(
                    {
                        "symbol": row["symbol"],
                        "side": row["direction"],
                        "reason": reason,
                    }
                )
            else:
                usable.append(row)
        buys = {r["symbol"]: r for r in usable if r["direction"] == "buy"}
        instruments = {s: make_research_stock(s, s) for s in buys}
        costs, effective = resolve_backtest_costs(
            BacktestCostAssumptions.model_validate(source.get("cost_assumptions") or {})
        )
        allocation = allocate_formula_targets(
            entries=list(buys),
            exits=[r["symbol"] for r in usable if r["direction"] == "sell"],
            position_values=values,
            prices={s: Decimal(str(r["frozen_close"])) for s, r in buys.items()},
            liquidity={
                s: Decimal(str(r["ranking_liquidity"])) for s, r in buys.items()
            },
            lot_sizes={s: item.lot_size for s, item in instruments.items()},
            cash=cash,
            equity=equity,
            buy_cost=lambda s, p, q: quote_formula_purchase(
                costs.commission_calc,
                instruments[s],
                s,
                p,
                q,
                slippage_bps=Decimal(effective["slippage_bps"]),
            ),
            max_positions=policy.allocation_slots,
            max_symbol_weight=policy.target_weight,
        )
        targets = allocation["target_weights"]
        quantities = allocation["entry_quantities"]
        purchase_costs = allocation["purchase_costs"]
        rejections = allocation["rejected_entries"]
        entries = allocation["selected_entries"]
        exits = allocation["exit_symbols"]
        if (
            not isinstance(targets, dict)
            or not isinstance(quantities, dict)
            or not isinstance(purchase_costs, dict)
            or not isinstance(rejections, dict)
            or not isinstance(entries, list)
            or not isinstance(exits, list)
        ):
            raise ValueError("research_allocation_result_invalid")
        blocked_candidates.extend(
            {"symbol": s, "side": "buy", "reason": reason}
            for s, reason in rejections.items()
        )
        selected = set(entries) | set(exits)
        draft = _mapping(source.get("draft"))
        actions = []
        for row in usable:
            symbol = row["symbol"]
            if symbol not in selected:
                continue
            entry_quantity = quantities.get(symbol)
            actions.append(
                {
                    **_signal_projection(row, display_name_resolver),
                    "submission_status": "research_simulation_only",
                    "target_weight": float(targets[symbol]),
                    "estimated_quantity": float(entry_quantity)
                    if entry_quantity is not None
                    else position_float(
                        (positions or {}).get(symbol), "quantity", "shares"
                    ),
                    "estimated_purchase_cost": float(purchase_costs[symbol])
                    if symbol in purchase_costs
                    else None,
                    "trigger_condition": draft.get(
                        "entry_conditions"
                        if row["direction"] == "buy"
                        else "exit_conditions"
                    )
                    or _formula_condition_summary(
                        source["formula_ast"].get(
                            "entry" if row["direction"] == "buy" else "exit"
                        )
                    ),
                    "reason": draft.get("economic_hypothesis"),
                    "risk_impact": draft.get("risk_impact"),
                    "manual_confirmation_required": True,
                    "executable": False,
                }
            )
        core.update(
            status="available"
            if actions
            else "blocked"
            if blocked_candidates
            else "no_action",
            actions=actions,
            blocked_candidates=blocked_candidates,
            blockers=[]
            if actions or not blocked_candidates
            else ["research_candidates_account_constraints_blocked"],
            cost_assumptions=effective,
            critique=source["critique"],
            target_weights={s: str(v) for s, v in targets.items()},
            hypothetical_exit_proceeds_available=False,
        )
    except (KeyError, TypeError, ValueError) as exc:
        code = str(exc)
        core["blockers"] = [
            code
            if isinstance(exc, ValueError) and code.startswith("research_")
            else "research_simulation_inputs_invalid_or_incomplete"
        ]
    return {**core, "evidence_fingerprint": "sha256:" + content_fingerprint(core)}


def resolve_latest_verified_promoted_strategy_scan(
    db: Any,
    *,
    decision_date: str,
    expected_run_id: str | None = None,
) -> dict[str, Any]:
    """Reopen and rehash a bound scan, or the latest same-day scan for legacy reads."""

    reader = getattr(db, "list_automation_runs_sync", None)
    if not callable(reader) or not decision_date:
        return _unavailable_scan("promoted_strategy_scan_reader_unavailable")
    if expected_run_id is not None:
        exact_reader = getattr(db, "get_automation_run_sync", None)
        row = exact_reader(expected_run_id) if callable(exact_reader) else None
        rows = [row] if isinstance(row, Mapping) else []
        if not rows:
            return _unavailable_scan("promoted_strategy_scan_bound_run_missing")
    else:
        rows = reader(
            run_type=PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE,
            run_date=decision_date,
            limit=1,
        )
    if not rows:
        promotion_reader = getattr(db, "list_strategy_promotion_states_sync", None)
        if callable(promotion_reader):
            eligible_promotions = [
                row
                for row in (promotion_reader() or [])
                if str(row.get("strategy_id") or "").startswith("ai_formula_shadow:")
                and str(row.get("stage") or "") == "paper_shadow"
            ]
            if not eligible_promotions:
                return _unavailable_scan("promoted_strategy_not_configured")
        return _unavailable_scan("promoted_strategy_scan_missing")
    row = dict(rows[0])
    payload = _json_object(row.get("payload_json"))
    output_fingerprint = str(payload.get("output_fingerprint") or "")
    output_core = dict(payload)
    output_core.pop("output_fingerprint", None)
    input_core = {key: payload.get(key) for key in _SCAN_INPUT_KEYS}
    expected_input_fingerprint = "sha256:" + content_fingerprint(input_core)
    expected_output_fingerprint = "sha256:" + content_fingerprint(output_core)
    input_fingerprint = str(payload.get("input_fingerprint") or "")
    expected_run_id = (
        f"automation:promoted-strategy-universe-scan:{decision_date}:"
        f"{input_fingerprint.removeprefix('sha256:')[:16]}"
    )
    blockers: list[str] = []
    if row.get("run_type") != PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE:
        blockers.append("promoted_strategy_scan_type_mismatch")
    if row.get("run_date") != decision_date or payload.get("decision_date") != (
        decision_date
    ):
        blockers.append("promoted_strategy_scan_date_mismatch")
    if payload.get("schema_version") != (
        PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION
    ):
        blockers.append("promoted_strategy_scan_schema_mismatch")
    if row.get("status") != payload.get("status"):
        blockers.append("promoted_strategy_scan_status_mismatch")
    scan_status = str(row.get("status") or "")
    started_at_blockers = _scan_started_at_blockers(
        row.get("started_at"), decision_date
    )
    if scan_status in {"completed", "completed_no_signal"}:
        blockers.extend(started_at_blockers)
    else:
        blockers.extend(
            item
            for item in started_at_blockers
            if item != "promoted_strategy_scan_started_at_outside_reviewed_window"
        )
    if str(row.get("run_id") or "") != expected_run_id:
        blockers.append("promoted_strategy_scan_run_identity_mismatch")
    if input_fingerprint != expected_input_fingerprint:
        blockers.append("promoted_strategy_scan_input_fingerprint_mismatch")
    if output_fingerprint != expected_output_fingerprint:
        blockers.append("promoted_strategy_scan_output_fingerprint_mismatch")
    if payload.get("preview_only") is not False:
        blockers.append("promoted_strategy_scan_not_persisted")
    if payload.get("creates_oms_order") is not False:
        blockers.append("promoted_strategy_scan_order_boundary_invalid")
    if payload.get("submits_broker_order") is not False:
        blockers.append("promoted_strategy_scan_broker_boundary_invalid")
    if payload.get("changes_capital_authority") is not False:
        blockers.append("promoted_strategy_scan_capital_boundary_invalid")
    if payload.get("mutates_account_ledger") is not False:
        blockers.append("promoted_strategy_scan_ledger_boundary_invalid")
    if payload.get("changes_strategy_promotion") is not False:
        blockers.append("promoted_strategy_scan_promotion_boundary_invalid")
    if payload.get("manual_confirmation_required") is not True:
        blockers.append("promoted_strategy_scan_human_control_invalid")
    blockers.extend(_scan_semantic_blockers(payload))
    if blockers:
        return _unavailable_scan(blockers[0], blockers=blockers)
    return {
        "decision_date": str(payload.get("decision_date") or "") or None,
        "market_date": str(payload.get("market_date") or "") or None,
        "status": str(payload.get("status") or "unavailable"),
        "run_id": str(row.get("run_id") or ""),
        "started_at": str(row.get("started_at") or "") or None,
        "input_fingerprint": input_fingerprint,
        "output_fingerprint": output_fingerprint,
        "selected_signal_count": int(payload.get("selected_signal_count") or 0),
        "signals": [
            dict(item)
            for item in payload.get("selected_signals") or []
            if isinstance(item, Mapping)
        ],
        "normal_no_signal": payload.get("normal_no_signal") is True,
        "raw_signal_count": int(payload.get("raw_signal_count") or 0),
        "raw_signals": [
            dict(item)
            for item in payload.get("raw_signals") or []
            if isinstance(item, Mapping)
        ],
        "account_blocked_buys": [
            dict(item)
            for item in payload.get("account_blocked_buys") or []
            if isinstance(item, Mapping)
        ],
        "blockers": _strings(payload.get("blockers")),
        "strategy_bindings": [
            dict(item)
            for item in payload.get("strategy_bindings") or []
            if isinstance(item, Mapping)
        ],
        "portfolio_binding": _mapping(payload.get("portfolio_binding")),
        "market_universe_snapshot_id": payload.get("market_universe_snapshot_id"),
        "receipt_fingerprints": _strings(payload.get("receipt_fingerprints")),
        "evaluation_policy_fingerprint": payload.get("evaluation_policy_fingerprint"),
        "signal_selection_fingerprint": payload.get("signal_selection_fingerprint"),
        "safety_gate_fingerprint": payload.get("safety_gate_fingerprint"),
        "action_task_ids": [
            str(item.get("task_id") or item.get("action_id") or "")
            for item in payload.get("action_tasks") or []
            if isinstance(item, Mapping)
            and str(item.get("task_id") or item.get("action_id") or "")
        ],
        "verified": True,
    }


def resolve_account_strategy_context(
    db: Any, promoted_scan: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """Explain exact published scan sources without changing action authority."""
    from server.persistence.database_identity import optional_database_path
    from server.services.ai_shadow.ai_shadow_research_daily_artifacts import (
        DailyStrategyArtifactRejected,
        DailyStrategyArtifactStore,
    )
    from server.services.research.strategy_promotion_pipeline import (
        resolve_strategy_order_generation_gate,
    )

    path = optional_database_path(db)
    if path is None or promoted_scan.get("verified") is not True:
        return {}
    bindings = [
        item
        for item in promoted_scan.get("strategy_bindings") or []
        if isinstance(item, Mapping)
    ]
    contexts: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        identity = str(binding.get("strategy_id") or "")
        expected = binding.get("strategy_artifact_fingerprint")
        if (
            not identity.startswith("ai_formula_shadow:")
            or not _is_sha256(expected)
            or sum(item.get("strategy_id") == identity for item in bindings) != 1
        ):
            continue
        try:
            gate, blockers = resolve_strategy_order_generation_gate(
                db,
                identity,
                as_of_date=str(promoted_scan.get("decision_date") or "") or None,
            )
            if (
                blockers
                or gate.get("status") != "pass"
                or binding.get("order_generation_gate_fingerprint")
                != "sha256:" + content_fingerprint(gate)
            ):
                continue
            promotion = _mapping(gate.get("promotion"))
            artifact = _mapping(promotion.get("daily_strategy_artifact_binding"))
            constraints = _mapping(artifact.get("operating_constraints"))
            if constraints.get("strategy_artifact_fingerprint") != expected:
                continue
            candidate_id = str(artifact.get("winner_candidate_id") or "")
            run_id = str(artifact.get("run_id") or "")
            store = DailyStrategyArtifactStore(
                path, path.parent / "strategy-research-backups"
            )
            try:
                loaded = store.load_verified_winner_strategy(
                    candidate_id=candidate_id, run_id=run_id
                )
            except DailyStrategyArtifactRejected:
                loaded = store.require_verified_research_candidate(
                    candidate_id=candidate_id, run_id=run_id
                )
            strategy = _mapping(loaded.get("strategy"))
            if (
                loaded.get("candidate_id") != candidate_id
                or loaded.get("run_id") != run_id
                or loaded.get("strategy_artifact_fingerprint") != expected
                or content_fingerprint(strategy) != expected
            ):
                continue
            entry = strategy.get("entry_conditions")
            exit_condition = strategy.get("exit_conditions")
            condition_basis = "frozen_strategy_text"
            if not all(
                isinstance(item, str) and item.strip()
                for item in (entry, exit_condition)
            ):
                ast = _mapping(strategy.get("formula_ast"))
                entry = _formula_condition_summary(ast.get("entry"))
                exit_condition = _formula_condition_summary(ast.get("exit"))
                condition_basis = "formula_ast_summary"
            saved_id = promotion.get("backtest_result_id")
            saved_id = saved_id if type(saved_id) is int and saved_id > 0 else None
            contexts[identity] = {
                "strategy_id": identity,
                "strategy_stage": promotion.get("stage"),
                "candidate_id": candidate_id,
                "run_id": run_id,
                "strategy_artifact_fingerprint": expected,
                "saved_backtest_id": saved_id,
                "entry_conditions": entry,
                "exit_conditions": exit_condition,
                "condition_basis": condition_basis,
                "economic_hypothesis": constraints.get("economic_hypothesis"),
                "risk_impact": constraints.get("risk_impact"),
                "failure_conditions": _strings(constraints.get("failure_conditions")),
                "forward": _account_strategy_forward_context(path, saved_id),
                "historical_comparison": _account_strategy_historical_comparison(
                    path, saved_id, _mapping(strategy.get("formula_ast"))
                ),
                "read_only": True,
                "authorizes_execution": False,
            }
        except (
            LookupError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            sqlite3.Error,
        ):
            # Display evidence cannot make a strategy usable or disable other sources.
            continue
    return contexts


def resolve_historical_research_comparison(db: Any) -> dict[str, Any] | None:
    """Show the latest valid persisted research pair independently of promotion."""
    from server.persistence.backtest_results import BacktestResultsRepository
    from server.persistence.database_identity import optional_database_path

    path = optional_database_path(db)
    if path is None:
        return None
    try:
        anchors = BacktestResultsRepository(
            path
        ).read_recent_historical_comparison_anchors()
        for anchor in anchors:
            pair = _account_strategy_historical_comparison(
                path, anchor["id"], _json_object(anchor.get("formula_ast_json"))
            )
            if pair is None:
                continue
            forward = {}
            for role in ("baseline", "candidate"):
                result_id = pair[role]["result_id"]
                forward[role] = {
                    "source_backtest_result_id": result_id,
                    **_account_strategy_forward_context(path, result_id),
                }
            return {
                **pair,
                "forward": forward,
                "read_only": True,
                "authorizes_execution": False,
            }
    except (LookupError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
        return None
    return None


def _account_strategy_historical_comparison(
    path: Any, saved_id: int | None, formula_ast: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Project a persisted, source-bound research pair; never promote its winner."""
    from server.persistence.backtest_results import (
        BacktestResultsRepository,
        backtest_evidence_blocker,
    )

    if saved_id is None or not formula_ast:
        return None
    try:
        rows = BacktestResultsRepository(path).read_historical_comparison_rows(saved_id)
        by_id = {row["id"]: row for row in rows if not backtest_evidence_blocker(row)}
        if saved_id not in by_id:
            return None
        anchor = _mapping(
            _json_object(by_id[saved_id].get("metrics_json")).get(
                "historical_comparison"
            )
        )
        source_id, anchor_role = saved_id, "source"
        if anchor:
            ancestor_id = anchor.get("historical_formula_source_result_id")
            role = anchor.get("role")
            if (
                type(ancestor_id) is not int
                or ancestor_id <= 0
                or not isinstance(role, str)
                or role not in {"gen7", "candidate2"}
            ):
                return None
            source_id, anchor_role = ancestor_id, role
        if source_id not in by_id:
            return None
        source_binding = _mapping(
            _json_object(by_id[source_id].get("metrics_json")).get("formula_binding")
        )
        source_ast = _mapping(source_binding.get("formula_ast"))
        if not source_ast:
            return None
        # Repository order is newest first, independent of strategy performance.
        for candidate in rows:
            if backtest_evidence_blocker(candidate):
                continue
            candidate_metrics = _json_object(candidate.get("metrics_json"))
            provenance = _mapping(candidate_metrics.get("historical_comparison"))
            if provenance.get("role") != "candidate2":
                continue
            baseline_id = provenance.get("actual_comparison_baseline_result_id")
            if (
                type(baseline_id) is not int
                or baseline_id <= 0
                or baseline_id == source_id
                or candidate["id"] == source_id
                or (anchor_role == "gen7" and baseline_id != saved_id)
                or (anchor_role == "candidate2" and candidate["id"] != saved_id)
            ):
                continue
            baseline = by_id.get(baseline_id)
            if baseline is None or baseline_id == candidate["id"]:
                continue
            pair = [
                _historical_comparison_inputs(row, source_id)
                for row in (baseline, candidate)
            ]
            if any(item is None for item in pair):
                continue
            base, proposed = pair
            assert base is not None and proposed is not None
            bp, cp = base["provenance"], proposed["provenance"]
            context_binding = proposed if anchor_role == "candidate2" else base
            if (
                bp.get("role") != "gen7"
                or bp.get("actual_comparison_baseline_result_id") is not None
                or base["binding"].get("formula_ast") != source_ast
                or context_binding["binding"].get("formula_ast") != formula_ast
                or any(
                    bp.get(key) != cp.get(key)
                    for key in (
                        "dataset_id",
                        "source_files",
                        "runner_sha256",
                        "frozen_input_sha256",
                        "candidate_2_frozen_sha256",
                    )
                )
                or base["snapshot"] != proposed["snapshot"]
                or any(
                    base["config"].get(key) != proposed["config"].get(key)
                    for key in (
                        "start_date",
                        "end_date",
                        "initial_cash",
                        "corporate_action_mode",
                    )
                )
                or not base["binding"].get("cost_model_reference")
                or base["binding"].get("cost_model_reference")
                != proposed["binding"].get("cost_model_reference")
            ):
                continue
            snapshot = base["snapshot"]
            return {
                "status": "recorded_pair",
                "source_result_id": source_id,
                "anchor_result_id": saved_id,
                "dataset_id": bp["dataset_id"],
                "start_date": base["config"]["start_date"],
                "end_date": base["config"]["end_date"],
                "instrument_count": len(snapshot["symbol_universe"]),
                "bar_row_count": snapshot["row_count"],
                "corporate_action_mode": base["config"].get("corporate_action_mode"),
                "point_in_time_verified": snapshot.get("point_in_time_verified"),
                "baseline": _historical_comparison_result(baseline),
                "candidate": _historical_comparison_result(candidate),
                "independent_final_evaluation": False,
                "authority_effect": "none",
            }
    except (LookupError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
        return None
    return None


def _historical_comparison_inputs(
    row: Mapping[str, Any], saved_id: int
) -> dict[str, Any] | None:
    from analytics.dataset_snapshot import backtest_dataset_snapshot_content_id

    metrics = _json_object(row.get("metrics_json"))
    provenance = _mapping(metrics.get("historical_comparison"))
    snapshot = _mapping(metrics.get("dataset_snapshot"))
    config = _json_object(row.get("config_json"))
    binding = _mapping(metrics.get("formula_binding"))
    snapshot_body = dict(snapshot)
    snapshot_id = snapshot_body.pop("snapshot_id", None)
    if (
        type(provenance.get("historical_formula_source_result_id")) is not int
        or provenance.get("historical_formula_source_result_id") != saved_id
        or not _is_prefixed_sha256(provenance.get("dataset_id"))
        or not _is_sha256(provenance.get("runner_sha256"))
        or not _is_sha256(provenance.get("candidate_2_frozen_sha256"))
        or any(
            not isinstance(provenance.get(key), Mapping)
            or not provenance[key]
            or any(not _is_sha256(value) for value in provenance[key].values())
            for key in ("source_files", "frozen_input_sha256")
        )
        or provenance.get("authority_effect") != "none"
        or any(
            provenance.get(key) is not False
            for key in (
                "historical_pit_claimed",
                "scope_is_deployment_admitted",
                "independent_final_evaluation",
            )
        )
        or snapshot.get("schema_version") != "karkinos.dataset_snapshot.v1"
        or snapshot_id != backtest_dataset_snapshot_content_id(snapshot_body)
        or snapshot.get("immutable_dataset_id") != provenance.get("dataset_id")
        or config.get("dataset_id") != provenance.get("dataset_id")
        or snapshot.get("date_range")
        != {"start": config.get("start_date"), "end": config.get("end_date")}
        or not config.get("start_date")
        or not config.get("end_date")
        or not isinstance(snapshot.get("symbol_universe"), list)
        or not snapshot["symbol_universe"]
        or type(snapshot.get("row_count")) is not int
        or snapshot["row_count"] <= 0
        or binding.get("dataset_snapshot_id") != snapshot_id
    ):
        return None
    return {
        "provenance": provenance,
        "snapshot": snapshot,
        "config": config,
        "binding": binding,
    }


def _historical_comparison_result(row: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _json_object(row.get("metrics_json"))
    # New comparison rows already contain engine metrics; this display does no replay
    # or return calculation. The result link retains the canonical detail view.
    values = {
        "total_return": row.get("total_return"),
        "annual_return": row.get("annual_return", metrics.get("annual_return")),
        "sharpe": row.get("sharpe"),
        "max_drawdown": row.get("max_drawdown"),
    }
    return {
        "result_id": row["id"],
        **{
            key: float(value)
            if type(value) in (int, float) and math.isfinite(value)
            else None
            for key, value in values.items()
        },
    }


def _formula_condition_summary(value: Any) -> str | None:
    """Render frozen DSL syntax; do not evaluate or invent a trading rationale."""
    if not isinstance(value, Mapping) or not isinstance(value.get("op"), str):
        return None
    op = value["op"]
    if op == "field":
        return str(value.get("name") or "") or None
    if op == "constant":
        return str(value["value"]) if "value" in value else None
    inputs = [
        _formula_condition_summary(value[key])
        for key in ("left", "right", "input")
        if key in value
    ]
    if any(item is None for item in inputs):
        return None
    arguments = [str(item) for item in inputs]
    arguments.extend(str(value[key]) for key in ("window", "period") if key in value)
    return f"{op}({', '.join(arguments)})" if arguments else None


def _account_strategy_forward_context(
    path: Any, saved_id: int | None
) -> dict[str, Any]:
    from server.persistence.research_observations import ResearchObservationsRepository

    unavailable = {"status": "unavailable", "qualification_assessed": False}
    if saved_id is None:
        return unavailable
    try:
        rows = ResearchObservationsRepository(path).list(
            limit=100, source_backtest_result_id=saved_id
        )
        return {
            "status": "recorded" if rows else "not_started",
            "observation_count": len(rows),
            "lifecycles": sorted({str(row["lifecycle"]) for row in rows}),
            "publication_count": sum(
                len(row.get("publications") or []) for row in rows
            ),
            "outcome_count": sum(len(row.get("outcomes") or []) for row in rows),
            "list_limit": 100,
            "qualification_assessed": False,
        }
    except (LookupError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
        return unavailable


def build_account_action_recommendation(
    *,
    decision_payload: Mapping[str, Any],
    trading_plan: Mapping[str, Any],
    promoted_scan: Mapping[str, Any],
    current_evidence_blockers: Sequence[str],
    current_evidence_fingerprint: str,
    display_name_resolver: Callable[[str, str | None], str] | None = None,
    strategy_context: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project strict action authority plus lower-risk read-only presentation tiers."""

    decision_date = str(decision_payload.get("decision_date") or "")
    candidates = [
        dict(item)
        for item in decision_payload.get("candidates") or []
        if isinstance(item, Mapping)
    ]
    order_intents = [
        dict(item)
        for item in trading_plan.get("order_intents") or []
        if isinstance(item, Mapping)
    ]
    scan_status = str(promoted_scan.get("status") or "unavailable")
    scan_blockers = _strings(promoted_scan.get("blockers"))
    account_blocked_buys = [
        dict(item)
        for item in promoted_scan.get("account_blocked_buys") or []
        if isinstance(item, Mapping)
    ]
    current_blockers = _strings(current_evidence_blockers)
    if not _is_sha256(current_evidence_fingerprint):
        current_blockers.append("current_account_evidence_fingerprint_invalid")
    current_blockers = list(dict.fromkeys(current_blockers))
    plan_blockers = [
        str(item.get("reason") or item.get("code") or "")
        for item in trading_plan.get("blockers") or []
        if isinstance(item, Mapping)
        and str(item.get("reason") or item.get("code") or "")
    ]

    # `status` remains the strict authority state used by the manual-review path.
    # Read-only display tiers below never weaken these fail-closed checks.
    if promoted_scan.get("verified") is not True:
        status = "unavailable"
        reasons = [*scan_blockers, *current_blockers] or [
            "verified_promoted_strategy_scan_unavailable"
        ]
    elif scan_status == "blocked":
        status = "blocked"
        reasons = [*scan_blockers, *current_blockers] or [
            "promoted_strategy_scan_blocked"
        ]
    elif current_blockers:
        status = "blocked"
        reasons = current_blockers
    elif int(trading_plan.get("manual_ready_count") or 0) > 0:
        status = "manual_review_required"
        reasons = ["manual_confirmation_required"]
    elif int(trading_plan.get("paper_shadow_ready_count") or 0) > 0:
        status = "paper_shadow_required"
        reasons = ["paper_shadow_evaluation_required"]
    elif int(trading_plan.get("blocked_count") or 0) > 0:
        status = "blocked"
        reasons = plan_blockers or ["daily_trading_plan_blocked"]
    elif (
        scan_status == "completed_no_signal"
        and promoted_scan.get("normal_no_signal") is True
        and int(promoted_scan.get("selected_signal_count") or 0) == 0
        and not scan_blockers
        and not candidates
        and not order_intents
    ):
        status = "no_action"
        reasons = ["promoted_strategy_scan_completed_without_signal"]
    elif scan_status == "completed_no_signal" and account_blocked_buys:
        status = "blocked"
        reasons = list(
            dict.fromkeys(
                f"account_buy_blocked:{item.get('reason')}"
                for item in account_blocked_buys
                if item.get("reason")
            )
        ) or ["account_buy_candidates_ineligible"]
    elif candidates or order_intents:
        status = "blocked"
        reasons = ["decision_candidates_not_ready_for_manual_review"]
    else:
        status = "unavailable"
        reasons = scan_blockers or ["verified_promoted_strategy_scan_unavailable"]

    summary = _mapping(decision_payload.get("summary"))
    portfolio = _mapping(summary.get("portfolio"))
    account_truth = _mapping(summary.get("account_truth"))
    strategy_bindings = [
        {
            "strategy_id": item.get("strategy_id"),
            "promotion_binding_fingerprint": item.get(
                "order_generation_gate_fingerprint"
            ),
            "qualification_fingerprint": item.get("qualification_fingerprint"),
        }
        for item in promoted_scan.get("strategy_bindings") or []
        if isinstance(item, Mapping)
    ]
    bound_artifacts = {
        str(item.get("strategy_id") or ""): item.get("strategy_artifact_fingerprint")
        for item in promoted_scan.get("strategy_bindings") or []
        if isinstance(item, Mapping)
    }
    contexts = {
        identity: dict(context)
        for identity, context in (strategy_context or {}).items()
        if promoted_scan.get("verified") is True
        and isinstance(context, Mapping)
        and identity in bound_artifacts
        and _is_sha256(context.get("strategy_artifact_fingerprint"))
        and context.get("strategy_id") == identity
        and context.get("strategy_artifact_fingerprint")
        == bound_artifacts.get(identity)
        and context.get("read_only") is True
        and context.get("authorizes_execution") is False
    }
    actual_signals = [
        item for item in promoted_scan.get("signals") or [] if isinstance(item, Mapping)
    ]
    actions = []
    for item in order_intents:
        matches = [
            signal
            for signal in actual_signals
            if signal.get("symbol") == item.get("symbol")
            and signal.get("direction") == item.get("side")
        ]
        signal = matches[0] if len(matches) == 1 else None
        if signal is not None and signal.get("strategy_id") not in contexts:
            signal = None
        actions.append(_action_projection(item, display_name_resolver, signal=signal))
    signal_actions = [
        _signal_projection(item, display_name_resolver)
        for item in promoted_scan.get("signals") or []
        if isinstance(item, Mapping)
    ]
    preview_blockers = _portfolio_preview_blockers(
        summary=summary,
        current_blockers=current_blockers,
    )
    fatal_signal_blockers = [
        item
        for item in scan_blockers
        if item
        in {
            "promoted_strategy_not_configured",
            "promoted_daily_candidate_strategy_missing",
            "full_market_universe_snapshot_missing",
            "verified_market_history_window_incomplete",
            "full_market_daily_receipt_replay_failed",
            "prior_verified_market_date_unavailable",
            "strategy_scan_decision_date_invalid",
            "strategy_scan_decision_date_not_verified_trading_day",
            "portfolio_instrument_type_evidence_missing",
        }
        or item.startswith("promoted_strategy_exit_signal_conflict:")
        or item.startswith("strategy_full_market_truth:")
        or item.startswith("strategy_gate_rejected:")
        or item.startswith("portfolio_instrument_type_unresolved:")
    ]
    signal_ready = (
        promoted_scan.get("verified") is True
        and scan_status in {"completed", "blocked", "prepared"}
        and int(promoted_scan.get("selected_signal_count") or 0) > 0
        and bool(signal_actions)
        and not fatal_signal_blockers
    )
    verified_no_signal = (
        promoted_scan.get("verified") is True
        and scan_status == "completed_no_signal"
        and promoted_scan.get("normal_no_signal") is True
        and int(promoted_scan.get("selected_signal_count") or 0) == 0
        and not scan_blockers
    )
    verified_account_blocked = (
        promoted_scan.get("verified") is True
        and scan_status in {"completed_no_signal", "blocked"}
        and int(promoted_scan.get("selected_signal_count") or 0) == 0
        and bool(account_blocked_buys)
        and not fatal_signal_blockers
    )
    if status == "manual_review_required":
        presentation_level = "manual_review"
    elif verified_no_signal:
        presentation_level = "no_action"
    elif signal_ready and not preview_blockers:
        presentation_level = "portfolio_preview"
    elif signal_ready:
        presentation_level = "signal"
    elif scan_status == "blocked" or verified_account_blocked:
        presentation_level = "blocked"
    else:
        presentation_level = "unavailable"

    configuration_blockers = [
        item
        for item in scan_blockers
        if item
        in {
            "promoted_strategy_not_configured",
            "promoted_daily_candidate_strategy_missing",
        }
    ]
    if (
        "promoted_daily_candidate_strategy_missing" in scan_blockers
        and "promoted_strategy_not_configured" not in configuration_blockers
    ):
        configuration_blockers.append("promoted_strategy_not_configured")
    source_action_task_ids = list(
        dict.fromkeys(
            [
                *_strings(promoted_scan.get("action_task_ids")),
                *[
                    str(item.get("action_id") or "")
                    for item in candidates
                    if str(item.get("action_id") or "")
                ],
            ]
        )
    )
    core = {
        "schema_version": ACCOUNT_ACTION_RECOMMENDATION_SCHEMA_VERSION,
        "decision_date": decision_date or None,
        "status": status,
        "reason_codes": list(dict.fromkeys(reasons)),
        "source_action_task_ids": source_action_task_ids,
        "actions": actions,
        "strategy_context": contexts,
        "presentation": {
            "level": presentation_level,
            "actions": actions
            if presentation_level == "manual_review"
            else signal_actions,
            "signal_status": (
                "ready"
                if signal_ready
                else "no_signal"
                if verified_no_signal
                else "account_blocked"
                if verified_account_blocked
                else "unavailable"
            ),
            "portfolio_preview_status": (
                "ready" if signal_ready and not preview_blockers else "blocked"
            ),
            "manual_review_status": (
                "ready" if status == "manual_review_required" else "blocked"
            ),
            "configuration_blockers": configuration_blockers,
            "signal_blockers": []
            if signal_ready or verified_no_signal
            else scan_blockers,
            "portfolio_preview_blockers": preview_blockers,
            "manual_review_blockers": (
                []
                if status == "manual_review_required"
                else list(dict.fromkeys([*reasons, *plan_blockers]))
            ),
            "read_only": True,
            "authorizes_execution": False,
        },
        "promoted_scan": {
            "run_id": promoted_scan.get("run_id"),
            "status": scan_status,
            "input_fingerprint": promoted_scan.get("input_fingerprint"),
            "output_fingerprint": promoted_scan.get("output_fingerprint"),
            "selected_signal_count": int(
                promoted_scan.get("selected_signal_count") or 0
            ),
            "raw_signal_count": int(promoted_scan.get("raw_signal_count") or 0),
            "account_blocked_buys": account_blocked_buys,
        },
        "current_evidence_fingerprint": current_evidence_fingerprint or None,
        "strategy_bindings": strategy_bindings,
        "account_evidence": {
            "valuation_snapshot_id": portfolio.get("valuation_snapshot_id"),
            "ledger_cutoff_id": portfolio.get("ledger_cutoff_id"),
            "quote_set_fingerprint": portfolio.get("quote_set_fingerprint"),
            "valuation_status": portfolio.get("valuation_status") or "missing",
            "account_truth_status": account_truth.get("gate_status") or "blocked",
            "account_qualification_status": (
                "passed"
                if strategy_bindings
                and promoted_scan.get("verified") is True
                and not current_blockers
                else "blocked"
            ),
            "account_positions_evaluated": (
                promoted_scan.get("verified") is True
                and scan_status in {"completed", "completed_no_signal"}
                and not current_blockers
            ),
        },
        "read_only": True,
        "manual_confirmation_required": True,
        "creates_oms_order": False,
        "submits_broker_order": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "authority_effect": "none",
    }
    return {**core, "evidence_fingerprint": "sha256:" + content_fingerprint(core)}


def _portfolio_preview_blockers(
    *,
    summary: Mapping[str, Any],
    current_blockers: Sequence[str],
) -> list[str]:
    """Require coherent account structure, but not execution-grade clock freshness."""

    portfolio = _mapping(summary.get("portfolio"))
    account_truth = _mapping(summary.get("account_truth"))
    blockers: list[str] = []
    if str(portfolio.get("valuation_status") or "").lower() != "complete":
        blockers.append("portfolio_preview_valuation_not_complete")
    if str(account_truth.get("reconciliation_status") or "").lower() != "pass":
        blockers.append("portfolio_preview_reconciliation_not_pass")
    if _nonnegative_int(account_truth.get("unresolved_mismatch_count")) != 0:
        blockers.append("portfolio_preview_unresolved_mismatch")
    if _mapping(account_truth.get("ledger_coverage")).get("status") != "covered":
        blockers.append("portfolio_preview_ledger_coverage_not_complete")
    if not str(account_truth.get("import_run_id") or ""):
        blockers.append("portfolio_preview_import_run_missing")
    if not _is_sha256(account_truth.get("source_fingerprint")):
        blockers.append("portfolio_preview_source_fingerprint_invalid")

    structural_markers = (
        "contract_invalid",
        "fingerprint_invalid",
        "date_mismatch",
        "date_missing",
        "portfolio_changed",
        "unresolved_mismatch",
        "reconciliation_not_pass",
        "ledger_coverage_not_complete",
        "valuation_snapshot_not_complete",
        "ledger_cutoff_id_invalid",
        "after_decision_generation",
        "plan_generated_before_decision",
    )
    blockers.extend(
        blocker
        for blocker in current_blockers
        if any(marker in blocker for marker in structural_markers)
    )
    return list(dict.fromkeys(blockers))


def _action_display_name(
    item: Mapping[str, Any],
    resolver: Callable[[str, str | None], str] | None,
) -> str | None:
    symbol = str(item.get("symbol") or "")
    name = item.get("display_name") or item.get("name")
    if name and name != symbol:
        return str(name)
    if resolver is not None and symbol:
        return resolver(symbol, item.get("asset_class"))
    return str(name) if name else None


def _signal_projection(
    signal: Mapping[str, Any],
    display_name_resolver: Callable[[str, str | None], str] | None,
) -> dict[str, Any]:
    display_name = _action_display_name(signal, display_name_resolver)
    projected = {
        "action_id": None,
        "symbol": signal.get("symbol"),
        "display_name": display_name,
        "name": display_name,
        "asset_class": signal.get("asset_class") or "stock",
        "side": signal.get("direction"),
        "target_weight": signal.get("target_weight"),
        "estimated_quantity": None,
        "submission_status": "read_only_signal",
        "strategy_id": signal.get("strategy_id"),
        "frozen_market_date": signal.get("frozen_market_date"),
    }
    price = signal.get("frozen_close") or signal.get("price")
    if price is not None:
        projected["estimated_price"] = price
    return projected


def _action_projection(
    intent: Mapping[str, Any],
    display_name_resolver: Callable[[str, str | None], str] | None,
    *,
    signal: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    display_name = _action_display_name(intent, display_name_resolver)
    projected = {
        "action_id": intent.get("action_id"),
        "symbol": intent.get("symbol"),
        "display_name": display_name,
        "name": display_name,
        "asset_class": intent.get("asset_class"),
        "side": intent.get("side"),
        "target_weight": intent.get("target_weight"),
        "estimated_quantity": intent.get("estimated_quantity"),
        "submission_status": intent.get("submission_status"),
        "strategy_id": signal.get("strategy_id") if signal is not None else None,
        "frozen_market_date": (
            signal.get("frozen_market_date") if signal is not None else None
        ),
    }
    price = intent.get("estimated_price") or intent.get("market_quote_price")
    if price is not None:
        projected["estimated_price"] = price
    if intent.get("estimated_gross_amount") is not None:
        projected["estimated_gross_amount"] = intent.get("estimated_gross_amount")
    if intent.get("estimated_net_cash_impact") is not None:
        projected["estimated_net_cash_impact"] = intent.get("estimated_net_cash_impact")
    if intent.get("estimated_total_fee") is not None:
        projected["estimated_total_fee"] = intent.get("estimated_total_fee")
    return projected


def _scan_semantic_blockers(payload: Mapping[str, Any]) -> list[str]:
    status = str(payload.get("status") or "")
    blockers = _strings(payload.get("blockers"))
    selected_count = _nonnegative_int(payload.get("selected_signal_count"))
    raw_count = _nonnegative_int(payload.get("raw_signal_count"))
    blocked_buys = [
        item
        for item in payload.get("account_blocked_buys") or []
        if isinstance(item, Mapping)
    ]
    action_tasks = [
        item for item in payload.get("action_tasks") or [] if isinstance(item, Mapping)
    ]
    strategy_bindings = [
        item
        for item in payload.get("strategy_bindings") or []
        if isinstance(item, Mapping)
    ]
    portfolio_binding = _mapping(payload.get("portfolio_binding"))
    violations: list[str] = []
    if status not in {"blocked", "completed", "completed_no_signal"}:
        violations.append("promoted_strategy_scan_terminal_status_invalid")
    if status == "blocked" and (not blockers or action_tasks):
        violations.append("promoted_strategy_scan_blocked_shape_invalid")
    if status == "completed" and (
        blockers
        or selected_count is None
        or selected_count <= 0
        or len(action_tasks) != selected_count
    ):
        violations.append("promoted_strategy_scan_completed_shape_invalid")
    if status == "completed_no_signal" and (
        blockers
        or selected_count != 0
        or action_tasks
        or (payload.get("normal_no_signal") is True) != (raw_count == 0)
        or (raw_count is not None and raw_count > 0 and not blocked_buys)
        or not strategy_bindings
    ):
        violations.append("promoted_strategy_scan_no_action_shape_invalid")
    if status != "completed_no_signal" and payload.get("normal_no_signal") is True:
        violations.append("promoted_strategy_scan_no_action_flag_invalid")
    if raw_count is None:
        violations.append("promoted_strategy_scan_raw_signal_count_invalid")
    raw_signals = payload.get("raw_signals")
    if isinstance(raw_signals, list) and len(raw_signals) != raw_count:
        violations.append("promoted_strategy_scan_raw_signal_count_mismatch")
    if any(
        not str(item.get("symbol") or "")
        or str(item.get("reason") or "")
        not in {
            "board_permission_unknown",
            "board_permission_disabled",
            "unsupported_trade_unit",
            "cash_evidence_missing",
            "insufficient_cash_for_one_lot",
            "frozen_price_invalid",
        }
        for item in blocked_buys
    ):
        violations.append("promoted_strategy_scan_account_blocked_buy_invalid")
    if status in {"completed", "completed_no_signal"}:
        receipt_fingerprints = _strings(payload.get("receipt_fingerprints"))
        if (
            not str(payload.get("market_date") or "")
            or not str(payload.get("market_universe_snapshot_id") or "")
            or not receipt_fingerprints
            or any(not _is_prefixed_sha256(item) for item in receipt_fingerprints)
            or not _is_prefixed_sha256(payload.get("evaluation_policy_fingerprint"))
            or not _is_prefixed_sha256(payload.get("signal_selection_fingerprint"))
            or not _is_prefixed_sha256(payload.get("safety_gate_fingerprint"))
        ):
            violations.append("promoted_strategy_scan_market_binding_invalid")
        strategy_ids = [
            str(item.get("strategy_id") or "") for item in strategy_bindings
        ]
        if (
            not strategy_ids
            or any(not item for item in strategy_ids)
            or len(strategy_ids) != len(set(strategy_ids))
        ):
            violations.append("promoted_strategy_scan_strategy_bindings_invalid")
        for item in strategy_bindings:
            if (
                not _is_sha256(item.get("strategy_artifact_fingerprint"))
                or not _is_prefixed_sha256(
                    item.get("order_generation_gate_fingerprint")
                )
                or not _is_prefixed_sha256(item.get("universe_truth_fingerprint"))
                or (
                    item.get("qualification_fingerprint") is not None
                    and not _is_sha256(item.get("qualification_fingerprint"))
                )
            ):
                violations.append(
                    "promoted_strategy_scan_strategy_binding_fingerprint_invalid"
                )
                break
        if (
            portfolio_binding.get("valuation_status") != "complete"
            or not str(portfolio_binding.get("valuation_snapshot_id") or "")
            or not _is_prefixed_sha256(portfolio_binding.get("held_symbol_fingerprint"))
            or _nonnegative_int(portfolio_binding.get("held_stock_count")) is None
            or not _is_prefixed_sha256(
                portfolio_binding.get("capital_constraint_fingerprint")
            )
        ):
            violations.append("promoted_strategy_scan_portfolio_binding_invalid")
    if status == "completed" and any(
        _nonnegative_int(item.get("action_id")) in {None, 0} for item in action_tasks
    ):
        violations.append("promoted_strategy_scan_action_task_identity_invalid")
    return violations


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized >= 0 else None


def _unavailable_scan(
    reason: str,
    *,
    blockers: Sequence[str] | None = None,
) -> dict[str, Any]:
    return {
        "decision_date": None,
        "market_date": None,
        "status": "unavailable",
        "run_id": None,
        "started_at": None,
        "input_fingerprint": None,
        "output_fingerprint": None,
        "selected_signal_count": 0,
        "signals": [],
        "normal_no_signal": False,
        "raw_signal_count": 0,
        "raw_signals": [],
        "account_blocked_buys": [],
        "blockers": list(dict.fromkeys(blockers or [reason])),
        "strategy_bindings": [],
        "portfolio_binding": {},
        "market_universe_snapshot_id": None,
        "receipt_fingerprints": [],
        "safety_gate_fingerprint": None,
        "action_task_ids": [],
        "verified": False,
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _scan_started_at_blockers(value: Any, decision_date: str) -> list[str]:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return ["promoted_strategy_scan_started_at_invalid"]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local = parsed.astimezone(ZoneInfo("Asia/Shanghai"))
    blockers: list[str] = []
    if local.date().isoformat() != decision_date:
        blockers.append("promoted_strategy_scan_started_at_date_mismatch")
    local_time = local.time().replace(tzinfo=None)
    if not time(9, 35) <= local_time < time(9, 45):
        blockers.append("promoted_strategy_scan_started_at_outside_reviewed_window")
    return blockers


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strings(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [str(item) for item in value if str(item)]


def _is_sha256(value: Any) -> bool:
    normalized = str(value or "")
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized.lower()
    )


def _is_prefixed_sha256(value: Any) -> bool:
    normalized = str(value or "")
    return normalized.startswith("sha256:") and _is_sha256(
        normalized.removeprefix("sha256:")
    )


__all__ = [
    "ACCOUNT_ACTION_RECOMMENDATION_SCHEMA_VERSION",
    "build_account_action_recommendation",
    "resolve_account_strategy_context",
    "resolve_historical_research_comparison",
    "resolve_latest_verified_promoted_strategy_scan",
]
