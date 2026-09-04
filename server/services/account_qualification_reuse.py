"""Read-only identity gates for deterministic account-qualification reuse."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from analytics.research_account_capital_evidence import (
    is_valid_passed_research_account_capital_evidence,
)
from analytics.strategy_advancement_gate import strategy_advancement_backtest_view
from server.ai_runtime.strategy_research_privacy import (
    NORMALIZED_RESEARCH_NOTIONAL,
    NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID,
)
from server.contracts.ai_shadow_research_qualification import (
    SHADOW_RESEARCH_QUALIFICATION_TERMINAL_STATUSES,
    ShadowResearchQualificationRejected,
)
from server.contracts.content_identity import content_fingerprint
from server.contracts.strategy_research import StrategyResearchSelection
from server.services.ai_shadow_research_qualification_support import (
    QUALIFICATION_COMPARISON_SCHEMA,
    QUALIFICATION_NOTIONAL_POLICY_ID,
    FrozenQualificationSource,
    account_total_equity,
    call_maybe_async,
    formula_binding,
    money_text,
    public_result,
    qualification_initial_cash,
    qualification_selection,
    require_complete_valuation,
    require_current_valuation_trade_date,
    valid_fingerprint,
    valuation_fingerprint,
)
from server.services.ai_shadow_research_support import (
    shadow_research_backtest_source_fingerprint,
    shadow_research_market_close_as_of,
)
from server.services.reviewed_fee_schedule_policy import REVIEWED_COST_MODEL_PREFIX


def require_qualification_source_run_id(value: Any) -> str:
    source_run_id = str(value or "").strip()
    if (
        not source_run_id
        or len(source_run_id) > 160
        or any(not (char.isalnum() or char in "._:-") for char in source_run_id)
    ):
        raise ShadowResearchQualificationRejected("qualification_source_run_id_invalid")
    return source_run_id


def select_oldest_retryable_source_run_id(
    daily_artifact_store: Any,
    qualification_store: Any,
) -> str:
    pairs = daily_artifact_store.list_verified_research_artifact_pairs()
    if not isinstance(pairs, list) or not pairs:
        raise ShadowResearchQualificationRejected(
            "qualification_verified_source_backlog_empty"
        )
    for pair in pairs:
        run_id = require_qualification_source_run_id(pair.get("run_id"))
        runs = qualification_store.list_qualification_runs(
            limit=200,
            source_run_id=run_id,
        )
        latest = _latest_valid_qualification_run(runs)
        if (
            latest is None
            or latest.get("status")
            not in SHADOW_RESEARCH_QUALIFICATION_TERMINAL_STATUSES
        ):
            return run_id
    return require_qualification_source_run_id(pairs[-1].get("run_id"))


def _latest_valid_qualification_run(
    runs: Any,
) -> Mapping[str, Any] | None:
    if not isinstance(runs, list) or not runs:
        return None
    valid: list[tuple[datetime, str, Mapping[str, Any]]] = []
    allowed = {*SHADOW_RESEARCH_QUALIFICATION_TERMINAL_STATUSES, "running"}
    for run in runs:
        if not isinstance(run, Mapping) or run.get("status") not in allowed:
            continue
        try:
            updated = datetime.fromisoformat(
                str(run.get("updated_at") or "").replace("Z", "+00:00")
            )
        except ValueError:
            continue
        if updated.tzinfo is None or updated.utcoffset() is None:
            continue
        valid.append(
            (
                updated,
                str(run.get("qualification_run_id") or ""),
                run,
            )
        )
    if not valid:
        raise ShadowResearchQualificationRejected(
            "qualification_history_latest_state_invalid"
        )
    return max(valid, key=lambda item: (item[0], item[1]))[2]


def require_normalized_source_selection(
    batch: Mapping[str, Any],
    source: Mapping[str, Any],
    selection: StrategyResearchSelection,
) -> None:
    expected = batch.get("source_research_selection")
    actual = {
        "schema_version": "karkinos.ai.normalized_source_selection_binding.v1",
        "universe": list(selection.universe),
        "asset_classes": list(selection.asset_classes),
        "asset_class_policy": "daily_candidate_stock_only",
        "dataset_snapshot_id": selection.dataset_snapshot_id,
        "start_date": selection.start_date,
        "end_date": selection.end_date,
        "frequency": selection.frequency,
        "initial_cash": selection.initial_cash,
        "notional_policy_id": NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID,
        "cost_model_reference": selection.cost_model_reference,
        "account_fact_binding": "not_applicable_strategy_only_research",
        "saved_backtest_result_id": None,
        "saved_backtest_result_id_status": ("not_present_in_privacy_minimized_backup"),
        "contains_private_account_identifiers": False,
        "authority_effect": "research_only",
    }
    if (
        actual != expected
        or selection.has_account_binding
        or selection.initial_cash != NORMALIZED_RESEARCH_NOTIONAL
        or any(item != "stock" for item in selection.asset_classes)
        or selection.saved_backtest_result_id
        != int(source.get("baseline_result_id") or 0)
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_source_selection_binding_invalid"
        )


def require_current_qualification_valuation(
    snapshot: Any,
    *,
    batch: Mapping[str, Any],
    db: Any,
    clock: Callable[[], Any],
    latest_closed_market_date_reader: Callable[[Any, Any], str | None],
) -> dict[str, Any]:
    valuation = require_complete_valuation(snapshot, db)
    require_current_valuation_trade_date(
        valuation,
        source_market_date=batch.get("market_date"),
        latest_closed_market_date_reader=latest_closed_market_date_reader,
        db=db,
        clock=clock,
    )
    return valuation


def resolve_qualification_stock_fee_schedule(
    resolver: Callable[..., Any],
    selection: StrategyResearchSelection,
) -> Any:
    resolution = resolver(
        start_date=selection.start_date,
        end_date=selection.end_date,
        universe=selection.universe,
        asset_classes=selection.asset_classes,
        account_truth_as_of=None,
    )
    evidence = getattr(resolution, "fee_evidence", None)
    if (
        not isinstance(evidence, Mapping)
        or evidence.get("account_specific") is not True
        or evidence.get("broker_statement_reconciled") is not True
        or evidence.get("fee_schedule_reviewed_asset_classes") != ["stock"]
        or evidence.get("fee_notional_covered_asset_classes") != ["stock"]
        or not valid_fingerprint(evidence.get("fee_schedule_fingerprint"))
        or not valid_fingerprint(evidence.get("account_truth_source_fingerprint"))
        or not valid_fingerprint(evidence.get("account_truth_scope_fingerprint"))
        or not str(getattr(resolution, "cost_model_reference", "")).strip()
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_reviewed_stock_fee_schedule_invalid"
        )
    return resolution


async def reusable_terminal_qualification_result(
    *,
    db: Any,
    store: Any,
    batch: Mapping[str, Any],
    sources: Sequence[FrozenQualificationSource],
    valuation: Mapping[str, Any],
    account_evidence_reader: Callable[[str], Any] | None,
    reviewed_fee_identity_reader: Callable[[StrategyResearchSelection], Any] | None,
    dataset_snapshot_replay_reader: Callable[[Mapping[str, Any]], Any] | None,
    advancement_gate_builder: Callable[..., Any],
) -> dict[str, Any] | None:
    """Reuse only after a read-only replay of every mutable input identity."""

    if (
        account_evidence_reader is None
        or reviewed_fee_identity_reader is None
        or dataset_snapshot_replay_reader is None
    ):
        return None
    runs = await asyncio.to_thread(
        store.list_qualification_runs,
        limit=200,
        source_run_id=str(batch["run_id"]),
    )
    terminal_runs = [
        run
        for run in runs
        if run.get("status") in SHADOW_RESEARCH_QUALIFICATION_TERMINAL_STATUSES
        and _run_source_and_valuation_match(
            run,
            batch=batch,
            valuation=valuation,
        )
    ]
    if not terminal_runs:
        return None
    try:
        fee_status = await call_maybe_async(
            lambda: reviewed_fee_identity_reader(sources[0].source_selection)
        )
    except Exception:
        return None
    for run in terminal_runs:
        try:
            record = await call_maybe_async(
                lambda run=run: account_evidence_reader(
                    str(run["account_evidence_reference"])
                )
            )
            if not _account_evidence_matches(
                record,
                run=run,
                valuation=valuation,
            ) or not _reviewed_fee_identity_matches(
                fee_status,
                run=run,
                selection=sources[0].source_selection,
            ):
                continue
            baseline = await db.get_backtest_result(int(run["baseline_result_id"]))
            if not await _baseline_identity_matches(
                baseline,
                run=run,
                selection=sources[0].source_selection,
                dataset_snapshot_replay_reader=dataset_snapshot_replay_reader,
            ):
                continue
            candidates = await asyncio.to_thread(
                store.list_qualification_candidates,
                str(run["qualification_run_id"]),
            )
            if not await _terminal_candidate_set_matches(
                db=db,
                run=run,
                batch=batch,
                sources=sources,
                candidates=candidates,
                baseline=baseline,
                advancement_gate_builder=advancement_gate_builder,
            ):
                continue
        except Exception:
            continue
        return await asyncio.to_thread(public_result, store, run, True)
    return None


async def _terminal_candidate_set_matches(
    *,
    db: Any,
    run: Mapping[str, Any],
    batch: Mapping[str, Any],
    sources: Sequence[FrozenQualificationSource],
    candidates: Any,
    baseline: Mapping[str, Any],
    advancement_gate_builder: Callable[..., Any],
) -> bool:
    if (
        len(sources) != 5
        or not isinstance(candidates, list)
        or len(candidates) != 5
        or run.get("status") != "completed"
    ):
        return False
    source_by_id = {
        str(source.source_candidate["candidate_id"]): source for source in sources
    }
    if set(source_by_id) != {
        str(candidate.get("source_candidate_id") or "") for candidate in candidates
    }:
        return False
    baseline_view = strategy_advancement_backtest_view(baseline)
    baseline_fingerprint = shadow_research_backtest_source_fingerprint(baseline)
    initial_cash = Decimal(str(run.get("initial_cash_text")))
    validated: list[Mapping[str, Any]] = []
    for candidate in candidates:
        source = source_by_id[str(candidate["source_candidate_id"])]
        result = await db.get_backtest_result(
            int(candidate.get("candidate_result_id") or 0)
        )
        if not isinstance(result, Mapping):
            return False
        comparison = candidate.get("comparison")
        if not isinstance(comparison, Mapping):
            return False
        candidate_view = strategy_advancement_backtest_view(result)
        qualified_selection = StrategyResearchSelection(
            saved_backtest_result_id=int(run["baseline_result_id"]),
            universe=source.source_selection.universe,
            asset_classes=source.source_selection.asset_classes,
            dataset_snapshot_id=source.source_selection.dataset_snapshot_id,
            start_date=source.source_selection.start_date,
            end_date=source.source_selection.end_date,
            frequency=source.source_selection.frequency,
            initial_cash=float(initial_cash),
            cost_model_reference=str(run["reviewed_cost_model_reference"]),
            account_truth_freshness_as_of=shadow_research_market_close_as_of(
                source.source_selection.end_date,
                "15:30",
            ).isoformat(),
            valuation_snapshot_id=str(run["valuation_snapshot_id"]),
            ledger_cutoff_id=int(run["ledger_cutoff_id"]),
        )
        expected_gate = advancement_gate_builder(
            baseline=baseline_view,
            candidate=candidate_view,
            critique_evidence={
                "status": "completed",
                "critique_id": source.source_critique["critique_id"],
                "artifact_fingerprint": source.source_critique["artifact_fingerprint"],
            },
        ).to_json_dict()
        expected_status = (
            "qualified" if expected_gate.get("status") == "pass" else "blocked"
        )
        expected_recommendation = (
            "paper_shadow_review"
            if expected_status == "qualified"
            else "keep_researching"
        )
        expected_deltas = {
            "total_return": candidate_view["total_return"]
            - baseline_view["total_return"],
            "sharpe": candidate_view["sharpe"] - baseline_view["sharpe"],
            "max_drawdown": candidate_view["max_drawdown"]
            - baseline_view["max_drawdown"],
            "total_cost": candidate_view["total_cost"] - baseline_view["total_cost"],
        }
        qualified_draft = dict(source.source_draft)
        qualified_draft["cost_model_reference"] = str(
            run["reviewed_cost_model_reference"]
        )
        qualified_draft["formula_fingerprint"] = formula_binding(
            qualified_selection,
            qualified_draft,
        ).fingerprint
        account_capital = comparison.get("account_capital_constraint")
        expected_comparison = {
            "schema_version": QUALIFICATION_COMPARISON_SCHEMA,
            "baseline_source_fingerprint": baseline_fingerprint,
            "candidate_source_fingerprint": (
                shadow_research_backtest_source_fingerprint(result)
            ),
            "source_run_id": source.source_candidate["run_id"],
            "source_candidate_id": source.source_candidate["candidate_id"],
            "source_draft_id": source.source_candidate["draft_id"],
            "source_selection_fingerprint": source.source_selection.fingerprint,
            "qualified_selection_fingerprint": qualified_selection.fingerprint,
            "source_strategy_artifact_fingerprint": source.verified[
                "strategy_artifact_fingerprint"
            ],
            "source_formula_semantic_fingerprint": source.semantic_fingerprint,
            "qualified_formula_semantic_fingerprint": source.semantic_fingerprint,
            "baseline": baseline_view,
            "candidate": candidate_view,
            "deltas": expected_deltas,
            "deepseek_critique": dict(source.source_critique["artifact"]),
            "critique_reuse_scope": ("formula_semantics_only_frozen_source_evidence"),
            "research_capital_mode": "account_bound",
            "account_qualification_status": (
                "passed" if expected_status == "qualified" else "blocked"
            ),
            "account_capital_constraint": account_capital,
            "initial_cash_policy": {
                "policy_id": QUALIFICATION_NOTIONAL_POLICY_ID,
                "normalized_notional_policy_id": (
                    NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID
                ),
                "rule": "minimum_of_normalized_notional_and_reconciled_total_equity",
                "research_initial_cash": money_text(initial_cash),
            },
            "iteration_lineage": dict(
                source.source_candidate["comparison"]["iteration_lineage"]
            ),
            "recommendation": expected_recommendation,
            "promotion_gate": expected_gate,
            "provider_call_performed": False,
            "automatic_strategy_replacement_enabled": False,
            "production_strategy_mutation_enabled": False,
            "broker_order_created": False,
            "broker_submission_enabled": False,
            "capital_authority_granted": False,
            "authority_effect": "research_only",
        }
        if (
            candidate.get("qualification_run_id") != run.get("qualification_run_id")
            or candidate.get("source_draft_id")
            != source.source_candidate.get("draft_id")
            or candidate.get("source_formula_fingerprint")
            != source.source_draft.get("formula_fingerprint")
            or candidate.get("qualified_formula_fingerprint")
            != qualified_draft.get("formula_fingerprint")
            or candidate.get("source_formula_semantic_fingerprint")
            != source.semantic_fingerprint
            or candidate.get("qualified_formula_semantic_fingerprint")
            != source.semantic_fingerprint
            or candidate.get("status") != expected_status
            or candidate.get("recommendation") != expected_recommendation
            or int(candidate.get("rank") or 0)
            != int(source.verified.get("iteration_number") or 0)
            or content_fingerprint(comparison)
            != candidate.get("comparison_fingerprint")
            or comparison != expected_comparison
            or not is_valid_passed_research_account_capital_evidence(
                account_capital,
                expected_initial_cash=initial_cash,
                expected_valuation_snapshot_id=run.get("valuation_snapshot_id"),
                expected_ledger_cutoff_id=run.get("ledger_cutoff_id"),
            )
        ):
            return False
        validated.append(candidate)
    terminal = qualification_selection(
        qualification_run_id=str(run["qualification_run_id"]),
        source_run_id=str(batch["run_id"]),
        market_date=str(batch["market_date"]),
        candidates=validated,
        replay_failed=False,
    )
    return bool(
        terminal["run_status"] == run.get("status")
        and terminal["selection"] == run.get("selection")
        and terminal["blockers"] == run.get("blockers")
        and terminal["failure_code"] == run.get("failure_code")
    )


def _run_source_and_valuation_match(
    run: Mapping[str, Any],
    *,
    batch: Mapping[str, Any],
    valuation: Mapping[str, Any],
) -> bool:
    return bool(
        run.get("source_run_id") == batch.get("run_id")
        and run.get("market_date") == batch.get("market_date")
        and run.get("source_selection_id") == batch.get("selection_id")
        and run.get("source_selection_fingerprint")
        == batch.get("selection_fingerprint")
        and run.get("source_backup_fingerprint")
        == batch.get("backup_artifact_fingerprint")
        and run.get("valuation_snapshot_id") == valuation.get("snapshot_id")
        and run.get("valuation_snapshot_fingerprint")
        == valuation_fingerprint(str(valuation.get("snapshot_id") or ""))
        and int(run.get("ledger_cutoff_id") or 0)
        == int(valuation.get("ledger_cutoff_id") or 0)
        and run.get("ledger_fingerprint") == valuation.get("ledger_fingerprint")
    )


def _record_field(record: Any, field: str) -> Any:
    return (
        record.get(field)
        if isinstance(record, Mapping)
        else getattr(record, field, None)
    )


def _account_evidence_matches(
    record: Any,
    *,
    run: Mapping[str, Any],
    valuation: Mapping[str, Any],
) -> bool:
    if (
        _record_field(record, "reference_id") != run.get("account_evidence_reference")
        or _record_field(record, "tool_name") != "account_state_projection.read"
        or _record_field(record, "status") != "complete"
        or _record_field(record, "authoritative") is not True
        or _record_field(record, "persisted_facts_only") is not True
        or _record_field(record, "valuation_snapshot_id")
        != valuation.get("snapshot_id")
        or int(_record_field(record, "ledger_cutoff_id") or 0)
        != int(valuation.get("ledger_cutoff_id") or 0)
        or _record_field(record, "ledger_fingerprint")
        != valuation.get("ledger_fingerprint")
        or _record_field(record, "record_fingerprint")
        != run.get("account_evidence_fingerprint")
    ):
        return False
    total_equity = account_total_equity(_record_field(record, "payload"), valuation)
    return money_text(qualification_initial_cash(total_equity)) == run.get(
        "initial_cash_text"
    )


def _reviewed_fee_identity_matches(
    value: Any,
    *,
    run: Mapping[str, Any],
    selection: StrategyResearchSelection,
) -> bool:
    if not isinstance(value, Mapping):
        return False
    review = value.get("review")
    if not isinstance(review, Mapping):
        return False
    preview = review.get("preview")
    review_fingerprint = str(review.get("review_fingerprint") or "")
    expected_reference = (
        REVIEWED_COST_MODEL_PREFIX
        + str(review.get("review_id") or "")
        + ":"
        + review_fingerprint.removeprefix("sha256:")
    )
    return bool(
        value.get("status") == "active"
        and value.get("persisted_facts_only") is True
        and value.get("provider_contacted") is False
        and value.get("database_writes_performed") is False
        and review.get("decision") == "accepted"
        and valid_fingerprint(review_fingerprint)
        and expected_reference == run.get("reviewed_cost_model_reference")
        and review.get("schedule_fingerprint")
        == run.get("reviewed_fee_schedule_fingerprint")
        and review.get("account_truth_source_fingerprint")
        == run.get("account_truth_source_fingerprint")
        and review.get("account_truth_scope_fingerprint")
        == run.get("account_truth_scope_fingerprint")
        and str(review.get("effective_start_date") or "") <= selection.start_date
        and str(review.get("effective_end_date") or "") >= selection.end_date
        and isinstance(preview, Mapping)
        and preview.get("reviewed_asset_classes") == ["stock"]
    )


async def _baseline_identity_matches(
    baseline: Any,
    *,
    run: Mapping[str, Any],
    selection: StrategyResearchSelection,
    dataset_snapshot_replay_reader: Callable[[Mapping[str, Any]], Any],
) -> bool:
    if not isinstance(baseline, Mapping):
        return False
    view = strategy_advancement_backtest_view(baseline)
    fees = view.get("fee_component_evidence")
    if not isinstance(fees, Mapping):
        return False
    fee_binding = fees.get("fee_schedule_binding")
    metrics = baseline.get("metrics", baseline.get("metrics_json"))
    if isinstance(metrics, str):
        try:
            metrics = json.loads(metrics)
        except json.JSONDecodeError:
            return False
    snapshot = metrics.get("dataset_snapshot") if isinstance(metrics, Mapping) else None
    replay = await call_maybe_async(lambda: dataset_snapshot_replay_reader(snapshot))
    return bool(
        int(baseline.get("id") or 0) == int(run.get("baseline_result_id") or 0)
        and Decimal(str(view.get("initial_cash")))
        == Decimal(str(run.get("initial_cash_text")))
        and view.get("dataset_snapshot_id") == selection.dataset_snapshot_id
        and view.get("dataset_quality_status") == "ok"
        and isinstance(replay, Mapping)
        and replay.get("status") == "pass"
        and replay.get("snapshot_id") == selection.dataset_snapshot_id
        and fees.get("cost_model_reference") == run.get("reviewed_cost_model_reference")
        and fees.get("fee_schedule_fingerprint")
        == run.get("reviewed_fee_schedule_fingerprint")
        and fees.get("account_specific") is True
        and fees.get("broker_statement_reconciled") is True
        and isinstance(fee_binding, Mapping)
        and fee_binding.get("account_truth_source_fingerprint")
        == run.get("account_truth_source_fingerprint")
        and fee_binding.get("account_truth_scope_fingerprint")
        == run.get("account_truth_scope_fingerprint")
    )


__all__ = [
    "require_current_qualification_valuation",
    "require_normalized_source_selection",
    "require_qualification_source_run_id",
    "resolve_qualification_stock_fee_schedule",
    "reusable_terminal_qualification_result",
    "select_oldest_retryable_source_run_id",
]
